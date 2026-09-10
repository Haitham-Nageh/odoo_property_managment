from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


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
        })
        cls.contract1.action_activate()
        cls.contract2 = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit2.id, 'tenant_id': cls.tenant2.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1500,
        })
        cls.contract2.action_activate()
        # unit3 stays vacant on purpose - its allocated share must be skipped.

        cls.income_account = cls.env['account.account'].create({
            'name': 'Service Charge Income (Test)', 'code': '401800', 'account_type': 'income',
        })

    def _amounts_by_unit(self, charge):
        return {line.unit_id: line.amount for line in charge.line_ids}

    def test_equal_allocation_splits_across_all_units_charges_only_occupied(self):
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'equal', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        amounts = self._amounts_by_unit(charge)
        self.assertEqual(set(amounts.keys()), {self.unit1, self.unit2})
        self.assertAlmostEqual(amounts[self.unit1], 100)
        self.assertAlmostEqual(amounts[self.unit2], 100)

    def test_proportional_allocation_by_area(self):
        charge = self.env['edara.service.charge'].create({
            'building_id': self.building.id, 'allocation_method': 'proportional', 'total_amount': 300,
        })
        charge.action_generate_allocation()
        amounts = self._amounts_by_unit(charge)
        self.assertAlmostEqual(amounts[self.unit1], 50)
        self.assertAlmostEqual(amounts[self.unit2], 100)

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
