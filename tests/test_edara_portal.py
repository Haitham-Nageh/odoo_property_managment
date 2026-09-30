import base64
import re
from datetime import date

from odoo.exceptions import ValidationError
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

    # ================= Phase 10.1.1 (Y1): renewal start date = day after the last occupied day =================

    def test_renewal_form_default_start_is_the_day_after_the_last_day(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        page = self.url_open('/my/leases/%d' % self.contract_a.id).text
        field = re.search(r'<input[^>]*name="requested_start_date"[^>]*>', page)
        self.assertTrue(field, "renewal start date input not found")
        self.assertIn('value="2027-01-01"', field.group(0))      # contract ends 2026-12-31 (last occupied day)
        self.assertIn('min="2027-01-01"', field.group(0))

    def test_renewal_request_at_the_boundary_is_accepted(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        csrf_token = self._get_csrf_token(self.url_open('/my/leases/%d' % self.contract_a.id).text)
        response = self.url_open('/my/leases/%d/renew' % self.contract_a.id, data={
            'requested_start_date': '2027-01-01', 'requested_end_date': '2027-12-31',
            'requested_rent_amount': '1100', 'csrf_token': csrf_token})
        self.assertEqual(response.status_code, 200)
        renewal = self.env['edara.renewal.request'].search([('contract_id', '=', self.contract_a.id)])
        self.assertEqual((renewal.state, renewal.requested_start_date), ('submitted', date(2027, 1, 1)))

    def test_renewal_request_one_day_before_the_boundary_is_rejected_at_submission(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        csrf_token = self._get_csrf_token(self.url_open('/my/leases/%d' % self.contract_a.id).text)
        response = self.url_open('/my/leases/%d/renew' % self.contract_a.id, data={
            'requested_start_date': '2026-12-31', 'requested_end_date': '2027-12-31',
            'requested_rent_amount': '1100', 'csrf_token': csrf_token})
        self.assertEqual(response.status_code, 400)
        self.assertIn('2027-01-01', response.text)                 # the earliest valid date is explained
        self.assertIn('alert-danger', response.text)
        self.assertFalse(self.env['edara.renewal.request'].search([('contract_id', '=', self.contract_a.id)]))

    def _create_active_contract(self, tenant=None, start_date=None, end_date=None):
        tenant = tenant or self.partner_a
        start_date = start_date or date(2026, 1, 1)
        end_date = end_date or date(2026, 12, 31)
        unit = self.env['edara.unit'].create({
            'name': 'Test Renewal Unit',
            'code': 'TRU%d' % self.env['edara.unit'].search_count([]),
            'building_id': self.building.id,
        })
        contract = self.env['edara.lease.contract'].create({
            'unit_id': unit.id, 'tenant_id': tenant.id,
            'start_date': start_date, 'end_date': end_date, 'rent_amount': 1000,
            'deposit_required': False,
        })
        contract.action_activate()
        return contract

    def test_renewal_request_with_malformed_end_date_is_rejected(self):
        contract = self._create_active_contract()
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        csrf_token = self._get_csrf_token(self.url_open('/my/leases/%d' % contract.id).text)
        response = self.url_open('/my/leases/%d/renew' % contract.id, data={
            'requested_start_date': '2027-01-01', 'requested_end_date': 'not-a-date',
            'requested_rent_amount': '1100', 'csrf_token': csrf_token})
        self.assertEqual(response.status_code, 400)
        self.assertIn('alert-danger', response.text)
        self.assertFalse(self.env['edara.renewal.request'].search([('contract_id', '=', contract.id)]))

    def test_renewal_request_with_missing_end_date_is_rejected(self):
        contract = self._create_active_contract()
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        csrf_token = self._get_csrf_token(self.url_open('/my/leases/%d' % contract.id).text)
        response = self.url_open('/my/leases/%d/renew' % contract.id, data={
            'requested_start_date': '2027-01-01', 'requested_end_date': '',
            'requested_rent_amount': '1100', 'csrf_token': csrf_token})
        self.assertEqual(response.status_code, 400)
        self.assertIn('alert-danger', response.text)
        self.assertFalse(self.env['edara.renewal.request'].search([('contract_id', '=', contract.id)]))

    def test_renewal_request_end_before_start_is_rejected(self):
        contract = self._create_active_contract()
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        csrf_token = self._get_csrf_token(self.url_open('/my/leases/%d' % contract.id).text)
        response = self.url_open('/my/leases/%d/renew' % contract.id, data={
            'requested_start_date': '2027-01-01', 'requested_end_date': '2026-12-01',
            'requested_rent_amount': '1100', 'csrf_token': csrf_token})
        self.assertEqual(response.status_code, 400)
        self.assertIn('alert-danger', response.text)
        self.assertFalse(self.env['edara.renewal.request'].search([('contract_id', '=', contract.id)]))

    def test_renewal_request_end_equal_to_start_is_accepted(self):
        contract = self._create_active_contract()
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        csrf_token = self._get_csrf_token(self.url_open('/my/leases/%d' % contract.id).text)
        response = self.url_open('/my/leases/%d/renew' % contract.id, data={
            'requested_start_date': '2027-01-01', 'requested_end_date': '2027-01-01',
            'requested_rent_amount': '1100', 'csrf_token': csrf_token})
        self.assertEqual(response.status_code, 200)
        renewal = self.env['edara.renewal.request'].search([('contract_id', '=', contract.id)])
        self.assertTrue(renewal)
        self.assertEqual(renewal.requested_start_date, date(2027, 1, 1))
        self.assertEqual(renewal.requested_end_date, date(2027, 1, 1))

    def test_renewal_request_for_non_active_contract_is_rejected(self):
        draft_contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_a.id, 'tenant_id': self.partner_a.id,
            'start_date': date(2027, 1, 1), 'end_date': date(2027, 12, 31), 'rent_amount': 1000,
            'deposit_required': False,
        })
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        csrf_token = self._get_csrf_token(self.url_open('/my/leases/%d' % self.contract_a.id).text)
        response = self.url_open('/my/leases/%d/renew' % draft_contract.id, data={
            'requested_start_date': '2028-01-01', 'requested_end_date': '2028-12-31',
            'requested_rent_amount': '1100', 'csrf_token': csrf_token})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.env['edara.renewal.request'].search([('contract_id', '=', draft_contract.id)]))

    def test_renewal_request_model_rejects_an_early_start_for_a_portal_user(self):
        Request = self.env['edara.renewal.request'].with_user(self.user_a)
        with self.assertRaises(ValidationError):
            Request.create({'contract_id': self.contract_a.id, 'requested_start_date': date(2026, 12, 31),
                            'requested_end_date': date(2027, 12, 31), 'requested_rent_amount': 1100})
        ok = Request.create({'contract_id': self.contract_a.id, 'requested_start_date': date(2027, 1, 1),
                             'requested_end_date': date(2027, 12, 31), 'requested_rent_amount': 1100})
        self.assertEqual(ok.state, 'submitted')

    def test_manager_approval_of_a_boundary_request_creates_a_scheduled_successor(self):
        renewal = self.env['edara.renewal.request'].create({
            'contract_id': self.contract_a.id, 'requested_start_date': date(2027, 1, 1),
            'requested_end_date': date(2027, 12, 31), 'requested_rent_amount': 1100})
        renewal.action_approve()
        self.assertEqual((renewal.state, renewal.new_contract_id.state, self.contract_a.state), ('approved', 'scheduled', 'active'))
        self.assertEqual(renewal.new_contract_id.predecessor_contract_id, self.contract_a)

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

    # ---- Localization / Selection Rendering Regression Test ----

    def test_portal_selection_rendering_uses_t_field(self):
        """Verify that portal templates use t-field instead of raw t-out for selection fields."""
        templates = [
            'property_managment.portal_my_leases',
            'property_managment.portal_lease_detail',
            'property_managment.portal_my_maintenance',
            'property_managment.portal_maintenance_detail',
        ]
        for template_xml_id in templates:
            view = self.env.ref(template_xml_id)
            arch = view.arch
            self.assertNotIn('t-out="contract.state"', arch)
            self.assertNotIn('t-out="renewal.state"', arch)
            self.assertNotIn('t-out="maintenance_request.state"', arch)

    # ================= Phase 12.5 — Portal Detail Access Robustness =================

    def test_unauthorized_tenant_lease_detail_access_denied_not_500(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/leases/%d' % self.contract_b.id)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(self.contract_b.name, response.text)

    def test_unauthorized_tenant_unit_detail_access_denied_not_500(self):
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/units/%d' % self.unit_b.id)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(self.unit_b.name, response.text)

    def test_unauthorized_tenant_maintenance_detail_access_denied_not_500(self):
        maint_b = self.env['edara.maintenance.request'].create({
            'title': 'Tenant B Sink Leak', 'unit_id': self.unit_b.id, 'tenant_id': self.partner_b.id,
        })
        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/maintenance/%d' % maint_b.id)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('Tenant B Sink Leak', response.text)

    def test_authorized_tenant_detail_routes_regression(self):
        maint_a = self.env['edara.maintenance.request'].create({
            'title': 'Tenant A AC Fix', 'unit_id': self.unit_a.id, 'tenant_id': self.partner_a.id,
        })
        self.authenticate('edara_tenant_a', 'edara_tenant_a')

        # Authorized model read access checks pass without AccessError
        self.contract_a.with_user(self.user_a).check_access('read')
        self.unit_a.with_user(self.user_a).check_access('read')
        maint_a.with_user(self.user_a).check_access('read')

        # Own unit detail route (successful 200 HTTP response)
        resp_unit = self.url_open('/my/units/%d' % self.unit_a.id)
        self.assertEqual(resp_unit.status_code, 200)
        self.assertIn(self.unit_a.name, resp_unit.text)

    def test_no_automatic_access_token_generation_on_normal_creation(self):
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_a.id, 'tenant_id': self.partner_a.id,
            'start_date': date(2027, 1, 1), 'end_date': date(2027, 12, 31), 'rent_amount': 1000,
            'deposit_required': False,
        })
        unit = self.env['edara.unit'].create({
            'name': 'Unit Token Test', 'code': 'UTT1', 'building_id': self.building.id,
        })
        maint = self.env['edara.maintenance.request'].create({
            'title': 'Token Test Request', 'unit_id': self.unit_a.id, 'tenant_id': self.partner_a.id,
        })

        self.assertTrue(hasattr(contract, 'access_token'))
        self.assertTrue(hasattr(unit, 'access_token'))
        self.assertTrue(hasattr(maint, 'access_token'))

        self.assertFalse(contract.access_token)
        self.assertFalse(unit.access_token)
        self.assertFalse(maint.access_token)

    def test_unauthenticated_portal_detail_access_remains_protected(self):
        maint_a = self.env['edara.maintenance.request'].create({
            'title': 'Tenant A AC Fix', 'unit_id': self.unit_a.id, 'tenant_id': self.partner_a.id,
        })
        self.opener.cookies.clear()
        resp_lease = self.url_open('/my/leases/%d' % self.contract_a.id, allow_redirects=False)
        self.assertIn(resp_lease.status_code, (302, 303))
        self.assertIn('/web/login', resp_lease.headers.get('Location', ''))

        resp_unit = self.url_open('/my/units/%d' % self.unit_a.id, allow_redirects=False)
        self.assertIn(resp_unit.status_code, (302, 303))
        self.assertIn('/web/login', resp_unit.headers.get('Location', ''))

        resp_maint = self.url_open('/my/maintenance/%d' % maint_a.id, allow_redirects=False)
        self.assertIn(resp_maint.status_code, (302, 303))
        self.assertIn('/web/login', resp_maint.headers.get('Location', ''))

    # ================= Phase 12.10: Mixed-Currency Overdue UX =================

    def _post_overdue_invoice(self, tenant, currency=None, amount=1000.0, ref='Overdue Rent'):
        currency = currency or self.env.company.currency_id
        account_code = '408%d%s' % (tenant.id, currency.name[:3])
        income_account = self.env['account.account'].search([
            ('code', '=', account_code),
        ], limit=1)
        if not income_account:
            income_account = self.env['account.account'].create({
                'name': 'Overdue Income %s %d' % (currency.name, tenant.id),
                'code': account_code,
                'account_type': 'income',
            })
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': tenant.id,
            'currency_id': currency.id,
            'invoice_date': date(2025, 1, 1),
            'invoice_date_due': date(2025, 1, 15),
            'invoice_line_ids': [(0, 0, {
                'name': ref,
                'quantity': 1,
                'price_unit': amount,
                'account_id': income_account.id,
            })],
        })
        move.action_post()
        return move

    def test_overdue_single_currency_pay_all_visible(self):
        """Case A: Tenant has overdue invoice in a single currency -> Pay overdue button is visible."""
        curr_ils = self.env['res.currency'].search([('name', '=', 'ILS')], limit=1) or self.env.company.currency_id
        inv = self._post_overdue_invoice(self.partner_a, currency=curr_ils, amount=500.0)
        self.assertTrue(self.partner_a._has_single_overdue_currency())

        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/invoices')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/my/invoices/overdue', response.text)
        self.assertIn(inv.name, response.text)

    def test_overdue_multiple_invoices_same_currency_pay_all_visible(self):
        """Case A: Multiple overdue invoices in the same currency -> Pay overdue button is visible."""
        curr_ils = self.env['res.currency'].search([('name', '=', 'ILS')], limit=1) or self.env.company.currency_id
        inv1 = self._post_overdue_invoice(self.partner_a, currency=curr_ils, amount=500.0, ref='Rent Part 1')
        inv2 = self._post_overdue_invoice(self.partner_a, currency=curr_ils, amount=700.0, ref='Rent Part 2')
        self.assertTrue(self.partner_a._has_single_overdue_currency())

        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/invoices')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/my/invoices/overdue', response.text)
        self.assertIn(inv1.name, response.text)
        self.assertIn(inv2.name, response.text)

    def test_overdue_mixed_currency_pay_all_hidden_and_individual_invoices_visible(self):
        """Case B: Multiple overdue currencies (ILS + USD) -> Pay All Overdue action is hidden,
        while each invoice remains visible in the list."""
        curr_ils = self.env['res.currency'].search([('name', '=', 'ILS')], limit=1) or self.env.company.currency_id
        curr_usd = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        self.assertTrue(curr_usd, "USD currency must exist")

        inv_ils = self._post_overdue_invoice(self.partner_a, currency=curr_ils, amount=500.0, ref='ILS Overdue')
        inv_usd = self._post_overdue_invoice(self.partner_a, currency=curr_usd, amount=200.0, ref='USD Overdue')
        self.assertFalse(self.partner_a._has_single_overdue_currency())

        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/invoices')
        self.assertEqual(response.status_code, 200)
        # Pay All button is hidden
        self.assertNotIn('/my/invoices/overdue', response.text)
        # Both individual invoices are visible in the list
        self.assertIn(inv_ils.name, response.text)
        self.assertIn(inv_usd.name, response.text)

    def test_overdue_triple_mixed_currency_pay_all_hidden(self):
        """Case B: Multiple overdue currencies (ILS + USD + JOD) -> Pay All Overdue action is hidden."""
        curr_ils = self.env['res.currency'].search([('name', '=', 'ILS')], limit=1) or self.env.company.currency_id
        curr_usd = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        curr_jod = self.env['res.currency'].search([('name', '=', 'JOD')], limit=1)
        self.assertTrue(curr_usd and curr_jod, "USD and JOD currencies must exist")

        self._post_overdue_invoice(self.partner_a, currency=curr_ils, amount=500.0, ref='ILS Overdue')
        self._post_overdue_invoice(self.partner_a, currency=curr_usd, amount=200.0, ref='USD Overdue')
        self._post_overdue_invoice(self.partner_a, currency=curr_jod, amount=150.0, ref='JOD Overdue')
        self.assertFalse(self.partner_a._has_single_overdue_currency())

        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        response = self.url_open('/my/invoices')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('/my/invoices/overdue', response.text)

    def test_overdue_individual_invoice_payment_accessible_for_mixed_currency(self):
        """Case B: Individual invoice detail pages and native payment flows remain accessible
        when multiple overdue currencies exist."""
        curr_ils = self.env['res.currency'].search([('name', '=', 'ILS')], limit=1) or self.env.company.currency_id
        curr_usd = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)

        inv_ils = self._post_overdue_invoice(self.partner_a, currency=curr_ils, amount=500.0, ref='ILS Rent')
        inv_usd = self._post_overdue_invoice(self.partner_a, currency=curr_usd, amount=200.0, ref='USD Rent')

        self.authenticate('edara_tenant_a', 'edara_tenant_a')
        # Check individual ILS invoice page
        resp_ils = self.url_open('/my/invoices/%d' % inv_ils.id)
        self.assertEqual(resp_ils.status_code, 200)
        self.assertIn(inv_ils.name, resp_ils.text)

        # Check individual USD invoice page
        resp_usd = self.url_open('/my/invoices/%d' % inv_usd.id)
        self.assertEqual(resp_usd.status_code, 200)
        self.assertIn(inv_usd.name, resp_usd.text)
