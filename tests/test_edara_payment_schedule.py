from datetime import date, timedelta
import os

from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestEdaraPaymentSchedule(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Ramallah Branch', 'code': 'RAM2'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Al-Masyoun Residence', 'code': 'MAS', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Building A', 'code': 'A', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'A-201', 'code': '201', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Sara Odeh'})
        cls.income_account = cls.env['account.account'].create({
            'name': 'EDARA Rental Income (Test)',
            'code': '400100',
            'account_type': 'income',
        })

    def _make_contract(self, **overrides):
        vals = {
            'unit_id': self.unit.id,
            'tenant_id': self.tenant.id,
            'start_date': date(2026, 1, 15),
            'end_date': date(2026, 6, 20),
            'rent_amount': 1000,
            'deposit_required': False,
        }
        vals.update(overrides)
        return self.env['edara.lease.contract'].create(vals)

    def test_schedule_generated_on_activation(self):
        contract = self._make_contract()
        self.assertFalse(contract.schedule_line_ids)
        contract.action_activate()
        self.assertEqual(len(contract.schedule_line_ids), 6)
        expected_dates = [date(2026, m, 15) for m in range(1, 7)]
        self.assertEqual(contract.schedule_line_ids.mapped('due_date'), expected_dates)
        # First 5 periods reach their own full monthly anchor (15/01..15/06);
        # the 6th is cut by end_date (2026-06-20 is the LAST occupied day, so the boundary
        # is 21/06, 24 days short of its 15/07 anchor) and is prorated: 6 of the 30 days
        # of the anchored month 15/06 - 15/07, not billed at the full rate.
        full_lines = contract.schedule_line_ids[:5]
        last_line = contract.schedule_line_ids[5]
        self.assertTrue(all(line.amount == 1000 and not line.is_prorated for line in full_lines))
        self.assertTrue(last_line.is_prorated)
        self.assertEqual(last_line.period_end, date(2026, 6, 21))
        self.assertEqual(last_line.period_last_day, date(2026, 6, 20))
        self.assertEqual(last_line.occupied_days, 6)
        self.assertEqual(last_line.amount, 200.0)

    def test_schedule_excludes_line_exactly_on_end_date(self):
        """MAT-FIND-005 Case 1: the term boundary (end_date + 1) is not itself a billable
        period - a due date landing exactly on it must NOT produce a separate installment."""
        contract = self._make_contract(start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))
        contract.action_activate()
        self.assertEqual(contract.schedule_line_ids.mapped('due_date'), [date(2026, 8, 1)])
        self.assertFalse(contract.schedule_line_ids.is_prorated)

    def test_schedule_normal_multi_month_excludes_end_date(self):
        """MAT-FIND-005 Case 2: a longer contract must still stop one period
        short of end_date, not include a line exactly on it."""
        contract = self._make_contract(start_date=date(2026, 8, 1), end_date=date(2026, 10, 31))
        contract.action_activate()
        self.assertEqual(
            contract.schedule_line_ids.mapped('due_date'),
            [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)])

    def test_schedule_keeps_legitimate_line_strictly_before_end_date(self):
        """MAT-FIND-005 Case 3: the end_date fix must not remove a legitimate
        due date that falls strictly before end_date. Payment Day is now
        always derived from Start Date, so there is no manual-payment_day
        "shift" scenario anymore - this exercises a period that is truncated
        by end_date but still produces exactly one correct line."""
        contract = self._make_contract(start_date=date(2026, 8, 7), end_date=date(2026, 9, 1))
        contract.action_activate()
        self.assertEqual(contract.schedule_line_ids.mapped('due_date'), [date(2026, 8, 7)])
        self.assertTrue(contract.schedule_line_ids[0].due_date < contract.end_date)
        self.assertEqual(contract.schedule_line_ids[0].occupied_days, 26)
        self.assertEqual(contract.schedule_line_ids[0].amount, 838.71)   # 1,000 x 26/31

    def test_invoice_blocked_without_income_account(self):
        # Phase 6.4: this shared dev database's real company may already have
        # edara_rental_income_account_id configured (real accounting setup,
        # not test data) - explicitly clear it for this negative test.
        self.env.company.edara_rental_income_account_id = False
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        with self.assertRaises(UserError):
            line._create_invoice()

    def test_invoice_created_with_analytic_distribution(self):
        self.env.company.edara_rental_income_account_id = self.income_account.id
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        invoice = line._create_invoice()
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(line.invoice_id, invoice)
        analytic_account = self.property.get_analytic_account()
        invoice_line = invoice.invoice_line_ids[0]
        self.assertEqual(invoice_line.account_id, self.income_account)
        self.assertIn(str(analytic_account.id), invoice_line.analytic_distribution)

    def test_prorated_line_creates_invoice_with_prorated_amount(self):
        """MAT-FIND-011 / MAT-FIND-013 accounting integration: a prorated
        schedule-line amount must flow through unchanged to the native
        Odoo invoice - no separate proration logic in _create_invoice()."""
        self.env.company.edara_rental_income_account_id = self.income_account.id
        contract = self._make_contract(
            start_date=date(2026, 9, 2), end_date=date(2026, 9, 30), rent_amount=1600)
        contract.action_activate()
        line = contract.schedule_line_ids
        self.assertTrue(line.is_prorated)
        self.assertEqual(line.amount, 1546.67)
        invoice = line._create_invoice()
        self.assertEqual(invoice.amount_total, 1546.67)

    def test_cron_is_idempotent_and_only_invoices_due_lines(self):
        self.env.company.edara_rental_income_account_id = self.income_account.id
        today = date.today()
        payment_day = min(today.day, 28)
        start_date = (today - relativedelta(months=2)).replace(day=payment_day)
        contract = self._make_contract(start_date=start_date, end_date=today + relativedelta(years=1))
        contract.action_activate()

        due_lines = contract.schedule_line_ids.filtered(lambda l: l.due_date <= today)
        self.assertEqual(len(due_lines), 3)

        self.env['edara.payment.schedule.line']._cron_generate_due_invoices()
        self.assertTrue(all(line.invoice_id for line in due_lines))
        invoice_ids_after_first_run = due_lines.mapped('invoice_id.id')

        # Running again must not create duplicate invoices for already-invoiced lines.
        self.env['edara.payment.schedule.line']._cron_generate_due_invoices()
        self.assertEqual(due_lines.mapped('invoice_id.id'), invoice_ids_after_first_run)

        future_lines = contract.schedule_line_ids - due_lines
        self.assertTrue(future_lines)
        self.assertFalse(any(line.invoice_id for line in future_lines))

    def test_termination_removes_future_lines_and_stops_cron_invoicing(self):
        self.env.company.edara_rental_income_account_id = self.income_account.id
        today = date.today()
        payment_day = min(today.day, 28)
        start_date = (today - relativedelta(months=1)).replace(day=payment_day)
        contract = self._make_contract(start_date=start_date, end_date=today + relativedelta(years=1))
        contract.action_activate()

        # MAT-FIND-006 + Phase 10.1.1: the termination date (today) is the last occupied day, so
        # rent is earned through it. Strictly-overdue uninvoiced lines survive untouched; the line
        # covering today is kept but cut to that one day; everything after it is removed.
        contract.action_terminate('Tenant moved out')

        lines = contract.schedule_line_ids
        last = lines[-1]
        self.assertTrue(all(line.due_date <= today for line in lines))            # nothing after today remains
        self.assertEqual(last.period_end, today + timedelta(days=1))              # cut at the last occupied day
        self.assertTrue(all(line.period_end <= last.period_start for line in lines[:-1]))
        self.assertTrue(all(line.state == 'overdue' for line in lines if line.due_date < today))
        # Track A: cron invoices surviving owed lines; future lines were unlinked and cannot be invoiced.
        self.env['edara.payment.schedule.line']._cron_generate_due_invoices()
        self.assertTrue(lines)
        self.assertTrue(all(line.invoice_id for line in lines))

    def test_invoiced_line_cannot_be_deleted(self):
        self.env.company.edara_rental_income_account_id = self.income_account.id
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        line._create_invoice()
        with self.assertRaises(UserError):
            line.unlink()

    def test_uninvoiced_line_can_still_be_deleted(self):
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        line.unlink()
        self.assertFalse(line.exists())

    def test_late_fee_blocked_when_not_overdue(self):
        contract = self._make_contract(
            start_date=date.today(), end_date=date.today() + relativedelta(years=1))
        contract.action_activate()
        line = contract.schedule_line_ids.filtered(lambda l: l.state != 'overdue')[0]
        with self.assertRaises(UserError):
            line.action_charge_late_fee()

    def test_late_fee_blocked_without_income_account(self):
        # Phase 6.4: explicitly clear the late-fee income account - the real
        # company may already have one configured.
        self.env.company.edara_late_fee_income_account_id = False
        contract = self._make_contract()  # 2026-01-15..2026-06-20, all overdue relative to "today"
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        self.assertEqual(line.state, 'overdue')
        self.env.company.edara_late_fee_amount = 25
        with self.assertRaises(UserError):
            line.action_charge_late_fee()

    def test_late_fee_blocked_without_amount_configured(self):
        self.env.company.edara_late_fee_amount = 0
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test)', 'code': '400200', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        with self.assertRaises(UserError):
            line.action_charge_late_fee()

    def test_late_fee_charged_as_separate_posted_invoice(self):
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test)', 'code': '400200', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]

        late_fee_invoice = line.action_charge_late_fee()
        self.assertEqual(late_fee_invoice.state, 'posted')
        self.assertEqual(late_fee_invoice.edara_invoice_type, 'late_fee')
        self.assertNotEqual(late_fee_invoice, line.invoice_id)  # separate from the rent invoice
        invoice_line = late_fee_invoice.invoice_line_ids[0]
        self.assertEqual(invoice_line.account_id, late_fee_account)
        self.assertEqual(invoice_line.price_unit, 25)
        # Ticket 6: Test 1 coverage
        self.assertTrue(line.late_fee_invoice_id)
        self.assertEqual(line.late_fee_invoice_id, late_fee_invoice)
        self.assertTrue(line.late_fee_invoice_id.exists())
        self.assertEqual(line.late_fee_invoice_id.state, 'posted')
        self.assertEqual(line.late_fee_invoice_id.edara_invoice_type, 'late_fee')

    def test_late_fee_second_charge_attempt_raises_user_error(self):
        """Ticket 6: Test 2 - Calling action_charge_late_fee() twice on the same line
        must raise UserError and produce no duplicate invoice."""
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test 2)', 'code': '400201', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]

        invoice1 = line.action_charge_late_fee()
        self.assertTrue(invoice1)
        self.assertEqual(line.late_fee_invoice_id, invoice1)

        with self.assertRaises(UserError):
            line.action_charge_late_fee()

        late_invoices = self.env['account.move'].search([
            ('edara_contract_id', '=', contract.id),
            ('edara_invoice_type', '=', 'late_fee'),
        ])
        self.assertEqual(len(late_invoices), 1)
        self.assertEqual(late_invoices, invoice1)

    def test_late_fee_persistence_and_attributes(self):
        """Ticket 6: Tests 3, 4, 5 - Verify late_fee_invoice_id persists upon reload,
        has edara_invoice_type == 'late_fee', and state == 'posted'."""
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test 3)', 'code': '400202', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]

        invoice = line.action_charge_late_fee()
        reloaded_line = self.env['edara.payment.schedule.line'].browse(line.id)
        # Test 3: Persistence
        self.assertTrue(reloaded_line.late_fee_invoice_id)
        self.assertEqual(reloaded_line.late_fee_invoice_id.id, invoice.id)
        # Test 4: Invoice type
        self.assertEqual(reloaded_line.late_fee_invoice_id.edara_invoice_type, 'late_fee')
        # Test 5: Posted state
        self.assertEqual(reloaded_line.late_fee_invoice_id.state, 'posted')

    def test_late_fee_bulk_mixed_selection(self):
        """Ticket 6: Test 6 - Bulk action charges eligible lines, skips already-charged,
        skips non-overdue, and avoids duplicate invoices."""
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test 6)', 'code': '400203', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25

        contract_overdue = self._make_contract()
        contract_overdue.action_activate()
        line_eligible = contract_overdue.schedule_line_ids[0]
        line_already = contract_overdue.schedule_line_ids[1]

        # Pre-charge line_already
        prev_inv = line_already.action_charge_late_fee()
        self.assertTrue(line_already.late_fee_invoice_id)

        # Future non-overdue line
        contract_future = self._make_contract(
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + relativedelta(years=1),
        )
        contract_future.action_activate()
        line_future = contract_future.schedule_line_ids[0]
        self.assertEqual(line_future.state, 'draft')

        invoices_before = self.env['account.move'].search_count([('edara_invoice_type', '=', 'late_fee')])

        selection = line_eligible + line_already + line_future
        res = selection.action_charge_late_fee_bulk()

        # Check line_eligible was charged
        self.assertTrue(line_eligible.late_fee_invoice_id)
        self.assertEqual(line_eligible.late_fee_invoice_id.state, 'posted')

        # Check line_already was skipped without duplicate invoice
        self.assertEqual(line_already.late_fee_invoice_id, prev_inv)

        # Check line_future was skipped
        self.assertFalse(line_future.late_fee_invoice_id)

        invoices_after = self.env['account.move'].search_count([('edara_invoice_type', '=', 'late_fee')])
        self.assertEqual(invoices_after, invoices_before + 1)

        # Notification action returned
        self.assertEqual(res['type'], 'ir.actions.client')
        self.assertEqual(res['tag'], 'display_notification')
        self.assertEqual(res['params']['type'], 'success')

    def test_late_fee_bulk_skip_already_charged(self):
        """Ticket 6: Test 7 - Bulk action does not create a second invoice for already-charged line."""
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test 7)', 'code': '400204', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        first_invoice = line.action_charge_late_fee()

        count_before = self.env['account.move'].search_count([('edara_invoice_type', '=', 'late_fee')])
        res = line.action_charge_late_fee_bulk()
        count_after = self.env['account.move'].search_count([('edara_invoice_type', '=', 'late_fee')])

        self.assertEqual(count_before, count_after)
        self.assertEqual(line.late_fee_invoice_id, first_invoice)
        self.assertEqual(res['tag'], 'display_notification')

    def test_late_fee_bulk_skip_non_overdue(self):
        """Ticket 6: Test 8 - Bulk action does not create late-fee invoice for non-overdue line."""
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test 8)', 'code': '400205', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25
        contract = self._make_contract(
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + relativedelta(years=1),
        )
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        self.assertEqual(line.state, 'draft')

        count_before = self.env['account.move'].search_count([('edara_invoice_type', '=', 'late_fee')])
        res = line.action_charge_late_fee_bulk()
        count_after = self.env['account.move'].search_count([('edara_invoice_type', '=', 'late_fee')])

        self.assertEqual(count_before, count_after)
        self.assertFalse(line.late_fee_invoice_id)
        self.assertEqual(res['tag'], 'display_notification')

    def test_late_fee_bulk_zero_eligible_selection(self):
        """Ticket 6: Test 9 - Bulk action on only ineligible records produces no side-effects and returns feedback."""
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test 9)', 'code': '400206', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25

        contract_overdue = self._make_contract()
        contract_overdue.action_activate()
        line_overdue = contract_overdue.schedule_line_ids[0]
        line_overdue.action_charge_late_fee()

        contract_future = self._make_contract(
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + relativedelta(years=1),
        )
        contract_future.action_activate()
        line_future = contract_future.schedule_line_ids[0]

        ineligible_selection = line_overdue + line_future
        count_before = self.env['account.move'].search_count([('edara_invoice_type', '=', 'late_fee')])
        res = ineligible_selection.action_charge_late_fee_bulk()
        count_after = self.env['account.move'].search_count([('edara_invoice_type', '=', 'late_fee')])

        self.assertEqual(count_before, count_after)
        self.assertEqual(res['type'], 'ir.actions.client')
        self.assertEqual(res['tag'], 'display_notification')

    def test_late_fee_single_record_form_action_regression(self):
        """Ticket 6: Test 10 - Existing form single-record action still works for eligible overdue line."""
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test 10)', 'code': '400207', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25
        contract = self._make_contract()
        contract.action_activate()
        line = contract.schedule_line_ids[0]
        self.assertEqual(line.state, 'overdue')
        self.assertFalse(line.late_fee_invoice_id)

        inv = line.action_charge_late_fee()
        self.assertTrue(inv)
        self.assertEqual(inv._name, 'account.move')
        self.assertEqual(inv.state, 'posted')
        self.assertEqual(inv.edara_invoice_type, 'late_fee')
        self.assertEqual(line.late_fee_invoice_id, inv)

    def test_late_fee_security_branch_isolation(self):
        """Ticket 6: Test 11 - Branch-scoped user cannot charge late fees outside permitted branch."""
        branch_a = self.env['edara.branch'].create({'name': 'Sec Branch A', 'code': 'SBA6'})
        branch_b = self.env['edara.branch'].create({'name': 'Sec Branch B', 'code': 'SBB6'})

        prop_a = self.env['edara.property'].create({'name': 'Sec Prop A', 'code': 'SPA6', 'branch_id': branch_a.id})
        prop_b = self.env['edara.property'].create({'name': 'Sec Prop B', 'code': 'SPB6', 'branch_id': branch_b.id})

        bld_a = self.env['edara.building'].create({'name': 'Sec Bld A', 'code': 'SBA_6', 'property_id': prop_a.id})
        bld_b = self.env['edara.building'].create({'name': 'Sec Bld B', 'code': 'SBB_6', 'property_id': prop_b.id})

        unit_a = self.env['edara.unit'].create({'name': 'Unit Sec A', 'code': 'UA6', 'building_id': bld_a.id})
        unit_b = self.env['edara.unit'].create({'name': 'Unit Sec B', 'code': 'UB6', 'building_id': bld_b.id})

        tenant_a = self.env['res.partner'].create({'name': 'Sec Tenant A6'})
        tenant_b = self.env['res.partner'].create({'name': 'Sec Tenant B6'})

        contract_a = self.env['edara.lease.contract'].create({
            'unit_id': unit_a.id, 'tenant_id': tenant_a.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 3, 31),
            'rent_amount': 1000, 'deposit_required': False,
        })
        contract_b = self.env['edara.lease.contract'].create({
            'unit_id': unit_b.id, 'tenant_id': tenant_b.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 3, 31),
            'rent_amount': 1000, 'deposit_required': False,
        })
        contract_a.action_activate()
        contract_b.action_activate()

        line_b = contract_b.schedule_line_ids[0]

        pm_user = new_test_user(
            self.env, login='edara_sec_pm_a', groups='property_managment.group_edara_property_manager')
        branch_a.user_ids = [(4, pm_user.id)]

        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Sec Test)', 'code': '400299', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25

        # Single action outside visible scope raises AccessError
        with self.assertRaises(AccessError):
            line_b.with_user(pm_user).action_charge_late_fee()

        # Bulk action outside visible scope re-raises AccessError
        with self.assertRaises(AccessError):
            line_b.with_user(pm_user).action_charge_late_fee_bulk()

    def test_late_fee_sql_uniqueness_constraint(self):
        """Ticket 6: Test 12 - SQL uniqueness constraint prevents linking the same invoice to two lines."""
        late_fee_account = self.env['account.account'].create(
            {'name': 'Late Fee Income (Test 12)', 'code': '400208', 'account_type': 'income'})
        self.env.company.edara_late_fee_income_account_id = late_fee_account.id
        self.env.company.edara_late_fee_amount = 25
        contract = self._make_contract()
        contract.action_activate()
        line1 = contract.schedule_line_ids[0]
        line2 = contract.schedule_line_ids[1]

        invoice = line1.action_charge_late_fee()
        self.assertEqual(line1.late_fee_invoice_id, invoice)

        with mute_logger('odoo.sql_db'), self.assertRaises(Exception):
            with self.env.cr.savepoint():
                line2.sudo().late_fee_invoice_id = invoice.id

    def test_list_view_invoice_id_is_readonly(self):
        """invoice_id is system-managed (only ever set by _create_invoice()) -
        the editable list view must not let a user inline-edit it (fixed
        2026-09-13, was inconsistent with the form view's existing readonly)."""
        arch = self.env['edara.payment.schedule.line'].get_view(
            view_id=self.env.ref('property_managment.view_edara_payment_schedule_line_list').id)['arch']
        field = etree.fromstring(arch).xpath("//field[@name='invoice_id']")
        self.assertTrue(field)
        self.assertEqual(field[0].get('readonly'), '1')


@tagged('post_install', '-at_install')
class TestEdaraPaymentScheduleFilterShortcuts(TransactionCase):
    """Phase 6.6 (2026-09-23): compact Paid/Overdue/Draft filter-shortcut
    buttons on the Payment Schedule list only - search-filter shortcuts
    (searchModel.toggleSearchItem), never a navigation/domain action. See
    static/src/js/payment_schedule_filter_shortcuts.js."""

    def test_list_view_has_scoped_js_class(self):
        arch = self.env['edara.payment.schedule.line'].get_view(
            view_id=self.env.ref('property_managment.view_edara_payment_schedule_line_list').id)['arch']
        self.assertIn('js_class="edara_payment_schedule_filter_shortcuts"', arch)

    def test_search_view_has_paid_overdue_draft_filters_with_correct_domains(self):
        arch = self.env['edara.payment.schedule.line'].get_view(
            view_id=self.env.ref('property_managment.view_edara_payment_schedule_line_search').id)['arch']
        tree = etree.fromstring(arch)
        for name, expected_domain in (
                ('paid', "[('state', '=', 'paid')]"),
                ('overdue', "[('state', '=', 'overdue')]"),
                ('draft', "[('state', '=', 'draft')]")):
            filters = tree.xpath("//filter[@name='%s']" % name)
            self.assertTrue(filters, "missing filter: %s" % name)
            self.assertEqual(filters[0].get('domain'), expected_domain, name)

    def test_action_has_no_new_act_window_created(self):
        """The buttons must never open a separate action - there must still
        be exactly one ir.actions.act_window for this model, unchanged."""
        actions = self.env['ir.actions.act_window'].search([('res_model', '=', 'edara.payment.schedule.line')])
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions.id, self.env.ref('property_managment.action_edara_payment_schedule_line').id)
        self.assertEqual(
            self.env.ref('property_managment.action_edara_payment_schedule_line').search_view_id.id,
            self.env.ref('property_managment.view_edara_payment_schedule_line_search').id)

    def test_no_global_web_list_view_modification(self):
        """The Phase 6.2 mistake this ticket forbids repeating: the compiled
        asset bundle must register this template as its OWN independent
        template (t-inherit-mode="primary"), never as a patch merged into
        the shared web.ListView template (t-inherit-mode="extension") - the
        latter would silently affect every other list view in the backend."""
        js_bundle = self.env['ir.qweb']._get_asset_bundle('web.assets_backend', css=False, js=True)
        js_content = ''.join(a.raw.decode('utf-8', errors='replace') for a in js_bundle.js())
        self.assertIn('registerTemplate("property_managment.PaymentScheduleFilterShortcutsListView"', js_content)
        self.assertNotIn('registerTemplateExtension("web.ListView"', js_content)

    def test_other_list_views_remain_unaffected(self):
        """Regression pin: this feature must not leak js_class onto any
        other EDARA list view (Units/Contracts already re-verified free of
        their own removed Phase 6.2 js_class elsewhere; this pins the new
        one specifically)."""
        self.assertNotIn(
            'edara_payment_schedule_filter_shortcuts',
            self.env['edara.property'].get_view(view_type='list')['arch'])
        self.assertNotIn(
            'edara_payment_schedule_filter_shortcuts',
            self.env['edara.building'].get_view(view_type='list')['arch'])
        self.assertNotIn(
            'edara_payment_schedule_filter_shortcuts',
            self.env['edara.unit'].get_view(
                view_id=self.env.ref('property_managment.view_edara_unit_list').id)['arch'])
        self.assertNotIn(
            'edara_payment_schedule_filter_shortcuts',
            self.env['edara.lease.contract'].get_view(
                view_id=self.env.ref('property_managment.view_edara_lease_contract_list').id)['arch'])

    def test_lease_contract_list_view_has_no_js_class_at_all(self):
        """Phase 6.6 Hotfix regression pin: the browser-reported
        KeyNotFoundError also affected Lease Contracts. Direct psql
        inspection during the hotfix investigation confirmed the database's
        arch_db for this view never actually carried the Payment Schedule
        js_class - this test pins that finding permanently so a future
        change can't silently reintroduce a cross-view js_class leak."""
        arch = self.env['edara.lease.contract'].get_view(
            view_id=self.env.ref('property_managment.view_edara_lease_contract_list').id)['arch']
        self.assertNotIn('js_class=', arch)

    def test_no_unintended_view_references_the_js_class_anywhere(self):
        """Full-database sweep (not just the handful of views spot-checked
        elsewhere): exactly one ir.ui.view in the whole system may reference
        edara_payment_schedule_filter_shortcuts - the Payment Schedule list
        itself."""
        views = self.env['ir.ui.view'].search([('arch_db', 'like', 'edara_payment_schedule_filter_shortcuts')])
        self.assertEqual(views.mapped('name'), ['edara.payment.schedule.line.list'])

    def test_shortcut_buttons_color_mapping_and_semantic_classes(self):
        """Ticket 4: buttons must use semantic Bootstrap classes (draft -> secondary,
        paid -> success, overdue -> danger) and must not regress to uniform btn-primary."""
        base_dir = os.path.dirname(__file__)
        js_path = os.path.normpath(os.path.join(
            base_dir, '..', 'static', 'src', 'js', 'payment_schedule_filter_shortcuts.js'))
        with open(js_path, 'r', encoding='utf-8') as f:
            js_source = f.read()
        xml_path = os.path.normpath(os.path.join(
            base_dir, '..', 'static', 'src', 'js', 'payment_schedule_filter_shortcuts.xml'))
        with open(xml_path, 'r', encoding='utf-8') as f:
            xml_source = f.read()

        # JS mapping contains all 3 states mapped to their required semantic classes
        self.assertIn('draft: "secondary"', js_source)
        self.assertIn('paid: "success"', js_source)
        self.assertIn('overdue: "danger"', js_source)

        # XML template uses dynamic semantic class binding, not hardcoded btn-primary
        self.assertIn("'btn-' + item.color", xml_source)
        self.assertIn("'btn-outline-' + item.color", xml_source)
        self.assertNotIn("'btn-primary' : 'btn-outline-primary'", xml_source)

    def test_payment_schedule_counts_respect_branch_security_rules(self):
        """Ticket 4: Payment schedule grouped state counts must strictly respect
        user ACLs and record rules (branch visibility). A branch-scoped viewer must
        only see and count records in their permitted branch, while a company manager
        sees the broader population."""
        branch_a = self.env['edara.branch'].create({'name': 'Security Branch A', 'code': 'SBA'})
        branch_b = self.env['edara.branch'].create({'name': 'Security Branch B', 'code': 'SBB'})

        prop_a = self.env['edara.property'].create({'name': 'Prop A', 'code': 'PA', 'branch_id': branch_a.id})
        prop_b = self.env['edara.property'].create({'name': 'Prop B', 'code': 'PB', 'branch_id': branch_b.id})

        bld_a = self.env['edara.building'].create({'name': 'Bld A', 'code': 'BA', 'property_id': prop_a.id})
        bld_b = self.env['edara.building'].create({'name': 'Bld B', 'code': 'BB', 'property_id': prop_b.id})

        unit_a = self.env['edara.unit'].create({'name': 'Unit A', 'code': 'UA', 'building_id': bld_a.id})
        unit_b = self.env['edara.unit'].create({'name': 'Unit B', 'code': 'UB', 'building_id': bld_b.id})

        tenant_a = self.env['res.partner'].create({'name': 'Sec Tenant A'})
        tenant_b = self.env['res.partner'].create({'name': 'Sec Tenant B'})

        contract_a = self.env['edara.lease.contract'].create({
            'unit_id': unit_a.id, 'tenant_id': tenant_a.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 3, 31),
            'rent_amount': 1000, 'deposit_required': False,
        })
        contract_b = self.env['edara.lease.contract'].create({
            'unit_id': unit_b.id, 'tenant_id': tenant_b.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 3, 31),
            'rent_amount': 1000, 'deposit_required': False,
        })
        contract_a.action_activate()
        contract_b.action_activate()

        lines_a = contract_a.schedule_line_ids
        lines_b = contract_b.schedule_line_ids
        self.assertEqual(len(lines_a), 3)
        self.assertEqual(len(lines_b), 3)

        # Distribute states deterministically
        lines_a[0].state = 'paid'
        lines_a[1].state = 'overdue'
        lines_a[2].state = 'draft'

        lines_b[0].state = 'paid'
        lines_b[1].state = 'paid'
        lines_b[2].state = 'overdue'

        viewer = new_test_user(
            self.env, login='edara_sec_viewer', groups='property_managment.group_edara_viewer')
        branch_a.user_ids = [(4, viewer.id)]

        manager = new_test_user(
            self.env, login='edara_sec_manager', groups='property_managment.group_edara_company_manager')

        # 1. Branch-scoped viewer isolation
        viewer_model = self.env['edara.payment.schedule.line'].with_user(viewer)
        viewer_visible = viewer_model.search([])
        # Viewer sees branch A records only, none of branch B
        self.assertTrue(all(line.branch_id == branch_a for line in viewer_visible))
        self.assertFalse(any(line.branch_id == branch_b for line in viewer_visible))

        # Grouped counts via read_group respect record rules
        viewer_grouped = viewer_model.read_group([], ['state'], ['state'])
        viewer_counts = {g['state']: g['state_count'] for g in viewer_grouped}
        self.assertEqual(viewer_counts.get('paid', 0), 1)
        self.assertEqual(viewer_counts.get('overdue', 0), 1)
        self.assertEqual(viewer_counts.get('draft', 0), 1)

        # Grouped counts via web_read_group (used by client ORM) also respect record rules
        viewer_web_groups = viewer_model.web_read_group([], ['state'], ['__count'])['groups']
        viewer_web_counts = {g['state']: g['__count'] for g in viewer_web_groups}
        self.assertEqual(viewer_web_counts.get('paid', 0), 1)
        self.assertEqual(viewer_web_counts.get('overdue', 0), 1)
        self.assertEqual(viewer_web_counts.get('draft', 0), 1)

        # 2. Company manager sees records from all branches
        manager_model = self.env['edara.payment.schedule.line'].with_user(manager)
        test_line_ids = (lines_a + lines_b).ids
        manager_test_lines = manager_model.search([('id', 'in', test_line_ids)])
        self.assertEqual(len(manager_test_lines), 6)

        manager_grouped = manager_model.read_group([('id', 'in', test_line_ids)], ['state'], ['state'])
        manager_counts = {g['state']: g['state_count'] for g in manager_grouped}
        self.assertEqual(manager_counts.get('paid', 0), 3)    # 1 from A + 2 from B
        self.assertEqual(manager_counts.get('overdue', 0), 2) # 1 from A + 1 from B
        self.assertEqual(manager_counts.get('draft', 0), 1)   # 1 from A + 0 from B

