from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


def _build_billing_fixture(cls, suffix):
    """Shared fixture builder: branch/property/building/unit/tenant/contract
    plus every EDARA-configured accounting account the four MAT-FIND-015
    workflows need, and a single Cash journal. `suffix` keeps codes unique
    across the several classes in this file (each gets its own branch, so
    isolation tests stay meaningful)."""
    cls.branch = cls.env['edara.branch'].create({'name': 'MAT-015 Branch %s' % suffix, 'code': 'M15B%s' % suffix})
    cls.property = cls.env['edara.property'].create(
        {'name': 'MAT-015 Property %s' % suffix, 'code': 'M15P%s' % suffix, 'branch_id': cls.branch.id})
    cls.building = cls.env['edara.building'].create(
        {'name': 'MAT-015 Building %s' % suffix, 'code': 'M15L%s' % suffix, 'property_id': cls.property.id})
    cls.unit = cls.env['edara.unit'].create(
        {'name': 'MAT-015 Unit %s' % suffix, 'code': 'M15U%s' % suffix, 'building_id': cls.building.id})
    cls.tenant = cls.env['res.partner'].create({'name': 'MAT-015 Tenant %s' % suffix})
    cls.contract = cls.env['edara.lease.contract'].create({
        'unit_id': cls.unit.id, 'tenant_id': cls.tenant.id,
        'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
        'rent_amount': 1500, 'deposit_required': True, 'deposit_amount': 500,
    })
    cls.contract.action_activate()
    cls.contract.action_view_deposit()
    cls.deposit = cls.env['edara.deposit'].search([('contract_id', '=', cls.contract.id)], limit=1)

    cls.service_income_account = cls.env['account.account'].create(
        {'name': 'Service Charge Income (M015-%s)' % suffix, 'code': '4019%s0' % suffix, 'account_type': 'income'})
    cls.env.company.edara_service_charge_income_account_id = cls.service_income_account.id
    cls.late_fee_income_account = cls.env['account.account'].create(
        {'name': 'Late Fee Income (M015-%s)' % suffix, 'code': '4019%s1' % suffix, 'account_type': 'income'})
    cls.env.company.edara_late_fee_income_account_id = cls.late_fee_income_account.id
    cls.env.company.edara_late_fee_amount = 25.0
    cls.liability_account = cls.env['account.account'].create(
        {'name': 'Deposit Liability (M015-%s)' % suffix, 'code': '2119%s0' % suffix,
         'account_type': 'liability_current'})
    cls.env.company.edara_deposit_liability_account_id = cls.liability_account.id
    cls.deduction_income_account = cls.env['account.account'].create(
        {'name': 'Deposit Deduction Income (M015-%s)' % suffix, 'code': '4019%s2' % suffix,
         'account_type': 'income_other'})
    cls.env.company.edara_deposit_deduction_income_account_id = cls.deduction_income_account.id

    cls.cash_account = cls.env['account.account'].create(
        {'name': 'Cash (M015-%s)' % suffix, 'code': '1019%s0' % suffix, 'account_type': 'asset_cash'})
    cls.cash_journal = cls.env['account.journal'].create({
        'name': 'Cash (M015-%s)' % suffix, 'type': 'cash', 'code': 'M15C%s' % suffix,
        'default_account_id': cls.cash_account.id,
    })


@tagged('post_install', '-at_install')
class TestMatFind015ScopedInvoicing(TransactionCase):
    """MAT-FIND-015 implementation: Service Charge invoicing and Late Fee
    charging must succeed for an EDARA-only Company Manager (no native
    Accounting group at all) via narrow, scoped elevation - and must still
    be denied to a Viewer, at the EDARA authorization layer, before any
    elevation is ever reached."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _build_billing_fixture(cls, '1')
        cls.company_manager = new_test_user(
            cls.env, login='edara_cm_m015_1', groups='property_managment.group_edara_company_manager')
        cls.viewer = new_test_user(
            cls.env, login='edara_viewer_m015_1', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [(4, cls.viewer.id)]

    def test_company_manager_can_invoice_service_charge_without_native_group(self):
        self.assertFalse(self.env['account.move'].with_user(self.company_manager).has_access('create'))
        charge = self.env['edara.service.charge'].with_user(self.company_manager).create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.with_user(self.company_manager).action_generate_allocation()
        charge.with_user(self.company_manager).action_invoice_lines()
        line = charge.line_ids
        self.assertTrue(line.invoice_id)
        # Verified through the test's own (privileged) env, never through the
        # EDARA-only user's env - proves the workflow really posted a real
        # native invoice, without needing the calling user to be able to
        # read it back directly (see TestMatFind015NoBroadNativeAccess).
        invoice = self.env['account.move'].browse(line.invoice_id.id)
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.edara_invoice_type, 'service_charge')

    def test_viewer_cannot_create_service_charge(self):
        with self.assertRaises(AccessError):
            self.env['edara.service.charge'].with_user(self.viewer).create(
                {'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300})

    def test_viewer_cannot_invoice_an_existing_service_charge_line_directly(self):
        """Even if a Viewer somehow obtains a real line id (e.g. by RPC),
        _create_invoice()'s explicit check_access('write') must block them
        before the scoped account.move elevation is ever reached."""
        charge = self.env['edara.service.charge'].create(
            {'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300})
        charge.action_generate_allocation()
        line = charge.line_ids
        moves_before = self.env['account.move'].search_count([])
        with self.assertRaises(AccessError):
            line.with_user(self.viewer)._create_invoice()
        self.assertFalse(line.invoice_id)
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)

    def test_company_manager_can_charge_late_fee_without_native_group(self):
        line = self.contract.schedule_line_ids.filtered(lambda l: l.due_date < date(2026, 9, 1))[:1]
        if not line:
            line = self.contract.schedule_line_ids[:1]
            line.due_date = date(2026, 1, 1)
        self.assertEqual(line.state, 'overdue')
        invoice = line.with_user(self.company_manager).action_charge_late_fee()
        real_invoice = self.env['account.move'].browse(invoice.id)
        self.assertEqual(real_invoice.state, 'posted')
        self.assertEqual(real_invoice.edara_invoice_type, 'late_fee')

    def test_viewer_cannot_charge_late_fee(self):
        line = self.contract.schedule_line_ids[:1]
        line.due_date = date(2026, 1, 1)
        self.assertEqual(line.state, 'overdue')
        moves_before = self.env['account.move'].search_count([])
        with self.assertRaises(AccessError):
            line.with_user(self.viewer).action_charge_late_fee()
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)

    def test_analytic_account_first_time_creation_via_scoped_elevation(self):
        """The MAT-FIND-015 architecture analysis flagged that native
        Invoicing access alone does not cover account.analytic.account
        create - confirms the scoped elevation added to
        edara.property.get_analytic_account() actually creates one on first
        use, for a property that has never been invoiced before."""
        self.assertFalse(self.property.analytic_account_id)
        charge = self.env['edara.service.charge'].with_user(self.company_manager).create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.with_user(self.company_manager).action_generate_allocation()
        charge.with_user(self.company_manager).action_invoice_lines()
        self.assertTrue(self.property.analytic_account_id)

    def test_viewer_cannot_trigger_analytic_account_creation(self):
        analytic_before = self.env['account.analytic.account'].search_count([])
        with self.assertRaises(AccessError):
            self.property.with_user(self.viewer).get_analytic_account()
        self.assertFalse(self.property.analytic_account_id)
        self.assertEqual(self.env['account.analytic.account'].search_count([]), analytic_before)


@tagged('post_install', '-at_install')
class TestMatFind015ScopedDeposit(TransactionCase):
    """MAT-FIND-015 implementation: Deposit Collect/Refund/Deduct must
    succeed for an EDARA-only Accountant (no native Accounting group) via
    narrow, scoped elevation, while a Viewer remains fully blocked and no
    native record is ever created before EDARA's own authorization passes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _build_billing_fixture(cls, '2')
        cls.accountant = new_test_user(
            cls.env, login='edara_accountant_m015_2', groups='property_managment.group_edara_accountant')
        cls.branch.user_ids = [(4, cls.accountant.id)]
        cls.viewer = new_test_user(
            cls.env, login='edara_viewer_m015_2', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [(4, cls.viewer.id)]

    def test_accountant_can_collect_deposit_without_native_group(self):
        self.assertFalse(self.env['account.payment'].with_user(self.accountant).has_access('create'))
        payment = self.deposit.with_user(self.accountant).action_collect(self.cash_journal.id, 500)
        real_payment = self.env['account.payment'].browse(payment.id)
        self.assertIn(real_payment.state, ('in_process', 'paid'))
        self.assertEqual(self.deposit.balance, 500)

    def test_accountant_can_refund_deposit_without_native_group(self):
        self.deposit.action_collect(self.cash_journal.id, 500)
        payment = self.deposit.with_user(self.accountant).action_refund(self.cash_journal.id, 200)
        real_payment = self.env['account.payment'].browse(payment.id)
        self.assertIn(real_payment.state, ('in_process', 'paid'))
        self.assertEqual(self.deposit.balance, 300)

    def test_accountant_can_deduct_from_deposit_without_native_group(self):
        self.deposit.action_collect(self.cash_journal.id, 500)
        move = self.deposit.with_user(self.accountant).action_deduct(150, 'Broken window (MAT-FIND-015 test)')
        real_move = self.env['account.move'].browse(move.id)
        self.assertEqual(real_move.state, 'posted')
        self.assertEqual(self.deposit.balance, 350)

    def test_viewer_cannot_collect_deposit_and_no_orphan_payment_is_created(self):
        """The core authorization-first regression: before this fix,
        _create_deposit_payment() ran BEFORE the edara.deposit.transaction
        authorization check, so a Viewer's call would create a real
        account.payment and only fail afterwards. Confirms that no longer
        happens - the AccessError fires first, and zero payments exist."""
        payments_before = self.env['account.payment'].search_count([])
        transactions_before = self.env['edara.deposit.transaction'].search_count([])
        with self.assertRaises(AccessError):
            self.deposit.with_user(self.viewer).action_collect(self.cash_journal.id, 500)
        self.assertEqual(self.env['account.payment'].search_count([]), payments_before)
        self.assertEqual(self.env['edara.deposit.transaction'].search_count([]), transactions_before)
        self.assertEqual(self.deposit.balance, 0)

    def test_viewer_cannot_refund_deposit(self):
        self.deposit.action_collect(self.cash_journal.id, 500)
        payments_before = self.env['account.payment'].search_count([])
        with self.assertRaises(AccessError):
            self.deposit.with_user(self.viewer).action_refund(self.cash_journal.id, 200)
        self.assertEqual(self.env['account.payment'].search_count([]), payments_before)
        self.assertEqual(self.deposit.balance, 500)

    def test_viewer_cannot_deduct_from_deposit(self):
        self.deposit.action_collect(self.cash_journal.id, 500)
        moves_before = self.env['account.move'].search_count([])
        with self.assertRaises(AccessError):
            self.deposit.with_user(self.viewer).action_deduct(100, 'Should be denied')
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)
        self.assertEqual(self.deposit.balance, 500)


@tagged('post_install', '-at_install')
class TestMatFind015DepositWizardJournalResolution(TransactionCase):
    """MAT-FIND-015: the wizard's own journal auto-default must keep working
    for an EDARA-only user via a narrowly-scoped lookup (never a general
    account.journal browse grant), and the field must be locked (not just
    defaulted) when the user has no native journal access, so they are never
    handed a dropdown whose search would itself fail."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _build_billing_fixture(cls, '3')
        cls.accountant = new_test_user(
            cls.env, login='edara_accountant_m015_3', groups='property_managment.group_edara_accountant')
        cls.branch.user_ids = [(4, cls.accountant.id)]

    def test_wizard_resolves_journal_for_edara_only_user_when_unambiguous(self):
        matching = self.env['account.journal'].search([
            ('type', 'in', ('cash', 'bank')), ('company_id', '=', self.deposit.company_id.id),
        ])
        wizard = self.env['edara.deposit.transaction.wizard'].with_user(self.accountant).create({
            'deposit_id': self.deposit.id, 'transaction_type': 'held', 'amount': 0,
        })
        wizard._onchange_deposit_transaction_type()
        self.assertFalse(wizard.has_journal_browse_access)
        if len(matching) == 1:
            self.assertEqual(wizard.journal_id, matching)
        else:
            self.assertFalse(wizard.journal_id)

    def test_wizard_confirm_succeeds_end_to_end_for_edara_only_user(self):
        matching = self.env['account.journal'].search([
            ('type', 'in', ('cash', 'bank')), ('company_id', '=', self.deposit.company_id.id),
        ])
        if len(matching) != 1:
            self.skipTest('This company does not have exactly one Cash/Bank journal - '
                           'ambiguous case is covered separately.')
        wizard_form = Form(self.env['edara.deposit.transaction.wizard'].with_user(self.accountant).with_context(
            active_id=self.deposit.id, default_transaction_type='held'))
        wizard = wizard_form.save()
        wizard.action_confirm()
        self.assertEqual(self.deposit.balance, 500)

    def test_action_confirm_gives_clear_error_when_ambiguous_and_no_native_access(self):
        second_account = self.env['account.account'].create(
            {'name': 'Cash 2 (M015-3)', 'code': '101932', 'account_type': 'asset_cash'})
        self.env['account.journal'].create({
            'name': 'Cash 2 (M015-3)', 'type': 'cash', 'code': 'M15D3',
            'default_account_id': second_account.id,
        })
        wizard = self.env['edara.deposit.transaction.wizard'].with_user(self.accountant).create({
            'deposit_id': self.deposit.id, 'transaction_type': 'held', 'amount': 500,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()


@tagged('post_install', '-at_install')
class TestMatFind015NoBroadNativeAccess(TransactionCase):
    """MAT-FIND-015 explicit negative tests: after successfully completing
    every scoped workflow, the EDARA-only user must still have zero native
    Accounting capability beyond those exact narrow actions - no general
    account.move/account.payment/account.journal read, search, browse, or
    write. The scoped elevation must never become a hidden general grant."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _build_billing_fixture(cls, '4')
        cls.company_manager = new_test_user(
            cls.env, login='edara_cm_m015_4', groups='property_managment.group_edara_company_manager')

    def test_no_native_access_before_or_after_running_every_workflow(self):
        # account.account/account.tax are deliberately excluded from this
        # read check: base.group_user (every internal user, including every
        # EDARA role) already has native READ on them in stock Odoo - a
        # baseline, pre-existing default unrelated to MAT-FIND-015, since it
        # only exposes chart-of-accounts/tax *structure*, never transaction
        # data. The three models that actually gate transactional Accounting
        # capability - and that this scoped elevation must never leak
        # general access to - are account.move/account.payment/account.journal.
        transactional_models = ('account.move', 'account.payment', 'account.journal')
        for model in transactional_models:
            self.assertFalse(self.env[model].with_user(self.company_manager).has_access('read'),
                              '%s: should have no native read access before running any workflow' % model)
        for model in ('account.account', 'account.tax'):
            self.assertFalse(self.env[model].with_user(self.company_manager).has_access('create'),
                              '%s: create must stay Administrator-only' % model)
            self.assertFalse(self.env[model].with_user(self.company_manager).has_access('write'),
                              '%s: write must stay Administrator-only' % model)

        charge = self.env['edara.service.charge'].with_user(self.company_manager).create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.with_user(self.company_manager).action_generate_allocation()
        charge.with_user(self.company_manager).action_invoice_lines()
        self.deposit.with_user(self.company_manager).action_collect(self.cash_journal.id, 500)
        self.deposit.with_user(self.company_manager).action_deduct(50, 'Test deduction')

        for model in transactional_models:
            self.assertFalse(self.env[model].with_user(self.company_manager).has_access('read'),
                              '%s: scoped elevation must not have granted general read access' % model)
            self.assertFalse(self.env[model].with_user(self.company_manager).has_access('create'))
            self.assertFalse(self.env[model].with_user(self.company_manager).has_access('write'))
        for model in ('account.account', 'account.tax'):
            self.assertFalse(self.env[model].with_user(self.company_manager).has_access('create'))
            self.assertFalse(self.env[model].with_user(self.company_manager).has_access('write'))

        # With zero ACL groups granting read at all (not just a record-rule
        # restriction), search()/search_read()/read() all raise AccessError
        # immediately (search()'s own self.browse().check_access('read')
        # guard) rather than silently returning nothing - confirm that
        # explicitly too, on the real invoice this test created.
        invoice = charge.line_ids.invoice_id
        self.assertTrue(invoice)
        with self.assertRaises(AccessError):
            self.env['account.move'].with_user(self.company_manager).search([('id', '=', invoice.id)])
        with self.assertRaises(AccessError):
            invoice.with_user(self.company_manager).read(['name'])
        with self.assertRaises(AccessError):
            self.env['account.move'].with_user(self.company_manager).search_read([], ['name'])


@tagged('post_install', '-at_install')
class TestMatFind015CompanyIsolation(TransactionCase):
    """MAT-FIND-015: the scoped elevation must still respect EDARA's own
    company/branch isolation - a Company Manager of Company A must not be
    able to trigger a native Accounting operation against Company B's
    deposit/service-charge merely by knowing its id."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'MAT-FIND-015 Isolation Company B'})

        cls.branch_b = cls.env['edara.branch'].create(
            {'name': 'MAT-015 Company B Branch', 'code': 'M15ISOB', 'company_id': cls.company_b.id})
        cls.property_b = cls.env['edara.property'].create(
            {'name': 'MAT-015 Company B Property', 'code': 'M15ISOP', 'branch_id': cls.branch_b.id})
        cls.building_b = cls.env['edara.building'].create(
            {'name': 'MAT-015 Company B Building', 'code': 'M15ISOL', 'property_id': cls.property_b.id})
        cls.unit_b = cls.env['edara.unit'].create(
            {'name': 'MAT-015 Company B Unit', 'code': 'M15ISOU', 'building_id': cls.building_b.id})
        cls.tenant_b = cls.env['res.partner'].create({'name': 'MAT-015 Company B Tenant'})
        cls.contract_b = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit_b.id, 'tenant_id': cls.tenant_b.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': 1000, 'deposit_required': True, 'deposit_amount': 500,
        })
        cls.contract_b.action_activate()
        cls.contract_b.action_view_deposit()
        cls.deposit_b = cls.env['edara.deposit'].search([('contract_id', '=', cls.contract_b.id)], limit=1)
        cls.service_charge_b = cls.env['edara.service.charge'].create(
            {'building_id': cls.building_b.id, 'allocation_method': 'equal', 'total_amount': 300})

        cls.company_manager_a = new_test_user(
            cls.env, login='edara_cm_m015_isolation_a',
            groups='property_managment.group_edara_company_manager',
            company_id=cls.company_a.id, company_ids=[(6, 0, [cls.company_a.id])])

    def test_company_a_manager_cannot_collect_company_b_deposit(self):
        with self.assertRaises(AccessError):
            self.deposit_b.with_user(self.company_manager_a).action_collect(1, 500)

    def test_company_a_manager_cannot_invoice_company_b_service_charge(self):
        self.service_charge_b.action_generate_allocation()
        line_b = self.service_charge_b.line_ids
        with self.assertRaises(AccessError):
            line_b.with_user(self.company_manager_a)._create_invoice()
