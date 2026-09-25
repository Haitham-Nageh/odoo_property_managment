import base64
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
            'deposit_required': False,
        })
        cls.contract_a.action_activate()
        cls.contract_b = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit_b.id, 'tenant_id': cls.partner_b.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1200,
            'deposit_required': False,
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
        self.assertEqual(renewal.note, 'Please renew')

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

    # ================= Phase 3: Tenant Portal Expansion =================

    # ---- Tenant Dashboard ----

    def test_tenant_dashboard_shows_own_lease(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.contract_a.name, response.text)
        self.assertNotIn(self.contract_b.name, response.text)

    def test_dashboard_blocked_for_non_tenant_portal_user(self):
        """Fail-closed tenant resolution (spec §6): a portal user with no
        EDARA tenant relationship at all must see no tenant data, never a
        silent fallback."""
        portal_group = self.env.ref('property_managment.group_edara_portal_tenant')
        non_tenant_partner = self.env['res.partner'].create({'name': 'No Lease Portal User'})
        self.env['res.users'].create({
            'name': 'No Lease', 'login': 'edara_no_lease', 'password': 'edara_no_lease',
            'partner_id': non_tenant_partner.id, 'group_ids': [(6, 0, [portal_group.id])],
        })
        self.authenticate('edara_no_lease', 'edara_no_lease')
        response = self.url_open('/my/dashboard')
        self.assertNotIn(self.contract_a.name, response.text)
        self.assertNotIn(self.contract_b.name, response.text)

    # ---- My Unit ----

    def test_tenant_can_view_own_unit(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/units/%d' % self.unit_a.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.unit_a.name, response.text)

    def test_tenant_cannot_view_other_tenants_unit_via_id_tampering(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/units/%d' % self.unit_b.id)
        self.assertNotIn(self.unit_b.name, response.text)

    def test_my_units_list_excludes_other_tenants_unit(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/units')
        self.assertIn(self.unit_a.name, response.text)
        self.assertNotIn(self.unit_b.name, response.text)

    # ---- Billing (Invoices / Outstanding / Payment History) ----

    def _post_rent_invoice(self, tenant, amount=1000.0):
        income_account = self.env['account.account'].create(
            {'name': 'Rental Income Test', 'code': '400999%d' % tenant.id, 'account_type': 'income'})
        move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': tenant.id,
            'invoice_date': date(2026, 1, 1),
            'invoice_line_ids': [(0, 0, {
                'name': 'Rent', 'quantity': 1, 'price_unit': amount, 'account_id': income_account.id,
            })],
        })
        move.action_post()
        return move

    def test_tenant_billing_shows_only_own_invoices(self):
        invoice_a = self._post_rent_invoice(self.partner_a, 1000.0)
        invoice_b = self._post_rent_invoice(self.partner_b, 1200.0)
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/billing')
        self.assertEqual(response.status_code, 200)
        self.assertIn(invoice_a.name, response.text)
        self.assertNotIn(invoice_b.name, response.text)

    def test_tenant_billing_outstanding_matches_invoice_residual(self):
        invoice_a = self._post_rent_invoice(self.partner_a, 1000.0)
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/billing')
        self.assertIn('1000.00', response.text)
        self.assertAlmostEqual(invoice_a.amount_residual, 1000.0)

    # ---- Documents ----

    def _attach_file(self, record, name='Lease Agreement.pdf'):
        return self.env['ir.attachment'].create({
            'name': name, 'res_model': record._name, 'res_id': record.id,
            'type': 'binary', 'datas': base64.b64encode(b'dummy file content'),
        })

    def test_tenant_documents_lists_own_attachment(self):
        attachment = self._attach_file(self.contract_a)
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/documents')
        self.assertEqual(response.status_code, 200)
        self.assertIn(attachment.name, response.text)

    def test_tenant_documents_excludes_other_tenants_attachment(self):
        self._attach_file(self.contract_a, name='Tenant A Doc.pdf')
        self._attach_file(self.contract_b, name='Tenant B Doc.pdf')
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/documents')
        self.assertIn('Tenant A Doc.pdf', response.text)
        self.assertNotIn('Tenant B Doc.pdf', response.text)

    def test_tenant_cannot_download_other_tenants_attachment_via_id_tampering(self):
        attachment_b = self._attach_file(self.contract_b, name='Tenant B Private.pdf')
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/web/content/%d?download=true' % attachment_b.id)
        self.assertNotEqual(response.status_code, 200)

    # ---- Notifications ----

    def test_tenant_sees_own_maintenance_completion_notification(self):
        request_a = self.env['edara.maintenance.request'].create({
            'title': 'Broken AC', 'unit_id': self.unit_a.id, 'tenant_id': self.partner_a.id,
            'assigned_user_id': self.env.ref('base.user_admin').id,
        })
        request_a.action_assign()
        request_a.action_start()
        request_a.action_complete()
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/notifications')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Broken AC', response.text)

    def test_tenant_does_not_see_other_tenants_notification(self):
        request_b = self.env['edara.maintenance.request'].create({
            'title': 'Broken Heater B', 'unit_id': self.unit_b.id, 'tenant_id': self.partner_b.id,
            'assigned_user_id': self.env.ref('base.user_admin').id,
        })
        request_b.action_assign()
        request_b.action_start()
        request_b.action_complete()
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/notifications')
        self.assertNotIn('Broken Heater B', response.text)

    def test_tenant_notifications_exclude_internal_only_messages(self):
        """An internal note (no partner_ids) must never reach the tenant,
        even though it's on the tenant's own record - only messages
        explicitly addressed to the tenant via partner_ids qualify."""
        self.contract_a.message_post(body='Internal staff note, not for the tenant')
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/notifications')
        self.assertNotIn('Internal staff note', response.text)

    def test_renewal_approval_notifies_tenant(self):
        renewal = self.env['edara.renewal.request'].create({
            'contract_id': self.contract_a.id,
            'requested_start_date': self.contract_a._term_boundary(),
            'requested_end_date': date(2027, 12, 31),
            'requested_rent_amount': 1100,
        })
        renewal.action_approve()
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/notifications')
        self.assertIn('approved', response.text)

    def test_renewal_rejection_notifies_tenant(self):
        renewal = self.env['edara.renewal.request'].create({
            'contract_id': self.contract_a.id,
            'requested_start_date': self.contract_a._term_boundary(),
            'requested_end_date': date(2027, 12, 31),
            'requested_rent_amount': 1100,
        })
        renewal.action_reject(reason='Rent proposal too low')
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/notifications')
        self.assertIn('not approved', response.text)

    # ---- Company isolation ----

    def test_tenant_cannot_view_unit_from_another_company(self):
        company_b = self.env['res.company'].create({'name': 'EDARA Company B Portal Test'})
        branch_b = self.env['edara.branch'].create(
            {'name': 'Company B Branch', 'code': 'CBB', 'company_id': company_b.id})
        property_b = self.env['edara.property'].create(
            {'name': 'Company B Property', 'code': 'CBP', 'branch_id': branch_b.id})
        building_b = self.env['edara.building'].create(
            {'name': 'Company B Building', 'code': 'CBBL', 'property_id': property_b.id})
        unit_company_b = self.env['edara.unit'].create(
            {'name': 'CB-101', 'code': 'CB101', 'building_id': building_b.id})
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/units/%d' % unit_company_b.id)
        self.assertNotIn(unit_company_b.name, response.text)
