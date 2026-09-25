import importlib.util
import os
from datetime import date, timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


def _migration(version):
    path = os.path.join(os.path.dirname(__file__), '..', 'migrations', version, 'post-migration.py')
    spec = importlib.util.spec_from_file_location('mig_' + version.replace('.', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestPhase1011Fixes(TransactionCase):
    """Phase 10.1.1 - Y2 termination truncation, Y3 migration occupancy resync, Y4 lifecycle-link
    guards and frozen invoiced coverage. Guard tests run as a real, restricted branch manager -
    the TransactionCase superuser would bypass exactly what they verify."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        E = cls.env
        cls.branch = E['edara.branch'].create({'name': 'P111 Branch', 'code': 'P111B'})
        cls.property = E['edara.property'].create({'name': 'P111 Property', 'code': 'P111P', 'branch_id': cls.branch.id})
        cls.building = E['edara.building'].create({'name': 'P111 Building', 'code': 'P111BL', 'property_id': cls.property.id})
        cls.tenant = E['res.partner'].create({'name': 'P111 Tenant'})
        cls.manager = new_test_user(E, login='p111_bm', groups='property_managment.group_edara_branch_manager')
        cls.branch.user_ids = [Command.link(cls.manager.id)]
        E.company.edara_rental_income_account_id = E['account.account'].create(
            {'name': 'P111 Rent', 'code': '411100', 'account_type': 'income'}).id
        cls.today = date.today()
        cls._n = 0

    # ---------------- helpers ----------------
    def _unit(self):
        type(self)._n += 1
        return self.env['edara.unit'].create(
            {'name': 'P111-%d' % self._n, 'code': 'P111U%d' % self._n, 'building_id': self.building.id})

    def _contract(self, start, end, rent=1000, freq='monthly', unit=None, **kw):
        vals = {'unit_id': (unit or self._unit()).id, 'tenant_id': self.tenant.id, 'start_date': start,
                'end_date': end, 'rent_amount': rent, 'billing_frequency': freq, 'deposit_required': False}
        vals.update(kw)
        return self.env['edara.lease.contract'].create(vals)

    def _at(self, day):
        return patch.object(fields.Date, 'context_today', staticmethod(lambda record, timestamp=None: day))

    def _terminate_on(self, contract, day):
        with self._at(day):
            contract.action_terminate(reason='P111')

    def _assert_no_overlap(self, unit):
        periods = sorted((l.period_start, l.period_end) for l in
                         self.env['edara.payment.schedule.line'].search([('unit_id', '=', unit.id)])
                         if l.period_start)
        for (s1, e1), (s2, e2) in zip(periods, periods[1:]):
            self.assertLessEqual(e1, s2, "overlapping schedule periods %s / %s" % ((s1, e1), (s2, e2)))

    # ================= Y2: termination truncation =================

    def test_mid_month_termination_cuts_the_line_and_reprices_it(self):
        contract = self._contract(date(2026, 9, 1), date(2026, 10, 31))
        with self._at(date(2026, 9, 20)):
            contract.action_activate()
        self.assertEqual(len(contract.schedule_line_ids), 2)
        self._terminate_on(contract, date(2026, 9, 20))
        (line,) = contract.schedule_line_ids
        self.assertEqual((line.period_start, line.period_end, line.period_last_day), (date(2026, 9, 1), date(2026, 9, 21), date(2026, 9, 20)))
        self.assertEqual((line.occupied_days, line.is_prorated), (20, True))
        self.assertEqual(line.amount, 666.67)                                   # 1,000 x 20/30, canonical engine
        self.assertIn('2026-09-20', line.description)
        self.assertNotIn('2026-09-21', line.description)

    def test_termination_exactly_on_a_period_boundary_leaves_no_stub(self):
        contract = self._contract(date(2026, 9, 1), date(2026, 10, 31))
        with self._at(date(2026, 9, 30)):
            contract.action_activate()
        september = contract.schedule_line_ids[0]
        self._terminate_on(contract, date(2026, 9, 30))
        self.assertEqual(contract.schedule_line_ids, september)                 # same record, October removed
        self.assertEqual((september.period_end, september.is_prorated, september.amount), (date(2026, 10, 1), False, 1000.0))

    def test_all_future_uninvoiced_lines_are_removed(self):
        contract = self._contract(date(2026, 9, 1), date(2026, 12, 31))
        with self._at(date(2026, 9, 20)):
            contract.action_activate()
        self.assertEqual(len(contract.schedule_line_ids), 4)
        self._terminate_on(contract, date(2026, 9, 20))
        self.assertEqual(contract.schedule_line_ids.mapped('period_start'), [date(2026, 9, 1)])

    def test_quarterly_line_crossing_termination_uses_calendar_months(self):
        contract = self._contract(date(2026, 1, 1), date(2026, 12, 31), rent=3000, freq='quarterly')
        with self._at(date(2026, 2, 10)):
            contract.action_activate()
        self._terminate_on(contract, date(2026, 2, 10))
        (line,) = contract.schedule_line_ids
        # January in full (1,000) + 10 of February's 28 days (357.14): not 41/90 of the quarter
        self.assertEqual((line.period_end, line.occupied_days, line.is_prorated, line.amount),
                         (date(2026, 2, 11), 41, True, 1357.14))

    def test_truncation_uses_the_contract_currency_rounding(self):
        jod = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'JOD')])
        jod.active = True
        contract = self._contract(date(2026, 1, 1), date(2026, 3, 31), currency_id=jod.id)
        with self._at(date(2026, 1, 20)):
            contract.action_activate()
        self._terminate_on(contract, date(2026, 1, 20))
        self.assertEqual(contract.schedule_line_ids.amount, 645.161)            # 1,000 x 20/31 at 0.001

    def test_invoiced_line_is_never_modified_and_is_reported(self):
        contract = self._contract(date(2026, 9, 1), date(2026, 12, 31))
        with self._at(date(2026, 9, 20)):
            contract.action_activate()
        line = contract.schedule_line_ids[0]
        invoice = line._create_invoice()
        snapshot = (line.id, line.period_start, line.period_end, line.amount, line.invoice_id, invoice.amount_total, invoice.state)
        self._terminate_on(contract, date(2026, 9, 20))
        self.assertEqual(contract.schedule_line_ids, line)                      # later lines removed, this one stays
        self.assertEqual((line.id, line.period_start, line.period_end, line.amount, line.invoice_id, invoice.amount_total, invoice.state), snapshot)
        self.assertEqual((line.period_end, invoice.amount_total, invoice.state), (date(2026, 10, 1), 1000.0, 'posted'))
        self.assertTrue(any('NOT modified' in (m.body or '') for m in contract.message_ids))

    def test_unit_can_be_relet_the_day_after_termination(self):
        unit = self._unit()
        old = self._contract(date(2026, 9, 1), date(2026, 10, 31), unit=unit)
        with self._at(date(2026, 9, 20)):
            old.action_activate()
        self._terminate_on(old, date(2026, 9, 20))
        new = self._contract(date(2026, 9, 21), date(2026, 12, 31), unit=unit)
        with self._at(date(2026, 9, 21)):
            new.action_activate()
        self.assertEqual(new.state, 'active')
        self.assertEqual(new.schedule_line_ids[0].period_start, date(2026, 9, 21))
        self._assert_no_overlap(unit)
        # every day billed once: old 20 days + new lease from the 21st
        self.assertEqual(old.schedule_line_ids.occupied_days, 20)

    def test_termination_schedule_cut_is_idempotent(self):
        contract = self._contract(date(2026, 9, 1), date(2026, 12, 31))
        with self._at(date(2026, 9, 20)):
            contract.action_activate()
        self._terminate_on(contract, date(2026, 9, 20))
        snapshot = [(l.id, l.period_start, l.period_end, l.amount, l.is_prorated) for l in contract.schedule_line_ids]
        contract._truncate_schedule_at(date(2026, 9, 21))
        contract._truncate_schedule_at(date(2026, 9, 21))
        self.assertEqual([(l.id, l.period_start, l.period_end, l.amount, l.is_prorated) for l in contract.schedule_line_ids], snapshot)

    def test_earned_overdue_rent_survives_termination(self):
        """MAT-FIND-006: an earned, already-due, uninvoiced period is never dropped; the period
        crossing the termination date is kept but cut to the earned days."""
        contract = self._contract(date(2026, 8, 1), date(2026, 12, 31))
        with self._at(date(2026, 9, 20)):
            contract.action_activate()
        august = contract.schedule_line_ids[0]
        self._terminate_on(contract, date(2026, 9, 20))
        self.assertEqual(len(contract.schedule_line_ids), 2)
        self.assertEqual((contract.schedule_line_ids[0], august.amount, august.state, august.period_end), (august, 1000.0, 'overdue', date(2026, 9, 1)))
        self.assertEqual((contract.schedule_line_ids[1].amount, contract.schedule_line_ids[1].period_end), (666.67, date(2026, 9, 21)))
        self._assert_no_overlap(contract.unit_id)

    # ================= Y3: migration occupancy resync =================

    def test_migration_resyncs_stale_occupancy_immediately_and_is_idempotent(self):
        current = self._contract(self.today - timedelta(days=100), self.today + timedelta(days=30))
        current.action_activate()
        unit = current.unit_id
        owner_unit = self._unit()
        owner_unit.occupancy_status = 'owner_occupied'
        # the state the 19.0.1.1.0 migration left behind: lease active and covering today, unit still reserved
        self.env.flush_all()
        self.env.cr.execute("UPDATE edara_unit SET occupancy_status = 'reserved' WHERE id = %s", (unit.id,))
        self.env.invalidate_all()
        self.assertEqual((unit.occupancy_status, unit._lease_occupancy_state()), ('reserved', 'rented'))
        migration = _migration('19.0.1.2.0')
        lines_before = current.schedule_line_ids.ids
        migration.migrate(self.env.cr, '19.0.1.1.0')
        self.env.invalidate_all()
        self.assertEqual(unit.occupancy_status, 'rented')
        self.assertEqual(owner_unit.occupancy_status, 'owner_occupied')         # not lease-managed: untouched
        stamp = unit.write_date
        migration.migrate(self.env.cr, '19.0.1.1.0')                            # idempotent: no write at all
        self.env.invalidate_all()
        self.assertEqual((unit.occupancy_status, unit.write_date), ('rented', stamp))
        self.assertEqual(current.schedule_line_ids.ids, lines_before)
        self.assertEqual((current.start_date, current.end_date, current.state), (self.today - timedelta(days=100), self.today + timedelta(days=30), 'active'))

    def test_upgrade_from_19_0_1_0_0_runs_both_migrations_in_order(self):
        legacy_renewed = self._contract(self.today - timedelta(days=100), self.today + timedelta(days=30))
        legacy_renewed.action_activate()
        unit = legacy_renewed.unit_id
        self.env.flush_all()
        self.env.cr.execute("UPDATE edara_lease_contract SET state = 'renewed' WHERE id = %s", (legacy_renewed.id,))
        self.env.cr.execute("UPDATE edara_unit SET occupancy_status = 'reserved' WHERE id = %s", (unit.id,))
        self.env.invalidate_all()
        for version in ('19.0.1.1.0', '19.0.1.2.0'):
            _migration(version).migrate(self.env.cr, '19.0.1.0.0')
        self.env.invalidate_all()
        self.assertEqual((legacy_renewed.state, unit.occupancy_status), ('active', 'rented'))
        self.assertFalse(self.env['account.move'].search([('edara_contract_id', '=', legacy_renewed.id)]))

    # ================= Y4: lifecycle links guard =================

    def _renewable(self):
        current = self._contract(self.today - timedelta(days=100), self.today + timedelta(days=30))
        current.action_activate()
        other = self._contract(self.today + timedelta(days=200), self.today + timedelta(days=300))
        return current, other

    def test_lifecycle_links_are_not_writable_by_a_restricted_user(self):
        current, other = self._renewable()
        as_manager = current.with_user(self.manager)
        for field in ('successor_contract_id', 'predecessor_contract_id'):
            with self.assertRaises(AccessError):
                as_manager.write({field: other.id})
            with self.assertRaises(AccessError):                                # web client entry point
                as_manager.web_save({field: other.id}, {'id': {}})
            with self.assertRaises(AccessError):                                # forged context cannot become su
                as_manager.with_context(su=True).write({field: other.id})
        self.assertFalse(current.successor_contract_id or current.predecessor_contract_id)

    def test_client_supplied_links_are_ignored_on_create(self):
        current, other = self._renewable()
        created = self.env['edara.lease.contract'].with_user(self.manager).create({
            'unit_id': self._unit().id, 'tenant_id': self.tenant.id, 'start_date': self.today, 'end_date': self.today + timedelta(days=30),
            'rent_amount': 500, 'deposit_required': False, 'predecessor_contract_id': current.id, 'successor_contract_id': other.id})
        self.assertFalse(created.predecessor_contract_id or created.successor_contract_id)

    def test_trusted_lifecycle_actions_still_set_and_clear_the_links(self):
        current, _other = self._renewable()
        successor = current.with_user(self.manager).action_renew(
            current.end_date + timedelta(days=1), current.end_date + timedelta(days=366), 1100)
        self.assertEqual((current.successor_contract_id, successor.predecessor_contract_id, successor.state), (successor, current, 'scheduled'))
        successor.with_user(self.manager).action_cancel()
        self.assertEqual((successor.state, current.successor_contract_id.id, successor.predecessor_contract_id), ('cancelled', False, current))

    # ================= Y4: invoiced schedule dates frozen =================

    def test_invoiced_line_coverage_is_frozen_but_uninvoiced_lines_stay_editable(self):
        contract = self._contract(date(2026, 1, 1), date(2026, 3, 31))
        contract.action_activate()
        invoiced, uninvoiced = contract.schedule_line_ids[0], contract.schedule_line_ids[2]
        # intended edits of an uninvoiced line remain possible for a restricted user
        uninvoiced.with_user(self.manager).write({'amount': 1234.0, 'description': 'edited', 'due_date': date(2026, 3, 2)})
        self.assertEqual((uninvoiced.amount, uninvoiced.due_date), (1234.0, date(2026, 3, 2)))
        invoice = invoiced._create_invoice()
        before = (invoiced.due_date, invoiced.period_start, invoiced.period_end, invoiced.period_last_day, invoiced.occupied_days, invoiced.is_prorated)
        as_manager = invoiced.with_user(self.manager)
        for vals in ({'period_start': date(2026, 1, 2)}, {'period_end': date(2026, 1, 21)}, {'period_last_day': date(2026, 1, 20)},
                     {'occupied_days': 10}, {'is_prorated': True}, {'due_date': date(2026, 1, 5)}):
            with self.assertRaises(AccessError, msg=str(vals)):
                as_manager.write(vals)
            with self.assertRaises(AccessError, msg='web_save %s' % vals):
                as_manager.web_save(vals, {'id': {}})
            with self.assertRaises(AccessError, msg='su-forged %s' % vals):
                as_manager.with_context(su=True).write(vals)
        with self.assertRaises(AccessError):
            as_manager.write({'amount': 1.0})
        self.assertEqual((invoiced.due_date, invoiced.period_start, invoiced.period_end, invoiced.period_last_day, invoiced.occupied_days, invoiced.is_prorated), before)
        self.assertEqual((invoice.amount_total, invoice.state, invoiced.invoice_id), (1000.0, 'posted', invoice))
        as_manager.write({'sequence': 99, 'description': 'ok'})                # non-coverage fields are not frozen

    def test_schedule_generation_stays_idempotent_with_an_invoiced_line(self):
        contract = self._contract(date(2026, 1, 1), date(2026, 3, 31))
        contract.action_activate()
        invoiced = contract.schedule_line_ids[0]
        invoiced._create_invoice()
        ids = contract.schedule_line_ids.ids
        contract._generate_schedule_lines()
        self.assertEqual(contract.schedule_line_ids.ids, ids)
        contract.end_date = date(2026, 4, 30)                                  # trusted extension path still works
        self.assertEqual(len(contract.schedule_line_ids), 4)
        self.assertEqual((invoiced.period_start, invoiced.period_end), (date(2026, 1, 1), date(2026, 2, 1)))
