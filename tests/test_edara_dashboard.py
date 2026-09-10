from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Dashboard Branch', 'code': 'DASH'})
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
        })
        cls.contract.action_activate()

    def test_kpis_reflect_current_state(self):
        dashboard = self.env['edara.dashboard'].create({})
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
