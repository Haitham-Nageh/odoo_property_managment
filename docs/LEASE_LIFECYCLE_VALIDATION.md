# Phase 9.2 — Lease Lifecycle & Accounting Validation

**Validation spike. No application code, view, security file, manifest, schema, test, configuration or real development record was changed.**
Date: 2026-09-25. Baseline: `property_managment` 19.0.1.0.0 at git HEAD `07cd5a1`, Odoo 19 Enterprise.
Companion documents (not overwritten): `docs/LEASE_LIFECYCLE_RESEARCH.md` (Phase 9 evidence), `docs/LEASE_LIFECYCLE_DECISIONS.md` (Phase 9.1 decisions).

---

## Reading guide: the four evidence categories

Every technical conclusion below is split into four labelled parts, which are never merged:

| Label | Meaning |
|---|---|
| **Source Evidence** | What Odoo source code or documentation says (file and line references), or what the existing EDARA source says. |
| **Observed Test Result** | What a controlled run in the throwaway database actually produced. |
| **EDARA Interpretation** | What the observation means for EDARA. |
| **Future Implementation Principle** | What Phase 10 must implement, or must not do. |

A result marked **NOT EXECUTED** was read from source but not run in this spike; it is never presented as observed.

---

## Executive Summary

The question was: *can the Phase 9.1 accounting and lifecycle rules be implemented safely with native Odoo accounting?* Answer: **yes for the rules that Phase 10 will implement; three items still need an accountant and two need a lawyer.**

1. **A deposit held in a foreign currency is represented correctly by native Odoo, and the current deposit account setup is the wrong shape for it.**
   On every account type tested, a USD deposit nets to USD 0 while the ILS balance keeps a residual (ILS +600 in the main cycle). That residual is the realised FX result. **Only a reconcilable account lets Odoo book it** (native exchange-difference entry, ILS 200 + 400 = 600 loss, liability back to 0/0). A non-reconcilable account cannot reconcile at all, so the residual stays and, on a full deduction, deduction income is overstated by the same amount (ILS 4,000 income recognised against ILS 3,000 received). This is what the current `liability_current`, non-reconcilable configuration does.
2. **Revaluation eligibility and reconcilability are independent.** The real Enterprise report includes a deposit account only if it has a fixed foreign currency or is a payable/receivable type. Verified by running the report: fixed-USD account, both payable accounts included; the two `liability_current` accounts without a fixed currency excluded, even when reconcilable. A fixed-currency account that is **not** reconcilable is included but keeps a permanent residual that the report re-proposes every period.
3. **OD-A5 is answered.** Odoo can hold a USD deposit while ILS cash arrives (a native USD payment on the ILS journal reconciles exactly against an ILS bank line). Odoo does **not** compute or enforce the conversion; EDARA must compute the USD credit at a defined rate. Recording the ILS amount directly on the liability (Model 2a) produces a mixed-currency liability that does not represent the USD obligation, and is rejected. The bank-side write-off for a rate mismatch was **not** exercised (the Enterprise bank-reconciliation widget is not installed).
4. **OD-B3 is validated on the real generator.** Feeding the boundary (`end_date + 1 day`) reproduces the inclusive business day count in 14 of 14 cases (365, 28, 29, 366, 55, 135, 546, 1 day…). Feeding the last day, as the business naturally enters it, is short by exactly one day in 13 cases, mis-bills whole-period contracts, and refuses the fourteenth, a single-day lease.
5. **The extension defect is confirmed quantitatively.** After the naive path (edit `end_date`, regenerate, run invoicing) all nine already-billed periods were invoiced twice: 18 invoices, ILS 18,000 against a correct 9,000. No constraint prevents two lines for the same period. A coverage-based prototype (kept only in the spike script) passed every invariant in 7 of 7 scenarios.
6. **The successor state model is internally consistent.** A paper prototype of `scheduled` + one ordered daily job gave the correct unit status and state on every date in five scenarios. On the real code, a *draft* successor does not protect the unit (a rival lease was accepted) and an *active-with-future-start* successor does; the current code also flips the old contract to `renewed` at click time and shows the unit `reserved` (observed).
7. **Deposit carry-over needs no journal entry.** A renewal creates zero accounting moves; no payment or journal item carries a contract reference (only a text memo). Amount changes map to the existing native collect/refund; a currency change forces a settlement with FX consequences.
8. **Two new findings reopen small items.** (a) The 30-day proration reference over-bills when a 31-day month is split (19 + 12 days = ILS 1,033.33) and on long partial periods (181 days = 502.76 against 500.00). (b) A late successor dated in the past back-bills at once, with the invoice dated on the due date.

---

## Test Environment

| Item | Value |
|---|---|
| Database | `edara_spike92`, created new for this phase, **dropped afterwards** (verified: only `odoo19_enterprise_dev` remains; filestore removed) |
| Real dev database | `odoo19_enterprise_dev` was never opened by any spike script. Verified afterwards with a read-only session: latest `write_date` on `account_move`, `account_payment`, `edara_lease_contract`, `edara_deposit`, `edara_payment_schedule_line`, `res_partner` is 2026-09-24 14:14 (before this spike began); 12 contracts, 0 spike partners, 0 spike units |
| Modules installed | `account`, `account_reports` (Enterprise revaluation report), `property_managment`. **Not installed:** `account_accountant` (the bank-reconciliation widget) |
| Company | ILS company currency (switched from the default USD before any entry existed); generic chart of accounts (`generic_coa`); no Palestinian localisation |
| Rates (fixed, ILS per 1 unit) | USD: 2020-01-01 = 3.00, 2020-01-02 = 4.00, 2020-01-03 = 3.50, 2020-01-31 = 3.90, 2020-02-03 = 3.60, 2020-02-29 = 3.70. JOD: 4.20, 5.60, 5.00, 5.10 on the first four dates. No market rate was used |
| Accounts under test | L1 `liability_current`; L1r `liability_current` + reconcile; L2 `liability_current` fixed USD; L2r the same + reconcile; L3 `liability_payable`; L4 `liability_payable` fixed USD. **Odoo accepted every combination**, including payable with a fixed currency |
| Journals | ILS bank `BNK1`, USD bank `BUSD` (currency USD), sales, general, Exchange Difference |
| How dates were controlled | Native payments and entries were created with explicit dates. The real EDARA `action_deduct` was run under an in-process replacement of `fields.Date.context_today` (a Python monkeypatch inside the script, not a code change). Crons were driven at simulated dates the same way |
| How EDARA was exercised | The real, unmodified models and methods: `action_collect`, `action_deduct`, `action_renew`, `action_activate`, `_generate_schedule_lines`, `_process_due_invoices`, `_cron_expire_contracts`, `_cron_sync_reserved_occupancy`, `_cron_generate_due_invoices` |
| Prototypes (script-only) | Coverage-based extension generator; carry-over as a Python calculation; the proposed state machine as a pure-Python model. None writes to module code |

### Runs executed
`s1` setup; `s2/s2b` deposit cycle across 5 accounts + reconciliation; `s3/s4/s4b/s4c/s4d` real revaluation report and adjustment wizard (incl. reversal and a second period-end); `s5` OD-A5 Models 1, 3, 2a, 2b and the overpayment/cap check; `s6` deposit-invoice variant; `s7` real renewal + carry-over cases A–D; `s8a` schedule mathematics (14 cases, two forms each); `s8b` extension safety (7 scenarios, naive vs coverage-based) and double invoicing; `s9` critical renewal, schedule-timing gates and holdover scenarios A–E; `s10` OD-A7 matrix (full deduction, partial refund, JOD); `s11` payables presentation; `sm.py` state-machine model.

### Limits and honest notes about the runs
- **A first attempt at `s9` ran for about 25 minutes without output** because my helper called the *unscoped* invoice cron, which invoiced every due line left in the throwaway DB by earlier scenarios. I killed only that process, scoped the helper to each scenario's own contracts (same `_process_due_invoices` logic), and reran. The aborted run had already committed some records; they are irrelevant because the whole database was dropped.
- In `s4` the revaluation wizard was run once per account in a loop, so later loops included earlier accounts' open lines. The per-account conclusions were checked against the posted entries afterwards (`s4b`), not against the loop's printout, which was unreliable (it searched the adjustment entry by an ISO date, while Odoo formats the reference with a locale date).
- Two overdue/expiry reminder crons were **not executed** (they would have processed every leftover line); their selection rules were read from source instead and are labelled as such.
- **NOT EXECUTED anywhere:** the Enterprise bank-reconciliation widget and its write-off line; the tenant portal pages (source read only); multi-company; a wall-clock cron; the overlapping-renewal double-billing (source and the Phase 7 test only).

---

## OD-A5 — Alternative Currency Deposit Payment

### Scenario A — payment in the contractual currency (Model 1)

**Source Evidence.** `edara_deposit.py::_create_deposit_payment` creates a native `account.payment` with `currency_id = deposit.currency_id`; `account_payment.py` overrides only the destination account.
**Observed Test Result.** Real USD cash on a USD bank journal (`s5`):

| Step | Journal item | `currency_id` | `amount_currency` | Debit / Credit (ILS) |
|---|---|---|---|---|
| Collect USD 1,000 @3.00 (2020-01-01) | Outstanding receipts | USD | +1,000 | 3,000 / 0 |
| | Deposit liability | USD | −1,000 | 0 / 3,000 |
| Refund USD 1,000 @3.50 (2020-01-03) | Deposit liability | USD | +1,000 | 3,500 / 0 |
| | Outstanding payments | USD | −1,000 | 0 / 3,500 |

Liability before reconciliation: USD 0, ILS balance +500 (debit). Native full reconciliation created **one exchange-difference entry**: Dr 641000 Foreign Exchange Loss 500 / Cr liability 500 (journal `EXCH`, dated 2020-01-31). Liability afterwards: USD 0, ILS 0.
**EDARA Interpretation.** The contractual obligation (USD 1,000) is satisfied and the refund is exact in USD. The realised FX (loss 500 because the USD rose from 3.00 to 3.50) is recognised natively, on reconciliation only.
**Future Implementation Principle.** Contractual-currency payment needs no custom accounting. It is the Phase 10 default.

### Scenario B — money received in ILS for a USD deposit

Setup: tenant tenders ILS 3,700 on 2020-01-02 (1 USD = 4.00 ILS ⇒ USD 925); the contract requires USD 1,000.

| Model | What was done | Observed result |
|---|---|---|
| **Model 3 (native)** | A native `account.payment` of **USD 925** on the ILS journal, dated 2020-01-02 | Lines: outstanding receipts USD +925 / ILS 3,700; deposit liability USD −925 / ILS −3,700. **The liability is denominated in USD.** Payment currency USD, journal currency ILS (company). |
| Model 3, bank side | Native ILS bank statement line of ILS 3,700; retargeted the suspense line to the outstanding account and reconciled (the step the Enterprise widget performs) | Both lines reconcile completely (residual 0). **No exchange difference** because the company-currency amounts are equal. |
| Model 3, mismatch | Statement of ILS 3,650 instead of 3,700 | The statement line reconciles; the payment's outstanding line keeps **residual ILS 50 (USD 12.50)** and is **not** reconciled. Odoo does not book the 50 by itself. **NOT EXECUTED:** the write-off of that residual (needs the Enterprise widget). |
| Model 3, refund | USD 925 refund @3.50 (cash out ILS 3,237.50), then native reconciliation | One exchange entry: Dr liability 462.50 / Cr 441000 Foreign Exchange Gain 462.50. Liability USD 0 / ILS 0. |
| **Model 2a (naive)** | Payment recorded in **ILS 3,700** directly on the liability (currency = company currency), later a USD 925 refund | The liability account then carries **two currencies**: ILS −3,700 with no USD, and USD +925. `sum(amount_currency)` is −2,775 (meaningless). Reconciliation succeeded and booked one exchange entry, but the USD deposit balance never existed in the ledger. By source, the revaluation report would not pick up the ILS-denominated line (its condition requires the line currency to differ from the company currency); that was not run. |
| **Model 2b (explicit conversion)** | ILS payment parked on a reconcilable clearing account, then a **hand-built** entry re-denominating into USD 925 | Result is identical to Model 3 on the liability (USD −925 / ILS −3,700) and the clearing account reconciles to zero. It needs a clearing account and a custom journal entry. |
| Model 3b (deposit as an *invoice*, "recognised at 3.00, received at 4.00") | Customer invoice USD 1,000 dated 2020-01-01 crediting the deposit liability; payment USD 1,000 on 2020-01-02 @4.00 | Cash received ILS 4,000; liability ILS 3,000 / USD 1,000; native reconciliation booked **an FX gain of ILS 1,000** (Cr 441000). |

**Source Evidence.** Odoo 19 multi-currency documentation: a payment can be registered in a currency different from the document's; exchange differences are booked on reconciliation. `account_move_line.py:2673`: reconciliation requires `account.reconcile`.
In the bank-side test, lines in two currencies (USD 925 against ILS 3,700) reconciled on their company-currency amounts, since those were equal (observed).
**EDARA Interpretation.**
- Odoo represents "ILS cash, USD contractual liability" **only if the payment is created in USD**. It does not turn ILS into USD; EDARA must compute `credited USD = tendered ILS ÷ rate` at the receipt-date rate and create the USD payment. The result is exact in USD, and no FX arises at receipt because the credit is derived from the same rate.
- The **shortfall** is represented by EDARA's own deposit record (USD 925 held of USD 1,000, USD 75 still to collect). Odoo does not know the contract requirement.
- The **overpayment** is not prevented anywhere. Real `action_collect(1,100)` on a USD 1,000 requirement was **accepted**: `amount_held = 1,100`, `balance = 1,100`, state `held` (no cap; conflicts with the Phase 9.1 cap rule).
- Model 3b (deposit recognised before cash) creates a spurious realised gain of 1,000 that a later revaluation would offset with an unrealised loss of 1,000; the deposit is not income. EDARA's current rule, recognise only on cash receipt, avoids this.
**Future Implementation Principle.** (1) Deposit payments are in the contractual currency (Model 1). (2) Any future alternative-currency workflow must create the payment in the **contractual** currency at a rate held by the accountant, and store tendered amount, currency, rate and rate date; it must never book the tendered amount on the liability (Model 2a). (3) Cap collection at `amount − amount_held`. (4) Do not invoice a deposit before cash arrives (Model 3b).

### Decision matrix for the three business models

| | Technically possible | Accounting-safe | Auditable | Native Odoo | Custom logic required | Operational complexity | Verdict |
|---|---|---|---|---|---|---|---|
| **Model 1** contractual currency only | Yes (observed) | Yes | Yes | Yes | None (cap only) | Low | **Recommended** |
| **Model 2** explicit FX conversion by EDARA | Yes (2b observed; 2a observed and invalid) | 2b yes; 2a **no** | 2b yes | Partly (clearing account, hand-built entry) | Rate lookup, conversion entry, clearing account | High | Fallback only, and only in form 2b |
| **Model 3** native multi-currency (USD payment on ILS journal) | Yes (observed) | Yes for the liability; bank-side residual write-off **NOT EXECUTED** | Yes (needs tendered-amount fields) | Yes | Rate lookup and the USD amount computation; audit fields | Medium | Candidate for a later phase, **BLOCKED — ACCOUNTANT** |

---

## OD-A7 — Deposit Liability Account

### Reconciliation behavior by account type

**Source Evidence.** `account.account.reconcile` is `compute='_compute_reconcile', store=True, readonly=False` (`account_account.py:89`). `_compute_reconcile` (lines 665-673) sets it to `True` for `asset_receivable`/`liability_payable`, `False` for income/expense/equity/cash/credit card/off-balance, and **leaves it untouched for other asset/liability types**, so `liability_current` can be made reconcilable by hand. `_check_reconcile` (line 27-30) forbids turning it off for receivable/payable. `account_move_line.py:2673` rejects a reconciliation on an account that is not reconcilable.

**Observed Test Result.** Cycle: collect USD 1,000 @3.00, deduct USD 200 @4.00 (real `action_deduct`), refund USD 800 @3.50. The posted lines were **identical** on all five accounts (credit 3,000; debit 800; debit 2,800; USD 0; ILS residual +600).

| Account | Reconcile attempt | Result |
|---|---|---|
| L1 `liability_current` | `lines.reconcile()` | **UserError: "does not allow reconciliation"**. Residual ILS 600 remains on the account. |
| L2 `liability_current` fixed USD | same | **UserError**, same |
| L1r `liability_current` + reconcile | same | Full reconcile; two exchange entries (Dr 641000 / Cr liability): **200** (deduction) and **400** (refund), dated 2020-01-31; liability USD 0 / ILS 0 |
| L3 `liability_payable` | same | Same result as L1r |
| L4 `liability_payable` fixed USD | same | Same result as L1r |

Further runs (`s10`), each on L1, L1r and L3:

| Case | L1 (not reconcilable) | L1r and L3 (reconcilable) |
|---|---|---|
| **Full deduction** USD 1,000 @4.00 on a deposit collected @3.00 | Deduction income recognised **ILS 4,000**; liability keeps **ILS +1,000 debit** with USD 0; cannot be cleared | Reconcile books exchange loss 1,000 (Dr 641000, Cr liability); liability 0/0; net P&L effect 4,000 − 1,000 = **3,000 = the ILS received** |
| **Partial refund** USD 400 @3.50 (deposit still open) | Liability USD −600 / ILS −1,600; nothing to reconcile | Partial reconcile **books exchange loss ILS 200** on the matched USD 400 (`EXCH/2020/01/0010`); USD 600 stays open at its 3.00 cost (ILS 1,800) |
| **JOD** deposit 500 collect @4.20, refund @5.00 | Liability JOD 0 / **ILS +400** stuck | Reconcile books exchange loss **400**; 0/0 |

**EDARA Interpretation.** (a) The current configuration (`liability_current`, not reconcilable) cannot settle foreign-currency deposits cleanly: the ILS residual is permanent and, on a retained deposit, income is overstated. For an ILS deposit it changes nothing. (b) **Realised FX needs a reconcilable account; the account type is irrelevant to that.** (c) Odoo books realised FX on a **partial** reconciliation too, so EDARA does not have to wait for the deposit to close.
**Future Implementation Principle.** For every deposit whose currency differs from the company's, the configured deposit liability account **must be reconcilable**, and EDARA reconciles each refund or deduction against the open collection lines natively (partial reconciliation is supported). EDARA must never book its own exchange entry.

### Payables versus current liabilities: presentation

**Observed Test Result** (`s11`, tenant with a USD 1,000 deposit and a separate ILS 500 rent invoice):

| Deposit account | Partner "payable" total (`debit`) | Deposit offered as an outstanding credit on the rent invoice | Lines on payable-type accounts |
|---|---|---|---|
| L1 `liability_current` | 0.00 | none | 0 |
| L1r `liability_current` + reconcile | 0.00 | none | 0 |
| L3 `liability_payable` | **3,000.00** (ILS value of the deposit) | none | 1 |

**EDARA Interpretation.** A `liability_payable` deposit account puts the tenant's deposit into Odoo's partner payable balance and payables reports. A refundable deposit *is* an amount owed to the tenant, but whether a customer deposit belongs in payables is a **chart-of-accounts and presentation choice for the customer's accountant**, not a technical necessity. Technically it does not leak into rent collection: the deposit is never offered against a rent invoice on any type.
The Phase 9.1 conclusion "prefer `liability_payable`" rested on revaluation eligibility. That is not sufficient, and this phase does not adopt it on that basis alone. The verified technical requirements (reconcilable + revaluation-eligible) are met by **three** configurations: L3 (payable), L4 (payable, fixed USD), or L2r (`liability_current`, fixed USD, reconcile). L2r keeps deposits out of payables but needs one account per currency (a company-level mapping that does not exist).
**Future Implementation Principle.** Phase 10 encodes the technical requirement (reconcilable, plus revaluation-eligible when foreign-currency deposits are used) as a **setup check with a clear warning**, not a hard-coded account type. **BLOCKED — ACCOUNTANT** for the choice between payable and per-currency accounts.

---

## Foreign Currency Revaluation

### Why the current EDARA account is excluded

**Source Evidence.** `account_multicurrency_revaluation_report.py:300-316` includes an account-balance line only if the account type is not income/expense/off-balance **and** (`account.currency_id != company currency` **or** (`account_type IN ('asset_receivable','liability_payable')` **and** the line currency ≠ company currency)). EDARA's deposit account has no account currency and is of type `liability_current`, so neither branch holds.
The adjustment wizard (`wizard/multicurrency_revaluation.py`, `_get_move_vals`, `create_entries`) posts, per account and currency, company-currency-only lines (`amount_currency` = 0) against the same account and an expense or income provision account, then posts an automatic reversal on the chosen date.

### Which of the four accounts are eligible

**Observed Test Result.** The real report at 2020-01-31 (rate "1 ILS = 0.25641 USD" = 3.90 ILS per USD) listed lines for **L2, L3 and L4** and **no line for L1 or L1r**. The wizard then posted provisions for L2, L2r, L3 and L4 (ILS 900 each: (3.90 − 3.00) × USD 1,000 on a USD 1,000 deposit collected @3.00) and posted **nothing** for L1r. Each entry has an automatic reversal on 2020-02-01.

| Account | Type / setup | Included | Why (source path) |
|---|---|---|---|
| Account 1 (L1) | `liability_current`, no currency | **No** | neither branch of the condition |
| L1r | `liability_current`, no currency, reconcile | **No** | reconcile is not part of the condition |
| Account 2 (L2, L2r) | `liability_current`, fixed USD | **Yes** | `account.currency_id != company currency` |
| Account 3 (L3) | `liability_payable`, no currency | **Yes** | receivable/payable branch, line currency USD |
| Account 4 (L4) | `liability_payable`, fixed USD (Odoo permits it) | **Yes** | either branch |

Further observations:
- Provision and reversal lines on reconcilable accounts are **reconciled to each other automatically** (residual 0, reconciled). They carry **no partner**.
- The adjustment lines have `amount_currency = 0`, so the account's **USD balance is not disturbed**; only the ILS balance moves. The liability remains correctly denominated.
- **Non-reconcilable fixed-currency account (L2):** after two deposits were settled, the ILS residual of **1,200** stayed on the account and the report proposed a 1,200 adjustment at the next period end, again and again. The residual is never realised. **L2r (the same account, reconcilable), once its settled deposits were reconciled: GL 0.00 and no adjustment proposed.** L3 and L4 still showed 600 in that check because the earlier deposits on them (whose deduction entry my reconcile filter skipped) had been left unreconciled by the test script; the same lines reconciled successfully in `s2b`, which is the observed mechanism.
- Exchange-difference entries were dated **month end** (2020-01-31, 2020-02-29), not on the reconciled lines' dates (`_prepare_exchange_difference_move_vals` takes the date from `journal.accounting_date`, which moves to the period end when the sequence requires it). This matters for period reports.

**EDARA Interpretation.** Revaluation and realised FX are two separate native mechanisms; each needs its own precondition (eligibility; reconcilable). A deposit account must satisfy both for foreign-currency deposits. Enabling revaluation on the real EDARA account was **not** done.
**Future Implementation Principle.** See OD-A7. Revaluation cadence is an accountant procedure (native report, provision with auto-reversal). EDARA writes no revaluation code.

---

## OD-B8 — Deposit Carry-Over

**Source Evidence.** No field on `account.payment` or `account.move.line` references a lease contract (`s7`: empty lists). The only textual link is the payment memo. `edara.deposit.transaction.payment_id`/`move_id` is EDARA's audit index (`edara_deposit_transaction.py`).
**Observed Test Result** (real `action_collect`, real `action_renew`, tenant with USD 1,000 held):

| Check | Result |
|---|---|
| Old contract / successor / unit after `action_renew` | `renewed` / `active` / `reserved` |
| Successor deposit record | not created automatically; created lazily on the Deposit button: requirement USD 1,000, held 0, state `draft`, while the old deposit stays `held` USD 1,000 |
| Accounting moves created by the renewal | **0** |
| Liability before and after renewal | USD −1,000 / ILS −3,700, one line, unchanged |
| Tie-out with a pair transfer (Python calculation, no records written) | old 0 + new 1,000 = 1,000 = GL USD 1,000 |
| **Case A** 1,000 → 1,500 | Extra USD 500 collected natively; GL USD −1,500 |
| **Case B** 1,000 → 700 | USD 300 refunded natively; the record balances still tie to the GL (e.g. old 700 + new 500 = 1,200 = GL USD 1,200 in the sequential test) |
| **Case C** USD → JOD | A hand-built entry closing USD 1,000 (@3.50) and opening JOD 700 (@5.00) leaves the USD leg with ILS 3,000 booked against ILS 3,500 → native reconciliation books a **realised FX loss of 500**. Currency change is a settlement event, not a relabel. (Illustration of mechanics; **not** a proposed entry.) |
| **Case D** deduction above balance | `action_deduct(1600)` with balance 500 → `UserError: Cannot deduct more than the remaining deposit balance.` `action_renew` has **no deposit check** and succeeded with the old deposit held. |

**EDARA Interpretation.**
- The liability belongs to the tenant and the company, not to a contract. Changing which contract a deposit is *associated with* changes EDARA's index only; **no journal entry is needed** and none is created. The safety property is `Σ deposit-record balances (in deposit currency) = GL liability (amount_currency)` per tenant and account.
- Increases and decreases map to the existing native collect and refund. A currency change cannot be a carry-over: it converts a liability and realises FX.
- EDARA has **no "pending deduction"** concept: deductions are immediate and bounded by the balance. A claim larger than the deposit is a receivable (an ordinary invoice, `edara_invoice_type = 'ad_hoc'`), not a deposit deduction.
**Future Implementation Principle.** Carry-over by paired transfer transactions, no journal entry, only for same tenant, company and currency; the carried amount is the old **balance**; a control report checks the tie-out. **BLOCKED — ACCOUNTANT**: confirm that a no-entry transfer is acceptable and that the tie-out is the required control (technical feasibility is validated; the accounting sign-off is not).

---

## OD-B3 — Inclusive End Date

**Source Evidence.** `_generate_schedule_lines` stops at `period_start >= end_date` and ends the last period at `min(next_boundary, end_date)`; `_check_no_overlap` compares `start < other.end` and `other.start < end`; `_check_dates` rejects `end_date <= start_date`. The expiry cron (`end_date < today`), occupancy (`end_date >= today`) and reminders already treat `end_date` as inclusive.
**Observed Test Result** (real generator on draft contracts, rent 1,000; two forms per case — the last day as entered, and the boundary `E + 1`):

| Case | Occupied days (inclusive) | As entered (`E`) | Boundary (`E+1`) |
|---|---:|---|---|
| 01/01/2026–31/12/2026 monthly | 365 | 364 days; December flagged prorated (30/30 = 1,000); total 12,000 | **365**; 12 full periods; 12,000 |
| same, quarterly | 365 | 364; Q4 prorated; total **4,011.10** | **365**; 4,000.00 |
| same, yearly | 365 | 364; **1,011.07** | **365**; 1,000.00 |
| 01/02/2026–28/02/2026 (Feb) | 28 | 27 days; **900.00** | **28**; 1,000.00, not prorated |
| 01/02/2028–29/02/2028 (leap Feb) | 29 | 28 days; **933.33** | **29**; 1,000.00 |
| 01/01/2028–31/12/2028 yearly (leap year) | 366 | 365 days; **1,013.85** | **366**; 1,000.00 |
| Day-31 anchor 31/01/2026–30/01/2027 | 365 | 364; last period prorated | **365**; 12 full periods, boundaries recomputed from the start (28/02, 31/03, 30/04 …) |
| Day-30 anchor / Day-29 anchor (leap) / Day-28 anchor | 365 / 366 / 365 | one short each | exact: 365 / 366 / 365 |
| Partial month 15/01–10/03 (55 d) | 55 | 54 days; 1,766.67 | **55** days; 1,800.00 (second period 24 days = 800.00) |
| Partial quarter 01/01–15/05 (135 d) | 135 | 134; 1,488.88 | **135**; 1,500.00 |
| Partial year 01/01/2026–30/06/2027 (546 d) | 546 | 545; 1,499.98 | **546**; **1,502.76** (see proration note) |
| Single day 15/03/2026 | 1 | **REFUSED**: "The end date must be after the start date" | **1** day, prorated 33.33 |
| Renewal old 31/12/2026, successor 01/01/2027 (boundary form) | 365 + 365 = 730 | — | old last period ends 01/01/2027 = successor first start: **no gap, no overlap**; 730 = the 730 calendar days of 2026–2027 |

All six required examples (1 to 6) match in the boundary form; Example 5 (extension to 31/03/2027) is scenario S2 below, which adds exactly three monthly lines. The leap-day anchor (start 29/02/2028) was a Phase 9.1 case and was not re-run here.
**EDARA Interpretation.** `exclusive_boundary = end_date + 1 day` is confirmed as the internal representation: the `[start, boundary)` form reproduces the business day count everywhere, adjacent leases share a boundary, and the final business day is inside the contractual period. Feeding the last day to the current generator drops that day and, for whole-period contracts, converts the last period into an inexact prorated line. The figures 1,011.07 and 4,011.10 differ by cents from the 1,011.11 and 4,011.11 in the Phase 9.1 record: the real generator uses the *rounded* stored monthly-equivalent rent (83.33), which an unrounded simulation did not.
**Future Implementation Principle.** Store the business end date; derive `term_boundary = end_date + 1 day` in one place; the schedule generator, overlap check, occupancy and expiry use that helper; `_check_dates` becomes `end_date >= start_date`.

**New observation (reopens a small item, see OD-N1).** The 30-day reference month over-bills partial periods that contain 31-day months: 181 days on a yearly-frequency contract = **502.76** instead of 500.00; a 31-day month split into a 19-day and a 12-day piece = **1,033.33** (633.33 + 400.00) instead of 1,000.00 (scenario S5 below). This predates the convention decision and is not caused by it.

---

## OD-B5 — Successor State

**Source Evidence.** `action_renew` creates the successor, sets the old contract `renewed`, and calls `action_activate()` on the successor even for a future start. `_check_no_overlap` runs only for `active` contracts and compares only `active` contracts. `_process_due_invoices` skips a line unless `contract.state in ('active','renewed')`. Portal (`controllers/portal.py:180-186`): the dashboard's *current contract* is `state = 'active'`; the *next payment* is the earliest line in state draft/invoiced/overdue/partial for the tenant; the lease list shows the tenant's contracts in any state.
**Observed Test Result — real code, the critical renewal** (old 01/01/2026–31/12/2026, successor 01/01/2027–31/12/2027, signed 01/10/2026):

| Check | Observed |
|---|---|
| State after signing | old **`renewed`**, successor **`active`**; unit **`reserved`** (tenant is in occupation) |
| Existing invoices (9) after renewal | unchanged (same ids, names, dates, amounts) |
| Successor schedule at signing | 12 lines, due 2027-01-01 to 2027-12-01; **0 invoices** |
| Invoice cron run twice on 2026-10-01 | old contract 9 → 10 invoices (the October line, billed once); successor still 0 |
| Rival lease 2027-06-01→2027-08-31, successor `active` with future start | **blocked**: "already has an active lease … overlapping" |
| Same rival when the successor is only **draft** | **accepted and activated** (a draft successor does not protect the unit) |
| Cron at 2026-12-31 / 2027-01-01 | old stays `renewed`, successor `active`; unit `reserved` → **`rented`** on 2027-01-01 |

**Observed Test Result — the proposed model (paper prototype, `sm.py`: one new state, one ordered daily job, derived occupancy):**

| Scenario | Date | Old | Successor | Unit |
|---|---|---|---|---|
| Critical | 2026-09-25, 2026-10-01, 2026-12-31 | active | scheduled | **rented** |
| | 2027-01-01 (job runs) | renewed | active | rented |
| | 2028-01-01 | renewed | expired | available |
| Gap (successor 01/03/2027) | 2027-01-01, 2027-02-15 | renewed | scheduled | **reserved** |
| | 2027-03-01 | renewed | active | rented |
| Renewal cancelled 01/11/2026 | 2027-01-01 | expired | cancelled | available |
| Old terminated 15/11/2026 | 2026-11-15 | terminated | cancelled | available |
| No renewal | 2026-12-31 / 2027-01-01 | active → expired | — | rented → available |

Overlap check with `scheduled` counted as occupying: a rival 2027-06-01→2027-08-31 is detected (`['successor']`); the same rival is **not** detected if the successor is `draft`; a lease starting exactly on the boundary is allowed; a single-day lease on the successor's start day is detected.
**EDARA Interpretation.** The proposed model is internally consistent with the existing architecture. It needs no new derivation mechanism: occupancy is `rented` if an `active` contract covers today, `reserved` if a `scheduled` one exists, else `available` (the existing BD-001 logic with one added state). Because invoicing is gated by a **whitelist** of contract states, a new `scheduled` state is excluded from invoicing by default.
Two constraints the prototype does not enforce by itself:
1. **The overdue-reminder cron selects lines by line state only.** *Source:* `search([('state','=','overdue')])` with no contract filter. *Observed:* a non-active contract's 9 past-due lines matched that predicate (the cron itself was not run). A `scheduled` contract can never have a past-due line while the transition job runs, but the invariant is not enforced.
2. The expiry-reminder cron already filters `state = 'active'` (source), so scheduled contracts are not reminded.
**Future Implementation Principle.** `scheduled` state with overlap including `scheduled`; occupancy derivation above; daily ordered job (activate scheduled → close ended active → recompute units); add a contract-state filter to the overdue-reminder domain; keep the invoicing gate a whitelist.

---

## OD-B6 — Schedule Timing

**Source Evidence.** `action_activate` generates the schedule immediately after setting the state; `_generate_schedule_lines` does not read the contract state; `_process_due_invoices` is the only place that reads the state; `unlink()` on a schedule line blocks deletion of an invoiced line.
**Observed Test Result.**

| Question | Result |
|---|---|
| Can schedule lines exist while the contract is not active? | Yes: a draft contract accepted `_generate_schedule_lines()` and held 12 lines, 9 already past due |
| Can invoices be generated prematurely? | No: `_process_due_invoices` on those 9 past-due lines returned **(created 0, skipped 9, errors 0)** |
| Does the invoice cron consider contract state? | Yes, in `_process_due_invoices`, not in the cron's SQL selection (which selects every uninvoiced due line) |
| Does schedule generation depend on state? | No |
| Successor lines on the current code | 12 lines existed from signing; **0 invoices** created for them before their due dates |
| Can a future contract's uninvoiced lines be removed on cancellation? | Yes: 12 uninvoiced lines removed, remaining 0 |
| Can an invoiced line be removed? | No: `UserError: An invoiced payment schedule line cannot be deleted…` |
| Reminders before activation | Expiry reminders: never (state filter). Overdue reminders: keyed to line state (see OD-B5, constraint 1) |
| Portal display of future schedules | Source: the next-payment query is by line state and tenant, independent of the contract state, so future lines display; **NOT EXECUTED** in a browser |

**EDARA Interpretation.** Schedule creation, invoice generation and contract activation are already three separate events in the code, protected by two different gates (the state whitelist, and the line's `due_date`). Generating a successor's schedule at **confirmation** is safe.
**Future Implementation Principle.** Keep the three events separate. Confirmation → schedule exists. Due date + `active` → invoice. Start date reached → activation. Cancellation removes only uninvoiced lines. The renewal action refuses a successor starting before the predecessor's boundary; this is also what the unit-level non-overlap constraint (below) would enforce. *The overlapping-renewal double billing was not re-run in this spike; the rule stands on the invariant and the extension evidence.*

---

## Double-Invoicing Protection

**Source Evidence.** The only uniqueness is `unique(invoice_id)` on `edara.payment.schedule.line` (`edara_payment_schedule_line.py:64`). There is no `@api.constrains` on the line model.
**Observed Test Result.**

| Step | Result |
|---|---|
| 1-2 Generate schedule, invoice due lines (2026-09-25) | 9 invoices |
| 3 Run invoicing again | 9 → 9 (**idempotent**: a line already invoiced is skipped) |
| 4 Edit `end_date` to 2027-04-01 and call the existing generator | uninvoiced lines regenerated for **all** periods from the start; 9 duplicate lines |
| 5 Run invoicing | **18 invoices**; **all 9 invoiced periods were invoiced twice** (e.g. period 2026-01-01 → `INV/…/00195` and `INV/…/00204`); invoiced amount for Jan–Sep **18,000** against a correct **9,000** |
| Inserting a second line for the same contract and period | **accepted** (ids 478 and 479 share 2027-03-01 → 2027-04-01) |

**EDARA Interpretation.** Today nothing identifies a *period*: only the invoice-to-line link is unique. The defect is in the generator (rebuilding covered periods), not in the invoicing cron, which is correct for the lines it is given.
**Future Implementation Principle.** *Invariant:* for one unit, the half-open periods `[period_start, period_end)` of all non-withdrawn schedule lines are pairwise disjoint; a period with a line that has an invoice in any state is consumed. Enforce it with a Python constraint on the line model (create and write, across contracts of the same unit) **and** make generation coverage-based. The contract state is not a duplicate guard.

---

## Extension Accounting Safety

**Source Evidence.** `end_date` is editable on an active contract; no `write()` override regenerates or extends the schedule (Phase 9 reading, unchanged).
**Observed Test Result** (real invoices; 7 scenarios; each run twice on identical starting contracts — the existing code path, and the coverage-based prototype):

| Scenario | NAIVE (edit end date, run existing generator) | COVERAGE-BASED PROTOTYPE |
|---|---|---|
| S1 fully invoiced, +1 month | lines 12 → **25**; 12 uninvoiced lines overlap invoiced periods | 12 → 13; adds `01/01/27–01/02/27`; all invariants hold |
| S2 partly invoiced (Jan–Sep), +3 months | 12 → **24**; 9 overlaps | 12 → 15; adds three monthly lines |
| S3 partly paid (Jan paid, Feb part-paid), +1 month | 12 → **22**; 9 overlaps | 12 → 13 |
| S4 unpaid **future** invoice (December invoiced early), +1 month | 12 → **23**; 10 overlaps | 12 → 13; December untouched |
| S5 last period prorated **and invoiced** (633.33), +3.4 months | 12 → **27**; 12 overlaps | 12 → 16; stub `20/12/26–01/01/27` (12 days, 400.00) then three full months |
| S6 last period prorated and **uninvoiced**, +1.4 months | 12 → **22**; 9 overlaps | 12 → 13; the stub is removed and recomputed as a full December |
| S7 quarterly, +2 quarters | 4 → **9**; 3 overlaps | 4 → 6 |

For every naive run the invoiced lines themselves stayed intact, but the pairwise-disjoint invariant failed. For every prototype run: invoiced lines unchanged (ids, periods, amounts, invoice links), pairwise disjoint, and contiguous coverage from the start to the new boundary.
**EDARA Interpretation.** The conceptual algorithm — never regenerate invoiced periods; find the coverage boundary; generate only missing future periods; invoice only what is due — passes on fully invoiced, partly invoiced, part-paid, unpaid-future, partial-period, one-month and multi-month extensions.
**Future Implementation Principle.**
1. Covered set = all existing lines, in any invoice or payment state.
2. If the last line is prorated and uninvoiced, remove and recompute it inside the new range. If it is prorated and invoiced, keep it and start the next period at its `period_end`, up to the next anchor boundary.
3. Generate only from the coverage boundary to the new boundary, anchored on the original start day.
4. Extension changes only `end_date`; direct editing of `end_date` on a confirmed contract is locked.
5. **Known consequence (OD-N1):** splitting a period at an invoiced stub sums to more than one rent for a 31-day month (633.33 + 400.00 = 1,033.33). The algorithm is correct under the current 30-day rule, but the rule itself needs a decision.

---

## OD-B10 — Holdover

*This section states product behavior and the legal questions it depends on. It makes no claim about Palestinian law.*

**Observed Test Result — the current software, per scenario** (real crons at simulated dates; old term ends 31/12/2026):

| Scenario | What the software does today | Accounting implication | Legal question that decides the product rule |
|---|---|---|---|
| **A** contract ends, no renewal | On 31/12/2026 the contract is still `active` (expiry count 0, unit `rented`). On 01/01/2027 it becomes `expired`, unit `available`, future uninvoiced lines removed, **no post-term invoice** (12 → 12) | No revenue after the term; nothing accrued | none for the software; who decides the tenant's status after the term |
| **B** renewal signed, successor starts later (01/03/2027) | Old flipped `renewed` at signing; unit `reserved` from 01/10/2026 through the gap (2027-01-01, 2027-02-15) and `rented` from 01/03/2027 | The Jan–Feb gap has no schedule line and no invoice | whether the gap is a tenancy (rent due) or a vacancy |
| **C** tenant stays, nobody acts | Contract `expired`, unit `available`, **no reminder** (expiry reminders are for `active` only), 12 previously invoiced lines are simply overdue | Nothing is accrued for occupation | whether occupation after expiry creates a periodic tenancy or a renewal, in which jurisdiction, and on what terms |
| **D** renewal signed after the old contract ended | `action_renew` on the expired contract: `UserError: Only an active contract can be renewed.` A hand-built successor dated 2027-01-01 and created on 2027-01-15 was **back-billed at once**: one invoice dated **2027-01-01**. A successor dated 2027-01-15 leaves 2027-01-01…14 unbilled | Back-billing issues an invoice in the past in one cron pass; alternatively the gap is unbilled | whether rent for the gap is owed, at what rate, and whether billing it is acceptance of a continuing tenancy |
| **E** tenant pays after expiry | (i) Paying an invoice of the expired contract reconciles natively: invoice `paid`, schedule line `paid`, contract still `expired`. (ii) A receipt with **no invoice** becomes a native customer credit (receivable credit 1,000; residual −1,000). Nothing in EDARA links the receipt to the contract or to a term | The receipt is a customer credit; no revenue is recognised for the occupation | whether accepting that payment is legally acceptance of a continuing tenancy |

**EDARA Interpretation.** The exact product decision needing legal validation is: *when the term has ended and the tenant remains, what is the tenant's status, and does accepting or invoicing rent change it?* The software should not answer that question by itself. Two behaviors are visible and not legal: the software silently invoices in the past if a back-dated successor is created (D), and it raises no alert when a tenant stays (C).
**Future Implementation Principle.**
- The system never extends, renews or bills after the boundary on its own.
- **No silent back-billing:** activating or creating a contract whose first lines are already due must show the invoices that will be created and require confirmation. (A protection principle; it does not choose the legal policy.)
- Keep the following **configurable**, because legal policy may vary by customer or jurisdiction: whether a holdover to-do is raised, the late-renewal window, whether back-billing is offered at all, and any holdover rent rate (taken from the signed contract, never computed).
- **BLOCKED — LEGAL** for the holdover status and the back-billing policy.

---

## Late Renewal / Back-Billing

Example: old contract ends 31/12/2026; renewal signed 15/01/2027; tenant remained in possession.

| Model | Accounting mechanics (observed or source) | Product behavior | Legal dependency |
|---|---|---|---|
| **Back-bill the occupied period** | A successor starting 01/01/2027 generated its January line due 01/01; one invoicing pass created the invoice **dated 01/01/2027** (observed). The 1–14 January days are billed as part of a full period | The first invoice is created in the past in one pass | whether rent is owed for the gap; billing may be read as acceptance |
| **Temporary holdover charge** | No such flow exists; would be an ad-hoc invoice or a stub period (the coverage generator can create a stub, validated in S5) | A separate, labelled charge for 01/01–14/01 | rate and basis |
| **Extend the old contract retroactively** | `expired` contracts cannot be extended by the UI; the ORM allows editing `end_date` but the existing generator would double-bill (Double-Invoicing) | Rewrites the term after the fact | whether the term is legally continuous |
| **Successor starting at the actual effective date (15/01/2027)** | First invoice dated 01/15/2027; **01/01–14/01 has no line and no invoice** (observed) | Simplest; the gap is unbilled | whether the gap is a vacancy |
| **Block until an owner/legal decision** | No state exists; the contract stays `expired` and the renewal is refused (observed) | An explicit decision is required | none: it defers the question |

**EDARA Interpretation.** Accounting can implement any of the models natively: they are all schedule-line choices, none requires special accounting. The choice is a product and legal choice.
**Future Implementation Principle.** Phase 10 implements only the guard (**no silent back-billing**) and the ability to create a stub period. Choosing between the models is **BLOCKED — LEGAL** (and the late-renewal window with it).

---

## Cross-Decision Findings

1. **OD-A7 ↔ OD-B8.** Carry-over depends on the tie-out between per-deposit balances and the GL liability. On a payable-type account the tenant's payable total also moves (3,000 in the observed test); the control report must group by tenant and account.
2. **OD-B3 ↔ OD-B10.** The expiry cron already treats `end_date` as inclusive, so the holdover moment is exactly the boundary date. No date logic needs to change for holdover; only the boundary helper for generation and overlap.
3. **OD-B5 ↔ OD-B6 ↔ OD-B9.** Invoicing is a state whitelist, so a new state is safe by default. Terminate-with-successor and renewal-cancel are covered by the same `cancelled` transition (verified in the model).
4. **OD-A4 ↔ OD-A5.** The collection cap and the requirement that alternative-currency payment credit the contractual currency are one rule: the deposit record is denominated in the contract currency and the payment must be too.
5. **Exchange-difference date.** Odoo dates realised FX entries at period end, so a settlement in one month can post its FX in the same month's last day; reports by day will show the FX after the cash movement.
6. **Phase 7 special case.** Billing of `renewed` contracts becomes redundant once the old contract stays `active` to its boundary; the whitelist can keep it as a safety net.
7. **Proration rule (new, OD-N1).** The stub period in extension and the 30-day reference month interact; this is independent of the end-date convention.
8. **Deposit before cash (new, OD-N2).** Model 3b shows that recognising a deposit as a receivable before cash creates a spurious realised gain and, later, an offsetting unrealised loss. EDARA's current rule (liability only on cash) avoids it and should be kept.

---

## Decision Status After Validation

| Decision | Phase 9.1 Status | Phase 9.2 Result | Final Status | Evidence |
|---|---|---|---|---|
| OD-A5 | OPEN | Native USD payment on an ILS journal represents a USD deposit exactly (observed); Odoo does not convert or enforce; Model 2a rejected; bank write-off NOT EXECUTED | **RECOMMENDED** (Model 1); Model 3 **NEEDS ACCOUNTANT** before release | `s5`, `s6`; source `account_move_line.py:2673` |
| OD-A7 | NEEDS ACCOUNTANT | Technical requirement validated: reconcilable is mandatory for foreign-currency deposits; revaluation needs a fixed currency or a payable type; payable presents deposits in payables; account type left to accountant | **NEEDS ACCOUNTANT** (type and presentation); requirement itself **RECOMMENDED** | `s2`, `s2b`, `s3`-`s4d`, `s10`, `s11`; source `account_multicurrency_revaluation_report.py:305-310` |
| OD-B3 | RECOMMENDED | Inclusive business date with `end_date + 1` boundary reproduces the business day count in 14 of 14 real-generator cases; the current form is short by one day in 13 and refuses the single-day lease | **RECOMMENDED** (validated) | `s8a`; sources listed in OD-B3 |
| OD-B5 | RECOMMENDED | Model consistent in 5 scenarios; a draft successor does not protect the unit; current code flips the old contract early and shows `reserved`; two constraints (reminder domain, whitelist) | **RECOMMENDED** (validated) | `s9`, `sm.py` |
| OD-B6 | RECOMMENDED | Schedule creation, invoicing and activation are separate events with two gates; confirmation-time generation safe; cancellation removes only uninvoiced lines; overlapping-renewal double billing NOT re-run | **RECOMMENDED** (timing validated) | `s9`, `s8b` |
| OD-B8 | NEEDS ACCOUNTANT | Renewal creates 0 accounting moves; carry-over needs no journal entry; amount changes map to native collect/refund; currency change realises FX; no pending-deduction concept | **NEEDS ACCOUNTANT** (technical feasibility validated) | `s7` |
| OD-B10 | NEEDS LEGAL | Scenarios A–E mapped; the exact legal question isolated; silent back-billing observed | **NEEDS LEGAL** (with the guard principle validated) | `s9` |

### Additional decisions reopened or added by technical findings

| ID | Status | Why |
|---|---|---|
| OD-N1 — Proration basis (30-day reference vs actual days) | **NEEDS ACCOUNTANT** | 181 days on a yearly line billed 502.76 against 500.00; a 31-day month split into two prorated pieces bills 1,033.33 (`s8a`, `s8b` S5) |
| OD-N2 — Deposit recognised only on cash receipt | **NEEDS ACCOUNTANT** | A receivable-first design yields a spurious gain of ILS 1,000 (`s6`); confirm the cash-receipt rule |
| OD-A7 (refinement) | (record only) | Phase 9.1 said "reconcile when a deposit closes". Partial reconciliation books realised FX on the matched part, so EDARA can reconcile at **each** refund or deduction |
| Phase 9.1 §3.3 figures | (correction only) | 1,011.11 and 4,011.11 become **1,011.07** and **4,011.10** on the real generator |
| Phase 9.1 OD-A5 acceptance step 2 | (correction only) | With equal company-currency amounts no exchange entry arises; a mismatch leaves a residual that needs a bank-side write-off (NOT EXECUTED) |

No Phase 9.1 decision became invalid.

---

## Phase 10 Must Implement

Only rules validated in this spike. Anything that still needs an accountant or a lawyer is marked and is **not** a final implementation rule.

**Dates and schedules**
1. The business end date is inclusive (the last occupied day). One helper derives `term_boundary = end_date + 1 day`; the schedule generator, overlap check, occupancy and expiry use it. `_check_dates` accepts `end_date >= start_date`.
2. Existing contract dates are migrated only per contract, reviewed by a person; for an anniversary-style contract, setting `end_date` back one day leaves the generated periods identical.
3. Schedule generation is coverage-based: it never rebuilds a period that has an invoiced line; it generates only from the coverage boundary; an uninvoiced prorated tail is recomputed, an invoiced one is kept.
4. A unit-level constraint: non-withdrawn schedule lines on one unit have pairwise-disjoint periods; a period with a line that has an invoice in any state is consumed.
5. Existing posted invoices are immutable from lifecycle logic; no lifecycle event cancels or regenerates an invoice.

**Lifecycle**
6. Extension changes only `end_date`, forward; it is an explicit action; direct editing of `end_date` on a confirmed contract is locked.
7. The old contract stays `active` to its boundary; a renewal never changes it before then.
8. A signed successor is `scheduled`; overlap and occupancy count it; a scheduled successor is `reserved` only while no active contract covers today, so the unit stays `rented` during a renewal.
9. One ordered daily job: activate scheduled → close ended active (`renewed` if a successor exists, `expired` otherwise) → recompute units. A scheduled contract that cannot activate produces a same-day to-do and stays `scheduled`.
10. The renewal start date may not precede the predecessor's boundary.
11. Invoicing stays a whitelist of contract states plus the line's due date; schedule creation, invoicing and activation stay three separate events; the overdue-reminder domain gets a contract-state filter.
12. `action_terminate` also cancels a scheduled successor after an explicit confirmation.
13. **No silent back-billing:** activation or creation of a contract with already-due lines shows the invoices that will be created and requires confirmation.

**Deposits and currency**
14. The deposit stays in its contractual currency; deposit payments are in that currency; `action_collect` is capped at `amount − amount_held`.
15. For any deposit whose currency differs from the company's, the configured liability account must be **reconcilable**, and EDARA reconciles each refund or deduction natively (partial reconciliation books the realised FX). EDARA books no exchange entry of its own. A setup check warns when the account is not reconcilable.
16. A deposit is recognised only on cash receipt (see OD-N2 for the accountant's confirmation).

**Marked as blocked (not final rules)**
- **BLOCKED — ACCOUNTANT:** deposit account type and presentation (payable vs per-currency current accounts); revaluation cadence; carry-over as a no-entry paired transfer; alternative-currency payment (Model 3) and its bank-side write-off; proration basis (OD-N1); cash-receipt-only recognition (OD-N2); discounting (OD-A2); agent/escrow (OD-A3).
- **BLOCKED — LEGAL:** the holdover status of a tenant who stays; back-billing policy; the late-renewal window; holdover rent; segregation duty for deposits (OD-A3).

---

## Remaining Accountant Questions

1. Is a customer deposit acceptable in payables, or must it stay in current liabilities with one fixed-currency account per currency? (OD-A7)
2. Is a no-entry transfer between two deposit records of the same tenant, company, currency and account acceptable, and is "Σ record balances = GL liability, per tenant and account" the required control? (OD-B8)
3. At what cadence is the foreign-currency deposit remeasured, and is the native provision with automatic reversal acceptable? (OD-A6)
4. Is recognising a deposit only on cash receipt, never as a receivable, the correct policy? (OD-N2)
5. Should the 30-day reference month stay, or should proration use the actual number of days in the period? (OD-N1)
6. For a USD deposit received in ILS, which rate source and rounding rule, and how is a bank-side rate mismatch written off? (OD-A4 / OD-A5, before Model 3 is built)
7. Does a customer need present-value discounting of a non-interest-bearing deposit? (OD-A2)

## Remaining Legal Questions

1. After the term ends and the tenant remains, is a periodic tenancy created, is it a renewal, or neither, and does accepting or invoicing rent change that? (OD-B10)
2. Is rent owed for a gap between the end of a term and a late renewal, and at what rate? (Back-billing; OD-B2)
3. Must security deposits be held in a segregated account, in the customers' jurisdiction? (OD-A3)
4. Do the customers' standard contract templates state the last day of the tenancy as the end date? (OD-B3, wording check; non-blocking)
5. Do customers write a deposit in a different currency from the rent, or with a conversion clause? (OD-A1; non-blocking)

## Remaining Open Decisions

- **OD-N1** proration basis (NEEDS ACCOUNTANT).
- **OD-N2** cash-receipt-only deposit recognition (NEEDS ACCOUNTANT).
- Everything marked NEEDS ACCOUNTANT / NEEDS LEGAL in the status tables above.
- **OD-A5 no longer requires a spike:** Model 1 is the Phase 10 rule; Model 3 waits for the accountant, and its bank-side write-off is the one technical item still **NOT EXECUTED**.
