from datetime import date, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraLeaseContract(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Phase 6.4: 'RAM' collides with a real, legitimate branch already in
        # this shared dev database - use a test-only code.
        cls.branch = cls.env['edara.branch'].create({'name': 'Test Ramallah Branch', 'code': 'TRAM'})
        cls.property = cls.env['edara.property'].create({'name': 'Al-Irsal Complex', 'code': 'IRS', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create({'name': 'Building A', 'code': 'A', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'A-101', 'code': '101', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Ahmad Ali'})

    def _make_contract(self, **overrides):
        vals = {
            'unit_id': self.unit.id,
            'tenant_id': self.tenant.id,
            'start_date': date(2026, 1, 1),
            'end_date': date(2026, 12, 31),
            'rent_amount': 1500,
            'deposit_required': False,
        }
        vals.update(overrides)
        return self.env['edara.lease.contract'].create(vals)

    def test_end_date_must_be_after_start_date(self):
        with self.assertRaises(ValidationError):
            self._make_contract(start_date=date(2026, 6, 1), end_date=date(2026, 1, 1))

    def test_rent_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._make_contract(rent_amount=0)

    def test_activate_sets_unit_rented_and_tenant_flag(self):
        contract = self._make_contract()
        self.assertEqual(contract.name[:2], 'LC')
        contract.action_activate()
        self.assertEqual(contract.state, 'active')
        self.assertEqual(self.unit.occupancy_status, 'rented')
        self.assertTrue(self.tenant.is_edara_tenant)

    def test_cannot_activate_over_sold_unit(self):
        self.unit.occupancy_status = 'sold'
        contract = self._make_contract()
        with self.assertRaises(UserError):
            contract.action_activate()

    def test_cannot_manually_mark_unit_rented_without_active_contract(self):
        with self.assertRaises(ValidationError):
            self.unit.occupancy_status = 'rented'

    def test_overlap_prevented_between_two_active_contracts(self):
        contract_1 = self._make_contract()
        contract_1.action_activate()
        contract_2 = self._make_contract(tenant_id=self.tenant.id, start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        with self.assertRaises(ValidationError):
            contract_2.action_activate()

    # -- MAT-FIND-012 / Phase 10.1: end_date is the last occupied day (inclusive) --

    def test_overlap_adjacent_leases_are_allowed(self):
        """end_date is inclusive - a new lease may start the day AFTER the
        prior lease's end_date."""
        existing = self._make_contract(start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
        existing.action_activate()
        adjacent = self._make_contract(
            tenant_id=self.tenant.id, start_date=date(2026, 7, 1), end_date=date(2026, 12, 31))
        adjacent.action_activate()  # must not raise
        self.assertEqual(adjacent.state, 'active')

    def test_overlap_one_day_before_adjacent_is_blocked(self):
        """Both leases would occupy 30/06 (the existing one's last occupied day)."""
        existing = self._make_contract(start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
        existing.action_activate()
        overlapping = self._make_contract(
            tenant_id=self.tenant.id, start_date=date(2026, 6, 30), end_date=date(2026, 12, 31))
        with self.assertRaises(ValidationError):
            overlapping.action_activate()

    def test_overlap_exact_same_dates_blocked(self):
        existing = self._make_contract(start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
        existing.action_activate()
        same = self._make_contract(
            tenant_id=self.tenant.id, start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
        with self.assertRaises(ValidationError):
            same.action_activate()

    def test_overlap_new_lease_fully_inside_existing_blocked(self):
        existing = self._make_contract(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        existing.action_activate()
        inside = self._make_contract(
            tenant_id=self.tenant.id, start_date=date(2026, 3, 1), end_date=date(2026, 6, 1))
        with self.assertRaises(ValidationError):
            inside.action_activate()

    def test_overlap_existing_lease_fully_inside_new_blocked(self):
        existing = self._make_contract(start_date=date(2026, 3, 1), end_date=date(2026, 6, 1))
        existing.action_activate()
        outer = self._make_contract(
            tenant_id=self.tenant.id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        with self.assertRaises(ValidationError):
            outer.action_activate()

    def test_overlap_partial_overlap_blocked(self):
        existing = self._make_contract(start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
        existing.action_activate()
        partial = self._make_contract(
            tenant_id=self.tenant.id, start_date=date(2026, 4, 1), end_date=date(2026, 9, 30))
        with self.assertRaises(ValidationError):
            partial.action_activate()

    def test_terminate_frees_the_unit(self):
        contract = self._make_contract()
        contract.action_activate()
        contract.action_terminate(reason='Tenant moved out')
        self.assertEqual(contract.state, 'terminated')
        self.assertEqual(self.unit.occupancy_status, 'available')
        self.assertEqual(contract.termination_reason, 'Tenant moved out')

    def test_terminate_without_reason_succeeds(self):
        """BD-002 (2026-09-22): unlike Reject, Terminate's reason stays
        optional - preserved, unchanged behavior."""
        contract = self._make_contract()
        contract.action_activate()
        contract.action_terminate()
        self.assertEqual(contract.state, 'terminated')
        self.assertEqual(self.unit.occupancy_status, 'available')
        self.assertFalse(contract.termination_reason)

    def test_renew_creates_scheduled_successor_and_keeps_predecessor_active(self):
        """Phase 10.1: a renewal creates a scheduled successor; the current lease stays active
        (and the unit rented) until its own term ends - only the daily job then renews it."""
        contract = self._make_contract()
        contract.action_activate()
        new_contract = contract.action_renew(
            contract.end_date + timedelta(days=1), contract.end_date + timedelta(days=366), 1650)
        self.assertEqual(contract.state, 'active')
        self.assertEqual(contract.successor_contract_id, new_contract)
        self.assertEqual(new_contract.state, 'scheduled')
        self.assertEqual(new_contract.predecessor_contract_id, contract)
        self.assertEqual(new_contract.rent_amount, 1650)
        self.assertEqual(self.unit.occupancy_status, 'rented')

    def test_kanban_and_calendar_views_load(self):
        """MAT/UI-032 §9: new native Kanban/Calendar views for the Dashboard's
        Lease Contract quick actions and Kanban/Calendar view mode."""
        action = self.env.ref('property_managment.action_edara_lease_contract')
        self.assertIn('kanban', action.view_mode)
        self.assertIn('calendar', action.view_mode)
        kanban_view = self.env['edara.lease.contract'].get_view(view_type='kanban')
        self.assertTrue(kanban_view.get('arch'))
        calendar_view = self.env['edara.lease.contract'].get_view(view_type='calendar')
        self.assertTrue(calendar_view.get('arch'))

    def test_cannot_delete_activated_contract(self):
        contract = self._make_contract()
        contract.action_activate()
        with self.assertRaises(UserError):
            contract.unlink()

    def test_cron_expires_active_contract_past_end_date(self):
        contract = self._make_contract(start_date=date(2020, 1, 1), end_date=date(2020, 12, 31))
        contract.action_activate()
        uninvoiced_line_count = len(contract.schedule_line_ids)
        self.assertTrue(uninvoiced_line_count)

        self.env['edara.lease.contract']._cron_expire_contracts()

        self.assertEqual(contract.state, 'expired')
        self.assertEqual(self.unit.occupancy_status, 'available')
        # MAT-FIND-006: every one of these lines is overdue (due dates in 2020,
        # long past) and uninvoiced - they represent real unpaid rent and must
        # survive expiry, not be silently deleted.
        self.assertEqual(len(contract.schedule_line_ids), uninvoiced_line_count)
        self.assertTrue(all(line.state == 'overdue' for line in contract.schedule_line_ids))

        # Idempotent: running it again does nothing further (no error, still
        # expired, no further lines removed).
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(contract.state, 'expired')
        self.assertEqual(len(contract.schedule_line_ids), uninvoiced_line_count)

    def test_cron_does_not_expire_contract_still_within_term(self):
        contract = self._make_contract()  # ends 2026-12-31, still in the future
        contract.action_activate()
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(contract.state, 'active')

    # -- MAT-020: occupancy recomputation with sequential active contracts --

    def _make_current_and_future_contracts(self):
        today = date.today()
        current = self._make_contract(
            start_date=today - timedelta(days=30), end_date=today + timedelta(days=30))
        current.action_activate()
        future = self._make_contract(
            tenant_id=self.tenant.id,
            start_date=today + timedelta(days=60), end_date=today + timedelta(days=120))
        future.action_activate()
        return current, future

    def test_current_and_future_sequential_contracts_can_both_be_active(self):
        current, future = self._make_current_and_future_contracts()
        self.assertEqual(current.state, 'active')
        self.assertEqual(future.state, 'scheduled')
        self.assertEqual(self.unit.occupancy_status, 'rented')

    def test_terminate_future_contract_keeps_unit_rented_via_current_contract(self):
        """MAT-020 regression: withdrawing a future-dated (scheduled) contract must not
        clobber occupancy still held by a currently-active contract on the
        same unit."""
        current, future = self._make_current_and_future_contracts()
        future.action_cancel()
        self.assertEqual(future.state, 'cancelled')
        self.assertEqual(current.state, 'active')
        self.assertEqual(self.unit.occupancy_status, 'rented')

    def test_terminate_current_contract_with_only_future_contract_remaining_leaves_unit_reserved(self):
        """A future-dated active contract does not by itself occupy the unit
        today (state='active' alone is not enough, MAT-020) - but per BD-001
        (2026-09-21) it IS a real commitment, so the unit becomes RESERVED,
        not AVAILABLE, once the only remaining active contract is future-dated."""
        current, future = self._make_current_and_future_contracts()
        current.action_terminate(reason='Current lease ended early')
        self.assertEqual(current.state, 'terminated')
        self.assertEqual(future.state, 'scheduled')
        self.assertEqual(self.unit.occupancy_status, 'reserved')

    def test_cron_expiry_with_future_contract_still_active_leaves_unit_reserved(self):
        """Same principle as the termination sibling above, via the expiry
        cron path (BD-001, 2026-09-21)."""
        today = date.today()
        current = self._make_contract(
            start_date=today - timedelta(days=400), end_date=today - timedelta(days=1))
        current.action_activate()
        future = self._make_contract(
            tenant_id=self.tenant.id,
            start_date=today + timedelta(days=60), end_date=today + timedelta(days=120))
        future.action_activate()

        self.env['edara.lease.contract']._cron_expire_contracts()

        self.assertEqual(current.state, 'expired')
        self.assertEqual(future.state, 'scheduled')
        self.assertEqual(self.unit.occupancy_status, 'reserved')

    def test_terminated_historical_contract_does_not_affect_later_occupancy(self):
        today = date.today()
        old = self._make_contract(
            start_date=today - timedelta(days=400), end_date=today - timedelta(days=200))
        old.action_activate()
        old.action_terminate(reason='Old tenant moved out')
        self.assertEqual(self.unit.occupancy_status, 'available')

        new = self._make_contract(
            tenant_id=self.tenant.id,
            start_date=today - timedelta(days=10), end_date=today + timedelta(days=350))
        new.action_activate()
        self.assertEqual(self.unit.occupancy_status, 'rented')

        new.action_terminate(reason='New tenant also moved out')
        self.assertEqual(self.unit.occupancy_status, 'available')

    def test_cannot_manually_mark_unit_available_with_current_active_contract(self):
        """Symmetric defense-in-depth to the existing 'cannot mark rented
        without an active contract' guard."""
        contract = self._make_contract()
        contract.action_activate()
        with self.assertRaises(ValidationError):
            self.unit.occupancy_status = 'available'

    # -- BD-001/MAT-FIND-010 (2026-09-21): date-aware RESERVED/RENTED occupancy --

    def test_activate_future_dated_contract_marks_unit_reserved(self):
        """BD-001 (2026-09-21): supersedes the old pinned "still marks unit
        Rented immediately" behavior. A future-dated ACTIVE contract now
        makes the unit RESERVED (contractually committed, not yet occupied)
        until its start date arrives - see the complementary
        test_cron_sync_reserved_occupancy_* tests below for that transition."""
        today = date.today()
        future = self._make_contract(
            start_date=today + timedelta(days=90), end_date=today + timedelta(days=450))
        future.action_activate()
        self.assertEqual(future.state, 'scheduled')
        self.assertEqual(self.unit.occupancy_status, 'reserved')

    def test_activate_same_day_start_contract_marks_unit_rented(self):
        """BD-001: a contract whose start_date is today is already in force -
        RENTED immediately, not RESERVED."""
        today = date.today()
        contract = self._make_contract(start_date=today, end_date=today + timedelta(days=365))
        contract.action_activate()
        self.assertEqual(self.unit.occupancy_status, 'rented')

    def test_activate_past_start_contract_marks_unit_rented(self):
        """BD-001: a contract whose start_date has already passed is in
        force - RENTED immediately."""
        today = date.today()
        contract = self._make_contract(
            start_date=today - timedelta(days=10), end_date=today + timedelta(days=355))
        contract.action_activate()
        self.assertEqual(self.unit.occupancy_status, 'rented')

    def test_cron_sync_reserved_occupancy_transitions_reserved_to_rented_when_start_date_arrives(self):
        """BD-001's reliable start-date-arrival mechanism. Simulates "the
        start date has arrived" by moving start_date into the past after
        activation (real date/time is never mocked elsewhere in this suite
        either - see the existing expiry-cron tests' use of already-past
        literal dates for the same convention)."""
        today = date.today()
        future = self._make_contract(
            start_date=today + timedelta(days=5), end_date=today + timedelta(days=365))
        future.action_activate()
        self.assertEqual(self.unit.occupancy_status, 'reserved')

        future.start_date = today - timedelta(days=1)
        self.env['edara.unit']._cron_sync_reserved_occupancy()
        self.assertEqual(self.unit.occupancy_status, 'reserved')   # still 'scheduled': the lease job starts it
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(future.state, 'active')
        self.assertEqual(self.unit.occupancy_status, 'rented')

        # Idempotent: running them again does nothing further (no error, still rented).
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.env['edara.unit']._cron_sync_reserved_occupancy()
        self.assertEqual(self.unit.occupancy_status, 'rented')

    def test_reserved_contract_terminated_before_start_date_frees_unit_to_available(self):
        """BD-001: terminating a still-RESERVED contract (never actually
        occupied) must free the unit to AVAILABLE, not leave it stranded."""
        today = date.today()
        future = self._make_contract(
            start_date=today + timedelta(days=30), end_date=today + timedelta(days=395))
        future.action_activate()
        self.assertEqual(self.unit.occupancy_status, 'reserved')

        future.action_cancel()
        self.assertEqual(future.state, 'cancelled')
        self.assertEqual(self.unit.occupancy_status, 'available')

    def test_overlap_prevented_between_reserved_and_new_active_contract(self):
        """BD-001: RESERVED must not open a path around the existing overlap
        protection - _check_no_overlap() compares contract date ranges
        regardless of the resulting occupancy label."""
        today = date.today()
        future = self._make_contract(
            start_date=today + timedelta(days=90), end_date=today + timedelta(days=450))
        future.action_activate()
        self.assertEqual(self.unit.occupancy_status, 'reserved')

        overlapping = self._make_contract(
            tenant_id=self.tenant.id,
            start_date=today + timedelta(days=200), end_date=today + timedelta(days=600))
        with self.assertRaises(ValidationError):
            overlapping.action_activate()

    # -- MAT-FIND-006: termination/expiry must not delete overdue uninvoiced lines --

    def _build_schedule(self, contract, offsets_days):
        """Replace contract's auto-generated schedule with lines at exact
        day-offsets from today, for deterministic MAT-FIND-006 case testing
        independent of whatever real date the suite happens to run on."""
        contract.schedule_line_ids.unlink()
        today = date.today()
        Line = self.env['edara.payment.schedule.line']
        for i, offset in enumerate(offsets_days):
            Line.create({
                'contract_id': contract.id,
                'due_date': today + timedelta(days=offset),
                'amount': contract.rent_amount,
                'sequence': (i + 1) * 10,
            })
        return contract.schedule_line_ids

    def _configure_rental_income_account(self):
        self.env.company.edara_rental_income_account_id = self.env['account.account'].create({
            'name': 'EDARA Rental Income (MAT-FIND-006 Test)', 'code': '400199', 'account_type': 'income',
        }).id

    def test_terminate_removes_future_uninvoiced_line(self):
        """Case 1: a not-yet-due, uninvoiced line may be removed on termination."""
        contract = self._make_contract()
        contract.action_activate()
        self._build_schedule(contract, [30])
        contract.action_terminate(reason='MAT-FIND-006 Case 1')
        self.assertFalse(contract.schedule_line_ids)

    def test_terminate_keeps_overdue_uninvoiced_line(self):
        """Case 2: an already-due, uninvoiced line must survive termination
        and remain state='overdue' - it represents a real unpaid rent
        obligation, not a cancelled future period."""
        contract = self._make_contract()
        contract.action_activate()
        line = self._build_schedule(contract, [-30])
        contract.action_terminate(reason='MAT-FIND-006 Case 2')
        self.assertTrue(line.exists())
        self.assertEqual(line.state, 'overdue')

    def test_terminate_keeps_invoiced_line_untouched(self):
        """Case 3: an invoiced line must never be touched by termination,
        regardless of its due date."""
        self._configure_rental_income_account()
        contract = self._make_contract()
        contract.action_activate()
        line = self._build_schedule(contract, [-30])
        invoice = line._create_invoice()
        contract.action_terminate(reason='MAT-FIND-006 Case 3')
        self.assertTrue(line.exists())
        self.assertEqual(line.invoice_id, invoice)

    def test_terminate_mixed_schedule_selectively_removes_only_future_uninvoiced(self):
        """Case 4: a contract with a mix of future-uninvoiced, overdue-
        uninvoiced, and invoiced lines must, on termination, remove only the
        future-uninvoiced one - the other two survive unchanged. Proves the
        filtering logic is selective, not all-or-nothing."""
        self._configure_rental_income_account()
        contract = self._make_contract()
        contract.action_activate()
        lines = self._build_schedule(contract, [-60, -30, 30])
        overdue_line, invoiced_line, future_line = lines.sorted('due_date')
        invoice = invoiced_line._create_invoice()

        contract.action_terminate(reason='MAT-FIND-006 Case 4')

        self.assertFalse(future_line.exists())
        self.assertTrue(overdue_line.exists())
        self.assertEqual(overdue_line.state, 'overdue')
        self.assertTrue(invoiced_line.exists())
        self.assertEqual(invoiced_line.invoice_id, invoice)

    def test_cron_expiry_keeps_overdue_uninvoiced_line_but_removes_future_one(self):
        """Same Case 1+2 selectivity, via the automatic expiry cron path
        instead of manual termination - both entry points share
        _unlink_future_uninvoiced_schedule_lines() and must behave
        identically (MAT-FIND-006)."""
        today = date.today()
        contract = self._make_contract(
            start_date=today - timedelta(days=400), end_date=today - timedelta(days=1))
        contract.action_activate()
        lines = self._build_schedule(contract, [-30, 30])
        overdue_line, future_line = lines.sorted('due_date')

        self.env['edara.lease.contract']._cron_expire_contracts()

        self.assertEqual(contract.state, 'expired')
        self.assertFalse(future_line.exists())
        self.assertTrue(overdue_line.exists())
        self.assertEqual(overdue_line.state, 'overdue')

    def test_state_field_is_indexed(self):
        """Product Readiness Review (2026-09-22): state is the Dashboard's/
        crons'/quick-actions' most-filtered column on this model."""
        self.assertTrue(self.env['edara.lease.contract']._fields['state'].index)
