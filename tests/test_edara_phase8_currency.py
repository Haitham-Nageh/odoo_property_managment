from datetime import date

from odoo.tests import TransactionCase, tagged

OLD_DATE = date(2020, 1, 1)
OLD_RATE = 3.0    # foreign units per 1 company-currency unit, valid from OLD_DATE
NEW_RATE = 4.0    # ... valid from today
# Controlled rates keep every expectation exact: 1000/4 = 250, 200/4 = 50, 3000/3 = 1000, ...


@tagged('post_install', '-at_install')
class TestEdaraPhase8Currency(TransactionCase):
    """Phase 8 - Currency Correctness. Every flow that hands an amount to native
    Accounting is verified for ILS, USD and JOD (whichever one is the company
    currency acts as the same-currency case), with deterministic exchange rates
    created by the test itself. Assertions inspect the posted journal items
    (currency_id / amount_currency / balance), not only the EDARA document."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        E = cls.env
        cls.company = E.company
        cls.company_cur = cls.company.currency_id
        cls.today = date.today()
        cls.currencies = {}
        for code in ('ILS', 'USD', 'JOD'):
            cur = E['res.currency'].with_context(active_test=False).search([('name', '=', code)])
            cur.active = True
            cls.currencies[code] = cur
            if cur != cls.company_cur:
                E['res.currency.rate'].search([('currency_id', '=', cur.id), ('company_id', '=', cls.company.id)]).unlink()
                for d, r in ((OLD_DATE, OLD_RATE), (cls.today, NEW_RATE)):
                    E['res.currency.rate'].create(
                        {'currency_id': cur.id, 'company_id': cls.company.id, 'name': d, 'rate': r})
        cls.branch = E['edara.branch'].create({'name': 'P8 Branch', 'code': 'P8B'})
        cls.property = E['edara.property'].create({'name': 'P8 Property', 'code': 'P8P', 'branch_id': cls.branch.id})
        cls.building = E['edara.building'].create({'name': 'P8 Building', 'code': 'P8BL', 'property_id': cls.property.id})
        acc = E['account.account']
        cls.a_rent = acc.create({'name': 'P8 Rent', 'code': '408001', 'account_type': 'income'})
        cls.a_late = acc.create({'name': 'P8 Late', 'code': '408002', 'account_type': 'income'})
        cls.a_svc = acc.create({'name': 'P8 Svc', 'code': '408003', 'account_type': 'income'})
        cls.a_ded = acc.create({'name': 'P8 Ded', 'code': '408004', 'account_type': 'income_other'})
        cls.a_liab = acc.create({'name': 'P8 Deposit Liability', 'code': '238001', 'account_type': 'liability_current'})
        cls.a_exp = acc.create({'name': 'P8 Maint', 'code': '608001', 'account_type': 'expense'})
        cls.company.write({
            'edara_rental_income_account_id': cls.a_rent.id, 'edara_late_fee_income_account_id': cls.a_late.id,
            'edara_service_charge_income_account_id': cls.a_svc.id,
            'edara_deposit_deduction_income_account_id': cls.a_ded.id,
            'edara_deposit_liability_account_id': cls.a_liab.id,
            'edara_maintenance_expense_account_id': cls.a_exp.id, 'edara_late_fee_amount': 60.0})
        cls.bank = E['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1) \
            or E['account.journal'].create({'name': 'P8 Bank', 'code': 'P8BK', 'type': 'bank'})
        cls.vendor = E['res.partner'].create({'name': 'P8 Vendor'})
        cls.fx = {}   # code -> dict(unit, tenant)
        for i, code in enumerate(cls.currencies):
            cls.fx[code] = {
                'unit': E['edara.unit'].create({'name': 'P8-%s' % code, 'code': 'P8%d' % i, 'building_id': cls.building.id}),
                'tenant': E['res.partner'].create({'name': 'P8 Tenant %s' % code}),
            }

    # ---------------- helpers ----------------
    def _rate(self, cur, on_old=False):
        if cur == self.company_cur:
            return 1.0
        return OLD_RATE if on_old else NEW_RATE

    def _conv(self, amount, cur, on_old=False):
        """foreign amount -> company currency using the controlled rate"""
        return self.company_cur.round(amount / self._rate(cur, on_old))

    def _contract(self, code, **kw):
        vals = {'unit_id': self.fx[code]['unit'].id, 'tenant_id': self.fx[code]['tenant'].id,
                'currency_id': self.currencies[code].id, 'start_date': date(2026, 3, 1), 'end_date': date(2026, 4, 1),
                'rent_amount': 3000, 'deposit_required': True, 'deposit_amount': 1000}
        vals.update(kw)
        contract = self.env['edara.lease.contract'].create(vals)
        contract.action_activate()
        return contract

    def _deposit(self, code):
        contract = self._contract(code)
        return self.env['edara.deposit'].create({'contract_id': contract.id, 'amount': 1000})

    def _liability_lines(self, deposit):
        moves = deposit.transaction_ids.payment_id.move_id | deposit.transaction_ids.move_id
        return moves.line_ids.filtered(lambda l: l.account_id == self.a_liab)

    # ---------------- Deposit: collect -> deduct -> refund ----------------
    def test_deposit_full_lifecycle_nets_to_zero_in_every_currency(self):
        for code, cur in self.currencies.items():
            deposit = self._deposit(code)
            deposit.action_collect(self.bank.id, 1000)
            deposit.action_deduct(200, 'damage')
            deposit.action_refund(self.bank.id, 800)
            lines = self._liability_lines(deposit)
            self.assertEqual(len(lines), 3, code)
            self.assertEqual(sum(lines.mapped('amount_currency')), 0.0, code + ' amount_currency')
            self.assertAlmostEqual(sum(lines.mapped('balance')), 0.0, places=2, msg=code + ' balance')
            self.assertEqual(deposit.state, 'closed')

    def test_deposit_deduction_entry_is_foreign_currency_correct(self):
        for code, cur in self.currencies.items():
            deposit = self._deposit(code)
            deposit.action_collect(self.bank.id, 1000)
            move = deposit.action_deduct(200, 'damage')
            self.assertEqual(move.state, 'posted')
            liab = move.line_ids.filtered(lambda l: l.account_id == self.a_liab)
            inc = move.line_ids.filtered(lambda l: l.account_id == self.a_ded)
            self.assertEqual(liab.currency_id, cur, code)
            self.assertEqual(inc.currency_id, cur, code)
            self.assertEqual(liab.amount_currency, 200.0, code)
            self.assertEqual(inc.amount_currency, -200.0, code)
            expected = self._conv(200, cur)      # rate valid TODAY (NEW_RATE), not the 2020 rate
            self.assertAlmostEqual(liab.debit, expected, places=2, msg=code)
            self.assertAlmostEqual(inc.credit, expected, places=2, msg=code)
            self.assertEqual(liab.partner_id, deposit.tenant_id)
            self.assertEqual(move.company_id, self.company)
            self.assertEqual(move.date, self.today)
            self.assertEqual(sum(move.line_ids.mapped('balance')), 0.0)

    def test_partial_deduction_leaves_correct_converted_liability(self):
        for code, cur in self.currencies.items():
            deposit = self._deposit(code)
            deposit.action_collect(self.bank.id, 1000)
            deposit.action_deduct(200, 'damage')
            lines = self._liability_lines(deposit)
            self.assertEqual(sum(lines.mapped('amount_currency')), -800.0, code)
            self.assertAlmostEqual(sum(lines.mapped('balance')), -self._conv(800, cur), places=2, msg=code)
            self.assertEqual(deposit.balance, 800.0)

    def test_deposit_payments_carry_deposit_currency(self):
        for code, cur in self.currencies.items():
            deposit = self._deposit(code)
            pay = deposit.action_collect(self.bank.id, 1000)
            self.assertEqual(pay.currency_id, cur)
            line = pay.move_id.line_ids.filtered(lambda l: l.account_id == self.a_liab)
            self.assertEqual(line.currency_id, cur)
            self.assertEqual(line.amount_currency, -1000.0)
            self.assertAlmostEqual(line.credit, self._conv(1000, cur), places=2)

    # ---------------- Late fee ----------------
    def test_late_fee_is_configured_company_amount_converted_to_contract_currency(self):
        for code, cur in self.currencies.items():
            contract = self._contract(code, deposit_required=False, deposit_amount=0)
            line = contract.schedule_line_ids[0]
            self.assertEqual(line.state, 'overdue')
            fee = line.action_charge_late_fee()
            self.assertEqual(fee.currency_id, cur, code)
            # 60 company-currency units -> contract currency at today's controlled rate
            self.assertEqual(fee.amount_total, cur.round(60.0 * self._rate(cur)), code)
            # and its company-currency value is exactly the configured fee
            self.assertAlmostEqual(fee.amount_total_signed, 60.0, places=2, msg=code)
            self.assertEqual(fee.partner_id, self.fx[code]['tenant'])
            self.assertEqual(fee.invoice_line_ids.account_id, self.a_late)

    # ---------------- Rent ----------------
    def test_rent_invoice_uses_contract_currency_and_due_date_rate(self):
        for code, cur in self.currencies.items():
            contract = self._contract(code, deposit_required=False, deposit_amount=0)
            line = contract.schedule_line_ids[0]
            inv = line._create_invoice()
            self.assertEqual(inv.currency_id, cur, code)
            self.assertEqual(inv.amount_total, 3000.0)
            self.assertEqual(inv.invoice_date, date(2026, 3, 1))
            # rate at the invoice (due) date: the 2020 rate, not today's
            self.assertAlmostEqual(inv.amount_total_signed, self._conv(3000, cur, on_old=True), places=2, msg=code)
            self.assertEqual(inv.invoice_line_ids.analytic_distribution,
                             {str(self.property.analytic_account_id.id): 100.0})
            self.assertEqual(inv.company_id, self.company)
            self.assertEqual(inv.journal_id.type, 'sale')

    def test_rent_invoice_payment_reconciles_in_every_currency(self):
        for code, cur in self.currencies.items():
            contract = self._contract(code, deposit_required=False, deposit_amount=0)
            inv = contract.schedule_line_ids[0]._create_invoice()
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=inv.ids).create({'journal_id': self.bank.id})._create_payments()
            self.assertIn(inv.payment_state, ('paid', 'in_payment'), code)
            self.assertEqual(inv.amount_residual, 0.0, code)

    # ---------------- Service charge ----------------
    def test_service_charge_invoice_in_charge_currency(self):
        for code, cur in self.currencies.items():
            building = self.env['edara.building'].create(
                {'name': 'P8 SB %s' % code, 'code': 'SB%s' % code, 'property_id': self.property.id})
            unit = self.env['edara.unit'].create({'name': 'SB-%s' % code, 'code': 'SB%s' % code, 'building_id': building.id})
            self.env['edara.lease.contract'].create({
                'unit_id': unit.id, 'tenant_id': self.fx[code]['tenant'].id, 'start_date': date(2026, 3, 1),
                'end_date': date(2027, 3, 1), 'rent_amount': 100, 'deposit_required': False,
                'currency_id': cur.id}).action_activate()
            charge = self.env['edara.service.charge'].create({
                'building_id': building.id, 'total_amount': 1200, 'allocation_method': 'equal', 'currency_id': cur.id})
            charge.action_generate_allocation()
            charge.action_invoice_lines()
            inv = charge.line_ids.invoice_id
            self.assertEqual(inv.currency_id, cur, code)
            self.assertEqual(inv.amount_total, 1200.0)
            self.assertAlmostEqual(inv.amount_total_signed, self._conv(1200, cur), places=2, msg=code)
            self.assertEqual(inv.invoice_line_ids.analytic_distribution,
                             {str(self.property.analytic_account_id.id): 100.0})

    # ---------------- Maintenance vendor bill ----------------
    def test_maintenance_bill_currency_balance_and_analytics(self):
        for code, cur in self.currencies.items():
            request = self.env['edara.maintenance.request'].create({
                'title': 'P8 fix', 'unit_id': self.fx[code]['unit'].id, 'cost': 800, 'vendor_id': self.vendor.id,
                'currency_id': cur.id})
            bill = request.action_create_vendor_bill()
            bill.invoice_date = self.today
            bill.action_post()
            self.assertEqual(bill.currency_id, cur, code)
            self.assertEqual(bill.amount_total, 800.0)
            self.assertAlmostEqual(-bill.amount_total_signed, self._conv(800, cur), places=2, msg=code)
            expense = bill.line_ids.filtered(lambda l: l.account_id == self.a_exp)
            self.assertEqual(expense.currency_id, cur)
            self.assertEqual(expense.amount_currency, 800.0)
            self.assertAlmostEqual(expense.debit, self._conv(800, cur), places=2, msg=code)
            self.assertEqual(expense.analytic_distribution, {str(self.property.analytic_account_id.id): 100.0})
            alines = self.env['account.analytic.line'].search([('move_line_id', '=', expense.id)])
            self.assertAlmostEqual(-alines.amount, self._conv(800, cur), places=2, msg=code)

    # ---------------- Portal outstanding ----------------
    def test_portal_outstanding_uses_company_currency_signed_residuals(self):
        code = next(c for c, cur in self.currencies.items() if cur != self.company_cur)
        contract = self._contract(code, deposit_required=False, deposit_amount=0)
        inv = contract.schedule_line_ids[0]._create_invoice()
        moves = self.env['account.move'].search([('partner_id', '=', self.fx[code]['tenant'].id), ('state', '=', 'posted')])
        self.assertNotEqual(sum(moves.mapped('amount_residual')), sum(moves.mapped('amount_residual_signed')))
        self.assertAlmostEqual(sum(moves.mapped('amount_residual_signed')), self._conv(3000, self.currencies[code], on_old=True),
                               places=2)
        self.assertTrue(inv)
