from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraLeaseBilling(TransactionCase):
    """Regression coverage for the finalized billing-anchor / proration
    rules: Payment Day derived from Start Date, exclusive End Date, a
    standardized 30-day proration reference, and a fresh-from-start_date
    billing anchor that never drifts (day-31 / leap-day)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Nablus Branch', 'code': 'NAB'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Rafidia Towers', 'code': 'RAF', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Tower 1', 'code': 'T1', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'T1-301', 'code': '301', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Nour Hamdan'})

    def _make_contract(self, **overrides):
        vals = {
            'unit_id': self.unit.id,
            'tenant_id': self.tenant.id,
            'start_date': date(2026, 9, 1),
            'end_date': date(2027, 9, 1),
            'rent_amount': 900,
            'billing_frequency': 'monthly',
            'deposit_required': False,
        }
        vals.update(overrides)
        return self.env['edara.lease.contract'].create(vals)

    def _activate(self, **overrides):
        contract = self._make_contract(**overrides)
        contract.action_activate()
        return contract

    # -- 1: Monthly full period --

    def test_monthly_full_period(self):
        contract = self._activate(start_date=date(2026, 9, 1), end_date=date(2026, 10, 1), rent_amount=900)
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.period_start, date(2026, 9, 1))
        self.assertEqual(lines.period_end, date(2026, 10, 1))
        self.assertFalse(lines.is_prorated)
        self.assertEqual(lines.amount, 900)

    # -- 2: Monthly partial, short --

    def test_monthly_partial_short(self):
        contract = self._activate(start_date=date(2026, 9, 3), end_date=date(2026, 9, 10), rent_amount=900)
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines.is_prorated)
        self.assertEqual(lines.occupied_days, 7)
        self.assertEqual(lines.amount, 210)

    # -- 3: Monthly partial spanning full months + a prorated tail --

    def test_monthly_partial_with_full_months(self):
        contract = self._activate(start_date=date(2026, 9, 3), end_date=date(2026, 12, 1), rent_amount=900)
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines.mapped('period_start'), [date(2026, 9, 3), date(2026, 10, 3), date(2026, 11, 3)])
        self.assertEqual(lines.mapped('period_end'), [date(2026, 10, 3), date(2026, 11, 3), date(2026, 12, 1)])
        self.assertEqual(lines.mapped('is_prorated'), [False, False, True])
        self.assertEqual(lines.mapped('amount'), [900, 900, 840])
        self.assertEqual(lines[2].occupied_days, 28)

    # -- 4: Monthly full, mid-month anchor --

    def test_monthly_full_midmonth(self):
        contract = self._activate(start_date=date(2026, 9, 15), end_date=date(2026, 10, 15), rent_amount=900)
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines.is_prorated)
        self.assertEqual(lines.amount, 900)

    # -- 5: Annual, 6-month contract --

    def test_annual_six_month_contract(self):
        """MAT-FIND-013: shorter than one full yearly period -> ONE
        prorated line (181 real days / 30), not six monthly-equivalent
        lines - a yearly-billed contract is never decomposed by month."""
        contract = self._activate(
            start_date=date(2026, 1, 1), end_date=date(2026, 7, 1),
            rent_amount=12000, billing_frequency='yearly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines.is_prorated)
        self.assertEqual(lines.occupied_days, 181)
        self.assertEqual(lines.amount, 6033.33)

    # -- 6: Annual, 15-day contract --

    def test_annual_fifteen_day_contract(self):
        contract = self._activate(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 16),
            rent_amount=12000, billing_frequency='yearly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines.is_prorated)
        self.assertEqual(lines.occupied_days, 15)
        self.assertEqual(lines.amount, 500)

    # -- 7: Full quarterly period stays ONE line --

    def test_quarterly_full_period(self):
        contract = self._activate(
            start_date=date(2026, 1, 1), end_date=date(2026, 4, 1),
            rent_amount=3000, billing_frequency='quarterly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines.is_prorated)
        self.assertEqual(lines.amount, 3000)

    # -- 8/MAT-FIND-013: a quarterly period shorter than 3 months is ONE
    # prorated line, never decomposed into monthly-equivalent chunks --

    def test_quarterly_partial_period(self):
        contract = self._activate(
            start_date=date(2026, 1, 15), end_date=date(2026, 4, 1),
            rent_amount=3000, billing_frequency='quarterly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines.is_prorated)
        self.assertEqual(lines.occupied_days, 76)
        self.assertEqual(lines.amount, 2533.33)

    def test_quarterly_multiple_full_periods(self):
        """MAT-FIND-013 matrix #7: multiple full quarters -> one line per quarter."""
        contract = self._activate(
            start_date=date(2026, 1, 1), end_date=date(2026, 7, 1),
            rent_amount=3000, billing_frequency='quarterly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines.mapped('period_start'), [date(2026, 1, 1), date(2026, 4, 1)])
        self.assertEqual(lines.mapped('period_end'), [date(2026, 4, 1), date(2026, 7, 1)])
        self.assertFalse(any(lines.mapped('is_prorated')))
        self.assertEqual(lines.mapped('amount'), [3000, 3000])

    def test_quarterly_full_periods_plus_prorated_remainder(self):
        """MAT-FIND-013 matrix #8: full quarters stay whole, only the
        leftover shorter-than-a-quarter remainder is prorated."""
        contract = self._activate(
            start_date=date(2026, 1, 15), end_date=date(2026, 8, 1),
            rent_amount=3000, billing_frequency='quarterly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines.mapped('is_prorated'), [False, False, True])
        self.assertEqual(lines.mapped('amount'), [3000, 3000, 566.67])
        self.assertEqual(lines[2].occupied_days, 17)

    def test_quarterly_short_period_does_not_decompose_into_monthly_lines(self):
        """MAT-FIND-013 matrix #9: a 2-month quarterly stub must stay ONE
        line, not split into two monthly-equivalent lines."""
        contract = self._activate(
            start_date=date(2026, 9, 15), end_date=date(2026, 11, 15),
            rent_amount=3000, billing_frequency='quarterly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines.is_prorated)
        self.assertEqual(lines.occupied_days, 61)
        self.assertEqual(lines.amount, 2033.33)

    # -- 10-13: Yearly billing granularity --

    def test_yearly_full_period(self):
        contract = self._activate(
            start_date=date(2026, 9, 1), end_date=date(2027, 9, 1),
            rent_amount=12000, billing_frequency='yearly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines.is_prorated)
        self.assertEqual(lines.amount, 12000)

    def test_yearly_short_period_single_prorated_line(self):
        contract = self._activate(
            start_date=date(2026, 9, 15), end_date=date(2026, 12, 1),
            rent_amount=12000, billing_frequency='yearly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines.is_prorated)
        self.assertEqual(lines.occupied_days, 77)
        self.assertEqual(lines.amount, 2566.67)

    def test_yearly_multiple_full_periods(self):
        contract = self._activate(
            start_date=date(2025, 1, 1), end_date=date(2028, 1, 1),
            rent_amount=12000, billing_frequency='yearly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 3)
        self.assertFalse(any(lines.mapped('is_prorated')))
        self.assertEqual(lines.mapped('amount'), [12000, 12000, 12000])

    def test_yearly_full_period_plus_prorated_remainder(self):
        contract = self._activate(
            start_date=date(2025, 1, 1), end_date=date(2026, 7, 15),
            rent_amount=12000, billing_frequency='yearly')
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines.mapped('is_prorated'), [False, True])
        self.assertEqual(lines[0].amount, 12000)
        self.assertEqual(lines[1].occupied_days, 195)
        self.assertEqual(lines[1].amount, 6500)

    # -- 9: MAT-FIND-011 - must produce exactly one line, never zero --

    def test_mat_find_011_scenario(self):
        contract = self._activate(start_date=date(2026, 9, 2), end_date=date(2026, 10, 1), rent_amount=1600)
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertEqual(contract.payment_day, 2)
        self.assertEqual(lines.period_start, date(2026, 9, 2))
        self.assertEqual(lines.period_end, date(2026, 10, 1))
        self.assertEqual(lines.occupied_days, 29)
        self.assertTrue(lines.is_prorated)
        self.assertEqual(lines.amount, 1546.67)

    # -- 10: MAT-FIND-005 - end_date must remain exclusive --

    def test_mat_find_005_scenario(self):
        contract = self._activate(start_date=date(2026, 8, 1), end_date=date(2026, 9, 1), rent_amount=1500)
        lines = contract.schedule_line_ids
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.due_date, date(2026, 8, 1))
        self.assertNotIn(date(2026, 9, 1), lines.mapped('due_date'))

    # -- 11/12/13: Payment Day is derived, follows Start Date, not editable --

    def test_payment_day_derives_from_start_date(self):
        contract = self._make_contract(start_date=date(2026, 9, 3))
        self.assertEqual(contract.payment_day, 3)

    def test_payment_day_follows_start_date_change(self):
        contract = self._make_contract(start_date=date(2026, 9, 3))
        self.assertEqual(contract.payment_day, 3)
        contract.start_date = date(2026, 9, 17)
        self.assertEqual(contract.payment_day, 17)

    def test_payment_day_field_is_not_independently_editable(self):
        field_info = self.env['edara.lease.contract'].fields_get(['payment_day'])['payment_day']
        self.assertTrue(field_info['readonly'])
        self.assertIn('start_date', field_info['depends'])

    # -- 14: Day-31 anchor restoration --

    def test_day31_anchor_restoration(self):
        contract = self._activate(start_date=date(2026, 1, 31), end_date=date(2026, 5, 31), rent_amount=900)
        lines = contract.schedule_line_ids
        self.assertEqual(contract.payment_day, 31)
        self.assertEqual(
            lines.mapped('period_start'),
            [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])
        self.assertEqual(
            lines.mapped('period_end'),
            [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31)])
        self.assertFalse(any(lines.mapped('is_prorated')))

    # -- 15: Leap-day anchor, no permanent drift --

    def test_leap_day_anchor_no_drift(self):
        contract = self._activate(start_date=date(2028, 2, 29), end_date=date(2028, 5, 31), rent_amount=900)
        lines = contract.schedule_line_ids
        self.assertEqual(contract.payment_day, 29)
        self.assertEqual(len(lines), 4)
        self.assertEqual(
            lines.mapped('period_start'),
            [date(2028, 2, 29), date(2028, 3, 29), date(2028, 4, 29), date(2028, 5, 29)])
        self.assertEqual(
            lines.mapped('period_end'),
            [date(2028, 3, 29), date(2028, 4, 29), date(2028, 5, 29), date(2028, 5, 31)])
        self.assertEqual(lines.mapped('is_prorated'), [False, False, False, True])
        self.assertEqual(lines[3].occupied_days, 2)

    # -- 17: A valid contract can never produce zero schedule lines --

    def test_zero_line_outcome_structurally_impossible(self):
        for start, end in [
            (date(2026, 9, 1), date(2026, 9, 2)),   # 1 day
            (date(2026, 9, 30), date(2026, 10, 1)),  # 1 day, month boundary
            (date(2026, 12, 31), date(2027, 1, 1)),  # 1 day, year boundary
        ]:
            contract = self._activate(start_date=start, end_date=end, rent_amount=900)
            self.assertTrue(contract.schedule_line_ids, "no schedule line for %s -> %s" % (start, end))

        for frequency, rent, start in [
            ('quarterly', 3000, date(2026, 10, 10)),
            ('yearly', 12000, date(2026, 11, 10)),
        ]:
            contract = self._activate(
                start_date=start, end_date=start + timedelta(days=1),
                rent_amount=rent, billing_frequency=frequency)
            self.assertEqual(len(contract.schedule_line_ids), 1, "no schedule line for %s" % frequency)
