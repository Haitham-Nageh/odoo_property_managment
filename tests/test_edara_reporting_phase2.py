from datetime import date, timedelta

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.property_managment.models.edara_dashboard import _expiring_soon_domain


def _today():
    return date.today()


@tagged('post_install', '-at_install')
class TestEdaraReportingPhase2Base(TransactionCase):
    """Reporting & Management Intelligence Expansion (2026-09-22)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Report2 Branch', 'code': 'RP2B'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Report2 Property', 'code': 'RP2P', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Report2 Building', 'code': 'RP2BL', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'RP2-101', 'code': 'RP2101', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Report2 Tenant'})

        cls.income_account = cls.env['account.account'].create(
            {'name': 'Rental Income (Report2)', 'code': '400960', 'account_type': 'income'})
        cls.expense_account = cls.env['account.account'].create(
            {'name': 'Maintenance Expense (Report2)', 'code': '601960', 'account_type': 'expense'})
        cls.vendor = cls.env['res.partner'].create({'name': 'Report2 Vendor'})

        cls.branch_manager = new_test_user(
            cls.env, login='edara_rp2_bm', groups='property_managment.group_edara_branch_manager')
        cls.branch.manager_id = cls.branch_manager
        cls.branch.user_ids = [(4, cls.branch_manager.id)]
        cls.viewer = new_test_user(
            cls.env, login='edara_rp2_viewer', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [(4, cls.viewer.id)]
        cls.accountant = new_test_user(
            cls.env, login='edara_rp2_accountant',
            groups='property_managment.group_edara_viewer,account.group_account_invoice')
        cls.branch.user_ids = [(4, cls.accountant.id)]

    def _make_contract(self, **overrides):
        vals = {
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': 1200, 'deposit_required': False,
        }
        vals.update(overrides)
        contract = self.env['edara.lease.contract'].create(vals)
        contract.action_activate()
        return contract

    def _make_maintenance_with_bill(self, cost=500, unit=None):
        """Returns the request re-browsed through the test's own (privileged,
        admin) env - never through the EDARA-only branch_manager's env - so
        callers can freely read vendor_bill_amount_total / manipulate the
        native account.move without hitting MAT-FIND-015's deliberate
        AccessError for a role with no native Accounting group. Matches the
        established convention in test_edara_maintenance_vendor_bill.py."""
        self.env.company.edara_maintenance_expense_account_id = self.expense_account.id
        request = self.env['edara.maintenance.request'].with_user(self.branch_manager).create({
            'title': 'Report2 Maintenance', 'unit_id': (unit or self.unit).id, 'tenant_id': self.tenant.id,
            'cost': cost, 'vendor_id': self.vendor.id,
        })
        bill_id = request.with_user(self.branch_manager).action_create_vendor_bill().id
        self.env['account.move'].browse(bill_id).action_post()
        return self.env['edara.maintenance.request'].browse(request.id)


@tagged('post_install', '-at_install')
class TestEdaraRentRoll(TestEdaraReportingPhase2Base):

    def test_monthly_equivalent_rent_monthly(self):
        contract = self._make_contract(rent_amount=1200, billing_frequency='monthly')
        self.assertAlmostEqual(contract.monthly_equivalent_rent, 1200)

    def test_monthly_equivalent_rent_quarterly(self):
        contract = self._make_contract(rent_amount=3000, billing_frequency='quarterly')
        self.assertAlmostEqual(contract.monthly_equivalent_rent, 1000)

    def test_monthly_equivalent_rent_yearly(self):
        contract = self._make_contract(rent_amount=12000, billing_frequency='yearly')
        self.assertAlmostEqual(contract.monthly_equivalent_rent, 1000)

    def test_monthly_equivalent_is_report_only_not_a_proration_input(self):
        """Phase 10.1 (RULE-07): the stored monthly_equivalent_rent is ROUNDED, so the schedule
        engine uses the exact rent / months instead - 1,000 per quarter is 333.333... a month,
        and 10 of January's 31 days is 107.53 (from the rounded 333.33 it would be 107.52)."""
        contract = self._make_contract(
            rent_amount=1000, billing_frequency='quarterly',
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 10))
        prorated_line = contract.schedule_line_ids[:1]
        self.assertTrue(prorated_line.is_prorated)
        self.assertEqual(contract.monthly_equivalent_rent, 333.33)
        self.assertEqual(prorated_line.amount, 107.53)

    def test_unit_occupancy_status_tracks_unit(self):
        contract = self._make_contract()
        self.assertEqual(contract.unit_occupancy_status, 'rented')
        self.assertEqual(contract.unit_occupancy_status, contract.unit_id.occupancy_status)

    def test_rent_roll_report_action_and_search_view_load(self):
        action = self.env.ref('property_managment.action_edara_rent_roll_report')
        self.assertEqual(action.res_model, 'edara.lease.contract')
        view = self.env['edara.lease.contract'].get_view(view_id=action.view_id.id, view_type='list')
        self.assertTrue(view.get('arch'))

    def test_rent_roll_lists_tenant_unit_lease_correctly(self):
        contract = self._make_contract()
        rows = self.env['edara.lease.contract'].search([('id', '=', contract.id)])
        self.assertEqual(rows.tenant_id, self.tenant)
        self.assertEqual(rows.unit_id, self.unit)
        self.assertEqual(rows.property_id, self.property)
        self.assertEqual(rows.branch_id, self.branch)

    def test_branch_manager_only_sees_own_branch_in_rent_roll(self):
        other_branch = self.env['edara.branch'].create({'name': 'Report2 Other Branch', 'code': 'RP2OB'})
        other_property = self.env['edara.property'].create(
            {'name': 'Report2 Other Property', 'code': 'RP2OP', 'branch_id': other_branch.id})
        other_building = self.env['edara.building'].create(
            {'name': 'Report2 Other Building', 'code': 'RP2OBL', 'property_id': other_property.id})
        other_unit = self.env['edara.unit'].create(
            {'name': 'RP2-OTH-101', 'code': 'RP2OTH101', 'building_id': other_building.id})
        other_tenant = self.env['res.partner'].create({'name': 'Other Branch Tenant'})
        other_contract = self.env['edara.lease.contract'].create({
            'unit_id': other_unit.id, 'tenant_id': other_tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 700,
            'deposit_required': False,
        })
        other_contract.action_activate()
        own_contract = self._make_contract()

        visible = self.env['edara.lease.contract'].with_user(self.branch_manager).search([])
        self.assertIn(own_contract.id, visible.ids)
        self.assertNotIn(other_contract.id, visible.ids)


@tagged('post_install', '-at_install')
class TestEdaraLeaseExpiryReport(TestEdaraReportingPhase2Base):

    def test_30_day_boundary_included(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=30))
        found = self.env['edara.lease.contract'].search([
            ('state', '=', 'active'),
            ('end_date', '>=', _today()), ('end_date', '<=', _today() + timedelta(days=30)),
        ])
        self.assertIn(contract.id, found.ids)

    def test_31_day_boundary_excluded(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=31))
        found = self.env['edara.lease.contract'].search([
            ('state', '=', 'active'),
            ('end_date', '>=', _today()), ('end_date', '<=', _today() + timedelta(days=30)),
        ])
        self.assertNotIn(contract.id, found.ids)

    def test_expired_lease_excluded_from_expiring_soon(self):
        contract = self._make_contract(
            start_date=date(2020, 1, 1), end_date=date(2020, 6, 30))
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(contract.state, 'expired')
        found = self.env['edara.lease.contract'].search([
            ('state', '=', 'active'),
            ('end_date', '>=', _today() - timedelta(days=3650)),
            ('end_date', '<=', _today() + timedelta(days=30)),
        ])
        self.assertNotIn(contract.id, found.ids)

    def test_draft_contract_excluded_from_expiring_soon(self):
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': _today(), 'end_date': _today() + timedelta(days=10), 'rent_amount': 900,
            'deposit_required': False,
        })
        found = self.env['edara.lease.contract'].search([
            ('state', '=', 'active'),
            ('end_date', '>=', _today()), ('end_date', '<=', _today() + timedelta(days=30)),
        ])
        self.assertNotIn(contract.id, found.ids)

    def test_lease_expiry_report_action_and_search_view_load(self):
        action = self.env.ref('property_managment.action_edara_lease_expiry_report')
        self.assertEqual(action.res_model, 'edara.lease.contract')
        view = self.env['edara.lease.contract'].get_view(view_id=action.view_id.id, view_type='list')
        self.assertTrue(view.get('arch'))
        self.assertTrue(action.search_view_id)

    def test_expiring_soon_search_filter_matches_dashboard_definition(self):
        """The report's own 'Expiring Soon (30d)' filter must select exactly
        the same records as BD-003's dashboard domain - one definition, not two."""
        eligible = self._make_contract(end_date=_today() + timedelta(days=25))
        ineligible = self._make_contract(
            unit_id=self.env['edara.unit'].create(
                {'name': 'RP2-102', 'code': 'RP2102', 'building_id': self.building.id}).id,
            end_date=_today() + timedelta(days=60))
        found = self.env['edara.lease.contract'].search(_expiring_soon_domain(_today()))
        self.assertIn(eligible.id, found.ids)
        self.assertNotIn(ineligible.id, found.ids)


@tagged('post_install', '-at_install')
class TestEdaraUnitPropertyBranchPerformance(TestEdaraReportingPhase2Base):

    def setUp(self):
        super().setUp()
        self.env.company.edara_rental_income_account_id = self.income_account.id

    def test_unit_financial_summary_revenue_and_maintenance_cost(self):
        contract = self._make_contract()
        line = contract.schedule_line_ids[:1]
        line._create_invoice()
        self._make_maintenance_with_bill(cost=300)

        unit = self.unit
        self.assertAlmostEqual(unit.total_revenue, contract.rent_amount)
        self.assertAlmostEqual(unit.maintenance_cost, 300)
        self.assertAlmostEqual(unit.total_expenses, 300)

    def test_unit_financial_summary_gated_for_viewer_without_accounting_access(self):
        contract = self._make_contract()
        contract.schedule_line_ids[:1]._create_invoice()
        unit = self.unit.with_user(self.viewer)
        self.assertFalse(unit.has_accounting_access)
        self.assertEqual(unit.total_revenue, 0.0)
        self.assertEqual(unit.maintenance_cost, 0.0)

    def test_property_maintenance_cost_matches_vendor_bill_no_double_count(self):
        self._make_maintenance_with_bill(cost=450)
        self.assertAlmostEqual(self.property.maintenance_cost, 450)
        # Included in, not added on top of, total_expenses.
        self.assertAlmostEqual(self.property.total_expenses, 450)

    def test_branch_maintenance_cost_aggregates_across_properties(self):
        second_property = self.env['edara.property'].create(
            {'name': 'Report2 Second Property', 'code': 'RP2P2', 'branch_id': self.branch.id})
        second_building = self.env['edara.building'].create(
            {'name': 'Report2 Second Building', 'code': 'RP2BL2', 'property_id': second_property.id})
        second_unit = self.env['edara.unit'].create(
            {'name': 'RP2-201', 'code': 'RP2201', 'building_id': second_building.id})
        self._make_maintenance_with_bill(cost=200)
        self._make_maintenance_with_bill(cost=150, unit=second_unit)
        self.assertAlmostEqual(self.branch.maintenance_cost, 350)

    def test_maintenance_request_cost_and_vendor_bill_amount_are_distinct(self):
        """No double counting: `cost` is the estimated amount entered before
        billing; `vendor_bill_amount_total` is the actual posted amount -
        they may legitimately differ, and reports must label them separately."""
        request = self._make_maintenance_with_bill(cost=500)
        self.assertEqual(request.cost, 500)
        self.assertEqual(request.vendor_bill_amount_total, 500)
        # Editing the posted bill's line price after the fact must not
        # silently change the request's own recorded estimate.
        request.vendor_bill_id.button_draft()
        request.vendor_bill_id.invoice_line_ids.price_unit = 600
        request.vendor_bill_id.action_post()
        self.assertEqual(request.cost, 500)
        self.assertAlmostEqual(request.vendor_bill_amount_total, 600)


@tagged('post_install', '-at_install')
class TestEdaraMaintenanceCostReport(TestEdaraReportingPhase2Base):

    def test_vendor_bill_amount_populated_when_bill_exists(self):
        request = self._make_maintenance_with_bill(cost=500)
        self.assertAlmostEqual(request.vendor_bill_amount_total, 500)

    def test_vendor_bill_amount_zero_when_no_bill(self):
        request = self.env['edara.maintenance.request'].create(
            {'title': 'No Bill Yet', 'unit_id': self.unit.id, 'tenant_id': self.tenant.id, 'cost': 200})
        self.assertEqual(request.vendor_bill_amount_total, 0.0)

    def test_vendor_bill_amount_degrades_to_zero_for_non_accounting_viewer(self):
        """MAT-FIND-014 pattern: never a raw AccessError, always a safe 0."""
        request = self._make_maintenance_with_bill(cost=500)
        viewer_view = request.with_user(self.viewer)
        self.assertFalse(viewer_view.has_accounting_access)
        self.assertEqual(viewer_view.vendor_bill_amount_total, 0.0)

    def test_maintenance_cost_report_action_loads(self):
        action = self.env.ref('property_managment.action_edara_maintenance_cost_report')
        self.assertEqual(action.res_model, 'edara.maintenance.request')
        self.assertEqual(action.view_mode, 'list')
        view = self.env['edara.maintenance.request'].get_view(view_id=action.view_id.id, view_type='list')
        self.assertTrue(view.get('arch'))

    def test_maintenance_cost_report_search_filters_by_vendor_bill_presence(self):
        with_bill = self._make_maintenance_with_bill(cost=300)
        without_bill = self.env['edara.maintenance.request'].create(
            {'title': 'No Bill', 'unit_id': self.unit.id, 'tenant_id': self.tenant.id})
        has_bill_results = self.env['edara.maintenance.request'].search([('vendor_bill_id', '!=', False)])
        self.assertIn(with_bill.id, has_bill_results.ids)
        self.assertNotIn(without_bill.id, has_bill_results.ids)


@tagged('post_install', '-at_install')
class TestEdaraInvoiceTypeReportFilter(TestEdaraReportingPhase2Base):

    def setUp(self):
        super().setUp()
        self.env.company.edara_rental_income_account_id = self.income_account.id

    def test_expenses_report_filtered_to_maintenance_matches_property_maintenance_cost(self):
        self._make_maintenance_with_bill(cost=275)
        action = self.env.ref('property_managment.action_edara_expense_report')
        moves = self.env['account.move'].search(
            safe_eval(action.domain) + [('edara_invoice_type', '=', 'maintenance')])
        self.assertEqual(len(moves), 1)
        self.assertAlmostEqual(moves.amount_untaxed, 275)

    def test_revenue_report_filtered_to_rent_excludes_maintenance(self):
        contract = self._make_contract()
        contract.schedule_line_ids[:1]._create_invoice()
        self._make_maintenance_with_bill(cost=100)
        action = self.env.ref('property_managment.action_edara_revenue_report')
        # Phase 6.4: action_edara_revenue_report's own domain is company-wide
        # by design (it's a real report, not scoped to one tenant) - this
        # shared dev database's real company may already have other real
        # posted rent/maintenance invoices for other tenants, so narrow to
        # this test's own tenant to assert what THIS test actually produced,
        # rather than assuming a clean company.
        rent_moves = self.env['account.move'].search(
            safe_eval(action.domain) + [('edara_invoice_type', '=', 'rent'), ('partner_id', '=', self.tenant.id)])
        self.assertEqual(len(rent_moves), 1)
        maintenance_in_revenue = self.env['account.move'].search(
            safe_eval(action.domain) + [('edara_invoice_type', '=', 'maintenance'), ('partner_id', '=', self.tenant.id)])
        self.assertFalse(maintenance_in_revenue)

    def test_edara_invoice_type_field_is_indexed(self):
        self.assertTrue(self.env['account.move']._fields['edara_invoice_type'].index)


@tagged('post_install', '-at_install')
class TestEdaraDashboardMaintenanceCostKpi(TestEdaraReportingPhase2Base):

    def test_maintenance_cost_this_month_computed(self):
        self._make_maintenance_with_bill(cost=350)
        dashboard = self.env['edara.dashboard'].create({})
        self.assertAlmostEqual(dashboard.maintenance_cost_this_month, 350)

    def test_maintenance_cost_this_month_excludes_other_months(self):
        """action_create_vendor_bill() always dates the bill today, so an
        older-month maintenance cost is created directly as an account.move
        (admin env) instead of backdating a posted bill after the fact -
        which native Odoo Accounting correctly rejects anyway (date-based
        vendor-bill sequences must stay chronologically consistent)."""
        self.env.company.edara_maintenance_expense_account_id = self.expense_account.id
        old_bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.vendor.id, 'invoice_date': date(2020, 1, 1),
            'edara_invoice_type': 'maintenance', 'edara_unit_id': self.unit.id,
            'edara_property_id': self.property.id, 'edara_branch_id': self.branch.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Old maintenance cost', 'quantity': 1, 'price_unit': 350,
                'account_id': self.expense_account.id,
            })],
        })
        old_bill.action_post()
        dashboard = self.env['edara.dashboard'].create({})
        self.assertEqual(dashboard.maintenance_cost_this_month, 0.0)

    def test_maintenance_cost_this_month_gated_for_viewer(self):
        self._make_maintenance_with_bill(cost=350)
        dashboard = self.env['edara.dashboard'].with_user(self.viewer).create({})
        self.assertFalse(dashboard.has_accounting_access)
        self.assertEqual(dashboard.maintenance_cost_this_month, 0.0)


@tagged('post_install', '-at_install')
class TestEdaraReportingSecurityIsolation(TestEdaraReportingPhase2Base):

    def test_portal_tenant_cannot_open_reports_menu_models_beyond_own_data(self):
        tenant_partner = self.env['res.partner'].create({'name': 'Report2 Portal Tenant'})
        tenant_user = new_test_user(
            self.env, login='edara_rp2_tenant', groups='property_managment.group_edara_portal_tenant',
            partner_id=tenant_partner.id)
        other_contract = self._make_contract()
        visible = self.env['edara.lease.contract'].with_user(tenant_user).search([])
        self.assertNotIn(other_contract.id, visible.ids)

    def test_cross_company_isolation_for_property_financial_summary(self):
        company_b = self.env['res.company'].create({'name': 'Report2 Company B'})
        branch_b = self.env['edara.branch'].create({'name': 'Report2 Branch B', 'code': 'RP2BB', 'company_id': company_b.id})
        property_b = self.env['edara.property'].create(
            {'name': 'Report2 Property B', 'code': 'RP2PB', 'branch_id': branch_b.id})
        # A user restricted to company A only must not be able to read company B's property record at all.
        user_a = new_test_user(
            self.env, login='edara_rp2_company_a', groups='property_managment.group_edara_company_manager',
            company_id=self.env.company.id, company_ids=[(6, 0, [self.env.company.id])])
        with self.assertRaises(AccessError):
            property_b.with_user(user_a).read(['maintenance_cost'])

    def test_viewer_sees_lease_expiry_report_only_for_assigned_branch(self):
        other_branch = self.env['edara.branch'].create({'name': 'Report2 Isolation Branch', 'code': 'RP2IB'})
        other_property = self.env['edara.property'].create(
            {'name': 'Report2 Isolation Property', 'code': 'RP2IP', 'branch_id': other_branch.id})
        other_building = self.env['edara.building'].create(
            {'name': 'Report2 Isolation Building', 'code': 'RP2IBL', 'property_id': other_property.id})
        other_unit = self.env['edara.unit'].create(
            {'name': 'RP2-ISO-101', 'code': 'RP2ISO101', 'building_id': other_building.id})
        other_tenant = self.env['res.partner'].create({'name': 'Isolation Tenant'})
        other_contract = self.env['edara.lease.contract'].create({
            'unit_id': other_unit.id, 'tenant_id': other_tenant.id,
            'start_date': _today(), 'end_date': _today() + timedelta(days=10), 'rent_amount': 800,
            'deposit_required': False,
        })
        other_contract.action_activate()
        own_contract = self._make_contract(end_date=_today() + timedelta(days=10))

        visible = self.env['edara.lease.contract'].with_user(self.viewer).search([('state', '=', 'active')])
        self.assertIn(own_contract.id, visible.ids)
        self.assertNotIn(other_contract.id, visible.ids)
