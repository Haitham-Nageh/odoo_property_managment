import importlib.util
import itertools
import os
from datetime import date, timedelta
from fractions import Fraction
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.property_managment.models import edara_proration as P

CENT = Fraction(1, 100)
MILLI = Fraction(1, 1000)


def units(amount, rounding):
    """amount as an integer number of minor units (exact comparison of float amounts)"""
    return round(Fraction(str(amount)) / rounding)


@tagged('post_install', '-at_install')
class TestProrationMath(TransactionCase):
    """Phase 10.1 - the pure engine (models/edara_proration.py): Period-Relative Actual/Actual with
    cumulative rounding. No ORM records involved."""

    def _lines(self, start, end, months, rent, rounding=CENT):
        return P.piece_lines(start, months, Fraction(str(rent)), rounding, start, P.term_boundary(end))

    # -- inclusive end date / exclusive boundary --

    def test_boundary_is_end_date_plus_one(self):
        self.assertEqual(P.term_boundary(date(2026, 12, 31)), date(2027, 1, 1))
        self.assertEqual(P.term_boundary(date(2028, 2, 28)), date(2028, 2, 29))
        self.assertEqual(P.term_boundary(date(2028, 2, 29)), date(2028, 3, 1))

    def test_one_day_lease_is_one_occupied_day(self):
        (line,) = self._lines(date(2026, 1, 15), date(2026, 1, 15), 1, 1000)
        self.assertEqual((line[1] - line[0]).days, 1)
        self.assertEqual((line[0], line[1], line[2]), (date(2026, 1, 15), date(2026, 1, 16), True))
        self.assertEqual(line[3], 32.26)   # 1000 / 31

    def test_complete_january_is_one_full_period(self):
        (line,) = self._lines(date(2026, 1, 1), date(2026, 1, 31), 1, 1000)
        self.assertEqual(line, (date(2026, 1, 1), date(2026, 2, 1), False, 1000.0))

    # -- monthly partial months use that month's real length --

    def test_monthly_partial_january_uses_31(self):
        (line,) = self._lines(date(2026, 1, 13), date(2026, 1, 31), 1, 1000)
        self.assertEqual(((line[1] - line[0]).days, line[3]), (19, 612.90))   # 19/31, not 19/30 = 633.33

    def test_monthly_partial_february_uses_28(self):
        (line,) = self._lines(date(2026, 2, 1), date(2026, 2, 14), 1, 1000)
        self.assertEqual(line[3], 500.0)                                      # 14/28

    def test_february_second_half_is_14_of_28(self):
        # anchored at the 15th: the piece 15/02 - 28/02 sits inside the anchored month 15/02 - 15/03
        # (28 real days), so occupancy 14 days = 14/28 of the rent.
        (line,) = self._lines(date(2026, 2, 15), date(2026, 2, 28), 1, 1000)
        self.assertEqual((line[1] - line[0]).days, 14)
        self.assertEqual(line[3], 500.0)

    def test_leap_year_february_has_29_days(self):
        (line,) = self._lines(date(2028, 2, 1), date(2028, 2, 14), 1, 1000)
        self.assertEqual(line[3], 482.76)                                     # 14/29
        (full,) = self._lines(date(2028, 2, 1), date(2028, 2, 29), 1, 1000)
        self.assertEqual((full[2], full[3]), (False, 1000.0))                # 29 days = the full month

    # -- full periods are exact for every frequency / currency --

    def test_full_periods_are_exact(self):
        for months, rent in ((1, 1000), (3, 3000), (12, 12000), (1, 1234.56), (3, 999.99), (12, 100000.01)):
            for rounding in (CENT, MILLI):
                for start in (date(2026, 1, 1), date(2026, 1, 31), date(2028, 2, 29), date(2026, 9, 15)):
                    end = P.month_boundary(start, months * 3) - timedelta(days=1)
                    lines = self._lines(start, end, months, rent, rounding)
                    self.assertEqual(len(lines), 3)
                    self.assertTrue(all(not l[2] and l[3] == float(Fraction(str(rent))) for l in lines), lines)

    def test_quarterly_partial_january_uses_exact_third(self):
        # 3000/quarter -> exactly 1000/month; a half-used January: 1000 * 17/31
        (line,) = self._lines(date(2026, 1, 15), date(2026, 1, 31), 3, 3000)
        self.assertEqual(line[3], 548.39)

    def test_yearly_three_and_six_complete_months(self):
        self.assertEqual(self._lines(date(2026, 1, 1), date(2026, 3, 31), 12, 12000)[0][3], 3000.0)
        self.assertEqual(self._lines(date(2026, 1, 1), date(2026, 6, 30), 12, 12000)[0][3], 6000.0)
        self.assertEqual(self._lines(date(2026, 3, 1), date(2026, 8, 31), 12, 12000)[0][3], 6000.0)
        # the old 30-day rule gave 3,033.33 / 6,033.33
        self.assertNotIn(self._lines(date(2026, 1, 1), date(2026, 3, 31), 12, 12000)[0][3], (3033.33, 6033.33))

    def test_yearly_full_leap_and_non_leap_year_bill_the_rent(self):
        for start in (date(2026, 1, 1), date(2028, 1, 1)):
            (line,) = self._lines(start, date(start.year, 12, 31), 12, 12000)
            self.assertEqual((line[2], line[3]), (False, 12000.0))

    # -- the split invariant --

    def test_split_invariant_exhaustive(self):
        """amount(a, b) = amount(a, c) + amount(c, b) for every cut c: 28/29/30/31-day months,
        month/quarter/year boundaries, day-31 and leap-day anchors, all frequencies, ILS/USD/JOD."""
        checked = 0
        for start in (date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 31), date(2028, 2, 29),
                      date(2026, 11, 30), date(2027, 12, 20)):
            for months, rent in ((1, 1000), (3, 3000), (12, 12000), (1, 1234.56)):
                for rounding in (CENT, MILLI):
                    rent_f = Fraction(str(rent))
                    p1 = P.month_boundary(start, months)
                    span = (p1 - start).days
                    for a_off, b_off in itertools.product(range(0, span, max(1, span // 20)),
                                                          list(range(1, span, max(1, span // 17))) + [span]):
                        a, b = start + timedelta(days=a_off), start + timedelta(days=b_off)
                        if b <= a:
                            continue
                        whole = units(P.piece_amount(start, months, 0, a, b, rent_f, rounding), rounding)
                        for c in {a + timedelta(days=1), a + (b - a) // 2, b - timedelta(days=1)}:
                            if not a < c < b:
                                continue
                            parts = (units(P.piece_amount(start, months, 0, a, c, rent_f, rounding), rounding)
                                     + units(P.piece_amount(start, months, 0, c, b, rent_f, rounding), rounding))
                            self.assertEqual(parts, whole, (start, months, rent, a, c, b))
                            checked += 1
        self.assertGreater(checked, 3000)

    def test_pieces_of_one_period_sum_to_its_rent(self):
        for rounding, rent in ((CENT, 1000), (MILLI, 1000), (CENT, 3333.33), (MILLI, 1234.567)):
            rent_f = Fraction(str(rent))
            for start, months, n_cuts in ((date(2026, 4, 1), 1, 3), (date(2026, 2, 1), 1, 5),
                                          (date(2028, 1, 1), 3, 6), (date(2026, 1, 31), 12, 9)):
                p1 = P.month_boundary(start, months)
                step = max(1, (p1 - start).days // n_cuts)
                cuts = [start + timedelta(days=i * step) for i in range(n_cuts) if start + timedelta(days=i * step) < p1]
                bounds = cuts + [p1]
                total = sum(units(P.piece_amount(start, months, 0, a, b, rent_f, rounding), rounding)
                            for a, b in zip(bounds, bounds[1:]))
                self.assertEqual(total, units(float(rent_f), rounding), (start, months, rent, rounding))

    def test_cumulative_rounding_three_thirds(self):
        start, boundary = date(2026, 4, 1), date(2026, 5, 1)          # a 30-day month
        cuts = [start, date(2026, 4, 11), date(2026, 4, 21), boundary]
        parts = [P.piece_amount(start, 1, 0, a, b, Fraction(1000), CENT) for a, b in zip(cuts, cuts[1:])]
        self.assertEqual(parts, [333.33, 333.34, 333.33])
        self.assertEqual(units(sum(parts), CENT), 100000)

    def test_rounding_matches_odoo_float_round(self):
        from odoo.tools.float_utils import float_round
        for rent, rounding, digits in ((1000, CENT, 2), (1234.56, CENT, 2), (1000, MILLI, 3), (3333.33, MILLI, 3)):
            for days in range(1, 32):
                exact = Fraction(str(rent)) * days / 31
                ours = P.round_units(exact, rounding) * float(rounding)
                self.assertAlmostEqual(ours, float_round(float(exact), precision_digits=digits), places=6)

    def test_coverage_generation_resumes_at_the_covered_boundary(self):
        # an already covered range is never generated again; the stub finishes the anchored period
        start = date(2026, 1, 1)
        rent = Fraction(1000)
        stub = P.piece_lines(start, 1, rent, CENT, date(2026, 12, 20), date(2027, 1, 1))
        self.assertEqual(stub, [(date(2026, 12, 20), date(2027, 1, 1), True, 387.10)])
        tail = P.piece_amount(start, 1, 11, date(2026, 12, 1), date(2026, 12, 20), rent, CENT)
        self.assertEqual(tail, 612.90)
        self.assertEqual(units(tail + stub[0][3], CENT), 100000)


@tagged('post_install', '-at_install')
class TestLeaseDateAndScheduleEngine(TransactionCase):
    """Phase 10.1 - lease dates, schedule generation, extension, renewal, occupancy."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        E = cls.env
        cls.branch = E['edara.branch'].create({'name': 'P10 Branch', 'code': 'P10B'})
        cls.property = E['edara.property'].create({'name': 'P10 Property', 'code': 'P10P', 'branch_id': cls.branch.id})
        cls.building = E['edara.building'].create({'name': 'P10 Building', 'code': 'P10BL', 'property_id': cls.property.id})
        cls.tenant = E['res.partner'].create({'name': 'P10 Tenant'})
        cls.today = date.today()
        cls.currencies = {}
        for code in ('ILS', 'USD', 'JOD'):
            cur = E['res.currency'].with_context(active_test=False).search([('name', '=', code)])
            cur.active = True
            cls.currencies[code] = cur
        E.company.edara_rental_income_account_id = E['account.account'].create(
            {'name': 'P10 Rent', 'code': '410010', 'account_type': 'income'}).id
        cls._n = 0

    def _unit(self):
        type(self)._n += 1
        return self.env['edara.unit'].create(
            {'name': 'P10-%d' % self._n, 'code': 'P10U%d' % self._n, 'building_id': self.building.id})

    def _contract(self, start, end, rent=1000, freq='monthly', unit=None, **kw):
        vals = {'unit_id': (unit or self._unit()).id, 'tenant_id': self.tenant.id, 'start_date': start,
                'end_date': end, 'rent_amount': rent, 'billing_frequency': freq, 'deposit_required': False}
        vals.update(kw)
        return self.env['edara.lease.contract'].create(vals)

    def _live(self, start, end, **kw):
        contract = self._contract(start, end, **kw)
        contract.action_activate()
        return contract

    def _at(self, day):
        """Run code as if today were `day` (every lifecycle rule reads fields.Date.context_today)."""
        return patch.object(fields.Date, 'context_today', staticmethod(lambda record, timestamp=None: day))

    # ---------------- date convention ----------------

    def test_end_date_equal_start_date_is_valid_and_end_before_start_is_not(self):
        contract = self._live(date(2026, 1, 15), date(2026, 1, 15))
        (line,) = contract.schedule_line_ids
        self.assertEqual((line.occupied_days, line.period_start, line.period_end, line.period_last_day),
                         (1, date(2026, 1, 15), date(2026, 1, 16), date(2026, 1, 15)))
        with self.assertRaises(ValidationError):
            self._contract(date(2026, 1, 15), date(2026, 1, 14))

    def test_full_calendar_year_end_date_is_last_occupied_day(self):
        contract = self._live(date(2026, 1, 1), date(2026, 12, 31))
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 12)
        self.assertFalse(any(lines.mapped('is_prorated')))
        self.assertEqual(sum(lines.mapped('amount')), 12000)
        self.assertEqual(lines[-1].period_end, date(2027, 1, 1))            # exclusive boundary
        self.assertEqual(lines[-1].period_last_day, date(2026, 12, 31))     # business-facing
        self.assertEqual(contract._term_boundary(), date(2027, 1, 1))

    def test_period_ending_on_31st_does_not_include_the_1st(self):
        contract = self._live(date(2026, 1, 1), date(2026, 3, 31))
        january, february, march = contract.schedule_line_ids
        self.assertEqual((january.period_last_day, february.period_start), (date(2026, 1, 31), date(2026, 2, 1)))
        self.assertEqual(january.period_end, february.period_start)         # adjacent, no overlap, no gap
        self.assertEqual([january.occupied_days, february.occupied_days, march.occupied_days], [31, 28, 31])
        self.assertIn('2026-01-31', january.description)
        self.assertNotIn('2026-02-01', january.description)

    def test_february_leap_year_full_month(self):
        contract = self._live(date(2028, 2, 1), date(2028, 2, 29))
        (line,) = contract.schedule_line_ids
        self.assertEqual((line.occupied_days, line.is_prorated, line.amount), (29, False, 1000))

    def test_overlap_boundary_is_inclusive(self):
        unit = self._unit()
        first = self._live(date(2026, 1, 1), date(2026, 6, 30), unit=unit)
        with self.assertRaises(ValidationError):                            # both occupy 30/06
            self._live(date(2026, 6, 30), date(2026, 12, 31), unit=unit)
        second = self._live(date(2026, 7, 1), date(2026, 12, 31), unit=unit)  # the day after: adjacent, allowed
        self.assertTrue(first.id and second.id)

    # ---------------- proration through the ORM ----------------

    def test_partial_lines_and_currencies(self):
        for code, rounding in (('ILS', 2), ('USD', 2), ('JOD', 3)):
            cur = self.currencies[code]
            contract = self._live(date(2026, 1, 13), date(2026, 1, 31), currency_id=cur.id)
            (line,) = contract.schedule_line_ids
            self.assertEqual(line.currency_id, cur)
            self.assertEqual(line.amount, round(1000 * 19 / 31, rounding), code)
            contract = self._live(date(2026, 1, 1), date(2026, 3, 31), rent=3000, freq='quarterly', currency_id=cur.id)
            self.assertEqual(contract.schedule_line_ids.mapped('amount'), [3000.0])

    def test_quarterly_and_yearly_full_periods_are_exact(self):
        quarterly = self._live(date(2026, 1, 1), date(2026, 12, 31), rent=3000, freq='quarterly')
        self.assertEqual(quarterly.schedule_line_ids.mapped('amount'), [3000.0] * 4)
        yearly = self._live(date(2026, 1, 1), date(2028, 12, 31), rent=12000, freq='yearly')
        self.assertEqual(yearly.schedule_line_ids.mapped('amount'), [12000.0] * 3)
        odd = self._live(date(2026, 1, 1), date(2026, 3, 31), rent=999.99, freq='quarterly')
        self.assertEqual(odd.schedule_line_ids.mapped('amount'), [999.99])

    def test_yearly_three_and_six_months_via_contract(self):
        three = self._live(date(2026, 1, 1), date(2026, 3, 31), rent=12000, freq='yearly')
        six = self._live(date(2026, 1, 1), date(2026, 6, 30), rent=12000, freq='yearly')
        self.assertEqual(three.schedule_line_ids.amount, 3000)
        self.assertEqual(six.schedule_line_ids.amount, 6000)

    def test_monthly_equivalent_field_is_not_a_calculation_input(self):
        # the stored field is rounded (report only); 1000 / 3 partial must still come from the exact 333.333...
        contract = self._live(date(2026, 1, 1), date(2026, 1, 10), rent=1000, freq='quarterly')
        self.assertEqual(contract.monthly_equivalent_rent, 333.33)
        self.assertEqual(contract.schedule_line_ids.amount, round(1000 / 3 * 10 / 31, 2))

    def test_day_31_and_leap_day_anchors_are_preserved(self):
        contract = self._live(date(2026, 1, 31), date(2026, 5, 30))
        self.assertEqual(contract.schedule_line_ids.mapped('period_start'),
                         [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])
        self.assertEqual(contract.schedule_line_ids.mapped('amount'), [1000.0] * 4)
        leap = self._live(date(2028, 2, 29), date(2029, 2, 28))
        starts = leap.schedule_line_ids.mapped('period_start')
        self.assertEqual((starts[0], starts[1], starts[12]), (date(2028, 2, 29), date(2028, 3, 29), date(2029, 2, 28)))
        self.assertEqual(len(starts), 13)
        self.assertEqual(leap.schedule_line_ids[-1].period_end, date(2029, 3, 1))   # boundary of 28/02/2029
        self.assertEqual(leap.schedule_line_ids[-1].occupied_days, 1)

    # ---------------- duplicate protection / extension ----------------

    def test_generating_twice_never_duplicates_a_period(self):
        contract = self._live(date(2026, 1, 1), date(2026, 12, 31))
        ids = contract.schedule_line_ids.ids
        contract._generate_schedule_lines()
        self.assertEqual(contract.schedule_line_ids.ids, ids)

    def test_overlapping_period_on_the_same_unit_is_rejected(self):
        contract = self._live(date(2026, 1, 1), date(2026, 3, 31))
        with self.assertRaises(ValidationError):
            self.env['edara.payment.schedule.line'].create({
                'contract_id': contract.id, 'due_date': date(2026, 2, 10),
                'period_start': date(2026, 2, 10), 'period_end': date(2026, 2, 20), 'amount': 1})
        # an adjacent period (starts on the existing boundary) is fine
        self.env['edara.payment.schedule.line'].create({
            'contract_id': contract.id, 'due_date': date(2026, 4, 1),
            'period_start': date(2026, 4, 1), 'period_end': date(2026, 4, 5), 'amount': 1})

    def test_extension_adds_only_missing_periods_and_keeps_invoices(self):
        contract = self._live(date(2026, 1, 1), date(2026, 12, 31))
        invoiced = contract.schedule_line_ids[:3]
        invoices = [line._create_invoice() for line in invoiced]
        before = contract.schedule_line_ids
        snapshot = {l.id: (l.period_start, l.period_end, l.amount, l.invoice_id.id) for l in before}
        contract.end_date = date(2027, 3, 31)
        after = contract.schedule_line_ids
        self.assertEqual(len(after), 15)
        self.assertEqual(set(before.ids), set(after.ids) & set(before.ids))         # nothing recreated
        for line in before:
            self.assertEqual((line.period_start, line.period_end, line.amount, line.invoice_id.id), snapshot[line.id])
        new = after - before
        self.assertEqual(new.mapped('period_start'), [date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1)])
        self.assertEqual(new.mapped('amount'), [1000.0] * 3)
        self.assertEqual(sum(1 for l in after if l.invoice_id), 3)
        self.assertEqual([l.invoice_id for l in invoiced], invoices)
        # no period appears twice
        self.assertEqual(len(set(after.mapped('period_start'))), 15)

    def test_extension_of_uninvoiced_partial_tail_recuts_the_tail(self):
        contract = self._live(date(2026, 1, 1), date(2026, 12, 19))
        self.assertEqual(contract.schedule_line_ids[-1].amount, 612.90)              # 19/31
        contract.end_date = date(2027, 2, 15)
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 14)
        self.assertEqual(lines[11].period_end, date(2027, 1, 1))
        self.assertEqual((lines[11].is_prorated, lines[11].amount), (False, 1000.0))
        self.assertEqual((lines[13].amount, lines[13].occupied_days), (535.71, 15))   # 15/28 of Feb 2027

    def test_extension_of_invoiced_partial_tail_bills_the_remainder_once(self):
        contract = self._live(date(2026, 1, 1), date(2026, 12, 19))
        tail = contract.schedule_line_ids[-1]
        tail._create_invoice()
        contract.end_date = date(2027, 2, 15)
        lines = contract.schedule_line_ids
        self.assertEqual(lines[11], tail)                                             # untouched
        self.assertEqual((tail.period_end, tail.amount), (date(2026, 12, 20), 612.90))
        stub = lines[12]
        self.assertEqual((stub.period_start, stub.period_end, stub.amount), (date(2026, 12, 20), date(2027, 1, 1), 387.10))
        self.assertEqual(tail.amount + stub.amount, 1000)                             # December billed exactly once
        self.assertEqual(lines.mapped('period_start')[13:], [date(2027, 1, 1), date(2027, 2, 1)])
        self.assertEqual(lines[-1].amount, 535.71)

    def test_extension_by_one_day(self):
        contract = self._live(date(2026, 1, 1), date(2026, 12, 31))
        contract.end_date = date(2027, 1, 1)
        new = contract.schedule_line_ids[-1]
        self.assertEqual((new.period_start, new.occupied_days, new.amount), (date(2027, 1, 1), 1, 32.26))

    def test_end_date_cannot_be_shortened_on_a_confirmed_lease(self):
        contract = self._live(date(2026, 1, 1), date(2026, 12, 31))
        with self.assertRaises(UserError):
            contract.end_date = date(2026, 11, 30)
        draft = self._contract(date(2026, 1, 1), date(2026, 12, 31))
        draft.end_date = date(2026, 6, 30)                                            # drafts are free to change
        self.assertFalse(draft.schedule_line_ids)

    def test_invoiced_history_is_never_recomputed(self):
        contract = self._live(date(2026, 1, 13), date(2026, 1, 31))
        line = contract.schedule_line_ids
        line._create_invoice()
        amount, invoice = line.amount, line.invoice_id
        contract._generate_schedule_lines()
        self.assertEqual((contract.schedule_line_ids, line.amount, line.invoice_id), (line, amount, invoice))

    # ---------------- renewal / scheduled successor / occupancy ----------------

    def _current_and_successor(self):
        today = self.today
        unit = self._unit()
        current = self._live(today - timedelta(days=100), today + timedelta(days=30), unit=unit)
        successor = current.action_renew(today + timedelta(days=31), today + timedelta(days=395), 1100)
        return unit, current, successor

    def test_renewal_creates_scheduled_successor_and_keeps_current_active(self):
        unit, current, successor = self._current_and_successor()
        self.assertEqual((current.state, successor.state), ('active', 'scheduled'))
        self.assertEqual(current.successor_contract_id, successor)
        self.assertEqual(successor.predecessor_contract_id, current)
        self.assertEqual(unit.occupancy_status, 'rented')                              # not 'reserved'
        self.assertTrue(successor.schedule_line_ids)
        self.assertEqual(successor.schedule_line_ids[0].period_start, successor.start_date)
        self.assertEqual(current.schedule_line_ids[-1].period_end, successor.start_date)  # no gap, no overlap

    def test_scheduled_successor_protects_the_unit_from_double_leasing(self):
        unit, current, successor = self._current_and_successor()
        with self.assertRaises(ValidationError):
            self._live(self.today + timedelta(days=100), self.today + timedelta(days=200), unit=unit)

    def test_renewal_must_start_after_the_current_last_day(self):
        unit = self._unit()
        current = self._live(self.today - timedelta(days=100), self.today + timedelta(days=30), unit=unit)
        with self.assertRaises(UserError):                                            # same day as end_date: overlap
            current.action_renew(current.end_date, current.end_date + timedelta(days=365), 1000)
        self.assertFalse(current.successor_contract_id)
        ok = current.action_renew(current.end_date + timedelta(days=1), current.end_date + timedelta(days=365), 1000)
        self.assertEqual(ok.state, 'scheduled')
        with self.assertRaises(UserError):                                            # one live renewal only
            current.action_renew(current.end_date + timedelta(days=1), current.end_date + timedelta(days=365), 1000)

    def test_backdated_successor_is_rejected_and_bills_nothing(self):
        unit = self._unit()
        current = self._live(self.today - timedelta(days=100), self.today + timedelta(days=30), unit=unit)
        invoices_before = self.env['account.move'].search_count([('edara_contract_id', '=', current.id)])
        with self.assertRaises(UserError):
            current.action_renew(self.today - timedelta(days=50), self.today + timedelta(days=300), 1000)
        self.assertFalse(current.successor_contract_id)
        self.assertEqual(current.state, 'active')
        self.assertEqual(self.env['edara.lease.contract'].search_count([('predecessor_contract_id', '=', current.id)]), 0)
        self.assertEqual(self.env['account.move'].search_count([('edara_contract_id', '=', current.id)]), invoices_before)

    def test_scheduled_lease_cannot_be_invoiced(self):
        unit, current, successor = self._current_and_successor()
        line = successor.schedule_line_ids[:1]
        created, skipped, errors = line._process_due_invoices()
        self.assertEqual((created, skipped, errors), (0, 1, 0))
        self.assertFalse(line.invoice_id)

    def test_confirm_activation_and_invoicing_are_separate(self):
        today = self.today
        contract = self._contract(today + timedelta(days=10), today + timedelta(days=200))
        self.assertFalse(contract.schedule_line_ids)
        contract.action_activate()                                                    # confirm: schedule, no invoice
        self.assertEqual(contract.state, 'scheduled')
        line_ids = contract.schedule_line_ids.ids
        self.assertTrue(line_ids)
        self.assertFalse(contract.schedule_line_ids.invoice_id)
        with self._at(today + timedelta(days=10)):                                    # start date arrives: activation only
            self.env['edara.lease.contract']._cron_expire_contracts()
            self.assertEqual(contract.state, 'active')
            self.assertEqual(contract.schedule_line_ids.ids, line_ids)                # schedule not regenerated
            self.assertFalse(contract.schedule_line_ids.invoice_id)                   # activation did not invoice
            contract.schedule_line_ids.filtered(lambda l: l.due_date <= self.today + timedelta(days=10))._process_due_invoices()
            self.assertEqual(contract.schedule_line_ids.ids, line_ids)
            self.assertEqual(len(contract.schedule_line_ids.filtered('invoice_id')), 1)

    def test_daily_job_moves_scheduled_to_active_and_current_to_renewed(self):
        unit, current, successor = self._current_and_successor()
        Contract = self.env['edara.lease.contract']
        with self._at(current.end_date):                                              # last occupied day
            Contract._cron_expire_contracts()
            self.assertEqual((current.state, successor.state), ('active', 'scheduled'))
            self.assertEqual(unit.occupancy_status, 'rented')
        with self._at(successor.start_date):                                          # the boundary day
            Contract._cron_expire_contracts()
            self.assertEqual((current.state, successor.state), ('renewed', 'active'))
            self.assertEqual(unit.occupancy_status, 'rented')
            Contract._cron_expire_contracts()                                         # idempotent
            self.assertEqual((current.state, successor.state), ('renewed', 'active'))

    def test_daily_job_expires_a_lease_without_successor_and_frees_the_unit(self):
        unit = self._unit()
        contract = self._live(self.today - timedelta(days=100), self.today + timedelta(days=30), unit=unit)
        with self._at(contract.end_date + timedelta(days=1)):
            self.env['edara.lease.contract']._cron_expire_contracts()
            self.assertEqual(contract.state, 'expired')
            self.assertEqual(unit.occupancy_status, 'available')

    def test_scheduled_only_unit_is_reserved_and_current_plus_future_is_rented(self):
        unit = self._unit()
        future = self._live(self.today + timedelta(days=20), self.today + timedelta(days=80), unit=unit)
        self.assertEqual((future.state, unit.occupancy_status), ('scheduled', 'reserved'))
        current = self._live(self.today - timedelta(days=100), self.today + timedelta(days=19), unit=unit)
        self.assertEqual(unit.occupancy_status, 'rented')
        current.action_terminate(reason='t')
        self.assertEqual(unit.occupancy_status, 'reserved')                           # only the future lease remains
        future.action_cancel()
        self.assertEqual((future.state, unit.occupancy_status), ('cancelled', 'available'))

    def test_terminating_the_current_lease_cancels_its_scheduled_successor(self):
        unit, current, successor = self._current_and_successor()
        current.action_terminate(reason='tenant left')
        self.assertEqual((current.state, successor.state), ('terminated', 'cancelled'))
        self.assertFalse(successor.schedule_line_ids)
        self.assertFalse(current.successor_contract_id)
        self.assertEqual(unit.occupancy_status, 'available')

    def test_scheduled_contract_that_cannot_start_stays_scheduled_and_alerts(self):
        unit = self._unit()
        contract = self._live(self.today + timedelta(days=5), self.today + timedelta(days=100), unit=unit)
        unit.occupancy_status = 'sold'
        with self._at(self.today + timedelta(days=5)):
            self.env['edara.lease.contract']._cron_expire_contracts()
            self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(contract.state, 'scheduled')
        self.assertEqual(len(contract.activity_ids.filtered(lambda a: 'could not start' in a.summary)), 1)

    def test_scheduled_lease_overlapping_a_live_one_does_not_break_the_daily_job(self):
        """Legacy data: a successor entered on the predecessor's last day (old exclusive style)."""
        unit = self._unit()
        current = self._live(self.today - timedelta(days=100), self.today + timedelta(days=30), unit=unit)
        legacy = self._contract(self.today + timedelta(days=31), self.today + timedelta(days=100), unit=unit)
        legacy.action_activate()
        self.env.cr.execute("UPDATE edara_lease_contract SET start_date = %s WHERE id = %s",
                            (current.end_date, legacy.id))
        legacy.invalidate_recordset()
        with self._at(current.end_date + timedelta(days=1)):
            self.env['edara.lease.contract']._cron_expire_contracts()   # must not raise
        self.assertEqual(legacy.state, 'scheduled')
        self.assertEqual(len(legacy.activity_ids.filtered(lambda a: 'could not start' in a.summary)), 1)

    def test_maintenance_status_unit_keeps_its_rule(self):
        unit = self._unit()
        unit.write({'occupancy_status': 'owner_occupied', 'operational_status': 'under_maintenance'})
        with self.assertRaises(UserError):
            self._live(self.today, self.today + timedelta(days=30), unit=unit)

    # ---------------- migration ----------------

    def test_state_migration_is_idempotent_and_touches_states_only(self):
        spec = importlib.util.spec_from_file_location(
            'p10_migration', os.path.join(os.path.dirname(__file__), '..', 'migrations', '19.0.1.1.0', 'post-migration.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        future = self._live(self.today + timedelta(days=10), self.today + timedelta(days=50))
        old_renewed = self._live(self.today - timedelta(days=100), self.today + timedelta(days=20))
        ended = self._live(self.today - timedelta(days=200), self.today - timedelta(days=100))
        lines = (future | old_renewed).schedule_line_ids.ids
        self.env.cr.execute("UPDATE edara_lease_contract SET state='active' WHERE id=%s", (future.id,))
        self.env.cr.execute("UPDATE edara_lease_contract SET state='renewed' WHERE id IN %s", ((old_renewed.id, ended.id),))
        mod.migrate(self.env.cr, '19.0.1.0.0')
        mod.migrate(self.env.cr, '19.0.1.0.0')
        self.env.invalidate_all()
        self.assertEqual((future.state, old_renewed.state, ended.state), ('scheduled', 'active', 'renewed'))
        self.assertEqual((future | old_renewed).schedule_line_ids.ids, lines)
