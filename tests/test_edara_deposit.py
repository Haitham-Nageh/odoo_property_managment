from datetime import date

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


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
        # Phase 6.4: this shared dev database's real company may already have
        # edara_deposit_liability_account_id configured (real accounting
        # setup, not test data) - explicitly clear it for this negative test
        # rather than assuming a blank company, matching the positive tests'
        # own convention of setting company fields per-test.
        self.env.company.edara_deposit_liability_account_id = False
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
        # Phase 6.4: explicitly clear the deduction income account for this
        # negative test - the real company may already have one configured.
        self.env.company.edara_deposit_deduction_income_account_id = False
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

    def test_create_blocked_when_deposit_required_and_amount_zero(self):
        with self.assertRaises(ValidationError):
            self.env['edara.lease.contract'].create({
                'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
                'start_date': date(2027, 1, 1), 'end_date': date(2027, 12, 31),
                'rent_amount': 1000, 'deposit_required': True, 'deposit_amount': 0,
            })

    def test_activation_blocked_for_legacy_zero_deposit_contract(self):
        # The ORM constraint (tested above) makes it impossible to *create* an
        # invalid row through normal use, so the only way a deposit_required=True
        # / deposit_amount=0 contract can exist is legacy data predating this
        # validation (e.g. LC/2026/0003 before it was corrected) - simulate that
        # here with a raw SQL bypass to prove action_activate()'s guard is real
        # defense-in-depth, not dead code.
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': date(2027, 1, 1), 'end_date': date(2027, 12, 31),
            'rent_amount': 1000, 'deposit_required': False, 'deposit_amount': 0,
        })
        self.env.cr.execute(
            "UPDATE edara_lease_contract SET deposit_required = true WHERE id = %s", (contract.id,))
        contract.invalidate_recordset()
        with self.assertRaises(UserError):
            contract.action_activate()

    def test_deposit_not_required_allows_zero_amount(self):
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': date(2027, 1, 1), 'end_date': date(2027, 12, 31),
            'rent_amount': 1000, 'deposit_required': False, 'deposit_amount': 0,
        })
        contract.action_activate()
        self.assertEqual(contract.state, 'scheduled')   # start_date is in the future

    def test_deposit_amount_independent_of_rent_amount(self):
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': date(2027, 1, 1), 'end_date': date(2027, 12, 31),
            'rent_amount': 1200, 'deposit_required': True, 'deposit_amount': 800,
        })
        self.assertEqual(contract.rent_amount, 1200)
        self.assertEqual(contract.deposit_amount, 800)

    def test_deposit_amount_cannot_be_negative(self):
        with self.assertRaises(ValidationError):
            self.env['edara.deposit'].create({
                'contract_id': self.contract.id, 'amount': -100,
            })

    def test_deposit_creation_blocked_when_contract_requires_deposit_and_amount_zero(self):
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': date(2027, 1, 1), 'end_date': date(2027, 12, 31),
            'rent_amount': 1000, 'deposit_required': True, 'deposit_amount': 900,
        })
        with self.assertRaises(ValidationError):
            self.env['edara.deposit'].create({'contract_id': contract.id, 'amount': 0})

    def test_required_deposit_can_be_created_and_collected(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': date(2027, 1, 1), 'end_date': date(2027, 12, 31),
            'rent_amount': 1000, 'deposit_required': True, 'deposit_amount': 1500,
        })
        contract.action_activate()
        deposit = contract.action_view_deposit() and self.env['edara.deposit'].search(
            [('contract_id', '=', contract.id)], limit=1)
        self.assertEqual(deposit.amount, 1500)
        payment = deposit.action_collect(self.cash_journal.id, 1500)
        self.assertIn(payment.state, ('in_process', 'paid'))
        self.assertEqual(deposit.balance, 1500)
        self.assertEqual(deposit.state, 'held')

    # ===================== Chatter (Product Readiness Review, 2026-09-22) =====================
    # Spec §43 names Deposit alongside Property/Unit/Lease Contract/Maintenance
    # Request as a record that should carry chatter - it was the one business
    # model in the module missing mail.thread. Adding it must not change any
    # existing accounting/security behavior; the tests above (collection,
    # refund, deduction, unlink protection) already cover that regression
    # surface and are unaffected by this addition.

    def test_deposit_has_chatter_capability(self):
        deposit = self._make_deposit()
        self.assertTrue(hasattr(deposit, 'message_ids'))
        self.assertTrue(hasattr(deposit, 'message_follower_ids'))

    def test_authorized_user_can_post_message_on_deposit(self):
        deposit = self._make_deposit()
        message = deposit.message_post(body='Tenant confirmed move-out inspection date.')
        self.assertIn(message, deposit.message_ids)

    def test_state_field_configured_for_tracking(self):
        """state is a stored compute field (set via action_collect()/
        action_refund()/action_deduct()'s downstream recompute, not a
        direct write()), so this checks the field's own tracking=True
        configuration rather than asserting on a live chatter message -
        the latter depends on ORM compute-vs-write tracking internals
        unrelated to what this cleanup ticket is actually verifying."""
        self.assertTrue(self.env['edara.deposit']._fields['state'].tracking)

    def test_chatter_does_not_grant_extra_business_access_to_viewer(self):
        """Adding mail.thread must not widen edara.deposit's existing ACL/
        record-rule boundary - a Viewer can read (and, per native Odoo
        chatter behavior, comment on) a deposit exactly as before, but still
        cannot perform any deposit business action."""
        viewer = new_test_user(self.env, login='edara_dep_chatter_viewer', groups='property_managment.group_edara_viewer')
        self.branch.user_ids = [(4, viewer.id)]
        deposit = self._make_deposit()
        with self.assertRaises(AccessError):
            deposit.with_user(viewer).action_collect(self.cash_journal.id, 500)

    # -- MAT-FIND-001/002: deposit transaction wizard defaults --

    def test_wizard_defaults_collect_amount_to_remaining_uncollected(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        wizard_form = Form(self.env['edara.deposit.transaction.wizard'].with_context(
            active_id=deposit.id, default_transaction_type='held'))
        self.assertEqual(wizard_form.amount, 500)

    def test_wizard_defaults_refund_amount_to_balance(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)
        wizard_form = Form(self.env['edara.deposit.transaction.wizard'].with_context(
            active_id=deposit.id, default_transaction_type='refund'))
        self.assertEqual(wizard_form.amount, 500)

    def test_wizard_defaults_deduction_amount_to_balance(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)
        wizard_form = Form(self.env['edara.deposit.transaction.wizard'].with_context(
            active_id=deposit.id, default_transaction_type='deduction'))
        self.assertEqual(wizard_form.amount, 500)

    def test_wizard_amount_remains_editable_for_partial_refund(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)
        wizard_form = Form(self.env['edara.deposit.transaction.wizard'].with_context(
            active_id=deposit.id, default_transaction_type='refund'))
        self.assertEqual(wizard_form.amount, 500)
        wizard_form.amount = 200
        wizard_form.journal_id = self.cash_journal
        wizard = wizard_form.save()
        wizard.action_confirm()
        self.assertEqual(deposit.balance, 300)
        self.assertEqual(deposit.state, 'held')

    def test_wizard_amount_remains_editable_for_partial_deduction(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        self.env.company.edara_deposit_deduction_income_account_id = self.deduction_income_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)
        wizard_form = Form(self.env['edara.deposit.transaction.wizard'].with_context(
            active_id=deposit.id, default_transaction_type='deduction'))
        self.assertEqual(wizard_form.amount, 500)
        wizard_form.amount = 150
        wizard_form.description = 'Broken window'
        wizard = wizard_form.save()
        wizard.action_confirm()
        self.assertEqual(deposit.balance, 350)

    def test_wizard_defaults_journal_when_unambiguous(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        deposit = self._make_deposit()
        matching_journals = self.env['account.journal'].search([
            ('type', 'in', ('cash', 'bank')), ('company_id', '=', deposit.company_id.id),
        ])
        wizard_form = Form(self.env['edara.deposit.transaction.wizard'].with_context(
            active_id=deposit.id, default_transaction_type='held'))
        if len(matching_journals) == 1:
            self.assertEqual(wizard_form.journal_id, matching_journals)
        else:
            self.assertFalse(wizard_form.journal_id)

    def test_wizard_does_not_default_journal_for_deduction(self):
        self.env.company.edara_deposit_liability_account_id = self.liability_account.id
        self.env.company.edara_deposit_deduction_income_account_id = self.deduction_income_account.id
        deposit = self._make_deposit()
        deposit.action_collect(self.cash_journal.id, 500)
        wizard_form = Form(self.env['edara.deposit.transaction.wizard'].with_context(
            active_id=deposit.id, default_transaction_type='deduction'))
        self.assertFalse(wizard_form.journal_id)
