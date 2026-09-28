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
class TestPhase1012Hardening(TransactionCase):
    """Phase 10.1.2 - Fix A (occupancy sync/migration defensive around a unit that is
    under maintenance) and Fix B (contract_id frozen on invoiced schedule lines, closing
    the gap the final Phase 10.1.1 audit found). Guard tests run as a real, restricted
    branch manager - the TransactionCase superuser would bypass exactly what they verify."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        E = cls.env
        cls.branch = E['edara.branch'].create({'name': 'P112 Branch', 'code': 'P112B'})
        cls.property = E['edara.property'].create({'name': 'P112 Property', 'code': 'P112P', 'branch_id': cls.branch.id})
        cls.building = E['edara.building'].create({'name': 'P112 Building', 'code': 'P112BL', 'property_id': cls.property.id})
        cls.tenant = E['res.partner'].create({'name': 'P112 Tenant'})
        cls.manager = new_test_user(E, login='p112_bm', groups='property_managment.group_edara_branch_manager')
        cls.branch.user_ids = [Command.link(cls.manager.id)]
        E.company.edara_rental_income_account_id = E['account.account'].create(
            {'name': 'P112 Rent', 'code': '411200', 'account_type': 'income'}).id
        cls.today = date.today()
        cls._n = 0

    # ---------------- helpers ----------------
    def _unit(self):
        type(self)._n += 1
        return self.env['edara.unit'].create(
            {'name': 'P112-%d' % self._n, 'code': 'P112U%d' % self._n, 'building_id': self.building.id})

    def _contract(self, start, end, unit=None, rent=1000, **kw):
        vals = {'unit_id': (unit or self._unit()).id, 'tenant_id': self.tenant.id, 'start_date': start,
                'end_date': end, 'rent_amount': rent, 'billing_frequency': 'monthly', 'deposit_required': False}
        vals.update(kw)
        return self.env['edara.lease.contract'].create(vals)

    def _at(self, day):
        return patch.object(fields.Date, 'context_today', staticmethod(lambda record, timestamp=None: day))

    # ================= Fix A: occupancy sync hardening =================

    def test_case_a_under_maintenance_no_lease_terminate_does_not_raise(self):
        """A rented unit that is also under maintenance (e.g. the AC breaks while occupied)
        is legal. Terminating its only lease derives 'available', which is illegal alongside
        under_maintenance. The sync must skip that write - not raise - and termination itself
        must still succeed."""
        contract = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20))
        contract.action_activate()
        unit = contract.unit_id
        self.assertEqual(unit.occupancy_status, 'rented')
        unit.operational_status = 'under_maintenance'                    # legal: rented + under_maintenance
        contract.action_terminate(reason='ac broken')                    # must not raise
        self.assertEqual(contract.state, 'terminated')
        self.assertEqual(unit.occupancy_status, 'rented')                # stale, left for a human; never 'available'
        self.assertEqual(unit.operational_status, 'under_maintenance')

    def test_case_a_direct_sync_call_skips_invalid_write(self):
        contract = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20))
        contract.action_activate()
        unit = contract.unit_id
        unit.operational_status = 'under_maintenance'
        self.env.cr.execute("UPDATE edara_lease_contract SET state = 'expired' WHERE id = %s", (contract.id,))
        self.env.invalidate_all()
        self.assertEqual((unit.occupancy_status, unit._lease_occupancy_state()), ('rented', 'available'))
        stamp = unit.write_date
        unit._sync_occupancy_from_contracts()                            # must not raise
        self.assertEqual((unit.occupancy_status, unit.write_date), ('rented', stamp))   # untouched, no write at all

    def test_case_b_under_maintenance_with_current_lease_stays_rented(self):
        contract = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20))
        contract.action_activate()
        unit = contract.unit_id
        unit.operational_status = 'under_maintenance'
        unit._sync_occupancy_from_contracts()
        self.assertEqual(unit.occupancy_status, 'rented')

    def test_case_c_normal_unit_no_lease_is_available(self):
        unit = self._unit()
        unit._sync_occupancy_from_contracts()
        self.assertEqual(unit.occupancy_status, 'available')

    def test_case_d_normal_unit_future_lease_is_reserved(self):
        contract = self._contract(self.today + timedelta(days=10), self.today + timedelta(days=40))
        contract.action_activate()
        self.assertEqual(contract.unit_id.occupancy_status, 'reserved')

    def test_case_e_normal_unit_current_lease_is_rented(self):
        contract = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20))
        contract.action_activate()
        self.assertEqual(contract.unit_id.occupancy_status, 'rented')

    def test_case_f_owner_occupied_untouched(self):
        unit = self._unit()
        unit.occupancy_status = 'owner_occupied'
        unit._sync_occupancy_from_contracts()
        self.assertEqual(unit.occupancy_status, 'owner_occupied')

    def test_case_g_sold_untouched(self):
        unit = self._unit()
        unit.occupancy_status = 'sold'
        unit._sync_occupancy_from_contracts()
        self.assertEqual(unit.occupancy_status, 'sold')

    # ================= Fix A: migration hardening =================

    def test_migration_completes_on_under_maintenance_plus_ended_lease(self):
        """The exact hazard the final Phase 10.1.1 audit found: a stale 'rented' unit, under
        maintenance, whose lease has already ended - the migration must not abort, and must
        leave the stale value alone rather than force the illegal 'available' state."""
        contract = self._contract(self.today - timedelta(days=100), self.today + timedelta(days=30))
        contract.action_activate()
        unit = contract.unit_id
        self.assertEqual(unit.occupancy_status, 'rented')
        self.env.flush_all()
        self.env.cr.execute("UPDATE edara_lease_contract SET state = 'expired' WHERE id = %s", (contract.id,))
        self.env.cr.execute("UPDATE edara_unit SET operational_status = 'under_maintenance' WHERE id = %s", (unit.id,))
        self.env.invalidate_all()
        self.assertEqual((unit.occupancy_status, unit._lease_occupancy_state()), ('rented', 'available'))
        migration = _migration('19.0.1.2.0')
        migration.migrate(self.env.cr, '19.0.1.1.0')                     # must not raise
        self.env.invalidate_all()
        self.assertEqual(unit.occupancy_status, 'rented')                # left stale, not forced to 'available'
        self.assertEqual(unit.operational_status, 'under_maintenance')
        stamp = unit.write_date
        migration.migrate(self.env.cr, '19.0.1.1.0')                     # idempotent: no further write
        self.env.invalidate_all()
        self.assertEqual((unit.occupancy_status, unit.write_date), ('rented', stamp))
        self.assertFalse(self.env['account.move'].search([('edara_contract_id', '=', contract.id)]))
        self.assertEqual(contract.state, 'expired')

    # ================= Fix B: contract_id frozen once invoiced =================

    def _two_contracts(self):
        a = self._contract(date(2026, 1, 1), date(2026, 3, 31))
        b = self._contract(date(2026, 6, 1), date(2026, 8, 31))          # different unit, non-overlapping window
        with self._at(date(2026, 1, 5)):
            a.action_activate()
        with self._at(date(2026, 6, 5)):
            b.action_activate()
        return a, b

    def test_uninvoiced_line_contract_id_stays_editable(self):
        a, b = self._two_contracts()
        line = a.schedule_line_ids[0]
        line.with_user(self.manager).write({'contract_id': b.id})
        self.assertEqual(line.contract_id, b)

    def test_invoiced_line_contract_id_cannot_be_moved_by_write(self):
        a, b = self._two_contracts()
        line = a.schedule_line_ids[0]
        line._create_invoice()
        with self.assertRaises(AccessError):
            line.with_user(self.manager).write({'contract_id': b.id})
        self.assertEqual(line.contract_id, a)

    def test_invoiced_line_period_and_amount_still_frozen_alongside_contract_id(self):
        a, _b = self._two_contracts()
        line = a.schedule_line_ids[0]
        line._create_invoice()
        as_manager = line.with_user(self.manager)
        for vals in ({'period_start': date(2026, 1, 2)}, {'period_end': date(2026, 1, 21)}):
            with self.assertRaises(AccessError, msg=str(vals)):
                as_manager.write(vals)
        with self.assertRaises(AccessError):
            as_manager.write({'amount': 1.0})
        self.assertEqual(line.contract_id, a)

    def test_invoiced_line_contract_id_cannot_be_moved_by_web_save(self):
        a, b = self._two_contracts()
        line = a.schedule_line_ids[0]
        line._create_invoice()
        with self.assertRaises(AccessError):
            line.with_user(self.manager).web_save({'contract_id': b.id}, {'id': {}})
        self.assertEqual(line.contract_id, a)

    def test_invoiced_line_contract_id_forged_su_context_is_rejected(self):
        a, b = self._two_contracts()
        line = a.schedule_line_ids[0]
        line._create_invoice()
        with self.assertRaises(AccessError):
            line.with_user(self.manager).with_context(su=True).write({'contract_id': b.id})
        self.assertEqual(line.contract_id, a)

    def test_invoiced_line_invoice_id_still_frozen(self):
        a, b = self._two_contracts()
        line = a.schedule_line_ids[0]
        line._create_invoice()
        other_invoice = b.schedule_line_ids[0]._create_invoice()
        with self.assertRaises(AccessError):
            line.with_user(self.manager).write({'invoice_id': other_invoice.id})

    def test_trusted_lifecycle_actions_still_work_with_contract_id_frozen(self):
        """Terminate/generate/invoice never write contract_id on an existing line, so the
        freeze must not interfere with any real lifecycle path."""
        contract = self._contract(date(2026, 1, 1), date(2026, 3, 31))
        with self._at(date(2026, 1, 5)):
            contract.action_activate()
        invoiced = contract.schedule_line_ids[0]
        invoice = invoiced._create_invoice()
        contract.action_terminate(reason='p112')
        self.assertEqual(invoiced.contract_id, contract)
        self.assertEqual((invoice.state, invoice.amount_total), ('posted', 1000.0))
