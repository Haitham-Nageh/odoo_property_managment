from datetime import date

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestEdaraInvoiceLinkExposure(TransactionCase):
    """MAT-031: empirical check (not assumed) of whether a Viewer reading an
    edara.payment.schedule.line that already has invoice_id set (pointing to
    account.move) trips an AccessError the same way MAT-FIND-014 did for the
    Dashboard - since a Viewer has read ACL on edara.payment.schedule.line
    but no native account.move access at all."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.income_account = cls.env['account.account'].create(
            {'name': 'Income (Security Test)', 'code': '402950', 'account_type': 'income'})
        cls.env.company.edara_rental_income_account_id = cls.income_account.id
        cls.branch = cls.env['edara.branch'].create({'name': 'Invoice Link Branch', 'code': 'INVLB'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Invoice Link Property', 'code': 'INVLP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Invoice Link Building', 'code': 'INVLBL', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create(
            {'name': 'Invoice Link Unit', 'code': 'INVLU', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Invoice Link Tenant'})
        cls.contract = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit.id, 'tenant_id': cls.tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': 1000, 'deposit_required': False,
        })
        cls.contract.action_activate()
        cls.line = cls.contract.schedule_line_ids[:1]
        cls.line.invoice_id = cls.line._create_invoice()

        cls.viewer = new_test_user(
            cls.env, login='edara_viewer_invlink', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [(4, cls.viewer.id)]

    def test_viewer_reading_schedule_line_with_invoice_set_does_not_crash(self):
        """The many2one's own foreign-key id lives on edara.payment.schedule.line's
        own row - reading it (list view / read()) does not require account.move
        access, only *dereferencing* a field on the related account.move record
        would. Confirms this is safe as-is; documented here so the assumption
        is proven, not left implicit."""
        line = self.line.with_user(self.viewer)
        data = line.read(['invoice_id', 'amount', 'state'])[0]
        self.assertTrue(data['invoice_id'])


@tagged('post_install', '-at_install')
class TestEdaraDashboardAndSummarySecurity(TransactionCase):
    """MAT-031 / MAT-FIND-014: a user without native Odoo Accounting read
    access must never hit a raw account.move/account.payment AccessError
    just from opening the EDARA Dashboard, a Property, or a Branch - those
    are ordinary Viewer-readable screens, not Accounting screens. Covers
    edara.dashboard._compute_kpis(), edara.property._compute_financial_summary()
    and edara.branch._compute_financial_summary()."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Security Branch', 'code': 'SECB'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Security Property', 'code': 'SECP', 'branch_id': cls.branch.id})

        cls.viewer = new_test_user(
            cls.env, login='edara_viewer_dash', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [(4, cls.viewer.id)]

        # A real accounting-capable user: an EDARA role PLUS the native Odoo
        # group that actually grants account.move/account.payment access
        # (account.group_account_invoice - the same one base.user_admin has
        # by default, which is why prior MAT sessions logged in as admin
        # never reproduced MAT-FIND-014).
        cls.accountant_with_native_access = new_test_user(
            cls.env, login='edara_accountant_native',
            groups='property_managment.group_edara_company_manager,account.group_account_invoice')

    def test_viewer_opens_dashboard_without_account_move_access_error(self):
        """The exact MAT-FIND-014 live reproduction: a Viewer must be able to
        open the Dashboard at all. Accounting-dependent KPIs degrade to a
        safe 0/False instead of crashing; non-accounting KPIs are unaffected."""
        dashboard = self.env['edara.dashboard'].with_user(self.viewer).create({})
        self.assertFalse(dashboard.has_accounting_access)
        self.assertEqual(dashboard.monthly_revenue, 0.0)
        self.assertEqual(dashboard.outstanding_receivables, 0.0)
        self.assertEqual(dashboard.recent_payments_count, 0)
        self.assertEqual(dashboard.total_properties, 1)

    def test_accounting_capable_user_sees_real_dashboard_kpis(self):
        dashboard = self.env['edara.dashboard'].with_user(self.accountant_with_native_access).create({})
        self.assertTrue(dashboard.has_accounting_access)

    def test_viewer_opens_property_without_account_move_access_error(self):
        prop = self.property.with_user(self.viewer)
        self.assertFalse(prop.has_accounting_access)
        self.assertEqual(prop.total_revenue, 0.0)
        self.assertEqual(prop.total_outstanding, 0.0)

    def test_viewer_opens_branch_without_account_move_access_error(self):
        branch = self.branch.with_user(self.viewer)
        self.assertFalse(branch.has_accounting_access)
        self.assertEqual(branch.total_revenue, 0.0)

    def test_accounting_capable_user_sees_real_property_financials(self):
        prop = self.property.with_user(self.accountant_with_native_access)
        self.assertTrue(prop.has_accounting_access)


@tagged('post_install', '-at_install')
class TestEdaraAccountingBoundaries(TransactionCase):
    """MAT-031: confirms the actual (not assumed) native Accounting access
    each EDARA role has out of the box - none of EDARA's own groups imply
    any native account.* group (grepped security/edara_security.xml), so
    holding an EDARA role alone is never sufficient for native Accounting
    access. Recorded in EDARA_PROJECT_STATE.md as a new observation for a
    future MAT, not something this pass changes."""

    def test_edara_viewer_has_no_account_move_access(self):
        user = new_test_user(self.env, login='edara_viewer_acct', groups='property_managment.group_edara_viewer')
        self.assertFalse(self.env['account.move'].with_user(user).has_access('read'))

    def test_edara_accountant_without_native_group_has_no_account_move_access(self):
        user = new_test_user(
            self.env, login='edara_accountant_only', groups='property_managment.group_edara_accountant')
        self.assertFalse(self.env['account.move'].with_user(user).has_access('read'))

    def test_edara_company_manager_without_native_group_has_no_account_move_access(self):
        user = new_test_user(
            self.env, login='edara_cm_only', groups='property_managment.group_edara_company_manager')
        self.assertFalse(self.env['account.move'].with_user(user).has_access('read'))

    def test_user_with_native_invoicing_group_has_account_move_access(self):
        user = new_test_user(
            self.env, login='edara_viewer_with_native',
            groups='property_managment.group_edara_viewer,account.group_account_invoice')
        self.assertTrue(self.env['account.move'].with_user(user).has_access('read'))


@tagged('post_install', '-at_install')
class TestEdaraViewerAclBoundaries(TransactionCase):
    """MAT-031: representative ORM-level proof (not just 'the menu exists')
    that the Viewer role's read-only ACL (ir.model.access.csv) is actually
    enforced by the ORM for create/write/unlink, on a representative sample
    of EDARA models rather than every single one (each model's own test
    file already exercises its full business-logic surface)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'ACL Branch', 'code': 'ACLB'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'ACL Property', 'code': 'ACLP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'ACL Building', 'code': 'ACLBL', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create(
            {'name': 'ACL Unit', 'code': 'ACLU', 'building_id': cls.building.id})
        cls.viewer = new_test_user(
            cls.env, login='edara_viewer_acl', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [(4, cls.viewer.id)]

    def test_viewer_cannot_create_property(self):
        with self.assertRaises(AccessError):
            self.env['edara.property'].with_user(self.viewer).create(
                {'name': 'Denied', 'code': 'DEN1', 'branch_id': self.branch.id})

    def test_viewer_cannot_write_unit(self):
        with self.assertRaises(AccessError):
            self.unit.with_user(self.viewer).write({'name': 'Renamed by Viewer'})

    def test_viewer_cannot_unlink_building(self):
        with self.assertRaises(AccessError):
            self.building.with_user(self.viewer).unlink()

    def test_viewer_can_read_authorized_unit(self):
        self.assertEqual(self.unit.with_user(self.viewer).code, 'ACLU')


@tagged('post_install', '-at_install')
class TestEdaraCompanyIsolationBroad(TransactionCase):
    """MAT-031: extends test_edara_multicompany.py's proof (that the
    company-manager 'sees all branches' rule stays company-scoped only
    because of the ANDed global multi-company rule) from edara.branch to
    every other model built on the identical 3-rule pattern in
    security/edara_record_rules.xml. Reuses that existing pattern rather
    than inventing a second isolation mechanism."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'EDARA Isolation Test Company B'})

        cls.branch_b = cls.env['edara.branch'].create(
            {'name': 'Company B Branch', 'code': 'ISOB', 'company_id': cls.company_b.id})
        cls.property_b = cls.env['edara.property'].create(
            {'name': 'Company B Property', 'code': 'ISOPB', 'branch_id': cls.branch_b.id})
        cls.building_b = cls.env['edara.building'].create(
            {'name': 'Company B Building', 'code': 'ISOBB', 'property_id': cls.property_b.id})
        cls.unit_b = cls.env['edara.unit'].create(
            {'name': 'Company B Unit', 'code': 'ISOU1', 'building_id': cls.building_b.id})
        cls.tenant_b = cls.env['res.partner'].create({'name': 'Company B Tenant'})
        cls.contract_b = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit_b.id, 'tenant_id': cls.tenant_b.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': 1000, 'deposit_required': True, 'deposit_amount': 500,
        })
        cls.contract_b.action_activate()
        cls.schedule_line_b = cls.contract_b.schedule_line_ids[:1]
        cls.contract_b.action_view_deposit()
        cls.deposit_b = cls.env['edara.deposit'].search([('contract_id', '=', cls.contract_b.id)], limit=1)
        cls.service_charge_b = cls.env['edara.service.charge'].create(
            {'building_id': cls.building_b.id, 'total_amount': 300})
        cls.maintenance_b = cls.env['edara.maintenance.request'].create(
            {'title': 'Company B Leak', 'unit_id': cls.unit_b.id, 'tenant_id': cls.tenant_b.id})
        cls.renewal_b = cls.env['edara.renewal.request'].create({
            'contract_id': cls.contract_b.id, 'requested_start_date': date(2027, 1, 1),
            'requested_end_date': date(2027, 12, 31), 'requested_rent_amount': 1100,
        })

        cls.company_manager_a = new_test_user(
            cls.env, login='edara_cm_isolation_a',
            groups='property_managment.group_edara_company_manager',
            company_id=cls.company_a.id, company_ids=[(6, 0, [cls.company_a.id])])

    def test_company_a_manager_cannot_search_or_read_company_b_records(self):
        cases = [
            ('edara.property', self.property_b),
            ('edara.building', self.building_b),
            ('edara.unit', self.unit_b),
            ('edara.lease.contract', self.contract_b),
            ('edara.payment.schedule.line', self.schedule_line_b),
            ('edara.deposit', self.deposit_b),
            ('edara.service.charge', self.service_charge_b),
            ('edara.maintenance.request', self.maintenance_b),
            ('edara.renewal.request', self.renewal_b),
        ]
        for model_name, record_b in cases:
            with self.subTest(model=model_name):
                self.assertTrue(record_b, "test setup for %s produced no record" % model_name)
                found = self.env[model_name].with_user(self.company_manager_a).search(
                    [('id', '=', record_b.id)])
                self.assertFalse(found, "%s: Company A manager should not find Company B's record via search()"
                                  % model_name)
                with self.assertRaises(
                        AccessError, msg="%s: Company A manager should not be able to read Company B's record"
                                          % model_name):
                    record_b.with_user(self.company_manager_a).read(['id'])
