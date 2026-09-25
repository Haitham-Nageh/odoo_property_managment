# Phase 9.3 — Proration Policy Decision

**Decision closure for OD-N1. Analysis and deterministic simulation only.** No application code, XML, view, security file, manifest, test, configuration, database record or posted entry was changed. **No database of any kind was opened in this phase** (all arithmetic ran outside Odoo, on exact fractions).
Date: 2026-09-25. Baseline: `property_managment` 19.0.1.0.0, git HEAD `07cd5a1`, Odoo 19 Enterprise.
Builds on `LEASE_LIFECYCLE_RESEARCH.md`, `LEASE_LIFECYCLE_DECISIONS.md`, `LEASE_LIFECYCLE_VALIDATION.md` (none overwritten).

## Evidence labels

| Tag | Meaning |
|---|---|
| **[P]** | Primary text read in full (ISDA 2006 Definitions §4.16, IFRS 16, Odoo source or documentation). |
| **[V]** | Vendor or professional page whose content was fetched and read. |
| **[S]** | Search-result excerpt only, or a third-party page quoting a vendor. **Weak.** |
| **[L]** | Local EDARA or Odoo source, or the project state file. |
| **[C]** | Result of the deterministic simulation in this phase (exact fractions, no Odoo). |
| **[R]** | Reasoning by the author; not evidence. |

**Simulation validity.** Before any candidate was evaluated, the simulation's copy of the *current* algorithm was checked against the 11 amounts that the real test suite and the recorded live verifications already assert (210.00, 840.00, 6,033.33, 500.00, 2,533.33, 566.67, 2,033.33, 2,566.67, 1,546.67, 3,033.33 …). **All 11 were reproduced exactly [C].** Rounding was cross-checked against Odoo's own `float_round` on 3,294 values with **0 mismatches** [C].

---

## Executive Summary

1. **The current 30-day rule fails the additivity invariant on 85 of 114 split points** (every 2-piece split of a 28-, 29-, 30- and 31-day month). A 31-day month split 19 + 12 bills **1,033.33**; a 28-day month split 10 + 18 bills **933.33**; a 29-day month split 15 + 14 bills **966.67** [C]. It fails only in 30-day months.
2. **The defect is wider than splits.** Because a partial period is billed as `days ÷ 30` even when it contains whole months, three exact months of a yearly contract (01/09→01/12, 91 days) bill **3,033.33**, and six exact months (181 days) bill **6,033.33**, instead of 3,000.00 and 6,000.00 [C, reproduces recorded results].
3. **None of the other simple models is acceptable on its own.** ACT/365 bills a full 31-day month **1,019.18** and a full February **920.55**. 30/360 is additive but bills days that were not occupied (the last 10 days of February cost 400.00, i.e. 12 days' worth). Calendar-month allocation bills one whole anchored month **1,048.39** when the contract month runs 15/01→14/02.
4. **Recommended policy — Period-Relative Actual/Actual.** Rent is a fixed amount per contractual (anchored) month. A full period bills the rent exactly. A part of a month bills `rent ÷ months-per-period × occupied days ÷ actual days of that anchored month`. Quarterly and yearly rent are decomposed into their monthly equivalents so that the same span costs the same whatever the billing frequency. For **monthly** periods this is exactly the day-count Odoo's own Subscriptions module uses (`ratio = days ÷ days in the full period`) and the accrual form of ICMA Actual/Actual [L][P]. For **quarterly and yearly** rent EDARA deliberately goes one step further, decomposing into monthly equivalents so that a span costs the same at any billing frequency; that step is an EDARA design choice [R], not something the sources do (they use the days of the whole period, which is additive but not frequency-neutral; see § Quarterly Rent).
5. **It satisfies every invariant tested:** 0 of 114 failing splits; the sum of the pieces of a period is exactly the period rent; extension and renewal boundaries carry no gap or overlap; ILS, USD and JOD all reconcile (cumulative rounding failed in 0 of 23,550 three-piece cases, against 6,108 for independent rounding) [C].
6. **Cost of the change.** Six existing test amounts and two recorded live results change (§ "Current EDARA Behavior"). The rule being replaced was recorded as *finalized* on 2026-09-17, so this decision **needs the business owner's explicit approval**. Already-invoiced lines are never regenerated.
7. **One policy is recommended; there is no configurable alternative.** Vendor evidence shows both 30-day and actual-day methods in use and says the lease should state the method; whether EDARA's customers' signed contracts state one is an **open question** (owner/legal), listed separately.

---

## Current EDARA Behavior

**Source Evidence [L].** `edara.lease.contract._generate_schedule_lines()`:
- One line per billing period, anchored on the start date (`_period_boundary`, computed fresh from `start_date`).
- A period that fits before `end_date` bills `rent_amount` exactly.
- The final period that does not fit bills `monthly_equivalent × (period_end − period_start).days ÷ 30`, rounded once with `currency.round`, and is flagged `is_prorated`.
- `monthly_equivalent` is the stored, **already-rounded** Monetary field `monthly_equivalent_rent = rent_amount ÷ months` (for example 83.33 for a yearly rent of 1,000).
- `end_date` is exclusive inside this method; the Phase 9.1/9.2 decision changes that to an inclusive business date with the internal boundary `end_date + 1 day`.

**Recorded decision [L].** `EDARA_PROJECT_STATE.md`, MAT-FIND-013 ("finalized billing rules", live-verified 2026-09-17): "monthly-equivalent rate × occupied days / a standardized 30-day reference month", and explicitly that `01/09→01/12` yearly is **3,033.33, not 3,000**. The 30-day rule is therefore a deliberate earlier decision; this phase reopens it on new evidence (Phase 9.2 additivity failures), and keeps the parts of MAT-FIND-011/013 that are not about the divisor: one line per billing period, the start-day anchor, a full period equals the full rent, at least one line for any active contract.

**Tests that pin the current amounts [L].** `tests/test_edara_lease_billing.py`. Amounts under the recommended policy [C]:

| Test / recorded result | Current | Recommended policy |
|---|---:|---:|
| `test_monthly_partial_short` 03/09→10/09, rent 900 | 210.00 | 210.00 (unchanged) |
| `test_monthly_partial_with_full_months` | 900 / 900 / 840.00 | unchanged |
| MAT-030 live: 02/09→01/10, rent 1,600 | 1,546.67 | 1,546.67 (unchanged) |
| `test_annual_six_month_contract` 01/01→01/07, 12,000 | 6,033.33 | **6,000.00** |
| `test_annual_fifteen_day_contract` 01/01→16/01, 12,000 | 500.00 | **483.87** |
| `test_quarterly_partial_period` 15/01→01/04, 3,000 | 2,533.33 | **2,548.39** |
| `test_quarterly_full_periods_plus_prorated_remainder` | 566.67 | **548.39** |
| `test_quarterly_short_period…` 15/09→15/11 | 2,033.33 | **2,000.00** |
| `test_yearly_short_period_single_prorated_line` 15/09→01/12 | 2,566.67 | **2,533.33** |
| Live LC/0139 yearly 01/09→01/12 | 3,033.33 | **3,000.00** |
| Live LC/0137 quarterly final stub | 566.67 | **548.39** |

**Phase 9.2 findings carried in [L][C].** Splitting a 31-day month into 19- and 12-day lines bills 1,033.33; a stub after an invoiced prorated tail (633.33 + 400.00) bills 1,033.33 for one 31-day month.

---

## Research Evidence

### Accounting and standards
| Source | Finding | Grade |
|---|---|---|
| **ISDA 2006 Definitions §4.16** (text extracted from the PDF) | Defines the day count fractions: **Actual/Actual (ISDA)** splits leap and non-leap days over 366 and 365; **Actual/Actual (ICMA)** is "days accrued ÷ days in the period" of Rule 251; **Actual/365 (Fixed)** = actual days ÷ 365; **30/360 (Bond Basis)** = `[360(Y2−Y1) + 30(M2−M1) + (D2−D1)] ÷ 360` with D1 = 30 if 31, D2 = 30 if 31 and D1 > 29; **30E/360** caps both at 30. In every 30/360 variant the end date used is **the day immediately following the last day included in the period**, that is the same inclusive-end / exclusive-boundary convention EDARA adopted. | **[P]** |
| Wikipedia, *Day count convention* | Where used: 30/360 (US corporate bonds), 30E/360 (Eurobonds), Actual/360 (money markets), Actual/365F (sterling instruments), ICMA Actual/Actual ("ensures all coupon payments are always for the same amount"), ISDA Actual/Actual (derivatives). Secondary summary of the definitions above. | [V] |
| **IFRS 16 ¶81** (extracted) | A lessor recognises operating-lease payments as income "on either a straight-line basis or another systematic basis". Proration of invoiced rent is a billing convention; whether it is a systematic basis is an accountant question (below). | **[P]** |
| **IFRS 16 ¶87** (extracted; number now confirmed) | A lessor accounts for a modification of an operating lease as a new lease from the effective date. Consistent with prospective extension lines and no restatement of invoiced periods. (Earlier documents marked this paragraph number unverified.) | **[P]** |
| Odoo `sale_subscription/models/sale_order_line.py`, `_get_invoice_line_parameters` | Partial-period ratio = `number_of_days ÷ (period_stop − period_start).days`, i.e. days in the piece over the **actual days of the full billing period**; a full period has ratio 1. | **[L]** |

### Property-management platforms
| Platform | What the readable evidence says | Grade |
|---|---|---|
| **Yardi Breeze** (blog, https://www.yardibreeze.com/blog/2026/09/how-does-prorated-rent-work/) | Two methods: 30-day and actual days (28–31). Proration is **a property default, not a per-lease entry**; the move-in day is billable; full rent only if all days are occupied. *This is Yardi Breeze; nothing was obtained for Yardi Voyager.* | [V] |
| **MRI Rent Payment** (blog) | Daily rate = monthly rent ÷ days in the month, or annual rent ÷ 365; neither called standard. *This is a payments product page, not MRI's lease engine.* | [V] |
| **DoorLoop** (blog) | Actual days in the month is the primary method; annual/365 (or 366) is the alternative; recommends the agreement state the proration. | [V] |
| **Buildium** (blog, https://www.buildium.com/blog/introducing-prorated-rent-calculations/) | Prorates the first and last month automatically for **monthly recurring rent only**, shows the number of days used; the divisor is **not stated**. Its rule "lease end date differs from the day before the next charge" implies the end date is the last day of the term (an inference from the summary, not a stated definition). | [V] |
| **AppFolio** | Settings "30 Day Month" and "Actual Days in Month" (a third-party training PDF quoting AppFolio). | **[S]** |
| **Propertyware, Entrata, Yardi Voyager, MRI lease engine** | **No first-party evidence obtained.** No claim is made. | — |
| Consumer and calculator sites | Both methods are "accepted"; a few say some jurisdictions prescribe one. Not relied on (no authoritative legal source). | not used |

**What the vendor evidence does and does not establish.** (a) Both the 30-day method and the actual-days method exist in the market; the actual-days method is presented first by DoorLoop and is the general definition in the Yardi Breeze page. (b) Vendors configure the method once (property level) and recommend that the lease state it. (c) **No readable vendor page addresses quarterly or yearly rent, periods anchored on a start day, or splitting one month into several invoices.** Additivity across extensions is therefore an EDARA-specific requirement that no vendor source answers, and the period-relative form is supported instead by ICMA Actual/Actual and by Odoo's own Subscriptions code.

---

## Candidate Models

Definitions used (all with the end date inclusive and the boundary `B = end_date + 1 day`, so `occupied days = (B − start).days`):

| Model | Definition | Note |
|---|---|---|
| **A — 30-day fixed month** | Daily rate = monthly ÷ 30. Partial = daily × actual days. A complete period bills the rent. | **This is what EDARA does today.** It counts real calendar days and divides by 30; it is *not* 30/360 (Model C). |
| **B — Actual/actual, calendar month** | Partial = monthly × days ÷ days in the calendar month; a piece spanning two calendar months is split per month. | Exact for periods that start on the 1st. |
| **C — 30/360** | ISDA §4.16(f) day count (Bond Basis) or (g) (30E/360): every month has 30 days, a year 360; amount = monthly × D360 ÷ 30. | A bond-market convention. Days billed can differ from days occupied. |
| **D — Actual/365** | Annual rent (12 × monthly) × actual days ÷ 365 (ACT/365F), or ACT/ACT-ISDA (365/366). | A day rate derived from the annual rent. |
| **E — Period-relative actual/actual** | Partial = (rent ÷ months-per-period) × occupied days ÷ **actual days of the anchored contractual month those days belong to**. Whole months elapsed bill their exact share. | Model B applied to the contractual billing month instead of the calendar month. For a monthly period it is identical to ICMA Actual/Actual and to Odoo Subscriptions' ratio; for quarterly and yearly rent the monthly decomposition is an EDARA choice [R]. **Introduced because the evidence supports it, not to add an option.** |

The "explicit contractual daily rate" (a rate written in the lease) was **not** evaluated as a model: no source shows it, and it is the same arithmetic as D with a different number.

---

## Mathematical Comparison

Monthly rent 1,000, ILS [C]. "Reference share" is 1,000 × occupied days ÷ actual days of that month.

| Month length | Case | Days | A current | B / E | C 30/360 | D ACT/365F | Reference share |
|---|---|---:|---:|---:|---:|---:|---:|
| **31-day** (Jan 2026) | full month | 31 | 1,000.00 | 1,000.00 | 1,000.00 | **1,019.18** | 1,000.00 |
| | first 10 days | 10 | 333.33 | 322.58 | 333.33 | 328.77 | 322.58 |
| | last 10 days | 10 | 333.33 | 322.58 | **300.00** | 328.77 | 322.58 |
| | 1 day | 1 | 33.33 | 32.26 | 33.33 | 32.88 | 32.26 |
| **30-day** (Apr 2026) | full month | 30 | 1,000.00 | 1,000.00 | 1,000.00 | **986.30** | 1,000.00 |
| | first 10 / last 10 | 10 | 333.33 | 333.33 | 333.33 | 328.77 | 333.33 |
| | 1 day | 1 | 33.33 | 33.33 | 33.33 | 32.88 | 33.33 |
| **28-day** (Feb 2026) | full month | 28 | 1,000.00 | 1,000.00 | 1,000.00 | **920.55** | 1,000.00 |
| | first 10 days | 10 | 333.33 | 357.14 | 333.33 | 328.77 | 357.14 |
| | last 10 days | 10 | 333.33 | 357.14 | **400.00** | 328.77 | 357.14 |
| | 1 day | 1 | 33.33 | 35.71 | 33.33 | 32.88 | 35.71 |
| **29-day** (Feb 2028) | full month | 29 | 1,000.00 | 1,000.00 | 1,000.00 | **953.42** | 1,000.00 |
| | first 10 days | 10 | 333.33 | 344.83 | 333.33 | 328.77 | 344.83 |
| | last 10 days | 10 | 333.33 | 344.83 | **366.67** | 328.77 | 344.83 |
| | 1 day | 1 | 33.33 | 34.48 | 33.33 | 32.88 | 34.48 |

Daily rates: A 33.333333 in every month; B/E 32.258065 (31), 33.333333 (30), 35.714286 (28), 34.482759 (29); C 33.333333; D 32.876712.

Observations [C]:
- **A** agrees with the reference share only in a 30-day month; it under-bills partial pieces of a 28- or 29-day month and over-bills those of a 31-day month.
- **C** bills the last 10 days of a 31-day month as 9 days (300.00) and the last 10 days of February as 12 days (400.00): the day count is additive but **days billed do not equal days occupied**.
- **D** does not give the monthly rent for a full month in any month except by coincidence (a 30.42-day average month), which conflicts with "a full month bills the monthly rent".

---

## Split-Period Invariant

> *If a contractual month is split into consecutive schedule periods, the pieces must sum to the monthly rent, subject only to documented rounding.*

| Split | Model A current | Model B / E | Model C (bond) | Model D |
|---|---|---|---|---|
| 31-day, 1–19 + 20–31 (19 + 12) | 633.33 + 400.00 = **1,033.33** (+33.33) | 612.90 + 387.10 = **1,000.00** | 633.33 + 366.67 = 1,000.00 | 624.66 + 394.52 = 1,019.18 |
| 31-day, 1–15 + 16–31 (15 + 16) | 500.00 + 533.33 = **1,033.33** (+33.33) | 483.87 + 516.13 = **1,000.00** | 500.00 + 500.00 = 1,000.00 | 493.15 + 526.03 = 1,019.18 |
| 28-day, 1–10 + 11–28 (10 + 18) | 333.33 + 600.00 = **933.33** (−66.67) | 357.14 + 642.86 = **1,000.00** | 333.33 + 666.67 = 1,000.00 | 328.77 + 591.78 = 920.55 |
| 29-day, 1–15 + 16–29 (15 + 14) | 500.00 + 466.67 = **966.67** (−33.33) | 517.24 + 482.76 = **1,000.00** | 500.00 + 500.00 = 1,000.00 | 493.15 + 460.27 = 953.42 |
| 30-day, 1–15 + 16–30 (15 + 15) | 500.00 + 500.00 = 1,000.00 | 500.00 + 500.00 = **1,000.00** | 1,000.00 | 986.30 |

**Exhaustive check** (every 2-piece split point in every month length, 114 splits) [C]:

| Model | Failing splits | Largest deviation |
|---|---:|---:|
| A current | **85 of 114** | 66.67 |
| B / E | **0 of 114** | 0.00 |
| C 30/360 Bond Basis | 1 of 114 (the 31st-day split: D1 is forced to 30) | 33.33 |
| C 30E/360 | 0 of 114 | 0.00 |
| D ACT/365F | 114 of 114 | 79.45 |

B and E are additive **by construction**: the fractions `d1/D + d2/D` sum to 1. Model A is additive only when the month has exactly 30 days. 30/360 is additive but not faithful to occupied days (above).

---

## Multi-Month Partial Periods

Monthly 1,000, anchor = start day, end date inclusive, `B = end + 1`. Billing periods are the anchored months `[S + j months, S + (j+1) months)`; Model E allocates days to the anchored month they fall in [C].

| Case | Occupied days | Lines under the recommended policy | Total E | Current A | B-cal | 30/360 | ACT/365F |
|---|---:|---|---:|---:|---:|---:|---:|
| **A** 15/01→14/02 | 31 | `15/01→15/02` = 1,000.00 (one full anchored month) | **1,000.00** | 1,000.00 | 1,048.39 | 1,000.00 | 1,019.18 |
| **B** 15/01→15/02 | 32 | 1,000.00 + `15/02→16/02` 1 of 28 days = 35.71 | **1,035.71** | 1,033.33 | 1,084.10 | 1,033.33 | 1,052.05 |
| **C** 20/01→10/03 | 50 | 1,000.00 + `20/02→11/03` 19 of 28 days = 678.57 | **1,678.57** | 1,633.33 | 1,709.68 | 1,700.00 | 1,643.84 |
| **D** 31/01→28/02 | 29 | 1,000.00 (`31/01→28/02`, a 28-day anchored month) + `28/02→01/03` 1 of 31 days = 32.26 | **1,032.26** | 1,033.33 | 1,032.26 | 1,033.33 | 953.42 |
| **E** 31/01→01/03 | 30 | 1,000.00 + `28/02→02/03` 2 of 31 days = 64.52 | **1,064.52** | 1,066.67 | 1,064.52 | 1,066.67 | 986.30 |

Which days belong to which billing period: an anchored month starts on the start day's anniversary computed fresh from the start date (`31/01` → `28/02` → `31/03` → `30/04`); the days of a partial piece are counted against **that** month's actual length (28–31), not against a calendar month.

**Ambiguities identified.**
1. *Calendar-month allocation (B-cal) contradicts anchored billing*: Case A is exactly one contractual month and must bill the rent, but B-cal bills 1,048.39. This is why the calendar month is not the unit.
2. *Clamped anchors*: with a day-31 anchor the anchored month `31/01→28/02` has 28 days and the next has 31; the length used is the anchored month's own length. This uses the existing `_period_boundary` unchanged.
3. *Which month a trailing day belongs to* is fixed by the boundaries: a piece never crosses a boundary because schedule lines are per billing period.

**Additivity.** Model E is additive across pieces of one period and across periods (a piece's amount depends only on its own start and end, see § Rounding). Model A is not additive when the month has 28, 29 or 31 days.

---

## Quarterly Rent

Quarterly rent 3,000 (= 1,000 per month), anchored quarters [C]:

| Case | Days of quarter | Ap. 1 monthly-equivalent (E) | Ap. 2 actual days of the quarter | Ap. 3 current 30-day |
|---|---|---:|---:|---:|
| full quarter 01/01→31/03 | 90 of 90 | 3,000.00 | 3,000.00 | 3,000.00 |
| first partial quarter 15/01→31/03 | 76 of 90 | **2,548.39** | 2,533.33 | 2,533.33 |
| last partial quarter 01/04→15/05 | 45 of 91 | **1,483.87** | 1,483.52 | 1,500.00 |
| split quarter, piece 1 (01/01→19/02) | 50 of 90 | 1,678.57 | 1,666.67 | 1,666.67 |
| split quarter, piece 2 (20/02→31/03) | 40 of 90 | 1,321.43 | 1,333.33 | 1,333.33 |
| split quarter total | | **3,000.00** | 3,000.00 | 3,000.00 |
| leap-year quarter, first 45 days (01/01→14/02/2028) | 45 of 91 | 1,482.76 | 1,483.52 | 1,500.00 |
| leap-year full quarter 2028 | 91 of 91 | 3,000.00 | 3,000.00 | 3,000.00 |

Each of the three approaches is additive within one quarter. They differ in **frequency neutrality**. The quarter crossing February, month by month:

| Month of the quarter | Ap. 1 | Ap. 2 | Ap. 3 (current) | A monthly-frequency tenant at 1,000/month pays |
|---|---:|---:|---:|---:|
| January | 1,000.00 | 1,033.33 | 1,033.33 | 1,000.00 |
| February | 1,000.00 | 933.33 | 933.33 | 1,000.00 |
| March | 1,000.00 | 1,033.33 | 1,033.33 | 1,000.00 |

**Note on the sources.** Approach 2 is the form used by ICMA Actual/Actual and by Odoo Subscriptions (days of the whole billing period). It is additive and it is the closest to the sources. Approach 1 is an EDARA design choice [R] made for the property below.

**Finding.** Only Approach 1 makes the cost of a given span independent of the billing frequency: 3,000 per quarter is 1,000 per month, and January of that quarter costs 1,000. It is also consistent with the rent-roll field `monthly_equivalent_rent`, which already states the monthly equivalent as the basis for reports. **Approach 1 is the consistent basis**; Approach 2 makes the tenant's January cost depend on the length of February.

---

## Annual Rent

Annual rent 12,000 (= 1,000 per month) [C]:

| Case | Days | Recommended (E) | Current 30-day | ACT/365F on 12,000 | ACT/ACT ISDA |
|---|---:|---:|---:|---:|---:|
| full non-leap year 2026 | 365 | 12,000.00 | 12,000.00 | 12,000.00 | 12,000.00 |
| full **leap** year 2028 | 366 | 12,000.00 | 12,000.00 | **12,032.88** | 12,000.00 |
| partial: 6 whole months 01/03→31/08/2026 | 184 | **6,000.00** | 6,133.33 | 6,049.32 | 6,049.32 |
| first month partial: 15 days | 15 | 483.87 | 500.00 | 493.15 | 493.15 |
| final month partial: 01/01→15/12/2026 | 349 | 11,483.87 | 11,633.33 | 11,473.97 | 11,473.97 |
| 11 months + 10 days | 344 | 11,322.58 | 11,466.67 | 11,309.59 | 11,309.59 |
| **extension by one month** (12,000 already invoiced; new 01/01→31/01/2027) | 31 | **1,000.00** | 1,033.33 | 1,019.18 | — |

**Findings.**
- A *full* year must bill 12,000 whether the year has 365 or 366 days: only the monthly decomposition, the current rule and ACT/ACT ISDA meet this; **ACT/365F over-bills a leap year by 32.88**.
- A partial period of **whole months** must bill whole months: 6 months = 6,000.00. Model D bills 6,049.32 and the current rule 6,133.33 for the same tenancy.
- Leap years need **no special handling** under E: a full year is 12,000 by definition, and the February anchored month simply has 29 days.

---

## Extension

Monthly rent 1,000; original `01/01/2026 → 31/12/2026`; extension `01/01/2027 → 15/02/2027` [C].

| | Lines |
|---|---|
| Existing lines | 12 full lines `01/01/2026 → 01/01/2027`, total 12,000.00 — **identical before and after** the extension |
| **New lines only** | `01/01/2027 → 01/02/2027` full = **1,000.00**; `01/02/2027 → 16/02/2027` 15 of 28 days = **535.71** |
| Contract total | 13,535.71 (the current rule would bill 500.00 for the February stub) |

**Extension after an invoiced partial tail.** Original ended 19/12/2026, so the last line `01/12→20/12` (19 of 31 days) was invoiced at **612.90**. Extended to 15/02/2027:
- The stub `20/12/2026→01/01/2027` (12 of 31 days) = **387.10**.
- Tail + stub = **1,000.00**: exactly one month, no over-billing (the current rule bills 1,033.33).
- Then January 1,000.00 and the 1–15 February stub 535.71.

**Extension by exactly one day** (`31/12/2026 → 01/01/2027`): one new piece `01/01/2027→02/01/2027` = **32.26** (1 of 31 days).

Nothing invoiced is modified; every new amount depends only on its own boundaries (§ Rounding).

---

## Renewal

Old `01/01/2026 → 31/12/2026`; successor `01/01/2027 → 15/02/2027`; monthly 1,000 [C].

| | Old | Successor |
|---|---|---|
| Lines | 12 full, `01/01/2026 → 01/01/2027`, total 12,000.00 | `01/01/2027 → 01/02/2027` = 1,000.00; `01/02/2027 → 16/02/2027` 15 of 28 = **535.71**; total **1,535.71** |
| Boundary | last `period_end` = **01/01/2027** | first `period_start` = **01/01/2027** |
| Gap / overlap | none: the old boundary equals the successor's start | — |
| Occupied days | 365 | 46 (01/01→15/02/2027 inclusive = 46) |

The successor's partial final period is calculated from its **own** start-day anchor and its own rent; nothing of the predecessor's schedule is reinterpreted.

---

## Rounding

**Policy demonstrated.** Compute the exact accrual as a rational number; round **once**, with the currency's own rounding (Odoo `currency.round` → `float_round`, HALF-UP, 0.01 for ILS/USD, 0.001 for JOD); and define each line's amount as the **difference of two cumulative roundings**:

`amount(piece [a, b) of period P) = round(F_P(b)) − round(F_P(a))`, where `F_P(x)` is the exact accrual of the period's rent from the period start to `x`, and `F_P` at the period's end equals the rent exactly.

**Results [C].**

| Test | Independent rounding | **Cumulative rounding** | Last-piece-remainder |
|---|---|---|---|
| 19 + 12 split of a 31-day month, rent 1,000 | — | ILS **612.90 + 387.10 = 1,000.00**; USD same; **JOD 612.903 + 387.097 = 1,000.000** | same |
| 10 + 10 + 10 of a 30-day month, rent 1,000 | ILS/USD 333.33 × 3 = **999.99**; JOD 333.333 × 3 = **999.999** | 333.33 + 333.34 + 333.33 = **1,000.00** (JOD 333.333 + 333.334 + 333.333 = **1,000.000**) | sums to the rent |
| Exhaustive: all 3-piece splits of 28/29/30/31-day months × 5 rents (900; 1,000; 1,234.56; 1,600; 3,333.33) × ILS/USD/JOD = **23,550 cases** | fails to sum to the rent in **6,108** | fails in **0** | fails in 0, but needs the amounts already invoiced |

**Why cumulative rounding.** It satisfies the invariant exactly for any number of pieces and needs **no knowledge of previously stored amounts**: a piece's amount is a function of its own dates and the period only, so an extension stub is reproducible from the dates and ordering does not matter. The "last piece absorbs the remainder" alternative gives the same total but depends on reading earlier lines, which is fragile when pieces are created at different times.

**Precision.** Internal calculation uses exact rational (or `Decimal`) arithmetic and a single rounding step; the rent used is the **exact** `rent_amount ÷ months-per-period`, **never the stored, already-rounded `monthly_equivalent_rent`** (which is a report field, e.g. 83.33 for a yearly rent of 1,000, and would reduce six exact months to 499.98). Cross-check: on 3,294 (numerator, denominator, currency) combinations the exact HALF-UP result equals Odoo's `float_round` result in every case [C].

**Full periods** bill `rent_amount` exactly and need no rounding.

---

## Invalid Periods

Business rules only (nothing implemented). Notation: `start`, inclusive business `end`, boundary `B = end + 1`.

| Situation | Expected rule |
|---|---|
| `start = end` | **Valid**: a one-day lease. `B = start + 1`; amount = 1 day of the anchored month (for example 32.26 in a 31-day month). |
| `start > end` (that is, `B ≤ start`) | **Invalid**; rejected. |
| A zero-day internal period (`B = start`, or a line with `period_start = period_end`) | Can never exist; the generator never emits a line with `period_start ≥ B`. |
| One-day lease | Valid; one prorated line of 1 ÷ (days of the anchored month) of the monthly rent. |
| An extension that adds exactly one day | Valid; one new piece `[old B, old B + 1)`; if it continues an invoiced partial tail of the same period it is `round(F(b)) − round(F(a))`. |
| A renewal starting the day after the old contract ends | The normal case: successor `start = old end + 1 = old B`; no gap, no overlap. |
| A renewal starting **on** the old contract's end date | Overlap (both occupy that day); rejected. |
| A renewal starting after `old B` | Allowed; the gap is not billed and the unit is `reserved` (Phase 9.1). |
| Accidental overlap of two schedule periods on one unit | Rejected by the unit-level disjointness rule (Phase 9.2). |
| A line whose amount rounds to 0.00 (rent below one minor unit per day) | Not expected for a positive rent above one minor unit; if it occurs it is a valid 0.00 line, never an error. |

---

## Decision Criteria

Factual statements per model; no score or ranking. "A" is today's rule.

| Criterion | A — 30-day fixed | B — actual, calendar month | C — 30/360 | D — ACT/365 | E — period-relative actual/actual |
|---|---|---|---|---|---|
| **Accuracy** (represents calendar occupancy) | Exact only in a 30-day month; under-bills 28/29-day pieces, over-bills 31-day pieces | Exact for calendar-aligned months | Bills 30 days per month regardless; days billed ≠ days occupied (last 10 days of Jan = 9 days) | Exact per day of a 365-day year, but a full month ≠ rent | Exact per day within the contractual month |
| **Additivity** | Fails 85/114 splits | Additive per calendar month; **not** consistent with anchored months (Case A = 1,048.39) | 1 of 114 fails for the bond basis, 0 for 30E/360 | Fails 114/114 | 0/114 fail; exact for any number of pieces |
| **Intuitiveness** | Simple ("÷ 30") but 3 exact months ≠ 3 months | Simple for calendar months | Needs a day-count rulebook | Simple formula, surprising full-month amounts | "Days occupied ÷ days in that rent month"; whole months exact |
| **Accounting defensibility** | Standardised convention; recorded as finalised 2026-09-17; conflicts with additivity | Widely used by vendors | Bond-market convention; not a rent convention in any source read | Named in vendor pages as the annual alternative | Identical to ICMA Actual/Actual accrual and Odoo Subscriptions' ratio for monthly periods [P][L]; quarterly/yearly decomposition is an EDARA choice [R] |
| **Tenant clarity** | Hard to explain why 12 days of a 31-day month cost 400 | Clear | Cannot be explained by real days | Clear for annual rent | "N of D days" fits on an invoice line |
| **Leap years** | Ignored (no effect) | Feb has 29 days | Ignored | 366 vs 365 changes a full year (+32.88) | No special handling; a full year is the rent |
| **28/29/30/31** | Treats all as 30 | Handles exactly | Treats all as 30 | Average 30.42 | Handles exactly |
| **Quarterly** | Works, not frequency-neutral (Jan 1,033.33) | Needs per-month splitting | Works | Awkward | Frequency-neutral via monthly equivalents |
| **Yearly** | 6 months = 6,033.33 | Needs per-month splitting | Works | 6 months = 6,049.32; leap year 12,032.88 | 6 months = 6,000.00; leap year 12,000.00 |
| **Extension** | Stub of a 31-day month over-bills (1,033.33) | Needs anchor handling | Additive | Not additive | Additive by construction |
| **Renewal** | Independent successor | Independent successor | Independent successor | Independent successor | Independent successor; no shared day |
| **Rounding** | Single rounding; no reconciliation rule | — | — | — | Cumulative rounding: exact, state-free |
| **Odoo implementation** | Existing code | Calendar decomposition code needed | ISDA day-count code needed | Simple | Existing `_period_boundary` + one accrual function; same monthly day-count as `sale_subscription`; standard `currency.round` |
| **Auditability** | Reproducible | Reproducible | Reproducible, but not from real days | Reproducible | Reproducible from `period_start`, `period_end`, rent and the anchor |

---

## The Business Question: what does the contract define?

**Chosen conceptual model: Option 1 — rent is a fixed amount per contractual month; partial months are prorated.**
Rent is **not** a daily rate. The daily figure exists only as an allocation inside one contractual month (rent ÷ months-per-period ÷ length of that month) and it therefore differs between a 28-day and a 31-day month.

| Effect | Under Option 1 (chosen) |
|---|---|
| February | A full February bills the monthly rent; a day of February costs more (35.71) than a day of a 31-day month (32.26) |
| 31-day months | Same: the rent is the rent |
| Annual leases | 12,000 whatever the year's length; a leap year costs the same |
| Extension | Appends months at the contract rent; only the trailing partial month is prorated |
| Termination | An early end bills whole months elapsed plus the days of the current contractual month |
| Renewal | The successor has its own rent and its own anchored months |
| Invoice explanation | "2 months + 17 of 31 days", or "19 of 31 days" |

Option 2 (a daily rate from the annual rent) was rejected: it makes a full month differ from the monthly rent (920.55 for February on a 12,000 lease).

---

## EDARA Canonical Proration Policy

**Name: Period-Relative Actual/Actual.**

1. **Base rent unit.** `rent_amount` is the rent for one billing period of `n` months (`n` = 1, 3 or 12). The monthly equivalent is the **exact** `rent_amount ÷ n`. The stored, rounded `monthly_equivalent_rent` is a report field and is **never** an input.
2. **Full-period calculation.** A schedule line that covers a whole billing period `[S + kn months, S + (k+1)n months)` bills exactly `rent_amount`.
3. **Partial-period calculation.** A line covering part of a billing period bills the rent accrued over its days. Rent accrues as `rent_amount ÷ n` per anchored month: a whole anchored month is the full monthly share, and a part of a month is `occupied days ÷ actual days of that anchored month` of the monthly share. The line amount is `round(F(end)) − round(F(start))` where `F(x)` is the exact accrual from the start of the billing period to `x`.
4. **Day-count convention.** Days are counted by real calendar days: `days(a, b) = (b − a).days`. The length of an anchored month is its real length (28–31), whose boundaries are `S + j months` computed **fresh from the start date** (the existing `_period_boundary`), so a day-31 anchor gives lengths 28, 31, 30 … No 30-day month and no 360-day or 365-day year appears anywhere.
5. **Inclusive / exclusive semantics.** The business `end_date` is inclusive (the last occupied day). Every calculation uses the single boundary `B = end_date + 1 day` and half-open intervals `[start, B)`; occupied days = `(B − start).days`; `01/01 → 31/01` is **31** occupied days. This is also the end date ISDA uses for its day counts.
6. **Monthly behavior.** A whole billing month bills the rent; the final or a stub piece bills `rent × days ÷ days of that anchored month` (for example 19 of 31 days = 612.90 of 1,000).
7. **Quarterly behavior.** Decomposed into the three monthly equivalents (`rent ÷ 3` each): whole anchored months bill their exact share, the partial month is prorated against its own length. A quarterly line still covers one quarter (one line per billing period is unchanged).
8. **Yearly behavior.** Same, with twelve monthly equivalents (`rent ÷ 12`). A full year bills the rent whatever the calendar year's length.
9. **Leap-year behavior.** No special rule: February's anchored month has 29 days when it does, and a full year or quarter is the rent.
10. **Rounding.** Exact rational arithmetic, **one** rounding step per cumulative value with the currency's own rounding (`currency.round`, HALF-UP; 0.01 for ILS/USD, 0.001 for JOD). Line amount = `round(F(b)) − round(F(a))` (cumulative rounding). Full periods need no rounding.
11. **Split-period invariant.** The lines of one billing period always sum **exactly** to the period's rent, with any rounding remainder distributed by the cumulative rule; a piece's amount depends only on its own start, end and period, never on other stored amounts.
12. **Extension behavior.** Only lines from the coverage boundary to the new boundary are created; an uninvoiced partial tail is recomputed inside the new range; an invoiced partial tail is kept and its remainder is the stub `round(F(b)) − round(F(a))`. Invoiced lines and amounts are never changed.
13. **Renewal behavior.** The successor's schedule is calculated from its own start-day anchor and rent; it starts at the predecessor's boundary, so there is no gap and no overlap; the predecessor's lines are not recalculated.
14. **One-day period behavior.** Valid. Amount = `1 ÷ (days of the anchored month)` of the monthly share, rounded cumulatively.
15. **Invalid period behavior.** `end < start` is invalid; a zero-day period never exists; overlapping periods on one unit are rejected; a renewal that starts on or before the old end date is rejected.

**Approval required (stated exactly).**
- **Business owner:** supersedes the "standardized 30-day reference month" finalised on 2026-09-17 (MAT-FIND-013 / MAT-030). Without that approval the policy cannot replace it.
- **Accountant:** (a) that the invoiced amount for a partial billing period under this rule is an acceptable systematic basis of rental income (IFRS 16 ¶81) or the customer's local equivalent; (b) that cumulative rounding, which can place the extra minor unit on a different line than independent rounding would, is acceptable.
- Everything else in the policy follows from the invariants proven above and needs no external approval.

---

## Phase 10 Schedule Engine Contract

Requirements only; each is supported by the decision above or by the Phase 9.2 validation it depends on. There is **no** configurable alternative proration method.

```text
RULE-01  Business end_date is inclusive.
RULE-02  The internal exclusive boundary is B = end_date + 1 day, derived in one place; every
         subsystem uses [start_date, B) and occupied_days = (B - start_date).days.
RULE-03  Billing periods are the intervals [start + k*n months, start + (k+1)*n months), with each
         boundary computed from start_date (never chained), n = 1 (monthly), 3 (quarterly), 12 (yearly).
RULE-04  One schedule line per billing period (unchanged from MAT-FIND-013); a line covers
         [period_start, min(period_end_of_period, B)).
RULE-05  A line covering a whole billing period bills exactly rent_amount.
RULE-06  A line covering part of a billing period bills round(F(b)) - round(F(a)), where F(x) is the
         exact rent accrued from the start of that billing period to x at the rate rent_amount / n
         per anchored month, prorating a part of a month by occupied days / actual days of that
         anchored month.
RULE-07  The rate used is the exact rent_amount / n. The stored rounded monthly_equivalent_rent is never
         used in the calculation.
RULE-08  Days are actual calendar days. No 30-day month, 360-day year or 365-day year is used.
RULE-09  Rounding: exact rational/Decimal arithmetic, one rounding step, HALF-UP, using the invoice
         currency's own rounding (0.01 ILS/USD, 0.001 JOD). A piece's amount is a function of its own
         dates and period only.
RULE-10  The lines of one billing period always sum exactly to that period's rent.
RULE-11  A contractual period must never be invoiced twice; for one unit, schedule periods must be
         pairwise disjoint (Phase 9.2 invariant).
RULE-12  Existing invoiced lines are never regenerated, re-amounted or re-dated, whatever the policy version.
RULE-13  Extension appends only the lines between the coverage boundary and the new boundary; an
         uninvoiced partial tail is recomputed inside the new range; an invoiced partial tail is kept
         and its remainder is created as a stub under RULE-06.
RULE-14  A renewal's successor is calculated from its own start date and rent, starts at the
         predecessor's boundary, and never recalculates the predecessor.
RULE-15  start_date = end_date is valid (one day); end_date < start_date is invalid; a zero-day period
         is never created.
RULE-16  The line stores period_start, period_end (exclusive), occupied_days and is_prorated (true when
         the line covers less than a whole billing period); the invoice line description states the
         basis, for example "19 of 31 days" or "2 months + 17 of 31 days".
RULE-17  The new policy applies only to lines generated after Phase 10 is released. No existing line,
         invoiced or not, is recalculated by the release.
RULE-18  The existing tests that assert 30-day amounts are rewritten to the amounts in the
         "Current EDARA Behavior" table; monthly_equivalent_rent stays a report-only field.
```

---

## Accountant / Legal Questions

**Business owner (blocking).**
1. Approve replacing the "standardized 30-day reference month" recorded as finalised on 2026-09-17, knowing that six test amounts and the recorded live results for LC/2026/0137 and LC/2026/0139 change.

**Accountant (blocking for Phase 10 sign-off).**
2. Is the billed amount for a partial period under this rule an acceptable systematic basis of operating-lease income under IFRS 16 ¶81, or the customer's local-GAAP equivalent?
3. Is cumulative rounding acceptable, given that it may put the extra minor unit on a different line than independent rounding would (for example 333.33 + 333.34 + 333.33)?

**Business owner / Legal (before rollout, not blocking the design).**
4. Do the customers' standard contracts, or any law that applies to them, state a proration method (30-day or actual days)? Vendor sources say the lease should state it. If a signed contract states a 30-day method, applying this policy to that contract would contradict it, and Phase 10 would need a per-customer decision (a configurable alternative was deliberately not designed).
5. Are the invoice explanation strings ("19 of 31 days") acceptable to customers and to the contract wording?

**Business owner (non-blocking).**
6. Is rent ever due on a fixed calendar day rather than the start-day anniversary? The policy extends to calendar-aligned billing (a first stub period followed by calendar months) but that is a different anchor rule and out of scope here.
7. Whether any customer should be told about already-invoiced periods that differ from the new policy (for example a yearly contract invoiced 3,033.33 for three months). No corrective entry is proposed; posted history is not rewritten.

**Not required.** No legal opinion is claimed for any jurisdiction; no source read states a legal requirement about proration methods.

---

## Verification

| # | Requirement | Result |
|---|---|---|
| 1 | All candidate models calculated | A, B, C (bond and 30E), D (365F and ACT/ACT ISDA), E — sections "Mathematical Comparison" to "Annual Rent" |
| 2 | 28/29/30/31-day months | All four, in every matrix |
| 3 | Leap year | Feb 2028 (29 days), leap quarter, leap year full and partial |
| 4 | Split-period additivity | 5 named splits + exhaustive 114 (2-piece) and 23,550 (3-piece) cases |
| 5 | Quarterly rent | Full, first, last, split, crossing February, leap quarter |
| 6 | Annual rent | Full (leap and non-leap), partial, first/final month, extension |
| 7 | Extension | 01/01/2027→15/02/2027, an invoiced partial tail, and one day |
| 8 | Renewal | 01/01/2027→15/02/2027, no gap or overlap |
| 9 | Rounding ILS/USD/JOD | Demonstrated for all three; 0 failures in 23,550 cumulative cases; 0 mismatches against `float_round` |
| 10 | Inclusive end-date semantics | Every figure uses `B = end + 1`; 01/01→31/01 = 31 days |
| 11 | No code changes | `git status`: only `docs/` files untracked |
| 12 | No real database changes | No database opened in this phase |
| 13 | ONE canonical policy | § "EDARA Canonical Proration Policy" |

---

## Final Decision

**OD-N1 is decided: RECOMMENDED — Period-Relative Actual/Actual, with cumulative rounding.**

Rent is a fixed amount per contractual month. A full billing period bills the rent exactly. A part of a period bills the rent accrued over its days, prorated against the actual length of the contractual month the days fall in; quarterly and yearly rent are decomposed into monthly equivalents so the cost of any span is independent of the billing frequency. The end date is inclusive and every count uses `B = end + 1`. Lines are rounded cumulatively so that the lines of one period always sum to the period's rent, exactly, in ILS, USD and JOD.

It is chosen because it is the only candidate that meets every invariant tested (additivity 0 of 114 failures, full-period exactness, whole months exact, leap years without special cases, extension and renewal without gap or overlap) while using, for monthly periods, the same day-count as Odoo Subscriptions and ICMA Actual/Actual (the quarterly and yearly monthly-decomposition is the EDARA-specific step that buys frequency neutrality). It is **not** claimed to be the only defensible convention: the 30-day method and the actual-days method are both in vendor use, which is why the owner's approval and the contract-template check are stated separately above.

**Status: RECOMMENDED — requires (1) business-owner approval to supersede the 2026-09-17 finalised 30-day rule, and (2) accountant confirmation of the income basis and cumulative rounding. Phase 10 may implement it once (1) and (2) are given.**

---

## Sources

**[P] Primary**
- ISDA 2006 Definitions, §4.16 Day Count Fraction (text extracted) — https://www.sc.com/en/uploads/sites/66/content/docs/2006-ISDA-Definitions.pdf
- IFRS 16 *Leases*, ¶81 and ¶87 (text extracted) — https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifrs-16-leases.pdf
- Odoo source: `odoo/addons/sale_subscription/models/sale_order_line.py` (`_get_invoice_line_parameters`); `odoo/tools/float_utils.py` (`float_round`, HALF-UP); `odoo/addons/base/data/res_currency_data.xml` (rounding 0.01 USD/ILS, 0.001 JOD)

**[V] Read**
- Yardi Breeze — https://www.yardibreeze.com/blog/2026/09/how-does-prorated-rent-work/
- MRI Rent Payment — https://mrisoftware.rentpayment.com/blog/guide-prorated-rent-when-how-landlords-should-use-it/
- DoorLoop — https://www.doorloop.com/blog/prorated-rent-calculator
- Buildium — https://www.buildium.com/blog/introducing-prorated-rent-calculations/
- Wikipedia, Day count convention — https://en.wikipedia.org/wiki/Day_count_convention

**[S] Weak**
- AppFolio proration settings (third-party training PDF excerpt) — https://irp-cdn.multiscreensite.com/44ea07a2/files/uploaded/Move%20Out%20Tenants%20Quick%20Guide.pdf
- Buildium help article on prorated rent (JavaScript-rendered) — https://help.buildium.com/hc/s/article/How-do-I-automatically-calculate-prorated-rent-1557495010161

**[L] Local**
- `models/edara_lease_contract.py` (`_generate_schedule_lines`, `_period_boundary`, `monthly_equivalent_rent`), `models/edara_payment_schedule_line.py`, `tests/test_edara_lease_billing.py`, `EDARA_PROJECT_STATE.md` (MAT-FIND-011, MAT-FIND-013, MAT-030), and the Phase 9, 9.1 and 9.2 documents.
