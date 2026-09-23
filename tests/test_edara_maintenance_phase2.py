from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.exceptions import AccessError
from odoo.fields import Date
from odoo.tests import HttpCase, TransactionCase, tagged


class TestEdaraMaintenancePhase2Base(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Nablus Branch', 'code': 'NBL'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Nablus Complex', 'code': 'NBC', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Building A', 'code': 'A', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'A-201', 'code': '201', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Fadi Hamdan'})
        cls.vendor = cls.env['res.partner'].create({'name': 'ACME Elevator Co'})
        cls.staff = cls.env['res.users'].create({
            'name': 'Maintenance Staff', 'login': 'edara_p4_staff', 'email': 'p4staff@example.com',
        })

    def _make_request(self, **overrides):
        vals = {'title': 'Broken pipe', 'unit_id': self.unit.id, 'tenant_id': self.tenant.id}
        vals.update(overrides)
        return self.env['edara.maintenance.request'].create(vals)

    def _backdate_create_date(self, record, hours_ago):
        self.env.cr.execute(
            "UPDATE edara_maintenance_request SET create_date = create_date - interval '%s hours' WHERE id = %s",
            (hours_ago, record.id))
        record.invalidate_recordset()


@tagged('post_install', '-at_install')
class TestEdaraVendorManagement(TestEdaraMaintenancePhase2Base):

    def test_vendor_optional_on_creation(self):
        request = self._make_request()
        self.assertFalse(request.vendor_id)

    def test_completion_does_not_require_vendor(self):
        """Preserved existing business rule (ticket §7)."""
        request = self._make_request()
        request.action_assign(self.staff.id)
        request.action_start()
        request.action_complete()
        self.assertEqual(request.state, 'done')

    def test_is_edara_vendor_flag(self):
        self.assertFalse(self.vendor.is_edara_vendor)
        self._make_request(vendor_id=self.vendor.id)
        self.assertTrue(self.vendor.is_edara_vendor)

    def test_vendor_stats_counts_and_isolation(self):
        other_vendor = self.env['res.partner'].create({'name': 'Other Vendor'})
        self._make_request(vendor_id=self.vendor.id)
        r2 = self._make_request(vendor_id=self.vendor.id, title='Second job')
        r2.action_assign(self.staff.id)
        r2.action_start()
        r2.action_complete()
        self._make_request(vendor_id=other_vendor.id, title='Unrelated job')

        self.assertEqual(self.vendor.edara_vendor_request_count, 2)
        self.assertEqual(self.vendor.edara_vendor_open_request_count, 1)
        self.assertEqual(other_vendor.edara_vendor_request_count, 1)
        self.assertEqual(self.vendor.edara_vendor_last_service_date, r2.completed_date)

    def test_vendor_maintenance_cost_distinct_from_estimated_cost(self):
        """ticket §9: estimated cost and actual Vendor Bill amount must
        remain separate concepts, never combined into one number."""
        income_account = self.env['account.account'].create(
            {'name': 'Maint Expense P4', 'code': '601998', 'account_type': 'expense'})
        self.env.company.edara_maintenance_expense_account_id = income_account.id
        request = self._make_request(vendor_id=self.vendor.id, cost=500)
        bill = request.action_create_vendor_bill()
        bill.action_post()
        self.assertEqual(request.cost, 500)
        self.assertAlmostEqual(self.vendor.edara_vendor_maintenance_cost_total, 500)


@tagged('post_install', '-at_install')
class TestEdaraSlaTracking(TestEdaraMaintenancePhase2Base):

    def test_first_response_at_set_once_on_first_assign(self):
        request = self._make_request()
        self.assertFalse(request.first_response_at)
        request.action_assign(self.staff.id)
        first_stamp = request.first_response_at
        self.assertTrue(first_stamp)
        # A later re-assignment (still 'assigned' -> reassign) must not move it.
        other_staff = self.env['res.users'].create({'name': 'Other Staff', 'login': 'edara_p4_staff2'})
        request.action_assign(other_staff.id)
        self.assertEqual(request.first_response_at, first_stamp)

    def test_resolved_at_set_once_on_completion(self):
        request = self._make_request()
        request.action_assign(self.staff.id)
        request.action_start()
        self.assertFalse(request.resolved_at)
        request.action_complete()
        self.assertTrue(request.resolved_at)

    def test_response_and_resolution_hours_computed(self):
        request = self._make_request()
        self._backdate_create_date(request, hours_ago=5)
        request.action_assign(self.staff.id)
        self.assertAlmostEqual(request.response_hours, 5, delta=0.1)
        request.action_start()
        request.action_complete()
        self.assertGreaterEqual(request.resolution_hours, request.response_hours)

    def test_sla_state_within_when_recent(self):
        self.branch.sla_resolution_hours = 72
        request = self._make_request()
        self.assertEqual(request.sla_state, 'within')

    def test_sla_state_at_risk_past_threshold(self):
        self.branch.sla_resolution_hours = 72
        request = self._make_request()
        self._backdate_create_date(request, hours_ago=60)  # 60/72 = 83% > 80% threshold
        self.assertEqual(request.sla_state, 'at_risk')

    def test_sla_state_breached_past_target(self):
        self.branch.sla_resolution_hours = 72
        request = self._make_request()
        self._backdate_create_date(request, hours_ago=100)
        self.assertEqual(request.sla_state, 'breached')

    def test_sla_state_disabled_when_target_is_zero(self):
        self.branch.sla_resolution_hours = 0
        request = self._make_request()
        self._backdate_create_date(request, hours_ago=1000)
        self.assertEqual(request.sla_state, 'within')

    def test_sla_state_manual_override_not_possible(self):
        """ticket §12: sla_state is derived only, never a plain writable field."""
        self.assertFalse(self.env['edara.maintenance.request']._fields['sla_state'].store)

    def test_completed_request_sla_state_reflects_actual_resolution(self):
        self.branch.sla_resolution_hours = 72
        request = self._make_request()
        request.action_assign(self.staff.id)
        request.action_start()
        request.action_complete()
        # resolution_hours is a STORED field, fixed the moment action_complete()
        # ran - a raw-SQL backdate of create_date afterward (bypassing the
        # ORM, so no recompute is triggered) must not retroactively change a
        # request's already-settled sla_state, unlike an OPEN request's
        # sla_state (which is live/non-stored and does react to elapsed time).
        self._backdate_create_date(request, hours_ago=100)
        self.assertEqual(request.sla_state, 'within')

    def test_sla_notification_idempotent(self):
        self.branch.sla_resolution_hours = 24
        request = self._make_request()
        self._backdate_create_date(request, hours_ago=100)
        sent_first = self.env['edara.maintenance.request']._cron_send_sla_notifications()
        sent_second = self.env['edara.maintenance.request']._cron_send_sla_notifications()
        self.assertEqual(sent_first, 1)
        self.assertEqual(sent_second, 0)
        activity_type = self.env.ref('property_managment.mail_activity_type_edara_maintenance_sla')
        self.assertEqual(len(request.activity_ids.filtered(lambda a: a.activity_type_id == activity_type)), 1)

    def test_sla_notification_skips_completed_requests(self):
        self.branch.sla_resolution_hours = 24
        request = self._make_request()
        request.action_assign(self.staff.id)
        request.action_start()
        request.action_complete()
        self._backdate_create_date(request, hours_ago=1000)
        sent = self.env['edara.maintenance.request']._cron_send_sla_notifications()
        self.assertEqual(sent, 0)

    def test_sla_notification_skips_branches_without_target(self):
        self.branch.sla_resolution_hours = 0
        request = self._make_request()
        self._backdate_create_date(request, hours_ago=1000)
        sent = self.env['edara.maintenance.request']._cron_send_sla_notifications()
        self.assertEqual(sent, 0)


@tagged('post_install', '-at_install')
class TestEdaraRecurringMaintenance(TestEdaraMaintenancePhase2Base):

    def _make_recurring(self, **overrides):
        vals = {
            'name': 'Elevator Servicing', 'unit_id': self.unit.id, 'frequency': 'monthly',
            'next_date': Date.today(),
        }
        vals.update(overrides)
        return self.env['edara.recurring.maintenance'].create(vals)

    def test_recurring_definition_creation_requires_unit(self):
        with self.assertRaises(Exception):
            self.env['edara.recurring.maintenance'].create({
                'name': 'No Unit', 'frequency': 'monthly', 'next_date': Date.today(),
            })

    def test_inactive_definition_not_processed(self):
        definition = self._make_recurring(active=False)
        created = self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(created, 0)
        self.assertFalse(definition.generated_request_ids)

    def test_generation_creates_request_on_due_date(self):
        today = Date.today()
        definition = self._make_recurring(vendor_id=self.vendor.id, category='hvac', next_date=today)
        created = self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(created, 1)
        self.assertEqual(len(definition.generated_request_ids), 1)
        request = definition.generated_request_ids
        self.assertEqual(request.unit_id, self.unit)
        self.assertEqual(request.vendor_id, self.vendor)
        self.assertEqual(request.category, 'hvac')
        self.assertEqual(request.edara_recurring_id, definition)
        self.assertEqual(request.occurrence_date, today)
        self.assertEqual(request.state, 'new')

    def test_generation_not_due_yet_produces_nothing(self):
        self._make_recurring(next_date=Date.today() + relativedelta(days=1))
        created = self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(created, 0)

    def test_recurrence_advancement_monthly(self):
        today = Date.today()
        definition = self._make_recurring(frequency='monthly', next_date=today)
        self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(definition.next_date, today + relativedelta(months=1))

    def test_recurrence_advancement_quarterly(self):
        today = Date.today()
        definition = self._make_recurring(frequency='quarterly', next_date=today)
        self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(definition.next_date, today + relativedelta(months=3))

    def test_recurrence_advancement_semi_annual(self):
        today = Date.today()
        definition = self._make_recurring(frequency='semi_annual', next_date=today)
        self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(definition.next_date, today + relativedelta(months=6))

    def test_recurrence_advancement_yearly(self):
        today = Date.today()
        definition = self._make_recurring(frequency='yearly', next_date=today)
        self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(definition.next_date, today + relativedelta(years=1))

    def test_running_cron_twice_does_not_duplicate(self):
        self._make_recurring(next_date=Date.today())
        first_run = self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        second_run = self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(first_run, 1)
        self.assertEqual(second_run, 0)
        self.assertEqual(self.env['edara.maintenance.request'].search_count(
            [('title', '=', 'Recurring: Elevator Servicing')]), 1)

    def test_multiple_recurrence_cycles_do_not_mutate_history(self):
        today = Date.today()
        definition = self._make_recurring(next_date=today)
        self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        first_request = definition.generated_request_ids
        first_request.action_assign(self.staff.id)
        # A distinct, already-due occurrence date for the second cycle
        # (never the same value as the first, which would hit the unique
        # constraint's idempotent-skip branch instead of generating a
        # second, genuinely different occurrence).
        second_occurrence = today - relativedelta(months=1)
        definition.next_date = second_occurrence
        self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(len(definition.generated_request_ids), 2)
        self.assertEqual(first_request.state, 'assigned')  # untouched by the second run
        self.assertEqual(first_request.occurrence_date, today)

    def test_database_constraint_blocks_duplicate_occurrence(self):
        today = Date.today()
        definition = self._make_recurring(next_date=today)
        self.env['edara.maintenance.request'].create({
            'title': 'Manual dup', 'unit_id': self.unit.id,
            'edara_recurring_id': definition.id, 'occurrence_date': today,
        })
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['edara.maintenance.request'].create({
                    'title': 'Manual dup 2', 'unit_id': self.unit.id,
                    'edara_recurring_id': definition.id, 'occurrence_date': today,
                })

    def test_recurring_generated_request_gets_triage_activity(self):
        """Generated requests go through the same create() override as any
        other request - Phase 1's triage activity is not bypassed."""
        self._make_recurring()
        self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        request = self.env['edara.maintenance.request'].search([('title', '=', 'Recurring: Elevator Servicing')])
        activity_type = self.env.ref('property_managment.mail_activity_type_edara_maintenance')
        self.assertTrue(request.activity_ids.filtered(lambda a: a.activity_type_id == activity_type))

    def test_branch_isolation(self):
        other_branch = self.env['edara.branch'].create({'name': 'Other Branch P4', 'code': 'OBP4'})
        other_property = self.env['edara.property'].create(
            {'name': 'Other Property P4', 'code': 'OPP4', 'branch_id': other_branch.id})
        other_building = self.env['edara.building'].create(
            {'name': 'Other Building P4', 'code': 'OBLP4', 'property_id': other_property.id})
        other_unit = self.env['edara.unit'].create(
            {'name': 'Other Unit P4', 'code': 'OUP4', 'building_id': other_building.id})
        self._make_recurring()
        other_definition = self.env['edara.recurring.maintenance'].create({
            'name': 'Other Branch Recurring', 'unit_id': other_unit.id,
            'frequency': 'monthly', 'next_date': date(2026, 1, 1),
        })
        manager = self.env['res.users'].create({
            'name': 'Branch Mgr P4', 'login': 'edara_p4_bm',
            'group_ids': [(6, 0, [self.env.ref('property_managment.group_edara_branch_manager').id])],
        })
        self.branch.user_ids = [(4, manager.id)]
        visible = self.env['edara.recurring.maintenance'].with_user(manager).search([])
        self.assertNotIn(other_definition.id, visible.ids)


@tagged('post_install', '-at_install')
class TestEdaraMaintenancePhase2Regression(TestEdaraMaintenancePhase2Base):
    """Confirms Phase 1 automation and the existing lifecycle are untouched."""

    def test_full_lifecycle_still_works(self):
        request = self._make_request()
        request.action_assign(self.staff.id)
        request.action_start()
        request.action_complete()
        self.assertEqual(request.state, 'done')
        self.assertTrue(request.completed_date)

    def test_staleness_cron_still_works_independently_of_sla_cron(self):
        request = self._make_request()
        # A fresh request already has an open triage activity of the SAME
        # type _cron_send_maintenance_reminders() itself checks for (Phase 1
        # design, unchanged) - it must be cleared first to simulate staff
        # having triaged it, or the staleness cron correctly considers it
        # already-notified and does nothing.
        request.activity_ids.action_feedback()
        self.env.cr.execute(
            "UPDATE edara_maintenance_request SET requested_date = requested_date - interval '4 days' WHERE id = %s",
            (request.id,))
        request.invalidate_recordset()
        sent = self.env['edara.maintenance.request']._cron_send_maintenance_reminders()
        self.assertEqual(sent, 1)

    def test_negative_cost_still_blocked(self):
        with self.assertRaises(Exception):
            self._make_request(cost=-10)


@tagged('post_install', '-at_install')
class TestEdaraMaintenancePhase2Portal(HttpCase):
    """Phase 3 portal regression + Phase 4 tenant-visibility boundaries."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Portal P4 Branch', 'code': 'PP4B'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Portal P4 Property', 'code': 'PP4P', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Portal P4 Building', 'code': 'PP4BL', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'PP4-101', 'code': 'PP4101', 'building_id': cls.building.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'Portal P4 Vendor'})
        portal_group = cls.env.ref('property_managment.group_edara_portal_tenant')
        cls.partner = cls.env['res.partner'].create({'name': 'Portal P4 Tenant'})
        cls.user = cls.env['res.users'].create({
            'name': 'Portal P4 Tenant', 'login': 'edara_p4_tenant', 'password': 'edara_p4_tenant',
            'partner_id': cls.partner.id, 'group_ids': [(6, 0, [portal_group.id])],
        })
        cls.contract = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit.id, 'tenant_id': cls.partner.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 1000,
            'deposit_required': False,
        })
        cls.contract.action_activate()

    def test_tenant_own_maintenance_request_still_visible(self):
        """Phase 3 regression - unrelated to recurring/vendor/SLA."""
        request = self.env['edara.maintenance.request'].create({
            'title': 'Tenant filed this', 'unit_id': self.unit.id, 'tenant_id': self.partner.id,
        })
        self.authenticate('edara_p4_tenant', 'edara_p4_tenant')
        response = self.url_open('/my/maintenance/%d' % request.id)
        self.assertIn('Tenant filed this', response.text)

    def test_recurring_generated_request_without_tenant_not_shown_by_default(self):
        definition = self.env['edara.recurring.maintenance'].create({
            'name': 'Portal P4 Elevator', 'unit_id': self.unit.id,
            'frequency': 'monthly', 'next_date': Date.today(),
        })
        self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.authenticate('edara_p4_tenant', 'edara_p4_tenant')
        response = self.url_open('/my/maintenance')
        self.assertNotIn('Portal P4 Elevator', response.text)

    def test_tenant_maintenance_detail_never_exposes_vendor_or_sla(self):
        request = self.env['edara.maintenance.request'].create({
            'title': 'Vendor Leak Test', 'unit_id': self.unit.id, 'tenant_id': self.partner.id,
            'vendor_id': self.vendor.id, 'cost': 250,
        })
        self.authenticate('edara_p4_tenant', 'edara_p4_tenant')
        response = self.url_open('/my/maintenance/%d' % request.id)
        self.assertNotIn('Portal P4 Vendor', response.text)
        self.assertNotIn('SLA', response.text)
        self.assertNotIn('250', response.text)

    def test_tenant_has_no_access_to_recurring_maintenance_model(self):
        definition = self.env['edara.recurring.maintenance'].create({
            'name': 'Config Not For Tenant', 'unit_id': self.unit.id,
            'frequency': 'monthly', 'next_date': date(2026, 1, 1),
        })
        with self.assertRaises(AccessError):
            definition.with_user(self.user).read(['name'])
