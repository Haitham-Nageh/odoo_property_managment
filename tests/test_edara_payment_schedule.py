from datetime import date

from dateutil.relativedelta import relativedelta

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
            'payment_day': 15,
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
        self.assertTrue(all(line.amount == 1000 for line in contract.schedule_line_ids))

    def test_invoice_blocked_without_income_account(self):
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

    def test_cron_is_idempotent_and_only_invoices_due_lines(self):
        self.env.company.edara_rental_income_account_id = self.income_account.id
        today = date.today()
        payment_day = min(today.day, 28)
        start_date = (today - relativedelta(months=2)).replace(day=payment_day)
        contract = self._make_contract(
            start_date=start_date, end_date=today + relativedelta(years=1), payment_day=payment_day)
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
        contract = self._make_contract(
            start_date=start_date, end_date=today + relativedelta(years=1), payment_day=payment_day)
        contract.action_activate()

        past_or_today_count = len(contract.schedule_line_ids.filtered(lambda l: l.due_date <= today))
        contract.action_terminate('Tenant moved out')

        self.assertEqual(len(contract.schedule_line_ids), past_or_today_count)
        self.assertTrue(all(line.due_date <= today for line in contract.schedule_line_ids))

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
            start_date=date.today(), end_date=date.today() + relativedelta(years=1),
            payment_day=min(date.today().day, 28))
        contract.action_activate()
        line = contract.schedule_line_ids.filtered(lambda l: l.state != 'overdue')[0]
        with self.assertRaises(UserError):
            line.action_charge_late_fee()

    def test_late_fee_blocked_without_income_account(self):
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
