from datetime import date, timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraPortalProvisioning(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Ramallah Branch', 'code': 'RAM_PROV'})
        cls.property = cls.env['edara.property'].create({
            'name': 'Ramallah Center', 'code': 'RMC_PROV', 'branch_id': cls.branch.id
        })
        cls.building = cls.env['edara.building'].create({
            'name': 'Building 1', 'code': 'B1', 'property_id': cls.property.id
        })
        cls.unit_1 = cls.env['edara.unit'].create({'name': 'U-101', 'code': '101', 'building_id': cls.building.id})
        cls.unit_2 = cls.env['edara.unit'].create({'name': 'U-102', 'code': '102', 'building_id': cls.building.id})

        cls.portal_group = cls.env.ref('base.group_portal')
        cls.edara_portal_group = cls.env.ref('property_managment.group_edara_portal_tenant')

    def test_1_active_lease_automatically_provisions_portal_user(self):
        """Partner -> no portal user -> activate lease -> portal user created automatically with base.group_portal and group_edara_portal_tenant."""
        partner = self.env['res.partner'].create({'name': 'New Tenant 1', 'email': 'tenant1_prov@example.com'})
        users_before = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])
        self.assertFalse(users_before)

        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        users_after = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])
        self.assertTrue(users_after)
        user = users_after[0]
        self.assertTrue(user.active)
        self.assertIn(self.portal_group, user.group_ids)
        self.assertIn(self.edara_portal_group, user.group_ids)

    def test_2_existing_portal_user_gets_edara_group(self):
        """Partner -> existing portal user -> activate lease -> EDARA group granted to existing user."""
        partner = self.env['res.partner'].create({'name': 'Existing Portal Tenant', 'email': 'existing_prov@example.com'})
        user = self.env['res.users'].create({
            'name': 'Existing Portal User',
            'login': 'existing_prov_login',
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.portal_group.id])],
        })
        self.assertNotIn(self.edara_portal_group, user.group_ids)

        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        self.assertIn(self.edara_portal_group, user.group_ids)
        self.assertTrue(user.active)

    def test_3_existing_archived_portal_user_is_reactivated(self):
        """Partner -> archived portal user -> activate lease -> user active=True & EDARA group present."""
        partner = self.env['res.partner'].create({'name': 'Archived Tenant', 'email': 'archived_prov@example.com'})
        user = self.env['res.users'].with_context(no_reset_password=True, signup_valid=False).create({
            'name': 'Archived User',
            'login': 'archived_prov_login',
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.portal_group.id])],
        })
        user.sudo().write({'active': False})
        self.assertFalse(user.active)

        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        self.assertTrue(user.active)
        self.assertIn(self.edara_portal_group, user.group_ids)

    def test_4_no_duplicate_portal_users(self):
        """Activating a second lease for a partner does not create duplicate user records."""
        partner = self.env['res.partner'].create({'name': 'Multi Lease Tenant', 'email': 'multilease_prov@example.com'})
        contract_1 = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_1.action_activate()

        users_1 = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])
        self.assertEqual(len(users_1), 1)

        contract_2 = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 600,
            'deposit_required': False,
        })
        contract_2.action_activate()

        users_2 = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])
        self.assertEqual(len(users_2), 1)
        self.assertEqual(users_1.id, users_2.id)

    def test_5_multiple_active_leases(self):
        """Repeated provisioning over multiple active leases is idempotent."""
        partner = self.env['res.partner'].create({'name': 'Tenant M', 'email': 'tenantm_prov@example.com'})
        partner._provision_edara_portal_tenant()
        partner._provision_edara_portal_tenant()
        users = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])
        self.assertEqual(len(users), 1)

    def test_6_renewal(self):
        """Renewal of a lease maintains the same active portal user."""
        partner = self.env['res.partner'].create({'name': 'Renewal Tenant', 'email': 'renew_prov@example.com'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() + timedelta(days=10),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])[0]
        self.assertTrue(user.active)

        contract.action_renew(
            new_start_date=contract.end_date + timedelta(days=1),
            new_end_date=contract.end_date + timedelta(days=365),
            new_rent_amount=550,
        )

        self.assertTrue(user.active)
        self.assertIn(self.edara_portal_group, user.group_ids)

    def test_7_termination_does_not_immediately_disable_portal_user(self):
        """Terminating the only active lease does NOT immediately archive the portal user."""
        partner = self.env['res.partner'].create({'name': 'Terminated Tenant', 'email': 'term_prov@example.com'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=30),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])[0]
        self.assertTrue(user.active)

        contract.action_terminate(reason='Moving out')
        self.assertTrue(user.active)

    def test_8_retention_period(self):
        """Portal user remains active if lease ended less than 30 days ago."""
        partner = self.env['res.partner'].create({'name': 'Recent Lease Ended Tenant', 'email': 'recent_prov@example.com'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=10),  # Ended 10 days ago (< 30 days)
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})

        user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])[0]
        self.assertTrue(user.active)

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()

        self.assertTrue(user.active)

    def test_9_retention_expiry(self):
        """Portal user is archived when lease ended > 30 days ago and no live lease exists."""
        partner = self.env['res.partner'].create({'name': 'Old Lease Ended Tenant', 'email': 'old_prov@example.com'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=35),  # Ended 35 days ago (> 30 days)
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})

        user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])[0]
        self.assertTrue(user.active)

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()

        self.assertFalse(user.active)

    def test_10_another_active_lease_prevents_archival(self):
        """If tenant has an old ended lease (>30 days ago) BUT another active lease, portal user remains active."""
        partner = self.env['res.partner'].create({'name': 'Multi Lease Retention Tenant', 'email': 'multiret_prov@example.com'})
        contract_old = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=200),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_old.action_activate()
        contract_old.sudo().write({'state': 'expired'})

        contract_active = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 600,
            'deposit_required': False,
        })
        contract_active.action_activate()

        user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])[0]
        self.assertTrue(user.active)

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()

        self.assertTrue(user.active)

    def test_11_reactivation_after_retention(self):
        """Archived user is reactivated when a new lease becomes active."""
        partner = self.env['res.partner'].create({'name': 'Reactivation Tenant', 'email': 'react_prov@example.com'})
        contract_old = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=200),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_old.action_activate()
        contract_old.sudo().write({'state': 'expired'})

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id), ('active', '=', False)])
        self.assertTrue(user)
        self.assertFalse(user.active)

        contract_new = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 600,
            'deposit_required': False,
        })
        contract_new.action_activate()

        self.assertTrue(user.active)
        self.assertIn(self.edara_portal_group, user.group_ids)

    def test_12_unrelated_portal_user(self):
        """Normal portal user without EDARA lease does not receive EDARA tenant portal group."""
        partner = self.env['res.partner'].create({'name': 'Unrelated Portal User', 'email': 'unrelated_prov@example.com'})
        user = self.env['res.users'].create({
            'name': 'Unrelated User',
            'login': 'unrelated_prov_login',
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.portal_group.id])],
        })
        self.assertNotIn(self.edara_portal_group, user.group_ids)

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertNotIn(self.edara_portal_group, user.group_ids)

    def test_13_draft_cancelled_lease_does_not_provision_access(self):
        """Draft or cancelled lease does not provision EDARA tenant portal access."""
        partner = self.env['res.partner'].create({'name': 'Draft Lease Tenant', 'email': 'draft_prov@example.com'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        users = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])
        self.assertFalse(users)

    def test_14_multiple_users_linked_to_same_partner(self):
        """Provisioning operates deterministically if a partner has multiple user records."""
        partner = self.env['res.partner'].create({'name': 'Double User Tenant', 'email': 'double_prov@example.com'})
        user_1 = self.env['res.users'].create({
            'name': 'Double User 1',
            'login': 'double_prov_1',
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.portal_group.id])],
        })
        user_2 = self.env['res.users'].create({
            'name': 'Double User 2',
            'login': 'double_prov_2',
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.portal_group.id])],
        })

        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        self.assertIn(self.edara_portal_group, user_1.group_ids)
        self.assertIn(self.edara_portal_group, user_2.group_ids)

    def test_15_real_native_portal_grant_path(self):
        """Creating a native portal user for a partner with a live lease automatically grants group_edara_portal_tenant."""
        partner = self.env['res.partner'].create({'name': 'Native Grant Tenant', 'email': 'nativegrant_prov@example.com'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        native_user = self.env['res.users'].create({
            'name': 'Native Grant User',
            'login': 'nativegrant_prov_login',
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.portal_group.id])],
        })

        self.assertIn(self.edara_portal_group, native_user.group_ids)

    def test_16_portal_security_regression(self):
        """Security regression: provisioned tenant can view own lease, but foreign tenant lease returns 403."""
        partner_a = self.env['res.partner'].create({'name': 'Tenant Security A', 'email': 'sec_a_prov@example.com'})
        partner_b = self.env['res.partner'].create({'name': 'Tenant Security B', 'email': 'sec_b_prov@example.com'})

        contract_a = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner_a.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_a.action_activate()

        contract_b = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner_b.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'rent_amount': 600,
            'deposit_required': False,
        })
        contract_b.action_activate()

        user_a = self.env['res.users'].sudo().search([('partner_id', '=', partner_a.id)])[0]

        # Authenticate user A via HttpCase
        self.authenticate(user_a.login, user_a.login)

        # Own lease route -> 200
        res_own = self.url_open(f'/my/leases/{contract_a.id}')
        self.assertEqual(res_own.status_code, 200)

        # Foreign lease route -> 403 Access Denied
        res_foreign = self.url_open(f'/my/leases/{contract_b.id}')
        self.assertEqual(res_foreign.status_code, 403)
