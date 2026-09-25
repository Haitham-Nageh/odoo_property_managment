# Lease Date & Payment Schedule Engine (Phase 10.1)

Developer reference for how EDARA turns a lease's dates and rent into payment-schedule lines.
The reasoning and evidence live in `PRORATION_POLICY_DECISION.md` (OD-N1) and
`LEASE_LIFECYCLE_DECISIONS.md` (OD-B3/B5/B6/B9, section 5); this file only describes what the code does.

Code: `models/edara_proration.py` (pure maths, no ORM), `models/edara_lease_contract.py`
(`_term_boundary`, `_generate_schedule_lines`, lifecycle), `models/edara_payment_schedule_line.py`
(period fields, disjointness constraint). Tests: `tests/test_edara_phase10_lease_engine.py`.

## 1. Dates: inclusive `end_date`, exclusive boundary

* `start_date` is the first occupied day, `end_date` is the **last occupied day**.
  `01/01/2026 -> 31/12/2026` means the tenant is in the unit through 31/12.
  `start_date == end_date` is a valid one-day lease; `end_date < start_date` is rejected.
* Interval logic uses one derived, half-open interval `[start_date, boundary)` with
  `boundary = end_date + 1 day`. It comes from exactly one place, `edara_proration.term_boundary()`
  (exposed as `contract._term_boundary()`). Nothing else adds or subtracts a day.
* Schedule lines store `period_start`, `period_end` (**exclusive boundary**, the next period starts
  there), and `period_last_day` (computed, business-facing `period_end - 1`). The meaning of
  `period_start`/`period_end` did not change. Invoice descriptions show the last day, not the boundary.
* Consumers: overlap check (`s1 <= e2 and s2 <= e1`), schedule generation, occupancy
  (`start <= today <= end_date`), expiry job (`end_date < today`), reminders, renewal default
  (`_term_boundary()`), calendar/portal (display the stored business date, no conversion).

## 2. Proration: Period-Relative Actual/Actual

Rent is a fixed amount per contractual (anchored) month; a day's price depends on the length of the
month it falls in. Billing periods are `[start + k*n months, start + (k+1)*n months)`, `n` = 1/3/12,
every boundary computed fresh from `start_date` (day-31 and leap-day anchors self-heal).

| Case | Amount |
|---|---|
| Whole billing period | exactly `rent_amount` (no arithmetic) |
| Part of a period | `round(F(b)) - round(F(a))` |
| `F(x)` | exact rent accrued from the period start to `x`: `rent/n` per whole anchored month, plus `days / actual days of that anchored month` of `rent/n` for the part-month |

Monthly: `rent x occupied days / days of that anchored month` (19 of 31 days of 1,000 = 612.90).
Quarterly: `rent/3` per month (exact, never the rounded `monthly_equivalent_rent`). Yearly: `rent/12`.
Leap years need no rule: February's anchored month simply has 29 days.

**Cumulative rounding.** Only cumulative values are rounded (one HALF-UP step, currency rounding: 0.01
ILS/USD, 0.001 JOD, identical to Odoo `float_round`). Pieces of one billing period therefore always sum to its
rent (`333.33 + 333.34 + 333.33 = 1000.00`), and a piece depends only on its own dates. Full periods are never
rounded. `monthly_equivalent_rent` (stored, rounded) is a report column only.

## 3. One line per billing period; generation by coverage

`_generate_schedule_lines()` never regenerates history. It keeps every invoiced line and every uninvoiced
line that covers a whole billing period, drops uninvoiced *prorated* lines (an unbilled partial tail is
re-cut), and creates lines only from the end of the last kept line to the boundary. It is idempotent.

Guards: `write()` on `end_date` (confirmed lease) accepts only a later date and triggers the same
generator; shortening raises (use Terminate). Schedule lines of one unit must be pairwise disjoint
(`_check_periods_disjoint`, across contracts, regardless of invoice state; adjacent periods are fine).

## 4. Extension (same contract, later end date)

| Situation | Result |
|---|---|
| End date moved later, all lines full/invoiced | only the missing periods are appended; existing lines untouched |
| Uninvoiced partial tail | tail deleted, re-cut inside the new range (Dec 1-19 becomes a whole December) |
| **Invoiced** partial tail | tail kept; a stub line finishes the anchored period (612.90 + 387.10 = 1,000.00), then normal periods |

Example: `01/01/2026 -> 31/12/2026` extended to `31/03/2027`: 12 existing lines untouched, 3 new lines
(Jan, Feb, Mar 2027).

## 5. Lifecycle (creation, activation, invoicing are separate events)

| Event | What it does | What it does not do |
|---|---|---|
| Confirm (`action_activate`) | preconditions; state `scheduled` if `start_date > today` else `active`; unit occupancy; **creates the schedule** | invoice anything |
| Start (daily job) | `scheduled -> active` when `start_date <= today` | touch the schedule |
| Invoicing (cron / manual) | invoices due lines of `active`/`renewed` contracts | create lines; touch `scheduled` contracts |
| Renewal (`action_renew`) | creates the successor (`scheduled`), links it; requires `start >= _term_boundary()` and no live successor | change the current lease |
| Term end (daily job) | `end_date < today`: `renewed` if a `scheduled`/`active` successor exists, else `expired` | |
| Terminate | current lease ends; a `scheduled` successor is cancelled in the same transaction | |
| Cancel (`action_cancel`) | `scheduled -> cancelled`, uninvoiced lines removed, reservation released | |

Daily job order (`_cron_expire_contracts`): activate due scheduled leases, then close finished ones, then
recompute occupancy. The successor starts at `predecessor.end_date + 1`, so both are briefly `active` with
disjoint dates. A scheduled lease that cannot start (unit sold / under maintenance) stays scheduled and
gets one to-do for the branch manager.

Occupancy: `rented` while an `active` lease covers today (also while a successor is scheduled);
`reserved` only if just a `scheduled` lease exists; otherwise `available`. `under_maintenance` rules
are unchanged.

## 6. Immutability

Invoiced lines are never regenerated, re-amounted or re-dated (Phase 7 amount freeze + `unlink` block +
generator keeps them). A cancelled/reversed invoice still consumes its period. The policy applies only to
lines generated after the release; nothing already generated or posted is recalculated or corrected.

## 7. Boundaries (not decided here)

Holdover after the end date, late renewal window (OD-B2), deposit carry-over (OD-B8), alternative-currency
payments, a separate Extend action/log (OD-B1), calendar-aligned billing. A renewal whose start is after the
boundary is allowed (a gap); nothing is billed for the gap.
