from datetime import date

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestEdaraPhase7Hardening(TransactionCase):
    """Phase 7 (Enterprise Hardening): server-side protection of system-managed
    fields, maintenance vendor-bill currency/analytics, early-renewal billing.
    Every test builds its own isolated fixture (no dependence on pre-existing data)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        E = cls.env
        cls.branch = E['edara.branch'].create({'name': 'P7 Branch A', 'code': 'P7A'})
        cls.other_branch = E['edara.branch'].create({'name': 'P7 Branch B', 'code': 'P7B'})
        cls.property = E['edara.property'].create({'name': 'P7 Property', 'code': 'P7P', 'branch_id': cls.branch.id})
        cls.building = E['edara.building'].create({'name': 'P7 Building', 'code': 'P7BL', 'property_id': cls.property.id})
        cls.unit = E['edara.unit'].create({'name': 'P7-101', 'code': 'P7101', 'building_id': cls.building.id})
        cls.unit2 = E['edara.unit'].create({'name': 'P7-102', 'code': 'P7102', 'building_id': cls.building.id})
        cls.tenant = E['res.partner'].create({'name': 'P7 Tenant'})
        cls.vendor = E['res.partner'].create({'name': 'P7 Vendor'})
        cls.manager = new_test_user(E, login='p7_bm', groups='property_managment.group_edara_branch_manager')
        cls.viewer = new_test_user(E, login='p7_viewer', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [Command.link(cls.manager.id), Command.link(cls.viewer.id)]
        company = E.company
        cls.income = E['account.account'].create({'name': 'P7 Income', 'code': '407001', 'account_type': 'income'})
        cls.expense = E['account.account'].create({'name': 'P7 Expense', 'code': '607001', 'account_type': 'expense'})
        company.edara_rental_income_account_id = cls.income
        company.edara_maintenance_expense_account_id = cls.expense
        if not E['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', company.id)]):
            E['account.journal'].create({'name': 'P7 Bank', 'code': 'P7BK', 'type': 'bank'})

    def _contract(self, unit=None, **kw):
        vals = {'unit_id': (unit or self.unit).id, 'tenant_id': self.tenant.id, 'start_date': date(2026, 1, 1),
                'end_date': date(2026, 7, 1), 'rent_amount': 1000, 'deposit_required': False}
        vals.update(kw)
        return self.env['edara.lease.contract'].create(vals)

    # ============ Defect 1: system-managed fields ============

    def test_unit_branch_id_not_writable_but_normal_fields_are(self):
        unit = self.unit.with_user(self.manager)
        with self.assertRaises(AccessError):
            unit.write({'branch_id': self.other_branch.id})
        # RPC-style entry point used by the web client
        with self.assertRaises(AccessError):
            unit.web_save({'branch_id': self.other_branch.id}, {'id': {}})
        unit.write({'floor': '4', 'area': 88.0})
        self.assertEqual(self.unit.floor, '4')
        self.assertEqual(self.unit.branch_id, self.branch)

    def test_client_supplied_derived_values_ignored_on_create(self):
        unit = self.env['edara.unit'].with_user(self.manager).create({
            'name': 'P7-X', 'code': 'P7X', 'building_id': self.building.id, 'branch_id': self.other_branch.id})
        self.assertEqual(unit.branch_id, self.branch)

    def test_contract_company_and_state_not_writable(self):
        contract = self._contract().with_user(self.manager)
        with self.assertRaises(AccessError):
            contract.write({'company_id': self.env['res.company'].create({'name': 'P7 Other Co'}).id})
        with self.assertRaises(AccessError):
            contract.write({'state': 'terminated'})
        with self.assertRaises(AccessError):
            contract.web_save({'state': 'active'}, {'id': {}})
        contract.write({'notes': 'ok'})
        self.assertEqual(self.env['edara.lease.contract'].browse(contract.id).state, 'draft')

    def test_contract_lifecycle_still_works_for_branch_manager(self):
        contract = self._contract().with_user(self.manager)
        contract.action_activate()
        self.assertEqual(contract.state, 'active')
        renewed = contract.action_renew(date(2026, 7, 1), date(2027, 7, 1), 1100)
        self.assertEqual(contract.state, 'renewed')
        self.assertEqual(renewed.state, 'active')
        renewed.action_terminate(reason='test')
        self.assertEqual(renewed.state, 'terminated')

    def test_viewer_cannot_drive_lifecycle_even_though_it_uses_sudo(self):
        contract = self._contract()
        with self.assertRaises(AccessError):
            contract.with_user(self.viewer).action_activate()
        self.assertEqual(contract.state, 'draft')
        contract.action_activate()
        with self.assertRaises(AccessError):
            contract.with_user(self.viewer).action_terminate()
        with self.assertRaises(AccessError):
            contract.with_user(self.viewer).action_renew(date(2026, 7, 1), date(2027, 7, 1), 1)

    def test_schedule_line_amount_frozen_once_invoiced_invoice_id_always_protected(self):
        contract = self._contract()
        contract.action_activate()
        line, other = contract.schedule_line_ids[0], contract.schedule_line_ids[1]
        line_m = line.with_user(self.manager)
        line_m.write({'amount': 1234.0})  # uninvoiced: intentionally editable in the views
        self.assertEqual(line.amount, 1234.0)
        with self.assertRaises(AccessError):
            line_m.write({'invoice_id': 1})
        line_m._create_invoice()  # legitimate system flow (check_access + scoped sudo)
        self.assertTrue(line.invoice_id)
        with self.assertRaises(AccessError):
            line_m.write({'amount': 1.0})
        with self.assertRaises(AccessError):
            line_m.write({'invoice_id': other.id})
        with self.assertRaises(AccessError):
            line_m.web_save({'invoice_id': False}, {'id': {}})
        self.assertEqual(line.amount, 1234.0)
        other.with_user(self.manager).write({'amount': 999.0})  # sibling uninvoiced line unaffected

    def test_derived_fields_of_schedule_line_not_writable(self):
        contract = self._contract()
        contract.action_activate()
        with self.assertRaises(AccessError):
            contract.schedule_line_ids[:1].with_user(self.manager).write({'branch_id': self.other_branch.id})

    def test_context_flag_cannot_bypass_guard(self):
        with self.assertRaises(AccessError):
            self.unit.with_user(self.manager).with_context(edara_system_write=True, active_test=False).write(
                {'branch_id': self.other_branch.id})

    def test_superuser_internal_writes_still_allowed(self):
        self.unit.write({'branch_id': self.branch.id})  # test env is su, like crons/system flows
        contract = self._contract()
        contract.state = 'active'
        self.assertEqual(contract.state, 'active')

    # ============ Defects 2 & 3: maintenance vendor bill ============

    def _bill(self, currency, cost=200.0, **kw):
        request = self.env['edara.maintenance.request'].with_user(self.manager).create({
            'title': 'P7 leak', 'unit_id': self.unit.id, 'tenant_id': self.tenant.id, 'cost': cost,
            'vendor_id': self.vendor.id, 'currency_id': currency.id, **kw})
        bill_id = request.action_create_vendor_bill().id
        return self.env['account.move'].browse(bill_id)

    def test_vendor_bill_follows_request_currency_ils_usd_jod(self):
        for code in ('ILS', 'USD', 'JOD'):
            currency = self.env['res.currency'].with_context(active_test=False).search([('name', '=', code)])
            currency.active = True
            bill = self._bill(currency, cost=200.0)
            self.assertEqual(bill.currency_id, currency, code)
            self.assertEqual(bill.amount_total, 200.0, code)
            self.assertEqual(bill.partner_id, self.vendor)
            self.assertEqual(bill.company_id, self.env.company)
            self.assertEqual(bill.journal_id.type, 'purchase')
            line = bill.invoice_line_ids
            self.assertEqual(line.account_id, self.expense)

    def test_vendor_bill_analytic_distribution_posts_to_property_analytic_account(self):
        currency = self.env.company.currency_id
        bill = self._bill(currency, cost=300.0)
        analytic = self.property.analytic_account_id
        self.assertTrue(analytic)
        self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(analytic.id): 100.0})
        bill.action_post()
        aline = self.env['account.analytic.line'].search([('move_line_id', 'in', bill.line_ids.ids)])
        self.assertEqual(len(aline), 1)
        self.assertEqual(aline.amount, -300.0)
        self.assertEqual(aline[analytic.plan_id._column_name()], analytic)
        # native payment still reconciles - no parallel ledger
        journal = self.env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', bill.company_id.id)], limit=1)
        self.env['account.payment.register'].with_context(active_model='account.move', active_ids=bill.ids).create(
            {'journal_id': journal.id})._create_payments()
        self.assertIn(bill.payment_state, ('paid', 'in_payment'))

    def test_analytic_distribution_not_applied_to_unrelated_vendor_bills(self):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.vendor.id, 'invoice_date': date(2026, 3, 1),
            'invoice_line_ids': [Command.create({'name': 'x', 'quantity': 1, 'price_unit': 10, 'account_id': self.expense.id})]})
        self.assertFalse(bill.invoice_line_ids.analytic_distribution)

    # ============ Defect 4: early renewal ============

    def test_renewed_contract_remaining_periods_are_still_billed(self):
        today = date.today()
        contract = self._contract(start_date=date(today.year - 1, 1, 1), end_date=date(today.year + 1, 1, 1))
        contract.action_activate()
        contract.action_renew(date(today.year + 1, 1, 1), date(today.year + 2, 1, 1), 1100)  # successor starts at old end
        self.assertEqual(contract.state, 'renewed')
        due = contract.schedule_line_ids.filtered(lambda l: l.due_date <= today and not l.invoice_id)
        self.assertTrue(due)
        created, skipped, errors = due._process_due_invoices()
        self.assertEqual((created, errors), (len(due), 0))
        # no revenue gap and no duplicate: no line of the old contract was dropped, none invoiced twice
        self.assertEqual(len(contract.schedule_line_ids), 24)
        self.assertEqual(len(contract.schedule_line_ids.invoice_id), len(due))

    def test_overlapping_renewal_drops_only_periods_successor_covers(self):
        contract = self._contract(start_date=date(2026, 1, 1), end_date=date(2027, 1, 1))
        contract.action_activate()
        self.assertEqual(len(contract.schedule_line_ids), 12)
        successor = contract.action_renew(date(2026, 7, 1), date(2027, 7, 1), 1100)
        remaining = contract.schedule_line_ids
        self.assertEqual(len(remaining), 6)  # Jan..Jun stay billable to the old contract
        self.assertEqual(max(remaining.mapped('period_end')), date(2026, 7, 1))
        self.assertEqual(min(successor.schedule_line_ids.mapped('period_start')), date(2026, 7, 1))

    def test_terminated_and_expired_contracts_still_not_invoiced(self):
        contract = self._contract(start_date=date(2025, 1, 1), end_date=date(2026, 1, 1))
        contract.action_activate()
        contract.state = 'terminated'
        created, skipped, errors = contract.schedule_line_ids._process_due_invoices()
        self.assertEqual((created, errors), (0, 0))
