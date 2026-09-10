import re
from datetime import date

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Tulkarm Branch', 'code': 'TLK'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Tulkarm Complex', 'code': 'TLC', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Building A', 'code': 'A', 'property_id': cls.property.id})
        cls.unit_a = cls.env['edara.unit'].create({'name': 'A-1', 'code': '1', 'building_id': cls.building.id})
        cls.unit_b = cls.env['edara.unit'].create({'name': 'A-2', 'code': '2', 'building_id': cls.building.id})

        portal_group = cls.env.ref('property_managment.group_edara_portal_tenant')

        cls.partner_a = cls.env['res.partner'].create({'name': 'Tenant A'})
        cls.user_a = cls.env['res.users'].create({
            'name': 'Tenant A', 'login': 'edara_tenant_a', 'password': 'edara_tenant_a',
            'partner_id': cls.partner_a.id, 'group_ids': [(6, 0, [portal_group.id])],
        })
        cls.partner_b = cls.env['res.partner'].create({'name': 'Tenant B'})
        cls.user_b = cls.env['res.users'].create({
            'name': 'Tenant B', 'login': 'edara_tenant_b', 'password': 'edara_tenant_b',
            'partner_id': cls.partner_b.id, 'group_ids': [(6, 0, [portal_group.id])],
        })

        cls.contract_a = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit_a.id, 'tenant_id': cls.partner_a.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1000,
        })
        cls.contract_a.action_activate()
        cls.contract_b = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit_b.id, 'tenant_id': cls.partner_b.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1200,
        })
        cls.contract_b.action_activate()

    def _get_csrf_token(self, html):
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertTrue(match, "csrf token not found in page")
        return match.group(1)

    def test_tenant_can_view_own_lease(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/leases/%d' % self.contract_a.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.contract_a.name, response.text)

    def test_tenant_cannot_view_other_tenants_lease(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/leases/%d' % self.contract_b.id)
        self.assertNotIn(self.contract_b.name, response.text)

    def test_record_rule_hides_other_tenants_unit(self):
        Unit = self.env['edara.unit'].with_user(self.user_a)
        visible_units = Unit.search([])
        self.assertIn(self.unit_a, visible_units)
        self.assertNotIn(self.unit_b, visible_units)

    def test_tenant_can_file_maintenance_request_for_own_unit(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        form_page = self.url_open('/my/maintenance/new')
        csrf_token = self._get_csrf_token(form_page.text)
        self.url_open('/my/maintenance/new', data={
            'unit_id': str(self.unit_a.id), 'title': 'Leaking sink', 'priority': 'normal',
            'csrf_token': csrf_token,
        })
        created = self.env['edara.maintenance.request'].search([('title', '=', 'Leaking sink')])
        self.assertTrue(created)
        self.assertEqual(created.tenant_id, self.partner_a)
        self.assertEqual(created.unit_id, self.unit_a)

    def test_tenant_cannot_file_maintenance_request_for_foreign_unit(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        form_page = self.url_open('/my/maintenance/new')
        csrf_token = self._get_csrf_token(form_page.text)
        self.url_open('/my/maintenance/new', data={
            'unit_id': str(self.unit_b.id), 'title': 'Sneaky request', 'priority': 'normal',
            'csrf_token': csrf_token,
        })
        self.assertFalse(self.env['edara.maintenance.request'].search([('title', '=', 'Sneaky request')]))

    def test_tenant_can_request_renewal_for_own_lease(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        detail_page = self.url_open('/my/leases/%d' % self.contract_a.id)
        csrf_token = self._get_csrf_token(detail_page.text)
        self.url_open('/my/leases/%d/renew' % self.contract_a.id, data={
            'requested_start_date': '2027-01-01', 'requested_end_date': '2027-12-31',
            'requested_rent_amount': '1100', 'note': 'Please renew', 'csrf_token': csrf_token,
        })
        renewal = self.env['edara.renewal.request'].search([('contract_id', '=', self.contract_a.id)])
        self.assertTrue(renewal)
        self.assertEqual(renewal.state, 'submitted')

    def test_tenant_cannot_request_renewal_for_foreign_lease(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        # A valid CSRF token from a page tenant A can legitimately reach - the
        # ownership check under test is the server-side ORM/rule check, not CSRF.
        own_page = self.url_open('/my/leases/%d' % self.contract_a.id)
        csrf_token = self._get_csrf_token(own_page.text)
        self.url_open('/my/leases/%d/renew' % self.contract_b.id, data={
            'requested_start_date': '2027-01-01', 'requested_end_date': '2027-12-31',
            'requested_rent_amount': '1100', 'csrf_token': csrf_token,
        })
        self.assertFalse(self.env['edara.renewal.request'].search([('contract_id', '=', self.contract_b.id)]))
