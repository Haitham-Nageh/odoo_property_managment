from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


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
            'start_date': today, 'end_date': today + timedelta(days=365),
            'rent_amount': 900, 'deposit_required': False,
        })
        renew_contract.action_activate()
        renew_contract.action_renew(today + timedelta(days=1), today + timedelta(days=730), 950)

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
            ('action_view_contracts_active', 'edara.lease.contract', [('state', '=', 'active')]),
            ('action_view_contracts_renewed', 'edara.lease.contract', [('state', '=', 'renewed')]),
            ('action_view_contracts_terminated', 'edara.lease.contract', [('state', '=', 'terminated')]),
            ('action_view_contracts_expired', 'edara.lease.contract', [('state', '=', 'expired')]),
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
                             'action_view_maintenance_sla_breached'):
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
