from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraDeposit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Nablus Branch', 'code': 'NBL'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Rafidia Towers', 'code': 'RAF', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Building A', 'code': 'A', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'A-301', 'code': '301', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Layla Hasan'})
        cls.contract = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit.id,
            'tenant_id': cls.tenant.id,
            'start_date': date(2026, 1, 1),
            'end_date': date(2026, 12, 31),
            'rent_amount': 1200,
            'deposit_required': True,
            'deposit_amount': 500,
        })
        cls.contract.action_activate()

        cls.cash_account = cls.env['account.account'].create({
            'name': 'Cash (Deposit Test)', 'code': '101900', 'account_type': 'asset_cash',
        })
        cls.cash_journal = cls.env['account.journal'].create({
            'name': 'Cash (Deposit Test)', 'type': 'cash', 'code': 'DEPC',
            'default_account_id': cls.cash_account.id,
        })
        cls.liability_account = cls.env['account.account'].create({
            'name': 'Deposit Liability (Test)', 'code': '211900', 'account_type': 'liability_current',
        })
        cls.deduction_income_account = cls.env['account.account'].create({
            'name': 'Damage Recovery Income (Test)', 'code': '401900', 'account_type': 'income_other',
        })

    def _make_deposit(self):
        return self.contract.action_view_deposit() and self.env['edara.deposit'].search(
            [('contract_id', '=', self.contract.id)], limit=1)

    def test_collection_blocked_without_liability_account(self):
        deposit = self._make_deposit()
        with self.assertRaises(UserError):
            deposit.action_collect(self.cash_journal.id, 500)

    def test_collect_creates_payment_and_updates_balance(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        payment = deposit.action_collect(self.cash_journal.id, 500)
        # Whether a cash-journal payment lands directly on 'paid' or goes through
        # 'in_process' pending reconciliation is a native Odoo accounting detail
        # unrelated to this feature; what we're verifying is the destination
        # account redirect and the deposit balance/state bookkeeping.
        self.assertIn(payment.state, ('in_process', 'paid'))
        self.assertEqual(payment.destination_account_id, self.liability_account)
        self.assertEqual(deposit.amount_held, 500)
        self.assertEqual(deposit.balance, 500)
        self.assertEqual(deposit.state, 'held')

    def test_refund_reduces_balance_and_closes_when_fully_refunded(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)

        deposit.action_refund(self.cash_journal.id, 200)
        self.assertEqual(deposit.balance, 300)
        self.assertEqual(deposit.state, 'held')

        deposit.action_refund(self.cash_journal.id, 300)
        self.assertEqual(deposit.balance, 0)
        self.assertEqual(deposit.state, 'closed')

    def test_cannot_refund_more_than_balance(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)
        with self.assertRaises(UserError):
            deposit.action_refund(self.cash_journal.id, 600)

    def test_deduction_blocked_without_income_account(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)
        with self.assertRaises(UserError):
            deposit.action_deduct(100, 'Broken window')

    def test_deduction_posts_journal_entry_and_reduces_balance(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        self.env.company.edara_deposit_deduction_income_account_id = self.deduction_income_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)

        move = deposit.action_deduct(150, 'Broken window')
        self.assertEqual(move.state, 'posted')
        liability_line = move.line_ids.filtered(lambda l: l.account_id == self.liability_account)
        income_line = move.line_ids.filtered(lambda l: l.account_id == self.deduction_income_account)
        self.assertEqual(liability_line.debit, 150)
        self.assertEqual(income_line.credit, 150)
        self.assertEqual(deposit.balance, 350)
        self.assertEqual(deposit.state, 'held')

    def test_deposit_transaction_cannot_be_deleted(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)
        with self.assertRaises(UserError):
            deposit.transaction_ids.unlink()
