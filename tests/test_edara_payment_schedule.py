from datetime import date

from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


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

        # MAT-FIND-006: only strictly-overdue (due_date < today) uninvoiced lines
        # survive termination - a line due today or later is not yet overdue
        # (edara.payment.schedule.line._compute_state() computes it as 'draft',
        # not 'overdue') and is removed as a not-yet-due future obligation.
        overdue_count = len(contract.schedule_line_ids.filtered(lambda l: l.due_date < today))
        contract.action_terminate('Tenant moved out')

        self.assertEqual(len(contract.schedule_line_ids), overdue_count)
        self.assertTrue(all(line.due_date < today for line in contract.schedule_line_ids))
        self.assertTrue(all(line.state == 'overdue' for line in contract.schedule_line_ids))

        self.env['edara.payment.schedule.line']._cron_generate_due_invoices()
        self.assertFalse(any(line.invoice_id for line in contract.schedule_line_ids))

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
