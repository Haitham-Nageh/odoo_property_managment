from datetime import date, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


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

    def test_kanban_calendar_and_gantt_views_load(self):
        """MAT/UI-032 §9 & Phase 11.1: Native Kanban/Calendar/Gantt views for Lease Contracts."""
        action = self.env.ref('property_managment.action_edara_lease_contract')
        self.assertIn('kanban', action.view_mode)
        self.assertIn('calendar', action.view_mode)
        self.assertIn('gantt', action.view_mode)
        kanban_view = self.env['edara.lease.contract'].get_view(view_type='kanban')
        self.assertTrue(kanban_view.get('arch'))
        calendar_view = self.env['edara.lease.contract'].get_view(view_type='calendar')
        self.assertTrue(calendar_view.get('arch'))
        gantt_view = self.env['edara.lease.contract'].get_view(view_type='gantt')
        self.assertTrue(gantt_view.get('arch'))

    def test_lease_timeline_landing_action(self):
        """Phase 11.1 Follow-up: Dedicated landing action for Lease Timeline (Gantt first)."""
        timeline_action = self.env.ref('property_managment.action_edara_lease_timeline')
        self.assertEqual(timeline_action.res_model, 'edara.lease.contract')
        modes = [m.strip() for m in timeline_action.view_mode.split(',')]
        self.assertEqual(modes[0], 'gantt')
        self.assertIn('calendar', modes)

        # Existing contracts action must remain list-first
        contracts_action = self.env.ref('property_managment.action_edara_lease_contract')
        contracts_modes = [m.strip() for m in contracts_action.view_mode.split(',')]
        self.assertEqual(contracts_modes[0], 'list')




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

    # ============ Track B: Unit Default Rent -> New Lease ============

    def test_onchange_unit_id_applies_default_rent(self):
        """Test 1: Selecting a unit with rent_amount_default populates rent_amount."""
        unit_with_rent = self.env['edara.unit'].create({
            'name': 'B-201',
            'code': 'B201',
            'building_id': self.building.id,
            'rent_amount_default': 2500.0,
        })
        contract_form = Form(self.env['edara.lease.contract'])
        contract_form.unit_id = unit_with_rent
        self.assertEqual(contract_form.rent_amount, 2500.0)

        # Also verify via direct model onchange call
        contract = self.env['edara.lease.contract'].new({'unit_id': unit_with_rent.id})
        contract._onchange_unit_id_rent_amount()
        self.assertEqual(contract.rent_amount, 2500.0)

    def test_onchange_unit_id_zero_default_rent_does_not_override(self):
        """Test 2: A unit with 0/unset default rent does not force rent_amount to 0,
        and existing rent validation remains intact."""
        unit_zero_rent = self.env['edara.unit'].create({
            'name': 'B-202',
            'code': 'B202',
            'building_id': self.building.id,
            'rent_amount_default': 0.0,
        })
        contract = self.env['edara.lease.contract'].new({
            'unit_id': unit_zero_rent.id,
            'rent_amount': 1800.0,
        })
        contract._onchange_unit_id_rent_amount()
        self.assertEqual(contract.rent_amount, 1800.0)

        # Confirm positive rent validation still rejects 0 rent
        with self.assertRaises(ValidationError):
            self._make_contract(unit_id=unit_zero_rent.id, rent_amount=0)

    def test_no_permanent_synchronization_between_unit_and_lease_rent(self):
        """Test 3: Changing a unit's rent_amount_default after lease creation
        must NOT modify the existing lease's rent_amount."""
        unit = self.env['edara.unit'].create({
            'name': 'B-203',
            'code': 'B203',
            'building_id': self.building.id,
            'rent_amount_default': 3000.0,
        })
        contract_form = Form(self.env['edara.lease.contract'])
        contract_form.unit_id = unit
        contract_form.tenant_id = self.tenant
        contract_form.start_date = date(2026, 1, 1)
        contract_form.end_date = date(2026, 12, 31)
        contract_form.deposit_required = False
        contract = contract_form.save()
        self.assertEqual(contract.rent_amount, 3000.0)

        # Modify unit's default rent
        unit.rent_amount_default = 4500.0

        # Existing contract rent remains unchanged
        contract.invalidate_recordset(['rent_amount'])
        self.assertEqual(contract.rent_amount, 3000.0)

    def test_manual_rent_override_persists(self):
        """Test 4: Manually setting a different rent_amount overrides the default rent,
        and the manual value persists on the saved contract."""
        unit = self.env['edara.unit'].create({
            'name': 'B-204',
            'code': 'B204',
            'building_id': self.building.id,
            'rent_amount_default': 3000.0,
        })
        contract_form = Form(self.env['edara.lease.contract'])
        contract_form.unit_id = unit
        self.assertEqual(contract_form.rent_amount, 3000.0)

        # Manually override rent
        contract_form.rent_amount = 3200.0
        contract_form.tenant_id = self.tenant
        contract_form.start_date = date(2026, 1, 1)
        contract_form.end_date = date(2026, 12, 31)
        contract_form.deposit_required = False
        contract = contract_form.save()

        self.assertEqual(contract.rent_amount, 3200.0)

    # ============ P2: Closed Contract Core-Term Freeze ============

    def test_historical_contracts_core_terms_frozen(self):
        """P2 Test A: In terminated, expired, cancelled, and renewed states,
        core terms (start_date, end_date, rent_amount, tenant_id) are immutable."""
        other_tenant = self.env['res.partner'].create({'name': 'P2 Other Tenant'})
        today = date.today()

        # 1. Terminated contract (separate unit to avoid date collision)
        unit_term = self.env['edara.unit'].create({
            'name': 'P2-Term', 'code': 'P2T', 'building_id': self.building.id,
        })
        c_term = self._make_contract(unit_id=unit_term.id)
        c_term.action_activate()
        c_term.action_terminate(reason='End of lease')

        # 2. Expired contract (separate unit)
        unit_exp = self.env['edara.unit'].create({
            'name': 'P2-Exp', 'code': 'P2E', 'building_id': self.building.id,
        })
        c_exp = self._make_contract(
            unit_id=unit_exp.id,
            start_date=today - timedelta(days=400),
            end_date=today - timedelta(days=1),
        )
        c_exp.action_activate()
        self.env['edara.lease.contract']._cron_expire_contracts()

        # 3. Cancelled contract (separate unit)
        unit_canc = self.env['edara.unit'].create({
            'name': 'P2-Canc', 'code': 'P2C', 'building_id': self.building.id,
        })
        c_canc = self._make_contract(
            unit_id=unit_canc.id,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=375),
        )
        c_canc.action_activate()
        c_canc.action_cancel()

        # 4. Renewed contract (predecessor of a renewal, separate unit)
        unit_ren = self.env['edara.unit'].create({
            'name': 'P2-Ren', 'code': 'P2R', 'building_id': self.building.id,
        })
        c_ren = self._make_contract(
            unit_id=unit_ren.id,
            start_date=today - timedelta(days=400),
            end_date=today - timedelta(days=1),
        )
        c_ren.action_activate()
        c_ren.action_renew(today, today + timedelta(days=365), 1800)
        self.env['edara.lease.contract']._cron_expire_contracts()

        historical_cases = [
            (c_term, 'terminated'),
            (c_exp, 'expired'),
            (c_canc, 'cancelled'),
            (c_ren, 'renewed'),
        ]

        for contract, expected_state in historical_cases:
            self.assertEqual(contract.state, expected_state)
            orig_start = contract.start_date
            orig_end = contract.end_date
            orig_rent = contract.rent_amount
            orig_tenant = contract.tenant_id

            # start_date frozen
            with self.assertRaises(UserError):
                contract.write({'start_date': date(2020, 1, 1)})
            self.assertEqual(contract.start_date, orig_start)

            # end_date frozen
            with self.assertRaises(UserError):
                contract.write({'end_date': date(2030, 12, 31)})
            self.assertEqual(contract.end_date, orig_end)

            # rent_amount frozen
            with self.assertRaises(UserError):
                contract.write({'rent_amount': 9999.0})
            self.assertEqual(contract.rent_amount, orig_rent)

            # tenant_id frozen
            with self.assertRaises(UserError):
                contract.write({'tenant_id': other_tenant.id})
            self.assertEqual(contract.tenant_id, orig_tenant)

    def test_historical_freeze_no_sudo_bypass(self):
        """P2 Test B: The historical core-term freeze applies even through sudo()."""
        unit = self.env['edara.unit'].create({
            'name': 'P2-Sudo', 'code': 'P2SUDO', 'building_id': self.building.id,
        })
        contract = self._make_contract(unit_id=unit.id)
        contract.action_activate()
        contract.action_terminate(reason='Termination test')
        self.assertEqual(contract.state, 'terminated')
        orig_rent = contract.rent_amount

        with self.assertRaises(UserError):
            contract.sudo().write({'rent_amount': 999.0})
        self.assertEqual(contract.rent_amount, orig_rent)

    def test_combined_state_and_core_term_write_blocked(self):
        """P2 Test C: Writing core terms together with a transition to historical state
        is blocked by checking effective state."""
        unit = self.env['edara.unit'].create({
            'name': 'P2-Comb', 'code': 'P2COMB', 'building_id': self.building.id,
        })
        contract = self._make_contract(unit_id=unit.id)
        contract.action_activate()
        self.assertEqual(contract.state, 'active')
        orig_rent = contract.rent_amount

        with self.assertRaises(UserError):
            contract.sudo().write({
                'state': 'terminated',
                'rent_amount': 999.0,
            })
        self.assertEqual(contract.state, 'active')
        self.assertEqual(contract.rent_amount, orig_rent)

    def test_live_contracts_core_terms_remain_editable(self):
        """P2 Test D: Live contracts (draft, scheduled, active) allow editing core terms."""
        other_tenant = self.env['res.partner'].create({'name': 'P2 Live Tenant'})
        today = date.today()

        # 1. Draft
        unit_draft = self.env['edara.unit'].create({
            'name': 'P2-Draft', 'code': 'P2DRF', 'building_id': self.building.id,
        })
        c_draft = self._make_contract(
            unit_id=unit_draft.id,
            start_date=today,
            end_date=today + timedelta(days=100),
            rent_amount=1000,
        )
        c_draft.write({
            'start_date': today + timedelta(days=1),
            'end_date': today + timedelta(days=200),
            'rent_amount': 1200,
            'tenant_id': other_tenant.id,
        })
        self.assertEqual(c_draft.start_date, today + timedelta(days=1))
        self.assertEqual(c_draft.end_date, today + timedelta(days=200))
        self.assertEqual(c_draft.rent_amount, 1200)
        self.assertEqual(c_draft.tenant_id, other_tenant)

        # 2. Scheduled
        unit_sched = self.env['edara.unit'].create({
            'name': 'P2-Sched', 'code': 'P2SCH', 'building_id': self.building.id,
        })
        c_sched = self._make_contract(
            unit_id=unit_sched.id,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=100),
            rent_amount=1000,
        )
        c_sched.action_activate()
        self.assertEqual(c_sched.state, 'scheduled')
        c_sched.write({
            'start_date': today + timedelta(days=15),
            'end_date': today + timedelta(days=150),
            'rent_amount': 1300,
            'tenant_id': other_tenant.id,
        })
        self.assertEqual(c_sched.start_date, today + timedelta(days=15))
        self.assertEqual(c_sched.end_date, today + timedelta(days=150))
        self.assertEqual(c_sched.rent_amount, 1300)
        self.assertEqual(c_sched.tenant_id, other_tenant)

        # 3. Active
        unit_act = self.env['edara.unit'].create({
            'name': 'P2-Act', 'code': 'P2ACT', 'building_id': self.building.id,
        })
        c_act = self._make_contract(
            unit_id=unit_act.id,
            start_date=today - timedelta(days=10),
            end_date=today + timedelta(days=100),
            rent_amount=1000,
        )
        c_act.action_activate()
        self.assertEqual(c_act.state, 'active')
        c_act.write({
            'start_date': today - timedelta(days=5),
            'end_date': today + timedelta(days=150),
            'rent_amount': 1400,
            'tenant_id': other_tenant.id,
        })
        self.assertEqual(c_act.start_date, today - timedelta(days=5))
        self.assertEqual(c_act.end_date, today + timedelta(days=150))
        self.assertEqual(c_act.rent_amount, 1400)
        self.assertEqual(c_act.tenant_id, other_tenant)

    def test_multi_record_write_historical_blocks_all(self):
        """P2 Multi-record: A mixed recordset of active and historical contracts blocks core term write."""
        unit_1 = self.env['edara.unit'].create({
            'name': 'P2-Mix1', 'code': 'P2M1', 'building_id': self.building.id,
        })
        unit_2 = self.env['edara.unit'].create({
            'name': 'P2-Mix2', 'code': 'P2M2', 'building_id': self.building.id,
        })
        c_active = self._make_contract(unit_id=unit_1.id, rent_amount=1500)
        c_active.action_activate()

        c_term = self._make_contract(unit_id=unit_2.id, rent_amount=1500)
        c_term.action_activate()
        c_term.action_terminate(reason='Moving out')

        mixed = c_active | c_term
        with self.assertRaises(UserError):
            mixed.write({'rent_amount': 5000})
        self.assertEqual(c_active.rent_amount, 1500)
        self.assertEqual(c_term.rent_amount, 1500)
