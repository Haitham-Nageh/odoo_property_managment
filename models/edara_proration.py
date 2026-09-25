"""Phase 10.1 - pure (no ORM) lease-date / proration maths.

Policy: docs/PRORATION_POLICY_DECISION.md (Period-Relative Actual/Actual, cumulative rounding).
Everything here is exact (fractions.Fraction); the only rounding is one HALF-UP step per
*cumulative* value, so the pieces of a billing period always add up to its rent.

Date convention: the business end_date is the LAST occupied day; every interval is the
half-open [start, term_boundary(end_date)).
"""
from datetime import timedelta
from fractions import Fraction

from dateutil.relativedelta import relativedelta


def term_boundary(end_date):
    """The single place the business end date becomes the exclusive boundary."""
    return end_date + timedelta(days=1)


def month_boundary(start, months):
    """Anchor boundary, always computed fresh from `start` (never chained), so a day-31 / leap-day
    anchor self-heals after a short month."""
    return start + relativedelta(months=months)


def period_index(start, n, x):
    """k such that x is in [start + k*n months, start + (k+1)*n months)."""
    k = 0
    while month_boundary(start, (k + 1) * n) <= x:
        k += 1
    return k


def accrued(start, n, k, x, rent):
    """Exact rent accrued from the start of billing period k (n months long) up to boundary x.
    rent is one period's rent; each anchored month earns rent/n, a part of a month earns
    occupied days / actual days of that anchored month."""
    p0, p1 = month_boundary(start, k * n), month_boundary(start, (k + 1) * n)
    assert p0 <= x <= p1, (p0, x, p1)
    if x == p1:
        return Fraction(rent)
    j = k * n
    while month_boundary(start, j + 1) <= x:
        j += 1
    m0, m1 = month_boundary(start, j), month_boundary(start, j + 1)
    return Fraction(rent) / n * (j - k * n + Fraction((x - m0).days, (m1 - m0).days))


def round_units(value, rounding):
    """value (Fraction) in whole `rounding` units, HALF-UP (Odoo float_round's default)."""
    units = Fraction(value) / rounding
    return (2 * units.numerator + units.denominator) // (2 * units.denominator)


def piece_amount(start, n, k, a, b, rent, rounding):
    """round(F(b)) - round(F(a)) as a float (currency.round-clean). rent is a Fraction or str/number
    convertible exactly; rounding is the currency's rounding as a Fraction."""
    rent = Fraction(rent)
    delta = (round_units(accrued(start, n, k, b, rent), rounding)
             - round_units(accrued(start, n, k, a, rent), rounding))
    return float(delta * rounding)


def piece_lines(start, n, rent, rounding, covered_to, boundary):
    """Lines for [covered_to, boundary): a list of (period_start, period_end, is_prorated, amount).
    covered_to must be `start` or the end of an existing line; one line per billing period."""
    rent = Fraction(rent)
    out = []
    a = covered_to
    while a < boundary:
        k = period_index(start, n, a)
        p0, p1 = month_boundary(start, k * n), month_boundary(start, (k + 1) * n)
        b = min(p1, boundary)
        whole = a == p0 and b == p1
        out.append((a, b, not whole, float(rent) if whole else piece_amount(start, n, k, a, b, rent, rounding)))
        a = b
    return out
