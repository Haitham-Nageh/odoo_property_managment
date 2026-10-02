import json
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestEdaraDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Phase 6.4: the dashboard's KPI fields (total_properties,
        # total_units, ...) are intentionally whole-portfolio counts
        # (edara_dashboard.py's own _compute_kpis, no sudo(), plain
        # search_count([]) that fully respects the calling user's record
        # rules) - so an exact-count assertion like "total_units == 2" is
        # only valid for a user whose visibility is scoped to exactly what
        # THIS test created. Reading via cls.env (unrestricted) silently
        # included this shared dev database's real portfolio (1 real
        # property, 1 real building, 18 real units) once that real data
        # existed. cls.dash_admin is a company-manager scoped to an isolated
        # company (matching TestEdaraMultiCompany's established pattern) so
        # dashboard reads below see only what this class creates.
        cls.dash_company = cls.env['res.company'].create({'name': 'EDARA Dashboard Test Company'})
        cls.dash_admin = new_test_user(
            cls.env, login='edara_dash_admin', groups='property_managment.group_edara_company_manager',
            company_id=cls.dash_company.id, company_ids=[(6, 0, [cls.dash_company.id])])
        cls.branch = cls.env['edara.branch'].create(
            {'name': 'Dashboard Branch', 'code': 'DASH', 'company_id': cls.dash_company.id})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Dashboard Property', 'code': 'DBP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Dashboard Building', 'code': 'DB', 'property_id': cls.property.id})
        cls.unit_rented = cls.env['edara.unit'].create(
            {'name': 'D-101', 'code': 'D101', 'building_id': cls.building.id})
        cls.unit_vacant = cls.env['edara.unit'].create(
            {'name': 'D-102', 'code': 'D102', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Dashboard Tenant'})
        cls.contract = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit_rented.id, 'tenant_id': cls.tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 900,
            'deposit_required': False,
        })
        cls.contract.action_activate()

    def test_kpis_reflect_current_state(self):
        dashboard = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertEqual(dashboard.total_properties, 1)
        self.assertEqual(dashboard.total_buildings, 1)
        self.assertEqual(dashboard.total_units, 2)
        self.assertEqual(dashboard.occupied_units, 1)
        self.assertEqual(dashboard.available_units, 1)
        self.assertEqual(dashboard.under_maintenance_units, 0)

    def test_action_open_returns_form_action_with_a_fresh_record(self):
        action = self.env['edara.dashboard'].action_open()
        self.assertEqual(action['res_model'], 'edara.dashboard')
        self.assertTrue(action['res_id'])

    def test_dashboard_form_view_contains_container_fluid(self):
        """Phase 11.1 Follow-up: Dashboard wrapper must contain container-fluid to prevent horizontal overflow."""
        form_view = self.env['edara.dashboard'].get_view(view_type='form')
        self.assertIn('container-fluid', form_view['arch'])


    def test_dashboard_display_name_is_not_raw_model_id(self):
        """Dashboard UX Hardening 6.1 (2026-09-23): a TransientModel with no
        name/_rec_name field defaults display_name to "edara.dashboard,<id>"
        (orm/models.py _compute_display_name's fallback) - that raw
        technical string was showing up in the form breadcrumb."""
        dashboard = self.env['edara.dashboard'].create({})
        self.assertEqual(dashboard.name, 'EDARA Dashboard')
        self.assertNotIn(',', dashboard.display_name)
        self.assertEqual(dashboard.display_name, 'EDARA Dashboard')

    def test_available_units_kpi_excludes_reserved_owner_occupied_and_sold(self):
        """BD-001/MAT-FIND-010 (2026-09-21): available_units must count the
        canonical occupancy_status='available' state directly, not derive it
        by subtraction (total - occupied - under_maintenance), which used to
        silently miscount reserved/owner_occupied/sold units as available."""
        today = date.today()
        reserved_unit = self.env['edara.unit'].create(
            {'name': 'D-103', 'code': 'D103', 'building_id': self.building.id})
        future_tenant = self.env['res.partner'].create({'name': 'Future Dashboard Tenant'})
        future_contract = self.env['edara.lease.contract'].create({
            'unit_id': reserved_unit.id, 'tenant_id': future_tenant.id,
            'start_date': today + timedelta(days=30), 'end_date': today + timedelta(days=395),
            'rent_amount': 900, 'deposit_required': False,
        })
        future_contract.action_activate()
        self.assertEqual(reserved_unit.occupancy_status, 'reserved')

        self.env['edara.unit'].create(
            {'name': 'D-104', 'code': 'D104', 'building_id': self.building.id,
             'occupancy_status': 'owner_occupied'})
        self.env['edara.unit'].create(
            {'name': 'D-105', 'code': 'D105', 'building_id': self.building.id,
             'occupancy_status': 'sold'})

        dashboard = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertEqual(dashboard.total_units, 5)
        self.assertEqual(dashboard.occupied_units, 1)
        # Only unit_vacant (from setUpClass) is genuinely available - reserved,
        # owner_occupied, and sold must all be excluded.
        self.assertEqual(dashboard.available_units, 1)

    # -- MAT/UI-032 (2026-09-22): expanded KPI fields --

    def test_unit_kpi_fields_cover_all_occupancy_states(self):
        """The new dedicated reserved_units/owner_occupied_units/sold_units
        fields (as opposed to the available_units-only check above)."""
        today = date.today()
        future_tenant = self.env['res.partner'].create({'name': 'KPI Future Tenant'})
        reserved_unit = self.env['edara.unit'].create(
            {'name': 'D-110', 'code': 'D110', 'building_id': self.building.id})
        future_contract = self.env['edara.lease.contract'].create({
            'unit_id': reserved_unit.id, 'tenant_id': future_tenant.id,
            'start_date': today + timedelta(days=30), 'end_date': today + timedelta(days=395),
            'rent_amount': 900, 'deposit_required': False,
        })
        future_contract.action_activate()
        self.env['edara.unit'].create(
            {'name': 'D-111', 'code': 'D111', 'building_id': self.building.id,
             'occupancy_status': 'owner_occupied'})
        self.env['edara.unit'].create(
            {'name': 'D-112', 'code': 'D112', 'building_id': self.building.id,
             'occupancy_status': 'sold'})
        # A unit cannot be operational_status='under_maintenance' while
        # occupancy_status='available' (pre-existing constraint,
        # _check_status_consistency) - use a real active lease so it's
        # 'rented' first, demonstrating that occupancy and operational
        # status are independent dimensions rather than trying (and being
        # correctly rejected) to combine under_maintenance with available.
        maintenance_unit = self.unit_rented
        maintenance_unit.operational_status = 'under_maintenance'

        dashboard = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertEqual(dashboard.reserved_units, 1)
        self.assertEqual(dashboard.owner_occupied_units, 1)
        self.assertEqual(dashboard.sold_units, 1)
        self.assertEqual(dashboard.under_maintenance_units, 1)
        # operational_status is independent of occupancy_status - unit_rented
        # is still 'rented' occupancy-wise even while under maintenance, and
        # must not be double-counted or excluded from either dimension.
        self.assertEqual(maintenance_unit.occupancy_status, 'rented')
        self.assertEqual(dashboard.occupied_units, 1)
        self.assertEqual(dashboard.available_units, 1)  # unit_vacant only

    def test_contract_state_kpis(self):
        today = date.today()
        tenant2 = self.env['res.partner'].create({'name': 'KPI Contract Tenant'})

        draft_unit = self.env['edara.unit'].create(
            {'name': 'D-106', 'code': 'D106', 'building_id': self.building.id})
        self.env['edara.lease.contract'].create({
            'unit_id': draft_unit.id, 'tenant_id': tenant2.id,
            'start_date': today, 'end_date': today + timedelta(days=365),
            'rent_amount': 900, 'deposit_required': False,
        })  # left in draft, never activated

        renew_unit = self.env['edara.unit'].create(
            {'name': 'D-107', 'code': 'D107', 'building_id': self.building.id})
        renew_contract = self.env['edara.lease.contract'].create({
            'unit_id': renew_unit.id, 'tenant_id': tenant2.id,
            'start_date': today - timedelta(days=400), 'end_date': today - timedelta(days=1),
            'rent_amount': 900, 'deposit_required': False,
        })
        renew_contract.action_activate()
        # successor starts the day after the last occupied day; the daily job below then closes the old term
        renew_contract.action_renew(today, today + timedelta(days=729), 950)

        terminate_unit = self.env['edara.unit'].create(
            {'name': 'D-108', 'code': 'D108', 'building_id': self.building.id})
        terminate_contract = self.env['edara.lease.contract'].create({
            'unit_id': terminate_unit.id, 'tenant_id': tenant2.id,
            'start_date': today, 'end_date': today + timedelta(days=365),
            'rent_amount': 900, 'deposit_required': False,
        })
        terminate_contract.action_activate()
        terminate_contract.action_terminate(reason='KPI test')

        expire_unit = self.env['edara.unit'].create(
            {'name': 'D-109', 'code': 'D109', 'building_id': self.building.id})
        expire_contract = self.env['edara.lease.contract'].create({
            'unit_id': expire_unit.id, 'tenant_id': tenant2.id,
            'start_date': today - timedelta(days=400), 'end_date': today - timedelta(days=1),
            'rent_amount': 900, 'deposit_required': False,
        })
        expire_contract.action_activate()
        self.env['edara.lease.contract']._cron_expire_contracts()

        dashboard = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertEqual(dashboard.draft_contracts_count, 1)
        # setUpClass's contract + the renewal's successor = 2 active
        self.assertEqual(dashboard.active_contracts_count, 2)
        self.assertEqual(dashboard.renewed_contracts_count, 1)
        self.assertEqual(dashboard.terminated_contracts_count, 1)
        self.assertEqual(dashboard.expired_contracts_count, 1)

    # -- BD-003 (2026-09-22): Expiring Soon = ACTIVE, end_date in [today, today+30] --

    def test_contract_expiring_soon_kpi_boundaries(self):
        today = date.today()
        tenant2 = self.env['res.partner'].create({'name': 'Expiring Soon Tenant'})

        def make_active(code, start, end):
            unit = self.env['edara.unit'].create(
                {'name': 'D-%s' % code, 'code': 'D%s' % code, 'building_id': self.building.id})
            contract = self.env['edara.lease.contract'].create({
                'unit_id': unit.id, 'tenant_id': tenant2.id,
                'start_date': start, 'end_date': end,
                'rent_amount': 900, 'deposit_required': False,
            })
            contract.action_activate()
            return contract

        ending_today = make_active('120', today - timedelta(days=100), today)
        ending_within = make_active('121', today - timedelta(days=100), today + timedelta(days=15))
        ending_exactly_30 = make_active('122', today - timedelta(days=100), today + timedelta(days=30))
        ending_after_30 = make_active('123', today - timedelta(days=100), today + timedelta(days=31))
        already_expired = make_active('124', today - timedelta(days=400), today - timedelta(days=1))
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(already_expired.state, 'expired')

        draft_unit = self.env['edara.unit'].create(
            {'name': 'D-125', 'code': 'D125', 'building_id': self.building.id})
        self.env['edara.lease.contract'].create({
            'unit_id': draft_unit.id, 'tenant_id': tenant2.id,
            'start_date': today, 'end_date': today + timedelta(days=10),
            'rent_amount': 900, 'deposit_required': False,
        })  # left in draft - ends within the window but is not ACTIVE

        dashboard = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertEqual(dashboard.expiring_soon_contracts_count, 3)  # today, within, exactly-30

        action = dashboard.action_view_contracts_expiring_soon()
        self.assertEqual(action['res_model'], 'edara.lease.contract')
        matched_ids = self.env['edara.lease.contract'].search(action['domain']).ids
        self.assertIn(ending_today.id, matched_ids)
        self.assertIn(ending_within.id, matched_ids)
        self.assertIn(ending_exactly_30.id, matched_ids)
        self.assertNotIn(ending_after_30.id, matched_ids)
        self.assertNotIn(already_expired.id, matched_ids)

    def test_maintenance_state_kpis(self):
        Maintenance = self.env['edara.maintenance.request']
        admin = self.env.ref('base.user_admin')

        Maintenance.create({'title': 'KPI New', 'unit_id': self.unit_rented.id})

        assigned_req = Maintenance.create(
            {'title': 'KPI Assigned', 'unit_id': self.unit_rented.id, 'assigned_user_id': admin.id})
        assigned_req.action_assign()

        in_progress_req = Maintenance.create(
            {'title': 'KPI In Progress', 'unit_id': self.unit_rented.id, 'assigned_user_id': admin.id})
        in_progress_req.action_assign()
        in_progress_req.action_start()

        done_req = Maintenance.create(
            {'title': 'KPI Done', 'unit_id': self.unit_rented.id, 'assigned_user_id': admin.id})
        done_req.action_assign()
        done_req.action_start()
        done_req.action_complete()

        cancelled_req = Maintenance.create({'title': 'KPI Cancelled', 'unit_id': self.unit_rented.id})
        cancelled_req.action_cancel()

        dashboard = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertEqual(dashboard.maintenance_new_count, 1)
        self.assertEqual(dashboard.maintenance_assigned_count, 1)
        self.assertEqual(dashboard.maintenance_in_progress_count, 1)
        self.assertEqual(dashboard.maintenance_done_count, 1)
        self.assertEqual(dashboard.maintenance_cancelled_count, 1)

    # -- MAT/UI-032: native quick actions --

    def test_quick_actions_open_correct_native_view_and_domain(self):
        """Every non-accounting-gated quick action must open the SAME native
        action the corresponding EDARA menu uses, with the exact expected
        domain - never a custom filtering mechanism (MAT/UI-032 §2/§15)."""
        dashboard = self.env['edara.dashboard'].create({})
        cases = [
            ('action_view_units_total', 'edara.unit', []),
            ('action_view_units_available', 'edara.unit', [('occupancy_status', '=', 'available')]),
            ('action_view_units_reserved', 'edara.unit', [('occupancy_status', '=', 'reserved')]),
            ('action_view_units_rented', 'edara.unit', [('occupancy_status', '=', 'rented')]),
            ('action_view_units_owner_occupied', 'edara.unit', [('occupancy_status', '=', 'owner_occupied')]),
            ('action_view_units_sold', 'edara.unit', [('occupancy_status', '=', 'sold')]),
            ('action_view_units_under_maintenance', 'edara.unit', [('operational_status', '=', 'under_maintenance')]),
            ('action_view_contracts_draft', 'edara.lease.contract', [('state', '=', 'draft')]),
            ('action_view_contracts_scheduled', 'edara.lease.contract', [('state', '=', 'scheduled')]),
            ('action_view_contracts_active', 'edara.lease.contract', [('state', '=', 'active')]),
            ('action_view_contracts_renewed', 'edara.lease.contract', [('state', '=', 'renewed')]),
            ('action_view_contracts_terminated', 'edara.lease.contract', [('state', '=', 'terminated')]),
            ('action_view_contracts_expired', 'edara.lease.contract', [('state', '=', 'expired')]),
            ('action_view_contracts_cancelled', 'edara.lease.contract', [('state', '=', 'cancelled')]),
            ('action_view_maintenance_new', 'edara.maintenance.request', [('state', '=', 'new')]),
            ('action_view_maintenance_assigned', 'edara.maintenance.request', [('state', '=', 'assigned')]),
            ('action_view_maintenance_in_progress', 'edara.maintenance.request', [('state', '=', 'in_progress')]),
            ('action_view_maintenance_done', 'edara.maintenance.request', [('state', '=', 'done')]),
            ('action_view_maintenance_cancelled', 'edara.maintenance.request', [('state', '=', 'cancelled')]),
            ('action_view_properties', 'edara.property', []),
            ('action_view_buildings', 'edara.building', []),
            ('action_view_renewals_pending', 'edara.renewal.request', [('state', '=', 'submitted')]),
            ('action_view_maintenance_open', 'edara.maintenance.request', [('state', 'not in', ('done', 'cancelled'))]),
        ]
        for method_name, expected_model, expected_domain in cases:
            action = getattr(dashboard, method_name)()
            self.assertEqual(action['type'], 'ir.actions.act_window', method_name)
            self.assertEqual(action['res_model'], expected_model, method_name)
            self.assertEqual(action['domain'], expected_domain, method_name)

    def test_sla_quick_actions_route_to_maintenance_request_with_matching_ids(self):
        """Dashboard UX Hardening (2026-09-23): sla_state is non-stored (Phase
        4's own documented limitation - can't be a search domain), so these
        route via an explicit ('id', 'in', [...]) domain instead of a field
        domain. The resulting list must still show exactly what the KPI tile
        itself counted - not a separate/duplicated computation."""
        dashboard = self.env['edara.dashboard'].create({})
        for method_name, kpi_field in (
                ('action_view_maintenance_sla_at_risk', 'maintenance_sla_at_risk_count'),
                ('action_view_maintenance_sla_breached', 'maintenance_sla_breached_count')):
            action = getattr(dashboard, method_name)()
            self.assertEqual(action['res_model'], 'edara.maintenance.request', method_name)
            domain_count = self.env['edara.maintenance.request'].search_count(action['domain'])
            self.assertEqual(domain_count, dashboard[kpi_field], method_name)

    def test_action_view_lease_timeline(self):
        """Phase 11.1: Dashboard quick action for Lease Timeline (Gantt view first)."""
        dashboard = self.env['edara.dashboard'].create({})
        action = dashboard.action_view_lease_timeline()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'edara.lease.contract')
        self.assertEqual(action['domain'], [])
        self.assertTrue(action.get('views'))
        self.assertEqual(action['views'][0][1], 'gantt')

        # Verify underlying contracts action default view mode ordering is unchanged (starts with list)
        base_action = self.env.ref('property_managment.action_edara_lease_contract')
        self.assertEqual(base_action.view_mode.split(',')[0], 'list')

    def test_new_non_accounting_quick_actions_work_for_viewer(self):
        """A Viewer (no native Accounting group) must be able to invoke every
        non-Collections quick action added by this hardening pass without
        hitting an AccessError - these are branch-record-rule-scoped, never
        accounting-gated."""
        viewer = new_test_user(
            self.env, login='dash_viewer_newactions@example.com', groups='property_managment.group_edara_viewer')
        self.branch.user_ids = [(4, viewer.id)]
        dashboard = self.env['edara.dashboard'].with_user(viewer).create({})
        for method_name in ('action_view_properties', 'action_view_buildings', 'action_view_renewals_pending',
                             'action_view_maintenance_open', 'action_view_maintenance_sla_at_risk',
                             'action_view_maintenance_sla_breached', 'action_view_lease_timeline'):
            action = getattr(dashboard, method_name)()
            self.assertEqual(action['type'], 'ir.actions.act_window', method_name)


    def test_schedule_quick_actions_open_correct_view_for_accounting_user(self):
        dashboard = self.env['edara.dashboard'].create({})
        self.assertTrue(dashboard.has_accounting_access)
        cases = [
            ('action_view_schedule_overdue', [('state', '=', 'overdue')]),
            ('action_view_schedule_paid', [('state', '=', 'paid')]),
        ]
        for method_name, expected_domain in cases:
            action = getattr(dashboard, method_name)()
            self.assertEqual(action['res_model'], 'edara.payment.schedule.line', method_name)
            self.assertEqual(action['domain'], expected_domain, method_name)
        # Due Today / Due This Month build their domain from today's date -
        # just confirm they resolve without error and target the right model.
        for method_name in ('action_view_schedule_due_today', 'action_view_schedule_due_this_month'):
            action = getattr(dashboard, method_name)()
            self.assertEqual(action['res_model'], 'edara.payment.schedule.line', method_name)

    def test_schedule_quick_actions_require_accounting_access(self):
        """MAT-FIND-014/015 regression: a non-Accounting EDARA role must never
        hit a raw AccessError, and the Collections quick actions must not be
        reachable even by direct method call when the hidden button is
        bypassed."""
        viewer = new_test_user(
            self.env, login='dash_viewer_schedule@example.com', groups='property_managment.group_edara_viewer')
        dashboard = self.env['edara.dashboard'].with_user(viewer).create({})
        self.assertFalse(dashboard.has_accounting_access)
        self.assertEqual(dashboard.schedule_overdue_count, 0)
        for method_name in ('action_view_schedule_overdue', 'action_view_schedule_due_today',
                             'action_view_schedule_due_this_month', 'action_view_schedule_paid'):
            with self.assertRaises(UserError, msg=method_name):
                getattr(dashboard, method_name)()

    def test_collections_quick_actions_open_correct_view_for_accounting_user(self):
        """Dashboard UX Hardening (2026-09-23): the 4 monetary Collections
        tiles route to the SAME existing Revenue/Receivables/Maintenance Cost
        report actions (Phase 2) and native account.payment list - never a
        new view - with a domain matching that tile's own KPI computation."""
        dashboard = self.env['edara.dashboard'].create({})
        self.assertTrue(dashboard.has_accounting_access)
        revenue_action = dashboard.action_view_monthly_revenue()
        self.assertEqual(revenue_action['res_model'], 'account.move')
        self.assertIn(('move_type', 'in', ('out_invoice', 'out_refund')), revenue_action['domain'])

        receivables_action = dashboard.action_view_outstanding_receivables()
        self.assertEqual(receivables_action['res_model'], 'account.move')
        self.assertIn(('move_type', 'in', ('out_invoice', 'out_refund')), receivables_action['domain'])

        payments_action = dashboard.action_view_payments_this_month()
        self.assertEqual(payments_action['res_model'], 'account.payment')

        maintenance_cost_action = dashboard.action_view_maintenance_cost_this_month()
        self.assertEqual(maintenance_cost_action['res_model'], 'edara.maintenance.request')

    def test_collections_quick_actions_require_accounting_access(self):
        viewer = new_test_user(
            self.env, login='dash_viewer_collections@example.com', groups='property_managment.group_edara_viewer')
        dashboard = self.env['edara.dashboard'].with_user(viewer).create({})
        for method_name in ('action_view_monthly_revenue', 'action_view_outstanding_receivables',
                             'action_view_payments_this_month', 'action_view_maintenance_cost_this_month'):
            with self.assertRaises(UserError, msg=method_name):
                getattr(dashboard, method_name)()

    def test_viewer_opens_dashboard_without_accounting_access_error(self):
        """MAT-FIND-014 regression, pinned explicitly for MAT/UI-032's
        expanded KPI set: a Viewer must be able to open the Dashboard and
        read every field (including the new ones) with no AccessError."""
        # Phase 6.4: self.branch now lives in the isolated cls.dash_company
        # (see setUpClass) - the viewer must be scoped to that same company,
        # or the global multi-company record rule excludes self.branch's
        # units entirely regardless of the user_ids assignment below.
        viewer = new_test_user(
            self.env, login='dash_viewer_open@example.com', groups='property_managment.group_edara_viewer',
            company_id=self.dash_company.id, company_ids=[(6, 0, [self.dash_company.id])])
        # Branch-assigned so the existing branch-scoping record rule doesn't
        # zero out the unit counts below - unrelated to this test's actual
        # concern (accounting-gating), but needed for a meaningful assertion.
        self.branch.user_ids = [(4, viewer.id)]
        dashboard = self.env['edara.dashboard'].with_user(viewer).create({})
        self.assertFalse(dashboard.has_accounting_access)
        self.assertEqual(dashboard.monthly_revenue, 0.0)
        self.assertEqual(dashboard.outstanding_receivables, 0.0)
        self.assertEqual(dashboard.recent_payments_count, 0)
        # Non-accounting KPIs must still compute normally for a Viewer.
        self.assertGreaterEqual(dashboard.total_units, 2)

    # -- Phase A: Dashboard Foundation Tests --

    def test_branch_filter_restricts_dashboard_data(self):
        """Phase A: Selecting a branch restricts dashboard counts and drill-down domains."""
        branch2 = self.env['edara.branch'].create({
            'name': 'Branch 2', 'code': 'BR2', 'company_id': self.dash_company.id,
        })
        prop2 = self.env['edara.property'].create({
            'name': 'Property 2', 'code': 'P2', 'branch_id': branch2.id,
        })
        bld2 = self.env['edara.building'].create({
            'name': 'Building 2', 'code': 'B2', 'property_id': prop2.id,
        })
        unit2 = self.env['edara.unit'].create({
            'name': 'Unit 201', 'code': 'U201', 'building_id': bld2.id,
        })

        # All branches (empty branch_id) sees both branches
        dash_all = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertEqual(dash_all.total_properties, 2)
        self.assertEqual(dash_all.total_buildings, 2)
        self.assertEqual(dash_all.total_units, 3)

        # Scoped to branch 1 (self.branch)
        dash_b1 = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertEqual(dash_b1.total_properties, 1)
        self.assertEqual(dash_b1.total_buildings, 1)
        self.assertEqual(dash_b1.total_units, 2)
        self.assertEqual(dash_b1.occupied_units, 1)
        self.assertEqual(dash_b1.available_units, 1)
        action_units = dash_b1.action_view_units_total()
        self.assertIn(('branch_id', '=', self.branch.id), action_units['domain'])

        # Scoped to branch 2
        dash_b2 = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': branch2.id})
        self.assertEqual(dash_b2.total_properties, 1)
        self.assertEqual(dash_b2.total_buildings, 1)
        self.assertEqual(dash_b2.total_units, 1)
        self.assertEqual(dash_b2.occupied_units, 0)
        self.assertEqual(dash_b2.available_units, 1)
        action_units_b2 = dash_b2.action_view_units_total()
        self.assertIn(('branch_id', '=', branch2.id), action_units_b2['domain'])

    def test_reporting_period_presets_and_date_semantics(self):
        """Phase A: Presets compute correct date_from and date_to, invalid dates raise
        ValidationError, and current-state/lookahead widgets are not filtered by financial period."""
        today = date.today()
        month_start = today.replace(day=1)
        next_m_start = month_start.replace(month=month_start.month + 1) if month_start.month < 12 else month_start.replace(year=month_start.year + 1, month=1)
        month_end = next_m_start - timedelta(days=1)

        # 1. This Month preset
        dash_month = self.env['edara.dashboard'].with_user(self.dash_admin).create({'period_preset': 'this_month'})
        self.assertEqual(dash_month.date_from, month_start)
        self.assertEqual(dash_month.date_to, month_end)

        # 2. This Year preset
        dash_year = self.env['edara.dashboard'].with_user(self.dash_admin).create({'period_preset': 'this_year'})
        self.assertEqual(dash_year.date_from, date(today.year, 1, 1))
        self.assertEqual(dash_year.date_to, date(today.year, 12, 31))

        # 3. Custom preset
        custom_from = date(2025, 1, 1)
        custom_to = date(2025, 6, 30)
        dash_custom = self.env['edara.dashboard'].with_user(self.dash_admin).create({
            'period_preset': 'custom',
            'date_from': custom_from,
            'date_to': custom_to,
        })
        self.assertEqual(dash_custom.date_from, custom_from)
        self.assertEqual(dash_custom.date_to, custom_to)

        # 4. Invalid date range raises ValidationError
        with self.assertRaises(ValidationError):
            self.env['edara.dashboard'].with_user(self.dash_admin).create({
                'period_preset': 'custom',
                'date_from': date(2026, 12, 31),
                'date_to': date(2026, 1, 1),
            })

        # 5. Date semantics: occupancy, maintenance, and lease expiry remain current-state
        # under custom historical period
        self.assertEqual(dash_custom.total_units, 2)
        self.assertEqual(dash_custom.occupied_units, 1)
        self.assertEqual(dash_custom.available_units, 1)
        self.assertEqual(dash_custom.maintenance_new_count, 0)
        self.assertEqual(dash_custom.expiring_soon_contracts_count, 0)

    def test_overdue_schedule_amount_and_branch_security(self):
        """Phase A: schedule_overdue_amount computes reliably, and Viewer cannot see unauthorized branches."""
        viewer = new_test_user(
            self.env, login='dash_viewer_branch_sec@example.com', groups='property_managment.group_edara_viewer',
            company_id=self.dash_company.id, company_ids=[(6, 0, [self.dash_company.id])])
        self.branch.user_ids = [(4, viewer.id)]
        branch_unauth = self.env['edara.branch'].create({
            'name': 'Unauthorized Branch', 'code': 'UNAUTH', 'company_id': self.dash_company.id,
        })

        # Viewer can read their own dashboard, branch_id list only contains self.branch
        viewer_branches = self.env['edara.branch'].with_user(viewer).search([])
        self.assertIn(self.branch, viewer_branches)
        self.assertNotIn(branch_unauth, viewer_branches)

        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertGreaterEqual(dash.schedule_overdue_amount, 0.0)

    # -- Phase B: Attention Center Refinement Tests --

    def test_phase_b_attention_center_empty_states(self):
        """Phase B: When no records require attention, dashboard produces clear empty states."""
        empty_branch = self.env['edara.branch'].create({
            'name': 'Empty Attention Branch', 'code': 'EAB', 'company_id': self.dash_company.id,
        })
        dash = self.env['edara.dashboard'].create({'branch_id': empty_branch.id})
        self.assertIn("No leases expiring soon", dash.expiring_leases_html)
        self.assertIn("No overdue payments", dash.overdue_payments_html)
        self.assertIn("No maintenance requiring attention", dash.maintenance_attention_html)
        self.assertIn("No pending renewal decisions", dash.pending_renewals_html)

    def test_phase_b_expiring_leases_attention(self):
        """Phase B: Expiring leases section displays actionable context and respects 30-day window."""
        today = date.today()
        tenant = self.env['res.partner'].create({'name': 'Expiring Tenant Corp'})
        unit_exp = self.env['edara.unit'].create({
            'name': 'D-EXP-1', 'code': 'DEXP1', 'building_id': self.building.id,
        })
        unit_far = self.env['edara.unit'].create({
            'name': 'D-EXP-2', 'code': 'DEXP2', 'building_id': self.building.id,
        })
        # 1. Lease expiring in 8 days (inside 30d window)
        c_expiring = self.env['edara.lease.contract'].create({
            'name': 'LC-EXP-001',
            'unit_id': unit_exp.id,
            'tenant_id': tenant.id,
            'start_date': today - timedelta(days=300),
            'end_date': today + timedelta(days=8),
            'rent_amount': 2000.0,
            'deposit_required': False,
            'state': 'active',
        })
        # 2. Lease expiring in 45 days (outside 30d window)
        c_far = self.env['edara.lease.contract'].create({
            'name': 'LC-EXP-FAR',
            'unit_id': unit_far.id,
            'tenant_id': tenant.id,
            'start_date': today - timedelta(days=300),
            'end_date': today + timedelta(days=45),
            'rent_amount': 3000.0,
            'deposit_required': False,
            'state': 'active',
        })

        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertEqual(dash.expiring_soon_contracts_count, 1)
        self.assertIn('Expiring Tenant Corp', dash.expiring_leases_html)
        self.assertIn('LC-EXP-001', dash.expiring_leases_html)
        self.assertIn('8 days remaining', dash.expiring_leases_html)
        self.assertNotIn('LC-EXP-FAR', dash.expiring_leases_html)

        action = dash.action_view_contracts_expiring_soon()
        self.assertEqual(action['res_model'], 'edara.lease.contract')

    def test_phase_b_overdue_payments_attention(self):
        """Phase B: Overdue payments card displays record-level amounts with original currency."""
        today = date.today()
        tenant = self.env['res.partner'].create({'name': 'Overdue Tenant Ltd'})
        branch_ovd = self.env['edara.branch'].create({
            'name': 'Overdue Branch', 'code': 'OVDB', 'company_id': self.dash_company.id,
        })
        prop_ovd = self.env['edara.property'].create({
            'name': 'Overdue Property', 'code': 'OVDP', 'branch_id': branch_ovd.id,
        })
        bld_ovd = self.env['edara.building'].create({
            'name': 'Overdue Building', 'code': 'OVDBL', 'property_id': prop_ovd.id,
        })
        unit_overdue = self.env['edara.unit'].create({
            'name': 'D-OVD-1', 'code': 'DOVD1', 'building_id': bld_ovd.id,
        })
        contract = self.env['edara.lease.contract'].create({
            'name': 'LC-OVERDUE-01',
            'unit_id': unit_overdue.id,
            'tenant_id': tenant.id,
            'start_date': today - timedelta(days=60),
            'end_date': today + timedelta(days=300),
            'rent_amount': 1500.0,
            'deposit_required': False,
            'state': 'active',
        })
        schedule_line = self.env['edara.payment.schedule.line'].create({
            'contract_id': contract.id,
            'due_date': today - timedelta(days=12),
            'amount': 1500.0,
        })
        self.assertEqual(schedule_line.state, 'overdue')

        dash = self.env['edara.dashboard'].create({'branch_id': branch_ovd.id})
        self.assertTrue(dash.has_accounting_access)
        self.assertEqual(dash.schedule_overdue_count, 1)
        self.assertIn('Overdue Tenant Ltd', dash.overdue_payments_html)
        self.assertIn('LC-OVERDUE-01', dash.overdue_payments_html)
        self.assertIn('12d overdue', dash.overdue_payments_html)
        self.assertIn('1,500.00', dash.overdue_payments_html)

        action = dash.action_view_schedule_overdue()
        self.assertEqual(action['res_model'], 'edara.payment.schedule.line')

    def test_phase_b_maintenance_attention(self):
        """Phase B: Maintenance attention distinguishes urgent & SLA breached and excludes unrelated."""
        admin = self.env.ref('base.user_admin')
        Maintenance = self.env['edara.maintenance.request']

        # 1. Urgent request (open)
        urgent_req = Maintenance.create({
            'title': 'Emergency Water Leak',
            'unit_id': self.unit_rented.id,
            'priority': 'urgent',
            'state': 'new',
        })
        # 2. Normal priority request (open)
        normal_req = Maintenance.create({
            'title': 'Routine Painting',
            'unit_id': self.unit_rented.id,
            'priority': 'normal',
            'state': 'new',
        })
        # 3. Done urgent request (completed)
        done_urgent = Maintenance.create({
            'title': 'Past Urgent Fixed',
            'unit_id': self.unit_rented.id,
            'priority': 'urgent',
            'state': 'done',
        })

        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertEqual(dash.maintenance_urgent_count, 1)
        self.assertIn('Emergency Water Leak', dash.maintenance_attention_html)
        self.assertIn('Urgent', dash.maintenance_attention_html)
        self.assertNotIn('Past Urgent Fixed', dash.maintenance_attention_html)

        action_urgent = dash.action_view_maintenance_urgent()
        self.assertEqual(action_urgent['res_model'], 'edara.maintenance.request')
        self.assertIn(('priority', '=', 'urgent'), action_urgent['domain'])
        self.assertIn(('branch_id', '=', self.branch.id), action_urgent['domain'])

    def test_phase_b_pending_renewals_attention(self):
        """Phase B: Pending renewals section shows submitted requests and excludes approved/rejected."""
        today = date.today()
        tenant = self.env['res.partner'].create({'name': 'Renewal Candidate'})
        unit_ren = self.env['edara.unit'].create({
            'name': 'D-REN-1', 'code': 'DREN1', 'building_id': self.building.id,
        })
        contract = self.env['edara.lease.contract'].create({
            'name': 'LC-REN-01',
            'unit_id': unit_ren.id,
            'tenant_id': tenant.id,
            'start_date': today - timedelta(days=330),
            'end_date': today + timedelta(days=35),
            'rent_amount': 5000.0,
            'deposit_required': False,
            'state': 'active',
        })
        renewal_pending = self.env['edara.renewal.request'].create({
            'contract_id': contract.id,
            'requested_start_date': today + timedelta(days=36),
            'requested_end_date': today + timedelta(days=400),
            'requested_rent_amount': 5500.0,
            'state': 'submitted',
        })

        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertEqual(dash.upcoming_renewals_count, 1)
        self.assertIn('Renewal Candidate', dash.pending_renewals_html)
        self.assertIn('LC-REN-01', dash.pending_renewals_html)
        self.assertIn('5,500.00', dash.pending_renewals_html)

        action = dash.action_view_renewals_pending()
        self.assertEqual(action['res_model'], 'edara.renewal.request')
        self.assertIn(('state', '=', 'submitted'), action['domain'])
        self.assertIn(('branch_id', '=', self.branch.id), action['domain'])

    def test_phase_b_viewer_security_attention_center(self):
        """Phase B: Viewer cannot see overdue payments HTML and has no accounting leak."""
        viewer = new_test_user(
            self.env, login='dash_viewer_phase_b@example.com', groups='property_managment.group_edara_viewer',
            company_id=self.dash_company.id, company_ids=[(6, 0, [self.dash_company.id])])
        self.branch.user_ids = [(4, viewer.id)]
        dash_viewer = self.env['edara.dashboard'].with_user(viewer).create({})

        self.assertFalse(dash_viewer.has_accounting_access)
        self.assertFalse(dash_viewer.overdue_payments_html)
        # Non-accounting attention fields remain accessible without AccessError
        self.assertTrue(dash_viewer.expiring_leases_html)
        self.assertTrue(dash_viewer.maintenance_attention_html)
        self.assertTrue(dash_viewer.pending_renewals_html)

    def test_phase_b_branch_filtering_in_attention_center(self):
        """Phase B: When a branch filter is applied, attention center isolates records to that branch."""
        today = date.today()
        branch_b = self.env['edara.branch'].create({
            'name': 'Attention Branch B', 'code': 'ATB', 'company_id': self.dash_company.id,
        })
        prop_b = self.env['edara.property'].create({
            'name': 'Property B', 'code': 'PRPB', 'branch_id': branch_b.id,
        })
        bld_b = self.env['edara.building'].create({
            'name': 'Building B', 'code': 'BLDB', 'property_id': prop_b.id,
        })
        unit_b = self.env['edara.unit'].create({
            'name': 'Unit B-1', 'code': 'UB1', 'building_id': bld_b.id,
        })
        tenant_b = self.env['res.partner'].create({'name': 'Tenant Branch B'})

        # Lease expiring in branch_b
        self.env['edara.lease.contract'].create({
            'name': 'LC-BRANCH-B',
            'unit_id': unit_b.id,
            'tenant_id': tenant_b.id,
            'start_date': today - timedelta(days=300),
            'end_date': today + timedelta(days=5),
            'rent_amount': 4000.0,
            'deposit_required': False,
            'state': 'active',
        })

        # Dashboard filtered to self.branch
        dash_filtered = self.env['edara.dashboard'].with_user(self.dash_admin).create({
            'branch_id': self.branch.id,
        })
        self.assertNotIn('LC-BRANCH-B', dash_filtered.expiring_leases_html)
        self.assertNotIn('Tenant Branch B', dash_filtered.expiring_leases_html)

    def test_phase_b_row_navigation_actions(self):
        """Phase B Defect Fix: Attention Center rows have valid native form actions and URLs."""
        today = date.today()
        tenant = self.env['res.partner'].create({'name': 'Nav Test Tenant'})
        branch_nav = self.env['edara.branch'].create({
            'name': 'Nav Test Branch', 'code': 'NTB', 'company_id': self.dash_company.id,
        })
        prop_nav = self.env['edara.property'].create({
            'name': 'Nav Property', 'code': 'NVP', 'branch_id': branch_nav.id,
        })
        bld_nav = self.env['edara.building'].create({
            'name': 'Nav Building', 'code': 'NVB', 'property_id': prop_nav.id,
        })
        unit_nav = self.env['edara.unit'].create({
            'name': 'D-NAV-1', 'code': 'DNAV1', 'building_id': bld_nav.id,
        })
        contract = self.env['edara.lease.contract'].create({
            'name': 'LC-NAV-01',
            'unit_id': unit_nav.id,
            'tenant_id': tenant.id,
            'start_date': today - timedelta(days=100),
            'end_date': today + timedelta(days=10),
            'rent_amount': 2500.0,
            'deposit_required': False,
            'state': 'active',
        })
        schedule_line = self.env['edara.payment.schedule.line'].create({
            'contract_id': contract.id,
            'due_date': today - timedelta(days=5),
            'amount': 2500.0,
        })
        maint_req = self.env['edara.maintenance.request'].create({
            'title': 'Navigation Pipe Repair',
            'unit_id': unit_nav.id,
            'priority': 'urgent',
            'state': 'new',
        })
        renewal_req = self.env['edara.renewal.request'].create({
            'contract_id': contract.id,
            'requested_start_date': today + timedelta(days=11),
            'requested_end_date': today + timedelta(days=375),
            'requested_rent_amount': 2600.0,
            'state': 'submitted',
        })

        dash = self.env['edara.dashboard'].create({'branch_id': branch_nav.id})

        # 1. HTML URLs contain native /odoo/action-.../{id} paths
        self.assertIn(f'/odoo/action-property_managment.action_edara_lease_contract/{contract.id}',
                      dash.expiring_leases_html)
        self.assertIn(f'/odoo/action-property_managment.action_edara_payment_schedule_line/{schedule_line.id}',
                      dash.overdue_payments_html)
        self.assertIn(f'/odoo/action-property_managment.action_edara_maintenance_request/{maint_req.id}',
                      dash.maintenance_attention_html)
        self.assertIn(f'/odoo/action-property_managment.action_edara_renewal_request/{renewal_req.id}',
                      dash.pending_renewals_html)

        # 2. Native form action for Expiring Lease
        action_lease = dash.with_context(
            target_model='edara.lease.contract', target_id=contract.id
        ).action_open_attention_record()
        self.assertEqual(action_lease['res_model'], 'edara.lease.contract')
        self.assertEqual(action_lease['res_id'], contract.id)
        self.assertEqual(action_lease['view_mode'], 'form')

        # 3. Native form action for Overdue Payment
        action_ovd = dash.with_context(
            target_model='edara.payment.schedule.line', target_id=schedule_line.id
        ).action_open_attention_record()
        self.assertEqual(action_ovd['res_model'], 'edara.payment.schedule.line')
        self.assertEqual(action_ovd['res_id'], schedule_line.id)
        self.assertEqual(action_ovd['view_mode'], 'form')

        # 4. Native form action for Maintenance Request
        action_maint = dash.with_context(
            target_model='edara.maintenance.request', target_id=maint_req.id
        ).action_open_attention_record()
        self.assertEqual(action_maint['res_model'], 'edara.maintenance.request')
        self.assertEqual(action_maint['res_id'], maint_req.id)
        self.assertEqual(action_maint['view_mode'], 'form')

        # 5. Native form action for Pending Renewal
        action_ren = dash.with_context(
            target_model='edara.renewal.request', target_id=renewal_req.id
        ).action_open_attention_record()
        self.assertEqual(action_ren['res_model'], 'edara.renewal.request')
        self.assertEqual(action_ren['res_id'], renewal_req.id)
        self.assertEqual(action_ren['view_mode'], 'form')

        # 6. Security: Viewer cannot open accounting record
        viewer = new_test_user(
            self.env, login='dash_nav_viewer@example.com', groups='property_managment.group_edara_viewer',
            company_id=self.dash_company.id, company_ids=[(6, 0, [self.dash_company.id])])
        self.branch.user_ids = [(4, viewer.id)]
        dash_viewer = self.env['edara.dashboard'].with_user(viewer).create({'branch_id': self.branch.id})
        with self.assertRaises(UserError):
            dash_viewer.with_context(
                target_model='edara.payment.schedule.line', target_id=schedule_line.id
            ).action_open_attention_record()

        # 7. Security: Disallowed model is rejected
        with self.assertRaises(UserError):
            dash.with_context(target_model='res.users', target_id=1).action_open_attention_record()

    # -- Phase C1: Recent Activity Operational Timeline Tests --

    def _setup_c1_accounting_fixture(self):
        main_comp = self.env.ref('base.main_company')
        branch = self.env['edara.branch'].create({
            'name': 'C1 Accounting Branch',
            'code': 'C1AB',
            'company_id': main_comp.id,
        })
        prop = self.env['edara.property'].create({'name': 'C1 Property', 'code': 'C1P', 'branch_id': branch.id})
        bld = self.env['edara.building'].create({'name': 'C1 Building', 'code': 'C1B', 'property_id': prop.id})
        u1 = self.env['edara.unit'].create({'name': 'C1-U1', 'code': 'C1U1', 'building_id': bld.id})
        u2 = self.env['edara.unit'].create({'name': 'C1-U2', 'code': 'C1U2', 'building_id': bld.id})
        tenant = self.env['res.partner'].create({'name': 'C1 Tenant'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': u1.id, 'tenant_id': tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1000.0,
            'deposit_required': False,
        })
        contract.action_activate()
        bank_journal = self.env['account.journal'].search([
            ('company_id', '=', main_comp.id), ('type', '=', 'bank'),
        ], limit=1)
        return {
            'company': main_comp,
            'branch': branch,
            'property': prop,
            'building': bld,
            'unit1': u1,
            'unit2': u2,
            'tenant': tenant,
            'contract': contract,
            'bank_journal': bank_journal,
        }

    def test_c1_01_empty_state(self):
        """1. Empty state: clean empty state 'No recent activity' when no events exist."""
        empty_branch = self.env['edara.branch'].create({
            'name': 'Empty Activity Branch', 'code': 'EACTB', 'company_id': self.dash_company.id,
        })
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': empty_branch.id})
        self.assertIn('No recent activity', dash.recent_activity_html)

    def test_c1_02_lease_terminated_activity(self):
        """2. Lease terminated activity renders correctly with state=terminated and termination_date."""
        today = date.today()
        self.env['edara.lease.contract'].create({
            'name': 'LC-TERM-001',
            'unit_id': self.unit_rented.id,
            'tenant_id': self.tenant.id,
            'start_date': today - timedelta(days=60),
            'end_date': today + timedelta(days=300),
            'rent_amount': 1200.0,
            'deposit_required': False,
            'state': 'terminated',
            'termination_date': today - timedelta(days=2),
        })
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertIn('Lease Terminated: LC-TERM-001', dash.recent_activity_html)
        self.assertIn('Terminated', dash.recent_activity_html)
        self.assertIn((today - timedelta(days=2)).strftime('%Y-%m-%d'), dash.recent_activity_html)

    def test_c1_03_maintenance_completed_activity(self):
        """3. Maintenance completed activity renders correctly with state=done and resolved_at/completed_date."""
        resolved_time = datetime.now() - timedelta(hours=5)
        m_done = self.env['edara.maintenance.request'].create({
            'title': 'Plumbing Leak Repaired',
            'unit_id': self.unit_rented.id,
            'state': 'done',
            'resolved_at': resolved_time,
        })
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertIn('Maintenance Completed: ' + m_done.name, dash.recent_activity_html)
        self.assertIn('Plumbing Leak Repaired', dash.recent_activity_html)
        self.assertIn('Completed', dash.recent_activity_html)

    def test_c1_04_renewal_approved_and_rejected(self):
        """4. Renewal decision: approved and rejected renewals are distinguished visually/textually."""
        today = date.today()
        self.env['edara.renewal.request'].create({
            'contract_id': self.contract.id,
            'requested_start_date': today + timedelta(days=366),
            'requested_end_date': today + timedelta(days=730),
            'requested_rent_amount': 950.0,
            'state': 'approved',
        })
        self.env['edara.renewal.request'].create({
            'contract_id': self.contract.id,
            'requested_start_date': today + timedelta(days=366),
            'requested_end_date': today + timedelta(days=730),
            'requested_rent_amount': 950.0,
            'state': 'rejected',
        })
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertIn('Renewal Approved', dash.recent_activity_html)
        self.assertIn('Renewal Rejected', dash.recent_activity_html)
        self.assertIn('Approved', dash.recent_activity_html)
        self.assertIn('Rejected', dash.recent_activity_html)

    def test_c1_05_payment_received(self):
        """5. Payment received: inbound customer paid payment renders with amount and partner/lease info."""
        f = self._setup_c1_accounting_fixture()
        today = date.today()
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': f['tenant'].id,
            'invoice_date': today,
            'edara_contract_id': f['contract'].id,
            'edara_branch_id': f['branch'].id,
            'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Monthly Rent', 'quantity': 1, 'price_unit': 900.0})],
        })
        inv.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids
        ).create({'journal_id': f['bank_journal'].id})._create_payments()

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch'].id})
        self.assertIn('Payment Received:', dash.recent_activity_html)
        self.assertIn(f'for Lease {f["contract"].name}', dash.recent_activity_html)
        self.assertIn('Paid', dash.recent_activity_html)

    def test_c1_06_mixed_activity_ordering(self):
        """6. Mixed activity ordering: all 4 sources sort by timestamp descending."""
        f = self._setup_c1_accounting_fixture()
        today = date.today()

        # Day -4: Terminated lease
        c_term = self.env['edara.lease.contract'].create({
            'name': 'LC-ORDER-1', 'unit_id': f['unit1'].id, 'tenant_id': f['tenant'].id,
            'start_date': today - timedelta(days=100), 'end_date': today + timedelta(days=200),
            'rent_amount': 500.0, 'deposit_required': False, 'state': 'terminated',
            'termination_date': today - timedelta(days=4),
        })

        # Day -3: Maintenance completed
        m_done = self.env['edara.maintenance.request'].create({
            'title': 'Order Test Maint', 'unit_id': f['unit1'].id, 'state': 'done',
            'resolved_at': datetime.combine(today - timedelta(days=3), datetime.min.time()),
        })

        # Day -2: Payment received
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': f['tenant'].id, 'invoice_date': today - timedelta(days=2),
            'edara_contract_id': f['contract'].id, 'edara_branch_id': f['branch'].id, 'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent', 'quantity': 1, 'price_unit': 450.0})],
        })
        inv.action_post()
        p = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids
        ).create({'journal_id': f['bank_journal'].id, 'payment_date': today - timedelta(days=2)})._create_payments()

        # Day -1 / today: Renewal decision
        ren = self.env['edara.renewal.request'].create({
            'contract_id': f['contract'].id, 'requested_start_date': today + timedelta(days=366),
            'requested_end_date': today + timedelta(days=730), 'requested_rent_amount': 950.0,
            'state': 'approved',
        })

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch'].id})
        html = dash.recent_activity_html

        idx_ren = html.find(f'action-property_managment.action_edara_renewal_request/{ren.id}')
        idx_pay = html.find(f'action-account.action_account_payments/{p.id}')
        idx_maint = html.find(f'action-property_managment.action_edara_maintenance_request/{m_done.id}')
        idx_term = html.find(f'action-property_managment.action_edara_lease_contract/{c_term.id}')

        self.assertTrue(all(i != -1 for i in (idx_ren, idx_pay, idx_maint, idx_term)))
        self.assertLess(idx_ren, idx_pay)
        self.assertLess(idx_pay, idx_maint)
        self.assertLess(idx_maint, idx_term)

    def test_c1_07_shared_activity_cap(self):
        """7. Shared activity cap: merged candidate list is capped at exactly 8 items."""
        today = date.today()
        for i in range(10):
            self.env['edara.lease.contract'].create({
                'name': f'LC-CAP-{i:02d}', 'unit_id': self.unit_rented.id, 'tenant_id': self.tenant.id,
                'start_date': today - timedelta(days=100), 'end_date': today + timedelta(days=200),
                'rent_amount': 500.0, 'deposit_required': False, 'state': 'terminated',
                'termination_date': today - timedelta(days=i + 1),
            })
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        count = dash.recent_activity_html.count('class="o_activity_item text-reset"')
        self.assertEqual(count, 8)

    def test_c1_08_branch_isolation(self):
        """8. Branch isolation: when branch_id is specified, only that branch's activities appear."""
        today = date.today()
        branch_b = self.env['edara.branch'].create({
            'name': 'Branch B Isolation', 'code': 'BBISO', 'company_id': self.dash_company.id,
        })
        prop_b = self.env['edara.property'].create({
            'name': 'Property B', 'code': 'PBISO', 'branch_id': branch_b.id,
        })
        bld_b = self.env['edara.building'].create({
            'name': 'Building B', 'code': 'BBISO2', 'property_id': prop_b.id,
        })
        unit_b = self.env['edara.unit'].create({
            'name': 'B-101', 'code': 'B101', 'building_id': bld_b.id,
        })
        self.env['edara.lease.contract'].create({
            'name': 'LC-BRANCH-A', 'unit_id': self.unit_rented.id, 'tenant_id': self.tenant.id,
            'start_date': today - timedelta(days=100), 'end_date': today + timedelta(days=200),
            'rent_amount': 500.0, 'deposit_required': False, 'state': 'terminated',
            'termination_date': today,
        })
        self.env['edara.lease.contract'].create({
            'name': 'LC-BRANCH-B', 'unit_id': unit_b.id, 'tenant_id': self.tenant.id,
            'start_date': today - timedelta(days=100), 'end_date': today + timedelta(days=200),
            'rent_amount': 500.0, 'deposit_required': False, 'state': 'terminated',
            'termination_date': today,
        })
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertIn('LC-BRANCH-A', dash_a.recent_activity_html)
        self.assertNotIn('LC-BRANCH-B', dash_a.recent_activity_html)

        dash_b = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': branch_b.id})
        self.assertIn('LC-BRANCH-B', dash_b.recent_activity_html)
        self.assertNotIn('LC-BRANCH-A', dash_b.recent_activity_html)

    def test_c1_09_accounting_access_gating(self):
        """9. Accounting access gating: viewer sees non-accounting activities, but payment rows are omitted."""
        f = self._setup_c1_accounting_fixture()
        today = date.today()
        self.env['edara.lease.contract'].create({
            'name': 'LC-GATE-TERM', 'unit_id': f['unit1'].id, 'tenant_id': f['tenant'].id,
            'start_date': today - timedelta(days=50), 'end_date': today + timedelta(days=100),
            'rent_amount': 500.0, 'deposit_required': False, 'state': 'terminated',
            'termination_date': today,
        })
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': f['tenant'].id, 'invoice_date': today,
            'edara_contract_id': f['contract'].id, 'edara_branch_id': f['branch'].id, 'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent', 'quantity': 1, 'price_unit': 450.0})],
        })
        inv.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids
        ).create({'journal_id': f['bank_journal'].id})._create_payments()

        viewer = new_test_user(
            self.env, login='dash_viewer_c1_gating@example.com', groups='property_managment.group_edara_viewer',
            company_id=f['company'].id, company_ids=[(6, 0, [f['company'].id])])
        f['branch'].user_ids = [(4, viewer.id)]

        dash_viewer = self.env['edara.dashboard'].with_user(viewer).create({'branch_id': f['branch'].id})
        self.assertFalse(dash_viewer.has_accounting_access)
        self.assertIn('LC-GATE-TERM', dash_viewer.recent_activity_html)
        self.assertNotIn('Payment Received', dash_viewer.recent_activity_html)
        self.assertNotIn('action-account.action_account_payments', dash_viewer.recent_activity_html)

    def test_c1_10_date_filter_independence(self):
        """10. Date-filter independence: Recent activity does not depend on reporting period or dates."""
        today = date.today()
        self.env['edara.lease.contract'].create({
            'name': 'LC-DATE-INDEP', 'unit_id': self.unit_rented.id, 'tenant_id': self.tenant.id,
            'start_date': today - timedelta(days=100), 'end_date': today + timedelta(days=200),
            'rent_amount': 500.0, 'deposit_required': False, 'state': 'terminated',
            'termination_date': today,
        })
        dash_future = self.env['edara.dashboard'].with_user(self.dash_admin).create({
            'branch_id': self.branch.id,
            'period_preset': 'custom',
            'date_from': date(2030, 1, 1),
            'date_to': date(2030, 12, 31),
        })
        self.assertIn('LC-DATE-INDEP', dash_future.recent_activity_html)

    def test_c1_11_maintenance_missing_date_exclusion(self):
        """11. Maintenance missing-date exclusion: done maintenance with no resolved_at or completed_date is excluded."""
        self.env['edara.maintenance.request'].create({
            'title': 'Undated Done Request',
            'unit_id': self.unit_rented.id,
            'state': 'done',
            'resolved_at': False,
            'completed_date': False,
        })
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertNotIn('Undated Done Request', dash.recent_activity_html)

    def test_c1_12_payment_reconciliation_ambiguity(self):
        """12. Payment reconciliation ambiguity: 1 lease shows lease ref; 0 or multiple leases shows generic payment."""
        f = self._setup_c1_accounting_fixture()
        today = date.today()

        contract2 = self.env['edara.lease.contract'].create({
            'unit_id': f['unit2'].id, 'tenant_id': f['tenant'].id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 800,
            'deposit_required': False,
        })

        # Payment A: exactly 1 contract
        inv1 = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': f['tenant'].id, 'invoice_date': today,
            'edara_contract_id': f['contract'].id, 'edara_branch_id': f['branch'].id, 'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent Single', 'quantity': 1, 'price_unit': 300.0})],
        })
        inv1.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv1.ids
        ).create({'journal_id': f['bank_journal'].id})._create_payments()

        # Payment B: generic invoice without contract
        inv_gen = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': f['tenant'].id, 'invoice_date': today,
            'edara_branch_id': f['branch'].id, 'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Service Generic', 'quantity': 1, 'price_unit': 200.0})],
        })
        inv_gen.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv_gen.ids
        ).create({'journal_id': f['bank_journal'].id})._create_payments()

        # Payment C: reconciled to 2 contracts
        inv_c1 = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': f['tenant'].id, 'invoice_date': today,
            'edara_contract_id': f['contract'].id, 'edara_branch_id': f['branch'].id, 'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent C1', 'quantity': 1, 'price_unit': 100.0})],
        })
        inv_c1.action_post()
        inv_c2 = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': f['tenant'].id, 'invoice_date': today,
            'edara_contract_id': contract2.id, 'edara_branch_id': f['branch'].id, 'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent C2', 'quantity': 1, 'price_unit': 100.0})],
        })
        inv_c2.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=(inv_c1 | inv_c2).ids
        ).create({'journal_id': f['bank_journal'].id, 'group_payment': True})._create_payments()

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch'].id})
        html = dash.recent_activity_html

        self.assertIn(f'for Lease {f["contract"].name}', html)
        self.assertIn('Payment Received: 200.00', html)
        self.assertIn(f'from {f["tenant"].name}', html)
        self.assertNotIn(f'for Lease {contract2.name}', html)

    def test_c1_13_vendor_outbound_payment_exclusion(self):
        """13. Vendor/outbound payment exclusion: vendor and outbound payments are not displayed."""
        f = self._setup_c1_accounting_fixture()
        today = date.today()
        vendor = self.env['res.partner'].create({'name': 'Vendor Contractor Inc'})
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': vendor.id,
            'invoice_date': today,
            'edara_branch_id': f['branch'].id,
            'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Maintenance Bill', 'quantity': 1, 'price_unit': 600.0})],
        })
        bill.action_post()
        vendor_pay = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids
        ).create({'journal_id': f['bank_journal'].id})._create_payments()

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch'].id})
        self.assertNotIn(f'action-account.action_account_payments/{vendor_pay.id}', dash.recent_activity_html)
        self.assertNotIn('Vendor Contractor Inc', dash.recent_activity_html)

    def test_c1_14_in_process_payment_exclusion(self):
        """14. in_process payment exclusion: payments not in state=paid are excluded."""
        f = self._setup_c1_accounting_fixture()
        today = date.today()
        pay_in_process = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': f['tenant'].id,
            'amount': 350.0,
            'journal_id': f['bank_journal'].id,
            'company_id': f['company'].id,
            'date': today,
        })
        pay_in_process.action_post()
        self.assertEqual(pay_in_process.state, 'in_process')

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch'].id})
        self.assertNotIn(f'action-account.action_account_payments/{pay_in_process.id}', dash.recent_activity_html)

    def test_c1_15_html_escaping(self):
        """15. HTML escaping: malicious strings in record names/titles are escaped."""
        today = date.today()
        self.env['edara.lease.contract'].create({
            'name': '<script>alert("xss")</script>',
            'unit_id': self.unit_rented.id,
            'tenant_id': self.tenant.id,
            'start_date': today - timedelta(days=50),
            'end_date': today + timedelta(days=100),
            'rent_amount': 500.0,
            'deposit_required': False,
            'state': 'terminated',
            'termination_date': today,
        })
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertNotIn('<script>', dash.recent_activity_html)
        self.assertIn('&lt;script&gt;', dash.recent_activity_html)
        self.assertIn('xss', dash.recent_activity_html)

    def test_c1_16_correct_native_navigation_urls(self):
        """16. Correct native navigation URLs: links use real /odoo/action-.../{id} routes."""
        f = self._setup_c1_accounting_fixture()
        today = date.today()

        c_term = self.env['edara.lease.contract'].create({
            'name': 'LC-NAV-TERM', 'unit_id': f['unit1'].id, 'tenant_id': f['tenant'].id,
            'start_date': today - timedelta(days=50), 'end_date': today + timedelta(days=100),
            'rent_amount': 500.0, 'deposit_required': False, 'state': 'terminated',
            'termination_date': today,
        })
        m_done = self.env['edara.maintenance.request'].create({
            'title': 'Nav Maint Done', 'unit_id': f['unit1'].id, 'state': 'done',
            'resolved_at': datetime.now(),
        })
        ren = self.env['edara.renewal.request'].create({
            'contract_id': f['contract'].id, 'requested_start_date': today + timedelta(days=366),
            'requested_end_date': today + timedelta(days=730), 'requested_rent_amount': 950.0,
            'state': 'approved',
        })
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': f['tenant'].id, 'invoice_date': today,
            'edara_contract_id': f['contract'].id, 'edara_branch_id': f['branch'].id, 'company_id': f['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent', 'quantity': 1, 'price_unit': 450.0})],
        })
        inv.action_post()
        pay = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids
        ).create({'journal_id': f['bank_journal'].id})._create_payments()

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch'].id})
        html = dash.recent_activity_html

        self.assertIn(f'/odoo/action-property_managment.action_edara_lease_contract/{c_term.id}', html)
        self.assertIn(f'/odoo/action-property_managment.action_edara_maintenance_request/{m_done.id}', html)
        self.assertIn(f'/odoo/action-property_managment.action_edara_renewal_request/{ren.id}', html)
        self.assertIn(f'/odoo/action-account.action_account_payments/{pay.id}', html)

        # Also verify action_open_attention_record works for account.payment
        act_pay = dash.with_context(
            target_model='account.payment', target_id=pay.id
        ).action_open_attention_record()
        self.assertEqual(act_pay['res_model'], 'account.payment')
        self.assertEqual(act_pay['res_id'], pay.id)
        self.assertEqual(act_pay['view_mode'], 'form')

    def test_c1_17_maintenance_candidate_ordering_by_completion_timestamp(self):
        """17. Maintenance candidate ordering: Older records with recent resolved_at rank ahead of newer records with older timestamps."""
        now = datetime.now()
        branch_order = self.env['edara.branch'].create({
            'name': 'Maint Order Branch', 'code': 'MOBR', 'company_id': self.dash_company.id,
        })
        prop = self.env['edara.property'].create({
            'name': 'Maint Prop', 'code': 'MPROP', 'branch_id': branch_order.id,
        })
        bld = self.env['edara.building'].create({
            'name': 'Maint Bld', 'code': 'MBLD', 'property_id': prop.id,
        })
        unit = self.env['edara.unit'].create({
            'name': 'M-Unit', 'code': 'MUNT', 'building_id': bld.id,
        })

        # 1. Create an older maintenance record (lower ID) with a RECENT resolved_at (e.g. 5 minutes ago)
        m_old_recent = self.env['edara.maintenance.request'].create({
            'title': 'Recent Urgent Fix Low ID',
            'unit_id': unit.id,
            'state': 'done',
            'resolved_at': now - timedelta(minutes=5),
        })

        # 2. Create newer records (higher IDs) with OLDER completion timestamps (e.g. 20-30 days ago)
        # Create 25 such records to exceed the CANDIDATE_LIMIT * 2 (20) window
        for i in range(25):
            self.env['edara.maintenance.request'].create({
                'title': f'Old Completion High ID {i:02d}',
                'unit_id': unit.id,
                'state': 'done',
                'resolved_at': now - timedelta(days=20 + i),
            })

        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': branch_order.id})
        html = dash.recent_activity_html

        # Verify that m_old_recent was NOT excluded by the candidate limit due to its lower ID
        self.assertIn('Recent Urgent Fix Low ID', html)
        self.assertIn(f'action-property_managment.action_edara_maintenance_request/{m_old_recent.id}', html)

        # Verify it ranks first among maintenance activities in the timeline
        idx_recent = html.find(f'action-property_managment.action_edara_maintenance_request/{m_old_recent.id}')
        idx_first_maint = html.find('action-property_managment.action_edara_maintenance_request/')
        self.assertGreater(idx_recent, -1)
        self.assertEqual(idx_recent, idx_first_maint)

    # -- Phase C2: Occupancy Doughnut Chart & Click-to-Filter Tests --

    def test_c2_01_occupancy_chart_data_all_statuses(self):
        """1. occupancy_chart_data contains correct counts and slices for all five real occupancy statuses,
        and under_maintenance is separate from the doughnut slices."""
        branch_c2 = self.env['edara.branch'].create({
            'name': 'C2 Test Branch', 'code': 'C2BR', 'company_id': self.dash_company.id,
        })
        prop = self.env['edara.property'].create({
            'name': 'C2 Prop', 'code': 'C2P', 'branch_id': branch_c2.id,
        })
        bld = self.env['edara.building'].create({
            'name': 'C2 Bld', 'code': 'C2B', 'property_id': prop.id,
        })
        tenant = self.env['res.partner'].create({'name': 'C2 Tenant'})
        today = date.today()

        # Available unit
        self.env['edara.unit'].create({
            'name': 'C2-U-AV', 'code': 'C2UAV', 'building_id': bld.id,
        })
        # Rented unit (with active contract)
        u_rent = self.env['edara.unit'].create({
            'name': 'C2-U-RENT', 'code': 'C2URENT', 'building_id': bld.id,
        })
        c_rent = self.env['edara.lease.contract'].create({
            'unit_id': u_rent.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=10), 'end_date': today + timedelta(days=200),
            'rent_amount': 1000.0, 'deposit_required': False,
        })
        c_rent.action_activate()

        # Reserved unit (active contract starting in future)
        u_res = self.env['edara.unit'].create({
            'name': 'C2-U-RES', 'code': 'C2URES', 'building_id': bld.id,
        })
        c_res = self.env['edara.lease.contract'].create({
            'unit_id': u_res.id, 'tenant_id': tenant.id,
            'start_date': today + timedelta(days=10), 'end_date': today + timedelta(days=200),
            'rent_amount': 1000.0, 'deposit_required': False,
        })
        c_res.action_activate()

        # Owner Occupied unit
        self.env['edara.unit'].create({
            'name': 'C2-U-OWN', 'code': 'C2UOWN', 'building_id': bld.id,
            'occupancy_status': 'owner_occupied',
        })

        # Sold unit
        self.env['edara.unit'].create({
            'name': 'C2-U-SOLD', 'code': 'C2USOLD', 'building_id': bld.id,
            'occupancy_status': 'sold',
        })

        # Under Maintenance unit (operational status, rented occupancy)
        u_maint = self.env['edara.unit'].create({
            'name': 'C2-U-MAINT', 'code': 'C2UMAINT', 'building_id': bld.id,
        })
        c_maint = self.env['edara.lease.contract'].create({
            'unit_id': u_maint.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=5), 'end_date': today + timedelta(days=200),
            'rent_amount': 1000.0, 'deposit_required': False,
        })
        c_maint.action_activate()
        u_maint.operational_status = 'under_maintenance'

        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': branch_c2.id})
        data = json.loads(dash.occupancy_chart_data)

        # 5 real occupancy statuses sum to total:
        # Available: 1, Reserved: 1, Rented: 2 (u_rent + u_maint), Owner Occupied: 1, Sold: 1 => Total: 6
        self.assertEqual(data['total'], 6)
        slice_map = {s['status']: s for s in data['slices']}
        self.assertEqual(len(data['slices']), 5)
        self.assertNotIn('under_maintenance', slice_map)

        self.assertEqual(slice_map['available']['count'], 1)
        self.assertEqual(slice_map['available']['action_method'], 'action_view_units_available')
        self.assertEqual(slice_map['reserved']['count'], 1)
        self.assertEqual(slice_map['reserved']['action_method'], 'action_view_units_reserved')
        self.assertEqual(slice_map['rented']['count'], 2)
        self.assertEqual(slice_map['rented']['action_method'], 'action_view_units_rented')
        self.assertEqual(slice_map['owner_occupied']['count'], 1)
        self.assertEqual(slice_map['owner_occupied']['action_method'], 'action_view_units_owner_occupied')
        self.assertEqual(slice_map['sold']['count'], 1)
        self.assertEqual(slice_map['sold']['action_method'], 'action_view_units_sold')

        # Under maintenance is separate
        self.assertEqual(data['under_maintenance']['count'], 1)
        self.assertEqual(data['under_maintenance']['action_method'], 'action_view_units_under_maintenance')

    def test_c2_02_occupancy_chart_data_branch_filtering(self):
        """2. Branch filtering correctly isolates chart data between branches and aggregates on all-branches."""
        br_a = self.env['edara.branch'].create({
            'name': 'C2 Branch A', 'code': 'C2BA', 'company_id': self.dash_company.id,
        })
        prop_a = self.env['edara.property'].create({
            'name': 'Prop A', 'code': 'PA', 'branch_id': br_a.id,
        })
        bld_a = self.env['edara.building'].create({
            'name': 'Bld A', 'code': 'BA', 'property_id': prop_a.id,
        })
        self.env['edara.unit'].create({'name': 'U-A1', 'code': 'UA1', 'building_id': bld_a.id})
        self.env['edara.unit'].create({'name': 'U-A2', 'code': 'UA2', 'building_id': bld_a.id})

        br_b = self.env['edara.branch'].create({
            'name': 'C2 Branch B', 'code': 'C2BB', 'company_id': self.dash_company.id,
        })
        prop_b = self.env['edara.property'].create({
            'name': 'Prop B', 'code': 'PB', 'branch_id': br_b.id,
        })
        bld_b = self.env['edara.building'].create({
            'name': 'Bld B', 'code': 'BB', 'property_id': prop_b.id,
        })
        self.env['edara.unit'].create({'name': 'U-B1', 'code': 'UB1', 'building_id': bld_b.id})

        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': br_a.id})
        data_a = json.loads(dash_a.occupancy_chart_data)
        self.assertEqual(data_a['total'], 2)

        dash_b = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': br_b.id})
        data_b = json.loads(dash_b.occupancy_chart_data)
        self.assertEqual(data_b['total'], 1)

    def test_c2_03_occupancy_chart_data_empty_portfolio(self):
        """3. Empty portfolio produces valid zero-state data with total 0 and all slice counts 0."""
        br_empty = self.env['edara.branch'].create({
            'name': 'C2 Empty Branch', 'code': 'C2BE', 'company_id': self.dash_company.id,
        })
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': br_empty.id})
        data = json.loads(dash.occupancy_chart_data)
        self.assertEqual(data['total'], 0)
        self.assertEqual(len(data['slices']), 5)
        for s in data['slices']:
            self.assertEqual(s['count'], 0)
        self.assertEqual(data['under_maintenance']['count'], 0)

    def test_c2_04_existing_kpi_fields_unchanged(self):
        """4. Existing KPI fields remain computed and accurate alongside occupancy_chart_data."""
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        data = json.loads(dash.occupancy_chart_data)
        slice_map = {s['status']: s['count'] for s in data['slices']}

        self.assertEqual(dash.available_units, slice_map['available'])
        self.assertEqual(dash.occupied_units, slice_map['rented'])
        self.assertEqual(dash.reserved_units, slice_map['reserved'])
        self.assertEqual(dash.owner_occupied_units, slice_map['owner_occupied'])
        self.assertEqual(dash.sold_units, slice_map['sold'])
        self.assertEqual(dash.under_maintenance_units, data['under_maintenance']['count'])

    def test_c2_05_existing_action_view_units_methods(self):
        """5. Existing action_view_units_* methods continue to work correctly and apply branch domain."""
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        cases = [
            ('action_view_units_available', [('occupancy_status', '=', 'available'), ('branch_id', '=', self.branch.id)]),
            ('action_view_units_rented', [('occupancy_status', '=', 'rented'), ('branch_id', '=', self.branch.id)]),
            ('action_view_units_reserved', [('occupancy_status', '=', 'reserved'), ('branch_id', '=', self.branch.id)]),
            ('action_view_units_owner_occupied', [('occupancy_status', '=', 'owner_occupied'), ('branch_id', '=', self.branch.id)]),
            ('action_view_units_sold', [('occupancy_status', '=', 'sold'), ('branch_id', '=', self.branch.id)]),
            ('action_view_units_under_maintenance', [('operational_status', '=', 'under_maintenance'), ('branch_id', '=', self.branch.id)]),
        ]
        for method_name, expected_domain in cases:
            action = getattr(dash, method_name)()
            self.assertEqual(action['type'], 'ir.actions.act_window')
            self.assertEqual(action['res_model'], 'edara.unit')
            self.assertEqual(action['domain'], expected_domain)

    def test_c2_06_date_filter_independence(self):
        """6. Occupancy chart data is current-state data and does not change with period_preset or date filters."""
        dash_current = self.env['edara.dashboard'].with_user(self.dash_admin).create({
            'branch_id': self.branch.id,
            'period_preset': 'this_month',
        })
        dash_future = self.env['edara.dashboard'].with_user(self.dash_admin).create({
            'branch_id': self.branch.id,
            'period_preset': 'custom',
            'date_from': date(2040, 1, 1),
            'date_to': date(2040, 12, 31),
        })
        self.assertEqual(dash_current.occupancy_chart_data, dash_future.occupancy_chart_data)

    # -- Phase C3: Revenue Trend Tests --

    def _setup_c3_accounting_fixture(self):
        main_comp = self.env.ref('base.main_company')
        branch_a = self.env['edara.branch'].create({
            'name': 'C3 Branch A', 'code': 'C3BA', 'company_id': main_comp.id,
        })
        branch_b = self.env['edara.branch'].create({
            'name': 'C3 Branch B', 'code': 'C3BB', 'company_id': main_comp.id,
        })
        tenant = self.env['res.partner'].create({'name': 'C3 Tenant'})
        return {
            'company': main_comp,
            'branch_a': branch_a,
            'branch_b': branch_b,
            'tenant': tenant,
        }

    def _create_c3_move(self, fixture, branch, move_type, date_val, amount, posted=True):
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': fixture['tenant'].id,
            'invoice_date': date_val,
            'edara_branch_id': branch.id if branch else False,
            'company_id': fixture['company'].id,
            'invoice_line_ids': [(0, 0, {'name': 'Test Rent Line', 'quantity': 1, 'price_unit': amount})],
        })
        if posted:
            move.action_post()
        return move

    def test_c3_01_six_month_buckets(self):
        """C3-01: Exactly six monthly buckets are present in chronological order with valid labels and structure."""
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        data = json.loads(dash.revenue_trend_data)
        self.assertIn('months', data)
        self.assertEqual(len(data['months']), 6)
        today = fields.Date.context_today(self)
        cur_month_start = today.replace(day=1)
        for i, m in enumerate(data['months']):
            self.assertEqual(m['index'], i)
            expected_date = cur_month_start - relativedelta(months=5 - i)
            self.assertEqual(m['year'], expected_date.year)
            self.assertEqual(m['month'], expected_date.month)
            self.assertTrue(m['label'])
            self.assertIsInstance(m['value'], (int, float))
        self.assertTrue(data.get('currency'))

    def test_c3_02_correct_aggregation_invoices_and_refunds(self):
        """C3-02: Correct aggregation: customer invoices and credit notes signed effect matches amount_untaxed_signed."""
        f = self._setup_c3_accounting_fixture()
        today = fields.Date.context_today(self)
        cur_month_start = today.replace(day=1)
        m5_date = cur_month_start
        m4_date = cur_month_start - relativedelta(months=1)

        # In branch A:
        # Month 5: invoice 1000, refund 200 => net 800
        self._create_c3_move(f, f['branch_a'], 'out_invoice', m5_date, 1000.0)
        self._create_c3_move(f, f['branch_a'], 'out_refund', m5_date, 200.0)
        # Month 4: invoice 500 => net 500
        self._create_c3_move(f, f['branch_a'], 'out_invoice', m4_date, 500.0)

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch_a'].id})
        data = json.loads(dash.revenue_trend_data)
        self.assertEqual(data['months'][5]['value'], 800.0)
        self.assertEqual(data['months'][4]['value'], 500.0)
        self.assertEqual(data['total_revenue'], 1300.0)

    def test_c3_03_draft_and_cancelled_exclusion(self):
        """C3-03: Non-posted invoices (draft/cancelled) are completely excluded from trend aggregation."""
        f = self._setup_c3_accounting_fixture()
        today = fields.Date.context_today(self)
        cur_month_start = today.replace(day=1)

        self._create_c3_move(f, f['branch_a'], 'out_invoice', cur_month_start, 1000.0, posted=True)
        self._create_c3_move(f, f['branch_a'], 'out_invoice', cur_month_start, 2000.0, posted=False)
        canc_move = self._create_c3_move(f, f['branch_a'], 'out_invoice', cur_month_start, 3000.0, posted=True)
        canc_move.button_cancel()

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch_a'].id})
        data = json.loads(dash.revenue_trend_data)
        self.assertEqual(data['months'][5]['value'], 1000.0)

    def test_c3_04_branch_filtering(self):
        """C3-04: Branch filtering correctly isolates revenue per branch or shows whole accessible company data."""
        f = self._setup_c3_accounting_fixture()
        today = fields.Date.context_today(self)
        cur_month_start = today.replace(day=1)

        self._create_c3_move(f, f['branch_a'], 'out_invoice', cur_month_start, 1000.0)
        self._create_c3_move(f, f['branch_b'], 'out_invoice', cur_month_start, 2500.0)

        dash_a = self.env['edara.dashboard'].create({'branch_id': f['branch_a'].id})
        data_a = json.loads(dash_a.revenue_trend_data)
        self.assertEqual(data_a['months'][5]['value'], 1000.0)

        dash_b = self.env['edara.dashboard'].create({'branch_id': f['branch_b'].id})
        data_b = json.loads(dash_b.revenue_trend_data)
        self.assertEqual(data_b['months'][5]['value'], 2500.0)

        dash_all = self.env['edara.dashboard'].create({})
        data_all = json.loads(dash_all.revenue_trend_data)
        self.assertGreaterEqual(data_all['months'][5]['value'], 3500.0)

    def test_c3_05_empty_months(self):
        """C3-05: Missing/empty months appear with 0.0 value and maintain all six month slots."""
        f = self._setup_c3_accounting_fixture()
        today = fields.Date.context_today(self)
        cur_month_start = today.replace(day=1)
        m2_date = cur_month_start - relativedelta(months=3)

        self._create_c3_move(f, f['branch_a'], 'out_invoice', m2_date, 750.0)

        dash = self.env['edara.dashboard'].create({'branch_id': f['branch_a'].id})
        data = json.loads(dash.revenue_trend_data)
        self.assertEqual(len(data['months']), 6)
        self.assertEqual(data['months'][2]['value'], 750.0)
        for idx in (0, 1, 3, 4, 5):
            self.assertEqual(data['months'][idx]['value'], 0.0)

    def test_c3_06_accounting_access(self):
        """C3-06: User without accounting access receives safe empty/zero payload and no AccessError."""
        viewer = new_test_user(
            self.env, login='c3_dash_viewer@example.com', groups='property_managment.group_edara_viewer',
            company_id=self.dash_company.id, company_ids=[(6, 0, [self.dash_company.id])])
        dash = self.env['edara.dashboard'].with_user(viewer).create({})
        self.assertFalse(dash.has_accounting_access)
        data = json.loads(dash.revenue_trend_data)
        self.assertEqual(len(data['months']), 6)
        for m in data['months']:
            self.assertEqual(m['value'], 0.0)
        self.assertEqual(data['total_revenue'], 0.0)
        with self.assertRaises(UserError):
            dash.action_view_revenue_trend_month(0)

    def test_c3_07_global_date_filter_independence(self):
        """C3-07: revenue_trend_data is independent of period_preset, date_from, and date_to."""
        dash_month = self.env['edara.dashboard'].with_user(self.dash_admin).create({
            'branch_id': self.branch.id,
            'period_preset': 'this_month',
        })
        dash_year = self.env['edara.dashboard'].with_user(self.dash_admin).create({
            'branch_id': self.branch.id,
            'period_preset': 'this_year',
        })
        dash_custom = self.env['edara.dashboard'].with_user(self.dash_admin).create({
            'branch_id': self.branch.id,
            'period_preset': 'custom',
            'date_from': date(2040, 1, 1),
            'date_to': date(2040, 12, 31),
        })
        self.assertEqual(dash_month.revenue_trend_data, dash_year.revenue_trend_data)
        self.assertEqual(dash_month.revenue_trend_data, dash_custom.revenue_trend_data)

    def test_c3_08_drilldown(self):
        """C3-08: action_view_revenue_trend_month returns valid act_window on account.move with exact month boundaries."""
        f = self._setup_c3_accounting_fixture()
        dash = self.env['edara.dashboard'].create({'branch_id': f['branch_a'].id})
        today = fields.Date.context_today(self)
        cur_month_start = today.replace(day=1)

        for idx in range(6):
            action = dash.action_view_revenue_trend_month(idx)
            self.assertEqual(action['type'], 'ir.actions.act_window')
            self.assertEqual(action['res_model'], 'account.move')
            domain = action['domain']
            months_ago = 5 - idx
            expected_start = cur_month_start - relativedelta(months=months_ago)
            expected_end = (expected_start + relativedelta(months=1)) - timedelta(days=1)
            self.assertIn(('state', '=', 'posted'), domain)
            self.assertIn(('move_type', 'in', ('out_invoice', 'out_refund')), domain)
            self.assertIn(('invoice_date', '>=', expected_start), domain)
            self.assertIn(('invoice_date', '<=', expected_end), domain)
            self.assertIn(('edara_branch_id', '=', f['branch_a'].id), domain)

    def test_c3_09_invalid_month_index(self):
        """C3-09: Invalid month index values (-1, 6, non-int) are safely rejected with UserError."""
        dash = self.env['edara.dashboard'].create({})
        with self.assertRaises(UserError):
            dash.action_view_revenue_trend_month(-1)
        with self.assertRaises(UserError):
            dash.action_view_revenue_trend_month(6)
        with self.assertRaises(UserError):
            dash.action_view_revenue_trend_month('abc')

    def test_c3_10_existing_revenue_kpi_regression(self):
        """C3-10: Existing monthly_revenue KPI and action_view_monthly_revenue remain unchanged."""
        f = self._setup_c3_accounting_fixture()
        today = fields.Date.context_today(self)
        self._create_c3_move(f, f['branch_a'], 'out_invoice', today, 1500.0)

        dash = self.env['edara.dashboard'].create({
            'branch_id': f['branch_a'].id,
            'period_preset': 'this_month',
        })
        self.assertEqual(dash.monthly_revenue, 1500.0)
        action = dash.action_view_monthly_revenue()
        self.assertEqual(action['res_model'], 'account.move')
        self.assertIn(('edara_branch_id', '=', f['branch_a'].id), action['domain'])

    # -- Phase C4: Contextual Record Creation Shortcuts Tests --

    def test_c4_01_action_new_lease_contract(self):
        """C4-01: action_new_lease_contract returns blank form action with branch context when branch selected."""
        # Case A: Without branch
        dash_no_branch = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        action_a = dash_no_branch.action_new_lease_contract()
        self.assertEqual(action_a['type'], 'ir.actions.act_window')
        self.assertEqual(action_a['res_model'], 'edara.lease.contract')
        self.assertEqual(action_a['view_mode'], 'form')
        self.assertEqual(action_a['views'][0][1], 'form')
        self.assertFalse(action_a.get('res_id'))
        self.assertNotIn('restrict_unit_branch_id', action_a.get('context', {}))

        # Case B: With branch selected
        dash_branch = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        action_b = dash_branch.action_new_lease_contract()
        self.assertEqual(action_b['type'], 'ir.actions.act_window')
        self.assertEqual(action_b['res_model'], 'edara.lease.contract')
        self.assertEqual(action_b['view_mode'], 'form')
        self.assertEqual(action_b['views'][0][1], 'form')
        self.assertFalse(action_b.get('res_id'))
        self.assertEqual(action_b['context'].get('restrict_unit_branch_id'), self.branch.id)

    def test_c4_02_action_new_maintenance_request(self):
        """C4-02: action_new_maintenance_request returns blank form action with branch context when branch selected."""
        # Case A: Without branch
        dash_no_branch = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        action_a = dash_no_branch.action_new_maintenance_request()
        self.assertEqual(action_a['type'], 'ir.actions.act_window')
        self.assertEqual(action_a['res_model'], 'edara.maintenance.request')
        self.assertEqual(action_a['view_mode'], 'form')
        self.assertEqual(action_a['views'][0][1], 'form')
        self.assertFalse(action_a.get('res_id'))
        self.assertNotIn('restrict_unit_branch_id', action_a.get('context', {}))

        # Case B: With branch selected
        dash_branch = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        action_b = dash_branch.action_new_maintenance_request()
        self.assertEqual(action_b['type'], 'ir.actions.act_window')
        self.assertEqual(action_b['res_model'], 'edara.maintenance.request')
        self.assertEqual(action_b['view_mode'], 'form')
        self.assertEqual(action_b['views'][0][1], 'form')
        self.assertFalse(action_b.get('res_id'))
        self.assertEqual(action_b['context'].get('restrict_unit_branch_id'), self.branch.id)

    def test_c4_03_action_new_tenant(self):
        """C4-03: action_new_tenant opens res.partner blank form with default_is_company=False and no branch context."""
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        action = dash.action_new_tenant()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['views'][0][1], 'form')
        self.assertFalse(action.get('res_id'))
        self.assertIs(action['context'].get('default_is_company'), False)
        self.assertNotIn('restrict_unit_branch_id', action['context'])

    def test_c4_04_unit_domain_branch_restriction_semantics(self):
        """C4-04: Verify unit domain branch restriction expression and presence in form views."""
        # 1. Test domain expression evaluation and filtering
        branch_2 = self.env['edara.branch'].create({
            'name': 'C4 Test Branch 2', 'code': 'C4B2', 'company_id': self.dash_company.id,
        })
        prop_2 = self.env['edara.property'].create({
            'name': 'C4 Prop 2', 'code': 'C4P2', 'branch_id': branch_2.id,
        })
        bld_2 = self.env['edara.building'].create({
            'name': 'C4 Bld 2', 'code': 'C4B2', 'property_id': prop_2.id,
        })
        unit_in_b2 = self.env['edara.unit'].create({
            'name': 'U-C4-B2', 'code': 'UC4B2', 'building_id': bld_2.id,
        })

        domain_expr = "[('branch_id', '=', context.get('restrict_unit_branch_id'))] if context.get('restrict_unit_branch_id') else []"

        # Restricted context
        res_domain = safe_eval(domain_expr, {'context': {'restrict_unit_branch_id': self.branch.id}})
        self.assertEqual(res_domain, [('branch_id', '=', self.branch.id)])
        restricted_units = self.env['edara.unit'].search(res_domain)
        self.assertIn(self.unit_rented, restricted_units)
        self.assertNotIn(unit_in_b2, restricted_units)

        # Unrestricted context
        unrestricted_domain = safe_eval(domain_expr, {'context': {}})
        self.assertEqual(unrestricted_domain, [])
        unrestricted_units = self.env['edara.unit'].search(unrestricted_domain)
        self.assertIn(self.unit_rented, unrestricted_units)
        self.assertIn(unit_in_b2, unrestricted_units)

        # 2. Verify form view arch has the conditional domain on unit_id
        contract_form = self.env['edara.lease.contract'].get_view(view_type='form')
        self.assertIn('restrict_unit_branch_id', contract_form['arch'])
        maint_form = self.env['edara.maintenance.request'].get_view(view_type='form')
        self.assertIn('restrict_unit_branch_id', maint_form['arch'])

    def test_c4_05_automation_quick_actions_regression(self):
        """C4-05: Existing four automation quick actions execute properly and return success notifications."""
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})

        act_inv = dash.action_manual_generate_due_invoices()
        self.assertEqual(act_inv['type'], 'ir.actions.client')
        self.assertEqual(act_inv['tag'], 'display_notification')
        self.assertEqual(act_inv['params']['type'], 'success')

        act_exp = dash.action_manual_process_lease_expiry()
        self.assertEqual(act_exp['type'], 'ir.actions.client')
        self.assertEqual(act_exp['tag'], 'display_notification')
        self.assertEqual(act_exp['params']['type'], 'success')

        act_rem = dash.action_manual_process_reminders()
        self.assertEqual(act_rem['type'], 'ir.actions.client')
        self.assertEqual(act_rem['tag'], 'display_notification')
        self.assertEqual(act_rem['params']['type'], 'success')

        act_rec = dash.action_manual_generate_recurring_maintenance()
        self.assertEqual(act_rec['type'], 'ir.actions.client')
        self.assertEqual(act_rec['tag'], 'display_notification')
        self.assertEqual(act_rec['params']['type'], 'success')

    # -- Phase C5: Lease Lifecycle Data Completeness & Visual Grouping Tests --

    def _setup_c5_test_fixture(self):
        """Sets up two isolated branches with units and lease contracts covering
        all 7 real lifecycle states for targeted Phase C5 tests."""
        company = self.dash_company
        branch_a = self.env['edara.branch'].create({
            'name': 'C5 Branch A', 'code': 'C5A', 'company_id': company.id,
        })
        branch_b = self.env['edara.branch'].create({
            'name': 'C5 Branch B', 'code': 'C5B', 'company_id': company.id,
        })
        prop_a = self.env['edara.property'].create({
            'name': 'C5 Prop A', 'code': 'C5PA', 'branch_id': branch_a.id,
        })
        prop_b = self.env['edara.property'].create({
            'name': 'C5 Prop B', 'code': 'C5PB', 'branch_id': branch_b.id,
        })
        bld_a = self.env['edara.building'].create({
            'name': 'C5 Bld A', 'code': 'C5BA', 'property_id': prop_a.id,
        })
        bld_b = self.env['edara.building'].create({
            'name': 'C5 Bld B', 'code': 'C5BB', 'property_id': prop_b.id,
        })
        tenant = self.env['res.partner'].create({'name': 'C5 Test Tenant'})
        today = fields.Date.context_today(self)

        def make_unit(bld, name):
            return self.env['edara.unit'].create({
                'name': name, 'code': name, 'building_id': bld.id,
            })

        # Contracts for Branch A: explicit records for each of the 7 states
        # 1. Draft
        u_draft = make_unit(bld_a, 'C5-U-DRAFT')
        c_draft = self.env['edara.lease.contract'].create({
            'unit_id': u_draft.id, 'tenant_id': tenant.id,
            'start_date': today, 'end_date': today + timedelta(days=365),
            'rent_amount': 1000, 'deposit_required': False,
        })

        # 2. Scheduled (start_date in the future)
        u_sched = make_unit(bld_a, 'C5-U-SCHED')
        c_sched = self.env['edara.lease.contract'].create({
            'unit_id': u_sched.id, 'tenant_id': tenant.id,
            'start_date': today + timedelta(days=30), 'end_date': today + timedelta(days=395),
            'rent_amount': 1200, 'deposit_required': False,
        })
        c_sched.action_activate()

        # 3. Active
        u_active = make_unit(bld_a, 'C5-U-ACTIVE')
        c_active = self.env['edara.lease.contract'].create({
            'unit_id': u_active.id, 'tenant_id': tenant.id,
            'start_date': today, 'end_date': today + timedelta(days=365),
            'rent_amount': 1500, 'deposit_required': False,
        })
        c_active.action_activate()

        # 4. Renewed (past term ended, renewed with successor)
        u_renew = make_unit(bld_a, 'C5-U-RENEW')
        c_renew = self.env['edara.lease.contract'].create({
            'unit_id': u_renew.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=400), 'end_date': today - timedelta(days=1),
            'rent_amount': 1100, 'deposit_required': False,
        })
        c_renew.action_activate()
        c_renew.action_renew(today, today + timedelta(days=365), 1150)

        # 5. Terminated (manually terminated before expiry)
        u_term = make_unit(bld_a, 'C5-U-TERM')
        c_term = self.env['edara.lease.contract'].create({
            'unit_id': u_term.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=100), 'end_date': today + timedelta(days=200),
            'rent_amount': 1300, 'deposit_required': False,
        })
        c_term.action_activate()
        c_term.action_terminate(reason='C5 Terminate Test')

        # 6. Expired (term ended with no successor)
        u_exp = make_unit(bld_a, 'C5-U-EXP')
        c_exp = self.env['edara.lease.contract'].create({
            'unit_id': u_exp.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=400), 'end_date': today - timedelta(days=1),
            'rent_amount': 1400, 'deposit_required': False,
        })
        c_exp.action_activate()
        self.env['edara.lease.contract']._cron_expire_contracts()

        # 7. Cancelled (scheduled lease withdrawn before starting)
        u_canc = make_unit(bld_a, 'C5-U-CANC')
        c_canc = self.env['edara.lease.contract'].create({
            'unit_id': u_canc.id, 'tenant_id': tenant.id,
            'start_date': today + timedelta(days=45), 'end_date': today + timedelta(days=410),
            'rent_amount': 1600, 'deposit_required': False,
        })
        c_canc.action_activate()
        c_canc.action_cancel()

        # Branch B: 1 scheduled and 1 cancelled contract
        u_b_sched = make_unit(bld_b, 'C5-UB-SCHED')
        c_b_sched = self.env['edara.lease.contract'].create({
            'unit_id': u_b_sched.id, 'tenant_id': tenant.id,
            'start_date': today + timedelta(days=15), 'end_date': today + timedelta(days=380),
            'rent_amount': 2000, 'deposit_required': False,
        })
        c_b_sched.action_activate()

        u_b_canc = make_unit(bld_b, 'C5-UB-CANC')
        c_b_canc = self.env['edara.lease.contract'].create({
            'unit_id': u_b_canc.id, 'tenant_id': tenant.id,
            'start_date': today + timedelta(days=20), 'end_date': today + timedelta(days=385),
            'rent_amount': 2100, 'deposit_required': False,
        })
        c_b_canc.action_activate()
        c_b_canc.action_cancel()

        return {
            'branch_a': branch_a,
            'branch_b': branch_b,
            'contracts_a': {
                'draft': c_draft,
                'scheduled': c_sched,
                'active': c_active,
                'renewed': c_renew,
                'terminated': c_term,
                'expired': c_exp,
                'cancelled': c_canc,
            },
            'contracts_b': {
                'scheduled': c_b_sched,
                'cancelled': c_b_canc,
            },
        }

    def test_c5_01_seven_lifecycle_states(self):
        """C5-01: Verify dashboard counts include all seven real lifecycle states
        (draft, scheduled, active, renewed, terminated, expired, cancelled) with known counts."""
        f = self._setup_c5_test_fixture()
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})

        self.assertEqual(dash.draft_contracts_count, 1)
        self.assertEqual(dash.scheduled_contracts_count, 1)
        # c_active + renewal successor = 2 active contracts in Branch A
        self.assertEqual(dash.active_contracts_count, 2)
        self.assertEqual(dash.renewed_contracts_count, 1)
        self.assertEqual(dash.terminated_contracts_count, 1)
        self.assertEqual(dash.expired_contracts_count, 1)
        self.assertEqual(dash.cancelled_contracts_count, 1)

    def test_c5_02_scheduled_count(self):
        """C5-02: Verify scheduled_contracts_count matches actual number of scheduled contracts."""
        f = self._setup_c5_test_fixture()
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        self.assertEqual(dash.scheduled_contracts_count, 1)

        # Create another scheduled contract in Branch A
        bld_a = self.env['edara.building'].search([('property_id.branch_id', '=', f['branch_a'].id)], limit=1)
        u_extra = self.env['edara.unit'].create({
            'name': 'C5-U-SCHED-2', 'code': 'C5US2', 'building_id': bld_a.id,
        })
        today = fields.Date.context_today(self)
        c_extra = self.env['edara.lease.contract'].create({
            'unit_id': u_extra.id, 'tenant_id': f['contracts_a']['draft'].tenant_id.id,
            'start_date': today + timedelta(days=50), 'end_date': today + timedelta(days=400),
            'rent_amount': 1250, 'deposit_required': False,
        })
        c_extra.action_activate()
        self.assertEqual(c_extra.state, 'scheduled')

        dash_updated = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        self.assertEqual(dash_updated.scheduled_contracts_count, 2)

    def test_c5_03_cancelled_count(self):
        """C5-03: Verify cancelled_contracts_count matches actual number of cancelled contracts."""
        f = self._setup_c5_test_fixture()
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        self.assertEqual(dash.cancelled_contracts_count, 1)

        # Create and cancel another scheduled contract in Branch A
        bld_a = self.env['edara.building'].search([('property_id.branch_id', '=', f['branch_a'].id)], limit=1)
        u_extra = self.env['edara.unit'].create({
            'name': 'C5-U-CANC-2', 'code': 'C5UC2', 'building_id': bld_a.id,
        })
        today = fields.Date.context_today(self)
        c_extra = self.env['edara.lease.contract'].create({
            'unit_id': u_extra.id, 'tenant_id': f['contracts_a']['draft'].tenant_id.id,
            'start_date': today + timedelta(days=60), 'end_date': today + timedelta(days=410),
            'rent_amount': 1350, 'deposit_required': False,
        })
        c_extra.action_activate()
        c_extra.action_cancel()
        self.assertEqual(c_extra.state, 'cancelled')

        dash_updated = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        self.assertEqual(dash_updated.cancelled_contracts_count, 2)

    def test_c5_04_branch_filtering(self):
        """C5-04: Verify scheduled and cancelled counts respect the existing dashboard branch context."""
        f = self._setup_c5_test_fixture()

        # Branch A Dashboard
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        self.assertEqual(dash_a.scheduled_contracts_count, 1)
        self.assertEqual(dash_a.cancelled_contracts_count, 1)
        self.assertEqual(dash_a.draft_contracts_count, 1)

        # Branch B Dashboard
        dash_b = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_b'].id})
        self.assertEqual(dash_b.scheduled_contracts_count, 1)
        self.assertEqual(dash_b.cancelled_contracts_count, 1)
        # Branch B has zero draft contracts
        self.assertEqual(dash_b.draft_contracts_count, 0)

        # Verify cross-branch contract IDs are excluded
        sched_contracts_in_a = self.env['edara.lease.contract'].search([
            ('branch_id', '=', f['branch_a'].id), ('state', '=', 'scheduled')
        ])
        self.assertIn(f['contracts_a']['scheduled'], sched_contracts_in_a)
        self.assertNotIn(f['contracts_b']['scheduled'], sched_contracts_in_a)

    def test_c5_05_drilldown_scheduled(self):
        """C5-05: action_view_contracts_scheduled returns correct native act_window with scheduled state and branch filter."""
        f = self._setup_c5_test_fixture()

        # Case A: With Branch Selected
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        action_a = dash_a.action_view_contracts_scheduled()
        self.assertEqual(action_a['type'], 'ir.actions.act_window')
        self.assertEqual(action_a['res_model'], 'edara.lease.contract')
        self.assertIn(('state', '=', 'scheduled'), action_a['domain'])
        self.assertIn(('branch_id', '=', f['branch_a'].id), action_a['domain'])

        matched_a = self.env['edara.lease.contract'].search(action_a['domain'])
        self.assertIn(f['contracts_a']['scheduled'], matched_a)
        self.assertNotIn(f['contracts_b']['scheduled'], matched_a)

        # Case B: Without Branch Selected (all accessible branches)
        dash_all = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        action_all = dash_all.action_view_contracts_scheduled()
        self.assertEqual(action_all['type'], 'ir.actions.act_window')
        self.assertEqual(action_all['res_model'], 'edara.lease.contract')
        self.assertIn(('state', '=', 'scheduled'), action_all['domain'])
        # No branch_id restriction in domain
        self.assertFalse(any(t[0] == 'branch_id' for t in action_all['domain']))

        matched_all = self.env['edara.lease.contract'].search(action_all['domain'])
        self.assertIn(f['contracts_a']['scheduled'], matched_all)
        self.assertIn(f['contracts_b']['scheduled'], matched_all)

    def test_c5_06_drilldown_cancelled(self):
        """C5-06: action_view_contracts_cancelled returns correct native act_window with cancelled state and branch filter."""
        f = self._setup_c5_test_fixture()

        # Case A: With Branch Selected
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        action_a = dash_a.action_view_contracts_cancelled()
        self.assertEqual(action_a['type'], 'ir.actions.act_window')
        self.assertEqual(action_a['res_model'], 'edara.lease.contract')
        self.assertIn(('state', '=', 'cancelled'), action_a['domain'])
        self.assertIn(('branch_id', '=', f['branch_a'].id), action_a['domain'])

        matched_a = self.env['edara.lease.contract'].search(action_a['domain'])
        self.assertIn(f['contracts_a']['cancelled'], matched_a)
        self.assertNotIn(f['contracts_b']['cancelled'], matched_a)

        # Case B: Without Branch Selected
        dash_all = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        action_all = dash_all.action_view_contracts_cancelled()
        self.assertEqual(action_all['type'], 'ir.actions.act_window')
        self.assertEqual(action_all['res_model'], 'edara.lease.contract')
        self.assertIn(('state', '=', 'cancelled'), action_all['domain'])
        self.assertFalse(any(t[0] == 'branch_id' for t in action_all['domain']))

        matched_all = self.env['edara.lease.contract'].search(action_all['domain'])
        self.assertIn(f['contracts_a']['cancelled'], matched_all)
        self.assertIn(f['contracts_b']['cancelled'], matched_all)

    def test_c5_07_existing_lifecycle_regression(self):
        """C5-07: Original five lifecycle counts remain correct and unregressed."""
        f = self._setup_c5_test_fixture()
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})

        self.assertEqual(dash.draft_contracts_count, 1)
        self.assertEqual(dash.active_contracts_count, 2)
        self.assertEqual(dash.renewed_contracts_count, 1)
        self.assertEqual(dash.terminated_contracts_count, 1)
        self.assertEqual(dash.expired_contracts_count, 1)

    def test_c5_08_empty_states(self):
        """C5-08: Scheduled and cancelled counts return 0 when no such contracts exist."""
        branch_empty = self.env['edara.branch'].create({
            'name': 'C5 Empty Branch', 'code': 'C5EMPTY', 'company_id': self.dash_company.id,
        })
        dash_empty = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': branch_empty.id})

        self.assertEqual(dash_empty.scheduled_contracts_count, 0)
        self.assertEqual(dash_empty.cancelled_contracts_count, 0)
        self.assertEqual(dash_empty.draft_contracts_count, 0)
        self.assertEqual(dash_empty.active_contracts_count, 0)
        self.assertEqual(dash_empty.renewed_contracts_count, 0)
        self.assertEqual(dash_empty.terminated_contracts_count, 0)
        self.assertEqual(dash_empty.expired_contracts_count, 0)

    def test_c5_09_existing_actions_regression(self):
        """C5-09: Existing contract actions and timeline action remain unchanged and functional."""
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})

        expected = [
            ('action_view_contracts_draft', [('state', '=', 'draft')]),
            ('action_view_contracts_active', [('state', '=', 'active')]),
            ('action_view_contracts_renewed', [('state', '=', 'renewed')]),
            ('action_view_contracts_terminated', [('state', '=', 'terminated')]),
            ('action_view_contracts_expired', [('state', '=', 'expired')]),
        ]
        for method_name, state_domain in expected:
            action = getattr(dash, method_name)()
            self.assertEqual(action['type'], 'ir.actions.act_window', method_name)
            self.assertEqual(action['res_model'], 'edara.lease.contract', method_name)
            self.assertIn(state_domain[0], action['domain'], method_name)
            self.assertIn(('branch_id', '=', self.branch.id), action['domain'], method_name)

        # Lease timeline action
        action_timeline = dash.action_view_lease_timeline()
        self.assertEqual(action_timeline['type'], 'ir.actions.act_window')
        self.assertEqual(action_timeline['res_model'], 'edara.lease.contract')
        self.assertEqual(action_timeline['views'][0][1], 'gantt')

    # =========================================================================
    # Phase C6: Security Deposit Liability & Settlement Tests
    # =========================================================================

    def _setup_c6_test_fixture(self):
        """Phase C6: Multi-branch, multi-currency fixture for Security Deposit tests."""
        today = fields.Date.context_today(self)
        company = self.dash_company
        comp_cur = company.currency_id

        # Setup second currency with rate 2.0 (so 500 second currency = 250 company currency)
        other_cur = self.env['res.currency'].with_context(active_test=False).search([
            ('name', '!=', comp_cur.name),
            ('name', 'in', ('USD', 'EUR', 'ILS', 'JOD'))
        ], limit=1)
        other_cur.active = True
        self.env['res.currency.rate'].search([
            ('currency_id', '=', other_cur.id),
            ('company_id', '=', company.id),
        ]).unlink()
        self.env['res.currency.rate'].create({
            'currency_id': other_cur.id,
            'company_id': company.id,
            'name': today,
            'rate': 2.0,
        })

        branch_a = self.env['edara.branch'].create({
            'name': 'C6 Branch A', 'code': 'C6BA', 'company_id': company.id,
        })
        branch_b = self.env['edara.branch'].create({
            'name': 'C6 Branch B', 'code': 'C6BB', 'company_id': company.id,
        })

        prop_a = self.env['edara.property'].create({
            'name': 'C6 Prop A', 'code': 'C6PA', 'branch_id': branch_a.id,
        })
        bld_a = self.env['edara.building'].create({
            'name': 'C6 Bld A', 'code': 'C6BLDA', 'property_id': prop_a.id,
        })
        prop_b = self.env['edara.property'].create({
            'name': 'C6 Prop B', 'code': 'C6PB', 'branch_id': branch_b.id,
        })
        bld_b = self.env['edara.building'].create({
            'name': 'C6 Bld B', 'code': 'C6BLDB', 'property_id': prop_b.id,
        })

        tenant = self.env['res.partner'].create({'name': 'C6 Tenant', 'company_id': company.id})

        def make_unit(bld, name):
            return self.env['edara.unit'].create({
                'name': name, 'code': name.replace('-', ''), 'building_id': bld.id,
            })

        # 1. Branch A: Active lease, company currency, balance=1000 (state='held')
        u_a1 = make_unit(bld_a, 'C6-UA-1')
        c_a1 = self.env['edara.lease.contract'].create({
            'unit_id': u_a1.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=30), 'end_date': today + timedelta(days=335),
            'rent_amount': 1000, 'deposit_required': True, 'deposit_amount': 1000,
        })
        c_a1.action_activate()
        dep_a1 = self.env['edara.deposit'].create({'contract_id': c_a1.id, 'amount': 1000})
        self.env['edara.deposit.transaction'].create({
            'deposit_id': dep_a1.id, 'transaction_type': 'held', 'amount': 1000,
        })

        # 2. Branch A: Active lease, other_cur, balance=500 (state='held')
        u_a2 = make_unit(bld_a, 'C6-UA-2')
        c_a2 = self.env['edara.lease.contract'].create({
            'unit_id': u_a2.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=20), 'end_date': today + timedelta(days=345),
            'rent_amount': 500, 'currency_id': other_cur.id,
            'deposit_required': True, 'deposit_amount': 500,
        })
        c_a2.action_activate()
        dep_a2 = self.env['edara.deposit'].create({'contract_id': c_a2.id, 'amount': 500})
        self.env['edara.deposit.transaction'].create({
            'deposit_id': dep_a2.id, 'transaction_type': 'held', 'amount': 500,
        })

        # 3. Branch A: Terminated lease, company currency, balance=800 (state='held')
        u_a_term = make_unit(bld_a, 'C6-UA-TERM')
        c_a_term = self.env['edara.lease.contract'].create({
            'unit_id': u_a_term.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=120), 'end_date': today + timedelta(days=200),
            'rent_amount': 800, 'deposit_required': True, 'deposit_amount': 800,
        })
        c_a_term.action_activate()
        c_a_term.action_terminate(reason='C6 Terminate Test')
        dep_a_term = self.env['edara.deposit'].create({'contract_id': c_a_term.id, 'amount': 800})
        self.env['edara.deposit.transaction'].create({
            'deposit_id': dep_a_term.id, 'transaction_type': 'held', 'amount': 800,
        })

        # 4. Branch A: Cancelled lease, company currency, balance=400 (state='held')
        u_a_canc = make_unit(bld_a, 'C6-UA-CANC')
        c_a_canc = self.env['edara.lease.contract'].create({
            'unit_id': u_a_canc.id, 'tenant_id': tenant.id,
            'start_date': today + timedelta(days=30), 'end_date': today + timedelta(days=395),
            'rent_amount': 400, 'deposit_required': True, 'deposit_amount': 400,
        })
        c_a_canc.action_activate()
        c_a_canc.action_cancel()
        dep_a_canc = self.env['edara.deposit'].create({'contract_id': c_a_canc.id, 'amount': 400})
        self.env['edara.deposit.transaction'].create({
            'deposit_id': dep_a_canc.id, 'transaction_type': 'held', 'amount': 400,
        })

        # 5. Branch A: Expired lease, settled deposit (held=600, refund=600 -> balance=0, state='closed')
        u_a_exp = make_unit(bld_a, 'C6-UA-EXP')
        c_a_exp = self.env['edara.lease.contract'].create({
            'unit_id': u_a_exp.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=400), 'end_date': today - timedelta(days=1),
            'rent_amount': 600, 'deposit_required': True, 'deposit_amount': 600,
        })
        c_a_exp.action_activate()
        self.env['edara.lease.contract']._cron_expire_contracts()
        dep_a_exp = self.env['edara.deposit'].create({'contract_id': c_a_exp.id, 'amount': 600})
        self.env['edara.deposit.transaction'].create({
            'deposit_id': dep_a_exp.id, 'transaction_type': 'held', 'amount': 600,
        })
        self.env['edara.deposit.transaction'].create({
            'deposit_id': dep_a_exp.id, 'transaction_type': 'refund', 'amount': 600,
        })

        # 6. Branch A: Draft lease, draft deposit (amount=300, no transactions -> balance=0, state='draft')
        u_a_draft = make_unit(bld_a, 'C6-UA-DRAFT')
        c_a_draft = self.env['edara.lease.contract'].create({
            'unit_id': u_a_draft.id, 'tenant_id': tenant.id,
            'start_date': today + timedelta(days=10), 'end_date': today + timedelta(days=375),
            'rent_amount': 300, 'deposit_required': True, 'deposit_amount': 300,
        })
        dep_a_draft = self.env['edara.deposit'].create({'contract_id': c_a_draft.id, 'amount': 300})

        # 7. Branch B: Active lease, company currency, balance=700 (state='held')
        u_b1 = make_unit(bld_b, 'C6-UB-1')
        c_b1 = self.env['edara.lease.contract'].create({
            'unit_id': u_b1.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=10), 'end_date': today + timedelta(days=355),
            'rent_amount': 700, 'deposit_required': True, 'deposit_amount': 700,
        })
        c_b1.action_activate()
        dep_b1 = self.env['edara.deposit'].create({'contract_id': c_b1.id, 'amount': 700})
        self.env['edara.deposit.transaction'].create({
            'deposit_id': dep_b1.id, 'transaction_type': 'held', 'amount': 700,
        })

        return {
            'branch_a': branch_a,
            'branch_b': branch_b,
            'other_cur': other_cur,
            'deposits_a': {
                'held_comp': dep_a1,
                'held_other': dep_a2,
                'term_unsettled': dep_a_term,
                'canc_unsettled': dep_a_canc,
                'exp_settled': dep_a_exp,
                'draft': dep_a_draft,
            },
            'deposits_b': {
                'held_comp': dep_b1,
            },
        }

    def test_c6_01_held_count(self):
        """C6-01: Verify dashboard correctly counts deposits in state = 'held'."""
        f = self._setup_c6_test_fixture()
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        # Branch A has 4 held deposits (held_comp, held_other, term_unsettled, canc_unsettled)
        self.assertEqual(dash_a.held_deposits_count, 4)

        # Branch B has 1 held deposit
        dash_b = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_b'].id})
        self.assertEqual(dash_b.held_deposits_count, 1)

    def test_c6_02_currency_safe_total(self):
        """C6-02: Verify multi-currency conversion to company currency (rate != 1.0) and proves raw sum is not used."""
        f = self._setup_c6_test_fixture()
        today = fields.Date.context_today(self)
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})

        comp_cur = self.dash_company.currency_id
        other_cur = f['other_cur']

        # Independent calculation of expected converted total
        # In Branch A:
        # held_comp: 1000 in company currency
        # held_other: 500 in other_cur (rate 2.0 -> 250 in company currency)
        # term_unsettled: 800 in company currency
        # canc_unsettled: 400 in company currency
        converted_other = other_cur._convert(500.0, comp_cur, self.dash_company, today)
        expected_total = 1000.0 + converted_other + 800.0 + 400.0
        naive_raw_sum = 1000.0 + 500.0 + 800.0 + 400.0

        self.assertAlmostEqual(dash_a.total_held_deposit_amount, expected_total, places=2)
        # Explicit proof: multi-currency conversion differs from naive raw sum
        self.assertNotEqual(round(dash_a.total_held_deposit_amount, 2), round(naive_raw_sum, 2))

    def test_c6_03_unsettled_closed_lease(self):
        """C6-03: Verify deposit is counted when balance > 0 and lease state in (terminated, expired, cancelled)."""
        f = self._setup_c6_test_fixture()
        today = fields.Date.context_today(self)
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})

        # Initially Branch A has 2 unsettled closed leases: term_unsettled (800) and canc_unsettled (400)
        self.assertEqual(dash_a.unsettled_closed_deposits_count, 2)

        # Now create an expired lease with balance > 0 to verify the third closed state ('expired')
        bld_a = self.env['edara.building'].search([('property_id.branch_id', '=', f['branch_a'].id)], limit=1)
        u_exp2 = self.env['edara.unit'].create({
            'name': 'C6-UA-EXP2', 'code': 'C6UAEXP2', 'building_id': bld_a.id,
        })
        tenant = f['deposits_a']['held_comp'].tenant_id
        c_exp2 = self.env['edara.lease.contract'].create({
            'unit_id': u_exp2.id, 'tenant_id': tenant.id,
            'start_date': today - timedelta(days=200), 'end_date': today - timedelta(days=2),
            'rent_amount': 550, 'deposit_required': True, 'deposit_amount': 550,
        })
        c_exp2.action_activate()
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(c_exp2.state, 'expired')

        dep_exp2 = self.env['edara.deposit'].create({'contract_id': c_exp2.id, 'amount': 550})
        self.env['edara.deposit.transaction'].create({
            'deposit_id': dep_exp2.id, 'transaction_type': 'held', 'amount': 550,
        })
        self.assertEqual(dep_exp2.balance, 550)

        dash_a_updated = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        # Now 3: terminated, cancelled, and expired
        self.assertEqual(dash_a_updated.unsettled_closed_deposits_count, 3)

    def test_c6_04_fully_settled_closed_lease_excluded(self):
        """C6-04: A deposit on terminated/expired/cancelled with balance = 0 must NOT be counted as unsettled."""
        f = self._setup_c6_test_fixture()
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})

        # exp_settled is on an expired contract but has balance == 0 (state='closed')
        dep_exp_settled = f['deposits_a']['exp_settled']
        self.assertEqual(dep_exp_settled.contract_id.state, 'expired')
        self.assertEqual(dep_exp_settled.balance, 0.0)

        # Unsettled count is 2 (term_unsettled + canc_unsettled), exp_settled is excluded
        self.assertEqual(dash_a.unsettled_closed_deposits_count, 2)

    def test_c6_05_active_lease_excluded(self):
        """C6-05: A deposit with balance > 0 on an active lease must NOT be counted in unsettled_closed_deposits_count."""
        f = self._setup_c6_test_fixture()
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})

        dep_active = f['deposits_a']['held_comp']
        self.assertEqual(dep_active.contract_id.state, 'active')
        self.assertGreater(dep_active.balance, 0)

        # Active contracts with positive balances are held, but not in unsettled closed count
        self.assertEqual(dash_a.unsettled_closed_deposits_count, 2)

    def test_c6_06_branch_isolation(self):
        """C6-06: Deposits across two branches are strictly isolated by branch, and aggregate when no branch is selected."""
        f = self._setup_c6_test_fixture()

        # Branch A dashboard
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        self.assertEqual(dash_a.held_deposits_count, 4)
        self.assertEqual(dash_a.unsettled_closed_deposits_count, 2)

        # Branch B dashboard
        dash_b = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_b'].id})
        self.assertEqual(dash_b.held_deposits_count, 1)
        self.assertEqual(dash_b.unsettled_closed_deposits_count, 0)
        self.assertEqual(dash_b.total_held_deposit_amount, 700.0)

        # Global dashboard (no branch selected)
        dash_all = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        self.assertEqual(dash_all.held_deposits_count, 5)  # 4 + 1
        self.assertEqual(dash_all.unsettled_closed_deposits_count, 2)  # 2 + 0
        self.assertAlmostEqual(
            dash_all.total_held_deposit_amount,
            dash_a.total_held_deposit_amount + dash_b.total_held_deposit_amount,
            places=2
        )

    def test_c6_07_empty_state(self):
        """C6-07: A company/branch with no deposits produces 0 values with no exception."""
        branch_empty = self.env['edara.branch'].create({
            'name': 'C6 Empty Branch', 'code': 'C6EMPTY', 'company_id': self.dash_company.id,
        })
        dash_empty = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': branch_empty.id})

        self.assertEqual(dash_empty.total_held_deposit_amount, 0.0)
        self.assertEqual(dash_empty.held_deposits_count, 0)
        self.assertEqual(dash_empty.unsettled_closed_deposits_count, 0)

    def test_c6_08_viewer_access(self):
        """C6-08: An EDARA viewer without native accounting access can read C6 deposit metrics and execute actions."""
        f = self._setup_c6_test_fixture()
        viewer = new_test_user(
            self.env, login='c6_dash_viewer@example.com', groups='property_managment.group_edara_viewer',
            company_id=self.dash_company.id, company_ids=[(6, 0, [self.dash_company.id])],
        )
        f['branch_a'].user_ids = [(4, viewer.id)]

        dash_viewer = self.env['edara.dashboard'].with_user(viewer).create({'branch_id': f['branch_a'].id})
        # Viewer does not have native accounting access
        self.assertFalse(dash_viewer.has_accounting_access)

        # Viewer can read all C6 metrics without error
        self.assertEqual(dash_viewer.held_deposits_count, 4)
        self.assertEqual(dash_viewer.unsettled_closed_deposits_count, 2)
        self.assertGreater(dash_viewer.total_held_deposit_amount, 0.0)

        # Viewer can call C6 actions without error
        act_held = dash_viewer.action_view_deposits_held()
        self.assertEqual(act_held['res_model'], 'edara.deposit')
        act_unsettled = dash_viewer.action_view_deposits_unsettled_closed()
        self.assertEqual(act_unsettled['res_model'], 'edara.deposit')

    def test_c6_09_drilldown_held(self):
        """C6-09: action_view_deposits_held returns act_window with ('state', '=', 'held') and branch restriction."""
        f = self._setup_c6_test_fixture()

        # Case A: With Branch Selected
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        action_a = dash_a.action_view_deposits_held()
        self.assertEqual(action_a['type'], 'ir.actions.act_window')
        self.assertEqual(action_a['res_model'], 'edara.deposit')
        self.assertIn(('state', '=', 'held'), action_a['domain'])
        self.assertIn(('branch_id', '=', f['branch_a'].id), action_a['domain'])

        matched_a = self.env['edara.deposit'].search(action_a['domain'])
        self.assertIn(f['deposits_a']['held_comp'], matched_a)
        self.assertIn(f['deposits_a']['held_other'], matched_a)
        self.assertIn(f['deposits_a']['term_unsettled'], matched_a)
        self.assertIn(f['deposits_a']['canc_unsettled'], matched_a)
        self.assertNotIn(f['deposits_b']['held_comp'], matched_a)
        self.assertNotIn(f['deposits_a']['exp_settled'], matched_a)
        self.assertNotIn(f['deposits_a']['draft'], matched_a)

        # Case B: Without Branch Selected
        dash_all = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        action_all = dash_all.action_view_deposits_held()
        self.assertEqual(action_all['res_model'], 'edara.deposit')
        self.assertIn(('state', '=', 'held'), action_all['domain'])
        self.assertFalse(any(t[0] == 'branch_id' for t in action_all['domain']))

        matched_all = self.env['edara.deposit'].search(action_all['domain'])
        self.assertIn(f['deposits_a']['held_comp'], matched_all)
        self.assertIn(f['deposits_b']['held_comp'], matched_all)

    def test_c6_10_drilldown_unsettled_closed(self):
        """C6-10: action_view_deposits_unsettled_closed returns act_window with balance > 0 and closed lease states."""
        f = self._setup_c6_test_fixture()

        # Case A: With Branch Selected
        dash_a = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': f['branch_a'].id})
        action_a = dash_a.action_view_deposits_unsettled_closed()
        self.assertEqual(action_a['type'], 'ir.actions.act_window')
        self.assertEqual(action_a['res_model'], 'edara.deposit')
        self.assertIn(('balance', '>', 0), action_a['domain'])
        self.assertIn(('contract_id.state', 'in', ('terminated', 'expired', 'cancelled')), action_a['domain'])
        self.assertIn(('branch_id', '=', f['branch_a'].id), action_a['domain'])

        matched_a = self.env['edara.deposit'].search(action_a['domain'])
        self.assertIn(f['deposits_a']['term_unsettled'], matched_a)
        self.assertIn(f['deposits_a']['canc_unsettled'], matched_a)
        self.assertNotIn(f['deposits_a']['held_comp'], matched_a)  # active lease
        self.assertNotIn(f['deposits_a']['exp_settled'], matched_a)  # balance = 0
        self.assertNotIn(f['deposits_b']['held_comp'], matched_a)  # different branch

        # Case B: Without Branch Selected
        dash_all = self.env['edara.dashboard'].with_user(self.dash_admin).create({})
        action_all = dash_all.action_view_deposits_unsettled_closed()
        self.assertEqual(action_all['res_model'], 'edara.deposit')
        self.assertIn(('balance', '>', 0), action_all['domain'])
        self.assertIn(('contract_id.state', 'in', ('terminated', 'expired', 'cancelled')), action_all['domain'])
        self.assertFalse(any(t[0] == 'branch_id' for t in action_all['domain']))

    def test_c6_11_regression(self):
        """C6-11: Full dashboard existing behavior (C1-C5) remains intact."""
        dash = self.env['edara.dashboard'].with_user(self.dash_admin).create({'branch_id': self.branch.id})
        self.assertEqual(dash.total_properties, 1)
        self.assertEqual(dash.total_buildings, 1)
        self.assertEqual(dash.total_units, 2)
        self.assertEqual(dash.occupied_units, 1)
        self.assertEqual(dash.available_units, 1)
        self.assertEqual(dash.active_contracts_count, 1)
