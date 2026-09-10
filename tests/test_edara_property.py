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
        cls.branch_a = cls.env['edara.branch'].create({'name': 'Ramallah Branch', 'code': 'RAM'})
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
