from datetime import date

from lxml import etree

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestEdaraServiceCharge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Hebron Branch', 'code': 'HBR'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Ain Sarah Complex', 'code': 'ASC', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Building A', 'code': 'A', 'property_id': cls.property.id})
        cls.unit1 = cls.env['edara.unit'].create(
            {'name': 'A-101', 'code': '101', 'building_id': cls.building.id, 'area': 50})
        cls.unit2 = cls.env['edara.unit'].create(
            {'name': 'A-102', 'code': '102', 'building_id': cls.building.id, 'area': 100})
        cls.unit3 = cls.env['edara.unit'].create(
            {'name': 'A-103', 'code': '103', 'building_id': cls.building.id, 'area': 150})
        cls.tenant1 = cls.env['res.partner'].create({'name': 'Tenant One'})
        cls.tenant2 = cls.env['res.partner'].create({'name': 'Tenant Two'})
        cls.contract1 = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit1.id, 'tenant_id': cls.tenant1.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1000,
            'deposit_required': False,
        })
        cls.contract1.action_activate()
        cls.contract2 = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit2.id, 'tenant_id': cls.tenant2.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1500,
            'deposit_required': False,
        })
        cls.contract2.action_activate()
        # unit3 stays vacant on purpose - its allocated share must be skipped.

        cls.income_account = cls.env['account.account'].create({
            'name': 'Service Charge Income (Test)', 'code': '401800', 'account_type': 'income',
        })
        cls.property_manager = new_test_user(
            cls.env, login='edara_sc_pm_guard', groups='property_managment.group_edara_property_manager')
        cls.branch_manager = new_test_user(
            cls.env, login='edara_sc_bm_guard', groups='property_managment.group_edara_branch_manager')
        cls.branch.user_ids = [(4, cls.property_manager.id), (4, cls.branch_manager.id)]

    def _amounts_by_unit(self, charge):
        return {line.unit_id: line.amount for line in charge.line_ids}

    def test_equal_allocation_splits_across_eligible_units_only(self):
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        amounts = self._amounts_by_unit(charge)
        self.assertEqual(set(amounts.keys()), {self.unit1, self.unit2})
        self.assertAlmostEqual(amounts[self.unit1], 150)
        self.assertAlmostEqual(amounts[self.unit2], 150)
        self.assertAlmostEqual(sum(amounts.values()), charge.total_amount)

    def test_proportional_allocation_by_area(self):
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'proportional', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        amounts = self._amounts_by_unit(charge)
        # total_area of ELIGIBLE units only (unit1 area 50 + unit2 area 100 = 150);
        # unit3 (vacant, area 150) must not be counted in the denominator.
        self.assertAlmostEqual(amounts[self.unit1], 100)
        self.assertAlmostEqual(amounts[self.unit2], 200)
        self.assertAlmostEqual(sum(amounts.values()), charge.total_amount)

    def test_per_sqm_allocation(self):
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'per_sqm', 'rate_per_sqm': 2,
        })
        charge.action_generate_allocation()
        amounts = self._amounts_by_unit(charge)
        self.assertAlmostEqual(amounts[self.unit1], 100)
        self.assertAlmostEqual(amounts[self.unit2], 200)

    def test_fixed_per_unit_allocation(self):
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'fixed_per_unit', 'fixed_amount_per_unit': 75,
        })
        charge.action_generate_allocation()
        amounts = self._amounts_by_unit(charge)
        self.assertAlmostEqual(amounts[self.unit1], 75)
        self.assertAlmostEqual(amounts[self.unit2], 75)

    def test_equal_allocation_reconciles_with_multiple_ineligible_units(self):
        """Regression for MAT-FIND-009 / MAT-026: 6 units, 5 eligible, 1 vacant, total=500.
        The vacant unit must not be counted in the Equal-allocation denominator."""
        building = self.env['edara.building'].create(
            {'name': 'Building MAT-026', 'code': 'MAT026', 'property_id': self.property.id})
        units = self.env['edara.unit'].create([
            {'name': f'MAT026-10{i}', 'code': f'M10{i}', 'building_id': building.id, 'area': 50}
            for i in range(1, 7)
        ])
        vacant_unit = units[1]
        eligible_units = units - vacant_unit
        tenant = self.env['res.partner'].create({'name': 'MAT-026 Tenant'})
        for unit in eligible_units:
            contract = self.env['edara.lease.contract'].create({
                'unit_id': unit.id, 'tenant_id': tenant.id,
                'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1000,
                'deposit_required': False,
            })
            contract.action_activate()

        charge = self.env['edara.service.charge'].create({
            'building_id': building.id, 'allocation_method': 'equal', 'total_amount': 500,
        })
        charge.action_generate_allocation()
        amounts = self._amounts_by_unit(charge)

        self.assertEqual(len(amounts), 5)
        self.assertNotIn(vacant_unit, amounts)
        for unit in eligible_units:
            self.assertAlmostEqual(amounts[unit], 100)
        self.assertAlmostEqual(sum(amounts.values()), 500)

    def test_proportional_allocation_reconciles_with_multiple_ineligible_units(self):
        """Regression for MAT-FIND-009 / MAT-026, proportional method: the vacant unit's
        area must not be counted in the denominator used to compute eligible units' shares."""
        building = self.env['edara.building'].create(
            {'name': 'Building MAT-026 Proportional', 'code': 'MAT026P', 'property_id': self.property.id})
        u1, u2, u3, u4, u5, u6 = self.env['edara.unit'].create([
            {'name': 'MAT026P-101', 'code': 'MP101', 'building_id': building.id, 'area': 50},
            {'name': 'MAT026P-102', 'code': 'MP102', 'building_id': building.id, 'area': 200},  # stays vacant
            {'name': 'MAT026P-103', 'code': 'MP103', 'building_id': building.id, 'area': 100},
            {'name': 'MAT026P-104', 'code': 'MP104', 'building_id': building.id, 'area': 100},
            {'name': 'MAT026P-105', 'code': 'MP105', 'building_id': building.id, 'area': 50},
            {'name': 'MAT026P-106', 'code': 'MP106', 'building_id': building.id, 'area': 100},
        ])
        vacant_unit = u2
        eligible_units = u1 + u3 + u4 + u5 + u6  # eligible total area = 400
        tenant = self.env['res.partner'].create({'name': 'MAT-026 Proportional Tenant'})
        for unit in eligible_units:
            contract = self.env['edara.lease.contract'].create({
                'unit_id': unit.id, 'tenant_id': tenant.id,
                'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1000,
                'deposit_required': False,
            })
            contract.action_activate()

        charge = self.env['edara.service.charge'].create({
            'building_id': building.id, 'allocation_method': 'proportional', 'total_amount': 500,
        })
        charge.action_generate_allocation()
        amounts = self._amounts_by_unit(charge)

        self.assertEqual(len(amounts), 5)
        self.assertNotIn(vacant_unit, amounts)
        self.assertAlmostEqual(amounts[u1], 62.5)
        self.assertAlmostEqual(amounts[u3], 125)
        self.assertAlmostEqual(amounts[u4], 125)
        self.assertAlmostEqual(amounts[u5], 62.5)
        self.assertAlmostEqual(amounts[u6], 125)
        self.assertAlmostEqual(sum(amounts.values()), 500)

    def test_missing_amount_blocks_allocation(self):
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal',
        })
        with self.assertRaises(UserError):
            charge.action_generate_allocation()

    def test_building_with_no_units_blocks_allocation(self):
        empty_building = self.env['edara.building'].create(
            {'name': 'Building B', 'code': 'B', 'property_id': self.property.id})
        charge = self.env['edara.service.charge'].create({
            'building_id': empty_building.id, 'allocation_method': 'equal', 'total_amount': 100,
        })
        with self.assertRaises(UserError):
            charge.action_generate_allocation()

    def test_invoicing_blocked_without_income_account(self):
        # Phase 6.4: this shared dev database's real company may already have
        # edara_service_charge_income_account_id configured (real accounting
        # setup, not test data) - explicitly clear it for this negative test.
        self.env.company.edara_service_charge_income_account_id = False
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        with self.assertRaises(UserError):
            charge.line_ids[0]._create_invoice()

    def test_invoicing_creates_posted_invoices_and_updates_state(self):
        self.env.company.edara_service_charge_income_account_id = self.income_account.id
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        self.assertEqual(charge.state, 'allocated')

        charge.action_invoice_lines()
        self.assertEqual(charge.state, 'invoiced')
        for line in charge.line_ids:
            self.assertEqual(line.invoice_id.state, 'posted')
            self.assertEqual(line.invoice_id.edara_invoice_type, 'service_charge')
            invoice_line = line.invoice_id.invoice_line_ids[0]
            self.assertEqual(invoice_line.account_id, self.income_account)
            analytic_account = self.property.get_analytic_account()
            self.assertIn(str(analytic_account.id), invoice_line.analytic_distribution)

    def test_invoiced_line_cannot_be_deleted(self):
        self.env.company.edara_service_charge_income_account_id = self.income_account.id
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        charge.action_invoice_lines()
        with self.assertRaises(UserError):
            charge.line_ids[0].unlink()

    # ============ Phase 12.9: Service Charge Area Validation ============

    def _create_test_building_with_units(self, name_prefix, unit_specs):
        """Helper to create an isolated building with units and active leases.
        unit_specs: list of tuples (name_suffix, code_suffix, area, is_leased)"""
        building = self.env['edara.building'].create({
            'name': f'Building {name_prefix}',
            'code': name_prefix[:8].upper(),
            'property_id': self.property.id,
        })
        units = []
        for name_suffix, code_suffix, area, is_leased in unit_specs:
            unit = self.env['edara.unit'].create({
                'name': f'{name_prefix}-{name_suffix}',
                'code': f'{name_prefix[:4]}-{code_suffix}',
                'building_id': building.id,
                'area': area,
            })
            if is_leased:
                tenant = self.env['res.partner'].create({'name': f'Tenant {unit.name}'})
                contract = self.env['edara.lease.contract'].create({
                    'unit_id': unit.id,
                    'tenant_id': tenant.id,
                    'start_date': date(2026, 1, 1),
                    'end_date': date(2026, 12, 31),
                    'rent_amount': 1000,
                    'deposit_required': False,
                })
                contract.action_activate()
            units.append(unit)
        return building, units

    def test_proportional_allocation_all_zero_area_blocked(self):
        """Test 1: When all eligible units have area=0, proportional allocation is blocked
        by the existing all-zero guard, and no allocation lines are created."""
        building, (u1, u2) = self._create_test_building_with_units(
            'P129-P1', [('U1', 'P11', 0.0, True), ('U2', 'P12', 0.0, True)])
        charge = self.env['edara.service.charge'].create({
            'building_id': building.id,
            'allocation_method': 'proportional',
            'total_amount': 200,
        })
        with self.assertRaises(UserError):
            charge.action_generate_allocation()
        self.assertFalse(charge.line_ids)

    def test_proportional_allocation_mixed_zero_area_blocked_and_identifies_unit(self):
        """Test 2: When some eligible units have area=0 (mixed), proportional allocation is
        blocked, the zero-area unit is identified in the UserError, and no lines are created."""
        building, (u1, u2) = self._create_test_building_with_units(
            'P129-P2', [('U1', 'P21', 0.0, True), ('U2', 'P22', 100.0, True)])
        charge = self.env['edara.service.charge'].create({
            'building_id': building.id,
            'allocation_method': 'proportional',
            'total_amount': 200,
        })
        with self.assertRaises(UserError) as cm:
            charge.action_generate_allocation()
        self.assertIn(u1.name, str(cm.exception))
        self.assertFalse(charge.line_ids)

    def test_per_sqm_allocation_all_zero_area_blocked(self):
        """Test 3: When all eligible units have area=0, per_sqm allocation is blocked,
        and no allocation lines are created."""
        building, (u1, u2) = self._create_test_building_with_units(
            'P129-P3', [('U1', 'P31', 0.0, True), ('U2', 'P32', 0.0, True)])
        charge = self.env['edara.service.charge'].create({
            'building_id': building.id,
            'allocation_method': 'per_sqm',
            'rate_per_sqm': 5.0,
        })
        with self.assertRaises(UserError):
            charge.action_generate_allocation()
        self.assertFalse(charge.line_ids)

    def test_per_sqm_allocation_mixed_zero_area_blocked_and_identifies_unit(self):
        """Test 4: When some eligible units have area=0 (mixed), per_sqm allocation is
        blocked, the zero-area unit is identified in the UserError, and no lines are created."""
        building, (u1, u2) = self._create_test_building_with_units(
            'P129-P4', [('U1', 'P41', 0.0, True), ('U2', 'P42', 100.0, True)])
        charge = self.env['edara.service.charge'].create({
            'building_id': building.id,
            'allocation_method': 'per_sqm',
            'rate_per_sqm': 5.0,
        })
        with self.assertRaises(UserError) as cm:
            charge.action_generate_allocation()
        self.assertIn(u1.name, str(cm.exception))
        self.assertFalse(charge.line_ids)

    def test_area_validation_ignores_vacant_ineligible_units_with_zero_area(self):
        """Test 5: Area validation applies ONLY to eligible units. A vacant/ineligible unit
        with area=0 does not block proportional or per_sqm allocation for eligible units."""
        building, (u1, u2) = self._create_test_building_with_units(
            'P129-P5', [('U1', 'P51', 100.0, True), ('U2', 'P52', 0.0, False)])
        # Proportional succeeds:
        charge_prop = self.env['edara.service.charge'].create({
            'building_id': building.id,
            'allocation_method': 'proportional',
            'total_amount': 200,
        })
        charge_prop.action_generate_allocation()
        self.assertEqual(len(charge_prop.line_ids), 1)
        self.assertEqual(charge_prop.line_ids[0].unit_id, u1)
        self.assertAlmostEqual(charge_prop.line_ids[0].amount, 200.0)

        # Per-sqm succeeds:
        charge_sqm = self.env['edara.service.charge'].create({
            'building_id': building.id,
            'allocation_method': 'per_sqm',
            'rate_per_sqm': 3.0,
        })
        charge_sqm.action_generate_allocation()
        self.assertEqual(len(charge_sqm.line_ids), 1)
        self.assertEqual(charge_sqm.line_ids[0].unit_id, u1)
        self.assertAlmostEqual(charge_sqm.line_ids[0].amount, 300.0)

    def test_equal_and_fixed_allocation_allow_zero_area_units(self):
        """Test 6: EQUAL and FIXED_PER_UNIT do not depend on area, so eligible units
        with area=0 allocate normally."""
        building, (u1, u2) = self._create_test_building_with_units(
            'P129-P6', [('U1', 'P61', 0.0, True), ('U2', 'P62', 0.0, True)])
        # Equal
        charge_eq = self.env['edara.service.charge'].create({
            'building_id': building.id,
            'allocation_method': 'equal',
            'total_amount': 200,
        })
        charge_eq.action_generate_allocation()
        self.assertEqual(len(charge_eq.line_ids), 2)
        for line in charge_eq.line_ids:
            self.assertAlmostEqual(line.amount, 100.0)

        # Fixed per unit
        charge_fx = self.env['edara.service.charge'].create({
            'building_id': building.id,
            'allocation_method': 'fixed_per_unit',
            'fixed_amount_per_unit': 80,
        })
        charge_fx.action_generate_allocation()
        self.assertEqual(len(charge_fx.line_ids), 2)
        for line in charge_fx.line_ids:
            self.assertAlmostEqual(line.amount, 80.0)

    def test_search_view_exists_and_has_state_filters(self):
        """Ticket 5: Native search view for edara.service.charge exists, model is edara.service.charge,
        has Draft, Allocated, Invoiced filters with exact domains, and Group By State."""
        search_view = self.env.ref('property_managment.view_edara_service_charge_search')
        self.assertTrue(search_view, "Search view view_edara_service_charge_search must exist")
        self.assertEqual(search_view.model, 'edara.service.charge')

        arch = self.env['edara.service.charge'].get_view(view_id=search_view.id)['arch']
        tree = etree.fromstring(arch)

        for name, expected_domain in (
                ('draft', "[('state', '=', 'draft')]"),
                ('allocated', "[('state', '=', 'allocated')]"),
                ('invoiced', "[('state', '=', 'invoiced')]")):
            filters = tree.xpath("//filter[@name='%s']" % name)
            self.assertTrue(filters, "missing filter: %s" % name)
            self.assertEqual(filters[0].get('domain'), expected_domain, name)

        group_by_filters = tree.xpath("//filter[@name='group_by_state']")
        self.assertTrue(group_by_filters, "missing group by state filter")
        self.assertEqual(group_by_filters[0].get('context'), "{'group_by': 'state'}")

    def test_action_edara_service_charge_references_search_view_and_no_new_action(self):
        """Ticket 5: existing action_edara_service_charge references the search view,
        and no new window action was created."""
        actions = self.env['ir.actions.act_window'].search([('res_model', '=', 'edara.service.charge')])
        self.assertEqual(len(actions), 1, "Expected exactly 1 window action for edara.service.charge")
        action = self.env.ref('property_managment.action_edara_service_charge')
        self.assertEqual(actions.id, action.id)
        self.assertEqual(
            action.search_view_id.id,
            self.env.ref('property_managment.view_edara_service_charge_search').id,
        )

    # ============ Q2.2 System Field Guard: edara.service.charge.line.invoice_id ============

    def _create_allocated_charge_with_invoices(self):
        self.env.company.edara_service_charge_income_account_id = self.income_account.id
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        charge.action_invoice_lines()
        return charge

    def test_guard_property_manager_cannot_reassign_invoice(self):
        """Negative security: Property Manager cannot reassign invoice_id to another invoice."""
        charge = self._create_allocated_charge_with_invoices()
        line = charge.line_ids[0]
        orig_invoice_id = line.invoice_id.id
        self.assertTrue(orig_invoice_id)
        other_invoice = charge.line_ids[1].invoice_id
        with self.assertRaises(AccessError):
            line.with_user(self.property_manager).write({'invoice_id': other_invoice.id})
        self.assertEqual(line.invoice_id.id, orig_invoice_id)

    def test_guard_branch_manager_cannot_reassign_invoice(self):
        """Negative security: Branch Manager cannot reassign invoice_id to another invoice."""
        charge = self._create_allocated_charge_with_invoices()
        line = charge.line_ids[0]
        orig_invoice_id = line.invoice_id.id
        self.assertTrue(orig_invoice_id)
        other_invoice = charge.line_ids[1].invoice_id
        with self.assertRaises(AccessError):
            line.with_user(self.branch_manager).write({'invoice_id': other_invoice.id})
        self.assertEqual(line.invoice_id.id, orig_invoice_id)

    def test_guard_property_manager_cannot_clear_invoice(self):
        """Negative security: Property Manager cannot clear invoice_id with False."""
        charge = self._create_allocated_charge_with_invoices()
        line = charge.line_ids[0]
        orig_invoice_id = line.invoice_id.id
        self.assertTrue(orig_invoice_id)
        with self.assertRaises(AccessError):
            line.with_user(self.property_manager).write({'invoice_id': False})
        self.assertEqual(line.invoice_id.id, orig_invoice_id)

    def test_guard_branch_manager_cannot_clear_invoice(self):
        """Negative security: Branch Manager cannot clear invoice_id with False."""
        charge = self._create_allocated_charge_with_invoices()
        line = charge.line_ids[0]
        orig_invoice_id = line.invoice_id.id
        self.assertTrue(orig_invoice_id)
        with self.assertRaises(AccessError):
            line.with_user(self.branch_manager).write({'invoice_id': False})
        self.assertEqual(line.invoice_id.id, orig_invoice_id)

    def test_guard_reassignment_to_unrelated_invoice_blocked_by_guard(self):
        """Negative security: Reassignment to an unlinked, unrelated valid invoice is blocked
        by the system field guard AccessError, proving guard operates before database uniqueness."""
        charge = self._create_allocated_charge_with_invoices()
        line = charge.line_ids[0]
        orig_invoice_id = line.invoice_id.id
        unrelated_invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': self.tenant1.id,
            'invoice_date': date(2026, 1, 1),
            'company_id': self.env.company.id,
        })
        with self.assertRaises(AccessError):
            line.with_user(self.property_manager).write({'invoice_id': unrelated_invoice.id})
        with self.assertRaises(AccessError):
            line.with_user(self.branch_manager).write({'invoice_id': unrelated_invoice.id})
        self.assertEqual(line.invoice_id.id, orig_invoice_id)

    def test_guard_multirecord_write_containing_protected_field_rejected_atomically(self):
        """Negative security: Multi-record write containing protected invoice_id is rejected atomically
        and neither line record is modified."""
        charge = self._create_allocated_charge_with_invoices()
        lines = charge.line_ids
        initial_invoices = {l.id: l.invoice_id.id for l in lines}
        some_invoice = lines[0].invoice_id
        with self.assertRaises(AccessError):
            lines.with_user(self.property_manager).write({'invoice_id': some_invoice.id})
        with self.assertRaises(AccessError):
            lines.with_user(self.branch_manager).write({'invoice_id': some_invoice.id})
        with self.assertRaises(AccessError):
            lines.with_user(self.property_manager).write({'invoice_id': False})
        with self.assertRaises(AccessError):
            lines.with_user(self.branch_manager).write({'invoice_id': False})
        for l in lines:
            self.assertEqual(l.invoice_id.id, initial_invoices[l.id])

    def test_guard_property_manager_can_execute_invoicing_workflow(self):
        """Positive workflow: Property Manager executing legitimate _create_invoice succeeds
        and assigns invoice_id correctly."""
        self.env.company.edara_service_charge_income_account_id = self.income_account.id
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        line = charge.line_ids[0]
        self.assertFalse(line.invoice_id)
        invoice = line.with_user(self.property_manager)._create_invoice()
        self.assertTrue(invoice)
        self.assertEqual(line.invoice_id.id, invoice.id)
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.edara_invoice_type, 'service_charge')

    def test_guard_branch_manager_can_execute_invoicing_workflow(self):
        """Positive workflow: Branch Manager executing legitimate _create_invoice succeeds
        and assigns invoice_id correctly."""
        self.env.company.edara_service_charge_income_account_id = self.income_account.id
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        line = charge.line_ids[0]
        self.assertFalse(line.invoice_id)
        invoice = line.with_user(self.branch_manager)._create_invoice()
        self.assertTrue(invoice)
        self.assertEqual(line.invoice_id.id, invoice.id)
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.edara_invoice_type, 'service_charge')

    def test_guard_unprotected_field_amount_remains_writable_on_uninvoiced_line(self):
        """Positive security: Unprotected fields like amount remain writable by Property Manager
        when the line is not invoiced."""
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        line = charge.line_ids[0]
        line.with_user(self.property_manager).write({'amount': 175.0})
        self.assertEqual(line.amount, 175.0)

    def test_equal_allocation_reconciles_with_rounding_remainder(self):
        """P3-01: Equal allocation reconciles rounding remainder back to total_amount."""
        building = self.env['edara.building'].create({
            'name': 'Building Equal Rounding', 'code': 'BER', 'property_id': self.property.id,
        })
        units = self.env['edara.unit'].create([
            {'name': f'U-{i}', 'code': f'U{i}', 'building_id': building.id, 'area': 100}
            for i in range(1, 4)
        ])
        for unit in units:
            contract = self.env['edara.lease.contract'].create({
                'unit_id': unit.id, 'tenant_id': self.tenant1.id,
                'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
                'rent_amount': 1000, 'deposit_required': False,
            })
            contract.action_activate()

        charge = self.env['edara.service.charge'].create({
            'building_id': building.id, 'allocation_method': 'equal', 'total_amount': 100.0,
        })
        charge.action_generate_allocation()
        amounts = [line.amount for line in charge.line_ids]
        self.assertEqual(amounts, [33.33, 33.33, 33.34])
        self.assertEqual(sum(amounts), 100.0)

    def test_proportional_allocation_reconciles_with_rounding_remainder(self):
        """P3-01: Proportional allocation reconciles rounding remainder back to total_amount."""
        building = self.env['edara.building'].create({
            'name': 'Building Prop Rounding', 'code': 'BPR', 'property_id': self.property.id,
        })
        units = self.env['edara.unit'].create([
            {'name': f'U-{i}', 'code': f'U{i}', 'building_id': building.id, 'area': 1.0}
            for i in range(1, 4)
        ])
        for unit in units:
            contract = self.env['edara.lease.contract'].create({
                'unit_id': unit.id, 'tenant_id': self.tenant1.id,
                'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
                'rent_amount': 1000, 'deposit_required': False,
            })
            contract.action_activate()

        charge = self.env['edara.service.charge'].create({
            'building_id': building.id, 'allocation_method': 'proportional', 'total_amount': 100.0,
        })
        charge.action_generate_allocation()
        amounts = [line.amount for line in charge.line_ids]
        self.assertEqual(amounts, [33.33, 33.33, 33.34])
        self.assertEqual(sum(amounts), 100.0)

    def test_negative_amount_blocked_on_create(self):
        """P3-02: Negative or zero service charge line amount is rejected on create."""
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        with self.assertRaises(ValidationError):
            self.env['edara.service.charge.line'].with_user(self.property_manager).create({
                'charge_id': charge.id,
                'unit_id': self.unit1.id,
                'tenant_id': self.tenant1.id,
                'amount': -10.0,
            })
        with self.assertRaises(ValidationError):
            self.env['edara.service.charge.line'].with_user(self.property_manager).create({
                'charge_id': charge.id,
                'unit_id': self.unit1.id,
                'tenant_id': self.tenant1.id,
                'amount': 0.0,
            })

    def test_negative_amount_blocked_on_write(self):
        """P3-02: Negative or zero service charge line amount is rejected on write."""
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        line = charge.line_ids[0]
        with self.assertRaises(ValidationError):
            line.with_user(self.property_manager).write({'amount': -5.0})
        with self.assertRaises(ValidationError):
            line.with_user(self.property_manager).write({'amount': 0.0})

