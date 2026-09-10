from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraMaintenanceRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Jenin Branch', 'code': 'JNN'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Al-Quds Complex', 'code': 'AQC', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Building A', 'code': 'A', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'A-101', 'code': '101', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Rana Saleh'})
        cls.staff = cls.env['res.users'].create({
            'name': 'Maintenance Staff', 'login': 'edara_maint_staff',
            'email': 'maint@example.com',
        })

    def _make_request(self, **overrides):
        vals = {'title': 'Leaking faucet', 'unit_id': self.unit.id, 'tenant_id': self.tenant.id}
        vals.update(overrides)
        return self.env['edara.maintenance.request'].create(vals)

    def test_sequence_name_assigned_on_create(self):
        request = self._make_request()
        self.assertTrue(request.name.startswith('MR/'))
        self.assertEqual(request.state, 'new')

    def test_full_lifecycle(self):
        request = self._make_request()
        request.action_assign(self.staff.id)
        self.assertEqual(request.state, 'assigned')
        self.assertEqual(request.assigned_user_id, self.staff)

        request.action_start()
        self.assertEqual(request.state, 'in_progress')

        request.action_complete()
        self.assertEqual(request.state, 'done')
        self.assertTrue(request.completed_date)

    def test_cannot_complete_a_new_request(self):
        request = self._make_request()
        with self.assertRaises(UserError):
            request.action_complete()

    def test_cancel_allowed_before_done(self):
        request = self._make_request()
        request.action_cancel()
        self.assertEqual(request.state, 'cancelled')

    def test_cannot_cancel_a_done_request(self):
        request = self._make_request()
        request.action_assign(self.staff.id)
        request.action_complete()
        with self.assertRaises(UserError):
            request.action_cancel()

    def test_negative_cost_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_request(cost=-50)

    def test_unit_smart_button_count(self):
        self._make_request()
        self._make_request(title='Broken window')
        self.assertEqual(self.unit.maintenance_request_count, 2)
