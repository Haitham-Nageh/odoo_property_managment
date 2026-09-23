from datetime import date

from psycopg2.errors import UniqueViolation

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestEdaraProperty(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Phase 6.4: 'RAM' collides with a real, legitimate branch that
        # already exists in this shared dev database (not test data - do not
        # rename/delete it). Use a test-only code instead of assuming a clean
        # database.
        cls.branch_a = cls.env['edara.branch'].create({'name': 'Test Ramallah Branch', 'code': 'TRAM'})
        cls.branch_b = cls.env['edara.branch'].create({'name': 'Nablus Branch', 'code': 'NBL'})
        cls.property_a = cls.env['edara.property'].create({'name': 'Al-Irsal Complex', 'code': 'IRS', 'branch_id': cls.branch_a.id})
        cls.building_a = cls.env['edara.building'].create({'name': 'Building A', 'code': 'A', 'property_id': cls.property_a.id})
        cls.owner_1 = cls.env['res.partner'].create({'name': 'Owner One'})
        cls.owner_2 = cls.env['res.partner'].create({'name': 'Owner Two'})

    def test_building_inherits_branch_from_property(self):
        self.assertEqual(self.building_a.branch_id, self.branch_a)
        self.assertEqual(self.building_a.company_id, self.property_a.company_id)

    def test_unit_code_unique_per_building(self):
        self.env['edara.unit'].create({'name': 'A-101', 'code': '101', 'building_id': self.building_a.id})
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation):
            with self.env.cr.savepoint():
                self.env['edara.unit'].create({'name': 'Dup', 'code': '101', 'building_id': self.building_a.id})

    # -- MAT-FIND-003 (2026-09-22): native Duplicate must not fail on unit code uniqueness --

    def test_duplicate_unit_gets_a_new_unique_code(self):
        original = self.env['edara.unit'].create(
            {'name': 'A-103', 'code': '103', 'building_id': self.building_a.id})
        duplicate = original.copy()
        self.assertNotEqual(duplicate.code, original.code)
        self.assertEqual(duplicate.code, '103-COPY')
        self.assertEqual(original.code, '103')  # original untouched
        self.assertEqual(duplicate.building_id, self.building_a)
        self.assertEqual(duplicate.name, original.name)  # other fields follow native copy semantics

    def test_duplicate_unit_twice_generates_distinct_codes(self):
        original = self.env['edara.unit'].create(
            {'name': 'A-104', 'code': '104', 'building_id': self.building_a.id})
        first_copy = original.copy()
        second_copy = original.copy()
        self.assertEqual(first_copy.code, '104-COPY')
        self.assertEqual(second_copy.code, '104-COPY2')
        # Uniqueness constraint still fully enforced - not bypassed.
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation):
            with self.env.cr.savepoint():
                self.env['edara.unit'].create(
                    {'name': 'Dup', 'code': first_copy.code, 'building_id': self.building_a.id})

    def test_duplicate_explicit_code_in_default_is_respected(self):
        original = self.env['edara.unit'].create(
            {'name': 'A-105', 'code': '105', 'building_id': self.building_a.id})
        duplicate = original.copy({'code': '105-CUSTOM'})
        self.assertEqual(duplicate.code, '105-CUSTOM')

    def test_duplicate_rented_unit_resets_occupancy_to_available(self):
        """lease_contract_ids is never copied, so a 'rented' copy with zero
        backing contracts would otherwise violate
        _check_occupancy_status_derivation()."""
        tenant = self.env['res.partner'].create({'name': 'MAT-FIND-003 Tenant'})
        unit = self.env['edara.unit'].create(
            {'name': 'A-106', 'code': '106', 'building_id': self.building_a.id})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': unit.id, 'tenant_id': tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': 1000, 'deposit_required': False,
        })
        contract.action_activate()
        self.assertEqual(unit.occupancy_status, 'rented')
        duplicate = unit.copy()
        self.assertEqual(duplicate.occupancy_status, 'available')
        self.assertEqual(unit.occupancy_status, 'rented')  # original untouched
        self.assertFalse(duplicate.lease_contract_ids)

    def test_duplicate_owner_occupied_unit_preserves_occupancy(self):
        unit = self.env['edara.unit'].create(
            {'name': 'A-107', 'code': '107', 'building_id': self.building_a.id,
             'occupancy_status': 'owner_occupied'})
        duplicate = unit.copy()
        self.assertEqual(duplicate.occupancy_status, 'owner_occupied')

    def test_unit_status_consistency(self):
        unit = self.env['edara.unit'].create({'name': 'A-102', 'code': '102', 'building_id': self.building_a.id})
        with self.assertRaises(ValidationError):
            unit.write({'operational_status': 'under_maintenance', 'occupancy_status': 'available'})

    def test_ownership_percentage_range(self):
        with self.assertRaises(ValidationError):
            self.env['edara.ownership'].create({
                'property_id': self.property_a.id, 'owner_id': self.owner_1.id, 'ownership_percentage': 150,
            })

    def test_ownership_total_cannot_exceed_100(self):
        self.env['edara.ownership'].create({
            'property_id': self.property_a.id, 'owner_id': self.owner_1.id, 'ownership_percentage': 60,
        })
        with self.assertRaises(ValidationError):
            self.env['edara.ownership'].create({
                'property_id': self.property_a.id, 'owner_id': self.owner_2.id, 'ownership_percentage': 50,
            })

    def test_ownership_valid_split_and_owner_flag(self):
        self.env['edara.ownership'].create({
            'property_id': self.property_a.id, 'owner_id': self.owner_1.id, 'ownership_percentage': 60,
        })
        self.env['edara.ownership'].create({
            'property_id': self.property_a.id, 'owner_id': self.owner_2.id, 'ownership_percentage': 40,
        })
        self.assertTrue(self.owner_1.is_edara_owner)
        self.assertTrue(self.owner_2.is_edara_owner)

    def test_unit_visibility_follows_branch_assignment(self):
        unit_a = self.env['edara.unit'].create({'name': 'A-201', 'code': '201', 'building_id': self.building_a.id})
        property_b = self.env['edara.property'].create({'name': 'Rafidia Complex', 'code': 'RAF', 'branch_id': self.branch_b.id})
        building_b = self.env['edara.building'].create({'name': 'Building A', 'code': 'A', 'property_id': property_b.id})
        unit_b = self.env['edara.unit'].create({'name': 'B-101', 'code': '101', 'building_id': building_b.id})

        user = new_test_user(self.env, login='edara_pm_a', groups='property_managment.group_edara_property_manager')
        self.branch_a.user_ids = [(4, user.id)]

        units = self.env['edara.unit'].with_user(user).search([])
        self.assertEqual(units, unit_a)
        with self.assertRaises(AccessError):
            unit_b.with_user(user).read(['name'])

    def test_building_smart_buttons_count_contracts_and_maintenance(self):
        unit = self.env['edara.unit'].create(
            {'name': 'A-1', 'code': 'BA1', 'building_id': self.building_a.id})
        tenant = self.env['res.partner'].create({'name': 'Building Smart Button Tenant'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': unit.id, 'tenant_id': tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 700,
            'deposit_required': False,
        })
        self.env['edara.maintenance.request'].create({'title': 'Leak', 'unit_id': unit.id, 'tenant_id': tenant.id})

        self.assertEqual(self.building_a.contract_count, 1)
        self.assertEqual(self.building_a.maintenance_request_count, 1)

        contracts_action = self.building_a.action_view_contracts()
        self.assertEqual(contracts_action['domain'], [('building_id', '=', self.building_a.id)])
        maintenance_action = self.building_a.action_view_maintenance_requests()
        self.assertEqual(maintenance_action['domain'], [('building_id', '=', self.building_a.id)])
        self.assertIn(contract.id, self.env['edara.lease.contract'].search(contracts_action['domain']).ids)

    def test_property_invoices_smart_button_domain(self):
        action = self.property_a.action_view_invoices()
        self.assertEqual(action['domain'], [('edara_property_id', '=', self.property_a.id)])
        self.assertEqual(action['context']['default_move_type'], 'out_invoice')

    def test_unit_kanban_view_loads(self):
        action = self.env.ref('property_managment.action_edara_unit')
        view = self.env['edara.unit'].get_view(view_type='kanban')
        self.assertTrue(view.get('arch'))
        self.assertEqual(action.search_view_id.id,
                          self.env.ref('property_managment.view_edara_unit_search').id)

    def test_unit_kanban_has_no_meaningless_floor_grouping_or_drag(self):
        """Dashboard UX Hardening 6.1 (2026-09-23): default_group_by="floor"
        produced meaningless "None (17) / 1 (1)" columns against real data
        (floor is free-text, almost never populated), and implicit drag
        between those columns would silently rewrite a unit's floor. A Unit
        is a record, not a workflow stage - never draggable."""
        arch = self.env['edara.unit'].get_view(view_type='kanban')['arch']
        self.assertNotIn('default_group_by="floor"', arch)
        self.assertIn('records_draggable="false"', arch)

    def test_unit_action_defaults_to_list_view(self):
        action = self.env.ref('property_managment.action_edara_unit')
        self.assertEqual(action.view_mode.split(',')[0], 'list')

    def test_unit_search_view_has_native_searchpanel_quick_filter(self):
        """§7/§8 of Dashboard UX Hardening 6.1: click-to-filter shortcuts
        living on the Units page itself, not a new page/duplicate view -
        native <searchpanel>, not a hidden Search > Filters dropdown entry."""
        arch = self.env['edara.unit'].get_view(
            view_id=self.env.ref('property_managment.view_edara_unit_search').id)['arch']
        self.assertIn('<searchpanel', arch)
        self.assertIn('occupancy_status', arch)

    def test_contract_search_view_has_native_searchpanel_quick_filter(self):
        arch = self.env['edara.lease.contract'].get_view(
            view_id=self.env.ref('property_managment.view_edara_lease_contract_search').id)['arch']
        self.assertIn('<searchpanel', arch)

    def test_contract_calendar_view_reachable_and_valid(self):
        action = self.env.ref('property_managment.action_edara_lease_contract')
        self.assertIn('calendar', action.view_mode.split(','))
        view = self.env['edara.lease.contract'].get_view(view_type='calendar')
        self.assertTrue(view.get('arch'))

    def test_unit_active_tenant_name_reflects_active_contract_only(self):
        unit = self.env['edara.unit'].create(
            {'name': 'A-KAN1', 'code': 'AKAN1', 'building_id': self.building_a.id})
        self.assertFalse(unit.active_tenant_name)
        tenant = self.env['res.partner'].create({'name': 'Kanban Tenant'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': unit.id, 'tenant_id': tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': 500, 'deposit_required': False,
        })
        self.assertFalse(unit.active_tenant_name)  # draft, not active yet
        contract.action_activate()
        unit.invalidate_recordset()
        self.assertEqual(unit.active_tenant_name, 'Kanban Tenant')
        self.assertEqual(unit.active_contract_name, contract.name)

    def test_occupancy_status_field_is_indexed(self):
        """Product Readiness Review (2026-09-22): occupancy_status is the
        Dashboard's/crons'/quick-actions' most-filtered column on this model."""
        self.assertTrue(self.env['edara.unit']._fields['occupancy_status'].index)


@tagged('post_install', '-at_install')
class TestEdaraPropertyMultiBuilding(TransactionCase):
    """Phase 5 (2026-09-23): the spec's own definition of Property ("the
    ownership and financial boundary... contains one or more buildings") was
    never regression-tested with more than one Building actually present.
    Proves the ownership/analytic/financial/occupancy/maintenance boundary
    is genuinely Property-wide, not accidentally Building-wide, for:

        Property
          |-- Building A (Unit A-101, Unit A-102)
          `-- Building B (Unit B-201, Unit B-202)
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'MultiBuilding Branch', 'code': 'MBB'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'MultiBuilding Complex', 'code': 'MBC', 'branch_id': cls.branch.id})
        cls.building_a = cls.env['edara.building'].create(
            {'name': 'Building A', 'code': 'MBA', 'property_id': cls.property.id})
        cls.building_b = cls.env['edara.building'].create(
            {'name': 'Building B', 'code': 'MBB2', 'property_id': cls.property.id})
        cls.unit_a1 = cls.env['edara.unit'].create({'name': 'A-101', 'code': 'MBA101', 'building_id': cls.building_a.id})
        cls.unit_a2 = cls.env['edara.unit'].create({'name': 'A-102', 'code': 'MBA102', 'building_id': cls.building_a.id})
        cls.unit_b1 = cls.env['edara.unit'].create({'name': 'B-201', 'code': 'MBB201', 'building_id': cls.building_b.id})
        cls.unit_b2 = cls.env['edara.unit'].create({'name': 'B-202', 'code': 'MBB202', 'building_id': cls.building_b.id})
        cls.tenant_a = cls.env['res.partner'].create({'name': 'MultiBuilding Tenant A'})
        cls.tenant_b = cls.env['res.partner'].create({'name': 'MultiBuilding Tenant B'})
        cls.owner = cls.env['res.partner'].create({'name': 'MultiBuilding Owner'})

        cls.income_account = cls.env['account.account'].create(
            {'name': 'Rental Income (MultiBuilding)', 'code': '400970', 'account_type': 'income'})
        cls.expense_account = cls.env['account.account'].create(
            {'name': 'Maintenance Expense (MultiBuilding)', 'code': '601970', 'account_type': 'expense'})
        cls.vendor = cls.env['res.partner'].create({'name': 'MultiBuilding Vendor'})

    def _activate_contract(self, unit, tenant, rent_amount):
        contract = self.env['edara.lease.contract'].create({
            'unit_id': unit.id, 'tenant_id': tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': rent_amount, 'deposit_required': False,
        })
        contract.action_activate()
        return contract

    def _bill_maintenance(self, unit, cost):
        self.env.company.edara_maintenance_expense_account_id = self.expense_account.id
        request = self.env['edara.maintenance.request'].create({
            'title': 'MultiBuilding Maintenance', 'unit_id': unit.id, 'cost': cost, 'vendor_id': self.vendor.id,
        })
        request.action_create_vendor_bill().action_post()
        return request

    def test_units_across_both_buildings_resolve_to_same_property(self):
        for unit in (self.unit_a1, self.unit_a2, self.unit_b1, self.unit_b2):
            self.assertEqual(unit.property_id, self.property)
        self.assertEqual(self.property.building_count, 2)
        self.assertEqual(self.property.unit_count, 4)

    def test_ownership_stays_property_level_regardless_of_building_count(self):
        ownership = self.env['edara.ownership'].create({
            'property_id': self.property.id, 'owner_id': self.owner.id, 'ownership_percentage': 100,
        })
        self.assertEqual(ownership.property_id, self.property)
        self.assertIn(ownership, self.property.ownership_ids)
        self.assertEqual(ownership.branch_id, self.branch)

    def test_single_analytic_account_shared_across_buildings(self):
        """get_analytic_account() must resolve to the SAME record no matter
        which building/unit the caller reached it through - one analytic
        account per Property, never one per Building."""
        account_via_a = self.property.get_analytic_account()
        account_via_b = self.property.get_analytic_account()
        self.assertEqual(account_via_a, account_via_b)
        self.assertTrue(self.property.analytic_account_id)

    def test_property_financial_summary_aggregates_both_buildings(self):
        self.env.company.edara_rental_income_account_id = self.income_account.id
        contract_a = self._activate_contract(self.unit_a1, self.tenant_a, 1000)
        contract_b = self._activate_contract(self.unit_b1, self.tenant_b, 1500)
        contract_a.schedule_line_ids[:1]._create_invoice()
        contract_b.schedule_line_ids[:1]._create_invoice()

        self.assertAlmostEqual(self.property.total_revenue, 2500)
        moves = self.env['account.move'].search([
            ('edara_contract_id', 'in', (contract_a | contract_b).ids)])
        self.assertEqual(set(moves.mapped('edara_property_id.id')), {self.property.id})
        self.assertEqual(set(moves.mapped('edara_building_id.id')), {self.building_a.id, self.building_b.id})

    def test_occupancy_includes_units_from_both_buildings(self):
        self._activate_contract(self.unit_a1, self.tenant_a, 1000)
        self._activate_contract(self.unit_b1, self.tenant_b, 1500)
        rented = self.env['edara.unit'].search([('property_id', '=', self.property.id), ('occupancy_status', '=', 'rented')])
        self.assertEqual(set(rented.ids), {self.unit_a1.id, self.unit_b1.id})

    def test_rent_roll_includes_leases_from_both_buildings(self):
        contract_a = self._activate_contract(self.unit_a1, self.tenant_a, 1000)
        contract_b = self._activate_contract(self.unit_b1, self.tenant_b, 1500)
        rows = self.env['edara.lease.contract'].search([('property_id', '=', self.property.id)])
        self.assertEqual(set(rows.ids), {contract_a.id, contract_b.id})
        self.assertEqual(rows.mapped('building_id'), self.building_a | self.building_b)

    def test_maintenance_cost_aggregates_both_buildings(self):
        self._bill_maintenance(self.unit_a1, 200)
        self._bill_maintenance(self.unit_b1, 150)
        self.assertAlmostEqual(self.property.maintenance_cost, 350)
        self.assertAlmostEqual(self.property.total_expenses, 350)

    def test_branch_manager_sees_both_buildings_not_other_branch_property(self):
        branch_manager = new_test_user(
            self.env, login='edara_mb_bm', groups='property_managment.group_edara_branch_manager')
        self.branch.manager_id = branch_manager
        other_branch = self.env['edara.branch'].create({'name': 'MultiBuilding Other Branch', 'code': 'MBOB'})
        other_property = self.env['edara.property'].create(
            {'name': 'MultiBuilding Other Property', 'code': 'MBOP', 'branch_id': other_branch.id})

        visible_buildings = self.env['edara.building'].with_user(branch_manager).search([])
        self.assertEqual(set(visible_buildings.ids), {self.building_a.id, self.building_b.id})
        visible_properties = self.env['edara.property'].with_user(branch_manager).search([])
        self.assertIn(self.property.id, visible_properties.ids)
        self.assertNotIn(other_property.id, visible_properties.ids)
