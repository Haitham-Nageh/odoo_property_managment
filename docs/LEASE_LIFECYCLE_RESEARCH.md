# EDARA — Lease Lifecycle & Foreign Currency Business Rules Research

**Phase 9 — research only.** No application code, views, security, tests, manifests, schema or configuration were changed. This document is the only file added.
Date: 2026-09-24. Baseline: `property_managment` 19.0.1.0.0 @ commit `07cd5a1`, Odoo 19 Enterprise, company currency ILS (dev DB).

---

## 0. How to read this document

### Evidence grades (used on every important claim)

| Tag | Meaning |
|---|---|
| **[P]** | Primary text read in full: an accounting standard, or Odoo documentation. |
| **[V]** | Vendor / practitioner page whose content I actually fetched and read. |
| **[S]** | Only a web-search excerpt was available (the page itself was JavaScript-rendered, blocked, or unreadable to my tools). Treat as **weak**; confirm before relying on it. |
| **[L]** | Local source code inspected (EDARA module or the installed Odoo 19 Enterprise addons). Verifiable in this repository. |
| **[R]** | Reasoning / recommendation by me. Not evidence. |

### Labels for conclusions
- **RECOMMENDED** — evidence is strong enough to adopt.
- **OPEN DECISION** — evidence is mixed, jurisdiction-dependent, or is a business/legal choice. Needs a human decision.

### What could NOT be obtained (stated up front)
- **Yardi, MRI, Entrata**: no usable first-party documentation. A Yardi blog returned HTTP 403; MRI/Entrata were not reachable through search. **No Yardi/MRI/Entrata claim is made anywhere below.**
- **Buildium and Propertyware help centers** (`help.buildium.com`, `support.propertyware.com`) render with JavaScript and returned only "loading" shells. I therefore rely on Buildium's *blog* pages [V] and on search-result excerpts of the help pages [S].
- **AppFolio**: search excerpts only [S].
- A property-management-platform survey statistic that appeared in one search summary (a "64 %" figure attributed to a housing council) could not be traced to a source and is **not used**.
- One search summary claimed "deposits are non-monetary under IAS 21". **This is wrong for refundable deposits** and was overridden by the standard's own text (Section A2).
- Local-GAAP status of IFRS in Palestine/Jordan/Israel was **not verified**. Every accounting recommendation below assumes IFRS-style rules and must be confirmed with EDARA's actual auditor.

---

## 1. Current EDARA behavior (verified in code) — the baseline for comparison

All items **[L]**, verified against `models/edara_lease_contract.py`, `edara_unit.py`, `edara_payment_schedule_line.py`, `edara_deposit.py`, `wizard/edara_lease_renewal_wizard.py`, `edara_renewal_request.py`, `views/contract_views.xml`, `data/edara_cron.xml`, `tests/test_edara_lease_contract.py`, and the EDARA state file.

**Contract lifecycle.** States `draft → active → renewed | terminated | expired`.
- `action_activate()` (draft→active) generates the schedule *once*, at activation.
- **Renewal** (`action_renew`, also called by `edara.renewal.request.action_approve`): requires the old contract to be `active`; creates a *new* contract (successor) linked via `predecessor_contract_id` / `successor_contract_id`; **immediately** sets the old contract to `renewed`; **immediately** activates the successor, even if its `start_date` is in the future. The renewal wizard defaults the successor's start to `old end_date + 1 day`.
- **Extension**: **does not exist** as an action. However `end_date` is *editable on an active contract* (`readonly="state not in ('draft','active')"`), and there is no `write()` override — editing it **does not regenerate or extend the schedule**.
- `rent_amount`, `billing_frequency`, `currency_id` have no state-based `readonly`; editing them on an active contract does not affect already-generated lines.
- Overlap guard `_check_no_overlap`: only compares contracts in state `active`; `end_date` is **exclusive** (adjacent leases allowed, MAT-FIND-012).
- Expiry cron: `active` and `end_date < today` → `expired` (i.e. contract stays active through its end date).

**Schedule and invoicing.** One line per billing period from the `start_date` anchor; `end_date` exclusive (MAT-FIND-005); a final short period is prorated on a 30-day reference. Invoices are created by a daily cron on/after `due_date`; `unique(invoice_id)` links one invoice to one line. Uninvoiced *future* lines are removed on terminate/expire; already-due lines survive (MAT-FIND-006). Since Phase 7 a `renewed` contract is still invoiced for its own remaining lines. `_generate_schedule_lines()` unlinks only uninvoiced lines and then regenerates **all** periods from `start_date` (see 1.1).

**Unit occupancy** (BD-001): derived from *active* contracts only — `rented` if an active contract currently covers today (`start_date <= today <= end_date`, **inclusive** end), else `reserved` if an active contract starts in the future, else `available`. A daily cron flips `reserved → rented` when the start date arrives.

**Deposit.** One `edara.deposit` per contract (`unique(contract_id)`), created lazily by the contract's Deposit button. Amounts are in the contract currency. Collect/refund = native `account.payment` (deposit currency, native conversion); deduction = plain journal entry (currency-correct since Phase 8) against the configured deposit-liability and deduction-income accounts. `action_collect` only requires `amount > 0` — **there is no cap against `deposit.amount`**. The deposit-liability account used in tests/dev is of type `liability_current`. `action_renew` copies `deposit_required`/`deposit_amount` to the successor; nothing transfers or links the predecessor's held deposit.

### 1.1 Conflicts already visible between current behavior and the recommendations below
(Full list in Section 12; these are the ones that drive design.)

1. Renewing flips the old contract to `renewed` at click-time although it is still legally in force until `end_date`.
2. During the rest of the old term the unit shows `reserved` (observed live in Phase 7) although the tenant is in occupation.
3. Wizard default `old end + 1 day` leaves a one-day gap under EDARA's own *exclusive* end-date convention; occupancy uses an *inclusive* end. The two conventions disagree on the boundary day.
4. An "extension" is possible only by editing `end_date`, which silently produces **no billing** for the extended period.
5. Re-running `_generate_schedule_lines()` on a partly-invoiced contract would re-create periods already covered by invoiced lines.
6. Successor gets its own deposit record; the held predecessor deposit stays orphaned on the old contract.
7. Deposit liability account type is excluded from Odoo's foreign-currency revaluation (Section A5).

---

# PART A — FOREIGN CURRENCY SECURITY DEPOSITS

## A1. The contractual principle (validated)

EDARA's assumption: *if the lease says "Deposit = USD 1,000", the tenant's obligation and the landlord's refund obligation are USD 1,000; an exchange-rate move does not change that.*

- **Validated as a contractual principle by reasoning and by the accounting classification below (A2)**: a refundable deposit is an obligation to hand back a *fixed number of currency units*. **[P]** IAS 21 ¶16, **[R]**.
- A regional practice note **[S]** (JustLanded, Israel guide, secondary): rentals can be quoted in one currency and paid in shekels with a contractual minimum exchange rate — i.e. the *contract* fixes which currency the obligation is in and how conversion works. This supports storing the contract currency and treating other payment currencies as settlement mechanics. Low weight (a consumer guide).
- **OPEN DECISION OD-A1**: the actual contract wording used by EDARA's customers ("USD 1,000, payable in USD only" vs "USD 1,000, payable in ILS at the day's rate" vs "ILS 3,700 fixed") must be checked. EDARA's model can only be "contract currency = obligation currency" if the contracts say so. A contract that fixes an ILS amount must be modeled as an ILS deposit, not a USD one.

## A2. What currency should the deposit liability represent? — RECOMMENDED: the contract (deposit) currency

**Facts.**
- **[P] IAS 21 ¶16** — "The essential feature of a monetary item is a right to receive (or an obligation to deliver) a fixed or determinable number of units of currency." Its listed monetary examples include "provisions that are to be settled in cash" and "lease liabilities"; its non-monetary examples include "amounts prepaid for goods and services". (Text extracted from the IFRS Foundation PDF.)
- **[P] IFRIC 22** scope — it applies when an entity recognises a **non-monetary** asset/liability from *advance consideration* (a prepayment for goods, services or income not yet recognised). A refundable security deposit is repayable in cash; it is not consideration for a future supply, so IFRIC 22 does **not** apply to it. (A summarising search tool said the opposite; the primary text above governs.)
- **[V] PwC Viewpoint IND FAQ 4.10.1** — refundable tenant deposits held by a lessor are **financial liabilities under IFRS 9** when separate from the lease unit of account, initially at fair value and then at amortised cost. PwC's example does not discuss foreign currency.
- **[S] Buildium help (excerpts)** — security deposits sit as **liabilities**; a refund reduces the liability; a *withheld* deposit turns the liability into income. This matches EDARA's collect → liability, refund → liability down, deduction → income.

**Conclusion (RECOMMENDED).** A refundable foreign-currency deposit is a **monetary liability denominated in the deposit currency**. The functional-currency (ILS) amount is a *derived* measurement.
**Caveat (RECOMMENDED to document):** the classification changes if the deposit is contractually *applied to rent* (e.g. "last month's rent"): at that point it behaves like a prepayment (IAS 21 ¶16 "amounts prepaid for goods and services"; IFRIC 22 territory). EDARA's deduction path recognises income when the landlord withholds; a "convert deposit to rent" feature does not exist and would need its own accounting rule.
**Caveat (OPEN DECISION OD-A2):** PwC notes that a non-interest-bearing deposit is *in theory* discounted to present value under IFRS 9 with the difference treated as an additional lease payment. Small operators almost never do this and it is immaterial for short deposits; whether EDARA's customers need it is an auditor/materiality question. Recommended default: **no discounting**.
**Caveat (OPEN DECISION OD-A3):** principal vs. agent. If a deposit is held in a segregated trust/escrow account *for an owner*, it may not be the operator's own liability (Buildium distinguishes owner-held vs management-held deposits **[S]**). EDARA's documented architecture is the *Principal* model; this research assumes it.

## A3. Payment in a different currency

Scenario: contract deposit USD 1,000; tenant tenders ILS 3,700; rate 1 USD = 3.70 ILS.

**Evidence.**
- **[P] Odoo 19 multi-currency documentation** — "click on the Register Payment button ... select a currency in the Amount field"; Odoo "automatically records exchange differences entries on dedicated accounts, in a dedicated journal" and an exchange-difference entry is created only when the invoices and payments are **fully reconciled**. So paying in a currency other than the document currency is a normal, native capability for *invoices*. Rates come from the currency-rate table; the documentation says the latest rate on/before the transaction date applies and rates can be manual or fetched by an automatic provider (Odoo 19 "Foreign currencies" page). **[P]**
- **[P] IAS 21 ¶21–22** — a foreign-currency transaction is recorded at the **spot rate on the transaction date** (an average rate is allowed if it is a reasonable approximation).
- **[L] Verified in the dev DB (Phase 6/7 tests):** for rent invoices EDARA already relies on this — an ILS payment against a JOD invoice reduced the JOD residual correctly, and an overpayment became native customer credit.

**What the sources do NOT say.** None of the sources I could read describes how a property-management vendor handles a *deposit* tendered in another currency. Vendor evidence here is absent. Everything below is **[R]** built on the accounting standards and Odoo mechanics.

**Proposed rule (OPEN DECISION OD-A4 — needs owner approval):**

| Question | Proposal | Basis |
|---|---|---|
| Accept a currency other than the contract currency? | Policy switch, **off by default**. When off, EDARA rejects it (simplest, no FX exposure). When on, allowed only from a fixed list (ILS/USD/JOD). | [R]; native support exists [P] |
| Which rate? | The company's Odoo rate table (manual or provider-fed) **on the receipt date**; no ad-hoc per-payment rate typing. | IAS 21 ¶22 [P], Odoo currencies doc [P] |
| Who defines the rate? | The company accountant (rate table), not the tenant or the collecting user. If the contract carries a fixed conversion clause, that clause needs its own field (see OD-A1). | [R] |
| When is the rate locked? | At receipt/posting date of the payment; never re-derived later. | IAS 21 ¶22 [P] |
| Rounding | Convert in company currency with the company currency's rounding (as `_convert`/`round` already do); credit the deposit in *contract currency* rounded to that currency's precision. | [L] Phase 8 tests |
| Converted amount < deposit | Deposit stays partially collected (state `draft`/`held` with balance < amount); shortfall = still owed. | [L] `amount_held` logic; native partial-payment model [P] |
| Converted amount > deposit | **Must not silently over-hold**: cap at the outstanding deposit and route the excess to tenant credit / a refund. Today `action_collect` has no cap (Section 1). | [L] + [R] |
| Where is the difference booked | Shortfall/excess in *contract currency* terms; FX difference between the tendered ILS and the credited USD is an exchange difference (P&L) per IAS 21 ¶28. | [P] IAS 21 |

**Implementation risk (not evidence):** a native `account.payment` books its counterpart line in the *payment's* currency. To credit the deposit liability in **USD** while the bank receives **ILS** likely needs either a payment created in USD on an ILS journal or an explicit two-line entry. This must be prototyped before promising the feature (**OD-A5**).

## A4. Foreign-currency revaluation

**Evidence.**
- **[P] IAS 21 ¶23(a)** — at the end of each reporting period, foreign-currency *monetary items* are translated at the **closing rate**. **¶28** — exchange differences on settlement or on retranslating monetary items at rates different from those used previously are recognised in **profit or loss** in the period they arise. Non-monetary items carried at historical cost are *not* retranslated (¶23(b)).
- **[S] Deloitte DART / PwC ASC 830 excerpts** — US GAAP reaches the same result: foreign-currency liabilities are remeasured at each balance-sheet date and the transaction gain/loss goes to net income. (Excerpts only.)
- **[P] Odoo 19 documentation (foreign-currency bank page)** — Enterprise "Unrealized Currency Gains/Losses" report lists open foreign-currency balances; an **Adjustment Entry** books the gain/loss, and Odoo **auto-reverses** it on a chosen reversal date.

**Conclusion.**
- Treating the USD 1,000 deposit as USD-denominated and **remeasuring it at each reporting date** is the standard treatment (IAS 21, and ASC 830 by the excerpts). In the example, at 3.60 the liability is ILS 3,600; at 4.00 it is ILS 4,000; the ILS 400 increase is an **unrealised FX loss in P&L**, reversed or realised at settlement. **RECOMMENDED** as the accounting policy for EDARA's own books.
- Frequency: IAS 21 ties it to **each reporting date** — monthly if the company produces monthly accounts, otherwise at least at year-end. **OPEN DECISION OD-A6**: the reporting cadence is a company choice. Recommended: month-end if management accounts are monthly, always at year-end.
- Is there a reason deposits are *different*? Only the three caveats in A2 (prepayment nature, agent/escrow, discounting). None applies to an ordinary refundable deposit held as the operator's own liability.
- **Odoo coverage — verified in the installed source [L]** (`odoo/addons/account_reports/models/account_multicurrency_revaluation_report.py`): the report only picks up a balance-sheet line if **either** the *account itself* has a foreign currency set (`account.currency_id != company currency`) **or** the account type is receivable/payable and the line's currency is foreign. EDARA's deposit-liability account is `liability_current` with **no account currency** → **it is silently excluded** from Odoo's revaluation today. Making the account single-currency would break multi-currency deposits (a currency-locked account accepts only that currency).

## A5. Settlement (refund / deduction) and realised FX

- Collection, deduction and refund happen on different dates. Since Phase 8 each is booked at *its own date's* native rate, so `amount_currency` nets to zero but the company-currency balance keeps an exchange difference if the rate moved (documented in Phase 8).
- **[L] Verified:** `account.account` types `asset_receivable` and `liability_payable` are automatically **reconcilable** (`account_account.py::_compute_reconcile`); for other liability types the flag is not changed. **[P]** Odoo books exchange-difference entries automatically **on reconciliation**.
- **[R] Design implication (RECOMMENDED for a future spike, OD-A7):** post deposit liabilities to an account that is (a) **reconcilable**, so collection can be reconciled against refund/deduction and Odoo books the *realised* FX difference natively, and (b) of a type included in the revaluation report (**`liability_payable`** qualifies; `liability_current` does not). Trade-off: deposits then appear in the partner payable ledger/aging, which accountants may or may not want. The alternative — one liability account per currency with the account currency set — is revalued by Odoo but is not reconcilable, so realised FX would not be booked automatically. This is a chart-of-accounts decision for EDARA's accountant, not an engineering default.
- **Deduction/refund policy (RECOMMENDED):** always in the deposit's currency; a deduction cannot exceed the *balance in that currency*; the refund is made in the deposit currency unless OD-A4 (alternative currency) is enabled, in which case the tenant receives the converted amount at the *refund-date* rate and the difference is realised FX.

## A6. Foreign-currency deposit — recommended EDARA policy

| Item | Recommendation | Status | Evidence |
|---|---|---|---|
| Contract / deposit currency | The currency stated in the lease; liability held in that currency | RECOMMENDED | IAS 21 ¶16 [P]; PwC 4.10.1 [V] |
| Functional-currency value | Derived, remeasured at reporting dates | RECOMMENDED | IAS 21 ¶23, ¶28 [P] |
| Allowed payment currencies | Deposit currency only by default; others behind a policy switch | OPEN (OD-A4) | [R]; Odoo capability [P] |
| Rate source / timing | Odoo rate table, rate on receipt date, locked at posting | RECOMMENDED if alt-currency enabled | IAS 21 ¶22 [P] |
| Revaluation | Period-end remeasurement to P&L | RECOMMENDED; cadence OPEN (OD-A6) | IAS 21 ¶23/28 [P]; Odoo report [P] |
| Odoo mechanics | Move deposits to a reconcilable, revaluation-eligible account type | OPEN (OD-A7) | Odoo source [L] |
| Settlement (refund/deduction) | In deposit currency; realised FX to P&L via reconciliation | RECOMMENDED direction | IAS 21 ¶28 [P]; Odoo docs [P] |
| Over-collection | Cap at outstanding deposit; excess = tenant credit/refund | RECOMMENDED | [L]+[R] |
| Discounting to PV | Not applied | OPEN (OD-A2) | PwC [V] |

---

# PART B — LEASE EXTENSION VS. LEASE RENEWAL

## B1. Terminology (validated, with one caveat)

| Term | Meaning found in sources | Evidence |
|---|---|---|
| **Lease extension** | Keeps the *existing lease in force* and pushes out the end date, usually via a short **addendum**; original terms carry over, at most one minor agreed change. | Buildium blog **[V]**; DoorLoop **[V]** |
| **Lease renewal** | A **new lease agreement** for a new term where terms (rent, rules) can change; signed fresh. | Buildium blog **[V]**; DoorLoop **[V]** |
| **Lease amendment** | Any written change to an existing lease; an extension is a kind of amendment. | [R] (consistent with the extension description above) |
| **Lease modification** (accounting) | A change to a lease's scope/consideration/term. A **lessor accounts for a modification to an operating lease as a *new lease from the effective date* of the modification**, treating prepaid/accrued amounts of the original as part of the new lease's payments. Prior periods are not restated. | **[P] IFRS 16** (lessor, operating leases; the modification wording was read in the extracted text, but its paragraph number was not) |
| **Holdover** | A tenant remaining after the lease ended without signing a new lease. Acceptance of rent may create a periodic (month-to-month) tenancy or be treated as a renewal, depending on jurisdiction. | Cornell LII **[V]** |
| **Month-to-month / "at will"** | Buildium's *fixed-with-rollover* lease moves to an *at will* status at the end date instead of *expired*, and keeps posting monthly rent until manually ended. | Buildium help excerpt **[S]** |

**Caveat on "successor / predecessor".** None of the vendor pages I could read use these words — they say "renewed lease", "renewal offer", "renewal". They are a *technical* naming choice by EDARA. It is not wrong (EDARA's `predecessor_contract_id`/`successor_contract_id` links express a real relationship), but they are **not validated industry terminology**. **RECOMMENDED**: keep the technical field names; keep user-facing labels "Renewed From / Renewed Into" (already the case).

**Industry implementations differ on "same record or new record":**
- **Buildium** — a renewal produces a *renewed lease*; it "will automatically transfer over all tenant notes, files, bank transactions, and lease ledger balances and credits; as well as security deposits, other liabilities ..." to it **[V] (Buildium blog, "New feature announcement: lease renewals")**.
- **DoorLoop** — *extension* = edit the end date on the **same** lease (no new agreement); *renewal* = a wizard updating rent, deposit, and fixed/month-to-month type, then e-signature **[V]**.
- **Propertyware** — "Renew Lease" sets a new start date, end date and auto charges; the lease summary's dates/charges are updated and *existing auto charges are end-dated* while new ones are created **[S]** (page not readable).
- **Odoo Subscriptions (native precedent)** — "Renew" produces a *renewal quotation* that becomes a **separate sales order attached to the same subscription**, and a *Sales History* button lists each order with its own status; previous orders keep their status **[V/P]** (Odoo 19 "Renew subscriptions").

So a **linked successor record is a legitimate, documented pattern** (Buildium, Odoo Subscriptions) but not the only one. EDARA's current successor-record model is therefore acceptable; what matters is the *state and billing semantics* around it.

## B2. Extension vs. renewal — RECOMMENDED business rules for EDARA

**Extension = same contract, only the end date moves later.** RECOMMENDED.
- Evidence: Buildium **[V]** ("pushes out the end date"; use it when "only the end date needs to move" or one minor change), DoorLoop **[V]**, IFRS 16 lessor modification **[P]** (accounted prospectively from the effective date).
- Contract ID unchanged; contract remains `active`; no `renewed` state involved.

| Question | Recommended rule | Status |
|---|---|---|
| Can **rent** change in an extension? | **No.** Any rent change = renewal. | RECOMMENDED (Buildium "nothing else"; keeps history clean [R]) — the strictness (Buildium tolerates "one minor change") is **OPEN OD-B1** |
| Payment **frequency**? | No (changes the schedule anchor/periods). | RECOMMENDED [R] |
| **Deposit**? | No change (a deposit change = renewal). | RECOMMENDED [R] |
| **Currency / tenant / unit**? | Never. Different tenant or unit = a new lease. | RECOMMENDED [R] |
| Multiple extensions | Allowed; each is appended and audited (chatter + a small extension log). | RECOMMENDED [R] |
| Extension **after** expiry | Not on an `expired` contract. Handle as a *late renewal*/holdover decision. (Buildium lets you renew an expired lease up to 240 days back — excerpt **[S]**.) | RECOMMENDED direction; window OPEN **OD-B2** |
| Extension **on the expiry date** | Allowed while the contract is still `active` (the expiry cron only expires `end_date < today`), i.e. it must be done before the day ends / before the cron runs. Under the exclusive-end convention this means "on the last occupied day". | RECOMMENDED [L]+[R]; boundary convention OPEN **OD-B3** (Section B7) |

**Renewal = new contract (successor)** whenever any commercial term changes or a fresh agreement is signed. RECOMMENDED. Evidence: Buildium **[V]**, DoorLoop **[V]**, IFRS 16 **[P]** (new lease from effective date).

## B3. States: old contract, successor, and what "active" should mean

**Question 1 — old contract after a renewal is agreed but before its end date.** Should it stay ACTIVE or become RENEWED at once?

*Evidence.* The sources agree the old lease remains the operative lease until the new one begins: Buildium's renewal "automatically ... when a lease renews" moves data at renewal; Propertyware's blog **[V]** recommends starting renewal work 120 days before expiry (checkpoints at 90/60/30) while the current lease keeps running. IFRS 16 applies the modification "from the effective date" **[P]**, not from the signing date. Odoo Subscriptions keeps prior orders' own status **[V]**.

**Conclusion — RECOMMENDED:** the old contract **stays ACTIVE until its end date** (it *is* legally in force and still generating rent). "A renewal is pending" is **data** (a link to the successor + a flag/smart button), not a state. It becomes `renewed` **only at the moment the successor becomes active** (i.e. when the term it covered has been continued by the successor), and `expired` remains for a contract that ended with no successor. Note: the *name* `renewed` for the final state is an EDARA choice (vendors show "expired"/"at will"/"renewed lease"); **OPEN OD-B4**: keep `renewed` as a terminal state, or fold it into `expired` plus a successor link.

**Question 2 — successor between signing and start date.** Draft? Active? Something else?

*Evidence.* Vendors treat a renewal as an *offer* until accepted and a lease as in force from its start date; I found **no vendor page (readable) defining a "future/signed" status** — Buildium's statuses were not readable. So the state name is an EDARA design choice. Two workable models:

| | **Option A — explicit "scheduled" state (recommended lean)** | **Option B — current model: ACTIVE with future start** |
|---|---|---|
| Successor state after signing | new state `scheduled` (signed, not yet started) — *not* `draft` | `active` with `start_date > today` |
| "Active" means | in force **today** | signed/confirmed |
| Schedule / invoices | generated when it becomes active (or at scheduling but never invoiced before start) | generated at confirmation; invoiced by due date, so never before start |
| Activation | daily job flips `scheduled → active` when `start_date <= today` (same pattern as the existing reserved→rented cron) | none (state already active) |
| Unit protection from double-leasing | overlap check must include `scheduled` | already covered (active) |
| KPI/report pollution | none — "active contracts", rent roll, monthly-equivalent sums count only in-force leases | future successors inflate "active" counts and rent-roll sums; reports need a date filter |
| Change size | new state + job + overlap/KPI updates | smaller code change but leaves current semantic mismatch |

*Why not `draft`?* Your proposed rule ("successor becomes ACTIVE only when its start date is reached") is validated in spirit, but a plain `draft` means "still being prepared"; a signed successor should **protect the unit** (overlap check) and appear in renewal follow-up, which `draft` does not do today (the overlap check ignores non-active contracts). So the recommendation is *a distinct signed-but-not-started state*, activated automatically at its start date. **OPEN DECISION OD-B5: Option A vs Option B.** This deliberately differs from the literal "DRAFT" in the brief; the brief also allowed "or another future/approved state".

**Question 3 — when exactly does the successor become ACTIVE?** RECOMMENDED: on `start_date`, by the daily job, in the **same run** that ends the predecessor (Section B7), so there is never a moment with zero or two in-force contracts.

## B4. What happens to existing schedules

- **Extension.** Existing lines — paid, partially paid, invoiced, draft — are **unchanged**. New lines are added only for the extended period, continuing the same anchor day. RECOMMENDED. Evidence: IFRS 16 lessor treatment of an operating-lease modification (new lease from the effective date) is prospective **[P]** (paragraph number not verified in the extracted text); Buildium/DoorLoop describe an addendum that changes only the end date **[V]**; EDARA's own invariant that invoiced lines are the frozen basis (Phase 13/MAT) **[L]**.
- **Renewal.** The old contract's lines remain exactly as they are and are billed to the old contract until its `end_date`; the successor owns the schedule for its own term. RECOMMENDED. Evidence: Buildium keeps "lease ledger balances" and transfers them **[V]**; Odoo Subscriptions keeps prior orders **[V]**; IFRS 16 prospective **[P]**.
- **Overlapping renewal** (successor starts before the old end): uninvoiced old lines whose *period starts on/after* the successor's start are dropped; a period that *straddles* the successor start is an edge case — **OPEN OD-B6** (truncate vs bill old to period end vs require the successor to start on a period boundary). Phase 7 already implements the "drop from successor start" part.
- **Extension edge:** if the old last period was **prorated** (ended mid-period) and *uninvoiced*, an extension should recompute it as a full period; if it was already *invoiced* as prorated, the extension starts a new period at the old end. This must not re-create periods already covered by invoiced lines — the current generator would (conflict 5, Section 12). RECOMMENDED design constraint.

## B5. Future invoices when a renewal is created

Assume old contract has October/November/December 2026 invoices and a renewal is created.

- **RECOMMENDED: existing invoices — draft or posted or paid — are left untouched; no cancellation, regeneration or crediting merely because a renewal exists.**
- Evidence: **[P] IFRS 16** — the modification is accounted "from the effective date", prior periods are not restated; **[V] Buildium** — renewal carries forward ledger balances/credits rather than voiding them; **[L] Odoo** — a posted `account.move` cannot be edited or deleted, only reversed by a credit note (native accounting; also EDARA's project rule "accounting history is never rewritten").
- Old uninvoiced future lines of the *old* contract: **still valid and still billable to the old contract until its end date** (because the tenant remains in occupation). They are neither cancelled nor transferred. RECOMMENDED. (This is what Phase 7 enforces for `renewed` contracts; under Option A/B3 the old contract is simply still `active`.)
- Credit notes only when the *commercial* outcome changes (e.g. a negotiated rent reduction *for an already-invoiced period*), never as a lifecycle side-effect. RECOMMENDED.

## B6. Successor-contract invoicing

- **What "the successor generates invoices" means:** the successor's own schedule lines (periods inside its own term) are the *only* source of its invoices; each invoice links to one schedule line and to the successor contract (`edara_contract_id`). It never invoices any period belonging to the predecessor's term. RECOMMENDED. **[L]** EDARA already has the structural pieces: schedule line → invoice 1:1, `edara_contract_id` on the move.
- **When are successor schedules created?** RECOMMENDED: at activation (Option A) — never earlier. Under Option B they exist from confirmation but are not invoiced before `due_date`, which is ≥ `start_date`.
- **Invoices before the successor is active?** No. RECOMMENDED. Evidence for the *principle*: Odoo Subscriptions invoices on a tracked **next invoice date** **[V]**; EDARA's cron invoices on `due_date`.
- **Different rent / frequency:** the successor schedule is generated from its *own* rent/frequency/anchor; nothing of the predecessor's schedule is reinterpreted. RECOMMENDED [R].

## B7. Boundaries: renewal before expiry, and the same-day transition

- **Renewal prepared months before expiry — RECOMMENDED.** Propertyware's blog **[V]** recommends starting the process 120 days before expiry with checkpoints at 90/60/30, and the old lease remains operative (an AppFolio 90/60/30 timeline in one search excerpt came from a third-party site and is **not** relied on), the new one takes effect at the old end. EDARA already has 30/7-day expiry reminders **[L]**.
- **Same-day boundary — RECOMMENDED design:** adopt one convention across the whole module: **`end_date` is exclusive** (already true for schedule generation and overlap). Therefore the successor starts **on** the predecessor's `end_date`, not the day after (the wizard's `+1 day` default creates a one-day gap — conflict 3). Occupancy must also treat `end_date` as exclusive. **OPEN OD-B3**: confirm the legal contract convention (does "31/12/2026" mean *last occupied day* or *exclusive end*?). Customers' printed contracts usually say "ending 31/12/2026", i.e. **inclusive** — in that case the stored `end_date` should be entered as 01/01/2027 or the whole module switched to inclusive semantics. This must be decided before implementation because it changes every boundary rule.
- **Transition job — RECOMMENDED order (single daily run, single transaction):** (1) activate `scheduled` successors with `start_date <= today`; (2) end predecessors whose `end_date <= today` (exclusive) — set `renewed` if a successor is active, else `expired`; (3) recompute unit occupancy. This makes it impossible to observe zero or two in-force contracts on the boundary date.
- **Preventing two active contracts on one unit:** keep the overlap constraint, extend it to include `scheduled` (Option A), and use the exclusive-end comparison. [L] EDARA's current constraint + tests already do exclusive comparison for `active`.

## B8. Unit occupancy during renewal

- **RECOMMENDED: the unit stays `rented` continuously across a renewal; it never becomes `available` or `reserved` merely because a renewal was agreed.** Reasoning: the tenant is physically in occupation until the old end date and continues under the successor; Buildium/DoorLoop keep a single continuous tenancy in their software (data carried to the renewed lease) **[V]**. **Conflict:** current behavior sets `reserved` (Section 1.1 #2), because the old contract left `active` early.
- Renewal cancelled before it starts: the successor is cancelled (Option A: `scheduled → cancelled`; unit unaffected); the old contract continues and expires normally; the unit becomes `available` at the old end.
- Successor signed but old contract has ended and the successor has not started (a gap by mistake or a deliberate later start): the existing `reserved` semantics fit (BD-001) — unit is not occupied but committed. RECOMMENDED to keep.
- Successor never becomes active (e.g. tenant never moves in / is never activated): raise a reminder when `scheduled` and `start_date` has passed by N days; do not auto-cancel. RECOMMENDED [R]; N is **OPEN OD-B7**.

## B9. Double-invoicing prevention

**Risk:** old contract December 2026 line + successor December 2026 line both invoiced.
**Evidence.** Odoo Subscriptions prevents duplicates by tracking a *next invoice date* per subscription **[V]**. Buildium/Propertyware post recurring charges from a single charge definition per lease ("auto charges"; on renewal existing auto charges are end-dated) **[S]**. No vendor page I could read documents cross-lease overlap detection.
**RECOMMENDED principle (EDARA-specific, [R]):** the **schedule line period is the source of truth**, protected at three levels:
1. *Invoice ↔ line* — already enforced: `unique(invoice_id)`.
2. *Line ↔ period* — a new invariant: for one **unit**, non-cancelled schedule lines must not overlap in `[period_start, period_end)` (Python constraint on create/write; the successor generator trims or refuses).
3. *Invoice ↔ contract* — keep `edara_contract_id` on the invoice for audit and for report filters.
The contract state alone must **not** be the duplicate guard (a state flip is exactly how the current gap appeared).

## B10. Edge-case matrix

| # | Case | RECOMMENDED behavior | Evidence / status |
|---|---|---|---|
| 1 | Extension before expiry | Move `end_date`; append lines; keep contract ACTIVE | Buildium/DoorLoop [V]; IFRS 16 [P] |
| 2 | Extension on expiry date | Allowed if still `active` (before the transition job) | [L]+[R]; OD-B3 |
| 3 | Multiple extensions | Allowed; each appends lines and is logged | [R] |
| 4 | Renewal before expiry | Create successor (`scheduled`); old stays ACTIVE; no early state flip | Propertyware timeline [V]; [R] |
| 5 | Renewal on expiry date | Successor starts on the old `end_date` (exclusive); handled by one transition job | [R]; OD-B3 |
| 6 | Renewal after expiry | Allowed as *late renewal* within a configurable window; unit `available` in the gap unless holdover | Buildium 240 days [S]; OD-B2 |
| 7 | Same-day predecessor/successor | Boundary is exclusive; transition job order (B7) | [R] |
| 8 | Existing future invoices | Untouched (draft/posted/paid) | IFRS 16 [P]; Odoo immutability [L] |
| 9 | Existing paid future invoices | Untouched; a paid invoice for a period beyond an early-terminated lease is a credit/refund question, not a renewal one | [R] |
| 10 | Different rent | Renewal only; successor schedule uses new rent; old lines unchanged | Buildium/DoorLoop [V] |
| 11 | Different frequency | Renewal only; new anchor from successor start | [R] |
| 12 | Different currency | Renewal only; deposit/currency transfer needs an explicit rule (OD-B8) | [R] |
| 13 | Different deposit | Renewal: top-up or refund the difference against the carried-over deposit (DoorLoop updates deposit in the wizard [V]; Buildium transfers the deposit [V]) | OD-B8 |
| 14 | Partial periods | Prorated final line on the 30-day reference (existing); an extension must not double-count | [L] |
| 15 | Leap years / day 28–31 | Anchor computed fresh from `start_date` each period (existing behavior, tested in Phase 8/Enterprise audit) | [L] |
| 16 | Renewal cancelled | Successor cancelled; old continues | [R] |
| 17 | Failed renewal | Old expires at end; unit `available`; successor never activated | [R] |
| 18 | Successor never becomes active | Reminder (OD-B7); never auto-activate/cancel | [R] |
| 19 | Old terminated before successor starts | Terminate = ends the tenancy; a `scheduled` successor should be cancelled or explicitly re-confirmed by a user (do not auto-activate for a tenant who left) | [R]; **OD-B9** |
| 20 | Unit vacant between contracts | `available`, or `reserved` while a signed successor exists | BD-001 [L] |
| 21 | Same tenant | Deposit and ledger carry over (Buildium transfers deposits [V]) | OD-B8 |
| 22 | Different tenant, same unit | Not a renewal; a new lease; old deposit settled first | [R] |
| 23 | Same unit, overlapping contracts | Blocked by the overlap invariant (contract level + line level) | [L]+[R] |
| 24 | Holdover after expiry | Explicit policy: either (a) no tenancy → `expired`, manual decision, or (b) auto month-to-month "at will" contract that keeps invoicing (Buildium rollover **[S]**). Jurisdiction-dependent (Cornell **[V]**: accepting rent may create a periodic tenancy). | **OD-B10** — needs legal input |
| 25 | Invoiced partial final period then extension | New period starts at old end; do not regenerate invoiced periods | [R]; conflict 5 |

## B11. Deposit through a renewal (surfaced by the research)

Buildium transfers "security deposits, other liabilities" to the renewed lease **[V]**; DoorLoop's renewal wizard lets the deposit be updated **[V]**. In EDARA the deposit is one-per-contract and the successor gets a separate, uncollected deposit, while the old deposit stays held against a finished contract — the tenant appears to owe a second deposit. **OD-B8 (OPEN):** carry the deposit across the chain (one deposit record spanning predecessor→successor) vs. settle-and-recollect; if the amount changes, top-up or partial refund. Recommended lean: **carry over**, with the difference collected/refunded in the deposit currency.

---

# 12. Full list of conflicts between current EDARA and the recommended rules

| # | Current behavior (verified) | Recommended | Severity |
|---|---|---|---|
| 1 | `action_renew` sets old contract `renewed` at click time | Old stays `active` until end; `renewed` only when successor becomes active | Medium |
| 2 | Successor is `active` immediately with future start | `scheduled` state activated at start (or keep + fix reports) | Medium (OD-B5) |
| 3 | Unit shows `reserved` while old term still running | Stays `rented` throughout | Medium (visible in live data) |
| 4 | Wizard default successor start = end + 1 day; occupancy inclusive end vs exclusive elsewhere | One exclusive convention; successor starts on old `end_date` | Medium (OD-B3) |
| 5 | No extension action; editing `end_date` on active contract does not extend billing | Explicit Extend action (end date only) that appends lines; lock `end_date` edits otherwise | **High** (silent revenue leak) |
| 6 | `rent_amount`/`billing_frequency` editable on active contract with no effect on schedule | Lock after activation; changes go through renewal | Medium |
| 7 | `_generate_schedule_lines` regenerates all periods, including ones covered by invoiced lines | Regenerate only uncovered periods | High (if reused for extension) |
| 8 | Successor gets separate deposit; old deposit orphaned | Deposit carried across the chain | Medium (OD-B8) |
| 9 | `action_collect` has no cap vs `deposit.amount` | Cap; excess → credit/refund | Medium |
| 10 | Deposit liability account type excluded from Odoo revaluation; not reconcilable | Reconcilable, revaluation-eligible account type (OD-A7) | Medium (accounting policy) |
| 11 | Collect/deduct/refund booked at each day's rate; realised FX not booked | Reconcile so Odoo books realised FX | Medium |
| 12 | Overlap constraint ignores non-active contracts | Include `scheduled`; add line-level period non-overlap | Medium |
| 13 | Deposits accepted only in deposit currency | Fine as default; alternative currency is an OPEN policy switch | Info |
| 14 | Phase 7 special-case: `renewed` contracts are still invoiced | Becomes redundant once #1 is fixed; harmless to keep | Info |

---

# 13. Accounting rules (dedicated section)

All **RECOMMENDED** unless marked; source tags as above.

1. **Contract currency = the currency of the obligation.** Rent and deposit are denominated in the lease currency; the company-currency amount is derived. [P] IAS 21 ¶16, ¶21–22.
2. **Posted accounting history is never rewritten** because of a lifecycle event (extension, renewal, termination). Corrections use credit notes/adjusting entries only. [P] IFRS 16 (prospective); [L] Odoo posted-entry immutability; EDARA rule.
3. **Rent invoices**: currency = contract currency; rate date = invoice date (EDARA uses the due date) — verified in Phase 8 tests [L].
4. **Payments in another currency**: native Odoo payment registration with the rate table; exchange differences booked on reconciliation; underpayment stays receivable; overpayment becomes credit. [P] Odoo docs; [L] verified live.
5. **Deposit**: monetary liability in deposit currency (A2); remeasured at reporting dates (A4); realised FX at settlement (A5); refund and deduction in deposit currency; deduction = income recognition at the deduction date. [P]/[S]/[R].
6. **Credit notes/refunds**: native only; never triggered automatically by a renewal.
7. **Successor invoices**: only for periods inside the successor's own term, linked to its own schedule lines. [R]
8. **Double-invoicing**: prevented by the unit-level schedule-period invariant + `unique(invoice_id)`; not by contract state. [R]
9. **FX revaluation**: at each reporting date via Odoo Enterprise's Unrealized Currency Gains/Losses report with auto-reversal; requires the deposit account to be revaluation-eligible (A4). [P]+[L]
10. **Lease modification accounting** (extension/renewal): prospective from the effective date; prepaid/accrued amounts of the old lease carry into the new one. [P] IFRS 16 (lessor, operating). Applicability to EDARA's customers (local GAAP) is **not verified**.

---

# 14. Final decision matrix

| Topic | Industry / standard finding | EDARA recommendation | Evidence | Status |
|---|---|---|---|---|
| Lease extension | Same lease, end date pushed, via addendum; only minor changes | Explicit **Extend** action; end date only; same contract ID; stays ACTIVE | Buildium [V], DoorLoop [V], IFRS 16 [P] | RECOMMENDED |
| Lease renewal | New lease agreement, terms may change; vendors carry deposit/ledger forward | New (successor) contract for any commercial change; deposit carried over | Buildium [V], DoorLoop [V] | RECOMMENDED; deposit rule OD-B8 |
| Extension: what may change | Usually end date; "one minor change" tolerated | Only end date; anything else = renewal | Buildium [V] | RECOMMENDED; strictness OD-B1 |
| Old contract state | Old lease remains operative until the new one takes effect | Stay ACTIVE to its end; `renewed` only when successor starts | IFRS 16 effective-date [P]; Propertyware/Buildium timelines [V] | RECOMMENDED; naming OD-B4 |
| Successor activation | Lease effective from its start date; renewal starts as an offer | Signed successor in a **scheduled** state; auto-activate on start date | Buildium/Propertyware [V]; [R] | OPEN (Option A vs B, OD-B5) |
| Existing schedules | Prior ledger/orders retained; new terms prospective | Unchanged; append (extension) or new schedule (successor) | IFRS 16 [P]; Buildium [V]; Odoo Subscriptions [V] | RECOMMENDED |
| Future invoices | Not voided by renewal; accounting not restated | Leave draft/posted/paid untouched; old uninvoiced lines billed to old contract to its end | IFRS 16 [P]; Odoo immutability [L] | RECOMMENDED |
| Unit occupancy | Continuous tenancy across renewal | Stays `rented` throughout renewal | Buildium data-carry-over [V]; [R] | RECOMMENDED |
| Same-day boundary | Not documented by readable vendor sources | One exclusive end-date convention; single transition job | [L]+[R] | OPEN (OD-B3 legal wording) |
| Double-invoicing | Odoo tracks next invoice date; vendors post from one charge definition | Unit-level schedule-period non-overlap + `unique(invoice_id)` | Odoo [V]; Buildium [S] | RECOMMENDED (design) |
| Holdover | Rent acceptance may create periodic tenancy; some systems roll to "at will" | Explicit holdover policy | Cornell [V]; Buildium [S] | OPEN (OD-B10, legal) |
| Foreign-currency deposit | Refundable deposit = monetary liability in contract currency | Hold in contract currency | IAS 21 ¶16 [P]; PwC [V] | RECOMMENDED |
| FX revaluation | Monetary items remeasured at closing rate, differences to P&L | Period-end remeasurement; Odoo Enterprise report | IAS 21 ¶23/28 [P]; Odoo [P]; Deloitte [S] | RECOMMENDED; cadence OD-A6 |
| Odoo revaluation eligibility | Report includes only foreign-currency-account or payable/receivable lines | Use reconcilable, eligible account type for deposits | Odoo source [L] | OPEN (OD-A7) |
| Alternative-currency payment | Native Odoo supports it with exchange differences; no vendor evidence for deposits | Off by default; policy switch; receipt-date rate from Odoo table | Odoo [P]; IAS 21 ¶22 [P] | OPEN (OD-A4/A5) |
| Over/under-collection of deposit | Native partial/credit model for invoices | Cap collection; excess → credit/refund | [L]+[R] | RECOMMENDED |

---

# 15. OPEN DECISIONS — consolidated

| ID | Decision needed | Suggested owner |
|---|---|---|
| OD-A1 | What do customers' contracts actually say about deposit/rent currency and conversion? | Business/legal |
| OD-A2 | Discount non-interest deposits to PV? (lean: no) | Auditor |
| OD-A3 | Are deposits ever held as agent/escrow rather than the operator's own liability? | Business/auditor |
| OD-A4 | Accept payment in a currency different from the contract's? Which currencies and rate source? | Owner + accountant |
| OD-A5 | Technical spike: can a deposit be credited in USD while cash arrives in ILS via native payments? | Engineering |
| OD-A6 | Revaluation cadence (month-end vs year-end) | Accountant |
| OD-A7 | Deposit liability account type/structure (reconcilable payable-type vs per-currency accounts) | Accountant |
| OD-B1 | Strictness of "extension changes only the end date" | Owner |
| OD-B2 | Late-renewal / late-extension window after expiry | Owner |
| OD-B3 | End-date convention (inclusive vs exclusive) as written in customers' contracts | Owner/legal |
| OD-B4 | Keep `renewed` as a terminal state or fold into `expired` + link | Owner |
| OD-B5 | Successor model: new `scheduled` state (Option A) vs keep ACTIVE-with-future-start (Option B) | Owner + engineering |
| OD-B6 | Renewal overlapping the old term mid-period: truncate vs bill old to period end vs require period boundary | Owner |
| OD-B7 | Reminder threshold for a scheduled successor that never started | Owner |
| OD-B8 | Deposit carry-over across renewal and treatment of a changed amount/currency | Owner + accountant |
| OD-B9 | Old contract terminated before successor starts: auto-cancel successor or require confirmation | Owner |
| OD-B10 | Holdover policy (jurisdiction-dependent) | Legal |

---

# 16. Implementation Impact — No Changes Made

Assessment only, to be planned **after** the decisions above are approved. Nothing below was changed.

| Area | Likely change |
|---|---|
| **Lease contract lifecycle** (`edara_lease_contract.py`, contract views) | Add Extend action; stop flipping the old contract to `renewed` at click time; possible new `scheduled` state; lock `end_date`/`rent_amount`/`billing_frequency` after activation; transition rules. |
| **Renewal / extension actions and wizard** | Wizard default start = predecessor end (not +1 day); extension wizard (end date only); deposit carry-over/top-up step; renewal-request approval flow adjusted to the new states. |
| **Payment schedule generation** | Make generation incremental (append for extension; never re-create periods covered by invoiced lines); successor schedule generated at activation. |
| **Invoice generation / cron** | Billing gate by contract in-force dates rather than state alone; keep `unique(invoice_id)`; add unit-level period non-overlap constraint. |
| **Unit occupancy** (`edara_unit.py`) | Derive occupancy from in-force contracts including a still-running old contract during renewal; exclusive end-date; include `scheduled` in overlap. |
| **Cron logic** | New/extended daily transition job (activate scheduled → end predecessors → recompute occupancy); reminder for stalled scheduled successors. |
| **Deposit accounting** (`edara_deposit.py`, liability account) | Cap collection; carry-over across the chain; possibly change the deposit liability account type; reconcile collection vs refund/deduction so realised FX is booked; optional alternative-currency collection behind a policy switch. |
| **Currency handling / settings** | Company setting(s) for allowed deposit payment currencies and revaluation policy; documentation for running Odoo's Unrealized Currency Gains/Losses report. |
| **Reports / dashboard** | Ensure "active contracts", rent roll and monthly-equivalent revenue count only in-force leases (especially under Option B). |
| **Tests** | New tests for extension, early renewal, same-day boundary, deposit carry-over, cap on collection, revaluation eligibility, double-invoice invariant; update tests that assert `renewed` at click time (e.g. `test_renew_creates_active_successor_and_marks_predecessor_renewed`) and the Phase 7 early-renewal tests. |
| **Security** | New actions need `check_access('write')` + scoped `sudo()` following the Phase 7 guard pattern; `state` transitions stay inside guarded methods; new fields/states covered by `edara.system.field.guard`. |
| **Documentation** | Update EDARA state file, UI field inventory, and this document's decisions. |

---

# 17. Sources

**Accounting standards / Odoo — read in full text [P]**
- IAS 21 (¶16, ¶21–23, ¶28) — https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-21-the-effects-of-changes-in-foreign-exchange-rates.pdf
- IFRIC 22 (scope) — https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifric-22-foreign-currency-transactions-and-advance-consideration.pdf
- IFRS 16 (lessor lease modifications for operating leases; paragraph numbers not confirmed) — https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifrs-16-leases.pdf
- Odoo 19 — Multi-currency system — https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html
- Odoo 19 — Manage a bank account in a foreign currency (unrealized gains/losses, adjustment entry, reversal) — https://www.odoo.com/documentation/19.0/applications/finance/accounting/bank/foreign_currency.html
- Odoo 19 — Foreign currencies (rate providers, rate by date) — https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/prices/currencies.html
- Odoo 19 — Renew subscriptions — https://www.odoo.com/documentation/19.0/applications/sales/subscriptions/renewals.html

**Professional/vendor pages actually read [V]**
- PwC Viewpoint, IND FAQ 4.10.1 "How should an entity account for a refundable tenant deposit?" — https://viewpoint.pwc.com/dt/gx/en/pwc/industry/industry_INT/industry_INT/real_estate__1_INT/Applying-IFRS-for-the-real-est/Rental-income-accounting-by-lessors/frequently-asked-questions/ind-faq-4-10-1-how-should-an-entity.html
- Buildium blog — Lease extension agreement — https://www.buildium.com/blog/lease-extension-agreement/
- Buildium blog — New feature announcement: lease renewals — https://www.buildium.com/blog/new-feature-announcement-lease-renewals/
- DoorLoop — Lease extension vs renewal — https://www.doorloop.com/blog/lease-extension
- Propertyware blog — Lease renewal process (120-day cycle) — https://www.propertyware.com/blog/lease-renewal-process-pro-tips/
- Cornell LII — Holdover tenant — https://www.law.cornell.edu/wex/holdover_tenant

**Search-result excerpts only — weak [S]**
- Buildium Help Center: "How to renew a lease", "Lease Renewals Process", security-deposit refund/withhold articles — https://help.buildium.com/hc/s/article/How-to-renew-a-lease , https://help.buildium.com/hc/s/article/How-to-withhold-or-refund-a-security-deposits-held-by-a-rental-owner
- Propertyware support: Renew Lease — https://support.propertyware.com/s/article/Renew-Lease
- AppFolio feature/blog pages — https://www.appfolio.com/blog/lease-renewal-strategies
- Deloitte DART ASC 830-10 §4.3 — https://dart.deloitte.com/USDART/home/codification/broad-transactions/asc830-10/roadmap-foreign-currency-transactions-translations/chapter-4-foreign-currency-transactions/4-3-subsequent-measurement-foreign-currency
- JustLanded (Israel rentals, secondary) — https://www.justlanded.com/english/Israel/Israel-Guide/Housing-Rentals/Rentals

**Local source inspected [L]**
- Installed Odoo 19 Enterprise: `odoo/addons/account_reports/models/account_multicurrency_revaluation_report.py`, `odoo/addons/account/models/account_account.py` (`_compute_reconcile`), `account_move_line.py` (`_compute_balance`).
- EDARA files listed in Section 1.
