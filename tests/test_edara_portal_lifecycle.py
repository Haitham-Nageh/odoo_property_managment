from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestEdaraPortalLifecycle(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.edara_portal_grace_days = 30

        cls.branch = cls.env['edara.branch'].create({
            'name': 'Lifecycle Branch',
            'code': 'LC_BR',
        })
        cls.property = cls.env['edara.property'].create({
            'name': 'Lifecycle Property',
            'code': 'LC_PROP',
            'branch_id': cls.branch.id,
        })
        cls.building = cls.env['edara.building'].create({
            'name': 'Lifecycle Building',
            'code': 'LC_BLD',
            'property_id': cls.property.id,
        })
        cls.unit_1 = cls.env['edara.unit'].create({
            'name': 'LC-101',
            'code': '101',
            'building_id': cls.building.id,
            'area': 100.0,
        })
        cls.unit_2 = cls.env['edara.unit'].create({
            'name': 'LC-102',
            'code': '102',
            'building_id': cls.building.id,
            'area': 150.0,
        })
        cls.unit_3 = cls.env['edara.unit'].create({
            'name': 'LC-103',
            'code': '103',
            'building_id': cls.building.id,
            'area': 120.0,
        })

        cls.portal_group = cls.env.ref('base.group_portal')
        cls.edara_portal_group = cls.env.ref('property_managment.group_edara_portal_tenant')
        cls.branch_mgr_group = cls.env.ref('property_managment.group_edara_branch_manager')
        cls.prop_mgr_group = cls.env.ref('property_managment.group_edara_property_manager')
        cls.accountant_group = cls.env.ref('property_managment.group_edara_accountant')

        # Users for access tests
        cls.branch_manager_user = new_test_user(
            cls.env,
            login='lc_branch_mgr@example.com',
            groups='base.group_user,property_managment.group_edara_branch_manager',
        )
        cls.branch.manager_id = cls.branch_manager_user

        cls.property_manager_user = new_test_user(
            cls.env,
            login='lc_prop_mgr@example.com',
            groups='base.group_user,property_managment.group_edara_property_manager',
        )
        cls.branch.user_ids = [(4, cls.branch_manager_user.id), (4, cls.property_manager_user.id)]

        cls.accountant_user = new_test_user(
            cls.env,
            login='lc_accountant@example.com',
            groups='base.group_user,property_managment.group_edara_accountant',
        )

    def _create_tenant_with_portal_user(self, name, email):
        partner = self.env['res.partner'].create({'name': name, 'email': email})
        user = self.env['res.users'].with_context(no_reset_password=True, signup_valid=False).create({
            'name': name,
            'login': email,
            'email': email,
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.portal_group.id, self.edara_portal_group.id])],
            'active': True,
            'edara_portal_lifecycle_archived': False,
        })
        return partner, user

    # =========================================================================
    # Group 1: Portal Eligibility & Contract Precedence
    # =========================================================================

    def test_01_active_contract_preserves_access_and_clears_settled_date(self):
        """A tenant with an active contract retains access; settled date is cleared."""
        partner, user = self._create_tenant_with_portal_user('Tenant Active', 'active_t@example.com')
        partner.edara_portal_settled_date = fields.Date.today() - timedelta(days=50)

        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=10),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 1000,
            'deposit_required': False,
        })
        contract.action_activate()

        self.assertEqual(contract.state, 'active')
        self.env['res.partner']._cron_cleanup_expired_portal_tenants()

        self.assertTrue(user.active)
        self.assertFalse(partner.edara_portal_settled_date)

    def test_02_scheduled_contract_does_not_grant_portal_access(self):
        """A scheduled contract does not provision portal access until active."""
        partner = self.env['res.partner'].create({
            'name': 'Tenant Scheduled',
            'email': 'sched_t@example.com',
        })
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() + timedelta(days=30),
            'end_date': fields.Date.today() + timedelta(days=200),
            'rent_amount': 1000,
            'deposit_required': False,
        })
        contract.action_activate()
        self.assertEqual(contract.state, 'scheduled')

        users = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])
        self.assertFalse(users, "Scheduled contract must not provision a portal user.")

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        users_after = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)])
        self.assertFalse(users_after, "Cron evaluator must not provision scheduled contract tenant.")

    def test_03_multiple_contracts_retains_access_when_one_qualifies(self):
        """Tenant with an old expired contract but another active contract retains access."""
        partner, user = self._create_tenant_with_portal_user('Multi Contract Tenant', 'multi_c@example.com')

        old_contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=300),
            'end_date': fields.Date.today() - timedelta(days=60),
            'rent_amount': 500,
            'deposit_required': False,
        })
        old_contract.action_activate()
        old_contract.sudo().write({'state': 'expired'})
        old_contract.schedule_line_ids.unlink()

        active_contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=10),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 600,
            'deposit_required': False,
        })
        active_contract.action_activate()

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertTrue(user.active)

    # =========================================================================
    # Group 2: Effective End Dates, Early Termination, & Grace Boundaries
    # =========================================================================

    def test_04_effective_end_date_expired_within_and_past_grace(self):
        """User is retained within grace (<= 30 days) and archived once past grace (> 30 days)."""
        # Tenant A: ended 30 days ago (within grace)
        partner_a, user_a = self._create_tenant_with_portal_user('Retention A', 'bound_a@example.com')
        contract_a = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner_a.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=30),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_a.action_activate()
        contract_a.sudo().write({'state': 'expired'})
        contract_a.schedule_line_ids.unlink()

        # Tenant B: ended 31 days ago (past grace)
        partner_b, user_b = self._create_tenant_with_portal_user('Retention B', 'bound_b@example.com')
        contract_b = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner_b.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=31),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_b.action_activate()
        contract_b.sudo().write({'state': 'expired'})
        contract_b.schedule_line_ids.unlink()

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertTrue(user_a.active, "User A should remain active through grace-end date.")
        self.assertFalse(user_b.active, "User B should be archived once today > grace_end.")
        self.assertTrue(user_b.edara_portal_lifecycle_archived)

    def test_05_effective_end_date_early_termination(self):
        """For terminated contract, effective end is the earlier of termination_date and end_date."""
        partner, user = self._create_tenant_with_portal_user('Early Term Tenant', 'early_term@example.com')
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() + timedelta(days=100),  # End date was in future
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        # Early termination 35 days ago (> 30 day grace)
        contract.sudo().write({
            'state': 'terminated',
            'termination_date': fields.Date.today() - timedelta(days=35),
        })
        contract.schedule_line_ids.unlink()

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertFalse(user.active, "Termination date must govern effective end.")
        self.assertTrue(user.edara_portal_lifecycle_archived)

    def test_06_zero_day_grace_period_behavior(self):
        """0-day grace retains access on anchor date and archives on following date."""
        self.company.edara_portal_grace_days = 0
        # Tenant A: ended today
        partner_a, user_a = self._create_tenant_with_portal_user('Zero Grace A', 'zero_a@example.com')
        contract_a = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner_a.id,
            'start_date': fields.Date.today() - timedelta(days=50),
            'end_date': fields.Date.today(),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_a.action_activate()
        contract_a.sudo().write({'state': 'expired'})
        contract_a.schedule_line_ids.unlink()

        # Tenant B: ended yesterday (1 day ago)
        partner_b, user_b = self._create_tenant_with_portal_user('Zero Grace B', 'zero_b@example.com')
        contract_b = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner_b.id,
            'start_date': fields.Date.today() - timedelta(days=50),
            'end_date': fields.Date.today() - timedelta(days=1),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_b.action_activate()
        contract_b.sudo().write({'state': 'expired'})
        contract_b.schedule_line_ids.unlink()

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertTrue(user_a.active, "0-day grace retains access on the anchor date.")
        self.assertFalse(user_b.active, "0-day grace archives on the day following anchor date.")
        self.company.edara_portal_grace_days = 30

    def test_07_grace_period_setting_constraints(self):
        """Company grace period must be between 0 and 3650 days."""
        with self.assertRaises(ValidationError):
            self.company.edara_portal_grace_days = -1
        with self.assertRaises(ValidationError):
            self.company.edara_portal_grace_days = 3651
        self.company.edara_portal_grace_days = 0
        self.assertEqual(self.company.edara_portal_grace_days, 0)
        self.company.edara_portal_grace_days = 3650
        self.assertEqual(self.company.edara_portal_grace_days, 3650)
        self.company.edara_portal_grace_days = 30

    # =========================================================================
    # Group 3: Outstanding Obligations (Blockers)
    # =========================================================================

    def test_08_outstanding_invoices_block_archival(self):
        """Unpaid qualifying customer invoices (rent, late_fee, service_charge, ad_hoc) block archival."""
        partner, user = self._create_tenant_with_portal_user('Invoice Block Tenant', 'inv_block@example.com')
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})
        contract.schedule_line_ids.unlink()

        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today() - timedelta(days=10),
            'edara_invoice_type': 'rent',
            'edara_unit_id': self.unit_1.id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent', 'quantity': 1, 'price_unit': 500})],
        })
        invoice.action_post()
        self.assertEqual(invoice.payment_state, 'not_paid')

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertTrue(user.active, "Unpaid rent invoice must block archival.")

    def test_09_overdue_uninvoiced_rent_schedule_line_blocks_archival(self):
        """Overdue uninvoiced rent schedule line (due_date <= today) on ended contract blocks archival."""
        partner, user = self._create_tenant_with_portal_user('Sched Block Tenant', 'sched_block@example.com')
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})
        overdue_line = contract.schedule_line_ids.filtered(lambda l: l.due_date <= fields.Date.today())
        self.assertTrue(overdue_line)

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertTrue(user.active, "Overdue uninvoiced rent schedule line must block archival.")

    def test_10_pending_service_charge_line_blocks_archival(self):
        """Uninvoiced service-charge line blocks archival."""
        partner, user = self._create_tenant_with_portal_user('SC Block Tenant', 'sc_block@example.com')
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})
        contract.schedule_line_ids.unlink()

        sc = self.env['edara.service.charge'].create({
            'building_id': self.building.id,
            'date': fields.Date.today(),
            'allocation_method': 'fixed_per_unit',
            'fixed_amount_per_unit': 200,
        })
        sc_line = self.env['edara.service.charge.line'].create({
            'charge_id': sc.id,
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'amount': 200,
        })
        self.assertFalse(sc_line.invoice_id)

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertTrue(user.active, "Pending uninvoiced service charge line must block archival.")

    def test_11_cancelled_invoice_does_not_block_archival(self):
        """Cancelled invoices do not block archival."""
        partner, user = self._create_tenant_with_portal_user('Cancel Inv Tenant', 'cancel_inv@example.com')
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})
        contract.schedule_line_ids.unlink()

        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today() - timedelta(days=10),
            'edara_invoice_type': 'rent',
            'edara_unit_id': self.unit_1.id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent', 'quantity': 1, 'price_unit': 500})],
        })
        invoice.action_post()
        invoice.button_cancel()
        self.assertEqual(invoice.state, 'cancel')

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertFalse(user.active, "Cancelled invoices must not block archival.")
        self.assertTrue(user.edara_portal_lifecycle_archived)

    def test_12_clean_settlement_starts_grace_period(self):
        """Paid/reversed invoices are cleanly settled, starting the grace period from settled date."""
        partner, user = self._create_tenant_with_portal_user('Settled Tenant', 'settled_t@example.com')
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})
        contract.schedule_line_ids.unlink()

        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today() - timedelta(days=5),
            'edara_invoice_type': 'rent',
            'edara_unit_id': self.unit_1.id,
            'invoice_line_ids': [(0, 0, {'name': 'Rent', 'quantity': 1, 'price_unit': 500})],
        })
        invoice.action_post()
        invoice.sudo().write({'payment_state': 'paid'})

        self.assertFalse(partner.edara_portal_settled_date)
        self.env['res.partner']._cron_cleanup_expired_portal_tenants()

        self.assertEqual(partner.edara_portal_settled_date, fields.Date.today())
        self.assertTrue(user.active, "Tenant retains access within grace period after settlement.")

    def test_13_new_blocker_clears_settled_date(self):
        """When a new blocker appears, settled date is cleared."""
        partner, user = self._create_tenant_with_portal_user('New Blocker Tenant', 'new_blocker@example.com')
        partner.edara_portal_settled_date = fields.Date.today() - timedelta(days=10)

        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})
        contract.schedule_line_ids.unlink()

        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'edara_invoice_type': 'ad_hoc',
            'invoice_line_ids': [(0, 0, {'name': 'Adhoc', 'quantity': 1, 'price_unit': 100})],
        })
        invoice.action_post()

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertFalse(partner.edara_portal_settled_date, "New blocker must clear settled date.")

    # =========================================================================
    # Group 4: Lifecycle Archival & Manual Archive Safety
    # =========================================================================

    def test_14_lifecycle_archived_user_reactivated_on_qualifying_obligation(self):
        """A lifecycle-archived user is reactivated when a qualifying obligation appears."""
        partner, user = self._create_tenant_with_portal_user('React Block Tenant', 'react_block@example.com')
        user.sudo().write({'active': False, 'edara_portal_lifecycle_archived': True})
        self.assertFalse(user.active)

        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()
        contract.sudo().write({'state': 'expired'})
        contract.schedule_line_ids.unlink()

        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'edara_invoice_type': 'rent',
            'invoice_line_ids': [(0, 0, {'name': 'Rent', 'quantity': 1, 'price_unit': 500})],
        })
        invoice.action_post()

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertTrue(user.active, "Lifecycle-archived user must be reactivated upon blocker.")
        self.assertFalse(user.edara_portal_lifecycle_archived)

    def test_15_manually_archived_user_is_never_automatically_reactivated(self):
        """A manually archived user is never automatically reactivated."""
        partner, user = self._create_tenant_with_portal_user('Manual Archive Tenant', 'man_arch@example.com')
        user.sudo().write({'active': False})
        self.assertFalse(user.active)
        self.assertFalse(user.edara_portal_lifecycle_archived)

        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today() - timedelta(days=10),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        self.assertFalse(user.active, "Manual archive must not be reactivated by contract activation.")

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertFalse(user.active, "Manual archive must not be reactivated by cron evaluator.")

    def test_16_manual_archive_resets_lifecycle_flag(self):
        """An ordinary manual write({'active': False}) resets the lifecycle flag."""
        partner, user = self._create_tenant_with_portal_user('Flag Reset Tenant', 'flag_reset@example.com')
        user.sudo().write({'active': False, 'edara_portal_lifecycle_archived': True})
        self.assertTrue(user.edara_portal_lifecycle_archived)

        user.sudo().write({'active': False})
        self.assertFalse(user.edara_portal_lifecycle_archived, "Manual archive must reset lifecycle flag.")

    def test_17_internal_users_are_never_modified(self):
        """Internal users linked to partner are never archived or modified by lifecycle."""
        partner = self.env['res.partner'].create({'name': 'Internal Partner', 'email': 'internal@example.com'})
        user = self.env['res.users'].create({
            'name': 'Internal User',
            'login': 'internal@example.com',
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.assertTrue(user.has_group('base.group_user'))

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.assertTrue(user.active)

    # =========================================================================
    # Group 5: Provisioning Safeguards & Follow-up Activities
    # =========================================================================

    def test_18_missing_invalid_email_and_login_conflict_activities(self):
        """Missing email, invalid email, or login conflict does not block activation; creates follow-up activity."""
        # 1. Missing email
        partner_no_email = self.env['res.partner'].create({'name': 'No Email Tenant', 'email': False})
        contract_1 = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner_no_email.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_1.action_activate()
        self.assertEqual(contract_1.state, 'active')
        act_1 = partner_no_email.activity_ids.filtered(lambda a: "Missing Email" in a.summary)
        self.assertTrue(act_1, "Missing email should schedule follow-up activity.")

        # 2. Invalid email
        partner_inv_email = self.env['res.partner'].create({'name': 'Invalid Email Tenant', 'email': 'not-an-email'})
        contract_2 = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner_inv_email.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_2.action_activate()
        act_2 = partner_inv_email.activity_ids.filtered(lambda a: "Invalid Email" in a.summary)
        self.assertTrue(act_2, "Invalid email should schedule follow-up activity.")

        # 3. Login conflict
        existing_user = self.env['res.users'].create({
            'name': 'Existing Login User',
            'login': 'conflict_login@example.com',
            'email': 'conflict_login@example.com',
        })
        partner_conflict = self.env['res.partner'].create({
            'name': 'Conflict Tenant',
            'email': 'conflict_login@example.com',
        })
        contract_3 = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_3.id,
            'tenant_id': partner_conflict.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_3.action_activate()
        act_3 = partner_conflict.activity_ids.filtered(lambda a: "Login Conflict" in a.summary)
        self.assertTrue(act_3, "Login conflict should schedule follow-up activity.")

    def test_19_idempotent_evaluator_runs_no_duplicate_activities(self):
        """Repeated evaluator runs do not duplicate staff follow-up activities."""
        partner = self.env['res.partner'].create({'name': 'Idempotent Tenant', 'email': False})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        count_1 = len(partner.activity_ids)
        self.assertEqual(count_1, 1)

        self.env['res.partner']._cron_cleanup_expired_portal_tenants()
        self.env['res.partner']._cron_cleanup_expired_portal_tenants()

        count_2 = len(partner.activity_ids)
        self.assertEqual(count_1, count_2, "Repeated evaluator runs must not duplicate activities.")

    # =========================================================================
    # Group 6: Service Charge Safeguards & Audited Removal Wizard
    # =========================================================================

    def test_20_invoiced_service_charge_line_cannot_be_deleted(self):
        """Invoiced service charge lines cannot be deleted."""
        sc = self.env['edara.service.charge'].create({
            'building_id': self.building.id,
            'date': fields.Date.today(),
            'allocation_method': 'fixed_per_unit',
            'fixed_amount_per_unit': 200,
        })
        line = self.env['edara.service.charge.line'].create({
            'charge_id': sc.id,
            'unit_id': self.unit_1.id,
            'tenant_id': self.branch_manager_user.partner_id.id,
            'amount': 200,
        })
        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': self.branch_manager_user.partner_id.id,
            'invoice_date': fields.Date.today(),
        })
        line.sudo().invoice_id = invoice.id

        with self.assertRaises(UserError):
            line.unlink()

        with self.assertRaises(UserError):
            line.with_context(edara_allow_service_charge_line_unlink=True).unlink()

    def test_21_uninvoiced_service_charge_line_direct_delete_blocked(self):
        """Uninvoiced line direct unlink is blocked except via privileged/audited route."""
        sc = self.env['edara.service.charge'].create({
            'building_id': self.building.id,
            'date': fields.Date.today(),
            'allocation_method': 'fixed_per_unit',
            'fixed_amount_per_unit': 200,
        })
        line = self.env['edara.service.charge.line'].create({
            'charge_id': sc.id,
            'unit_id': self.unit_1.id,
            'tenant_id': self.branch_manager_user.partner_id.id,
            'amount': 200,
        })

        with self.assertRaises(UserError):
            line.unlink()

        # Privileged route succeeds
        line.with_context(edara_allow_service_charge_line_unlink=True).unlink()
        self.assertFalse(line.exists())

    def test_22_parent_service_charge_delete_refused_when_lines_exist(self):
        """Deleting parent service charge is refused while allocation lines exist."""
        sc = self.env['edara.service.charge'].create({
            'building_id': self.building.id,
            'date': fields.Date.today(),
            'allocation_method': 'fixed_per_unit',
            'fixed_amount_per_unit': 200,
        })
        line = self.env['edara.service.charge.line'].create({
            'charge_id': sc.id,
            'unit_id': self.unit_1.id,
            'tenant_id': self.branch_manager_user.partner_id.id,
            'amount': 200,
        })

        with self.assertRaises(UserError):
            sc.unlink()

        # Once lines are removed via privileged route, parent can be deleted
        line.with_context(edara_allow_service_charge_line_unlink=True).unlink()
        sc.unlink()
        self.assertFalse(sc.exists())

    def test_23_regeneration_refuses_when_pair_dropped_and_identifies_pairs(self):
        """Regeneration refuses if existing uninvoiced line's (unit, tenant) pair would disappear."""
        partner = self.env['res.partner'].create({'name': 'Tenant SC 1', 'email': 'sc1@example.com'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        sc = self.env['edara.service.charge'].create({
            'building_id': self.building.id,
            'date': fields.Date.today(),
            'allocation_method': 'equal',
            'total_amount': 500,
        })
        sc.action_generate_allocation()
        self.assertEqual(len(sc.line_ids), 1)

        # Now simulate tenant moving out (contract terminated)
        contract.sudo().write({'state': 'terminated', 'termination_date': fields.Date.today()})

        # Attempt regeneration -> pair (unit_1, partner) would disappear!
        with self.assertRaises(UserError) as cm:
            sc.action_generate_allocation()
        self.assertIn("pairs would be dropped", str(cm.exception))
        self.assertIn(self.unit_1.display_name, str(cm.exception))

    def test_24_regeneration_allows_amount_change_when_pairs_remain(self):
        """Regeneration succeeds when (unit, tenant) pairs remain unchanged, updating amounts."""
        partner = self.env['res.partner'].create({'name': 'Tenant SC 2', 'email': 'sc2@example.com'})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=100),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract.action_activate()

        sc = self.env['edara.service.charge'].create({
            'building_id': self.building.id,
            'date': fields.Date.today(),
            'allocation_method': 'equal',
            'total_amount': 500,
        })
        sc.action_generate_allocation()
        self.assertEqual(sc.line_ids[0].amount, 500)

        # Change total amount and regenerate
        sc.total_amount = 750
        sc.action_generate_allocation()
        self.assertEqual(len(sc.line_ids), 1)
        self.assertEqual(sc.line_ids[0].amount, 750)

    def test_25_remove_as_not_payable_wizard_workflow(self):
        """Remove as Not Payable wizard requires reason, records chatter note, and removes line."""
        partner = self.env['res.partner'].create({'name': 'Not Payable Tenant', 'email': 'notpay@example.com'})
        sc = self.env['edara.service.charge'].create({
            'building_id': self.building.id,
            'date': fields.Date.today(),
            'allocation_method': 'fixed_per_unit',
            'fixed_amount_per_unit': 200,
        })
        line = self.env['edara.service.charge.line'].create({
            'charge_id': sc.id,
            'unit_id': self.unit_1.id,
            'tenant_id': partner.id,
            'amount': 200,
        })

        Wizard = self.env['edara.service.charge.not.payable.wizard'].with_user(self.branch_manager_user)
        # Reason required
        wiz_no_reason = Wizard.create({'line_id': line.id, 'reason': '  '})
        with self.assertRaises(UserError):
            wiz_no_reason.action_confirm()

        # Non-manager access denied
        with self.assertRaises(AccessError):
            self.env['edara.service.charge.not.payable.wizard'].with_user(self.accountant_user).create({
                'line_id': line.id,
                'reason': 'Disputed charge',
            })

        # Successful removal by branch manager
        wiz = Wizard.create({
            'line_id': line.id,
            'reason': 'Tenant vacated prior to charge period',
        })
        wiz.action_confirm()

        self.assertFalse(line.exists())
        msg = partner.message_ids.filtered(lambda m: "removed as not payable" in m.body)
        self.assertTrue(msg)
        self.assertIn("Tenant vacated prior to charge period", msg.body)

    def test_26_service_charge_line_immutable_fields_and_amount_edit(self):
        """Line tenant, unit, and charge are immutable for non-superusers; amount can be edited."""
        sc = self.env['edara.service.charge'].create({
            'building_id': self.building.id,
            'date': fields.Date.today(),
            'allocation_method': 'fixed_per_unit',
            'fixed_amount_per_unit': 200,
        })
        line = self.env['edara.service.charge.line'].create({
            'charge_id': sc.id,
            'unit_id': self.unit_1.id,
            'tenant_id': self.branch_manager_user.partner_id.id,
            'amount': 200,
        })

        line_user = line.with_user(self.branch_manager_user)
        with self.assertRaises(UserError):
            line_user.write({'tenant_id': self.accountant_user.partner_id.id})

        with self.assertRaises(UserError):
            line_user.write({'unit_id': self.unit_2.id})

        # Amount edit is permitted
        line_user.write({'amount': 250})
        self.assertEqual(line.amount, 250)

    # =========================================================================
    # Group 7: Fault Isolation
    # =========================================================================

    def test_27_tenant_exception_does_not_halt_batch(self):
        """Failure processing one tenant does not stop other tenants from being evaluated."""
        partner_1, user_1 = self._create_tenant_with_portal_user('Tenant Faulty', 'faulty@example.com')
        partner_2, user_2 = self._create_tenant_with_portal_user('Tenant Normal', 'normal@example.com')

        contract_2 = self.env['edara.lease.contract'].create({
            'unit_id': self.unit_2.id,
            'tenant_id': partner_2.id,
            'start_date': fields.Date.today() - timedelta(days=100),
            'end_date': fields.Date.today() - timedelta(days=40),
            'rent_amount': 500,
            'deposit_required': False,
        })
        contract_2.action_activate()
        contract_2.sudo().write({'state': 'expired'})
        contract_2.schedule_line_ids.unlink()

        orig_eval = type(self.env['res.partner'])._evaluate_single_portal_tenant

        def faulty_eval(self_partner, p):
            if p.id == partner_1.id:
                raise Exception("Simulated unexpected failure")
            return orig_eval(self_partner, p)

        with patch.object(type(self.env['res.partner']), '_evaluate_single_portal_tenant', faulty_eval):
            self.env['res.partner']._cron_cleanup_expired_portal_tenants()

        # Partner 2's user should be processed and archived normally despite Partner 1's exception
        self.assertFalse(user_2.active, "Partner 2 must be archived despite Partner 1 error.")

    def test_28_property_manager_contract_activation_creates_activity_without_email(self):
        """A property manager (non-superuser) can activate a contract for a tenant without email;
        portal provisioning succeeds without placeholder user, and creates a follow-up activity
        assigned to the branch manager."""
        # 1. Tenant without usable email
        tenant_no_email = self.env['res.partner'].create({
            'name': 'No Email Tenant For PM Activation',
            'email': False,
        })
        unit = self.env['edara.unit'].create({
            'name': 'LC-PM-Activation',
            'code': 'PM-ACT',
            'building_id': self.building.id,
            'area': 110.0,
        })
        today = fields.Date.today()
        contract = self.env['edara.lease.contract'].create({
            'unit_id': unit.id,
            'tenant_id': tenant_no_email.id,
            'start_date': today,
            'end_date': today + timedelta(days=365),
            'rent_amount': 1000,
            'deposit_required': False,
        })
        self.assertEqual(contract.state, 'draft')

        # 2. Activate contract as property manager (non-superuser)
        contract.with_user(self.property_manager_user).action_activate()

        # 3. Confirms activation succeeds
        self.assertEqual(contract.state, 'active')

        # 4. Confirms portal provisioning does not create a placeholder account
        linked_users = self.env['res.users'].sudo().search([('partner_id', '=', tenant_no_email.id)])
        self.assertFalse(linked_users, "No placeholder portal user should be created for email-less tenant.")

        # 5. Confirms the expected follow-up activity exists and is assigned to the intended staff user
        activity = tenant_no_email.activity_ids.filtered(lambda a: a.summary == "Portal Provisioning: Missing Email")
        self.assertTrue(activity, "Follow-up activity for missing email must be created.")
        self.assertEqual(activity.user_id, self.branch_manager_user, "Activity must be assigned to the branch manager.")

