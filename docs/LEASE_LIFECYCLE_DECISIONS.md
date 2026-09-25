# EDARA — Lease Lifecycle & Foreign-Currency Deposit: Business Decision Record

**Phase 9.1 — decision closure. Analysis and documentation only.**
Date: 2026-09-24. Baseline: `property_managment` 19.0.1.0.0, git HEAD `07cd5a1` (Phase 8), Odoo 19 Enterprise, company currency ILS (dev DB).
No Python, XML, JS, CSS, security, manifest, schema, test, configuration or database record was changed. This file is the only file added in Phase 9.1.
It builds on, and does not replace, `docs/LEASE_LIFECYCLE_RESEARCH.md` (the Phase 9 evidence record).

---

## 0. How to read this document

### 0.1 Labels used in every decision

| Label | Meaning |
|---|---|
| **Current EDARA Behavior** | What the code does today, verified by reading the source (file and line references) or by a read-only query. |
| **Industry Evidence** | What property-management platforms document. Graded (see 0.2). |
| **Accounting Evidence** | What accounting standards, professional-firm guidance or Odoo documentation/source say. Graded. |
| **EDARA Recommendation** | A design choice made in this document. It is **not** an industry fact, even where evidence supports it. |
| **External Validation Required** | Who outside engineering must confirm it: `None`, `Accountant`, `Legal`, or `Accountant + Legal`. |

### 0.2 Evidence grades

| Tag | Meaning |
|---|---|
| **[P]** | Primary text read in full (an accounting standard, or Odoo documentation). |
| **[V]** | A vendor/professional page whose content was fetched and read. |
| **[S]** | Search-result excerpt only (page JavaScript-rendered, blocked, or unreadable to the tools). **Weak — confirm before relying on it.** |
| **[L]** | Local source code (EDARA or the installed Odoo 19 Enterprise addons) or a read-only query of the dev database. Reproducible in this repository. |
| **[C]** | A calculation reproduced by running a plain-Python copy of EDARA's own schedule algorithm outside Odoo (no database). |
| **[R]** | Reasoning by the author. Not evidence. |

### 0.3 Status vocabulary (final matrix only)
`RECOMMENDED` · `NEEDS ACCOUNTANT` · `NEEDS LEGAL` · `NEEDS ACCOUNTANT + LEGAL` · `OPEN`.

### 0.4 What could not be obtained (unchanged from Phase 9, plus this phase)
- **Yardi, MRI, Entrata**: no usable first-party documentation was reachable. **No claim about them is made anywhere in this document.**
- **AppFolio**: a search for its month-to-month/holdover handling returned no AppFolio-specific content. **No claim about AppFolio is made.**
- **Buildium and Propertyware help centers** are JavaScript-rendered; only search excerpts [S] were available for them. Buildium's *blog* [V] was read.
- **Palestinian / Jordanian / Israeli lease law**: one search returned only a general statement that Jordanian civil law and Palestinian regulations frame contracts in the West Bank [S, secondary source]. **No legal conclusion is drawn from it.** Every legal point below is routed to legal review.
- **Local GAAP**: whether EDARA customers report under IFRS was not verified. Accounting recommendations assume IFRS-style rules and need the customer's auditor to confirm.

### 0.5 Corrections to the Phase 9 research document (found while closing decisions)
These are changes of position and are recorded here so the two documents do not silently disagree.

1. **Phase 9, A5 said a per-currency deposit account "is not reconcilable".** That is wrong. In Odoo 19, `account.account.reconcile` is user-settable and `_compute_reconcile` leaves it unchanged for non-payable/receivable liability types (`odoo/addons/account/models/account_account.py`, `_compute_reconcile`, lines 665-673) [L]. A `liability_current` account can be set reconcilable. The real limit is revaluation eligibility (OD-A7).
2. **Phase 9, B3 said the old contract becomes `renewed` "only when the successor becomes active".** This document changes that to: the old contract leaves `active` **at its own term boundary**, becoming `renewed` if a successor exists (scheduled or active) and `expired` otherwise. The earlier wording would leave a contract `active` past its end date whenever the successor starts later than the old end.
3. **Phase 9, B6 said successor schedules are created "at activation".** This document changes that to: created when the contract is **confirmed** (as today), invoiced only once `active`. Reason in OD-B5.
4. **Phase 9 treated the end-date convention as "exclusive, confirm with legal".** This document recommends the opposite storage convention (inclusive business date, one derived exclusive boundary) after counting how the code already behaves (OD-B3).

### 0.6 Decision principles applied
Every recommendation was checked against these 17 principles: (1) accounting correctness before UI convenience; (2) native Odoo accounting is the source of truth; (3) contractual currency stays explicit; (4) no silent currency conversion; (5) posted history is never rewritten; (6) paid invoices are immutable from renewal logic; (7) accounting records are not casually cancelled or recreated; (8) lease history stays auditable; (9) occupancy reflects contractual reality; (10) future contracts cause no premature occupancy change; (11) renewal never duplicates billing; (12) extension never leaks revenue; (13) one canonical representation per concept; (14) security stays server-side; (15) prefer native Odoo over custom accounting machinery; (16) avoid complexity a Palestinian SMB does not need; (17) the design must still scale to large portfolios.

---

## 1. Files and history inspected (read-only)

**Documents:** `EDARA_PROJECT_STATE.md` (incl. Phase 7 and Phase 8 sections), `docs/LEASE_LIFECYCLE_RESEARCH.md`.

**EDARA code:** `models/edara_lease_contract.py`, `models/edara_payment_schedule_line.py`, `models/edara_deposit.py`, `models/edara_deposit_transaction.py`, `models/edara_unit.py`, `models/edara_renewal_request.py`, `models/account_payment.py`, `models/account_move.py`, `models/res_company.py`, `models/edara_system_field_guard.py`, `wizard/edara_lease_renewal_wizard.py`, `wizard/edara_deposit_transaction_wizard.py`, `data/edara_cron.xml`, `views/res_config_settings_views.xml`.

**EDARA tests (read, not run):** `tests/test_edara_lease_contract.py` (test names surveyed), `tests/test_edara_phase7_hardening.py`, `tests/test_edara_phase8_currency.py`, `tests/test_edara_deposit.py`.

**Odoo Enterprise source:** `odoo/addons/account_reports/models/account_multicurrency_revaluation_report.py` (eligibility query, lines 300-316); `odoo/addons/account/models/account_account.py` (`_compute_reconcile`, `_check_reconcile`); `odoo/addons/account/models/account_move_line.py` (reconcile requires a reconcilable account, line 2673; exchange-difference creation, lines 2433-3170); `odoo/addons/sale_subscription/models/sale_order.py` and `sale_order_line.py` (period-end arithmetic).

**Git history:** `git log` — `a977296` (initial module), `8546174` (schedule filter shortcuts), `987740b` (Phase 7 hardening), `07cd5a1` (Phase 8 currency). The Phase 7 change to `_process_due_invoices` (billing `renewed` contracts) and `action_renew` (dropping successor-covered lines) and the Phase 8 change to `edara_deposit.py::action_deduct` were re-read.

**Read-only database query** (dev DB `odoo19_enterprise_dev`, `SELECT` only, session set read-only): contract dates/states, last schedule period, deposits. The dev database is test data, not production data; it is used only to show which conventions appear in practice.

**Calculation [C]:** `scratchpad/sim.py` — a plain-Python copy of `_generate_schedule_lines` and `_period_boundary` (no Odoo, no database) used for every schedule figure below.

---

## 2. Locked concepts: Extension vs Renewal

These two definitions are the fixed vocabulary for Phase 10.

### 2.1 Lease Extension
- **Definition (EDARA Recommendation):** the *same* contract; only the contractual term (its End Date) moves later. Nothing else changes: rent, billing frequency, currency, tenant, unit, deposit stay as they are. Any other change is a renewal.
- **Identity:** same contract ID, same number, same deposit record, same schedule. State stays `active`; there is no `renewed` state involved.
- **Billing:** every existing schedule line — draft, invoiced, paid, partially paid, cancelled — is untouched. New lines are created **only for the newly added time**, starting at the first uncovered boundary (section 5). Extending never regenerates, moves, or re-amounts an existing line.
- **Revenue safety:** end date on an active contract can change **only** through the Extend action; editing the field directly is locked. Today it is editable and produces no billing (Current Behavior; gap G-05).
- **Audit:** each extension is recorded (chatter entry with old end, new end, user, date; recommended small extension log so the history is queryable).
- **Industry Evidence:** Buildium's lease-extension guidance ("keep the existing lease in force and push out the end date") [V]; DoorLoop's distinction (an extension edits the end date on the same lease; a renewal creates a new agreement) [V]. **Accounting Evidence:** IFRS 16 lessor modification of an operating lease is accounted as a new lease from the effective date, prior periods not restated [P] (paragraph number not confirmed in the extracted text).

### 2.2 Lease Renewal
- **Definition (EDARA Recommendation):** a *new* contract (the successor) linked to the old one. Any of these may differ: rent, deposit, frequency, terms, dates, currency-neutral commercial conditions.
- **The old contract stays historical and unchanged.** It is not marked `renewed` because a renewal was prepared or signed. It leaves `active` only at its own term boundary (section 3).
- **The successor is not `active` before its start date** (it is `scheduled`).
- **Existing invoices are untouched** (section 6).
- **Industry Evidence:** Buildium — a renewal produces a renewed lease that "will renew automatically when the old one ends" and carries over ledger balances, credits and security deposits; the tenant portal and auto-payments continue unchanged [V, fetched this phase, https://www.buildium.com/blog/new-feature-announcement-lease-renewals/]. DoorLoop — renewal is a new agreement signed electronically [V]. Odoo Subscriptions — a renewal is a separate sales order attached to the same subscription, and prior orders keep their own status [P].

### 2.3 Decision boundary in one table

| Question | Extension | Renewal |
|---|---|---|
| Contract record | same | new (successor) |
| What may change | End Date (later) only | anything |
| Old contract state | remains `active` | remains `active` until its boundary, then `renewed` |
| Schedule | old lines untouched, new lines appended | old lines untouched, successor generates its own |
| Deposit | unchanged | carry-over rule (OD-B8) |
| Accounting effect at signing | none | none |

---

## 3. Canonical date convention (OD-B3 — foundational)

### 3.1 The decision in three sentences (EDARA Recommendation)
1. **`Start Date` is the first day of occupancy and `End Date` is the last day of occupancy — both are occupied days.** "01/01/2026 → 31/12/2026" means the tenant occupies the unit on 31/12/2026.
2. **Every internal calculation uses exactly one derived half-open interval `[Start Date, Term Boundary)`, where `Term Boundary = End Date + 1 day`.** The boundary is produced by **one** helper on the contract (`term_boundary`) and is never re-derived in another place.
3. **The stored field stays the business date.** Nothing in the UI, portal, print or reports needs a "minus one day" conversion; only interval logic (schedule, overlap, occupancy, cron) calls the helper.

### 3.2 What the code does today, subsystem by subsystem [L]

| Subsystem | Location | Treats `end_date` as | 
|---|---|---|
| Schedule generation | `_generate_schedule_lines`: `if period_start >= self.end_date: break`, `min(next_boundary, self.end_date)` | **exclusive** |
| Overlap constraint | `_check_no_overlap`: `start_date < contract.end_date`, `end_date > contract.start_date` | **exclusive** |
| Expiry cron | `_cron_expire_contracts`: `end_date < today` → expired | **inclusive** (a contract is active through its end date) |
| Unit occupancy | `_has_current_active_contract`: `end_date >= today` | **inclusive** |
| Expiry reminders | `_cron_send_expiry_reminders`: `end_date >= today`, `days_left = end_date - today` (0 on the last day) | **inclusive** |
| Renewal wizard default | `new_start_date = end_date + 1 day` | **inclusive** (successor starts the day after) |
| Date validation | `_check_dates`: `end_date <= start_date` is an error | requires at least a 1-day span under the exclusive reading; a same-day lease is impossible |

Result: **4 subsystems already behave inclusively, 2 behave exclusively, and 1 is neutral.** The codebase is split, and the split boundary is exactly where billing meets occupancy.

### 3.3 Measured consequences of the split [C]
Feeding the *existing* generator an End Date entered as the last occupied day (the intuitive entry):

| Contract entered as | Lines produced | Total billed (rent = 1,000 per period) | Defect |
|---|---|---|---|
| 01/01/2026 → 31/12/2026, monthly | 12 lines; December `01/12 → 31/12`, 30 days, flagged prorated | 12,000.00 | none by coincidence: December has 30 counted days on the 30-day reference |
| 01/02/2026 → 28/02/2026, monthly (one month) | 1 line `01/02 → 28/02`, 27 days, prorated | **900.00** | **10 % under-billed** for a full calendar month |
| 01/01/2026 → 31/12/2026, yearly | 1 line, 364 days, prorated | **1,011.11** | **1.11 % over-billed** on a full year |
| 01/01/2026 → 31/12/2026, quarterly | 4 lines; Q4 `01/10 → 31/12` prorated | **4,011.11** | over-billed 11.11 in total |

The same contracts entered with the boundary as the end date (`01/01/2027`, `01/03/2026`) produce 12 × 1,000, 1 × 1,000, 1 × 1,000, 4 × 1,000 with no prorated line [C]. So the module is exact for exclusive-style entry and inexact for the entry the business finds natural.

### 3.4 What the dev data shows [L, read-only query]
Of 12 contracts in the dev database: **7 use anniversary-style dates** (e.g. 01/06/2026 → 01/06/2027), **2 use year-end style** (LC/2026/0010: 31/01/2026 → 31/12/2026; LC/2026/0012: 01/01/2026 → 31/12/2026), **3 are test-day contracts** (24/09/2026 → 01/09/2027). Both styles are already present.
Concrete boundary bug: LC/2026/0012 ends 31/12/2026 and its successor LC/2026/0015 **starts 31/12/2026**. Read inclusively (the convention recommended here), both contracts occupy 31/12/2026.

### 3.5 Options compared

| Criterion | **Option A — fully inclusive, stored as entered** (recommended) | **Option B — stored exclusive, display "end − 1"** | Option C — leave the split |
|---|---|---|---|
| Stored value for "01/01/2026 → 31/12/2026" | End = 31/12/2026 | End = 01/01/2027; UI shows 31/12/2026 | End = whichever the user typed |
| Code that must change | Schedule generator and overlap constraint switch to `term_boundary`; `_check_dates` becomes `end_date < start_date`; wizard default already correct | Every display, report, portal page, reminder text, expiry cron, occupancy, and wizard default; plus every export | none |
| Places a "±1 day" conversion exists | 1 helper (interval logic only) | Every UI/portal/print surface | n/a |
| Matches contract text | yes — leases state the last day [S: general lease-drafting excerpts, not Palestine-specific] | only after conversion | inconsistent |
| Native Odoo precedent | **Odoo Subscriptions stores an inclusive order `end_date` (`start_date + duration − 1 day`, `sale_order.py:864`) while invoicing uses the exclusive `next_invoice_date`; a period's end is `next_invoice_date − 1 day` (`sale_order.py:1150`)** [L] | same internal idea, opposite storage | none |
| Data migration | needed for anniversary-style contracts (3.7) | needed for the *inclusive-style* contracts | none |
| Risk of the measured billing defects (3.3) | removed | removed | stays |

**Analysis.** The half-open interval is the correct *internal* representation (adjacent periods share a boundary without a gap or overlap, and period arithmetic needs no ±1). The question is only where the ±1 lives. Option A puts it in one helper called by two subsystems; Option B puts it in every surface a human reads. Option A also matches the convention Odoo's own recurring-billing module chose. Option C is rejected by principle 13.

### 3.6 Date semantics table (Option A) [C for schedule figures]
`E` = business End Date (last occupied day). `B` = `E + 1` (internal boundary). A day `D` is occupied iff `S ≤ D ≤ E` ⇔ `S ≤ D < B`. Rent = 1,000 per billing period.

| Scenario | Start `S` | Business End `E` | Internal Boundary `B` | Occupied on | Occupied after | Schedule (monthly unless stated) |
|---|---|---|---|---|---|---|
| 1 year | 01/01/2026 | 31/12/2026 | 01/01/2027 | 31/12/2026 = **yes** | 01/01/2027 = no | 12 full periods, last `01/12 → 01/01/2027`, no prorated line, total 12,000 |
| 1 year, yearly billing | 01/01/2026 | 31/12/2026 | 01/01/2027 | 31/12/2026 = yes | 01/01/2027 = no | 1 full period, 1,000.00 (current code with `E` entered gives 1,011.11) |
| 1 month | 01/02/2026 | 28/02/2026 | 01/03/2026 | 28/02/2026 = yes | 01/03/2026 = no | 1 full period, 1,000.00 (current code gives 900.00) |
| Day-31 anchor | 31/01/2026 | 30/01/2027 | 31/01/2027 | 30/01/2027 = yes | 31/01/2027 = no | 12 full periods: `31/01→28/02`, `28/02→31/03`, `31/03→30/04`, … each boundary recomputed from `S` (`_period_boundary`), total 12,000 |
| Leap year inside term | 01/01/2028 | 31/12/2028 | 01/01/2029 | 31/12/2028 = yes | 01/01/2029 = no | 12 full periods, February `01/02→01/03` (29 days) is a full period, total 12,000; yearly: 1 full period, 1,000.00 |
| Leap-day anchor | 29/02/2028 | 28/02/2029 | 01/03/2029 | 28/02/2029 = yes | 01/03/2029 = no | 13 periods; the 13th is `28/02/2029 → 01/03/2029`, 1 day, prorated 33.33 (see 3.8) |
| Extension | 01/01/2026 | 31/12/2026 → **31/03/2027** | 01/01/2027 → **01/04/2027** | 31/03/2027 = yes | 01/04/2027 = no | 12 existing lines untouched; **3 new lines** `01/01→01/02`, `01/02→01/03`, `01/03→01/04` [C] |
| Renewal | old 01/01/2026 – 31/12/2026; **successor 01/01/2027** | old 31/12/2026; successor 31/12/2027 | old 01/01/2027; successor 01/01/2028 | 31/12/2026 belongs to old only; 01/01/2027 belongs to successor only | — | old keeps its 12 lines; successor generates 12 of its own; no shared day, no gap |
| Same-day transition | successor `S` = old `B` | — | — | on 01/01/2027 the old term has ended and the successor's begins in the same daily run | — | see 4.3 (job order) |
| Single-day lease | 15/03/2026 | 15/03/2026 | 16/03/2026 | 15/03/2026 = yes | 16/03/2026 = no | 1 period of 1 day, prorated (`_check_dates` must accept `E ≥ S`) |
| Termination today | — | — | `termination_date` = today is the first uncovered day | tenant not covered from `termination_date` | — | uninvoiced lines with `due_date ≥ termination_date` are dropped (as today); invoiced lines stay (section 6) |

### 3.7 Migration of existing data (EDARA Recommendation)
- **No automatic bulk date shift.** Dates are contract facts; the system cannot tell which style a user typed.
- Phase 10 first produces a **read-only classification report**: for each `active`/`scheduled`/`renewed`-in-term contract, whether `end_date == start_date + N whole months` (anniversary-style, candidate to be entered exclusively) or not.
- Correcting an anniversary-style contract means `end_date := end_date − 1 day`. **This is lossless for billing:** with the new generator (`term_boundary = end_date + 1`) the generated periods are identical to those already generated, because the same boundary results [C: `01/01/2026 → B 01/01/2027` yields the same 12 lines]. Invoiced lines are never touched. Each correction is confirmed by a person, in a script run with explicit authorization, not by a silent upgrade hook.
- Contracts that are not anniversary-style are left as entered.
- Until a contract is corrected, an anniversary-style contract would appear to overlap its successor by one day; the migration must run **before** the overlap constraint switches to `term_boundary`.

### 3.8 Deliberate consequences that Phase 10 must surface, not hide
- If the operator's chosen `E` ends a contract inside a billing period, the last period is prorated on the existing 30-day reference (unchanged rule, not one of the 17 decisions). The leap-day anchor row shows the extreme case (1 prorated day). The confirm action should show the operator the last period and its amount.
- The 30-day proration reference is not part of this decision. It produces 1.11 % over-billing only when a contract ends *inside* a full-period, which is what the corrected convention avoids for whole-period contracts.

### 3.9 Cross-check against the required checklist
Overlap, occupancy, unit status, schedule periods, invoice periods, prorating, monthly/quarterly/yearly frequency, leap years, day 28–31, extension, renewal, same-day transition, cron transitions, future contracts, termination, expiration, reporting and portal are each covered in 3.2–3.7, the table in 3.6, and the state machine in section 4. **Reports and the portal need no change** (they display the stored business date); the only report-side check is that any "days remaining" figure counts inclusively, as the reminder cron already does.

---

## 4. Lease state machine (OD-B5 with OD-B4, OD-B9)

### 4.1 Recommended states

| State | Meaning | Unit effect |
|---|---|---|
| `draft` | Being prepared. No schedule, no unit effect. May be deleted. | none |
| `scheduled` | Confirmed/signed, `Start Date > today`. Schedule exists; **no invoice may be created**. Counts in the overlap check. | contributes to **reserved** |
| `active` | In force **today** (`Start ≤ today < Term Boundary`), or awaiting the daily job on its boundary day. | contributes to **rented** |
| `renewed` | Terminal. Ended at its own boundary and a successor (`scheduled`/`active`) exists. | none |
| `expired` | Terminal. Ended at its own boundary, no successor. | none |
| `terminated` | Terminal. Ended early by a user action. | none |
| `cancelled` | Terminal. A `scheduled` contract withdrawn before it started. | frees the reservation |

`draft`, `active`, `renewed`, `expired`, `terminated` already exist. `scheduled` and `cancelled` are new.

### 4.2 Transitions

| From | To | Trigger | Rule |
|---|---|---|---|
| draft | active | Confirm | `Start ≤ today`; today's preconditions (unit not sold, not under maintenance, positive deposit amount). Schedule generated. |
| draft | scheduled | Confirm | `Start > today`; same preconditions; schedule generated (invoicing gated by `active`). |
| scheduled | active | daily transition job | `Start ≤ today`. Preconditions re-checked; on failure (unit sold or under maintenance, overlap) the job **does not skip silently**: it posts a chatter note and a to-do for the branch manager the same day and retries next run. |
| scheduled | cancelled | user action | Renewal withdrawn or failed. Uninvoiced lines removed; reservation released; deposit carry-over (if any) not executed. |
| active | active | Extend | End Date moves later only; rules in section 2.1; blocked while a `scheduled` successor exists. |
| active | renewed | daily transition job | `Term Boundary ≤ today` **and** a successor in `scheduled`/`active` exists. |
| active | expired | daily transition job | `Term Boundary ≤ today` and no successor. Same condition the expiry cron already uses (`end_date < today`). |
| active | terminated | Terminate | Immediate; `termination_date = today`. If a `scheduled` successor exists it is cancelled **in the same transaction** after an explicit confirmation dialog, and both chatters record it (OD-B9). |
| expired | renewed | Late renewal | A successor created inside the late-renewal window (OD-B2) becomes `active`. |

### 4.3 Daily transition job (single run, per-contract savepoint)
1. Activate `scheduled` contracts with `Start ≤ today`.
2. Close `active` contracts with `Term Boundary ≤ today` → `renewed` or `expired`; drop future uninvoiced lines; run the deposit carry-over when the successor was just activated (OD-B8).
3. Recompute unit occupancy for every touched unit.

Because the successor starts at the predecessor's boundary, in step 1 the two contracts never overlap by date (`pred.B ≤ succ.S`), so the overlap constraint is not violated while both still carry `state = active` for the length of one run.

### 4.4 Unit occupancy (BD-001, restated on the new states)
`rented` ⇔ an `active` contract covers today; else `reserved` ⇔ a `scheduled` contract exists; else `available`. During a renewal the old contract is `active` and covers today, so the unit **stays `rented`** (fixes Phase 7's observation that a renewed-but-in-term contract showed `reserved`).

### 4.5 Options considered for the successor between signing and start

| Option | Overlap protection | KPI / "active" count | Portal and reports | Cancellation | Verdict |
|---|---|---|---|---|---|
| `draft` | **none today** — `_check_no_overlap` skips non-active contracts, so a signed successor would not protect the unit from a second lease | correct | shown as "draft" | delete | rejected (double-leasing) |
| **`scheduled` (new state)** | included in the overlap check | excludes not-yet-in-force leases | shown as "Scheduled" | `cancelled` | **recommended** |
| `active` with future start (today's model) | protected | future successors inflate "active contracts", rent roll and monthly-equivalent sums; every report needs a date filter | mixed | terminate | rejected (principle 13) |
| `renewed`-like "pending renewal" flag on the old contract | old contract protected only | none | ambiguous | flag removal | rejected (a flag is not a state; it duplicates the successor link) |

### 4.6 Migration of states (state values only, not accounting) 
- `active` with `start_date > today` → `scheduled`.
- `renewed` with `Term Boundary > today` (still inside its own term; LC/2026/0012 in the dev data) → `active`.
- All other states unchanged. The unit occupancy sync then follows.

---

## 5. Payment-schedule integrity (the "never invoice a period twice" invariant)

### 5.1 The invariant (EDARA Recommendation)
> For one unit, the half-open periods `[period_start, period_end)` of all schedule lines that are not withdrawn must be **pairwise disjoint**. A period is *consumed* once a line for it has an invoice, in **any** invoice state (draft, posted, paid, cancelled, reversed).

Three layers enforce it:
1. **Invoice ↔ line** — `unique(invoice_id)` already exists [L].
2. **Line ↔ period** — new Python constraint on `edara.payment.schedule.line` (create/write): no two lines on the same **unit** overlap. Checked across contracts, so predecessor and successor cannot double-bill.
3. **Generator** — generation is **incremental**: it computes the first uncovered boundary and creates only lines from there.

The contract `state` is **not** the duplicate guard; a state flip is precisely how the current gap appeared (Phase 7).

### 5.2 The design principle for Phase 10
**Generate by coverage, never by regeneration.** Replace "delete all uninvoiced lines, then regenerate every period from `start_date`" with "compute the covered set, then create only the uncovered remainder up to the boundary".

### 5.3 The current defect, quantified [L, C]
`_generate_schedule_lines` unlinks uninvoiced lines and regenerates **every** period from `start_date` (`edara_lease_contract.py:193-224`); the `unlink()` on the line model blocks deleting invoiced lines but nothing stops re-creating their periods.
Example [C]: old term `01/01/2026 → 20/12/2026` (exclusive), last line `01/12 → 20/12`, prorated, **invoiced 633.33**. Extending to `01/04/2027` and calling the generator creates a new uninvoiced line `01/12 → 01/01/2027`, **1,000.00**. December would be billed **1,633.33** for one month, and the period overlaps the invoiced one by 19 days.

### 5.4 Scenario table

| Scenario | Required behavior |
|---|---|
| **Extension** | Covered set = all existing lines. Create lines from `max(period_end)` to the new boundary. If the last existing line is prorated and **uninvoiced**, remove it and regenerate its period as part of the new range. If it is prorated and **invoiced**, keep it; the next period starts at its `period_end` and runs to the next anchor boundary (a stub period) — e.g. `20/12 → 01/01`. |
| **Renewal** | Predecessor lines are never edited. Successor lines start at `successor.start_date`. The unit-level constraint rejects any successor period that intersects a predecessor line. |
| **Regeneration** (draft edit before confirm) | Allowed only while no line has an invoice; otherwise the incremental rule applies. |
| **Cron** | Invoices a line only if it has no `invoice_id`, its `due_date ≤ today`, its contract is `active`, and the row lock `FOR UPDATE SKIP LOCKED` is taken (already in place). |
| **Manual "Generate Due Invoices Now"** | Same candidate rule as the cron (`_process_due_invoices` is shared, MAT-FIND-007). |
| **Retry after failure** | A line whose invoice creation failed has no `invoice_id` and is picked up on the next run. Recommended gate for the retry: a line whose `due_date` falls inside the contract's own term is still billable after the contract left `active` through `expired`/`renewed` (today only `active`/`renewed` pass; an `expired` contract with an unbilled overdue line is stranded). `terminated` contracts keep today's rule (MAT-FIND-006/007). **Confidence: MEDIUM; the owner should confirm the `expired` case.** |
| **Partial period** | Prorated on the existing 30-day reference; the line stores `occupied_days` and `is_prorated`; frozen once invoiced. |
| **Future lines** | Exist from confirmation (also for `scheduled`), never invoiced before `due_date`, removed on terminate/cancel. |
| **Already-invoiced lines** | Immutable: `amount` is frozen (Phase 7), `unlink()` is blocked, `invoice_id` is a system field. |
| **Cancelled invoice** (never posted) | The line shows `cancelled` and its period stays consumed. A new invoice for that period needs an explicit, authorized "re-invoice" action; nothing regenerates it automatically. |
| **Reversed invoice** (credit note on a posted invoice) | Period stays consumed; any re-billing is a manual accounting decision. EDARA creates no credit notes (Phase 8 audit). |

---

## 6. Early renewal and existing invoices

**Scenario:** old contract `active`, with invoiced, paid and future lines; a renewal is signed.
**Decision (EDARA Recommendation):** **nothing existing changes.**
- Invoiced, posted, paid and partially paid invoices: untouched.
- Old uninvoiced future lines: **remain valid** and continue to be billed to the old contract until its boundary, because the tenant stays in occupation until then.
- No old invoice is cancelled because a renewal exists. A credit note is issued only when a *commercial* fact changes (a negotiated concession on an invoiced period), by an accountant, never as a side effect of the lifecycle.
- The successor creates lines only for its own term; the unit-level invariant (section 5) blocks overlap.
- Because the successor cannot start before the predecessor's boundary (OD-B6), no straddling period exists.
- **Evidence:** IFRS 16 prospective treatment from the effective date [P]; Odoo posted entries are immutable and are only reversed by a credit note [L]; Buildium's renewal carries the ledger forward rather than voiding it [V]; project rule "accounting history is never rewritten" [L].

---

## 7. Currency vocabulary (used by OD-A1 … OD-A7)

| Term | Meaning | Where it lives in EDARA / Odoo |
|---|---|---|
| **Contractual currency** | The currency in which the obligation is fixed by the lease (e.g. deposit = USD 1,000). | `edara.lease.contract.currency_id`; `edara.deposit.currency_id` is a stored related field to it [L]. |
| **Transaction currency** | The currency of a specific journal item or payment. Equals the contractual currency unless an alternative-currency workflow (OD-A4) is enabled. | `account.move.line.currency_id` / `amount_currency`. |
| **Company (functional) currency** | The currency of the company's books and of `debit`/`credit`/`balance`. ILS in the dev DB. | `res.company.currency_id`. IAS 21 "functional currency" is a related but not identical concept and is an accountant matter. |
| **Reporting (presentation) currency** | The currency of published statements, if different from functional. | Not configured; outside this phase. If it ever differs, IAS 21 translation rules apply and the accountant decides. |

---

## 8. The 17 decisions

Each decision uses the same headings. Where several fields say "see …" the detail is in the numbered section referenced.

---

## OD-A1 — What do the customers' contracts say about deposit/rent currency and conversion?

**Status:** RECOMMENDED (modeling rule). The factual survey of customer templates remains a non-blocking validation.

### Question
Does a contract state the deposit as "USD 1,000, payable in USD", "USD 1,000, payable in ILS at the day's rate", or "ILS 3,700 fixed"? Can rent and deposit be in different currencies?

### Current EDARA Behavior
One `currency_id` per contract; the deposit's currency is a *stored related field* to it [L: `edara_deposit.py` line 25]. Rent and deposit therefore share one currency; a contract with ILS rent and a USD deposit cannot be represented. The collection wizard has no "tendered currency" field, so every payment is recorded in the deposit currency [L: `edara_deposit_transaction_wizard.py`, `_create_deposit_payment` passes `currency_id`].

### Industry Evidence
No readable vendor page documents currency clauses. A consumer guide on Israeli rentals reports rent quoted in one currency, paid in shekels, sometimes with a contractual floor on the exchange rate [S, JustLanded — weak, secondary].

### Accounting Evidence
The amount that binds the parties is the amount stated in the contract; the obligation is monetary when it is a fixed number of currency units (IAS 21 ¶16) [P].

### Options
1. Contract currency = the currency of the obligation for both rent and deposit (today).
2. Add an independent deposit currency, defaulting to the contract currency.
3. Model conversion clauses (minimum rates, "payable in ILS at the day's rate") as first-class contract terms.

### Analysis
Option 1 covers a contract that fixes every amount in one currency and is the smallest model. Option 2 is needed only if customers write ILS rent with a USD or JOD deposit, which the source material here cannot confirm or exclude. Option 3 is a legal-drafting feature with no evidence of demand. Making the deposit currency an independent stored field later is a small change **if** Phase 10 reads `deposit.currency_id` everywhere and never `contract.currency_id`. It already does (`edara_deposit.py` uses `self.currency_id`).

### EDARA Recommendation
1. **Rule:** the contract stores the currency of the obligation explicitly; the system never infers or converts it.
2. Phase 10 keeps Option 1. Option 2 is added only if the template survey finds mixed-currency contracts; the design keeps that a schema-only change.
3. A contract that fixes an ILS amount is entered as an ILS contract, never as a USD contract "worth" ILS.
4. Conversion clauses (Option 3) are out of scope; they are handled under OD-A4 only as an explicit workflow.

### Confidence
HIGH for the rule; LOW for whether mixed-currency contracts exist (unknown).

### External Validation
Legal (non-blocking): a person with access to the customers' contract templates confirms which of the three patterns occur.

### Implementation Impact
Contract form (a visible "Currency of obligation" help text); deposit model only if Option 2 is later needed; onboarding checklist item.

### Sources
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-21-the-effects-of-changes-in-foreign-exchange-rates.pdf
- https://www.justlanded.com/english/Israel/Israel-Guide/Housing-Rentals/Rentals (weak)

---

## OD-A2 — Discount a non-interest-bearing deposit to present value?

**Status:** NEEDS ACCOUNTANT.

### Question
Under IFRS 9 a non-interest-bearing refundable deposit is in theory discounted, with the difference treated as an additional lease payment. Does EDARA discount?

### Current EDARA Behavior
The deposit liability is booked at the face amount (collect = payment for the full amount, refund = payment for the amount refunded) [L]. No discounting exists.

### Industry Evidence
None found. Property-management platforms document deposits as liabilities held at face value (Buildium: liability; refund reduces it; a withheld deposit becomes income) [S, Buildium Help excerpts].

### Accounting Evidence
PwC Viewpoint IND FAQ 4.10.1: refundable tenant deposits held by a lessor are financial liabilities under IFRS 9, initially at fair value and afterwards at amortised cost; the guidance discusses discounting non-interest-bearing deposits and does not discuss foreign currency [V].

### Options
1. Face value only (today).
2. Discount at initial recognition and accrete interest over the lease term.

### Analysis
Option 2 requires a discount rate policy, an amortisation schedule, and an extra journal entry each period, on an amount held for the lease term (typically 12 months). Materiality depends on the customer's reporting framework, which is unverified. Option 2 would also need custom accounting machinery that principle 15 disfavors.

### EDARA Recommendation
Option 1. EDARA records deposits at face value. If a customer's auditor requires discounting, that is a separate, customer-specific accounting project, not a default.

### Confidence
MEDIUM.

### External Validation
Accountant (materiality and reporting framework).

### Implementation Impact
None in Phase 10. Document the policy in the state file and the accountant handover note.

### Sources
- https://viewpoint.pwc.com/dt/gx/en/pwc/industry/industry_INT/industry_INT/real_estate__1_INT/Applying-IFRS-for-the-real-est/Rental-income-accounting-by-lessors/frequently-asked-questions/ind-faq-4-10-1-how-should-an-entity.html
- https://help.buildium.com/hc/s/article/Security-deposit-lifecycle-1557493000858 (weak)

---

## OD-A3 — Are deposits ever held as agent/escrow rather than as the operator's own liability?

**Status:** NEEDS ACCOUNTANT + LEGAL.

### Question
Is a deposit ever held in a segregated account for the owner, so it is not the operator's own liability?

### Current EDARA Behavior
One company-level liability account holds all deposits [L: `res_company.py`, `edara_deposit_liability_account_id`]. The documented architecture is the **Principal** model. Collect and refund post through the company's own journals [L].

### Industry Evidence
Buildium distinguishes deposits held by the management company from deposits held by the rental owner and has separate refund/withhold flows for each [S, Buildium Help excerpt].

### Accounting Evidence
Whether a held amount is the operator's liability depends on whether the operator controls the funds and bears the obligation (principal vs. agent). PwC's FAQ addresses a lessor's own deposit, not an agent's [V].

### Options
1. Support only operator-held deposits (today).
2. Add a per-property flag "deposit held by owner/escrow" and a separate liability (or no liability) accordingly.

### Analysis
Option 2 changes the balance-sheet presentation and possibly local trust-account rules. Whether the law requires segregation is a legal question that cannot be answered from the sources available here.

### EDARA Recommendation
Option 1, stated explicitly: **EDARA v1 supports operator-held deposits only.** No flag is added. The state file and the onboarding checklist must say so, so that no customer with a legal segregation duty adopts EDARA by assumption.

### Confidence
MEDIUM.

### External Validation
Accountant + Legal (segregation duty and presentation).

### Implementation Impact
Documentation and an onboarding question only. A later property-level flag would touch `edara.property`, the deposit account resolution and the payment destination account (`account_payment.py`).

### Sources
- https://help.buildium.com/hc/s/article/How-to-withhold-or-refund-a-security-deposits-held-by-a-rental-owner (weak)
- https://viewpoint.pwc.com/dt/gx/en/pwc/industry/industry_INT/industry_INT/real_estate__1_INT/Applying-IFRS-for-the-real-est/Rental-income-accounting-by-lessors/frequently-asked-questions/ind-faq-4-10-1-how-should-an-entity.html

---

## OD-A4 — Accept a deposit payment in a currency other than the contract's?

**Status:** RECOMMENDED (Option A now; Option B specified, gated on accountant sign-off and OD-A5).

### Question
If the contract says USD 1,000, may the tenant pay in another currency? If so, under what conversion rules?

### Current EDARA Behavior
The wizard's amount is a Monetary in the deposit's currency and the payment is created with `currency_id = deposit.currency_id` [L]. Alternative-currency payment is **not** a feature. A cashier who receives ILS can only type a USD figure computed elsewhere — the conversion is then silent and unrecorded. `action_collect` also has no cap: it accepts any `amount > 0` even above the outstanding deposit [L: `edara_deposit.py:89-99`].

### Industry Evidence
No readable vendor page documents deposits tendered in another currency. Vendor evidence for this decision is **absent**.

### Accounting Evidence
- IAS 21 ¶21-22: a foreign-currency transaction is recorded at the spot rate on the transaction date [P].
- Odoo 19 documentation: a payment can be registered in a currency different from the invoice's; exchange differences are booked automatically on reconciliation [P].
- Odoo bank statement lines in the journal currency are matched against a payment in another currency through native reconciliation (mechanism read in the reconcile code; not executed) [L].

### Options
A. Contract currency only. B. Allow another currency through an explicit conversion workflow.

### Analysis
Option A has no FX exposure at receipt, no rate policy and the simplest audit trail. Its weakness is operational: a tenant who tenders ILS cannot be served without an off-system conversion, which is a silent conversion (principle 4). Option B is compatible with native Odoo, but the correct posting design depends on the OD-A5 spike (see OD-A5). Building B before that spike risks a wrong accounting shape.

### EDARA Recommendation
1. **Phase 10: Option A, plus a hard cap.** Collection cannot exceed `amount − amount_held`; an excess is rejected with a clear message, not silently absorbed.
2. **Option B is retained as a future capability with this fixed specification** (each row is an EDARA Recommendation, not an industry fact):

| Item | Specification |
|---|---|
| Switch | Company setting `Allow deposit payment in another currency`, **off** by default; when on, a fixed list of allowed currencies |
| Exchange-rate source | The company's Odoo `res.currency.rate` table (manual or provider-fed) |
| Rate date | The **receipt date** of the payment; locked at posting; never re-derived |
| Who controls the rate | The accountant maintains the rate table; the collecting user cannot type a rate. A manual override, if ever needed, requires the accountant role and a stored reason |
| Conversion | `credited_amount = tendered_amount ÷ rate`, rounded to the **deposit currency's** rounding; company-currency value rounded to company currency |
| Minimum accepted amount | The tendered amount must convert to at least one deposit-currency minor unit; below that the wizard refuses |
| Shortfall | The deposit stays partially collected; the balance still owed remains in the deposit currency |
| Overpayment | The credited amount is capped at the outstanding deposit; the excess is returned to the tenant or held as customer credit through native accounting, never absorbed in the deposit |
| Receipt currency | The receipt shows **both** the tendered amount/currency and the credited amount/currency, plus the rate and its date |
| Accounting currency | The deposit liability line is in the **deposit currency**; the company-currency amount follows the receipt-date rate |
| FX difference | None at receipt (the credit is computed from the tendered amount at the same rate). FX arises later from remeasurement (OD-A6) and settlement (OD-A7) |
| Refund behavior | Default in the deposit currency; a refund in another currency follows the same rules at the **refund-date** rate, and the resulting difference is realised FX |
| Audit trail | Store `tendered_amount`, `tendered_currency_id`, `rate`, `rate_date` on the deposit transaction; chatter entry |
| Tenant communication | The deposit statement always shows the USD balance; the receipt states the rate used |

### Confidence
HIGH for Option A and the cap; MEDIUM for the specification of Option B.

### External Validation
None for Option A. Accountant before Option B is built.

### Implementation Impact
`edara_deposit.py::action_collect` (cap); collection wizard (validation message); tests for the cap in ILS/USD/JOD. For Option B: wizard fields, deposit transaction fields, company settings, `_create_deposit_payment`.

### Sources
- https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-21-the-effects-of-changes-in-foreign-exchange-rates.pdf
- https://www.bdo.nz/en-nz/blogs/financial-reporting-insights/accounting-for-forex-transactions

---

## OD-A5 — Can a deposit be credited in USD while cash arrives in ILS through native payments?

**Status:** OPEN (engineering spike, defined here, executed first in Phase 10).

### Question
Is there a native way to record the receipt so that the deposit liability is credited in the deposit currency (USD) while the bank receives another currency (ILS)?

### Current EDARA Behavior
`_create_deposit_payment` creates a native `account.payment` with `currency_id = deposit.currency_id`; the destination account is overridden to the deposit liability account [L: `account_payment.py`]. This is correct for a same-currency receipt (Phase 8 verified ILS/USD/JOD).

### Industry Evidence
None.

### Accounting Evidence
- An `account.payment` in USD posted on an ILS bank journal produces a liquidity line and a counterpart line, both in USD with company-currency balances at the payment-date rate; the bank statement line in ILS is then matched through native reconciliation, and Odoo books an exchange difference on full reconciliation [P: Odoo multi-currency doc; L: `account_move_line.py` reconcile path]. **This was read, not executed.**
- No claim is made that the flow works for a *deposit* payment whose destination account is the EDARA liability account, because that combination was not run.

### Options
1. **Design 1:** payment in the deposit currency on the ILS journal; the ILS bank statement is reconciled against it.
2. **Design 2:** payment in the tendered currency, with the deposit liability credited by a second, explicit journal entry.
3. Reject Option B permanently.

### Analysis
Design 1 needs no custom entry and uses the flow Odoo already supports for invoices. It is the preferred candidate. Design 2 needs custom accounting machinery (principle 15). The result decides whether Option B of OD-A4 is cheap or expensive; it does not affect Option A.

### EDARA Recommendation
This is an engineering question, not a business decision. It is **closed as a business item** and kept as an explicit Phase 10 spike with these acceptance tests, run in a **throwaway test database** (not the dev database):
1. Register a USD payment for a USD deposit on an ILS bank journal; verify `amount_currency`, `balance`, partner and destination account on both lines.
2. Post an ILS bank statement line for the tendered amount and reconcile it; verify that the exchange difference, if any, lands in Odoo's exchange journal, and that the deposit liability balance in USD is unchanged.
3. Repeat for JOD.
4. If steps 1-3 pass, Design 1 is adopted; otherwise OD-A4 stays at Option A.

### Confidence
LOW (nothing was executed).

### External Validation
None (engineering); Accountant reviews the resulting entries before Option B is released.

### Implementation Impact
A test-only spike file; no production code until the spike passes.

### Sources
- https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html
- Local: `odoo/addons/account/models/account_move_line.py` (reconcile path, lines 2433-3170)

---

## OD-A6 — Revaluation cadence for foreign-currency deposits

**Status:** NEEDS ACCOUNTANT.

### Question
How often is the USD/JOD deposit liability remeasured to the closing rate: monthly or at year-end?

### Current EDARA Behavior
No remeasurement exists in EDARA. The deposit liability account is `liability_current` with no account currency, so Odoo's Foreign Currency Revaluation report **excludes it** (eligibility: `account.currency_id != company currency`, or the account type is receivable/payable *and* the line currency is foreign) [L: `account_multicurrency_revaluation_report.py`, lines 305-310]. Collect and refund are each booked at their own date's rate, so the company-currency balance keeps a difference when the rate moved (documented in Phase 8) [L].

### Industry Evidence
None specific to property platforms.

### Accounting Evidence
- IAS 21 ¶23(a): foreign-currency monetary items are translated at the closing rate at the end of each reporting period; ¶28: exchange differences on retranslation are recognised in profit or loss [P].
- BDO: differences arise both on retranslating unsettled items at period end (unrealised) and on settlement (realised), and are recognised in profit or loss in the period they arise [V, fetched this phase].
- Deloitte DART on US GAAP reaches the same result for liabilities [S].
- Odoo 19: the Unrealized Currency Gains/Losses report creates an **Adjustment Entry** with automatic reversal on a chosen date [P].

### Options
1. Year-end only. 2. Month-end when the company produces monthly accounts, otherwise year-end. 3. Only at settlement (no remeasurement).

### Analysis
IAS 21 ties remeasurement to the **reporting period**, so the required frequency equals the company's reporting frequency (Option 2 follows the standard). Option 3 (only at settlement) does not meet IAS 21 for any period end that falls before the deposit is settled. The only cost of Option 2 is running one native report per month.

### EDARA Recommendation
Option 2, with Odoo Enterprise's native adjustment entry and auto-reversal. **No EDARA code performs it.** EDARA's part is to make the account eligible (OD-A7) and to document the monthly procedure.

### Confidence
MEDIUM (the standard is clear; the customer's reporting cadence is unknown).

### External Validation
Accountant.

### Implementation Impact
Operating procedure in the state file; depends on OD-A7; a Phase 10 test that the revaluation report lists deposit lines once the account is eligible.

### Sources
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-21-the-effects-of-changes-in-foreign-exchange-rates.pdf
- https://www.bdo.nz/en-nz/blogs/financial-reporting-insights/accounting-for-forex-transactions
- https://www.odoo.com/documentation/19.0/applications/finance/accounting/bank/foreign_currency.html
- https://dart.deloitte.com/USDART/home/codification/broad-transactions/asc830-10/roadmap-foreign-currency-transactions-translations/chapter-4-foreign-currency-transactions/4-3-subsequent-measurement-foreign-currency (weak)

---

## OD-A7 — Deposit liability account: type, reconcilability, currency

**Status:** NEEDS ACCOUNTANT.

### Question
Should the deposit liability account be reconcilable, carry a fixed currency, or stay a plain company-currency liability, given how Odoo revalues and settles foreign-currency balances?

### Current EDARA Behavior
`res.company.edara_deposit_liability_account_id` is a single account per company. In every test it is `liability_current`, no account currency [L: `test_edara_deposit.py:38`, `test_edara_phase8_currency.py`]. Collect and refund are native payments whose destination account is overridden to this account; deduction is a journal entry against it [L]. Result: (a) it is not revaluation-eligible; (b) Odoo books no realised FX at settlement, because collect and refund are never reconciled against each other. The account's `reconcile` flag is not set by EDARA.

### Industry Evidence
None (property platforms do not document their chart-of-accounts mechanics).

### Accounting Evidence [L unless noted]
- `account_type` `liability_payable` is automatically reconcilable (`_compute_reconcile`); `liability_current` keeps whatever the user sets, so it **can** be made reconcilable manually. A reconciliation requires `account.reconcile` (`account_move_line.py:2673`).
- Odoo's revaluation includes a line if `account.currency_id != company currency` **or** the type is `asset_receivable`/`liability_payable` and the line currency is foreign (`account_multicurrency_revaluation_report.py:305-310`).
- On full reconciliation Odoo creates the exchange-difference entry in the company's exchange journal (`account_move_line.py`, `_create_exchange_difference_moves`).
- Locking an account to one currency makes Odoo revalue it but restricts which currencies its lines may carry (fits one account per currency, not one shared account).

### Options

| # | Configuration | Revalued by Odoo? | Realised FX booked on settlement? | Admin burden | Partner ledger effect |
|---|---|---|---|---|---|
| 1 | Current: `liability_current`, not reconcilable | No | No | none | none |
| 2 | `liability_current`, **reconcile = True** | **No** | Yes, if EDARA reconciles the lines | one flag | none |
| 3 | **`liability_payable`** (reconcilable automatically) | **Yes** | Yes, if EDARA reconciles the lines | one account type | deposits appear in the tenant's payable balance and aging |
| 4 | One `liability_current` account **per currency**, currency-locked, reconcile = True | Yes | Yes | company setting must map currency → account | none |

### Analysis
- Option 1 leaves both effects missing.
- Option 2 gives realised FX but no unrealised revaluation, so the accountant would have to compute period-end remeasurement by hand — the exact work the Enterprise report exists to remove.
- Option 3 satisfies both with one account and no new EDARA setting. Its cost is presentational: the deposit shows as an amount payable to the tenant, which is factually what a refundable deposit is. The accountant must confirm that presenting it in payables is acceptable and that no reconciliation model will auto-match the tenant's deposit lines with an unrelated vendor bill.
- Option 4 gives both effects and no payables presentation, but needs a per-currency account mapping (new company settings, resolution logic, and a second-currency deposit fails until its account exists). That is machinery a Palestinian SMB with three currencies does not need (principle 16).
- Settlement mechanics for Options 2-4 (EDARA Recommendation): when a deposit reaches `closed` (balance zero), EDARA reconciles that deposit's liability lines natively; Odoo then books the realised difference itself (no EDARA-invented entry).

### EDARA Recommendation
**Option 3**, on these conditions:
1. The accountant approves payables presentation and confirms the account code.
2. Phase 10 first proves it in tests: (i) the revaluation report lists foreign-currency deposit lines; (ii) full reconciliation of a closed USD deposit whose refund was at a different rate produces the native exchange-difference entry; (iii) the ILS deposit case (no foreign currency) is unaffected.
3. If the accountant rejects payables presentation, fall back to **Option 4** (not Option 2, which forfeits revaluation).

### Confidence
MEDIUM (source-verified eligibility and reconcile rules; no runtime test yet).

### External Validation
Accountant (chart of accounts, presentation, local GAAP).

### Implementation Impact
Company configuration (account type), a setup check that warns if the configured account is not eligible, `edara_deposit.py` (reconcile lines when `closed`), tests, accountant handover note. Existing deposits already booked on the current account need a one-time decision (moving balances is an accountant journal entry, not a code change).

### Sources
- Local source files listed above.
- https://www.odoo.com/documentation/19.0/applications/finance/accounting/bank/foreign_currency.html
- https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-21-the-effects-of-changes-in-foreign-exchange-rates.pdf

---

## OD-B1 — How strict is "an extension changes only the end date"?

**Status:** RECOMMENDED.

### Question
May an extension also change rent (or one other minor term), or is any other change a renewal?

### Current EDARA Behavior
No Extend action exists. `end_date`, `rent_amount` and `billing_frequency` are editable on an active contract and have no effect on the existing schedule [L: `contract_views.xml`, no `write()` override].

### Industry Evidence
Buildium's extension guidance describes an addendum that moves the end date, tolerating at most one minor agreed change [V]. DoorLoop treats an extension as an end-date edit on the same lease and a renewal as the wizard that updates rent and deposit [V].

### Accounting Evidence
IFRS 16 lessor: a modification of an operating lease is accounted for as a new lease from the effective date; a rent change in the middle of a lease is not a retroactive restatement [P].

### Options
1. End date only. 2. End date plus one minor change (Buildium's tolerance). 3. Any change through "extension".

### Analysis
A rent change inside an extension makes one contract carry two rent levels, which the schedule (one `rent_amount`, frozen at generation) cannot represent without per-line rates. A short renewal represents it exactly: a new contract, its own rent, its own schedule. Option 2 also forces a definition of "minor" that the software cannot check. Option 3 defeats the point of the distinction.

### EDARA Recommendation
**Option 1.** Extension = End Date (later than the current one) only. Anything else — rent, frequency, deposit, currency, tenant, unit — is a renewal, however short. The Extend action refuses if the new end is not later than the current one. Shortening a term is not an extension: use Terminate.

### Confidence
HIGH.

### External Validation
None.

### Implementation Impact
`edara_lease_contract.py` (Extend action; lock `end_date`, `rent_amount`, `billing_frequency`, `currency_id` after confirmation), contract views (read-only fields, Extend button and wizard), new tests, security (`check_access('write')` + scoped `sudo()`, per the Phase 7 guard).

### Sources
- https://www.buildium.com/blog/lease-extension-agreement/
- https://www.doorloop.com/blog/lease-extension
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifrs-16-leases.pdf

---

## OD-B2 — Late renewal / late extension window after expiry

**Status:** RECOMMENDED (mechanism); the default window value is an adjustable setting.

### Question
After a contract expires, for how long can a renewal still be recorded against it, and can an expired contract be extended?

### Current EDARA Behavior
`action_renew` requires `state == 'active'`; the expiry cron moves a contract to `expired` the day after its end date; an expired contract cannot be renewed or extended [L: `edara_lease_contract.py:353`, `:393`].

### Industry Evidence
Buildium allows renewing an expired lease going back 240 days, and does not renew future, at-will or past leases [S, Buildium Help excerpt — weak]. Nothing readable states a rationale for 240.

### Accounting Evidence
None specific. A back-dated successor creates schedule lines whose due dates are in the past; the cron would invoice them on the next run.

### Options
1. No late renewal (today). 2. Late renewal within a company-set window. 3. Unlimited.

### Analysis
Option 1 forces a manual workaround (re-key a new contract) for the common case of a tenant who signs a few days late, and loses the successor link. Option 3 lets an old contract be "revived" indefinitely and lets a back-dated successor collide with a lease signed for the same unit in the meantime; the overlap constraint blocks the collision but only after the fact. Option 2 bounds both. The number is a business preference; 240 is one vendor's setting and is not adopted as evidence.

### EDARA Recommendation
**Option 2**, as a company setting with a default of **30 days**. Rules: (1) only *renewal* is allowed on an `expired` contract; **extension is not** (an extension of an expired contract is a late renewal with the same terms); (2) the successor's start date must equal the old contract's boundary (no gap, no overlap); (3) the overlap constraint must pass; (4) back-billing of the gap periods happens through the normal cron and is an owner-visible consequence shown in the confirmation dialog; (5) on success the old contract moves `expired → renewed`.

### Confidence
HIGH for the mechanism; LOW for the number 30.

### External Validation
Legal for the back-billing consequence in the holdover case (see OD-B10).

### Implementation Impact
Renewal action and wizard, company setting, state transition `expired → renewed`, tests (inside window, outside window, overlap with a newer lease).

### Sources
- https://help.buildium.com/hc/s/article/How-to-renew-a-lease (weak)
- https://www.buildium.com/blog/new-feature-announcement-lease-renewals/

---

## OD-B3 — Contract end-date convention

**Status:** RECOMMENDED.

### Question
Does "End Date 31/12/2026" mean the tenant occupies on 31/12/2026, and how do all subsystems share one convention?

### Current EDARA Behavior
Split between inclusive and exclusive subsystems (3.2); measurable billing errors for last-day entry (3.3); both styles present in the data (3.4).

### Industry Evidence
General lease-drafting sources describe a lease end date as the last day of the tenancy, and a one-year lease starting on 1 June ending on 31 May [S: excerpts from `realestatelicensewizard.com`, `debtbook.com`, LawInsider — weak, not Palestine-specific]. Odoo Subscriptions stores an inclusive `end_date` and uses an exclusive next-invoice date internally [L, `sale_order.py:864`, `:1150`].

### Accounting Evidence
IFRS 16 places the commencement date at the start of the term and needs a definite end to measure the lease term; it does not prescribe an inclusive or exclusive convention (no readable text says otherwise) [P].

### Options
A (inclusive stored, one derived boundary), B (exclusive stored), C (leave split). Compared in 3.5.

### Analysis
See 3.2–3.5. Option A changes two subsystems and one validation; Option B changes every human-facing surface. Option A also matches the business expectation stated for this phase and Odoo's own subscription module.

### EDARA Recommendation
**Option A** as defined in 3.1, with the helper `term_boundary = end_date + 1 day`, `_check_dates` relaxed to `end_date >= start_date`, the schedule generator and overlap constraint switched to the helper, and the migration in 3.7. A single-day lease becomes valid (3.6). One convention, no subsystem defines its own.

### Confidence
HIGH for the architecture (it follows from the measured code split); MEDIUM on the adequacy of the printed-contract wording, which needs a template check.

### External Validation
Legal (non-blocking): confirm that the customers' standard template states the last day of the tenancy, so operators enter it as the Business End. This changes an operator instruction, not the architecture: if a template used the other reading, only the entry convention and the migration classification flip.

### Implementation Impact
`edara_lease_contract.py` (helper, `_generate_schedule_lines`, `_check_no_overlap`, `_check_dates`), `edara_payment_schedule_line.py` (period constraint uses `period_end` as exclusive — unchanged), `edara_unit.py` (occupancy compares `today < term_boundary`, equal to today's `end_date >= today`), expiry cron (condition unchanged), wizard (default unchanged), tests (the adjacent-lease and overlap tests are re-expressed with inclusive ends), data-migration script, contract form help text.

### Sources
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifrs-16-leases.pdf
- https://realestatelicensewizard.com/lease-expiration/ (weak)
- https://www.debtbook.com/learn/blog/what-is-a-lease-end-date (weak)
- Local: `odoo/addons/sale_subscription/models/sale_order.py` (lines 864, 1150)

---

## OD-B4 — Keep `renewed` as a terminal state, or fold it into `expired` + link

**Status:** RECOMMENDED.

### Question
Is a contract that was continued by a successor `renewed`, or `expired` with a link to the successor?

### Current EDARA Behavior
`renewed` exists and is set **at click time** by `action_renew` [L: line 367]. Phase 7 added special handling so `renewed` contracts are still invoiced [L: `_process_due_invoices`].

### Industry Evidence
Buildium keeps the old lease and its renewed lease as separate records and moves the ledger and deposits to the renewed lease [V]. Odoo Subscriptions keeps prior orders with their own status and lists them in a history [P]. No readable page documents a state literally named "renewed".

### Accounting Evidence
None (a workflow label, not an accounting concept).

### Options
1. Keep `renewed` as a terminal state, reached at the boundary. 2. Remove `renewed`; use `expired` + a derived "renewed" flag from the successor link.

### Analysis
Option 2 loses nothing structurally but changes an existing state value used by tests, reports, filters, the portal and existing data; it buys no billing or occupancy benefit. Option 1 keeps the label that reports and the renewal-rate KPI need. The defect today is the *timing* of the flip, not the state's existence.

### EDARA Recommendation
**Option 1.** `renewed` is terminal and is reached only by the transition job at the old contract's boundary (or by a late renewal, OD-B2). It is never set by clicking Renew. The Phase 7 `renewed`-billing special case becomes redundant once timing is corrected but stays harmless as a safety net.

### Confidence
MEDIUM.

### External Validation
None.

### Implementation Impact
`action_renew` (stop writing `renewed`), transition job, tests that assert `renewed` immediately after `action_renew` (`test_renew_creates_active_successor_and_marks_predecessor_renewed`) and the two Phase 7 early-renewal tests, state migration (4.6).

### Sources
- https://www.buildium.com/blog/new-feature-announcement-lease-renewals/
- https://www.odoo.com/documentation/19.0/applications/sales/subscriptions/renewals.html

---

## OD-B5 — Successor contract state before its start date

**Status:** RECOMMENDED.

### Question
What is the state of a signed renewal whose start date has not arrived?

### Current EDARA Behavior
`action_renew` creates the successor and immediately calls `action_activate()`: it becomes `active` with a future start, and its unit is marked `reserved` by BD-001 [L]. The overlap check ignores every state except `active`. An `active` successor inflates any count or sum filtered on state alone.

### Industry Evidence
No readable vendor page documents a "signed but not started" status; Buildium's status list was unreadable. Odoo Subscriptions invoices on a tracked next-invoice date, so a future renewal is not billed early [P].

### Accounting Evidence
IFRS 16 applies a modification from its effective date, not from signing [P].

### Options
Draft; `scheduled`; active with future start; a flag. Compared in 4.5.

### Analysis
`draft` fails the "prevent double-leasing" requirement because non-active contracts are not in the overlap check. Active-with-future-start satisfies protection but makes "active" mean "signed", which pollutes every report (principle 13). `scheduled` satisfies both, and is the same pattern as the existing reserved→rented daily job. It also gives BD-001 one clean rule: reserved ⇔ a scheduled contract exists.
Schedule timing: generate at **confirmation**, not at activation. Reasons: the portal and cash-flow forecasts show the coming periods; the code path is unchanged (`action_activate` generates today); cancellation removes only uninvoiced lines, and a `scheduled` contract has none invoiced (billing is gated by `active` and by `due_date ≥ start_date`).

### EDARA Recommendation
**`scheduled`** with the state machine in section 4. Confirm sets `scheduled` when `Start > today`, else `active`. The unit is `reserved` while only a scheduled contract exists and `rented` while the old contract is `active`. The transition job (4.3) activates it.

### Confidence
MEDIUM (design reasoning; no vendor precedent could be read).

### External Validation
None.

### Implementation Impact
`edara_lease_contract.py` (states, `action_activate`, `action_renew`, transition job, cancellation), `edara_unit.py` (occupancy derivation and the reserved-sync cron), `edara_cron.xml`, overlap constraint (states `active` + `scheduled`), contract views (statusbar, filters, badges), portal (shows scheduled contracts as "Upcoming"), dashboard/reports (counts by state), `edara.system.field.guard` (new state under the guard), state migration (4.6), roughly a dozen existing lifecycle tests rewritten.

### Sources
- https://www.odoo.com/documentation/19.0/applications/sales/subscriptions/renewals.html
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifrs-16-leases.pdf

---

## OD-B6 — A renewal that overlaps the old term mid-period

**Status:** RECOMMENDED.

### Question
If a successor starts before the old contract's boundary, does the old period straddling the start get truncated, billed to its end, or is such a renewal disallowed?

### Current EDARA Behavior
Phase 7: `action_renew` drops the predecessor's *uninvoiced* lines whose `period_start ≥ successor start`. A period that straddles the successor start, and any *invoiced* period past that start, remain, so the same days can be billed under both contracts [L: `action_renew`, lines 375-377; tests `test_overlapping_renewal_drops_only_periods_successor_covers`]. It was built for an early renewal semantic that the state machine of section 4 replaces.

### Industry Evidence
No readable vendor page addresses overlapping renewals. Buildium's renewal takes effect "when the old one ends" [V].

### Accounting Evidence
Truncating an already-invoiced straddling period would require a credit note, i.e. rewriting billed history, which principles 5–7 forbid as a lifecycle side effect.

### Options
1. Disallow: the successor must start at or after the predecessor's boundary. 2. Truncate the straddling old period (drop or prorate it). 3. Bill the old period to its end and start the successor afterward.

### Analysis
Option 2 is unsafe when the straddling period is invoiced, and needs a credit-note workflow EDARA does not have. Option 3 moves the successor start away from the date the parties agreed. Option 1 removes the problem: no straddling period can exist. A genuine mid-term replacement of terms is a different business event (end the old lease at a date, start a new one), and is not a renewal.

### EDARA Recommendation
**Option 1.** The renewal action refuses a `start_date` earlier than the predecessor's `term_boundary`, with the message "A renewal starts when the current term ends; to change terms mid-term, end the current contract first." A start **later** than the boundary (a gap) is allowed with a visible warning (the unit is `reserved` in the gap, BD-001). The Phase 7 code that drops overlapping lines becomes unreachable and is removed. A future capability for "replace terms mid-term" is out of scope and is not implied.

### Confidence
HIGH.

### External Validation
None.

### Implementation Impact
`action_renew` validation, renewal wizard default (already `end + 1` = the boundary), deletion of the overlapping-line drop, rewriting `test_overlapping_renewal_drops_only_periods_successor_covers`.

### Sources
- https://www.buildium.com/blog/new-feature-announcement-lease-renewals/
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifrs-16-leases.pdf

---

## OD-B7 — Reminder for a `scheduled` successor that fails to start

**Status:** RECOMMENDED.

### Question
After how many days should the system remind someone that a scheduled successor never started?

### Current EDARA Behavior
No such state exists today (a successor is `active` immediately). The daily jobs that touch lifecycle are `_cron_expire_contracts`, `_cron_sync_reserved_occupancy` and the 30/7-day expiry reminders [L].

### Industry Evidence
Propertyware's renewal blog recommends a structured cycle (checkpoints at 90/60/30 days) before expiry [V]. Nothing readable covers a signed lease that fails to start.

### Accounting Evidence
None.

### Options
1. A reminder after N days of a stalled scheduled contract. 2. No reminder. 3. Fail loudly on the day the job cannot activate.

### Analysis
Under the section 4 design a scheduled contract that reaches its start date is activated by the daily job in the same run; it can only stall when a precondition fails on that day (unit sold or under maintenance, an overlapping lease slipped in). Waiting N days to report that would let a paying tenant occupy an un-invoiced unit for N days. The correct threshold is therefore **the day itself**. A tenant who never physically moves in is not a system state: the contract is `active` and invoiced (a business matter).

### EDARA Recommendation
**Option 3, N = 0.** If the job cannot activate a scheduled contract on its start date, it (1) leaves the contract `scheduled`, (2) posts a chatter note with the failing precondition, (3) creates a to-do for the branch manager (`_get_reminder_responsible_user`, existing helper), and (4) retries the next run and repeats the to-do once a day until resolved. No automatic cancellation and no automatic activation past a failed precondition.

### Confidence
MEDIUM.

### External Validation
None.

### Implementation Impact
Transition job, reuse of the existing reminder-user helper and activity pattern from `_cron_send_expiry_reminders`, tests (unit sold on the start date; overlap appeared).

### Sources
- https://www.propertyware.com/blog/lease-renewal-process-pro-tips/

---

## OD-B8 — Deposit carry-over on renewal

**Status:** NEEDS ACCOUNTANT.

### Question
When a tenant renews and a deposit is held on the old contract, what happens to it?

### Current EDARA Behavior
`action_renew` copies `deposit_required` and `deposit_amount` to the successor. The successor's deposit record is created later, uncollected, by the contract's Deposit button (`unique(contract_id)`). The old deposit stays `held` on the finished contract; nothing links the two [L]. The tenant appears to owe a second deposit while the first is still held.

### Industry Evidence
Buildium: on renewal all tenant notes, files, bank transactions, ledger balances and credits, **security deposits and other liabilities** move to the renewed lease automatically [V, fetched]; a separate help article exists titled "How to transfer a security deposit to a new lease" [S, title from search results only]. DoorLoop's renewal wizard lets the deposit amount be updated [V].

### Accounting Evidence
A refundable deposit is a monetary liability (IAS 21 ¶16; PwC IND FAQ 4.10.1) [P, V]. The tenant, the company and the liability account do not change when a deposit is carried across a renewal for the same tenant, so the balance of the liability account does not change either. No cash moves.

### Options
- **A:** one deposit record spanning the chain of contracts.
- **B:** refund the old deposit and collect a new one.
- **C:** keep one deposit record per contract; move the balance with a paired *transfer* transaction, without a refund and without a new collection.

### Analysis
| Consideration | A: single record | B: refund and recollect | C: paired transfer |
|---|---|---|---|
| Cash and bank movements | none | two (refund out, collect in) | none |
| Native journal entries created | none | two payments | **none** (see below) |
| Audit trail | one history for the whole tenancy, but deductions from different contracts mix | complete but noisy; a bank fee/rate difference on each leg | per-contract history preserved, plus a linked pair showing the transfer |
| Change to existing schema | breaks `unique(contract_id)` and the contract-currency assumption | none | adds two transaction types |
| FX exposure | none | crystallises FX on the refund leg at one rate and a fresh basis on the new collect | none (same currency and same basis carried) |
| Tenant experience | none | tenant must pay again | none; only a top-up if the requirement rose |

- **No journal entry is created by Option C.** The tenant, company and liability account are the same on both sides, so the general-ledger balance does not change; the two paired `edara.deposit.transaction` records net to zero across the pair, so the sum of EDARA deposit balances still equals the liability account balance. **This is a design statement to be validated by the accountant, not an accounting entry defined here** ("do not invent accounting entries").
- Carry-over is allowed only when tenant, company and **deposit currency** are unchanged. A different currency would convert the liability (principle 4); a different tenant is not a renewal (Phase 9, edge-case 22); a different company is a different legal entity. In those cases Option B applies: settle first, then collect on the new contract.
- **Amount changes.** *Increase:* the successor's requirement exceeds the carried balance; the difference is collected on the successor's deposit in the deposit currency. *Decrease:* only the new requirement is carried; the excess stays on the old deposit and is refunded natively (the refund action already exists) — never automatically.
- **Partial or prior deductions.** The carried amount is the old deposit's **balance** (`held − refunded − deducted`), never its original amount. Deductions already booked stay in the old contract's history. A deduction the landlord intends for damage found at the end of the *old* term is recorded **before** the transfer; after the transfer it belongs to the successor's contract.
- **Property or landlord change.** The deposit liability account is not analytic-tagged (deposit payments carry no analytic distribution [L]), so a property change alone needs no entry; if the deposit's *owner* changes, that is OD-A3 (agent/principal) and out of scope.
- **Timing.** The transfer is executed **when the successor becomes `active`** (the transition job), not when the renewal is signed. Consequences: a **cancelled** renewal leaves the deposit untouched with no reversal; an **old contract terminated** before the successor starts keeps its own deposit for the normal refund/deduction process; and the old tenancy remains fully protected until it ends.
- **Old contract state after transfer.** The old deposit shows `closed` with a `transfer_out` transaction; the successor's deposit shows `held` with a `transfer_in` transaction and a top-up amount if any.

### EDARA Recommendation
**Option C.** Two new transaction types `transfer_out` / `transfer_in` on `edara.deposit.transaction`, created in one transaction, mutually linked, with chatter on both deposits, executed by the transition job when the successor activates, only if a `carry_over_deposit` choice was recorded at renewal (default **on** when the old deposit has a positive balance and the tenant, company and currency match). The deposit balance formula includes the two types. A currency, tenant or company change forces Option B.

### Confidence
MEDIUM.

### External Validation
Accountant: confirm that a transfer between two deposit records of the same tenant, company, currency and liability account needs no journal entry, and that the sum-of-records = GL check is acceptable as the control.

### Implementation Impact
`edara_deposit_transaction.py` (types), `edara_deposit.py` (`_compute_amounts`, transfer method), the renewal wizard (carry-over choice and the top-up/refund preview), transition job, deposit views, portal deposit display, tests for ILS/USD/JOD (equal amount, increase, decrease, partial deduction beforehand, cancelled renewal, terminated old contract, different currency refused).

### Sources
- https://www.buildium.com/blog/new-feature-announcement-lease-renewals/
- https://help.buildium.com/hc/s/article/How-to-transfer-a-security-deposit-to-a-new-lease (weak)
- https://www.doorloop.com/blog/lease-extension
- https://viewpoint.pwc.com/dt/gx/en/pwc/industry/industry_INT/industry_INT/real_estate__1_INT/Applying-IFRS-for-the-real-est/Rental-income-accounting-by-lessors/frequently-asked-questions/ind-faq-4-10-1-how-should-an-entity.html
- https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-21-the-effects-of-changes-in-foreign-exchange-rates.pdf

---

## OD-B9 — Old contract terminated before a scheduled successor starts

**Status:** RECOMMENDED.

### Question
If the old contract is terminated while its successor is `scheduled`, does the successor cancel automatically, or does a user confirm?

### Current EDARA Behavior
`action_terminate` requires `state == 'active'`, sets `terminated`, syncs unit occupancy and drops future uninvoiced lines of the terminated contract. The successor is not consulted; today it is already `active` with a future start and remains so [L: `edara_lease_contract.py:327-343`]. A successor for a tenant who has left would keep its unit `reserved`.

### Industry Evidence
None readable.

### Accounting Evidence
A `scheduled` successor has no invoice, payment or deposit transfer (transfers run at activation, OD-B8), so cancelling it changes no posted accounting.

### Options
1. Auto-cancel the successor silently. 2. Auto-cancel after an explicit confirmation. 3. Leave it scheduled. 4. Block termination until the user cancels the successor.

### Analysis
Option 3 leaves a contract that will activate for a tenant who has left, which principle 9 prohibits. Option 1 removes information without telling anyone. Option 4 forces two steps for what is one decision. Option 2 keeps it one step and shows the consequence. The operator who wants to keep the successor (for example to re-sign with a different tenant) can cancel and recreate it; nothing is lost because a scheduled contract carries no accounting.

### EDARA Recommendation
**Option 2.** `Terminate` on a contract that has a `scheduled` successor shows a confirmation ("This also cancels scheduled renewal LC/…"); on confirm, the successor moves to `cancelled` in the same transaction, both chatters record it, and the successor's uninvoiced lines are removed. Never auto-activate a successor for a tenant whose predecessor was terminated.

### Confidence
MEDIUM.

### External Validation
None.

### Implementation Impact
`action_terminate` (successor handling in one transaction), confirmation attribute in the view, `cancelled` state and its guard, tests.

### Sources
- Local: `edara_lease_contract.py` `action_terminate`; state-machine reasoning in section 4.

---

## OD-B10 — Holdover policy

**Status:** NEEDS LEGAL.

### Question
What should the system do when the end date passes, the tenant is still in possession, and no renewal or termination has been completed?

### Current EDARA Behavior
The expiry cron moves the contract to `expired` the day after its end date and drops future uninvoiced lines. The unit becomes `available` through `_sync_occupancy_from_contracts`. The system has no holdover concept, does not bill after the term, and has no periodic ("month-to-month") contract type; `end_date` is required [L].

### Industry Evidence
- Buildium's rollover option: a fixed-term lease can move to an "at will" status at its end date instead of `expired`, and keep posting rent until ended [S, Buildium Help excerpt — weak]. Buildium also states that at-will leases cannot be renewed [S].
- Cornell Legal Information Institute: a holdover tenant remains after the lease ended; whether accepting rent creates a periodic tenancy or a renewal depends on the jurisdiction [V, fetched in Phase 9].
- RentRedi documents converting a lease to month-to-month, after which recurring rent charges continue [S, not among the priority platforms — weak].

### Accounting Evidence
Revenue for occupancy after the term is recognised when the right to occupy and the price are established; which of those hold in a holdover is a contract and legal fact, not an accounting default.

### Options
1. Auto month-to-month: the contract rolls into a periodic tenancy and keeps invoicing.
2. Remain `active` temporarily (grace), no billing.
3. `expired` but flagged occupied; owner decides.
4. Block occupancy: the unit becomes `available` and staff re-let it.
5. Require explicit owner action: a task, then a late renewal or a termination record.

### Analysis
Options 1 and 2 both create billing or entitlement that the parties never agreed to in writing and that Cornell [V] says can create a tenancy by conduct in some jurisdictions; auto-billing after the term could itself be treated as acceptance. Option 2 also breaks the single date convention (an `active` contract past its boundary). Option 4 keeps occupancy tied to the contract but leaves a physically occupied unit `available`, and no one is told. Option 3/5 together keep the contract's end date true, do not invent a tenancy, and make the human decision visible. The system cannot decide whether a periodic tenancy exists; a lawyer can.

### EDARA Recommendation (product rule, not a legal claim)
1. **The system never extends, renews, or bills a period after the boundary on its own.** At the boundary the contract becomes `expired` (or `renewed` if a successor exists).
2. On the day after the boundary with no successor, the job creates a **holdover to-do** for the branch manager: "Contract LC/… ended yesterday. Confirm the tenant has vacated, or record a late renewal." Reminders repeat until resolved. The unit follows BD-001 (`available`), and the to-do names the unit so staff do not re-let it without checking.
3. Resolution paths: **late renewal** (OD-B2, within its window) if the tenant stays; or **no action** if the tenant vacated (the to-do is completed).
4. A periodic month-to-month contract type is **not built** until legal review states whether a periodic tenancy arises in the customers' jurisdiction and what rent applies. Until then a tenant who stays is handled by short renewals (for example one-month renewals) chosen by the owner.
5. Any holdover rent rate or penalty comes only from the signed contract, entered as a normal renewal rent, never computed by the system.

### Confidence
HIGH that legal review is required; MEDIUM for the interim product rule.

### External Validation
Legal (whether acceptance of rent after expiry creates a periodic tenancy or a renewal; any holdover-rate clause; notice periods).

### Implementation Impact
Transition job (to-do creation), reminder helper reuse, late-renewal path (OD-B2), documentation for staff; no schema change.

### Sources
- https://www.law.cornell.edu/wex/holdover_tenant
- https://help.buildium.com/hc/s/article/How-to-renew-a-lease (weak)
- https://help.rentredi.com/en/articles/11832039-convert-a-lease-to-month-to-month (weak)

---

## 9. Renewal behavior: confirm, modify or reject (checklist from the brief)

| # | Assumption | Verdict | Basis |
|---|---|---|---|
| 1 | Old contract stays ACTIVE while inside its term | **Confirmed** | Buildium renews "when the old one ends" [V]; IFRS 16 effective-date treatment [P]; section 4 |
| 2 | Unit stays RENTED | **Confirmed** | 4.4; fixes Phase 7's `reserved` observation |
| 3 | New successor is not ACTIVE before its start date | **Confirmed** | `scheduled` (OD-B5) |
| 4 | Existing invoices remain untouched | **Confirmed** | Section 6 |
| 5 | Existing paid invoices remain untouched | **Confirmed** | Section 6; Odoo immutability [L] |
| 6 | Existing future invoices remain untouched unless a business rule requires otherwise | **Confirmed, with no such rule defined** | Section 6; no exception is recommended |
| 7 | New payment schedules belong to the successor's own term | **Confirmed**, and *generated at confirmation*, not at activation | Section 5; OD-B5 |
| 8 | No period may be invoiced twice | **Confirmed** as an enforced invariant | Section 5 |
| 9 | The unit must not become AVAILABLE/RESERVED merely because a renewal was signed | **Confirmed** | 4.4 (reserved only when there is no active contract today) |
| 10 | Successor becomes ACTIVE when its effective date is reached | **Confirmed** | Transition job 4.3 |
| 11 | Old contract becomes RENEWED at the appropriate transition point | **Modified** | At the old contract's **own boundary** if a successor exists (0.5, item 2), not "when the successor activates" |
| 12 | Successor may start earlier than the old end | **Rejected** | OD-B6 |

---

## 10. Accounting scenarios

All rate figures are **illustrative**, not market data. "Native" means Odoo produces the entry without EDARA-specific code. No entry below is invented: each is either an entry EDARA already posts (verified in Phase 8 tests), a native Odoo process, or explicitly marked as requiring accountant validation. Sign convention: Dr = debit, Cr = credit; amounts as `amount_currency / company-currency balance`.

### 10.1 Deposit

| Scenario | Entry / behavior | Source |
|---|---|---|
| **Collect in ILS** (company currency) | Dr Bank 1,000 ILS / Cr Deposit liability 1,000 ILS. No currency conversion. | Phase 8 tests [L] |
| **Collect in USD** 1,000 at 3.70 | Native payment: Dr Bank USD 1,000 / ILS 3,700; Cr Deposit liability USD −1,000 / ILS −3,700. | Phase 8 tests [L] |
| **Collect in JOD** 500 at 5.26 | Same shape; the company-currency amount follows the payment-date rate. | Phase 8 tests [L] |
| **Deduct in contract currency** USD 200 at 3.80 | Dr Deposit liability USD 200 / ILS 760; Cr Deduction income USD −200 / ILS −760, dated the deduction date (Phase 8 fix). | `action_deduct` [L] |
| **Refund in contract currency** USD 800 | Native payment out in USD; Dr Deposit liability, Cr Bank, at the refund-date rate. | Phase 8 tests [L] |
| **Remeasurement at period end** (USD 1,000 collected at 3.70, closing 3.90) | The liability carrying amount rises from 3,700 to 3,900 ILS; Odoo's Unrealized Currency Gains/Losses report proposes the **Adjustment Entry** (loss 200) with auto-reversal on the chosen date. **Requires OD-A7 (eligible account).** | Native [P] |
| **Realised FX at settlement** (refund of USD 1,000 at 3.80 against a liability originally booked at 3.70) | The residual 100 ILS between the refund line (3,800) and the collect line (3,700) is booked by Odoo as a native exchange-difference entry when the two lines are **fully reconciled**. **Requires OD-A7 and reconciling the deposit lines when `closed`.** | Native [P, L] |
| **Cap** | Collection above `amount − amount_held` is rejected (OD-A4). | EDARA Recommendation |

### 10.2 Renewal

| Scenario | Behavior |
|---|---|
| **Same deposit** (USD 1,000 held, requirement USD 1,000) | At successor activation: `transfer_out` on the old deposit (balance 0, `closed`) and `transfer_in` on the new one (`held`, USD 1,000). **No journal entry.** Accountant to validate (OD-B8). |
| **Increased deposit** (requirement USD 1,500) | Transfer USD 1,000; the successor's remaining USD 500 is collected by the normal collect action in USD. |
| **Decreased deposit** (requirement USD 800) | Transfer USD 800; the excess USD 200 stays held on the old deposit and is refunded by the normal refund action. Never automatic. |
| **Carry-over with prior deduction** (USD 100 deducted before renewal) | The carried amount is the balance USD 900; the successor's remaining requirement (USD 100) is a top-up. The deduction stays in the old contract's history. |
| **Deposit deduction before renewal** | Booked as today (Dr liability, Cr deduction income); only the balance is carried. |
| **Currency changes / different tenant / different company** | Carry-over is refused; the old deposit is refunded or deducted, a new one is collected. |
| **Renewal cancelled before it starts** | Nothing posted, nothing to reverse: schedule lines on the successor are uninvoiced and are removed; the transfer never ran. |
| **Old contract terminated before the successor starts** | Successor cancelled (OD-B9); the old deposit follows the normal refund/deduction path. |

### 10.3 Extension

| Scenario | Behavior |
|---|---|
| **Existing invoiced periods** | Untouched; the extension only appends. |
| **New extended periods** | Lines created only from the first uncovered boundary to the new boundary (section 5); e.g. extending to `31/03/2027` adds 3 monthly lines [C]. |
| **Already-paid periods** | Untouched; a paid invoice is never altered by an extension. |
| **Extension cancelled or reverted** (the user asks to undo) | If **none** of the new lines has an invoice, the extension is reverted by removing those lines and restoring the previous end date through a guarded "Revert extension" (recorded in the log). If any new line has been invoiced, the periods are consumed (section 5): the contract is **terminated** at the desired date, and any invoiced period beyond it is a credit-note question for the accountant. No line is deleted and no invoice is voided by the lifecycle. |
| **Extension while a successor is scheduled** | Blocked (OD-B5 / 4.2). |

---

## 11. Current Implementation vs Recommended Decisions

Severity: CRITICAL / HIGH / MEDIUM / LOW / INFORMATIONAL. "Future Phase" is a suggested slicing, not a commitment: **10A** = date convention, states, extension, schedule integrity; **10B** = deposit; **10C** = alternative currency, holdover follow-up, optional items.

| # | Area | Current Behavior | Recommended Behavior | Severity | Future Phase |
|---|---|---|---|---|---|
| G-01 | End-date convention | Schedule and overlap exclusive; expiry, occupancy, reminders and wizard inclusive (3.2) | One inclusive business date, one `term_boundary` helper | **HIGH** | 10A |
| G-02 | Billing of last-day-entered contracts | 1-month contract billed 900 (−10 %); yearly billed 1,011.11 (+1.11 %) [C] | Boundary-based generation: 1,000 exact | **HIGH** | 10A |
| G-03 | Date validation | `end_date <= start_date` rejected; single-day lease impossible | `end_date >= start_date` | LOW | 10A |
| G-04 | Existing contract data | Two entry styles coexist; LC/2026/0012 and LC/2026/0015 share 31/12/2026 | Reviewed per-contract migration (3.7) | MEDIUM | 10A |
| G-05 | Extension | No Extend action; editing `end_date` on an active contract creates **no billing** for the added time | Extend action, end-date lock, incremental generation | **CRITICAL** (silent revenue leak, principle 12) | 10A |
| G-06 | Schedule regeneration | Regenerates every period from `start_date`; overlaps invoiced periods (1,633.33 for one December, 5.3) | Generate by coverage; unit-level period non-overlap constraint | **CRITICAL** if reused for extension; HIGH as a latent defect | 10A |
| G-07 | Old contract state on renewal | Flipped to `renewed` at click time | Stays `active` to its boundary | MEDIUM | 10A |
| G-08 | Successor state | `active` with future start; not protected by a dedicated state | `scheduled`; `cancelled` | MEDIUM | 10A |
| G-09 | Unit occupancy in renewal | Old contract renewed-but-in-term ⇒ unit `reserved` | Unit stays `rented` | MEDIUM | 10A |
| G-10 | Renewal overlap | Overlapping renewal allowed; straddling and invoiced periods can double-bill | Successor must start ≥ predecessor boundary | HIGH | 10A |
| G-11 | Overlap constraint | Considers only `active` contracts | Considers `active` + `scheduled` on `[start, boundary)` | MEDIUM | 10A |
| G-12 | Lifecycle job | Separate crons; no ordered transition; no activation preconditions report | One ordered daily job with failure to-dos (OD-B7) | MEDIUM | 10A |
| G-13 | Editable terms after confirmation | `rent_amount`, `billing_frequency`, `currency_id`, `end_date` editable with no effect on the schedule | Locked; changes through renewal/Extend | MEDIUM | 10A |
| G-14 | Deposit across renewal | Successor gets a separate uncollected deposit; old deposit orphaned | Paired transfer at successor activation | MEDIUM | 10B |
| G-15 | Deposit collection cap | `action_collect` accepts any positive amount | Capped at `amount − amount_held` | MEDIUM | 10B |
| G-16 | Deposit liability account | Not revaluation-eligible; collect/refund never reconciled, so realised FX is not booked | Eligible account (OD-A7) and reconciliation at `closed` | MEDIUM (accounting policy) | 10B, after accountant sign-off |
| G-17 | Late renewal | Expired contracts cannot be renewed | Window-limited late renewal (default 30 days) | LOW | 10C |
| G-18 | Holdover | Expires silently; unit `available`; no notice | Holdover to-do; no auto-billing | LOW | 10C |
| G-19 | Alternative-currency deposit payment | Not supported; silent off-system conversion by staff is possible | Spike (OD-A5); specified workflow (OD-A4) | LOW (feature) | 10C |
| G-20 | Billing gate for `expired` contracts | An `expired` contract's unbilled overdue line is never invoiced | Bill lines whose due date is inside the contract's own term | LOW | 10A |
| G-21 | Legacy USD deposit LC/2026/0007 (dev DB) | Liability account −540.75 ILS from pre-Phase 8 posting (Phase 8, "remaining risks") | Corrective journal entry by an accountant, or treat the dev data as disposable | INFORMATIONAL | none (data decision) |
| G-22 | Phase 7 `renewed`-billing special case | Bills `renewed` contracts | Redundant once G-07 is fixed; harmless | INFORMATIONAL | 10A |

The gaps that cannot be silently ignored while Phase 10 is planned are **G-05** and **G-06**: they are not caused by the new decisions; they exist now.

---

## 12. Final Decision Matrix

| Decision | Recommended Outcome | Status | Confidence | External Validation | Main Impact |
|---|---|---|---|---|---|
| OD-A1 | Contract stores the currency of the obligation explicitly; single currency per contract in Phase 10; independent deposit currency only if a template survey shows mixed-currency contracts | RECOMMENDED | HIGH (rule); LOW (whether mixed contracts exist) | Legal (non-blocking template check) | Contract form help text; deposit model only if later needed |
| OD-A2 | Deposits held at face value; no present-value discounting | NEEDS ACCOUNTANT | MEDIUM | Accountant | Documentation only |
| OD-A3 | EDARA v1 supports operator-held deposits only; no escrow/agent mode | NEEDS ACCOUNTANT + LEGAL | MEDIUM | Accountant + Legal | Documentation and onboarding question |
| OD-A4 | Contract-currency payment only, with a collection cap; alternative-currency workflow fully specified but deferred | RECOMMENDED | HIGH (A); MEDIUM (B spec) | None now; Accountant before Option B | `action_collect` cap; wizard message; later wizard/transaction fields |
| OD-A5 | Not a business decision; a defined test-database spike (three acceptance tests) decides whether Option B is cheap | OPEN | LOW | None (Accountant reviews entries before release) | Test-only spike |
| OD-A6 | Remeasure at each reporting date using Odoo's native adjustment entry with auto-reversal; month-end if the company closes monthly, else year-end | NEEDS ACCOUNTANT | MEDIUM | Accountant | Operating procedure; depends on OD-A7 |
| OD-A7 | `liability_payable` account for deposits (eligible for revaluation and reconcilable); reconcile the lines when a deposit closes; fall back to per-currency locked accounts if payables presentation is refused | NEEDS ACCOUNTANT | MEDIUM | Accountant | Company account setup; `edara_deposit.py`; tests |
| OD-B1 | Extension changes the end date only (later); any other change is a renewal | RECOMMENDED | HIGH | None | Extend action; field locks; tests |
| OD-B2 | Late renewal allowed on `expired` contracts within a company setting (default 30 days); no late extension | RECOMMENDED | HIGH (mechanism); LOW (30) | Legal (back-billing in holdover) | Renewal action/wizard; setting; `expired → renewed` |
| OD-B3 | End Date is the last occupied day; one derived `term_boundary = end_date + 1` used by all interval logic | RECOMMENDED | HIGH (architecture); MEDIUM (template wording) | Legal (non-blocking) | Generator, overlap, validation, occupancy; data migration |
| OD-B4 | Keep `renewed` as a terminal state, reached only at the old contract's boundary | RECOMMENDED | MEDIUM | None | `action_renew`; transition job; tests |
| OD-B5 | New `scheduled` state (and `cancelled`); schedule generated at confirmation; invoicing gated by `active`; one ordered daily transition job | RECOMMENDED | MEDIUM | None | States, occupancy, overlap, cron, views, portal, ~12 tests |
| OD-B6 | A renewal must start at or after the predecessor's boundary; overlapping renewals disallowed | RECOMMENDED | HIGH | None | `action_renew` validation; remove overlap-drop code; tests |
| OD-B7 | Alert on the start day itself when a scheduled contract cannot activate; retry daily; never auto-cancel | RECOMMENDED | MEDIUM | None | Transition job; to-do helper reuse |
| OD-B8 | Carry the deposit balance with paired transfer transactions at successor activation; no cash movement and no journal entry; refuse if currency, tenant or company changes | NEEDS ACCOUNTANT | MEDIUM | Accountant | Deposit transaction types, balance formula, wizard, transition job, tests |
| OD-B9 | Terminating the old contract also cancels a scheduled successor, after an explicit confirmation | RECOMMENDED | MEDIUM | None | `action_terminate`; view confirmation; tests |
| OD-B10 | The system never extends, renews or bills after the boundary on its own; holdover to-do; late renewal as the resolution; no periodic-tenancy type until legal review | NEEDS LEGAL | HIGH (need for review); MEDIUM (interim rule) | Legal | Transition job to-do; no schema change |

**Counts.** Reviewed: 17 of 17. `RECOMMENDED`: OD-A1, A4, B1, B2, B3, B4, B5, B6, B7, B9 (10). `NEEDS ACCOUNTANT`: OD-A2, A6, A7, B8 (4). `NEEDS ACCOUNTANT + LEGAL`: OD-A3 (1). `NEEDS LEGAL`: OD-B10 (1). `OPEN`: OD-A5 (1).

---

## 13. Verification against the Phase 9.1 checklist

| # | Check | Result |
|---|---|---|
| 1 | All 17 Open Decisions from Phase 9 Section 15 addressed | Yes: OD-A1…A7, OD-B1…B10, each in its own section in section 8 |
| 2 | Every decision has question, current behavior, industry evidence, accounting evidence, options, analysis, recommendation, confidence, external validation, implementation impact, sources | Yes; where no industry evidence exists the section says so explicitly |
| 3 | OD-B3 resolved or marked for external validation | Resolved as RECOMMENDED; wording check is a non-blocking Legal validation |
| 4 | Renewal/extension distinction explicit | Section 2 |
| 5 | Deposit currency policy explicit | OD-A1, A4, A5, A7; section 7 |
| 6 | Successor lifecycle explicit | Section 4; OD-B5, B9 |
| 7 | Deposit carry-over explicit | OD-B8 and 10.2 |
| 8 | Holdover explicit | OD-B10 |
| 9 | Payment-period double-invoicing prevention explicit | Section 5 |
| 10 | No source-code or database changes | Confirmed: `git status` shows only `docs/` additions; one read-only `SELECT` session was used against the dev database; no module update, no server restart |

---

## 14. Sources

**Accounting standards and Odoo documentation [P]**
- IAS 21 — https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-21-the-effects-of-changes-in-foreign-exchange-rates.pdf
- IFRIC 22 — https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifric-22-foreign-currency-transactions-and-advance-consideration.pdf
- IFRS 16 (paragraph numbers for lessor modifications not confirmed in the extracted text) — https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifrs-16-leases.pdf
- Odoo 19 multi-currency — https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html
- Odoo 19 foreign-currency bank account, unrealised gains and losses — https://www.odoo.com/documentation/19.0/applications/finance/accounting/bank/foreign_currency.html
- Odoo 19 foreign currencies (rate providers) — https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/prices/currencies.html
- Odoo 19 renew subscriptions — https://www.odoo.com/documentation/19.0/applications/sales/subscriptions/renewals.html

**Professional and vendor pages read [V]**
- PwC Viewpoint IND FAQ 4.10.1 (refundable tenant deposits) — https://viewpoint.pwc.com/dt/gx/en/pwc/industry/industry_INT/industry_INT/real_estate__1_INT/Applying-IFRS-for-the-real-est/Rental-income-accounting-by-lessors/frequently-asked-questions/ind-faq-4-10-1-how-should-an-entity.html
- BDO New Zealand, accounting for forex transactions — https://www.bdo.nz/en-nz/blogs/financial-reporting-insights/accounting-for-forex-transactions
- Buildium blog, lease renewals — https://www.buildium.com/blog/new-feature-announcement-lease-renewals/
- Buildium blog, lease extension — https://www.buildium.com/blog/lease-extension-agreement/
- DoorLoop, extension vs renewal — https://www.doorloop.com/blog/lease-extension
- Propertyware blog, renewal process — https://www.propertyware.com/blog/lease-renewal-process-pro-tips/
- Cornell LII, holdover tenant — https://www.law.cornell.edu/wex/holdover_tenant

**Weak evidence, excerpts only [S] — not relied on alone for any conclusion**
- Buildium Help: renew a lease — https://help.buildium.com/hc/s/article/How-to-renew-a-lease
- Buildium Help: transfer a security deposit to a new lease — https://help.buildium.com/hc/s/article/How-to-transfer-a-security-deposit-to-a-new-lease
- Buildium Help: security deposit lifecycle — https://help.buildium.com/hc/s/article/Security-deposit-lifecycle-1557493000858
- Buildium Help: refund or withhold deposits held by a rental owner — https://help.buildium.com/hc/s/article/How-to-withhold-or-refund-a-security-deposits-held-by-a-rental-owner
- Deloitte DART ASC 830-10 §4.3 — https://dart.deloitte.com/USDART/home/codification/broad-transactions/asc830-10/roadmap-foreign-currency-transactions-translations/chapter-4-foreign-currency-transactions/4-3-subsequent-measurement-foreign-currency
- General lease-drafting excerpts on end dates — https://realestatelicensewizard.com/lease-expiration/ , https://www.debtbook.com/learn/blog/what-is-a-lease-end-date
- RentRedi Help (additional platform, not on the priority list) — https://help.rentredi.com/en/articles/11832039-convert-a-lease-to-month-to-month
- JustLanded, Israel rentals (consumer guide) — https://www.justlanded.com/english/Israel/Israel-Guide/Housing-Rentals/Rentals

**Local source and data [L, C]**
- EDARA module files and Odoo Enterprise addons listed in section 1.
- Schedule-algorithm simulation `scratchpad/sim.py` (not part of the project).
