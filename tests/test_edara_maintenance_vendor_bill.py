from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestEdaraMaintenanceVendorBill(TransactionCase):
    """Maintenance Cost -> Native Accounting Integration (2026-09-22).
    BD-MNT-001: Vendor Bills are created manually only, never auto-created
    on completion. BD-MNT-002: cost>0 with no vendor must never block
    operational completion - only Create Vendor Bill itself requires a
    vendor. Follows the MAT-FIND-015 authorization-first, narrowly-scoped
    .sudo() pattern already proven for rent/late-fee/service-charge
    invoicing and deposit transactions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'MNT Branch', 'code': 'MNTB'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'MNT Property', 'code': 'MNTP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'MNT Building', 'code': 'MNTBL', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'MNT-101', 'code': 'MNT101', 'building_id': cls.building.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'Handy Repairs Co.'})

        cls.expense_account = cls.env['account.account'].create(
            {'name': 'Maintenance Expense (MNT)', 'code': '601910', 'account_type': 'expense'})
        cls.env.company.edara_maintenance_expense_account_id = cls.expense_account.id

        cls.branch_manager = new_test_user(
            cls.env, login='edara_mnt_bm', groups='property_managment.group_edara_branch_manager')
        cls.branch.user_ids = [(4, cls.branch_manager.id)]
        cls.viewer = new_test_user(
            cls.env, login='edara_mnt_viewer', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [(4, cls.viewer.id)]

        cls.tenant_partner = cls.env['res.partner'].create({'name': 'MNT Tenant'})
        cls.tenant_user = new_test_user(
            cls.env, login='edara_mnt_tenant', groups='property_managment.group_edara_portal_tenant',
            partner_id=cls.tenant_partner.id)

    def _make_request(self, **overrides):
        vals = {'title': 'Broken elevator', 'unit_id': self.unit.id, 'tenant_id': self.tenant_partner.id}
        vals.update(overrides)
        return self.env['edara.maintenance.request'].with_user(self.branch_manager).create(vals)

    # ===================== Creation =====================

    def test_valid_cost_and_vendor_creates_vendor_bill(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill = request.with_user(self.branch_manager).action_create_vendor_bill()
        self.assertTrue(bill)
        self.assertEqual(request.vendor_bill_id, bill)

    def test_vendor_bill_is_draft(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        # Re-browsed through the test's own (privileged) env, never through the
        # EDARA-only user's env - matches the established MAT-FIND-015 test
        # convention (see test_edara_mat015_scoped_accounting.py): the calling
        # user need not be able to read native accounting data back directly.
        bill = self.env['account.move'].browse(bill_id)
        self.assertEqual(bill.state, 'draft')

    def test_vendor_bill_correct_vendor(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        bill = self.env['account.move'].browse(bill_id)
        self.assertEqual(bill.partner_id, self.vendor)

    def test_vendor_bill_correct_amount(self):
        request = self._make_request(cost=350.5, vendor_id=self.vendor.id)
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        bill = self.env['account.move'].browse(bill_id)
        self.assertAlmostEqual(bill.amount_untaxed, 350.5)

    def test_vendor_bill_correct_expense_account(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        bill = self.env['account.move'].browse(bill_id)
        self.assertEqual(bill.invoice_line_ids.account_id, self.expense_account)

    def test_vendor_bill_correct_company_and_tags(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        bill = self.env['account.move'].browse(bill_id)
        self.assertEqual(bill.company_id, self.env.company)
        self.assertEqual(bill.move_type, 'in_invoice')
        self.assertEqual(bill.edara_invoice_type, 'maintenance')
        self.assertEqual(bill.edara_unit_id, self.unit)
        self.assertEqual(bill.edara_building_id, self.building)
        self.assertEqual(bill.edara_property_id, self.property)
        self.assertEqual(bill.edara_branch_id, self.branch)

    def test_maintenance_request_links_to_vendor_bill(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        request.with_user(self.branch_manager).action_create_vendor_bill()
        self.assertTrue(request.vendor_bill_id)
        bill = self.env['account.move'].browse(request.vendor_bill_id.id)
        self.assertEqual(bill.partner_id, self.vendor)

    def test_vendor_bill_reaches_property_financial_summary(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        # Posting requires real native Accounting rights (branch_manager has
        # none, by MAT-FIND-015 design - an actual accountant would post this
        # from their own, separately-privileged session), so this uses the
        # test's own admin env, exactly like every other posting test in this
        # module (e.g. test_edara_mat015_scoped_accounting.py).
        self.env['account.move'].browse(bill_id).action_post()
        self.assertAlmostEqual(self.property.total_expenses, 500)

    # ===================== Validation =====================

    def test_no_vendor_blocks_creation(self):
        request = self._make_request(cost=500)
        with self.assertRaises(UserError):
            request.with_user(self.branch_manager).action_create_vendor_bill()
        self.assertFalse(request.vendor_bill_id)

    def test_zero_cost_blocks_creation(self):
        request = self._make_request(cost=0, vendor_id=self.vendor.id)
        with self.assertRaises(UserError):
            request.with_user(self.branch_manager).action_create_vendor_bill()

    def test_negative_cost_blocked_at_field_level(self):
        """The pre-existing _check_cost constraint (see
        test_edara_maintenance_request.py::test_negative_cost_blocked)
        already rejects a negative cost at create()/write() time, so a
        negative-cost record can never exist to reach action_create_vendor_bill()
        in the first place."""
        with self.assertRaises(ValidationError):
            self._make_request(cost=-10, vendor_id=self.vendor.id)

    def test_missing_expense_account_blocks_creation(self):
        self.env.company.edara_maintenance_expense_account_id = False
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        with self.assertRaises(UserError):
            request.with_user(self.branch_manager).action_create_vendor_bill()

    def test_existing_linked_bill_prevents_duplicate(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        first_bill = request.with_user(self.branch_manager).action_create_vendor_bill()
        second_call = request.with_user(self.branch_manager).action_create_vendor_bill()
        self.assertEqual(second_call, first_bill)
        self.assertEqual(self.env['account.move'].search_count(
            [('edara_invoice_type', '=', 'maintenance'), ('edara_unit_id', '=', self.unit.id)]), 1)

    # ===================== Completion (BD-MNT-002) =====================

    def test_completion_allowed_with_zero_cost(self):
        request = self._make_request(cost=0)
        request.with_user(self.branch_manager).action_assign(self.branch_manager.id)
        request.with_user(self.branch_manager).action_complete()
        self.assertEqual(request.state, 'done')

    def test_completion_allowed_with_cost_and_vendor(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        request.with_user(self.branch_manager).action_assign(self.branch_manager.id)
        request.with_user(self.branch_manager).action_complete()
        self.assertEqual(request.state, 'done')

    def test_completion_allowed_with_cost_and_no_vendor(self):
        request = self._make_request(cost=500)
        request.with_user(self.branch_manager).action_assign(self.branch_manager.id)
        request.with_user(self.branch_manager).action_complete()
        self.assertEqual(request.state, 'done')
        self.assertFalse(request.vendor_id)
        self.assertFalse(request.vendor_bill_id)

    # ===================== Security =====================

    def test_authorized_user_can_create_vendor_bill(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill = request.with_user(self.branch_manager).action_create_vendor_bill()
        self.assertTrue(bill)

    def test_viewer_cannot_create_vendor_bill(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        with self.assertRaises(AccessError):
            request.with_user(self.viewer).action_create_vendor_bill()
        self.assertFalse(request.vendor_bill_id)

    def test_tenant_cannot_create_vendor_bill(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        with self.assertRaises(AccessError):
            request.with_user(self.tenant_user).action_create_vendor_bill()
        self.assertFalse(request.vendor_bill_id)

    def test_unauthorized_direct_method_invocation_blocked(self):
        """Server-side enforcement, not button visibility: calling the
        method directly (as an RPC caller would) is blocked identically to
        going through the UI."""
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        with self.assertRaises(AccessError):
            self.env['edara.maintenance.request'].with_user(self.viewer).browse(
                request.id).action_create_vendor_bill()

    def test_viewer_without_accounting_access_cannot_view_vendor_bill(self):
        """No EDARA role implies native Accounting group access (MAT-FIND-015);
        action_view_vendor_bill() must degrade to a clear UserError rather
        than a raw AccessError, even for the user who created the bill."""
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        request.with_user(self.branch_manager).action_create_vendor_bill()
        with self.assertRaises(UserError):
            request.with_user(self.branch_manager).action_view_vendor_bill()

    # ===================== Native accounting behavior =====================

    def test_bill_is_a_real_native_account_move(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        bill = self.env['account.move'].browse(bill_id)
        self.assertEqual(bill._name, 'account.move')
        self.assertEqual(bill.move_type, 'in_invoice')

    def test_posting_vendor_bill_follows_native_odoo_behavior(self):
        request = self._make_request(cost=500, vendor_id=self.vendor.id)
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        bill = self.env['account.move'].browse(bill_id)
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        debit_line = bill.line_ids.filtered(lambda l: l.account_id == self.expense_account)
        self.assertAlmostEqual(debit_line.debit, 500)
