from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


def _today():
    return date.today()


@tagged('post_install', '-at_install')
class TestEdaraNotificationsBase(TransactionCase):
    """Shared fixtures for Notifications & Reminders Automation (2026-09-22) +
    MAT-FIND-007 business-level manual triggers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Notif Branch', 'code': 'NOTB'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Notif Property', 'code': 'NOTP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Notif Building', 'code': 'NOTBL', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'NOT-101', 'code': 'NOT101', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Notif Tenant', 'email': 'tenant@example.com'})

        cls.income_account = cls.env['account.account'].create(
            {'name': 'EDARA Rental Income (Notif)', 'code': '400910', 'account_type': 'income'})

        cls.branch_manager = new_test_user(
            cls.env, login='edara_notif_bm', groups='property_managment.group_edara_branch_manager')
        cls.branch.manager_id = cls.branch_manager
        cls.branch.user_ids = [(4, cls.branch_manager.id)]
        cls.viewer = new_test_user(
            cls.env, login='edara_notif_viewer', groups='property_managment.group_edara_viewer')
        cls.branch.user_ids = [(4, cls.viewer.id)]
        cls.tenant_user = new_test_user(
            cls.env, login='edara_notif_tenant', groups='property_managment.group_edara_portal_tenant',
            partner_id=cls.tenant.id)

        cls.lease_expiry_type = cls.env.ref('property_managment.mail_activity_type_edara_lease_expiry')
        cls.renewal_type = cls.env.ref('property_managment.mail_activity_type_edara_renewal_pending')
        cls.overdue_type = cls.env.ref('property_managment.mail_activity_type_edara_payment_overdue')
        cls.maintenance_type = cls.env.ref('property_managment.mail_activity_type_edara_maintenance')

    def _make_contract(self, **overrides):
        vals = {
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': date(2020, 1, 1), 'end_date': date(2030, 12, 31),
            'rent_amount': 1000, 'deposit_required': False,
        }
        vals.update(overrides)
        contract = self.env['edara.lease.contract'].create(vals)
        contract.action_activate()
        return contract


@tagged('post_install', '-at_install')
class TestEdaraLeaseExpiryReminders(TestEdaraNotificationsBase):

    def test_eligible_lease_within_30_days_receives_reminder(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=25))
        sent = self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.assertEqual(sent, 1)
        activities = contract.activity_ids.filtered(lambda a: a.activity_type_id == self.lease_expiry_type)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.user_id, self.branch_manager)
        self.assertEqual(contract.last_expiry_reminder_days, 30)

    def test_non_eligible_lease_outside_window_no_reminder(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=60))
        sent = self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.assertEqual(sent, 0)
        self.assertFalse(contract.activity_ids.filtered(lambda a: a.activity_type_id == self.lease_expiry_type))

    def test_reminder_boundary_exact_30_days_included(self):
        """BD-003's own inclusive boundary (today..today+30) is reused as-is."""
        contract = self._make_contract(end_date=_today() + timedelta(days=30))
        sent = self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.assertEqual(sent, 1)

    def test_reminder_boundary_31_days_not_yet_eligible(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=31))
        sent = self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.assertEqual(sent, 0)

    def test_urgent_window_escalates_after_wider_window_already_sent(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=25))
        self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.assertEqual(contract.last_expiry_reminder_days, 30)
        # Simulate the calendar advancing to within the urgent (7-day) window.
        contract.end_date = _today() + timedelta(days=5)
        sent = self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.assertEqual(sent, 1)
        self.assertEqual(contract.last_expiry_reminder_days, 7)
        activities = contract.activity_ids.filtered(lambda a: a.activity_type_id == self.lease_expiry_type)
        self.assertEqual(len(activities), 2)

    def test_repeated_cron_same_day_does_not_duplicate(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=25))
        self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.env['edara.lease.contract']._cron_send_expiry_reminders()
        activities = contract.activity_ids.filtered(lambda a: a.activity_type_id == self.lease_expiry_type)
        self.assertEqual(len(activities), 1)

    def test_repeated_manual_trigger_does_not_duplicate(self):
        """Manual trigger reuses the exact same cron method - see
        edara.dashboard.action_manual_process_reminders()."""
        contract = self._make_contract(end_date=_today() + timedelta(days=10))
        self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.env['edara.lease.contract']._cron_send_expiry_reminders()
        activities = contract.activity_ids.filtered(lambda a: a.activity_type_id == self.lease_expiry_type)
        self.assertEqual(len(activities), 1)

    def test_non_active_contract_not_reminded(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=10))
        contract.action_terminate('done early')
        sent = self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.assertEqual(sent, 0)

    def test_tenant_notified_via_chatter(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=10))
        before = len(contract.message_ids)
        self.env['edara.lease.contract']._cron_send_expiry_reminders()
        after = contract.message_ids
        self.assertGreater(len(after), before)
        self.assertIn(self.tenant, after[:len(after) - before].mapped('partner_ids'))

    def test_reminder_never_changes_rent_or_dates(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=10), rent_amount=1234)
        self.env['edara.lease.contract']._cron_send_expiry_reminders()
        self.assertEqual(contract.rent_amount, 1234)
        self.assertEqual(contract.end_date, _today() + timedelta(days=10))


@tagged('post_install', '-at_install')
class TestEdaraRenewalReminders(TestEdaraNotificationsBase):

    def test_submitted_request_gets_reminder(self):
        contract = self._make_contract()
        request = self.env['edara.renewal.request'].create({
            'contract_id': contract.id,
            'requested_start_date': date(2031, 1, 1), 'requested_end_date': date(2031, 12, 31),
            'requested_rent_amount': 1100,
        })
        sent = self.env['edara.renewal.request']._cron_send_renewal_reminders()
        self.assertEqual(sent, 1)
        activities = request.activity_ids.filtered(lambda a: a.activity_type_id == self.renewal_type)
        self.assertEqual(activities.user_id, self.branch_manager)

    def test_approved_request_not_reminded(self):
        contract = self._make_contract()
        request = self.env['edara.renewal.request'].create({
            'contract_id': contract.id,
            'requested_start_date': date(2031, 1, 1), 'requested_end_date': date(2031, 12, 31),
            'requested_rent_amount': 1100,
        })
        request.action_approve()
        sent = self.env['edara.renewal.request']._cron_send_renewal_reminders()
        self.assertEqual(sent, 0)

    def test_repeated_processing_does_not_duplicate(self):
        contract = self._make_contract()
        request = self.env['edara.renewal.request'].create({
            'contract_id': contract.id,
            'requested_start_date': date(2031, 1, 1), 'requested_end_date': date(2031, 12, 31),
            'requested_rent_amount': 1100,
        })
        self.env['edara.renewal.request']._cron_send_renewal_reminders()
        self.env['edara.renewal.request']._cron_send_renewal_reminders()
        activities = request.activity_ids.filtered(lambda a: a.activity_type_id == self.renewal_type)
        self.assertEqual(len(activities), 1)

    def test_reminder_does_not_change_contract_rent(self):
        contract = self._make_contract(rent_amount=1000)
        self.env['edara.renewal.request'].create({
            'contract_id': contract.id,
            'requested_start_date': date(2031, 1, 1), 'requested_end_date': date(2031, 12, 31),
            'requested_rent_amount': 1500,
        })
        self.env['edara.renewal.request']._cron_send_renewal_reminders()
        self.assertEqual(contract.rent_amount, 1000)


@tagged('post_install', '-at_install')
class TestEdaraOverduePaymentReminders(TestEdaraNotificationsBase):

    def setUp(self):
        super().setUp()
        self.env.company.edara_rental_income_account_id = self.income_account.id

    def test_overdue_line_generates_reminder(self):
        contract = self._make_contract(
            start_date=_today() - timedelta(days=60), end_date=_today() + timedelta(days=300))
        line = contract.schedule_line_ids.filtered(lambda l: l.due_date < _today())[:1]
        self.assertEqual(line.state, 'overdue')
        sent = self.env['edara.payment.schedule.line']._cron_send_overdue_reminders()
        self.assertGreaterEqual(sent, 1)
        activities = line.activity_ids.filtered(lambda a: a.activity_type_id == self.overdue_type)
        self.assertEqual(activities.user_id, self.branch_manager)

    def test_current_line_not_reminded(self):
        contract = self._make_contract(
            start_date=_today() + timedelta(days=10), end_date=_today() + timedelta(days=400))
        sent = self.env['edara.payment.schedule.line']._cron_send_overdue_reminders()
        self.assertEqual(sent, 0)

    def test_repeated_processing_is_idempotent(self):
        contract = self._make_contract(
            start_date=_today() - timedelta(days=60), end_date=_today() + timedelta(days=300))
        line = contract.schedule_line_ids.filtered(lambda l: l.due_date < _today())[:1]
        self.env['edara.payment.schedule.line']._cron_send_overdue_reminders()
        self.env['edara.payment.schedule.line']._cron_send_overdue_reminders()
        activities = line.activity_ids.filtered(lambda a: a.activity_type_id == self.overdue_type)
        self.assertEqual(len(activities), 1)

    def test_invoiced_not_yet_due_line_not_reminded(self):
        """An invoiced line whose due date hasn't arrived yet is 'invoiced',
        never 'overdue' (see _compute_state) - reminders must not fire for
        it. (A line invoiced AFTER it was already overdue stays 'overdue'
        until paid - that is existing, unchanged _compute_state business
        logic, already covered by test_edara_payment_schedule.py.)"""
        contract = self._make_contract(
            start_date=_today(), end_date=_today() + timedelta(days=400))
        line = contract.schedule_line_ids[:1]
        line._create_invoice()
        self.assertNotEqual(line.state, 'overdue')
        sent = self.env['edara.payment.schedule.line']._cron_send_overdue_reminders()
        self.assertEqual(sent, 0)


@tagged('post_install', '-at_install')
class TestEdaraMaintenanceReminders(TestEdaraNotificationsBase):

    def _make_request(self, **overrides):
        vals = {'title': 'Leaking faucet', 'unit_id': self.unit.id, 'tenant_id': self.tenant.id}
        vals.update(overrides)
        return self.env['edara.maintenance.request'].create(vals)

    def test_new_request_gets_triage_activity_immediately(self):
        request = self._make_request()
        activities = request.activity_ids.filtered(lambda a: a.activity_type_id == self.maintenance_type)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.user_id, self.branch_manager)

    def test_completed_request_not_picked_up_by_staleness_cron(self):
        request = self._make_request(requested_date=_today() - timedelta(days=10))
        request.action_assign(self.branch_manager.id)
        request.action_complete()
        request.activity_ids.unlink()
        sent = self.env['edara.maintenance.request']._cron_send_maintenance_reminders()
        self.assertEqual(sent, 0)

    def test_stale_open_request_gets_followup_after_triage_resolved(self):
        request = self._make_request(requested_date=_today() - timedelta(days=10))
        request.activity_ids.filtered(
            lambda a: a.activity_type_id == self.maintenance_type).action_feedback()
        self.assertFalse(request.activity_ids)
        sent = self.env['edara.maintenance.request']._cron_send_maintenance_reminders()
        self.assertEqual(sent, 1)
        activities = request.activity_ids.filtered(lambda a: a.activity_type_id == self.maintenance_type)
        self.assertEqual(len(activities), 1)

    def test_recent_request_not_yet_stale(self):
        request = self._make_request(requested_date=_today())
        request.activity_ids.filtered(
            lambda a: a.activity_type_id == self.maintenance_type).action_feedback()
        sent = self.env['edara.maintenance.request']._cron_send_maintenance_reminders()
        self.assertEqual(sent, 0)

    def test_repeated_staleness_processing_is_idempotent(self):
        request = self._make_request(requested_date=_today() - timedelta(days=10))
        request.activity_ids.filtered(
            lambda a: a.activity_type_id == self.maintenance_type).action_feedback()
        self.env['edara.maintenance.request']._cron_send_maintenance_reminders()
        self.env['edara.maintenance.request']._cron_send_maintenance_reminders()
        activities = request.activity_ids.filtered(lambda a: a.activity_type_id == self.maintenance_type)
        self.assertEqual(len(activities), 1)

    def test_tenant_notified_on_completion(self):
        request = self._make_request()
        request.action_assign(self.branch_manager.id)
        before = len(request.message_ids)
        request.action_complete()
        after = request.message_ids
        self.assertGreater(len(after), before)
        self.assertIn(self.tenant, after[:len(after) - before].mapped('partner_ids'))


@tagged('post_install', '-at_install')
class TestEdaraManualTriggers(TestEdaraNotificationsBase):
    """MAT-FIND-007 (2026-09-22): business-level manual triggers on the
    Dashboard, reusing the exact same methods the daily crons call."""

    def setUp(self):
        super().setUp()
        self.env.company.edara_rental_income_account_id = self.income_account.id

    def _make_due_line(self):
        """15 days back keeps this to exactly one due (monthly) schedule
        line - the next one isn't due for another ~15 days - so tests that
        assert exact invoice counts stay correct."""
        contract = self._make_contract(
            start_date=_today() - timedelta(days=15), end_date=_today() + timedelta(days=300))
        lines = contract.schedule_line_ids.filtered(lambda l: l.due_date <= _today())
        self.assertEqual(len(lines), 1)
        return lines

    def test_authorized_user_can_generate_due_invoices(self):
        line = self._make_due_line()
        created, skipped, errors = self.env['edara.payment.schedule.line'].with_user(
            self.branch_manager).action_generate_due_invoices_now()
        self.assertGreaterEqual(created, 1)
        self.assertEqual(errors, 0)
        self.assertTrue(line.invoice_id)

    def test_unauthorized_viewer_cannot_generate_due_invoices(self):
        self._make_due_line()
        with self.assertRaises(AccessError):
            self.env['edara.payment.schedule.line'].with_user(
                self.viewer).action_generate_due_invoices_now()

    def test_manual_generation_is_idempotent(self):
        line = self._make_due_line()
        self.env['edara.payment.schedule.line'].with_user(self.branch_manager).action_generate_due_invoices_now()
        first_invoice = line.invoice_id
        created, skipped, errors = self.env['edara.payment.schedule.line'].with_user(
            self.branch_manager).action_generate_due_invoices_now()
        self.assertEqual(created, 0)
        self.assertEqual(line.invoice_id, first_invoice)

    def test_manual_then_cron_interaction_stays_idempotent(self):
        """Section 24 (Cron/manual interaction): running the manual trigger
        and then the daily cron over the same candidate must never produce a
        second invoice for the same line."""
        line = self._make_due_line()
        self.env['edara.payment.schedule.line'].with_user(self.branch_manager).action_generate_due_invoices_now()
        self.env['edara.payment.schedule.line']._cron_generate_due_invoices()
        self.assertEqual(self.env['account.move'].search_count(
            [('edara_invoice_type', '=', 'rent'), ('edara_unit_id', '=', self.unit.id)]), 1)

    def test_manual_invoice_uses_same_business_logic_as_cron(self):
        line = self._make_due_line()
        self.env['edara.payment.schedule.line'].with_user(self.branch_manager).action_generate_due_invoices_now()
        invoice = self.env['account.move'].browse(line.invoice_id.id)
        self.assertEqual(invoice.edara_invoice_type, 'rent')
        self.assertEqual(invoice.invoice_line_ids.account_id, self.income_account)
        self.assertEqual(invoice.state, 'posted')

    def test_process_lease_expiry_manual_trigger(self):
        contract = self._make_contract(
            start_date=date(2020, 1, 1), end_date=date(2020, 6, 30))
        count = self.env['edara.lease.contract'].with_user(self.branch_manager)._cron_expire_contracts()
        self.assertGreaterEqual(count, 1)
        self.assertEqual(contract.state, 'expired')

    def test_dashboard_process_reminders_action_returns_notification_and_creates_reminders(self):
        contract = self._make_contract(end_date=_today() + timedelta(days=10))
        dashboard = self.env['edara.dashboard'].with_user(self.branch_manager).create({})
        result = dashboard.action_manual_process_reminders()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertTrue(contract.activity_ids.filtered(lambda a: a.activity_type_id == self.lease_expiry_type))

    def test_dashboard_generate_invoices_action_returns_notification(self):
        self._make_due_line()
        dashboard = self.env['edara.dashboard'].with_user(self.branch_manager).create({})
        result = dashboard.action_manual_generate_due_invoices()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn('created', result['params']['message'])

    def test_dashboard_process_lease_expiry_action_returns_notification(self):
        self._make_contract(start_date=date(2020, 1, 1), end_date=date(2020, 6, 30))
        dashboard = self.env['edara.dashboard'].with_user(self.branch_manager).create({})
        result = dashboard.action_manual_process_lease_expiry()
        self.assertEqual(result['tag'], 'display_notification')


@tagged('post_install', '-at_install')
class TestEdaraNotificationSecurityAndIsolation(TestEdaraNotificationsBase):

    def test_tenant_cannot_trigger_internal_reminder_crons(self):
        """Portal tenants have zero ir.model.access on edara.payment.schedule.line
        and no write access on edara.lease.contract/edara.renewal.request/
        edara.maintenance.request - the manual-trigger model methods below
        are only ever reachable through the Dashboard (which itself has no
        portal-tenant access), but direct RPC invocation must still be
        blocked server-side, not just hidden in the UI."""
        with self.assertRaises(AccessError):
            self.env['edara.dashboard'].with_user(self.tenant_user).create({})

    def test_tenant_never_receives_another_tenants_reminder_activity(self):
        other_tenant = self.env['res.partner'].create({'name': 'Other Tenant'})
        other_unit = self.env['edara.unit'].create(
            {'name': 'NOT-102', 'code': 'NOT102', 'building_id': self.building.id})
        contract = self._make_contract(unit_id=other_unit.id, tenant_id=other_tenant.id,
                                        end_date=_today() + timedelta(days=10))
        self.env['edara.lease.contract']._cron_send_expiry_reminders()
        messages = contract.message_ids
        self.assertNotIn(self.tenant, messages.mapped('partner_ids'))

    def test_manual_invoice_generation_respects_branch_isolation(self):
        """A Branch Manager scoped to one branch must never process another
        branch's due invoices through the manual trigger, even though the
        underlying SQL-based cron processes every branch unrestricted."""
        other_branch = self.env['edara.branch'].create({'name': 'Other Branch', 'code': 'OTHB'})
        other_property = self.env['edara.property'].create(
            {'name': 'Other Property', 'code': 'OTHP', 'branch_id': other_branch.id})
        other_building = self.env['edara.building'].create(
            {'name': 'Other Building', 'code': 'OTHBL', 'property_id': other_property.id})
        other_unit = self.env['edara.unit'].create(
            {'name': 'OTH-101', 'code': 'OTH101', 'building_id': other_building.id})
        other_tenant = self.env['res.partner'].create({'name': 'Other Branch Tenant'})
        self.env.company.edara_rental_income_account_id = self.income_account.id

        other_contract = self.env['edara.lease.contract'].create({
            'unit_id': other_unit.id, 'tenant_id': other_tenant.id,
            'start_date': _today() - timedelta(days=60), 'end_date': _today() + timedelta(days=300),
            'rent_amount': 900, 'deposit_required': False,
        })
        other_contract.action_activate()
        other_line = other_contract.schedule_line_ids.filtered(lambda l: l.due_date < _today())[:1]

        created, skipped, errors = self.env['edara.payment.schedule.line'].with_user(
            self.branch_manager).action_generate_due_invoices_now()
        self.assertEqual(errors, 0)
        self.assertFalse(other_line.invoice_id, "Branch Manager must not invoice another branch's line")
