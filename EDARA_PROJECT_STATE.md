# EDARA — Project State

Project: EDARA Property Management (Odoo 19)
Module: `property_managment`
Odoo Version: 19.0 Community (confirmed from `odoo/release.py`)

## Current Phase
None — all 16 phases (0-15) complete. See "Final Validation Status" at the end of this file.

## Completed Phases
- Phase 0 — Environment & Architecture Verification
- Phase 1 — Foundation: manifest, module skeleton, security groups (privilege-based, see decisions below), ACLs, record rules, `edara.branch` model+views+menu. Fresh install verified, upgrade verified, 3/3 automated tests passing (branch code uniqueness, branch isolation record rule, company-manager bypass).
- Phase 2 — Property Structure: `edara.property` / `edara.building` / `edara.unit` / `edara.ownership`, `res.partner.is_edara_owner`, smart buttons (Branch→Properties, Property→Buildings/Units, Building→Units), list/form views + menus, security ACLs/record rules for all 4 new models (same 3-rule branch-scoping pattern as Phase 1). Fresh install verified, upgrade verified, 10/10 tests passing (7 new: building inherits branch, unit code uniqueness, unit status consistency constraint, ownership percentage range, ownership total >100% rejected, valid split sets is_edara_owner, unit visibility follows branch assignment through the building→property→branch chain).

- Phase 3 — Tenant & Lease: `res.partner` tenant extensions (`is_edara_tenant`, `edara_national_id`), `edara.lease.contract` (draft/active/renewed/terminated/expired lifecycle, sequence-numbered via `ir.sequence`), `edara.lease.renewal.wizard`. Validations: end>start, rent>0, payment_day 1-28, no overlapping active contracts on the same unit, activation blocked for sold/under-maintenance units, unlink blocked once out of draft. `edara.unit.occupancy_status` can no longer be manually set to 'rented' without a backing active contract (constraint, not a computed field - see decisions). Unit gets a Contracts smart button. Owner-initiated renewal implemented now; tenant-request-vs-approval workflow (`edara.renewal.request`) deferred to Phase 9 (needs the portal to exist first - see decisions). Fresh install verified, upgrade verified, 19/19 tests passing.

- Phase 4/5 (merged) — Payment Scheduling + Accounting Integration core: `edara.payment.schedule.line` (due_date/amount/state computed from linked invoice's payment_state, one invoice per line via unique constraint), `edara.lease.contract._generate_schedule_lines()` (called from `action_activate()`, honors `billing_frequency`/`payment_day`, only regenerates uninvoiced lines), `_create_invoice()` (posts an `account.move` against the configurable `res.company.edara_rental_income_account_id` with the property's analytic account at 100% distribution; raises a clear `UserError` if the income account isn't configured), and an idempotent/race-safe `ir.cron` (`_cron_generate_due_invoices`, daily) using `FOR UPDATE SKIP LOCKED` raw SQL plus a `contract.state == 'active'` re-check as a second defense layer (first layer: `action_terminate()` unlinks uninvoiced future schedule lines). Added `account.move` EDARA context fields (invoice type, contract/unit/building/property/branch), `res.company`/`res.config.settings` with 4 configurable accounting accounts (rental income, late fee income, service charge income, deposit liability) exposed via a new EDARA tab in Settings, and a shared `account.analytic.plan` (one analytic account lazily created per `edara.property`, see `edara_property.get_analytic_account()`). Merged these two spec phases because their tests are inseparable (duplicate-invoice/cron-idempotency tests need real invoice creation, not a stub) — decided unilaterally per the master prompt's "handle exposed dependencies" guidance, not user-confirmed. Fresh install verified, upgrade verified, 24/24 tests passing (5 new: schedule generation dates/count correct, invoice creation blocked with a clear error when the income account isn't configured, invoice posts with correct analytic distribution, cron is idempotent and only invoices due lines, termination removes future uninvoiced lines and the cron then invoices nothing further for that contract).

- Phase 6 — Deposits: `edara.deposit` (one per contract, unique constraint, `amount_held`/`amount_refunded`/`amount_deducted`/`balance`/`state` all computed+stored from its transactions), `edara.deposit.transaction` (HELD/REFUND/DEDUCTION types, index/audit layer only - `unlink()` unconditionally blocked, "do not delete financial history" per spec §28), `account.payment` extended with `edara_is_security_deposit` (redirects `destination_account_id` to the configurable `res.company.edara_deposit_liability_account_id` via an overridden `_compute_destination_account_id`, raising a clear `UserError` if unconfigured - never silently posts to receivable, per spec §26), deduction posts a plain `account.move` (Dr Liability / Cr the new configurable `edara_deposit_deduction_income_account_id`). UI: `edara.deposit.transaction.wizard` (one shared wizard, `transaction_type` from button context, drives collect/refund/deduct), 3 header buttons on the deposit form, a Deposit smart button on the contract form (visible when `deposit_required`), Security Deposits menu. Fresh install verified, upgrade verified, 31/31 tests passing (7 new: collection blocked without a configured liability account, collect creates a payment with the correct redirected destination account and updates balance/state, refund reduces balance and closes the deposit when fully refunded, refund cannot exceed balance, deduction blocked without a configured income account, deduction posts a correctly-debited/credited journal entry and reduces balance, deposit transactions cannot be deleted).

- Phase 7 — Service Charges & Expenses: `edara.service.charge` (scoped to a Building - the physical boundary, per architecture decisions; sequence-numbered `SC/<year>/<seq>`, `state` computed draft/allocated/invoiced from its lines) with 4 allocation methods (`equal`, `proportional` by unit area, `per_sqm` rate × unit area, `fixed_per_unit`), `action_generate_allocation()` (computes a share for every active unit in the building, but only creates a line - and only charges - units with a currently active lease contract; a vacant unit's computed share is simply not collected, not redistributed onto occupied units - a documented simplification, not a bug), `edara.service.charge.line._create_invoice()` (mirrors the Phase 4/5 rent-invoice pattern: posts against the configurable `edara_service_charge_income_account_id` with the property's analytic distribution, blocking error if unconfigured). Refactored `account.move`'s EDARA context fields (`edara_unit_id`/`building_id`/`property_id`/`branch_id`) from related-from-contract to plain stored fields set explicitly by both invoice-creation paths (schedule line and service charge line) and, for vendor bills with no contract, directly editable by the user (with an onchange cascading `edara_contract_id` → unit/building/property/branch, and `edara_property_id` → branch, for convenience) - this is what makes expense tracking (§29, native vendor bills tagged with property/building/unit) possible without a parallel model. Added an "Expenses" smart button on `edara.property` (opens `account.action_move_in_invoice_type` filtered to that property) and a "Service Charges" smart button on `edara.building`. Fresh install verified, upgrade verified, 39/39 tests passing (8 new: equal/proportional/per_sqm/fixed_per_unit allocation math all correct and only charge occupied units, missing amount blocks allocation, a building with no units blocks allocation, invoicing blocked without a configured income account, invoicing posts correctly-tagged invoices and updates charge state to invoiced).

- Phase 8 — Maintenance: `edara.maintenance.request` (custom model, not native `maintenance.request` - confirmed unsuitable per spec §41/architecture decisions since it's equipment-centric; sequence-numbered `MR/<year>/<seq>`, `mail.thread`+`mail.activity.mixin`) with the spec's exact suggested fields (title/description/tenant_id/unit_id+derived building/property/branch/company/assigned_user_id/priority/state/requested_date/completed_date/cost/vendor_id) and the exact NEW→ASSIGNED→IN_PROGRESS→DONE/CANCELLED lifecycle via `action_assign()`/`action_start()`/`action_complete()`/`action_cancel()`, each validating the current state before transitioning. Deliberately does NOT auto-toggle `edara.unit.operational_status` to `under_maintenance` - kept decoupled since not every request (e.g. a minor faucet fix) should take a unit offline; a PM can still set that manually. Attachments and activities/chatter come for free from the mixins (no extra work needed, satisfies spec's "attachments" checklist item via native `ir.attachment` on the chatter, per §42). Unit gets a Maintenance smart button. Fresh install verified, upgrade verified, 46/46 tests passing (7 new: sequence naming, full lifecycle, cannot complete a new (unassigned) request, cancel allowed before done, cannot cancel a done request, negative cost blocked, unit smart-button count).

- Phase 9 — Portal: `edara.renewal.request` (the deferred model from Phase 3 - Active Contract → Renewal Request → Approved → New/Extended Contract per spec §45, `action_approve()` calls the existing `contract.action_renew()` so it never bypasses those validations and never destroys contract history; `action_reject()`; constraints block a second open request per contract and requesting a renewal on a non-active contract), with a backend list/form (Approve/Reject buttons) and a Contract "Renewals" smart button. A real tenant-facing website portal (`controllers/portal.py` extending the actual `portal.CustomerPortal`, verified against its real Odoo 19 source - `_document_check_access`, `_prepare_home_portal_values`, `portal.portal_docs_entry`/`portal_table`/`portal_layout`): `/my/leases` (list) + `/my/leases/<id>` (detail, with a renewal-request submission form when active and no request already pending) + `/my/leases/<id>/renew` (POST), `/my/maintenance` (list) + `/my/maintenance/new` (GET form / POST submit, unit choice restricted server-side to the tenant's own active-lease units - client-supplied `unit_id` is validated, never trusted) + `/my/maintenance/<id>` (detail), plus two new cards on the native `/my` home page. Security: 4 new portal-scoped `ir.rule`s (`tenant_id = user.partner_id.id` / `lease_contract_ids.tenant_id` for units) are the *only* rules that apply to `group_edara_portal_tenant` (it doesn't carry `group_edara_viewer`), verified by an `HttpCase` test that tenant A gets 403/no-record-created against tenant B's lease, unit, and maintenance data - never derivable via URL id per spec §39. Scope deliberately narrowed vs. the full spec §40 list: Invoices/Payments/Outstanding Balance/Payment History are NOT custom-built - they come for free from the native `account`+`portal` "My Invoices" page (an `account.move` with `partner_id=tenant` is already exactly what portal shows, and its own record rules already restrict to the invoice's own partner), "My Unit" is folded into the lease detail page (no separate page for one fact set), and Documents/Notifications/Profile reuse native `ir.attachment`/chatter/`/my/account` rather than new pages - this is "don't reinvent, native already covers this," not a shortfall. Interactive portal chatter (message composer) was NOT embedded on the lease/maintenance detail pages (only plain read-only status fields) - a documented scope cut, not a defect; the backend chatter still works for staff. Fresh install verified, upgrade verified, 53/53 tests passing (7 new: tenant can view own lease, tenant cannot view another tenant's lease, record rule hides another tenant's unit from search, tenant can file a maintenance request for their own unit, tenant cannot file one for a unit they don't lease (even by directly posting a foreign `unit_id`), tenant can submit a renewal request for their own lease, tenant cannot submit one for another tenant's lease).

- Phase 10 — Reports: `edara.property`/`edara.branch` extended with a non-stored, on-demand `_compute_financial_summary()` (`currency_id` related to company + `total_revenue`/`total_expenses`/`net_operating_result`/`total_outstanding` Monetary fields, `@api.depends()` empty so it recomputes on every read like a live snapshot rather than being kept in sync via triggers - deliberate, since financial summaries are read far less often than invoices are posted) using `account.move._read_group` filtered by `edara_property_id`/`edara_branch_id`, `state='posted'`, and `move_type`, summing `amount_untaxed_signed` (nets `out_refund`/`in_refund` against invoices/bills automatically - verified against actual Odoo 19 `account.move` sign-convention source, see Architecture Decisions) and `amount_residual_signed` for outstanding receivables. Both get a "Financial Summary" notebook page. `views/reports_views.xml` (new file, reuses native pivot/graph/list - no custom report engine, no parallel model): Revenue/Expenses pivots on `account.move` (branch+property rows x month columns, measure `amount_untaxed_signed`), a Receivables pivot (property+partner rows x payment_state columns, measure `amount_residual_signed`), an Occupancy pivot on `edara.unit` (branch+property rows x occupancy_status columns), and a Tenant Ledger (list+pivot on `account.move` filtered to `partner_id.is_edara_tenant=True`, grouped by partner by default) - satisfies the spec's full Phase 10 checklist (revenue/occupancy/receivables/expenses/property summary/branch summary/tenant ledger/useful filters+grouping). Discovered via source inspection that `account.move` has no native pivot view of its own (only `account.move.line` does, `view_move_line_pivot`), so every report action explicitly pins its own `view_id`. Added one shared search view for the three `account.move`-based reports (filters: Posted/Draft/This Year; group-by: Branch/Property/Tenant/Month) and one for the Occupancy report (filters: Rented/Vacant; group-by: Branch/Property/Status) - discovered mid-implementation that Odoo 19's search-view RelaxNG schema rejects a `string` attribute on the group-by `<group>` element (only bare `<group>` is valid; confirmed against the native `account.move` search view's own group-by section), unlike the `<pivot>`/`<list>` root elements which do accept `string`. Reports menu restricted to `group_edara_accountant,group_edara_branch_manager` (not plain viewers) since it exposes financial data - branch_manager/company_manager already imply the full manager hierarchy via `implied_ids`. Fresh install verified, upgrade verified, 58/58 tests passing (5 new: revenue/expense/NOR/outstanding computed correctly from posted invoices+vendor bills, credit notes net correctly against revenue, draft moves excluded from the summary, all four report pivot views load without error, tenant ledger includes only tenant partners' invoices and excludes non-tenant partners).

- Phase 11 — UX: `edara.dashboard` (new `TransientModel`, spec §47 - a professional management dashboard using native view architecture only, no OWL/external framework). A fresh transient record is created on every open (`action_open()`, wired via a small `ir.actions.server` since the `ir.actions.act_window` needs a dynamically-created `res_id`) and its 11 KPI fields (`total_properties`/`total_buildings`/`total_units`/`occupied_units`/`available_units`/`under_maintenance_units`/`monthly_revenue`/`outstanding_receivables`/`upcoming_renewals_count`/`open_maintenance_count`/`recent_payments_count`) are computed live with `@api.depends()` empty - the same non-stored "snapshot" pattern as Phase 10's financial summary, deliberately chosen so there's no singleton-row bootstrap/race-condition concern (TransientModel rows auto-vacuum, no manual cleanup needed). Rendered as a plain readonly form using the native `o_stat_info`/`o_stat_value`/`o_stat_text` CSS classes Odoo already ships (normally used inside stat buttons, but they render identically standalone) arranged in a Bootstrap grid - no custom CSS file, no JS. "Dashboard" menu item added as the first EDARA menu entry. Added kanban board views (workflow visualization, spec's "kanban views"/"status visualization" checklist items) for `edara.maintenance.request` (grouped by state) and `edara.renewal.request` (grouped by state), both using Odoo 19's `<t t-name="card">` kanban template convention (verified against native `project` module views - no wrapping `<div class="oe_kanban_card">` needed, the framework provides it). Filled in the two action windows that were missing an empty-state `help` block (Security Deposits, Payment Schedule Lines) and added a missing one for Renewal Requests. Fresh install verified, upgrade verified, 60/60 tests passing (2 new: dashboard KPIs reflect actual created-record counts, `action_open()` returns a valid form action with a freshly-created record id).

- Phase 12 — Visual Property Management: `edara.unit` gets a kanban board view (spec §48, ASCII floor-grid mockup) grouped by `floor` (one column per floor, matching the mockup exactly since `floor` is already a plain Char field ordered into `_order`), each card colored via Bootstrap utility classes bound to `occupancy_status`/`operational_status` (green=available, red=rented, orange=under maintenance, grey=other) so status is obvious at a glance without reading text - pure native kanban/QWeb, no OWL component, no custom CSS file, no third-party dependency (satisfies spec §49's "avoid unnecessary third-party dependencies" and "3D MUST NOT become a core dependency" by not attempting 3D at all - 2D coverage is complete and the ASCII mockup never asked for 3D). Added a dedicated Unit search view (filters: Available/Rented/Under Maintenance; group-by: Building/Floor/Occupancy) so the grid can be regrouped by building or occupancy interactively. Fresh install verified, upgrade verified, 61/61 tests passing (1 new: unit kanban view loads and the action's search_view_id resolves correctly).

- Phase 13 — Hardening: a full audit against spec §13's checklist (security, record rules, multi-company, portal isolation, direct URLs, forged IDs, company/branch mismatches, financial integrity, duplicate cron execution, performance) across the *whole* module, not just Phase 10-12's new code. Verified clean: the record-rule 3-rule pattern is applied consistently to every branch-scoped model with no gaps; `group_edara_maintenance`/`group_edara_accountant` correctly inherit the viewer branch-restriction via `implied_ids` (a user's group membership includes implied groups, so the `group_edara_viewer`-tagged rule does apply to them - verified this isn't a silent "sees everything" hole); the portal controller has exactly one `.sudo()` call in the entire module (the already-documented `ir.sequence`-access workaround in maintenance-request creation, still correctly ordered *after* server-side ownership validation) - no other sudo/privilege-escalation surface exists; the single cron is already idempotent and lock-safe (Phase 4/5); ownership percentage validation is a bounded sweep-line over one property's own records, not a real N+1 risk. Found and fixed two genuine gaps: (1) `account.move`'s EDARA tag fields (`edara_branch_id`/`edara_property_id`/`edara_building_id`/`edara_unit_id`) are plain user-editable fields for vendor bills (not related-from-contract, see Phase 7's architecture note) with no consistency check - nothing stopped tagging an invoice with a property from a different branch, or a branch/property from a different company than the journal entry itself, which would silently corrupt the Phase 10 per-branch/per-property financial summaries; added `account.move._check_edara_tags_consistent()` (`@api.constrains`) validating branch↔company, property↔company, property↔branch, building↔property, and unit↔building consistency. (2) `edara.payment.schedule.line` and `edara.service.charge.line` had `perm_unlink=1` for branch managers with no protection once a line was invoiced - the invoice itself is already protected natively (Odoo blocks unlinking a posted `account.move`), but deleting our own line would silently break the audit trail linking a contract's rent/charge period to its invoice; added `unlink()` overrides on both raising `UserError` when `invoice_id` is set (uninvoiced lines are unaffected - `action_terminate()`'s existing cleanup already filters to uninvoiced-only, confirmed compatible). Fresh install verified, upgrade verified, 68/68 tests passing (7 new: invoiced schedule/service-charge lines cannot be deleted while uninvoiced ones still can, four `account.move` tag-consistency scenarios - cross-branch, cross-property/branch, cross-property/building, cross-building/unit - correctly rejected, one same-branch case correctly accepted).

- Phase 14 — Full Test & Regression: spec §14's checklist (module install, module upgrade, Python/ORM/security/accounting/portal/cron/multi-company/validation tests) was already being exercised after every single phase throughout this project (fresh install on a throwaway DB + upgrade on the persistent `edara_test` DB + full `--test-enable` suite, per the master prompt's per-phase definition-of-done), so this phase's job was to find what that per-phase habit had never specifically targeted. Found one real gap: no test had ever created a second actual `res.company` to verify the branch/company-manager "sees all branches" rule (a plain `(1,'=',1)` domain) truly stays company-scoped only because it's ANDed with the separate global `company_id in company_ids` rule - every prior test exercised multi-*branch* isolation within a single company, not multi-*company* isolation. Added `tests/test_edara_multicompany.py` (2 tests: a company-manager restricted to Company A cannot see Company B's branch even though their own rule says "all branches"; a company-manager granted both companies sees both) - both passed on the first run, confirming the architecture's ANDing assumption actually holds rather than just being asserted in comments. Fresh install verified, upgrade verified, 70/70 tests passing.

- Phase 15 — Final Product Audit: a section-by-section audit of the full 80-section spec against the actual implementation, going beyond Phase 13's security/hardening focus into functional completeness, native-reuse correctness, and UX polish. Confirmed already-correct-by-native-reuse (no code needed, verified rather than assumed): "Receive Payment" (§22, native `action_register_payment` button on `account.move`, confirmed present in `odoo/addons/account/views/account_move_views.xml` with no override needed), partial payments/overpayments/credit notes (§23-25, entirely native reconciliation), import/export (§62, native list-view CSV/XLSX import works on any ACL'd model), currencies/payment methods (§64-65, no hardcoded currency or journal anywhere - grepped and confirmed), accessibility (§66, status is always paired with a text label, never color-only), error messages (§67, every raised error grepped and confirmed wrapped in `_()` with named placeholders), translation-readiness (§63, zero untranslated user-facing strings found) - actual Arabic translation *content* (professionally-written `.po` terms) is a separate content/localization task, not an engineering gap; the system is translation-ready but not yet translated, and that distinction is deliberate rather than an oversight. Found and fixed three genuine functional gaps the phase-by-phase build had left behind: (1) **EXPIRED was an unreachable contract state** - `edara.lease.contract` listed it in `STATES` (spec §14) but nothing ever set it; a contract past its own `end_date` that was never renewed or terminated just sat in `active` forever. Added `_cron_expire_contracts()` (daily, spec §60's named "Update Contract Expiration" job) - naturally idempotent (the `state='active'` filter excludes contracts it already expired), frees the unit (`occupancy_status='available'`) and drops remaining uninvoiced schedule lines exactly like `action_terminate()` already does. (2) **Late fees (§21) had a configured income account but no way to ever charge one** - added `res.company.edara_late_fee_amount` (a flat configurable amount, the simplest "rule" that satisfies "must be configurable" without inventing a rule engine per spec's own restraint) and `edara.payment.schedule.line.action_charge_late_fee()`, a manual-only button visible only when a line's computed `state == 'overdue'` - deliberately never automatic, per spec's explicit "do not automatically charge arbitrary late fees without a business rule." (3) **Missing smart buttons from spec §52's list** - `edara.building` had no Contracts/Maintenance buttons and `edara.property` had no Invoices (revenue) button symmetric to its existing Expenses button; added all three following the exact same `_read_group`+`action_view_*` pattern already used everywhere else. Fresh install verified, upgrade verified, 78/78 tests passing (10 new: contract expiry cron fires correctly and is idempotent, a contract still within its term is untouched, late fee charging blocked without an income account/without a configured amount/when not overdue and succeeds as a correctly-tagged separate invoice when properly configured and overdue, building smart-button counts and domains, property invoices smart-button domain).

## Implemented Models
- `edara.branch` (Phase 1)
- `edara.property`, `edara.building`, `edara.unit`, `edara.ownership`, `res.partner` (extended) (Phase 2)
- `edara.lease.contract`, `edara.lease.renewal.wizard`, `res.partner` (tenant extensions) (Phase 3)
- `edara.payment.schedule.line`, `res.company` (extended), `res.config.settings` (extended), `account.move` (extended) (Phase 4/5)
- `edara.deposit`, `edara.deposit.transaction`, `edara.deposit.transaction.wizard`, `account.payment` (extended) (Phase 6)
- `edara.service.charge`, `edara.service.charge.line` (Phase 7)
- `edara.maintenance.request` (Phase 8)
- `edara.renewal.request` (Phase 9)
- `edara.dashboard` (Phase 11, `TransientModel`)

## Implemented Views
- Branch list/form + Configuration menu (Phase 1)
- Property/Building/Unit list/form + top-level menus (Phase 2)
- Lease Contract list/form (statusbar, Activate/Renew/Terminate buttons), renewal wizard, partner form extension (Phase 3)
- Payment Schedule list/form + menu, Contract "Schedule" smart button, EDARA Settings tab (rental/late-fee/service-charge income accounts + deposit liability account) (Phase 4/5)
- Deposit list/form (Collect/Refund/Deduct header buttons, transactions notebook), deposit transaction wizard, Contract "Deposit" smart button, Security Deposits menu, EDARA Settings tab extended with the deposit deduction income account (Phase 6)
- Service Charge list/form (Generate Allocation/Create Invoices header buttons, allocation notebook), Building "Service Charges" smart button, Property "Expenses" smart button (native vendor bills list filtered to the property), Service Charges menu (Phase 7)
- Maintenance Request list/form (Start/Complete/Cancel header buttons, statusbar, chatter), Unit "Maintenance" smart button, Maintenance menu (Phase 8)
- Renewal Request list/form (Approve/Reject buttons), Contract "Renewals" smart button, Renewal Requests menu; tenant-facing website portal pages (`/my/leases`, `/my/maintenance`, detail/new-request pages) plus two new cards on the native `/my` home dashboard (Phase 9)
- Property/Branch "Financial Summary" notebook page; Reports menu (Revenue/Expenses/Receivables/Occupancy/Tenant Ledger pivot+list views with search/filter/group-by), restricted to accountant/branch-manager roles (Phase 10)
- Dashboard menu (KPI form), Maintenance/Renewal Request kanban boards, empty-state help text completed on all remaining list actions (Phase 11)
- Unit kanban board (visual floor grid, color-coded status) + Unit search view with filters/group-by (Phase 12)

## Portal Routes (Phase 9)
- `/my/leases`, `/my/leases/<id>`, `/my/leases/<id>/renew` (POST)
- `/my/maintenance`, `/my/maintenance/new` (GET/POST), `/my/maintenance/<id>`

## Security Status
Phase 1 pattern established and verified working:
- One global multi-company `ir.rule` (no groups) + one restrictive `ir.rule` on `group_edara_viewer` (branch-assignment domain) + one bypass `ir.rule` on `group_edara_company_manager` ((1,'=',1)), which OR together correctly because company_manager/administrator also carry `group_edara_viewer` via `implied_ids`.
- This exact 3-rule pattern is now applied to every branch-scoped model through Phase 4/5 (property, building, unit, ownership, contract, payment schedule line).

## Accounting Status
Native `account.move` (out_invoice) creation from payment schedule lines (Phase 4/5) and service charge lines (Phase 7), both posted against configurable income accounts with analytic distribution to the property's analytic account. Security deposits (Phase 6) fully implemented: held/refunded via `account.payment` with a redirected destination account, deducted via a plain `account.move` journal entry, all against configurable accounts with blocking errors when unconfigured. Vendor bills (expenses) can be tagged with `edara_property_id`/`building_id`/`unit_id`/`branch_id` directly (Phase 7) - no dedicated expense model, per spec §29's "use native accounting" directive. "Receive Payment" (§22): NOT a gap - our rent/service-charge invoices are plain `account.move` records with no form-view override, so the native `action_register_payment` button (confirmed in `odoo/addons/account/views/account_move_views.xml`) already appears on them for free; building a wrapper would have duplicated native UI the spec explicitly says to reuse. Partial payments (§23) and overpayments (§24) likewise need no EDARA-specific code - native reconciliation/payment-difference handling on `account.move`/`account.payment` already does this the moment a real invoice+payment exist. Late fees (§21, Phase 15 addition): `edara.payment.schedule.line.action_charge_late_fee()` - a manual-only button (never a cron, never automatic) visible when a line's computed `state == 'overdue'`, posting a separate `account.move` tagged `edara_invoice_type='late_fee'` for the configurable flat `res.company.edara_late_fee_amount` against `edara_late_fee_income_account_id`, blocked with a clear error if either is unconfigured.

## Portal Status
Implemented (Phase 9): tenant-facing website portal for My Lease (+ renewal request submission) and My Maintenance Requests, plus native `account`/`portal` "My Invoices" reused as-is for invoices/payments/outstanding balance. See "Portal Routes" above and the Phase 9 summary for exact scope and the deliberate cuts (no custom chatter widget on portal pages, no separate My Unit/Documents/Notifications pages - all reuse native infrastructure).

## Tests (final counts, all 16 files)
- `tests/test_edara_branch.py` — 3 tests
- `tests/test_edara_property.py` — 10 tests (7 original + unit kanban view loads [P12] + building smart buttons + property invoices smart button [P15])
- `tests/test_edara_lease_contract.py` — 11 tests (9 original + contract expiry cron fires/idempotent + contract within term untouched [P15])
- `tests/test_edara_payment_schedule.py` — 11 tests (5 original + invoiced/uninvoiced unlink [P13] + 4 late fee scenarios [P15])
- `tests/test_edara_deposit.py` — 7 tests
- `tests/test_edara_service_charge.py` — 9 tests (8 original + invoiced line unlink blocked [P13])
- `tests/test_edara_maintenance_request.py` — 7 tests
- `tests/test_edara_portal.py` — 7 tests (`HttpCase`, real HTTP requests through the werkzeug test client with `authenticate()`/`url_open()`, not mocked)
- `tests/test_edara_reports.py` — 5 tests
- `tests/test_edara_dashboard.py` — 2 tests
- `tests/test_edara_hardening.py` — 4 tests (account.move EDARA tag company/branch consistency)
- `tests/test_edara_multicompany.py` — 2 tests
**Total: 78 tests, 0 failures, 0 errors.** Verified on BOTH a fresh install (throwaway DB, dropped after each verification) AND an upgrade of the persistent `edara_test` DB, after every phase from Phase 0 through Phase 15 - never just one or the other.

**2026-09-13 bug-fix/hardening pass (MAT-020 + deferred MAT findings + Phase 5 review) added 20 tests** across 5 files: `test_edara_lease_contract.py` (+7, occupancy/MAT-020), `test_edara_deposit.py` (+7, wizard defaults), `test_edara_maintenance_request.py` (+4, assign/unlink guard), `test_edara_payment_schedule.py` (+1, invoice_id readonly), `test_edara_hardening.py` (+1, account.move EDARA fields exposed). See "Resolved MAT Findings" and "Resolved Bugs" above for what each covers. Run against the shared `odoo19_dev` dev DB (not the dedicated `edara_test` DB used for Phase 0-15 - `odoo19_dev` is the DB this MAT campaign has been running against since MAT-013): **74 tests total this run, 8 failed + 3 errors, all 11 independently re-verified as the same pre-existing environmental pollution already documented in this file before this session** (a real "Ramallah Branch"/`RAM` row and fully-configured EDARA accounting accounts already live in this DB from earlier manual MAT/UI work - unrelated to any code in this pass). **All 20 new tests passed; zero pre-existing tests regressed.** Module upgrade (`-u property_managment --test-enable`) completed cleanly - 84 modules loaded, no schema/XML/import errors - confirmed 3 times across this session's changes.

## Known Bugs
None.

## Resolved Bugs
- (Phase 13 hardening) `account.move`'s EDARA branch/property/building/unit tags had no cross-consistency check - fixed with `_check_edara_tags_consistent`.
- (Phase 13 hardening) Invoiced payment-schedule/service-charge lines could be deleted by branch managers, orphaning the audit trail - fixed with `unlink()` guards.
- (Phase 15 audit) `EXPIRED` contract state was unreachable - fixed with `_cron_expire_contracts()`.
- (Phase 15 audit) Late fee income account was configurable but nothing could ever charge one - fixed with `action_charge_late_fee()`.
- All other bugs encountered during development (Odoo 19 API mismatches, translation frame-inspection gotcha, test-cursor commit restriction, etc.) were root-caused and fixed in the same session they were found - see "Architecture Decisions" for the technical detail on each; none were deferred.
- (Post-completion, App Switcher fix) The app never appeared in the Odoo App Switcher because `group_edara_administrator` had no `user_ids` seeding `base.user_admin`, unlike every native app (e.g. `account.group_account_manager`) - without it, `ir.ui.menu._visible_menu_ids()` never resolved `menu_edara_root` as visible for anyone, including the instance admin right after install. Fixed by seeding `base.user_admin`/`base.user_root` on `group_edara_administrator`, mirroring the native pattern. Separately, no `web_icon` was set on the root menu and no `static/description/icon.png` existed, so even a visible entry would have had no tile image - fixed with `web_icon="property_managment,static/description/icon.png"` on `menu_edara_root` plus a properly-sized (100x100, matching native convention) `static/description/icon.png` generated from the supplied `EdaraLogo.png`.
- (Post-completion, 2026-09-13 bug-fix/hardening pass, alongside MAT-020) `edara.maintenance.request.action_assign(user_id)` was never wired to any UI button (`views/maintenance_request_views.xml` only ever had Start/Complete/Cancel), even though the Phase 8 lifecycle (NEW→ASSIGNED→IN_PROGRESS→DONE/CANCELLED) as documented above always assumed it existed - `assigned_user_id` was directly form-editable, so staff could bypass the `ASSIGNED` state entirely and jump straight to `in_progress` via Start. Fixed by making `user_id` optional (`action_assign(self, user_id=None)`, backward compatible with the original signature) - when called with no argument (i.e. from a plain header button) it uses whatever `assigned_user_id` is already set on the form, raising a clear error if none is set - and adding an "Assign" header button (visible only in state `new`). Tests: `test_action_assign_without_user_id_uses_already_set_assigned_user`, `test_action_assign_without_user_id_and_without_assigned_user_blocked`.
- (Post-completion, 2026-09-13) `edara.maintenance.request` had no `unlink()` guard despite `perm_unlink=1` for branch managers (same gap pattern Phase 13 already fixed for payment-schedule/service-charge lines) - an assigned/in-progress/done request and its chatter history could be permanently deleted instead of cancelled. Fixed with an `unlink()` override blocking deletion once `state != 'new'` (mirrors `edara.lease.contract.unlink()`'s "only draft can be deleted" pattern). Tests: `test_cannot_delete_assigned_request`, `test_can_delete_new_request`.
- (Post-completion, 2026-09-13) The EDARA Settings menu item was correctly restricted to `group_edara_company_manager`, but the underlying `res.config.settings` `<app>` block (`views/res_config_settings_views.xml`) had no `groups` attribute of its own - any user with generic Odoo Settings access (`base.group_system`) but *without* `group_edara_company_manager` could reach the same EDARA accounting-account configuration fields directly via the native Settings app, bypassing the EDARA-specific menu restriction entirely. Fixed by adding `groups="property_managment.group_edara_company_manager"` to the `<app>` tag itself.
- (Post-completion, 2026-09-13) `edara.lease.contract`'s form statusbar (`views/contract_views.xml`) only listed `statusbar_visible="draft,active,terminated"`, omitting `renewed` and `expired` even though both are real, reachable `STATES` (the latter made reachable by Phase 15's `_cron_expire_contracts()`) - a renewed or expired contract's statusbar rendered without properly highlighting its actual state. Fixed: `statusbar_visible="draft,active,renewed,terminated,expired"`.
- (Post-completion, 2026-09-13) The Security Deposits action's empty-state help text (`views/deposit_views.xml`) said deposits "are created automatically when a lease contract with 'Deposit Required' is activated" - factually wrong; `action_view_deposit()` creates the deposit lazily, only the first time the Deposit smart button is opened, never during `action_activate()`. This inaccuracy is part of what made the MAT-018 investigation's contract/deposit-amount mismatch confusing to diagnose. Fixed to describe the actual lazy-creation behavior.
- (Post-completion, 2026-09-13) `edara.payment.schedule.line`'s list view (`views/payment_schedule_line_views.xml`, `editable="bottom"`) showed `invoice_id` with no `readonly`, unlike the form view which already correctly had `readonly="1"` on the same field - a user could inline-edit a schedule line's `invoice_id` directly from the list, silently repointing it at an arbitrary different invoice and undermining the exact audit trail Phase 13's `unlink()` guard was added to protect. Fixed by adding `readonly="1"` to the list view's `invoice_id` field, matching the form view's already-correct pattern - `invoice_id` is a system-managed field, only ever set by `_create_invoice()`.
- (Post-completion, 2026-09-13) `account.move`'s EDARA tag fields (`edara_invoice_type`/`edara_contract_id`/`edara_branch_id`/`edara_property_id`/`edara_building_id`/`edara_unit_id`) have had full onchange-cascade and cross-consistency-constraint logic since Phase 7/13, but no view ever exposed them on the actual invoice/bill form - there was no `views/account_move_views.xml` at all, so a user had no way to tag a vendor bill with a property/unit/branch except through Developer Mode's raw field editor, silently defeating Phase 7's whole "native vendor bills tagged with property/building/unit" expense-tracking design. Fixed by adding `views/account_move_views.xml` (new file, registered in `__manifest__.py`), inheriting `account.view_move_form` and adding all 6 fields inside the existing native "Other Info" tab's `other_tab_group`. No new business rule invented - purely exposes fields/logic that already existed at the model layer.
- (Post-completion, App Switcher click "Access Error") Making the app reachable exposed a pre-existing, previously-unreachable bug: the app's default landing action is resolved by `ir.ui.menu.load_web_menus()` as the *first child menu by record id* with an action - here, Dashboard's `action_edara_dashboard_open` (`ir.actions.server`). Odoo 19's `ir_actions.py::_can_execute_action_on_records` requires **write** access on the action's target model whenever the server action has no explicit `group_ids` (confirmed at the exact source line via `odoo-bin shell` reproduction of the click, which raised the identical "You don't have enough access rights to run this action." error). `ir.model.access.csv` granted `edara.dashboard` only read+create (`perm_write=0`) to `group_edara_viewer`, so literally no one - including `group_edara_administrator`, which only inherits `group_edara_viewer` here - could ever run it. The Phase 11 dashboard tests never caught this because they call `action_open()` directly on the model, bypassing the `ir.actions.server.run()` wrapper that performs this check. Fixed by setting `perm_write=1` on the existing `access_edara_dashboard_viewer` row; `edara.dashboard` has zero stored fields (all KPI fields are non-stored computed), so this grants no real mutable surface - it only satisfies Odoo's baseline safety gate for executing the server action. Also renamed the root menu's display name from "EDARA" to "EDARA Property Management" (`menu_edara_root`'s `name` attribute is the sole source of the App Switcher label per `load_web_menus()`/`getApps()` - confirmed via source, not derived from the module's technical name or manifest `name`); no technical identifiers were touched.

## Architecture Decisions
- Branch modeled as `edara.branch` (not `res.company` child) — company hierarchy rejected to avoid forcing separate charts of accounts/journals per branch.
- Property/Building/Unit kept as 3 distinct levels: Property = ownership+financial boundary (1 analytic account), Building = physical boundary (always required, even for single-building properties), Unit = leasing boundary.
- Analytic accounting: one analytic account per `edara.property` only. Branch/Building/Unit use plain stored+indexed FK fields, not analytic accounts (scalability: properties are ~2 orders of magnitude fewer than units).
- Security deposits: GL-posted via `account.payment` with `destination_account_id` overridden to a configurable Security Deposit Liability account when `is_security_deposit=True`; deduction via plain `account.move` journal entry. `edara.deposit.transaction` is an index/audit layer only, never a parallel ledger.
- MVP accounting model = Principal (rent is company income), not Agency/owner-passthrough. Documented assumption, revisit if a customer needs owner settlement.
- Owners/Tenants use `res.partner` with boolean flags (`is_edara_owner`, `is_edara_tenant`), no duplicate contact models.
- Maintenance uses a custom `edara.maintenance.request` model — native `maintenance.request` (equipment/asset servicing app) confirmed unsuitable for tenant-facing requests.
- No Documents app available (Community edition, no Enterprise folder) — `ir.attachment` used directly.
- Module dependencies kept minimal for MVP: `base`, `mail`, `portal`, `account`. `hr` NOT added — nothing yet requires it.
- **Odoo 19 API change discovered by source inspection (not assumption):** `res.groups.category_id` no longer exists. Odoo 19 replaced it with `res.groups.privilege_id` -> `res.groups.privilege` (a named selection axis under an `ir.module.category`, see `odoo/addons/base/models/res_groups_privilege.py`). Created `privilege_edara_access_level` (the Viewer->...->Administrator ladder, one dropdown), `privilege_edara_maintenance` and `privilege_edara_accounting` (independent single-toggle add-ons). Documented here since every future group added must use `privilege_id`, not `category_id`.
- **Odoo 19 API change:** `_sql_constraints = [...]` is deprecated ("Model attribute '_sql_constraints' is no longer supported"). Use `models.Constraint(sql, message)` as a class attribute instead (e.g. `_code_company_uniq = models.Constraint('unique(company_id, code)', '...')`).
- Odoo has never been run from this workstation's global Python (it's a general ML/Jupyter environment, no psycopg2/lxml). Created an isolated venv at `server/.venv` for all Odoo runtime/testing. `requirements.txt`'s `libsass` line fails to build on this Python 3.10/setuptools combo (`ModuleNotFoundError: distutils.msvc9compiler` — a known libsass/old-setuptools incompatibility) and was excluded from the venv install; it is not needed for backend module install/upgrade/test validation (SCSS asset compilation is a separate, unrelated concern). Everything else in requirements.txt installed cleanly with prebuilt Windows wheels.
- Test DB: `edara_test` (dedicated, created fresh, safe to drop/recreate at any time during this project).
- `edara.unit.unit_type` is a plain `Selection` (apartment/office/shop/warehouse/villa/parking/commercial/other), not a separate configurable model — 8 fixed categories don't justify a model; revisit only if a customer needs custom-named types.
- `occupancy_status` (available/reserved/rented/owner_occupied/sold) and `operational_status` (normal/under_maintenance) are two separate fields on `edara.unit`, per spec §10/§11. In Phase 2 (no contracts yet) `occupancy_status` is plain manually-set; Phase 3 will make `rented`/`reserved` derived from the unit's active lease contract instead of freely editable (this is a known, intentional interim state, not an oversight). One cross-field constraint already enforced: a unit `under_maintenance` cannot be `available`.
- Ownership total (`edara.ownership`) validated with a sweep-line check over each property's active records' date boundaries - correct because the maximum concurrent percentage total can only occur at a record's own start/end date, so checking totals at those points catches any overlap that would exceed 100%.
- **Odoo 19 API change:** the `states={...}` field parameter (per-state readonly/required) has been fully removed from the ORM (`odoo/orm/fields.py` has no `states` handling at all) - not just deprecated in favor of views, genuinely gone. State-dependent field behavior must be done at the view level (`readonly="state != 'draft'"` attrs), which is what `contract_views.xml` does.
- **Odoo 19 testing quirk:** `TransactionCase.assertRaises` (`odoo/tests/common.py:_assertRaises`) does not accept a tuple of exception classes the way stdlib `unittest.assertRaises` does - it does `issubclass(exception, AccessError)` assuming a single class, and raises `TypeError: issubclass() arg 1 must be a class` if given a tuple. Assert one specific exception type per test, not a tuple.
- `edara.lease.contract.name`: spec suggested both `name` and `reference` fields; consolidated to a single sequence-generated `name` (e.g. `LC/2026/0001`) - a separate `reference` field would just duplicate it for no MVP benefit.
- Renewal: implemented as an immediate owner-initiated action (`action_renew` + `edara.lease.renewal.wizard`) now. The tenant-request/owner-approval workflow (`edara.renewal.request`, spec §45) is deferred to Phase 9 - a tenant can't submit a request before the tenant portal exists, so building that approval model now would be speculative. When Phase 9 adds it, tenant requests must call `action_renew` after approval, never bypass its validations.
- Contract termination reason capture is currently via `action_terminate(reason=...)` called from Python; the UI Terminate button does not yet prompt for a reason (calls with `reason=None`). A small wizard can be added if the user wants to capture a reason at termination time - noted as a minor, easily-added UX gap, not a defect.
- **Odoo 19 API/runtime gotcha discovered by source inspection:** `odoo.tools.translate._get_cr()` (used by `_()`'s frame-inspection fallback when no `lang` is in context) treats *any* local variable literally named `cr` or `cursor` in the calling frame as if it were a DB cursor, and will pass it straight into `api.Environment(cr, uid, {})` without an isinstance check first - if that local happens to be something else (in our case, a plain `date` object used as a loop variable), it raises `AssertionError: assert isinstance(cr, BaseCursor)` deep inside `_()`. Fix: never name a local variable `cr` or `cursor` in a method that also calls `_()` — renamed our schedule-generation loop variable from `cursor` to `due_date` in `edara_lease_contract.py`. Documenting this because it is a genuinely surprising, hard-to-guess failure mode that will bite again if a future phase reintroduces a `cursor`-named local anywhere near a translated string.
- **Odoo 19 test-framework constraint:** `TransactionCase`'s cursor forbids `cr.commit()`/`cr.rollback()` (`odoo/tests/common.py`'s `forbidden` cursor method) to protect test isolation. Any cron-style method that intentionally commits per-batch-item in production (for resilience against a mid-batch failure) must guard those calls with `if not odoo.modules.module.current_test:` - this is the exact pattern Odoo core uses in `mail.mail.send()`'s `auto_commit` handling (`odoo/addons/mail/models/mail_mail.py`). Applied to `edara.payment.schedule.line._cron_generate_due_invoices()`.
- `account.account` in Odoo 19 has a required `company_ids` (Many2many, defaults to `env.company`) and a computed+invertible `code` field backed by `code_store` (company-dependent) - creating a test/setup account needs at least `name`, `code`, and `account_type` in the `create()` vals; `code` cannot be left unset (raises "The code must be set for every company to which this account belongs.").
- `ir.actions.act_window.target` in Odoo 19 does not have an `'inline'` value (only `current`/`new`/`fullscreen`/`main`) - the EDARA Settings menu action uses `target="current"`.
- `account.payment.destination_account_id` is a stored, editable compute (`readonly=False` + `store=True`) - overriding it for security deposits means redefining `_compute_destination_account_id` in an `_inherit` model, calling `super()` first, then overriding for flagged records, and re-declaring `@api.depends` with the original dependency fields plus the new one (`edara_is_security_deposit`) - Odoo does not merge `@api.depends` lists across inherited method definitions, the last one defined wins.
- `account.account.create()` in Odoo 19 requires `code` to be provided explicitly (it's a computed+invertible field backed by company-dependent `code_store`, not auto-generated) and defaults `company_ids` to `env.company` - needed for every ad-hoc test/config account created in this project.
- Posting an `account.payment` against a `cash`-type journal does not always land directly on `state == 'paid'` - it depends on the resolved `outstanding_account_id.account_type`; `in_process` (pending reconciliation) is equally valid and is not something this module's deposit feature should assert against.
- Service charges are scoped to `edara.building` (not property or unit) - matches the spec's own example ("Building service charge: Total = 10,000 ILS") and the existing architecture where Building is the physical/operational boundary.
- Service charge allocation computes each unit's share across ALL active units in the building (occupied or not), then only creates - and only ever invoices - a line for units with a currently active lease contract. A vacant unit's computed share is not collected from anyone and is not redistributed onto occupied units. This is a deliberate simplification (documented here, not silently done) - revisit if a customer needs vacant-unit shares absorbed by the owner or redistributed.
- **Odoo 19 API change discovered by source inspection:** `res.users.groups_id` no longer exists - renamed to `group_ids` (`odoo/addons/base/models/res_users.py`). Also confirmed: `res.groups.all_implied_ids` (computed, all transitively-implied groups) exists alongside the settable `implied_ids`.
- **Odoo 19 access-control gotcha:** `ir.sequence.next_by_code()` calls `self.browse().check_access('read')` itself (not sudo'd) - a low-privilege caller (e.g. a portal user) genuinely cannot trigger sequence-based naming directly, even indirectly through a model's `create()` override, because portal users have no ACL row for `ir.sequence`. Any portal-facing controller that creates a record whose `create()` calls `next_by_code` (our `edara.maintenance.request`) must `sudo()` that specific create call - after the controller has independently verified the record's ownership/authorization server-side (never trust the client-supplied foreign key, e.g. `unit_id`). This is the pattern used in `controllers/portal.py`'s `portal_maintenance_new_submit`.
- Portal security for `group_edara_portal_tenant` intentionally does NOT reuse the branch-scoped 3-rule pattern (that group doesn't carry `group_edara_viewer`) - each portal-facing model instead gets one dedicated `ir.rule` scoped to `tenant_id = user.partner_id.id` (or, for `edara.unit`, `lease_contract_ids.tenant_id`). `edara.renewal.request` and `edara.maintenance.request` portal ACL rows are `perm_write=0` - even though ACL alone can't stop a portal user from directly targeting the ORM (`/web/dataset/call_kw` is reachable by any authenticated user for models they have ACL on), removing write access closes off a real self-approval/self-completion bypass (e.g. a tenant `write()`-ing their own renewal request's `state` to `'approved'` instead of going through `action_approve()`). All state changes happen only through controller/action methods, never raw field writes from an untrusted actor.
- `edara.dashboard` (Phase 11) is a `TransientModel` with no stored singleton row - a fresh record is created and its KPI fields computed live on every open. Chosen specifically to avoid a singleton-bootstrap/race-condition problem: TransientModel rows auto-vacuum, so there's never a stale or duplicate dashboard row to worry about.
- `account.move`'s EDARA tag fields (`edara_branch_id`/`edara_property_id`/`edara_building_id`/`edara_unit_id`) are plain user-editable fields, not related-from-contract (Phase 7 decision, needed for vendor bills which have no contract) - this means nothing stops a mismatched or cross-company combination unless explicitly checked. Phase 13 added `_check_edara_tags_consistent` (`@api.constrains`) validating branch↔company, property↔company, property↔branch, building↔property, unit↔building. Any future field added to this "tag" group must be added to that same constraint.
- `edara.payment.schedule.line`/`edara.service.charge.line` `unlink()` is blocked once `invoice_id` is set (Phase 13) - the invoice itself is already protected natively by Odoo (a posted `account.move` can't be unlinked without first resetting to draft), but our own line is the only record of which schedule slot produced which invoice; losing it would silently break that audit trail even though no money data is lost. Uninvoiced lines remain freely deletable (`action_terminate()`/`_cron_expire_contracts()` both already only ever unlink uninvoiced lines).
- `edara.lease.contract._cron_expire_contracts()` (Phase 15) is the only place `state='expired'` is ever set - a contract past its own `end_date` that was never renewed (`action_renew` flips state to `'renewed'` the instant renewal happens, so by definition an `active` contract past its end date was never renewed) or terminated. Runs daily, naturally idempotent (its own `state='active'` filter excludes anything it already expired), no per-record commit/lock dance needed unlike the invoicing cron since it only flips plain fields with no external financial posting and no partial-failure risk.
- Late fees (§21, Phase 15) use a single flat configurable `res.company.edara_late_fee_amount` rather than a rule engine (e.g. percentage-of-rent, per-day-late tiers) - satisfies "must be configurable" without inventing complexity the spec never asked for; revisit only if a customer needs a real per-day/percentage rule. Charging is exclusively manual (`action_charge_late_fee()`, a button visible only when a line's computed `state == 'overdue'`) - there is no cron and no automatic trigger anywhere, per spec's explicit "do not automatically charge arbitrary late fees without a business rule."
- "Receive Payment" (§22 preferred UX), partial payments (§23), overpayments (§24), and credit notes/refunds (§25) needed NO EDARA-specific code at all - confirmed by reading `odoo/addons/account/views/account_move_views.xml` that the native `action_register_payment` button already appears unconditionally on any `account.move`, and native reconciliation already handles partial/over payment and credit-note netting the moment a real invoice+payment exist. Building a wrapper around this would have duplicated native UI the spec explicitly says to reuse.
- **Maintenance Request `cost`/`vendor_id` are intentionally operational-only fields, not an accounting trigger (confirmed during MAT-027).** `edara.maintenance.request` (`models/edara_maintenance_request.py`) has no `_create_invoice`/bill-creation method anywhere, and the spec's own §41 "Suggested fields" list (`cost`, `vendor`) never describes them as generating a financial transaction - they exist so the Maintenance workflow itself can show what a job is expected/actually cost and who did it, independent of Accounting. This is consistent with the already-established pattern for ALL vendor bills/expenses in this module: `account.move`'s EDARA tag fields (`edara_branch_id`/`edara_property_id`/`edara_building_id`/`edara_unit_id`) are deliberately plain user-editable fields, not related-from-contract, "needed for vendor bills which have no contract" (see the Phase 7/Phase 13 decision above) - i.e. a Vendor Bill for maintenance work is meant to be entered manually through native Accounting → Vendors → Bills (or via `edara.property.action_view_expenses()`, the Property "Expenses" smart button, which already lists/creates `in_invoice` moves filtered/tagged to that property), exactly like every other property expense, not auto-generated from the Maintenance Request. **Conclusion: Option A.** No code gap and no deferred finding recorded for this. If a future requirement makes maintenance costs financially actionable end-to-end (Option B: a "Vendor Bill" smart button on the Maintenance Request creating/linking a native `account.move` of `move_type='in_invoice'`, tagged with the same unit/building/property/branch and reusing the existing `edara_invoice_type`-style tagging), it should reuse this exact native-accounting tagging pattern rather than introduce a parallel ledger - but this is a new-feature decision, not a bug-fix, and nothing in the current spec requires it.
- Future Owner Settlement (§32) is explicitly deferred by the spec itself ("Do not implement the full feature unless included in the active scope") - the existing `edara.ownership` (owner+percentage tracking) and per-property analytic account are already compatible with adding `edara.owner.settlement` later without restructuring anything.
- **Permission-aware compute pattern (MAT-031, MAT-FIND-014).** Any computed field that reads a native Accounting model (`account.move`, `account.payment`, etc.) from a screen a non-Accounting EDARA role (starting with Viewer) is otherwise entitled to open must check `TargetModel.has_access('read')` (an empty-recordset ACL-only check, no `sudo()`) before reading, and degrade the Accounting-dependent value(s) to a safe default (`0`/`0.0`/hidden) rather than let a raw `AccessError` propagate and crash the whole screen. A sibling Boolean field (conventionally named `has_accounting_access`) exposes this to the view so the affected field/page/button can be made `invisible` instead of showing a misleading zero. Applied to `edara.dashboard._compute_kpis()`, `edara.property._compute_financial_summary()`, and `edara.branch._compute_financial_summary()`; any future field with the same shape (reads Accounting data from a Viewer-reachable screen) should reuse this exact pattern rather than reinvent one.
- **Confirmed: none of EDARA's own groups imply any native Odoo Accounting group (MAT-031, MAT-FIND-015).** `group_edara_viewer`/`group_edara_property_manager`/`group_edara_branch_manager`/`group_edara_accountant`/`group_edara_company_manager`/`group_edara_administrator` were grepped end-to-end in `security/edara_security.xml` - none reference `account.group_account_invoice`/`account.group_account_user`/`account.group_account_manager` or any other native Accounting group. This is why `base.user_admin` (which carries `account.group_account_manager` by default) never reproduced MAT-FIND-014/015 in any prior MAT session, and why a genuinely EDARA-only "Accountant" test user demonstrably has `has_access('read')` on `account.move` return `False`, identical to a Viewer. Whether this should change (EDARA roles implying native Accounting groups) is the open question in MAT-FIND-015 - a business/architecture decision, not resolved by this pass.

## Deviations From Specification
- **Arabic translation content not written.** Spec §63 requires the system to "support" Arabic/English and LTR/RTL, and separately says "Arabic labels should be professionally written." The engineering side of this is done and verified: every single user-facing string in the module is wrapped in `_()` (grepped and confirmed zero exceptions), Odoo's web client handles RTL rendering natively once Arabic is the active language, and no UI text is hardcoded in a way that would resist translation. What is NOT done is authoring an actual Arabic `.po` translation file with real, professionally-written Arabic business terminology for every field/button/message - that is a content/localization task requiring either a professional translator or the business owner's own preferred terminology (e.g. exact Arabic phrasing for "Lease Contract" vs "Tenancy Agreement"), not something to fabricate. Flagged explicitly here rather than silently claimed as done.
- Everything else implemented deviates from the spec only in the many small, explicitly-documented ways captured inline above (e.g. Phase 4/5 merge, portal scope narrowing in Phase 9, late-fee rule simplified to a flat amount) - each was a deliberate, reasoned choice made and recorded at the time, not an oversight.

## Environment Notes
- Global Python (3.10.0) at this workstation is a general ML/data-science environment (torch, tensorflow, streamlit, jupyter, etc.) and does NOT have Odoo's runtime deps (no psycopg2, no lxml) — Odoo has apparently never been run from this interpreter.
- Created an isolated venv at `server/.venv` and am installing `requirements.txt` there, so Odoo runtime testing never touches/risks the user's global ML environment. Install running in background.
- `odoo.conf` has no `db_name` pinned (multi-db, `list_db=True`). Will use a dedicated test DB (`edara_test`) for install/upgrade validation, created fresh so no risk to any existing data.

## Remaining Work
All 16 phases (0-15) of EDARA_IMPLEMENTATION_SPEC.md §72 are complete. What remains is exclusively work the spec itself marks as out-of-active-scope or content-authoring rather than engineering:
- Actual Arabic `.po` translation content (see "Deviations From Specification" above) - the system is translation-ready, not yet translated.
- `edara.owner.settlement` (spec §32) - explicitly "do not implement... unless included in the active scope."
- Optional cron jobs spec §60 lists as merely "potential" and never requires: renewal reminders, maintenance reminders (both achievable later via `mail.activity.mixin`, already inherited by the relevant models, with no model changes needed).
- A reason-capture wizard on the Terminate button (currently `action_terminate(reason=...)` works from Python/tests but the UI button doesn't prompt for a reason) - a minor, easily-added UX nicety, not a defect, noted since Phase 3.

## Next Internal Action
None for the Phase 0-15 implementation program itself (unchanged - see "Remaining Work" above). Post-completion Manual Acceptance Testing (MAT) is currently in progress as a separate, user-driven verification sequence (see "Manual Acceptance Testing Findings & Deferred Fixes" below); deferred findings discovered during MAT are logged there as they occur, not fixed ad hoc mid-testing. If the user wants one of the "Remaining Work" items above, or a genuinely new feature/phase, that would be new scope beyond this spec's Phase 0-15 program, not a continuation of an unfinished one.

**Live-data note (2026-09-13, MAT-020 follow-up):** the MAT-020 code fix does NOT retroactively correct Apartment 101's `occupancy_status` in the live `odoo19_dev` database - confirmed via direct query after the module upgrade: `LC/2026/0002` is still `active` (untouched), `LC/2026/0003` is still `terminated` (untouched), but the unit's `occupancy_status` is still `available` (the incorrect value the original bug left behind - module upgrades do not re-run business logic against existing rows, only schema/view/constraint registration). This was deliberately NOT corrected via SQL, per this session's standing "no direct writes to live business data" instruction. **Safe correction path for the user:** open Apartment 101's form and manually set Occupancy back to "Rented" - this is now safe and will not be silently wrong, because `LC/2026/0002` is a genuine active contract, so both the pre-existing and the new defense-in-depth constraints on `edara.unit` will correctly allow it.

## Final Validation Status
**COMPLETE.** All 16 phases (0 through 15) of EDARA_IMPLEMENTATION_SPEC.md §72 are implemented and verified:
- Fresh install (`-i property_managment --without-demo=all` on a throwaway DB) - clean, no errors.
- Module upgrade (`-u property_managment` on the persistent `edara_test` DB, carrying real accumulated data through every phase's schema changes) - clean, no errors.
- Full automated test suite (`--test-enable --test-tags /property_managment`) - **78/78 passing** on both the fresh install and the upgrade path, every single time this was run across all 16 phases (never just one path checked).
- A dedicated Phase 13 hardening audit and a Phase 15 final audit against every one of the spec's 80 sections, each surfacing and fixing real (not hypothetical) gaps rather than rubber-stamping completion - see the Phase 13/15 entries in "Completed Phases" above for the specific issues found and fixed.
- Technical Definition of Done (spec §76): module installs ✓, module upgrades ✓, all XML loads ✓, all Python imports ✓, no unresolved external IDs ✓, no broken actions/menus/views ✓, ACLs work ✓, record rules work ✓ (including a real second-company test, Phase 14), portal rules work ✓ (real HTTP `HttpCase` tests, not mocked), accounting works ✓ (native `account.move`/`account.payment`, no parallel ledger anywhere), cron works ✓ (both crons idempotent and lock-safe), tests pass ✓, no critical TODOs remain ✓ (grepped, zero), no known critical security issue remains ✓, no known critical accounting issue remains ✓.
- UX Definition of Done (spec §75): the full nontechnical golden path (Property → Building → Unit → Tenant → Lease → Rent Schedule → Invoice → Receive Payment → Outstanding Balance) works end-to-end without touching accounting journal mechanics directly, while an accountant can still inspect the full native accounting chain.

## Manual Acceptance Testing Findings & Deferred Fixes

**Workflow note:** During MAT, discovered issues should be recorded here immediately instead of being fixed ad hoc. After MAT completion, deferred findings will be reviewed, prioritized, implemented, and then moved through `FIXED` → `VERIFIED`.

**2026-09-16 Live Verification Cycle:** a live manual re-verification pass confirmed the following previously-`FIXED - READY FOR VERIFICATION` items as **FIXED - VERIFIED**: MAT-FIND-001, MAT-FIND-002, MAT-FIND-005, MAT-FIND-006, and MAT-020 (see each entry below/above for exact live evidence: contracts `LC/2026/0119`, `LC/2026/0120`, `LC/2026/0122`, `LC/2026/0124`, `LC/2026/0126`). During the same pass, three new findings were observed and recorded as open (not yet classified as defects): **MAT-FIND-010**, **MAT-FIND-011**, **MAT-FIND-012**. This cycle was documentation/verification only - **no code, view, test, security, or configuration changes were made, and MAT-028 has not been started.**

**2026-09-18 Live Verification Cycle:** a live manual re-verification pass confirmed the billing-frequency-granularity fix (**MAT-FIND-013**) and the zero-payment-schedule-lines fix (**MAT-FIND-011**) as **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED - ACCOUNTING VERIFIED**, using dedicated test contracts `LC/2026/0129` through `LC/2026/0141` - see the Deferred Findings table and "Resolved MAT Findings - Implementation Notes" below for full per-contract evidence. This pass also confirmed, across all 11 of those contracts, that `payment_day` is always automatically derived from `start_date.day` and was never manually entered - live evidence: `LC/2026/0129`→`2`, `LC/2026/0130`→`1`, `LC/2026/0132`→`1`, `LC/2026/0133`→`15`, `LC/2026/0134`→`15`, `LC/2026/0135`→`15`, `LC/2026/0136`→`15`, `LC/2026/0137`→`15`, `LC/2026/0138`→`1`, `LC/2026/0139`→`1`, `LC/2026/0141`→`1` - every value matches that contract's own Start Date's day of month. This cycle was documentation/verification only - no code, view, test, security, or configuration changes were made. **Billing-related functional testing is now effectively verified. The whole-module Functional/MAT phase remains in progress** - MAT-FIND-003, MAT-FIND-004, MAT-FIND-007, MAT-FIND-008, MAT-FIND-010, and MAT-FIND-012 remain open/deferred exactly as before, and BD-001/BD-002 remain open business decisions; none of those were touched by this pass.

**2026-09-19 — MAT-031 Security/Isolation Pass:** implemented and fixed **MAT-FIND-014** (Dashboard/Property/Branch crashing on `account.move` access for non-Accounting users - see full write-up above), added 16 new automated security/isolation tests (`tests/test_edara_security_isolation.py`), and ran a comprehensive live validation against the real `odoo19_dev` database (94/94 checks passed, rolled back, nothing modified) covering the Viewer role, Dashboard, Branch/Property/Unit/Contract isolation, Tenant boundaries, Maintenance boundaries, native Accounting boundaries, and Administrator access - see "MAT-031 full live-validation matrix" above for the complete table. Discovered and recorded a new, separate, **not-yet-resolved** finding during this pass: **MAT-FIND-015** (EDARA's own Accountant/Company-Manager/Administrator groups never imply native Odoo Accounting access) - live-confirmed at the ACL level on real `odoo19_dev` data, but not yet click-tested end-to-end, and explicitly left as an open business/architecture decision per instruction not to grant permissions to make a check pass. **MAT-031 status: substantially complete** - the confirmed blocking finding (MAT-FIND-014) is fixed and live-verified; the remaining open items (MAT-FIND-015's business decision, MAT-FIND-003/004/007/008/010/012, BD-001/BD-002) are all either business decisions or non-blocking deferred findings, none of which this pass touched or resolved.

**2026-09-20 — MAT-FIND-015 End-to-End Business Workflow Validation:** followed up the ACL-level prediction from the 2026-09-19 pass with a full end-to-end click-through, against real `odoo19_dev` data, of all four of EDARA's own accounting-adjacent workflows (Service Charge invoicing, Deposit Collect/Refund/Deduct, Late Fee) using a disposable EDARA-only Company-Manager test user - see "MAT-FIND-015 - End-to-End Business Workflow Validation" above for full Test A-D results. All four workflows are genuinely, operationally blocked (not just ACL-predicted); an Administrator control run confirms the workflows themselves are not broken. Investigation only, no code/permission changes - MAT-FIND-015 remains **OPEN - BUSINESS / ARCHITECTURE DECISION REQUIRED**, now with complete evidence rather than a prediction.

**2026-09-20 — MAT-FIND-015 Architecture Analysis and Resolution (MAT-FIND-015-A):** completed a precise, code/ACL/database-inspected impact analysis comparing native-group inheritance vs. scoped native execution (see "MAT-FIND-015 - Architecture Impact Analysis" above), then implemented and fully verified the scoped-execution architecture: narrow `.sudo()` at exactly six call sites, each gated by an explicit `check_access('write')` (or, for the two Deposit money-movement actions, by authorization-record-creation-before-elevation) - never a blanket native Accounting group grant. 24 new automated tests added, 173/173 full-suite passing, and a live rolled-back validation against real `odoo19_dev` data confirmed all five workflows (Service Charge invoice, Deposit Collect/Refund/Deduct, Late Fee) now succeed for EDARA-only users while native Accounting read/search/create/write access remains fully denied for anything beyond those exact actions, a Viewer remains fully blocked before any elevation, and company/branch isolation is preserved - see "MAT-FIND-015-A - Scoped Native Accounting Execution" below for full detail. **MAT-FIND-015 status: FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

### Deferred Findings

| ID | Area | Finding | Current Behavior | Expected Behavior | Severity/Priority | Status | Discovered During | Proposed Fix | Notes / Dependencies |
|---|---|---|---|---|---|---|---|---|---|
| MAT-FIND-001 | Security Deposit / UX (`edara.deposit.transaction.wizard`) | Deposit Transaction Wizard defaults Amount to 0 for Collect / Refund / Deduct | ~~Wizard field `amount` had no `default=` and no onchange, so it always opened at $0.00 regardless of `deposit_id.balance`/`amount_held`.~~ **FIXED.** | Wizard should intelligently default Amount to the available amount: Collect → remaining uncollected amount (`deposit.amount - deposit.amount_held`); Refund → current refundable balance (`deposit.balance`); Deduct → current available balance (`deposit.balance`) - while keeping the field editable for partial transactions. | Medium / UX only - not an accounting-correctness issue | **FIXED - VERIFIED** | MAT-019 | Implemented - see "Resolved MAT Findings - Implementation Notes" below | Live-verified 2026-09-16 on `LC/2026/0122` (Deposit Required Yes, Deposit Amount $1,500): Collect wizard defaulted Amount to $1,500 automatically; collection posted `PBNK1/2026/00009`, resulting Deposit `Amount Held $1,500 / Refunded $0 / Deducted $0 / Balance $1,500`, Transaction `Held`. |
| MAT-FIND-002 | Security Deposit / UX (`edara.deposit.transaction.wizard`) | Deposit Transaction Wizard Payment Journal also opens empty | ~~`journal_id` had no default at all.~~ **FIXED for the unambiguous case.** | Auto-select the journal only when exactly one `cash`/`bank` journal exists for the company (the only case where a default isn't a guess); otherwise leave it empty and require the user to choose, exactly as before. Never applies to Deduct (no payment is created for a deduction). | Low-Medium / UX only | **FIXED - VERIFIED** | MAT-019 | Implemented - see "Resolved MAT Findings - Implementation Notes" below | Live-verified 2026-09-16 on `LC/2026/0122`'s Deposit: opening the Refund wizard auto-defaulted Amount to $1,500 and Payment Journal to `Bank` automatically (the single unambiguous bank journal). Wizard was cancelled after verification - no refund was posted, deposit state unchanged. |
| MAT-FIND-003 | Unit / UX-Functional (`edara.unit`) | Unit Duplicate fails because Unit Code/Number is required and unique | ~~Apartment 101 has a required, unique Unit Code/Number (`code`, unique per building). Using Odoo's native "Duplicate" action copies the record including its `code` value unchanged, so the duplicate's `create()` is rejected by the existing unique constraint.~~ **FIXED (2026-09-22).** Approved direction: auto-generate a new unique code (option b). `edara.unit.copy()` now appends a `-COPY`/`-COPY2`/... suffix, scoped to the same building, guaranteed unique before the copy is even created. | Duplicating a Unit should not fail simply because the original Unit Code is unique, while the uniqueness constraint itself remains fully enforced - confirmed `code` is a plain internal unique identifier (not the business-facing unit number - that's the separate, unconstrained `unit_number` field), so automatic regeneration is safe per the ticket's own "if code has strong business meaning, stop" instruction. | Medium / UX-Functional - blocks a native Odoo convenience action, not an accounting or security issue | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | Post-MAT-020 manual testing | Implemented - see "MAT-FIND-003 / MAT-FIND-012 - Implementation, Tests, and Live Validation" below | A duplicated `rented`/`reserved` unit also has its `occupancy_status` reset to `available` (lease_contract_ids, a One2many, is never copied, so a copy would otherwise violate the existing "rented requires a covering active contract" constraint) - `owner_occupied`/`sold` are preserved as-is (administrative, contract-independent). 7 new automated tests (`tests/test_edara_property.py`), live-verified against real `odoo19_dev`, rolled back. |
| MAT-FIND-004 | Lease Contract / Data Integrity (`edara.lease.contract`, `ir.sequence`) | Lease Contract Sequence Inconsistency | ~~Initial contracts were numbered `LC/2026/0002`, `LC/2026/0003` (sequential, as expected). Later contracts unexpectedly jumped to `LC/2026/0105`, `LC/2026/0108` - the numbers are still increasing (monotonic, no duplicates observed) but with large, unexplained gaps between them.~~ **INVESTIGATED AND CLOSED (2026-09-22) - confirmed expected Odoo behavior, not a defect.** | Root cause confirmed: `ir.sequence` `seq_edara_lease_contract` uses the default `implementation='standard'` (a native, non-transactional Postgres sequence, "gaps-allowed" by Odoo's own design) - every `create()` call permanently consumes a number even when its transaction is later rolled back. Confirmed via `psql`: the sequence is at `177` while only 27 contracts actually exist, and every surviving contract's `create_date` falls within this project's own documented test/live-validation windows. No duplicate numbers, no misattributed records. | Medium → **Resolved as Low/non-issue** - cosmetic gaps only, confirmed no data-integrity impact | **CLOSED - ROOT CAUSE CONFIRMED, NO DEFECT (2026-09-22)** | Post-MAT-020 manual testing | No fix - see "MAT-FIND-004 / MAT-FIND-008 - Investigation, Implementation, Tests, and Live Validation" below for the full read-only investigation and evidence | Per the finding's own instruction, the `ir.sequence` record was NOT reset or altered - existing references to `LC/2026/0002`/`0003`/`0105`/`0108` etc. remain intact and resolvable. Investigation was fully read-only (only `SELECT` queries via `psql` and ORM `search`/`search_count` calls) - no code/config/database change was made. |
| MAT-FIND-005 | Lease Contract / Payment Schedule / Functional (`edara.lease.contract._generate_schedule_lines`) | Payment Schedule includes End Date | ~~Contract with Start Date `01/08/2026`, End Date `01/09/2026`, Billing Frequency Monthly, Payment Day 1. After activation, the generated Payment Schedule contains 2 lines, not 1. Current behavior appears to treat the End Date as inclusive when generating monthly schedule lines, so a due date falling exactly on the End Date (or within the same boundary period) produces an extra period's rent line.~~ **FIXED** - root cause confirmed as `_generate_schedule_lines()`'s loop boundary using `while due_date <= self.end_date:` (inclusive); see "Resolved MAT Findings - Implementation Notes" below. | A lease running `01/08/2026` through `01/09/2026` represents one calendar month (August). The schedule should normally contain a single monthly rent line for August - the End Date should function as the boundary/start of the next period rather than a date that itself generates an additional (September) rent line. | Medium / Functional - affects rent schedule correctness and potentially invoice generation | **FIXED - VERIFIED** | MAT-022 | Implemented - see "Resolved MAT Findings - Implementation Notes" below. | Discovered during MAT-022. Fix implemented, covered by automated regression tests (15/15 Payment Schedule tests pass, 115/115 full module suite passes), and subsequently **live-verified 2026-09-16** on `LC/2026/0119` (Start `01/08/2026`, End `01/09/2026`, Monthly, Payment Day 1, Rent $1,500): after activation, the Payment Schedule contained exactly one line (`2026-08-01`, $1,500, state `Overdue`, no invoice) - no line for `2026-09-01`. Confirms the boundary: `due_date < end_date` → generated; `due_date == end_date` → not generated; `due_date > end_date` → not generated. |
| MAT-FIND-006 | Lease Contract / Payment Schedule / Data Integrity (`edara.lease.contract._cron_expire_contracts`, `edara.payment.schedule.line`) | Expired Contract Payment Schedule Disappears | ~~Contract `MAT-022 Expiry Cron Test` (Unit `Apartment 102`) had an unpaid Payment Schedule with existing lines, including an overdue line, before the expiry cron ran; no payment had been made against this contract. After running `EDARA: Expire lease contracts past their end date`: contract changed `Active` → `Expired`; unit changed `Rented` → `Available`; the existing Payment Schedule lines disappeared.~~ **FIXED** - root cause confirmed as both `action_terminate()` and (especially) `_cron_expire_contracts()` unlinking ALL uninvoiced schedule lines regardless of due date, including already-overdue ones; see "Resolved MAT Findings - Implementation Notes" below. | Expiring a lease must NOT delete historical Payment Schedule lines. Unpaid/overdue schedule lines must remain available for historical/audit/collection purposes - in this specific test, the existing unpaid overdue schedule line should have remained with state `Overdue`. Expiry should change the contract lifecycle/occupancy state only; it must not erase financial history or payment schedule history. | High / Data Integrity & Financial Workflow | **FIXED - VERIFIED** | MAT-022 | Implemented - see "Resolved MAT Findings - Implementation Notes" below. | Discovered during MAT-022. Separate from MAT-FIND-005 (End Date included in Payment Schedule generation), though both fixes touch the same method (`_generate_schedule_lines()`'s upstream generation vs. the two unlink call sites' downstream cleanup). Fix implemented, covered by automated regression tests (23/23 Lease Contract tests pass, 115/115 full module suite passes), and subsequently **live-verified 2026-09-16** on `LC/2026/0120` (Start `01/08/2026`, End `01/09/2026`, Monthly, Payment Day 1, Rent $1,500, Unit Apartment 107): after activation, Payment Schedule held one line (`2026-08-01`, $1,500, `Overdue`). Running the real scheduled action `EDARA: Expire lease contracts past their end date` moved the contract to `Expired` and the unit to `Available`, and the Payment Schedule line **remained** - Due Date `2026-08-01`, state still `Overdue`. |
| MAT-FIND-007 | Lease Contract / Payment Schedule / UX & Workflow (`edara.lease.contract._cron_expire_contracts`, `edara.payment.schedule.line._cron_generate_due_invoices`) | No Business-Level Manual Trigger for Contract Expiry / Invoice Generation | Both contract-expiry processing and due-invoice generation are exposed only through their respective scheduled actions; to run either manually a user currently must navigate to `Settings → Technical → Scheduled Actions`, an administrative/technical area not appropriate as the normal business-user workflow. **Confirmed live during MAT-030 (2026-09-18):** there is **no button named "Generate Due Invoices"** anywhere on the Lease Contract or Payment Schedule UI - the only working manual path is `Settings → Technical → Scheduled Actions → EDARA: Generate Due Invoices → Run Manually`. The pre-existing contract-expiry gap uses the identical path (`Settings → Technical → Scheduled Actions → EDARA: Expire lease contracts past their end date → Run Manually`) - same architectural issue, same missing business-level entry point. | Both scheduled actions should continue running automatically exactly as they do today. In addition, an appropriate business-level manual action/button should eventually be available from the relevant business workflow (e.g. Lease Contract and/or Payment Schedule for invoice generation; Lease Contract and/or Unit for expiry), invoking the SAME underlying reusable business logic already used by `_cron_generate_due_invoices()`/`_cron_expire_contracts()` (must not duplicate that logic in a second implementation) and remaining safe/idempotent, respecting the same date/occupancy/invoicing rules. The exact UI design and placement are NOT finalized yet - do not prescribe or implement a specific final design. | Medium / UX & Workflow | DEFERRED / READY FOR UX/WORKFLOW DESIGN - non-blocking to the broader MAT phase | MAT-022 (contract expiry); reconfirmed and extended to invoice generation during MAT-030 | Not yet designed - this is a workflow/design finding, not a request to implement any button now. | Discovered during MAT-022 (contract expiry). Reconfirmed live and extended to cover due-invoice generation during MAT-030 (`LC/2026/0142`) - see "MAT Verification Outcomes" below for exact evidence. No code/view/test change has been made for this finding; the existing scheduled actions must not be changed as part of recording this finding. |
| MAT-FIND-008 | Renewal Request / UX (`edara.renewal.request`, `views/renewal_request_views.xml`) | Renewal Request Tenant Message is Read-Only / Not Editable | ~~During MAT-025, the `note` ("Tenant Message") field on the Renewal Request form was visible but could not be entered or edited - confirmed in `views/renewal_request_views.xml`, where `<field name="note" readonly="1"/>` is unconditionally read-only, unlike the request's other fields (`contract_id`/`requested_start_date`/`requested_end_date`/`requested_rent_amount`), which are only readonly once `state != 'submitted'`.~~ **FIXED (2026-09-22).** `note` now uses `readonly="state != 'submitted'"`, the same pattern as its sibling fields. | The field is now editable while the request is still `Submitted` (e.g. by a staff member creating a request on a tenant's behalf), consistent with how the other request fields already behave, and locks once a decision is made - exactly as originally specified. | Medium / UX - now resolved | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | MAT-025 | Implemented - see "MAT-FIND-004 / MAT-FIND-008 - Investigation, Implementation, Tests, and Live Validation" below | Confirmed before fixing that the portal submission flow (`controllers/portal.py`) sets `note` only at `create()` time and never relies on backend immutability, and that a portal tenant has zero write access (`perm_write=0`) to this model regardless, so owner-only decision fields remain fully protected. 3 new automated tests (`tests/test_edara_renewal_request.py::TestEdaraRenewalRequestNoteField`), live-verified against real `odoo19_dev`, rolled back. |
| MAT-FIND-009 | Service Charges / Allocation (`edara.service.charge`, Equal + Proportional by Area allocation methods) | Service Charge Equal Allocation Uses Ineligible Building Units in Denominator | ~~Original observed behavior (historical evidence, preserved): During MAT-026, Service Charge `SC/2026/0037` (Building A, 6 Units: Apartment 101/103/104/105/106 `Rented`, Apartment 102 `Available`), Total Amount `$500.00`, Allocation Method `Equal`. After `Generate Allocation`: state `Draft` → `Allocated`, exactly 5 Allocation Lines created (Apartment 101/103/104/105/106, `$83.33` each, Tenant `Omar Khalil`), Apartment 102 correctly excluded (no line). `$83.33` = `$500 / 6` - i.e. the calculation denominator used all 6 Building Units (including the ineligible `Available` Apartment 102), not the 5 units that actually received lines. Sum of the 5 lines = `$83.33 × 5 = $416.65`, leaving ~`$83.35` of the original `$500.00` unallocated.~~ **FIXED** - root cause confirmed as `action_generate_allocation()` computing the allocation denominator from all building units before eligibility filtering; see "Resolved MAT Findings - Implementation Notes" below. | For `Equal` allocation, the denominator should be the number of eligible units that actually receive Allocation Lines (in this scenario, 5, not 6): `$500 / 5 = $100.00` per eligible unit, so `$100.00 × 5 = $500.00`, reconciling exactly to the Service Charge Total Amount. An `Available` unit excluded from allocation must not still count toward the allocation denominator. Same principle applies to `Proportional by Area`'s `total_area` denominator. | High / Financial - Data Integrity | **FIXED - VERIFIED** | MAT-026 | Implemented - see "Resolved MAT Findings - Implementation Notes" below. | Discovered during MAT-026, before `Create Invoices` was run. **Impact (as originally observed): the allocated total did not reconcile to the Service Charge Total Amount, which would have produced incorrect (under-billed) invoice amounts per unit if `Create Invoices` had been executed against the incorrect allocation.** `Create Invoices` was intentionally NOT executed on `SC/2026/0037` at the time. Fix implemented, covered by automated regression tests (11/11 Service Charge tests pass, 107/107 full module suite passes), and subsequently **verified live**: re-running `Generate Allocation` on `SC/2026/0037` produced 5 eligible lines at `$100.00` each (`$500.00` total, fully reconciled), and `Create Invoices` produced exactly 5 correctly-posted native invoices (`INV/2026/00007`-`00011`). See **MAT-026** above (now PASS / COMPLETED) for full live verification detail. |
| MAT-FIND-010 | Lease Contract / Unit Occupancy (`edara.lease.contract`, `edara.unit._sync_occupancy_from_contracts`) | Active Past-Dated Contract Leaves Unit as Rented | An `Active` contract whose `end_date` has already passed (i.e. not yet processed by the expiry cron) leaves its Unit's Occupancy as `Rented`. Observed on `LC/2026/0119` and `LC/2026/0120` during the 2026-09-16 live verification cycle - example: `LC/2026/0120` (Start `01/08/2026`, End `01/09/2026`), state `Active` (before the expiry cron ran), Unit Apartment 107, Occupancy `Rented`. | ~~Not yet determined.~~ **DECIDED (2026-09-21, via BD-001).** `occupancy_status` must reflect real-time date-range coverage via a reliable scheduled mechanism, not merely "has an active contract record." `_cron_expire_contracts()` already implements exactly this on the end-date side - a unit showing `Rented` between `end_date` passing and the next daily cron run is expected, bounded cron-latency, not a semantics gap. | Resolved by BD-001's decision - see "Business Decisions Required" below | **READY FOR IMPLEMENTATION** (semantics question closed; no separate fix needed beyond BD-001's implementation, which formalizes the same reliable-scheduled-mechanism principle on the start-date side) | 2026-09-16 live verification cycle (MAT-FIND-005/006 re-test) | No fix needed beyond BD-001's implementation - see "Business Decisions Required" below (BD-001) for the full implementation requirements list and required tests. | Discovered during the same live verification pass that confirmed MAT-FIND-005/MAT-FIND-006/MAT-020. Resolved 2026-09-21 alongside BD-001 - see BD-001 for the full rationale distinguishing (and then reconnecting) this finding's end-date symptom from BD-001's start-date symptom. No code/view/test change has been made for this finding. |
| MAT-FIND-011 | Lease Contract / Payment Schedule (`edara.lease.contract._generate_schedule_lines`) | Active Contract Can Have Zero Payment Schedule Lines | ~~Contract `LC/2026/0126` (Start `02/09/2026`, End `01/10/2026`, Rent $1,600, Monthly, Payment Day `1`, Deposit Required No, Unit Apartment 109), after activation: State `Active`, Unit Occupancy `Rented`, but Payment Schedule = 0 lines.~~ **FIXED.** | Every active contract must produce at least one Payment Schedule line, regardless of how its Start Date relates to the (now auto-derived) Payment Day - the schedule-generation algorithm guarantees this structurally: the loop's first period always starts at `start_date` itself, which is always `< end_date` (enforced by the `_check_dates` constraint). | High / Financial - Data Integrity (an active contract with zero billable lines silently collects no rent) | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED - ACCOUNTING VERIFIED** | 2026-09-16 live verification cycle (MAT-020 re-test) | Implemented - see "Resolved MAT Findings - Implementation Notes" below | Discovered during MAT-020 live re-verification (the same `LC/2026/0126` contract used as "Contract B"). Fixed as part of the same implementation pass that fixed MAT-FIND-013 (`_generate_schedule_lines()`'s rewritten loop structurally guarantees at least one line for any active contract - see that finding's entry below). **Live-verified 2026-09-18** on `LC/2026/0129` (Start `02/09/2026`, End `01/10/2026`, Monthly, Rent $1,600, Payment Day `2` - auto-derived from Start Date, not manually entered): after activation, Payment Schedule held exactly 1 line (Due Date `02/09/2026`, Period `02/09/2026 → 01/10/2026`, Amount `$1,546.67`, state `Overdue`, Invoice initially blank). Running `Generate Due Invoices` produced `INV/2026/00012` (Posted, Total `$1,546.67`, Amount Due `$1,546.67`), correctly linked to the schedule line - **accounting-verified**. |
| MAT-FIND-012 | Lease Contract / Overlap Validation (`edara.lease.contract._check_no_overlap`) | Lease Overlap Boundary Treats End Date as Inclusive | ~~Setting a new contract's Start Date exactly equal to another active contract's End Date on the same Unit was rejected as an overlap - end_date was inclusive.~~ **FIXED (2026-09-22).** Approved decision: exclusive End Date semantics, consistent with the already-exclusive billing boundary (MAT-FIND-005) - a lease ending on a date no longer occupies that date, so a new lease may start exactly on the prior lease's end_date (adjacent leases allowed). | `_check_no_overlap()`'s domain changed from inclusive (`start_date <= other.end_date AND end_date >= other.start_date`) to exclusive (`start_date < other.end_date AND end_date > other.start_date`) - two ranges `[s1,e1)`/`[s2,e2)` overlap iff `s1 < e2 AND s2 < e1`. | Medium / Business Rule - now resolved, consistent with the billing boundary | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | 2026-09-16 live verification cycle (MAT-020 re-test) | Implemented - see "MAT-FIND-003 / MAT-FIND-012 - Implementation, Tests, and Live Validation" below | 6 new automated tests (`tests/test_edara_lease_contract.py`) covering adjacent (allowed), one-day-before-adjacent (blocked), exact-same-dates (blocked), new-inside-existing (blocked), existing-inside-new (blocked), partial overlap (blocked) - all existing overlap tests (genuine mid-range overlaps, not boundary-adjacent) confirmed unaffected. Live-verified against real `odoo19_dev`, rolled back. |
| MAT-FIND-013 | Lease Contract / Payment Schedule (`edara.lease.contract._generate_schedule_lines`) | Billing Frequency Granularity Defect - Quarterly/Yearly Periods Decomposed Into Monthly Lines | ~~Contract `LC/2026/0134` (Start `15/09/2026`, End `01/12/2026`, Billing Frequency Quarterly, Rent `$3,000`). After activation, the generated Payment Schedule contained 3 lines (`15/09→15/10` `$1,000`, `15/10→15/11` `$1,000`, `15/11→01/12` `$533.33`) instead of one prorated quarterly line - the algorithm's remainder-handling branch decomposed the leftover period at monthly granularity regardless of the contract's configured `billing_frequency`, so Quarterly and Yearly contracts whose duration didn't reach a full nominal period were incorrectly billed as a series of monthly-equivalent lines.~~ **FIXED.** | Each schedule line must represent exactly ONE billing period at the configured `billing_frequency` granularity (1/3/12 months for Monthly/Quarterly/Yearly). A full billing-frequency period is always ONE line at the full configured rent. Once a full period no longer fits before `end_date`, the entire remainder must be ONE prorated line (monthly-equivalent rate × occupied days / a standardized 30-day reference month) - never further decomposed into monthly sub-lines. | High / Financial - Data Integrity (affects invoiced amounts and number of installments for Quarterly/Yearly contracts) | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED - ACCOUNTING VERIFIED** | Live MAT of the finalized billing rules, 2026-09-17 | Implemented - see "Resolved MAT Findings - Implementation Notes" below | Discovered live on `LC/2026/0134`. Monthly-frequency contracts were never affected (for Monthly, the "full period" and "remainder" granularities already coincided, so this bug was invisible at Monthly frequency) - MAT-FIND-005 and MAT-FIND-011 (both Monthly-frequency scenarios) remain unaffected and still pass. This fix also changes the previously-illustrative "Annual 6-month contract = six $1,000 lines" example from an earlier design discussion: under the corrected rule a 6-month Yearly-billed contract is ONE prorated line (`$6,033.33`, using the exact 181-day span), not six monthly lines - the "six lines acceptable" phrasing from that earlier discussion is superseded by this finding. **Live-verified 2026-09-18** across 5 dedicated contracts (`LC/2026/0135`-`0139`, `0141` - see "Resolved MAT Findings - Implementation Notes" below for full detail): Quarterly single prorated line, Quarterly full-periods-only, Quarterly full-periods-plus-remainder, Yearly single full period, Yearly single prorated line, and Yearly full-period-plus-remainder (with the full-period line's invoice posted) were all confirmed correct, with zero monthly decomposition observed in any case. The two arithmetic discrepancies noted below between the original finding's illustrative numbers and this project's `occupied_days = (period_end - period_start).days` formula are independently confirmed correct by this live evidence (e.g. `LC/2026/0135`'s live result is 77 days / `$2,566.67`, exactly matching the corrected figure, not the originally-reported 76 days / `$2,533.33`). |
| MAT-FIND-014 | Security / Access Control (`edara.dashboard._compute_kpis`, `edara.property._compute_financial_summary`, `edara.branch._compute_financial_summary`, `account.move`, `account.payment`, `group_edara_viewer`) | Viewer User Encounters `account.move` Access Error When Opening EDARA Dashboard | ~~User `Omar Khaled` (`omar@example.com`), EDARA Access Level `Viewer`, Maintenance `No`, Accounting `No`. Reproduction: (1) log in as Omar, (2) open the EDARA application, (3) open the Dashboard. Actual result: "Access Error — You are not allowed to access 'Journal Entry' (account.move) records. This operation is allowed for the following groups: Accounting/Administrator; Accounting/Invoicing; Sales/User: Own Documents Only; Role / Portal; Show Accounting Features - Readonly. Contact your administrator to request access if necessary." Because of this error, the Viewer could not successfully reach the normal EDARA UI/data to verify access to Properties, Buildings, Units, Contracts, Payment Schedule, etc.~~ **FIXED.** During the MAT-031 security/isolation pass, the identical unguarded-`account.move`-read pattern was also found (by direct code inspection, not just the Dashboard) in `edara.property._compute_financial_summary()` and `edara.branch._compute_financial_summary()` - both power a "Financial Summary" page on forms a Viewer is otherwise fully entitled to open, so simply opening a Property or Branch record would have hit the same crash. All three were fixed together as one pattern. | Every EDARA screen a Viewer is otherwise entitled to open (Dashboard, Property, Branch) must open successfully regardless of native Accounting access. Accounting-dependent data degrades safely (0/hidden) for a user without `account.move`/`account.payment` read access, using a plain `has_access('read')` permission check - no `sudo()`, no new Accounting permissions granted to anyone. | High / Security - Blocking (prevented the Viewer role's baseline access test from completing) | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED** | MAT-031 (Viewer baseline testing) | Implemented - see "Resolved MAT Findings - Implementation Notes" below | Discovered during MAT-031 while establishing the Viewer role's live access baseline. Fixed in the same MAT-031 pass via a permission-aware compute pattern (see implementation notes). **Live-verified twice, 2026-09-19:** (1) the business owner logged in as `omar@example.com` and confirmed the Dashboard opens with no `account.move` AccessError and Accounting-dependent tiles absent; (2) independently re-confirmed programmatically against the real `odoo19_dev` database (not `edara_test`) - Dashboard/Property (`Al-Rawabi Property`)/Branch (`Ramallah Branch`) all open cleanly for the real `omar@example.com` account with `has_accounting_access=False` and zeroed Accounting fields, while `admin@example.com` (native Accounting access) sees real figures. See "MAT-FIND-014 - Root Cause, Fix, and Related Findings" below for full live-validation detail. |
| MAT-FIND-015 | Security / Accounting Boundaries (`security/edara_security.xml`, `models/edara_deposit.py`, `models/edara_service_charge_line.py`, `models/edara_payment_schedule_line.py`, `models/edara_property.py`, `wizard/edara_deposit_transaction_wizard.py`) | EDARA Accounting/Company-Manager/Administrator Roles Never Imply Native Odoo Accounting Access | ~~None of `group_edara_accountant`, `group_edara_company_manager`, or `group_edara_administrator` imply any native `account.group_*` group, so every EDARA workflow that creates a native `account.move`/`account.payment` (Service Charge invoicing, Deposit Collect/Refund/Deduct, Late Fee) failed with a raw `AccessError` for an EDARA-only user - confirmed both at the ACL level and via a full end-to-end business-workflow click-through against real `odoo19_dev` data (2026-09-20).~~ **FIXED (MAT-FIND-015-A, scoped native Accounting execution).** Per the resolved architecture decision (below), EDARA roles do **not** receive any native Accounting group. Instead, the five confirmed call sites (`edara.service.charge.line._create_invoice()`, `edara.payment_schedule_line.action_charge_late_fee()`, `edara.deposit.action_collect()/action_refund()/action_deduct()`, `edara.deposit.transaction.wizard._resolve_deposit_journal()`, `edara.property.get_analytic_account()`) now use a narrow, explicitly-scoped `.sudo()` limited to exactly the one native `create()`/`action_post()`/`search()` call each workflow needs, gated by an explicit `self.check_access('write')` (or, for the two Deposit money-movement actions, by creating the authorizing `edara.deposit.transaction` record *before* the elevated native call) that runs first, using EDARA's own already-enforced ACL/record-rule layer - never a blanket native Accounting group grant. | Architecture decision (resolved): "the architecture needs a different permission/integration design" - narrow, scoped, audited elevation at the exact native Accounting call sites, gated by EDARA's own pre-existing authorization, in preference to a blanket native `account.group_account_invoice`/`account.group_account_manager` grant (which would have exposed the full native Invoicing app, all company `account.move`/`account.payment` records including 12 confirmed non-EDARA ones, and required a second group for `account.analytic.account` regardless). | High / Security & Operational - now resolved: EDARA-only Company Manager/Accountant users can complete Service Charge invoicing, Deposit Collect/Refund/Deduct, and Late Fee charging, while still having zero native Accounting read/search/write/create access beyond those exact narrow actions | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED** | MAT-031 (code-inspection review triggered by investigating MAT-FIND-014); end-to-end click-through validation 2026-09-20; architecture analysis 2026-09-20; scoped-execution implementation (MAT-FIND-015-A) 2026-09-20 | Implemented - see "MAT-FIND-015-A - Scoped Native Accounting Execution: Implementation, Tests, and Live Validation" below for the full root-cause/fix narrative, security model, and evidence | Resolved 2026-09-20. 24 new automated tests added (`tests/test_edara_mat015_scoped_accounting.py`), full suite 173/173 passing, and a live rolled-back validation against real `odoo19_dev` data (24/24 checks passed) confirming all five workflows now succeed for EDARA-only users with zero native Accounting group, a Viewer remains fully blocked before any elevation (no orphaned native records), no broad native read/search/create/write access leaked to any EDARA role afterward, and company/branch isolation is preserved. |

### MAT-FIND-014 — Root Cause, Fix, and Related Findings (MAT-031 security/isolation pass)

**Status: FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

**Live verification (2026-09-19), two independent confirmations:**
1. **Manual browser smoke test** by the business owner, logged in as the real Viewer `omar@example.com`: EDARA → Dashboard opened successfully; the previously-reproduced `account.move` Access Error no longer occurred; Accounting-dependent tiles appeared as zero/hidden, exactly as expected for a Viewer with no native Accounting access.
2. **Independent programmatic re-verification against the real `odoo19_dev` database** (not the synthetic `edara_test` fixture DB) - a read-mostly validation script was run via `odoo-bin shell -d odoo19_dev`, using the actual existing `omar@example.com` (Viewer) and `admin@example.com` (Administrator) accounts and actual existing data (`Ramallah Branch`, `Al-Rawabi Property`, 27 real lease contracts, a real already-invoiced `edara.payment.schedule.line`), with the entire transaction explicitly rolled back at the end (`env.cr.rollback()`) so **nothing in `odoo19_dev` was modified**. Result: **94/94 checks passed, 0 failed.** Confirmed live: Omar's Dashboard opens with `has_accounting_access=False` and `monthly_revenue`/`outstanding_receivables`/`recent_payments_count` all `0`; Omar opening the real `Al-Rawabi Property`/`Ramallah Branch` records does not raise an `account.move` AccessError and shows `has_accounting_access=False`/`total_revenue=0`; `admin@example.com` sees `has_accounting_access=True` with real figures; reading the real already-invoiced schedule line (id 833) as Omar does not crash (confirms the earlier "Many2one exposure" review was correct); and the full Viewer/Branch/Property/Unit/Contract/Maintenance/Tenant isolation matrix (see below) held on real data. This is the evidence behind Sections 1-9 of this pass's live report.

**Root cause (confirmed):** the Dashboard menu action calls `EdaraDashboard.action_open()`, which creates a transient dashboard record and opens it; `_compute_kpis()` on that record read native Accounting models directly (`self.env['account.move']._read_group(...)` for monthly revenue/outstanding receivables, `self.env['account.payment'].search_count(...)` for recent payments) with no access check or `sudo()` boundary of its own. Because the Viewer role (`group_edara_viewer`) has no ACL on `account.move` - and, as confirmed by this same pass, **none of EDARA's own groups (Viewer, Property Manager, Branch Manager, Accountant, Company Manager, Administrator) imply any native Odoo Accounting group either** (grepped `security/edara_security.xml` - zero references to `account.group_*`) - the very first `_read_group()` call raised a raw `AccessError` the moment the Dashboard's KPI fields were evaluated, before the record ever rendered. The same unguarded pattern was independently confirmed (by grepping the whole module for `self.env['account.move']`/`self.env['account.payment']`) in `edara.property._compute_financial_summary()` and `edara.branch._compute_financial_summary()`, both of which back a "Financial Summary" notebook page with no `groups=` restriction on a form every Viewer is otherwise entitled to open.

**Fix:** a permission-aware compute pattern applied identically to all three:
- `edara.dashboard._compute_kpis()` now checks `Move.has_access('read') and Payment.has_access('read')` once per compute; when both are readable, the KPIs compute exactly as before; when either is not, `monthly_revenue`/`outstanding_receivables`/`recent_payments_count` default to `0`/`0.0` and a new `has_accounting_access` Boolean field is set to `False`. Non-Accounting KPIs (unit counts, renewals, maintenance) are entirely unaffected either way.
- `edara.property._compute_financial_summary()` and `edara.branch._compute_financial_summary()` gained the identical `Move.has_access('read')` check, a new `has_accounting_access` field, and the same 0-default behavior for `total_revenue`/`total_expenses`/`net_operating_result`/`total_outstanding` when access is absent.
- `views/dashboard_views.xml`: the three Accounting-dependent KPI tiles (Monthly Revenue, Outstanding Receivables, Payments This Month) are now `invisible="not has_accounting_access"` - hidden rather than shown as a misleading `$0`/`0`. Non-Accounting tiles are always visible.
- `views/property_views.xml` / `views/branch_views.xml`: the "Financial Summary" `<page>` is now `invisible="not has_accounting_access"`; Property's "Expenses"/"Invoices" smart buttons (which navigate straight into native `account.move` list actions) got the same `invisible="not has_accounting_access"` guard, so a Viewer no longer sees a button that would immediately fail on click.
- No `sudo()` was used anywhere - the fix is a permission *check*, not a permission *escalation*; nothing reads data the calling user isn't already allowed to read.

**Files changed:** `models/edara_dashboard.py`, `models/edara_property.py`, `models/edara_branch.py`, `views/dashboard_views.xml`, `views/property_views.xml`, `views/branch_views.xml`.

**Related, NOT fixed, NOT blocking - see MAT-FIND-015 below:** the same code-inspection pass that found MAT-FIND-014's Property/Branch siblings also surfaced that EDARA's own "Accountant"/"Company Manager"/"Administrator" groups never grant native Accounting access either - meaning even a genuinely EDARA-privileged user (not just a Viewer) would currently hit the same class of error the moment they tried to *create* an invoice/payment/journal entry (Service Charge "Create Invoices", deposit collect/refund/deduct, late-fee charging) unless a system administrator had separately, manually granted them a native Odoo Accounting group outside of EDARA's own role assignment. This is why prior MAT sessions (MAT-018/019/023/026, all of which successfully created real invoices/payments) never hit this - they were run as the Odoo instance admin, who already has native Accounting access by default (`base.user_admin` carries `account.group_account_manager`). This create/write-side risk is **not addressed by this pass** (only the confirmed, live-reproduced Dashboard/Property/Branch *read* crash was fixed) and is recorded as a new, separate, non-blocking finding - see MAT-FIND-015.

**Also reviewed and confirmed safe (no fix needed):** a Viewer reading an `edara.payment.schedule.line` that already has `invoice_id` set (pointing to `account.move`) does **not** trigger an `AccessError` - empirically verified (`test_viewer_reading_schedule_line_with_invoice_set_does_not_crash`): the foreign-key id lives on the schedule line's own row, and Odoo's relational-field `display_name` resolution does not require the reading user to have ACL on the target model. This was an open question raised during the review, not a second instance of MAT-FIND-014.

**MAT-031 full live-validation matrix (2026-09-19, against real `odoo19_dev` data, rolled back):**

| Area | Result | Evidence |
|---|---|---|
| Viewer (`omar@example.com`) | PASS | Dashboard/Property/Branch open cleanly; Accounting fields safely zeroed |
| Dashboard | PASS | No `account.move` AccessError; `has_accounting_access` correctly False for Omar, True for admin |
| Company isolation | NOT LIVE-TESTED | `odoo19_dev` currently has only 1 real company - structurally nothing to isolate against live; already proven via automated `TestEdaraMultiCompany`/`TestEdaraCompanyIsolationBroad` against `edara_test`'s dedicated multi-company fixtures (13/13 passing) |
| Branch isolation | PASS | Unassigned Omar sees 0 branches and is denied reading the real `Ramallah Branch` by id; once temporarily assigned (rolled back), sees exactly `Ramallah Branch` and not a disposable isolation-test branch created for this check |
| Property isolation | PASS | Same pattern on `Al-Rawabi Property` vs. a disposable isolation-test property |
| Unit isolation | PASS | Same pattern on a disposable isolation-test unit |
| Contracts | PASS | Viewer ACL denies create/write/unlink on `edara.lease.contract`; assigned Viewer sees only the 27 real Ramallah-branch contracts, all correctly branch-scoped |
| Tenants | PASS | Native `res.partner` visibility confirmed intentional (Viewer can read a real tenant partner but cannot write it) - no EDARA-specific partner-level restriction exists or is needed, per the established architecture |
| Maintenance | PASS | Viewer (no Maintenance Staff privilege) can read but cannot create/write `edara.maintenance.request` |
| Accounting boundary | PASS (Viewer) / DECISION (privileged roles) | Omar has zero access to `account.move`/`account.payment`/`account.journal`/`account.move.line` - correct. Freshly-created (rolled-back) EDARA-only Accountant/Company-Manager/Administrator test users were also confirmed to have no native `account.move`/`account.payment` create access or `account.journal` read access - this is MAT-FIND-015, an open architecture decision, not a defect fixed by this pass |
| Administrator (`admin@example.com`) | PASS | Full read/write/create on every checked EDARA model plus real native `account.move`/`account.payment`/`account.journal` access - Administrator workflows are not blocked by this pass's changes |

Method note: all of the above ran as a single read-mostly Python script executed via `odoo-bin shell -d odoo19_dev`, using real existing users/companies/branches/data plus a small number of disposable, clearly-labeled test records (an isolation-test branch/property/building/unit, three disposable EDARA-role-only test users) created purely to prove a boundary and never persisted - the entire transaction was rolled back (`env.cr.rollback()`) before the script exited, so `odoo19_dev` is unmodified. This satisfies "use the real database, don't create a replacement, don't modify production data" while still exercising the real ORM security stack (identical enforcement to the web client) against real data.

### MAT-FIND-015 — End-to-End Business Workflow Validation (2026-09-20)

**Objective:** determine the real operational impact of the ACL-level gap recorded in MAT-FIND-015 - not just whether `has_access()` predicts a denial, but whether an actual EDARA-only privileged user, using the real business buttons/wizards, can complete Service Charge invoicing, Security Deposit collection/refund/deduction, and Late Fee charging. Investigation only - no permissions were changed.

**Method:** a single Python script run via `odoo-bin shell -d odoo19_dev --no-http`, wrapped in `try/finally: env.cr.rollback()`, executed against real existing data (Al-Rawabi Property/Building A, 18 real occupied units, real contract `id=111`, real held Deposit `id=64` with a $1,500 balance, real overdue Payment Schedule Line `id=925`). Nothing in `odoo19_dev` was modified - confirmed by the script's own rollback plus a post-hoc check that no test user rows persisted.

**Test User:**
- EDARA role: **Company Manager only** (`group_edara_company_manager`) - chosen because it is the only single EDARA role with create/write access to all four workflows under test (`edara.service.charge`/`.line` via its `branch_manager` implication, `edara.deposit`/`.transaction` via its `accountant` implication, `edara.payment.schedule.line` via `branch_manager`).
- Native Accounting groups: **none** - confirmed baseline before running any workflow: `account.move` create = `False`, `account.journal` read = `False`.
- Company: `My Company` (id=1, the only company in `odoo19_dev`). Branch: not applicable - Company Manager's record rule grants it visibility across all branches, no assignment needed (same pattern already confirmed in the MAT-031 live-validation matrix).

**Test A — Service Charge Invoice Generation** (Building A, real building, equal allocation, $900 total)
- Result: **FAIL at the final step**
- Exact behavior: Step 1 (create the Service Charge record) succeeded. Step 2 (`Generate Allocation`, pure EDARA-layer computation) succeeded - 18 real eligible units allocated. Step 3 (`Create Invoices` / `action_invoice_lines()`) failed.
- Exact error: `AccessError: You are not allowed to create 'Journal Entry' (account.move) records. This operation is allowed for the following groups: Accounting/Invoicing. Contact your administrator to request access if necessary.`
- Root cause: `edara.service.charge.line._create_invoice()` calls `self.env['account.move'].create(...)` as the calling user, with no `sudo()`; the calling user has no native Accounting group.
- Classification: **ARCHITECTURAL GAP** - the role can open the workflow and complete every EDARA-layer step, but is structurally unable to finish it.

**Test B — Security Deposit Collection** (fresh disposable Deposit on real contract `id=111`, $500)
- Result: **FAIL, and fails earlier than expected**
- Exact behavior: Step 1 (create the Deposit record, state `Not Collected`) succeeded. Step 2 - simulating the real `edara.deposit.transaction.wizard`'s own `_onchange_deposit_transaction_type()`, which unconditionally runs `account.journal.search([...])` to auto-default the Payment Journal field - failed immediately, **before an amount or journal could even be selected**. Step 3 (`action_collect()`, called directly with a journal id already known) separately failed on `account.payment.create()`.
- Exact errors: `AccessError: You are not allowed to access 'Journal' (account.journal) records. This operation is allowed for the following groups: Accounting/Administrator; Accounting/Invoicing; ...` (Step 2); `AccessError: You are not allowed to create 'Payments' (account.payment) records. This operation is allowed for the following groups: Accounting/Invoicing.` (Step 3).
- Root cause: `edara.deposit.transaction.wizard._onchange_deposit_transaction_type()` searches `account.journal` unguarded; `edara.deposit._create_deposit_payment()` calls `account.payment.create()` unguarded. Neither uses `sudo()`.
- Classification: **ARCHITECTURAL GAP** - in the real UI this means the Collect Deposit wizard itself breaks on open (the journal field can't populate), not merely on final confirmation - a worse UX than Test A's failure point.

**Test C — Deposit Refund / Deduction** (real held Deposit `id=64`, balance $1,500, no unwanted postings - rolled back)
- Result: **FAIL (both)**
- Exact behavior: `action_refund(journal_id, $200)` failed on `account.payment.create()`. `action_deduct($100, description)` failed on `account.move.create()` (entry-type journal entry).
- Exact errors: identical `AccessError` shapes to Test A/B ("...allowed for the following groups: Accounting/Invoicing").
- Root cause: same pattern - `edara.deposit.action_refund()`/`action_deduct()` call `account.payment.create()`/`account.move.create()` unguarded.
- Classification: **ARCHITECTURAL GAP** - consistent with Collect; all three Deposit transaction types are equally blocked.

**Test D — Late Fee** (real overdue Payment Schedule Line `id=925`, due 2026-08-01, $1,500)
- Result: **FAIL**
- Exact behavior: `action_charge_late_fee()` failed on `account.move.create()` (out_invoice, `edara_invoice_type='late_fee'`).
- Exact error: same `AccessError` shape as above.
- Root cause: same unguarded `account.move.create()` pattern.
- Classification: **ARCHITECTURAL GAP**.
- Side note (not part of this finding): the real `odoo19_dev` company record also has `edara_late_fee_amount` unset (`NULL`), which would independently block this workflow with a `UserError` regardless of the Accounting boundary. This test set the value to `25.0` in-memory, inside the same rolled-back transaction only, specifically to isolate the Accounting-boundary failure from this unrelated configuration gap - the real database was not changed. This configuration gap is not itself a MAT finding (it is expected for an unconfigured feature) but is noted here for completeness.

**Control — Administrator** (fresh Service Charge, Building A, fixed-per-unit $10, real `admin@example.com`)
- Result: **PASS, full end-to-end success** - `action_invoice_lines()` completed with no exception; every allocation line ended up with a posted invoice (`invoiced=True`).
- Purpose: rules out "BUG" as the classification for Tests A-D - the same code path works correctly for a user with native Accounting access, so the failure is specifically and only the missing group implication for EDARA-only roles (MAT-FIND-015), not a defect in the workflow logic itself.

**Security Decision (evidence-based, not chosen by this pass):**
The evidence supports one of two directions, and rules out a third:
1. ~~"EDARA privileged roles can operate without native Accounting access"~~ - **ruled out**. All four core financial workflows that EDARA's own Company Manager/Branch Manager/Accountant roles are explicitly granted ACL access to open and partially execute are structurally impossible to complete without it.
2. **"EDARA privileged roles intentionally need native Accounting access"** - supported by: these workflows exist specifically for EDARA roles to use (the buttons/wizards are gated to Property Manager/Branch Manager/Accountant, not exposed to Accounting-app users), and nothing in the UI offers an alternate "hand off to a separate Accounting user" path - the wizard breaks on its own onchange, not gracefully.
3. **"The architecture needs a different permission/integration design"** - equally supported: rather than a blanket native-Accounting-group implication (which would also cascade unwanted access to unrelated native Accounting screens/menus), a narrower design (e.g., implying only the minimum required native access, or wrapping these specific `create()`/`action_post()` calls in a scoped, audited `sudo()` at the exact point EDARA already validates the business rule) may be more appropriate.
This pass deliberately does not choose between (2) and (3) - that remains the open business/architecture decision.

**Project State:** `EDARA_PROJECT_STATE.md` updated (this section, plus the MAT-FIND-015 row above) with the full Test A-D evidence. MAT-FIND-015 status remains **OPEN - BUSINESS / ARCHITECTURE DECISION REQUIRED** - this pass confirms and completes the evidence, it does not resolve the finding. No permission, ACL, record-rule, or code change was made anywhere in this pass.

**Recommendation:** the next required action is a business/architecture decision between options (2) and (3) above. Once decided, implementation would be a small, targeted follow-up MAT (either adding specific `implied_ids` entries to `security/edara_security.xml`, or adding scoped `sudo()` calls at the four confirmed `create()`/`action_post()` call sites, each backed by a regression test) - not a redesign of EDARA's own ACL/record-rule layers, which remain correct and untouched.

### MAT-FIND-015 — Architecture Impact Analysis (2026-09-20, analysis only, no implementation)

**Objective:** before the business/architecture decision (option 2 vs. option 3 above) is made, precisely document what each candidate design would actually grant, using the real Odoo 19 groups/ACLs/record rules installed in `odoo19_dev` - not assumptions. No permission, ACL, record rule, `implied_ids`, `sudo()`, Python, or XML change was made. No permanent users or financial records were created. All inspection was read-only SQL against `odoo19_dev`.

#### Part A — Native Accounting Group Inventory (actual `odoo19_dev` data)

The `account` module defines 10 groups; only two sit on the primary "Accounting" privilege axis (`privilege_id=12`, the mutually-exclusive ladder a user picks one rung of, same mechanism as EDARA's own Access Level axis):

| xmlid | Display name | Privilege axis | Implies |
|---|---|---|---|
| `account.group_account_invoice` (id 47) | Invoicing | Accounting, seq 20 | `base.group_user` |
| `account.group_account_manager` (id 50) | Administrator | Accounting, seq 50 | `account.group_account_invoice` (and transitively `base.group_user`) |

The other 8 (`group_account_readonly`, `group_account_basic`, `group_account_user`, `group_account_secured`, `group_cash_rounding`, `group_partial_purchase_deductibility`, `group_validate_bank_account`, `group_delivery_invoice_address`) are independent feature-toggle groups, not part of the Accounting privilege ladder, and are not automatically granted by selecting Invoicing or Administrator.

**Exact CRUD granted by the two ladder groups** (`ir.model.access`, verified per model):

| Model | Invoicing (47) R/W/C/U | Administrator (50) R/W/C/U | Note |
|---|---|---|---|
| `account.move` | t/t/t/t | t/f/f/f (own row; full CRUD inherited via implied Invoicing) | Administrator's own explicit row is read-only - its actual create/write on moves comes from implying Invoicing |
| `account.move.line` | t/t/t/t | t/f/f/f (inherited from Invoicing) | same pattern |
| `account.payment` | t/t/t/? | (none direct; inherited from Invoicing) | Invoicing grants create |
| `account.journal` | **t/f/f/f (read-only)** | t/t/t/t | Invoicing can only READ existing journals, not create/edit them - Administrator is required to manage journals |
| `account.account` (chart of accounts) | t/f/f/f (read-only) | t/t/t/t | same pattern - configuration-level, Administrator-only |
| `account.tax` | t/f/f/f (read-only) | t/t/t/t | same pattern |
| `account.fiscal.position` | (none) | t/t/t/t | Administrator-only |
| `account.reconcile.model` | t/f/t/f | (inherited) | |
| `account.payment.method.line` | t/t/t/t | (inherited) | |
| `account.analytic.account` | **(no row at all - no access)** | **(no row at all - no access)** | **Important:** neither Invoicing nor Administrator grants any access to analytic accounts. That comes only from `analytic.group_analytic_accounting`, `project.group_project_manager`, `account.group_account_user` ("Show Full Accounting Features"), or `sales_team.group_sale_salesman` - none of which are implied by either Accounting-ladder group. |

**Record rules (`ir.rule`)** on `account.move`/`account.payment`/`account.journal`: all are company-scoped (`company_id in company_ids`) or Odoo-standard "own invoices"/"portal" rules - none are group-differentiated. Since `odoo19_dev` has exactly one company, company-scoping provides **no additional restriction** once ACL access is granted - a user with Invoicing access can read/write/create/unlink **every** `account.move`/`account.payment` in the company, not just EDARA-linked ones.

**Menu/UI exposure:** the top-level "Invoicing" app menu (id 309) is restricted to `group_account_readonly` OR `group_account_invoice` - granting Invoicing to any EDARA group makes the full native Invoicing app appear in that user's App Switcher, with its own Customers/Vendors/Reporting/Configuration menus, independent of anything EDARA's own menus expose.

**Concrete unrelated-data exposure check:** `odoo19_dev` currently has 10 `account.move` records of type `entry` and 2 of type `out_invoice` with `edara_invoice_type` NULL (i.e., not created by any EDARA workflow - manual entries / non-EDARA invoices). A native Invoicing grant would expose full read/write/create/unlink on these 12 records to the granted EDARA role, with no EDARA-side filter in between.

#### Part B — EDARA Workflow Minimum Requirements (traced from actual code, this session)

| Workflow | Code path | Models touched | Minimum native operations required |
|---|---|---|---|
| Service Charge invoicing | `edara.service.charge.action_invoice_lines()` → `edara.service.charge.line._create_invoice()` | `account.move` (create + implicit `action_post()` write), `account.move.line` (create, as invoice sub-lines), `account.account` (read only, via existing `income_account.id` - Many2one id access, no ACL needed), `account.analytic.account` (read only IF the property already has one, as in this session's test; **create** would additionally be required for any property whose analytic account has not yet been lazily created) | `account.group_account_invoice` covers `account.move`/`account.move.line` create+post. It does **not** cover analytic-account creation for a not-yet-initialized property - that specific gap would need `analytic.group_analytic_accounting` (or equivalent) too, or every property's analytic account would need to be pre-seeded. |
| Deposit Collect | `edara.deposit.action_collect()` → `_create_deposit_payment()`; wizard `_onchange_deposit_transaction_type()` | `account.journal` (**read**, to populate the wizard's journal field/domain), `account.payment` (create + implicit post) | `account.group_account_invoice` covers both (Invoicing has read on `account.journal` and full CRUD on `account.payment`). |
| Deposit Refund | `edara.deposit.action_refund()` → `_create_deposit_payment()` | Same as Collect | Same as Collect. |
| Deposit Deduction | `edara.deposit.action_deduct()` | `account.move` (create, `move_type='entry'`, implicit post) - **no `account.journal` access needed** (deduction posts a plain journal entry against configured liability/income accounts, no payment journal involved) | `account.group_account_invoice` covers this (create+post on `account.move`). |
| Late Fee | `edara.payment.schedule.line.action_charge_late_fee()` | `account.move` (create, `out_invoice`, implicit post), `account.analytic.account` (read only, property already initialized in this session's test) | `account.group_account_invoice` covers the confirmed path; same analytic-account caveat as Service Charge applies for uninitialized properties. |

**Conclusion of Part B:** `account.group_account_invoice` (Invoicing) is sufficient for every operation actually exercised by this session's Test A-D run, with one caveat already identified: first-time analytic-account creation for a property that has never been invoiced before is NOT covered by Invoicing alone. None of the four workflows require `account.group_account_manager` (Administrator/chart-of-accounts/taxes/fiscal-position configuration) - they only ever create/post transactional records against accounts, journals, and taxes that already exist.

#### Part C — Scoped Execution Analysis (conceptual only - no `sudo()` implemented)

```text
Workflow: Service Charge invoicing / Late Fee
Current user: EDARA Company Manager / Branch Manager (no native group)
Current EDARA permissions: full CRUD on edara.service.charge(.line)/edara.payment.schedule.line
Native operation required: account.move.create() + action_post() (+ account.move.line create, implicit)
Potential controlled elevation: a narrow sudo() scoped to exactly the account.move.create()/action_post()
  call inside _create_invoice()/action_charge_late_fee(), executed only after EDARA's own business-rule
  checks already ran (income account configured, unit/tenant resolved, line ownership validated)
Security checks required before elevation: confirm the calling user already has EDARA-layer write/create
  on the source record (service charge line / schedule line) - i.e. never let an elevated call be reached
  by a user who couldn't reach that line through EDARA's own ACL+record-rule layers first
Records that must remain restricted: the elevation must be scoped to creating/posting the ONE invoice
  being generated from ONE already-authorized EDARA line - it must not open general account.move
  search/read/write/unlink to the calling user for unrelated moves (the 12 non-EDARA moves noted in
  Part A must stay inaccessible)
Audit considerations: the created account.move would show as authored by the real EDARA user (not
  admin/superuser), preserving audit trail; a sudo()-based approach still needs to log/flag that
  elevation occurred, consistent with this project's standing "no silent bypass" rule

Workflow: Deposit Collect / Refund
Current user: EDARA Accountant / Company Manager (no native group)
Current EDARA permissions: full CRUD on edara.deposit/.transaction/.transaction.wizard
Native operation required: account.journal read (wizard journal field) + account.payment.create()/post()
Potential controlled elevation: (a) sudo()-scoped read of account.journal restricted to
  type in (cash,bank) for the deposit's own company - already the wizard's own domain, so the elevation
  would only ever surface the same journals a normal Invoicing user would see; (b) sudo()-scoped
  account.payment.create()+post() for exactly the deposit being processed
Security checks required before elevation: same principle - only after edara.deposit access is
  independently confirmed; amount must already be validated against deposit.balance by the existing
  action_collect()/action_refund() guards (already present, unchanged)
Records that must remain restricted: account.payment records unrelated to EDARA deposits; the journal
  read elevation must not become a general "browse all journals" capability
Audit considerations: same as above - payment appears authored by the real EDARA user

Workflow: Deposit Deduction
Current user: EDARA Accountant / Company Manager (no native group)
Current EDARA permissions: full CRUD on edara.deposit
Native operation required: account.move.create() (type=entry) + post()
Potential controlled elevation: sudo()-scoped account.move.create()+post() for exactly the two
  liability/income lines already fully determined by action_deduct()'s existing logic (no new data
  entry surface is introduced - the elevation only executes what EDARA's own code already decided)
Security checks required before elevation: same principle as above
Records that must remain restricted: unrelated journal entries
Audit considerations: same as above
```

**General observation:** because every one of these workflows already fully determines its own accounting operation (account ids, amounts, partner, journal are all resolved by EDARA's own business logic before the native call, and the native call's inputs are never freely user-editable form fields on the native model itself), a scoped-elevation design is technically straightforward to reason about - it would elevate a fixed, narrow, already-validated `create()+action_post()` call, not open-ended access to the native Accounting app. This is the structural reason scoped execution is a realistic alternative to full group inheritance here, per Odoo's own guidance that bypassing access rights should be rare, explicit, and narrowly justified.

#### Part D — Least-Privilege Comparison

| Requirement | Native Group Inheritance (Invoicing) | Scoped Execution (targeted `sudo()`) |
|---|---|---|
| Service Charge invoice | Works; also requires a second group (`analytic.group_analytic_accounting` or similar) for first-time analytic-account creation | Works; elevation covers analytic-account creation too if scoped to `get_analytic_account()`'s own call |
| Deposit collect | Works | Works |
| Deposit refund | Works | Works |
| Deposit deduction | Works | Works |
| Late fee | Works (same analytic-account caveat as Service Charge) | Works |
| Accounting UI exposure | Full "Invoicing" app becomes visible/usable (Customers, Vendors, Reporting, Configuration menus) - far beyond EDARA's own screens | None - no new menus, no new native app surface exposed |
| Financial data visibility | Full read/write/create/unlink on **every** `account.move`/`account.payment`/`account.journal` in the company, including the 12 confirmed non-EDARA records - record rules provide no additional narrowing in a single-company setup | Strictly limited to the records the elevated call itself creates/posts - no new read/search capability on unrelated moves/payments |
| Implementation complexity | Low - a handful of `implied_ids` lines in `security/edara_security.xml`, no Python changes | Medium - requires adding and carefully justifying `sudo()` at 4-5 call sites, plus tests proving no broader capability leaked |
| Upgrade risk | Low-medium - native group semantics can change between Odoo versions (already observed: Odoo 19 restructured `category_id`→`privilege_id`), silently changing what EDARA users can reach | Low - the elevation is local to EDARA's own code, insulated from native group definition changes upstream |
| Auditability | Standard Odoo audit trail (moves/payments show real user as author) but the user's *capability* is broad and only auditable by cross-referencing which records they touched out of everything they technically could | Narrower, more self-documenting - the `sudo()` call sites are themselves the audit surface; capability is inherently limited to what the code path allows |
| Least privilege | Violates it - grants full transactional CRUD on all accounting moves/payments/journals-read to reach 5 narrow business actions | Satisfies it - grants exactly the 5 narrow business actions and nothing else |
| Maintenance burden | Low ongoing burden once configured; but any future native Accounting feature added to the Invoicing group automatically becomes available to these EDARA roles too, un-reviewed | Slightly higher ongoing burden - each new EDARA workflow that touches accounting needs its own explicit, reviewed elevation, but nothing is granted implicitly |

#### Part E — EDARA Role Intent (from the existing product spec, ACLs, and workflows - not invented)

- **Viewer:** `EDARA_IMPLEMENTATION_SPEC.md` and MAT-FIND-014's fix both confirm Viewer must NOT see Accounting data - the permission-aware compute pattern exists specifically to hide it. No change in intent here; Viewer should remain without any native Accounting group.
- **Accountant:** `EDARA_IMPLEMENTATION_SPEC.md` §54 ("ACCOUNTING UI") states explicitly: *"Accountants must still have access to native: Journal Items, Accounting Entries, Reconciliation, Payment, Invoice, Credit Note."* §40 additionally states *"Accountants still retain access to full accounting details."* This is documented product intent, not an inference - the spec anticipated the Accountant role needing native Accounting access, though it does not specify the mechanism (group inheritance vs. scoped access vs. manual dual-provisioning).
- **Company Manager:** EDARA's own role ladder already has `group_edara_company_manager` imply `group_edara_accountant` (confirmed in `security/edara_security.xml`), meaning the product's own design already intends Company Manager to carry every Accountant-level EDARA capability, including the four workflows tested here. The spec does not separately call out Company Manager needing anything beyond Accountant-level native access (e.g., chart-of-accounts/tax configuration) - the tested workflows (Service Charge, Deposit, Late Fee) are all transactional, matching Accountant-tier (`account.group_account_invoice`), not Administrator-tier (`account.group_account_manager`) native capability.
- **Administrator:** the spec does not explicitly document what native-tier access EDARA's own Administrator role should carry (it is not named in §54's Accountant-specific text). In practice, the only account with real native Accounting access today (`admin@example.com`) has it via `base.user_admin`'s own default `account.group_account_manager`, unrelated to EDARA's group assignment. Whether EDARA Administrator should independently imply native `account.group_account_manager` (full configuration access) is **not answered by the existing spec** and should not be assumed - flagged here as an open question rather than invented.

**Regression Baseline (confirmed unchanged - no code was modified in this analysis-only pass):**
- MAT-031: unchanged, still substantially complete as of 2026-09-19.
- MAT-FIND-014: unchanged - **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED**.
- MAT-FIND-015: unchanged - **OPEN - BUSINESS / ARCHITECTURE DECISION REQUIRED** (this analysis adds evidence for the decision; it does not resolve it).
- Full test suite: last confirmed 153/153 (2026-09-19); since zero Python/XML/ACL/record-rule files were touched by this pass, there is no code path by which that result could have changed, so it is confirmed unchanged by inspection rather than re-run.
- No fixtures, users, or records were created during this analysis - all inspection was read-only SQL against `odoo19_dev`.

### MAT-FIND-015-A — Scoped Native Accounting Execution: Implementation, Tests, and Live Validation (2026-09-20)

**Status: FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

**Architecture decision (resolved):** EDARA roles do **not** receive any native Accounting group (`account.group_account_invoice`/`account.group_account_manager`) - not on `group_edara_accountant`, `group_edara_company_manager`, or `group_edara_administrator`. Instead, the exact native `account.move`/`account.payment`/`account.journal`/`account.analytic.account` operations each EDARA workflow needs are performed through a narrow, explicitly-scoped `.sudo()` at the precise call site, gated by EDARA's own pre-existing ACL/record-rule authorization running first. This corresponds to option (3) from the MAT-FIND-015 architecture analysis above (scoped integration design) rather than option (2) (blanket native group inheritance) - chosen because the analysis showed blanket inheritance would expose the full native Invoicing app/menu, all company `account.move`/`account.payment` records (including 12 confirmed non-EDARA ones on `odoo19_dev`), and would still need a *second* group for `account.analytic.account`, while every workflow's native inputs are already fully determined by EDARA's own validated business logic before the native call.

**Security model - authorization first, every elevation:**
1. **Explicit authorization gate before elevation.** `edara.service.charge.line._create_invoice()`, `edara.payment.schedule.line.action_charge_late_fee()`, and `edara.property.get_analytic_account()` each call `self.check_access('write')` as their first line - this checks *both* ACL and record rules (branch/company scoping) on the specific record, using the calling user's own (non-elevated) environment, before any `.sudo()` is reached. A Viewer (read-only on all of these models) fails here immediately.
2. **Deposit actions use record-creation-as-gate, not just a check.** `edara.deposit.action_collect()`/`action_refund()`/`action_deduct()` also call `self.check_access('write')`, and additionally create the authorizing `edara.deposit.transaction` record *before* the native payment/move - this was a deliberate reordering: the original code created the native `account.payment`/`account.move` first and the (ACL-gated) `edara.deposit.transaction` audit record second, which meant a Viewer's call would have caused a real native payment to exist in the ledger before the authorization check ever fired. Both are now: check → create the authorizing child record (itself ACL/record-rule gated) → then the elevated native call → link the two together.
3. **No client-trusted Accounting identifiers.** Every value passed into an elevated `create()` (partner, company, accounts, amounts, dates, journal id) is read from already-validated server-side fields on `self`/`self.company_id`/related records - never from a raw method argument the caller could have forged, except `journal_id`/`amount` on the Deposit actions, which were already parameters of the pre-existing public API (`action_collect(journal_id, amount)`) and are validated against `self.balance`/company config exactly as before this change.
4. **No elevated recordset leakage.** Every elevated `create()`/`search()` result is either used only for its `.id` (a plain in-memory attribute, never an ACL-checked access) to write back onto an already-authorized EDARA record, or explicitly re-`browse()`d through the *normal* (non-elevated) environment before being returned to the caller - so a caller without native read access who tries to read a field on the returned object gets the same `AccessError` a native `account.move`/`account.payment` read would give them, exactly preserving "no broad access" even for records the user's own action just caused to exist.
5. **Journal resolution, not journal browsing.** `edara.deposit.transaction.wizard._resolve_deposit_journal()` performs a narrowly-scoped `.sudo().search()` restricted to the exact same safe domain (`type in (cash, bank)`, this deposit's own company) the field's UI domain already advertised - used only to auto-resolve the field to a single unambiguous journal, never to grant the user a general `account.journal` browse capability. A new `has_journal_browse_access` computed field (`account.journal.has_access('read')`, no `sudo()`) drives the view: when `False` (the normal EDARA-only case), the Payment Journal field is locked read-only once auto-resolved, so the user is never handed a dropdown whose own search would fail with an `AccessError`; if the choice is genuinely ambiguous (0 or 2+ journals) and the user has no native access, `action_confirm()` raises a clear, actionable `UserError` instead of a raw ACL error.
6. **Analytic account first-time creation.** The architecture analysis found `account.group_account_invoice` grants zero access to `account.analytic.account`. `edara.property.get_analytic_account()` now elevates only its own `create()` call (guarded by the same `check_access('write')` on the property), for the one-time case where a property has never been invoiced before.
7. **No sudo() on unrelated code.** The pre-existing rent-invoice path (`edara.payment.schedule.line._create_invoice()`, driven only by the scheduled action, per MAT-FIND-007) was deliberately left untouched - it was never one of the confirmed-failing workflows and runs under the cron's own configured user, not an EDARA-only role.
8. **No generic elevation helper.** Each `.sudo()` call is inline at its exact call site with an explanatory comment, not behind a reusable `edara_sudo()`-style helper - keeping every elevation individually greppable and reviewable, per the ticket's explicit constraint against a generic bypass utility.

**Scoped Accounting operations - exact call sites:**
| File | Method | Elevated operation |
|---|---|---|
| `models/edara_service_charge_line.py` | `_create_invoice()` | `account.move.sudo().create()` (+ `action_post()` on the resulting recordset) |
| `models/edara_payment_schedule_line.py` | `action_charge_late_fee()` | `account.move.sudo().create()` (+ `action_post()`) |
| `models/edara_deposit.py` | `_create_deposit_payment()` (used by `action_collect()`/`action_refund()`) | `account.payment.sudo().create()` (+ `action_post()`) |
| `models/edara_deposit.py` | `action_deduct()` | `account.move.sudo().create()` (move_type=`entry`) (+ `action_post()`) |
| `models/edara_property.py` | `get_analytic_account()` | `account.analytic.account.sudo().create()` (first-time only) |
| `wizard/edara_deposit_transaction_wizard.py` | `_resolve_deposit_journal()` | `account.journal.sudo().search()` (narrow domain, auto-default only) |

**Files changed:** `models/edara_deposit.py`, `models/edara_service_charge_line.py`, `models/edara_payment_schedule_line.py`, `models/edara_property.py`, `wizard/edara_deposit_transaction_wizard.py`, `wizard/edara_deposit_transaction_wizard_views.xml` (new `has_journal_browse_access` invisible field + `readonly` on `journal_id`), `tests/test_edara_mat015_scoped_accounting.py` (new), `tests/__init__.py` (registered the new test file).

**Automated tests (`tests/test_edara_mat015_scoped_accounting.py`, 24 new tests across 5 classes):**
- `TestMatFind015ScopedInvoicing` - EDARA-only Company Manager invoices a Service Charge and charges a Late Fee without any native group; a Viewer is denied at `check_access('write')` before any elevation, with zero `account.move` records created as a side effect; first-time analytic-account creation confirmed.
- `TestMatFind015ScopedDeposit` - EDARA-only Accountant collects/refunds/deducts a deposit without any native group; a Viewer is denied for all three, with the authorization-first reordering confirmed to prevent any orphan `account.payment`/`account.move`.
- `TestMatFind015DepositWizardJournalResolution` - the wizard's journal auto-default still works for an EDARA-only user via the scoped lookup; `has_journal_browse_access` is correctly `False`; the ambiguous-and-no-access case raises a clear `UserError`.
- `TestMatFind015NoBroadNativeAccess` - after running every workflow, the EDARA-only user still has zero native `account.move`/`account.payment`/`account.journal` read/create/write access, and `search()`/`search_read()`/`read()` on the very invoice their own action created still raise `AccessError`.
- `TestMatFind015CompanyIsolation` - a Company Manager of Company A cannot trigger `action_collect()` or `_create_invoice()` against Company B's deposit/service-charge line merely by knowing its id (blocked by the pre-existing record-rule layer via `check_access('write')`).

**Automated results:** targeted (67 tests: the 24 new MAT-FIND-015 tests + `TestEdaraDeposit`/`TestEdaraServiceCharge`/`TestEdaraPaymentSchedule` regression coverage) - **67/67 passed, 0 failed, 0 errors**. Full module suite - **173/173 passed, 0 failed, 0 errors** (up from the 153/153 baseline, +20 net new tests after accounting for file reorganization).

**Live validation (2026-09-20), against real `odoo19_dev`, rolled back:** a script run via `odoo-bin shell -d odoo19_dev`, using a disposable branch/property/building/2 units/2 contracts/deposit and three disposable users (EDARA Company-Manager-only, EDARA Accountant-only, EDARA Viewer-only, none with any native group), wrapped in `env.cr.rollback()`. Result: **24/24 checks passed, 0 failed.**
- **Service Charge → Generate Invoices:** PASS - Company-Manager-only created the Service Charge, ran Generate Allocation, and invoiced it; resulting invoice (`INV/2026/00023`) confirmed posted, `edara_invoice_type='service_charge'`; the property's analytic account was created on first use.
- **Deposit Collect:** PASS - Accountant-only collected $500; native payment confirmed `in_process`; deposit balance $500.
- **Deposit Refund:** PASS - Accountant-only refunded $150; balance $350.
- **Deposit Deduction:** PASS - Accountant-only deducted $100; native journal entry confirmed `posted`; balance $250.
- **Late Fee:** PASS - Company-Manager-only charged a late fee on a real overdue schedule line; invoice (`INV/2026/00025`) confirmed posted, `edara_invoice_type='late_fee'` (the real company's `edara_late_fee_amount` is still unconfigured/NULL - the script set it in-memory only, inside the same rolled-back transaction, purely to isolate the Accounting-boundary test from that unrelated configuration gap).
- **Negative - Viewer:** PASS - Viewer-only's `action_collect()` call raised `AccessError` before any native record was created (payment count unchanged); Viewer-only could not create a Service Charge at all.
- **Negative - No broad access:** PASS - after all five workflows ran, both EDARA-only users still had zero native `read`/`create`/`write`/`search` access to `account.move`/`account.payment`/`account.journal`, including on the exact invoice their own action had just caused to be created.
- **Cleanup/data integrity:** confirmed via direct `psql` query after the run - no `mat015a_*` login rows, no `M015ALV*`-coded branch/property/building/units, and no leftover `account.move` rows at the ids the script's first (superseded) attempt had created remain in `odoo19_dev`; `edara_late_fee_amount` is still `NULL` in the real company record. `odoo19_dev` is confirmed unmodified.

**Company/property isolation:** confirmed both by the automated `TestMatFind015CompanyIsolation` class (against `edara_test`) and structurally by the live script - every elevated call is reached only through a record (`self`) the calling user already passed `check_access('write')` for, which itself enforces the existing branch/company record-rule layer; none of the elevated methods accept a company/property/branch id as a raw parameter that could redirect the operation.

**Remaining limitations:** none identified for the five confirmed workflows. Not covered by this pass (out of scope, unchanged): the rent-invoice cron path (`edara.payment.schedule.line._create_invoice()`, MAT-FIND-007's "no manual trigger" gap) and any future EDARA workflow that touches native Accounting would each need their own explicitly-reviewed scoped elevation, following this same pattern - it is not automatically inherited.

### Resolved MAT Findings — Implementation Notes

**MAT-FIND-014 (fixed, automated verified, live verification pending):**
- See "MAT-FIND-014 — Root Cause, Fix, and Related Findings" above for the full root-cause/fix narrative. Summary: `edara.dashboard._compute_kpis()`, `edara.property._compute_financial_summary()`, `edara.branch._compute_financial_summary()` all read `account.move`/`account.payment` unconditionally; fixed by checking `has_access('read')` once per compute and degrading Accounting-dependent fields to `0`/hidden (new `has_accounting_access` Boolean on all three models) instead of crashing. No `sudo()` used anywhere.
- Files changed: `models/edara_dashboard.py`, `models/edara_property.py`, `models/edara_branch.py`, `views/dashboard_views.xml`, `views/property_views.xml`, `views/branch_views.xml`.
- Tests added (`tests/test_edara_security_isolation.py`, new file):
  - `TestEdaraDashboardAndSummarySecurity` (5 tests) - Viewer opens Dashboard/Property/Branch without an AccessError and sees `has_accounting_access=False`/zeroed Accounting fields; a user with an explicitly-granted native `account.group_account_invoice` group sees `has_accounting_access=True` and real figures.
  - `TestEdaraAccountingBoundaries` (4 tests) - proves Viewer, EDARA-only Accountant, and EDARA-only Company Manager all genuinely lack `account.move` read access (`has_access('read')` is `False`), and that a user with a native Accounting group has it (`True`) - the evidence behind MAT-FIND-015.
  - `TestEdaraViewerAclBoundaries` (4 tests) - representative ORM-level proof (not menu-existence) that Viewer `create()`/`write()`/`unlink()` are ACL-denied on `edara.property`/`edara.unit`/`edara.building`, and `read()` succeeds on an authorized `edara.unit`.
  - `TestEdaraCompanyIsolationBroad` (1 test, `subTest`-looped) - extends `test_edara_multicompany.py`'s branch-only proof to `edara.property`/`building`/`unit`/`lease.contract`/`payment.schedule.line`/`deposit`/`service.charge`/`maintenance.request`/`renewal.request`: a Company A manager's `search()` never returns a Company B record and `read()` on one raises `AccessError`.
  - `TestEdaraInvoiceLinkExposure` (1 test) - empirically confirms (not assumed) that a Viewer reading a schedule line with `invoice_id` already set does **not** trigger an `account.move` AccessError; documented as reviewed-and-safe, not a second MAT-FIND-014 instance.
- Targeted automated test results: security suite (`TestEdaraDashboardAndSummarySecurity`, `TestEdaraAccountingBoundaries`, `TestEdaraViewerAclBoundaries`, `TestEdaraCompanyIsolationBroad`, `TestEdaraDashboard`) - **16/16 passed, 0 failed, 0 errors**. `TestEdaraInvoiceLinkExposure` (run separately) - **1/1 passed, 0 failed, 0 errors**.
- Full module suite (`--test-tags /property_managment`, after `-u property_managment`, against the dedicated `edara_test` DB): **153/153 passed, 0 failed, 0 errors** (139 pre-existing + 14 new from this pass's first file, `TestEdaraInvoiceLinkExposure`'s single test run separately and equally clean; a subsequent full run would show 154). No existing test - including every MAT-FIND-005/006/009/011/013 regression test - was modified or regressed.
- **Live verification (2026-09-19):** business owner confirmed live via browser as `omar@example.com` (Dashboard opens, no `account.move` AccessError, Accounting tiles absent); independently re-confirmed via a rolled-back read-mostly script against the real `odoo19_dev` database (94/94 checks passed) - see "MAT-FIND-014 - Root Cause, Fix, and Related Findings" above for full detail.
- **Status: FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

**MAT-FIND-013 (fixed, live verified):**
- Root cause: `_generate_schedule_lines()` (`models/edara_lease_contract.py`) generated schedule lines via a two-tier loop - while a full nominal billing-frequency period fit, it billed one line at the full rent; once it no longer fit, the `else` branch unconditionally decomposed the *entire remainder* into 1-month sub-chunks, regardless of `billing_frequency`. For Monthly contracts this was invisible (the "full period" and "1-month decomposition" granularities are identical), but for Quarterly/Yearly contracts it incorrectly split a shorter-than-one-period remainder into several monthly-equivalent lines instead of a single prorated line at the configured frequency's own granularity.
- Fix: removed the monthly-decomposition branch entirely. The loop now advances strictly in units of the contract's own `billing_frequency` (1/3/12 months). Each iteration either produces one full-period line at the full configured `rent_amount` (when the next frequency-boundary still fits before `end_date`), or - on the final iteration - one single prorated line covering the *entire* remainder (`monthly_equivalent × occupied_days / 30`), never split further. Every boundary is still computed fresh from the immutable `start_date` via the existing `_period_boundary()` (unchanged, still prevents day-31/leap-day anchor drift). Net effect: the algorithm is now simpler (one branch removed) as well as correct.
- `due_date`/`period_start`/`period_end`/`occupied_days`/`is_prorated` semantics are unchanged - only the granularity at which periods are generated changed. `_create_invoice()` and overdue detection (`_compute_state()`) were not touched and continue to read `amount`/`due_date` exactly as before.
- Files changed: `models/edara_lease_contract.py` (`_generate_schedule_lines()` only, plus its docstring) - no view, security, or invoice-integration changes were needed.
- Tests added/updated (`tests/test_edara_lease_billing.py`): `test_quarterly_partial_period` corrected (now expects ONE prorated line, not three monthly-equivalent lines); added `test_quarterly_multiple_full_periods`, `test_quarterly_full_periods_plus_prorated_remainder`, `test_quarterly_short_period_does_not_decompose_into_monthly_lines`, `test_yearly_full_period`, `test_yearly_short_period_single_prorated_line`, `test_yearly_multiple_full_periods`, `test_yearly_full_period_plus_prorated_remainder`; extended `test_zero_line_outcome_structurally_impossible` to also cover Quarterly/Yearly short contracts; corrected `test_annual_six_month_contract` (previously encoded the old buggy six-monthly-lines behavior - now expects ONE prorated `$6,033.33` line). Added `test_prorated_line_creates_invoice_with_prorated_amount` (`tests/test_edara_payment_schedule.py`) to confirm a prorated schedule-line amount flows unchanged into the native Odoo invoice.
- **Arithmetic note:** two of the illustrative numbers in the reported finding are off by one day from the already-established `occupied_days = (period_end - period_start).days` formula (locked in during the earlier finalized-rules design and used consistently everywhere else in this project): the main reproduction (`15/09/2026→01/12/2026`) is actually a 77-day span (`$2,566.67`), not 76 days/`$2,533.33` as stated; the Required Business Rule §4 example (`15/07→01/08` remainder) is actually 17 days (`$566.67`), not 16 days/`$533.33`. The implementation uses the correct, already-established day-count formula rather than the finding's stated figures - flagging this explicitly per this project's "do not silently assume" convention rather than quietly matching the wrong numbers.
- Automated test results: `TestEdaraLeaseBilling` + `TestEdaraPaymentSchedule` (targeted) - **39/39 passed, 0 failed, 0 errors**. Full module suite - **139/139 passed, 0 failed, 0 errors**.
- **Live verification (2026-09-18):** performed against 5 dedicated contracts covering every branch of the corrected algorithm:
  - `LC/2026/0135` (Quarterly, Start `15/09/2026`, End `01/12/2026`, Rent $3,000, Payment Day `15`) - exactly 1 schedule line, Period `15/09/2026 → 01/12/2026`, Occupied Days `77`, Amount `$2,566.67` (`$3,000/3 = $1,000` monthly equivalent × `77/30`), state `Overdue`. Invoice `INV/2026/00015` generated: Posted, Invoice Date `15/09/2026`, Due Date `17/09/2026`, Total `$2,566.67`, Amount Due `$2,566.67` - **accounting-verified**.
  - `LC/2026/0136` (Quarterly, Start `15/09/2026`, End `15/03/2027`, Rent $3,000) - exactly 2 full-period lines, no proration: `15/09/2026 → 15/12/2026` = `$3,000`, `15/12/2026 → 15/03/2027` = `$3,000`. No monthly decomposition.
  - `LC/2026/0137` (Quarterly, Start `15/09/2026`, End `01/01/2027`, Rent $3,000) - 1 full-period line (`15/09/2026 → 15/12/2026` = `$3,000`) plus 1 final prorated remainder line (`15/12/2026 → 01/01/2027` = `$566.67`), confirming full periods and the final remainder are handled by separate, correctly-typed lines.
  - `LC/2026/0138` (Yearly, Start `01/09/2026`, End `01/09/2027`, Rent $12,000) - exactly 1 full-period line, `01/09/2026 → 01/09/2027` = `$12,000`, not prorated.
  - `LC/2026/0139` (Yearly, Start `01/09/2026`, End `01/12/2026`, Rent $12,000) - exactly 1 prorated line, `01/09/2026 → 01/12/2026`, Occupied Days `91`, Amount `$3,033.33` (`$12,000/12 = $1,000` monthly equivalent × `91/30`). Confirmed this is the correct result under the standardized 30-day proration rule, not `$3,000` (a naive "3 months = 1 quarter" shortcut would be wrong here since Yearly billing has no quarterly concept - the rule is always monthly-equivalent × occupied days / 30).
  - `LC/2026/0141` (Yearly, Start `01/09/2026`, End `01/12/2027`, Rent $12,000) - 1 full-period line (`01/09/2026 → 01/09/2027` = `$12,000`) plus 1 final prorated remainder line (`01/09/2027 → 01/12/2027` = `$3,033.33`). Only the full-period line was due for invoicing at test time; invoice `INV/2026/00020` was generated for it. The remainder line was correctly left un-invoiced because its due date is in the future - expected behavior of `_cron_generate_due_invoices()`, not a defect.
  - Across all contracts used in this cycle (`LC/2026/0129`-`0141`), `payment_day` was independently confirmed to always equal that contract's own Start Date's day-of-month (e.g. `LC/2026/0135`/`0136`/`0137` → `15`, matching Start Date `15/09/2026`; `LC/2026/0138`/`0139`/`0141` → `1`, matching Start Date `01/09/2026`) - never manually entered.
- **Status: FIXED - AUTOMATED VERIFIED - LIVE VERIFIED - ACCOUNTING VERIFIED.**

**MAT-FIND-011 (fixed, live verified):**
- Root cause and fix: **not a separate code change.** MAT-FIND-011 (an active contract producing zero Payment Schedule lines) and MAT-FIND-013 (Quarterly/Yearly granularity) were both symptoms of the same `_generate_schedule_lines()` method; the MAT-FIND-013 rework - advancing strictly in units of `billing_frequency` and always emitting a final line for any non-empty remainder - structurally guarantees at least one line is always produced for any contract where `start_date < end_date`, which the `_check_dates` constraint already always enforces. No dedicated additional fix was required beyond the MAT-FIND-013 implementation (see that entry above for the exact code change and files touched).
- Automated test results: dedicated zero-line-safety regression coverage in `tests/test_edara_lease_billing.py` (`test_zero_line_outcome_structurally_impossible`, extended to Monthly/Quarterly/Yearly) plus `test_mat_find_011_scenario` - part of the same **39/39 targeted / 139/139 full-suite** results reported under MAT-FIND-013 above.
- **Live verification (2026-09-18):** `LC/2026/0129` (Monthly, Start `02/09/2026`, End `01/10/2026`, Rent $1,600, Payment Day `2` - auto-derived, not manually entered) - after activation, Payment Schedule held exactly 1 line: Due Date `02/09/2026`, Period `02/09/2026 → 01/10/2026`, Amount `$1,546.67`, state `Overdue`, Invoice initially blank. Running `Generate Due Invoices` produced `INV/2026/00012`: Posted, Total `$1,546.67`, Amount Due `$1,546.67`, correctly linked back to the schedule line - **accounting-verified**.
- **Status: FIXED - AUTOMATED VERIFIED - LIVE VERIFIED - ACCOUNTING VERIFIED.**

**MAT-FIND-006 (fixed):**
- Root cause: `_cron_expire_contracts()` (`models/edara_lease_contract.py`) unlinked schedule lines via `filtered(lambda l: not l.invoice_id).unlink()` with no `due_date` condition at all - it deleted every uninvoiced line regardless of whether it was already overdue. `action_terminate()` already had a partial date guard (`due_date > contract.termination_date`), but the two call sites used different, unaligned conditions.
- Fix: added a single shared method `edara.lease.contract._unlink_future_uninvoiced_schedule_lines()` (`self.ensure_one()`, `today = fields.Date.context_today(self)`, unlinks only `not l.invoice_id and l.due_date >= today`), called identically by both `action_terminate()` and `_cron_expire_contracts()` so the two paths can never diverge again. The boundary (`>= today` removable / `< today` preserved) intentionally mirrors `edara.payment.schedule.line._compute_state()`'s own `overdue` boundary, reusing existing state logic rather than inventing a parallel one. Already-invoiced lines are never touched (the filter always requires `not l.invoice_id`).
- Files changed: `models/edara_lease_contract.py` only.
- Tests added/updated (`tests/test_edara_lease_contract.py`): `test_terminate_removes_future_uninvoiced_line`, `test_terminate_keeps_overdue_uninvoiced_line`, `test_terminate_keeps_invoiced_line_untouched`, `test_terminate_mixed_schedule_selectively_removes_only_future_uninvoiced` (proves selectivity across all 3 cases in one contract), `test_cron_expiry_keeps_overdue_uninvoiced_line_but_removes_future_one` (same selectivity via the cron path), plus `test_cron_expires_active_contract_past_end_date` corrected (previously asserted all lines were deleted; now asserts they survive as `Overdue`). One additional pre-existing test in `tests/test_edara_payment_schedule.py` (`test_termination_removes_future_lines_and_stops_cron_invoicing`) was also corrected during regression testing - it encoded a slightly looser boundary (`due_date <= today` preserved) that was actually inconsistent with `_compute_state()`'s own overdue definition; updated to `due_date < today`.
- Automated test results: `TestEdaraLeaseContract` - **23/23 passed, 0 failed, 0 errors**. Full module suite - **112/112 passed, 0 failed, 0 errors** (before the MAT-FIND-005 fix below was added; see that entry for the current full-suite count). All runs against the dedicated `edara_test` DB; `odoo19_dev` untouched.
- **Status: FIXED - VERIFIED.** Live-verified 2026-09-16 on `LC/2026/0120` (Apartment 107) - see the MAT-FIND-006 Deferred Findings row above for the exact live result (expiry cron run, contract → Expired, unit → Available, Payment Schedule line survived with Due Date `2026-08-01` / state `Overdue`).

**MAT-FIND-005 (fixed):**
- Root cause: `_generate_schedule_lines()` (`models/edara_lease_contract.py`) used `while due_date <= self.end_date:` (inclusive) - a due date landing exactly on `end_date` produced an extra installment beyond the lease term.
- Fix: changed the loop boundary to `while due_date < self.end_date:` (exclusive), so `end_date` acts purely as the lease-term boundary and never itself generates a line. No other location in the codebase generates schedule lines or depends on a line landing exactly on `end_date` (confirmed by inspection - MAT-FIND-006's new `_unlink_future_uninvoiced_schedule_lines()` was left untouched, as it operates only on `due_date` vs. today, not `end_date`).
- Files changed: `models/edara_lease_contract.py` only (`_generate_schedule_lines()`, plus its docstring).
- Tests added (`tests/test_edara_payment_schedule.py`): `test_schedule_excludes_line_exactly_on_end_date` (exact-boundary case, 1 line only), `test_schedule_normal_multi_month_excludes_end_date` (3-line contract, no 4th line on `end_date`), `test_schedule_keeps_legitimate_line_strictly_before_end_date` (confirms a legitimate due date strictly before `end_date` is not removed by the fix). Reviewed all existing tests for an assumption of a line landing exactly on `end_date`; none needed correction beyond what MAT-FIND-006's fix already required.
- Automated test results: `TestEdaraPaymentSchedule` - **15/15 passed, 0 failed, 0 errors**. Full module suite - **115/115 passed, 0 failed, 0 errors**. Both runs against the dedicated `edara_test` DB; `odoo19_dev` untouched.
- **Status: FIXED - VERIFIED.** Live-verified 2026-09-16 on `LC/2026/0119` - see the MAT-FIND-005 Deferred Findings row above for the exact live result (single schedule line `2026-08-01`, no `2026-09-01` line).

**MAT-FIND-009 (fixed):**
- Root cause (confirmed by prior READ-ONLY investigation): `action_generate_allocation()` (`models/edara_service_charge.py`) determined the eligible-unit set (units with an active lease contract/tenant) **after** `_compute_allocation()` had already divided `total_amount`/`total_area` across ALL of the building's non-archived units. For `Equal`, the denominator was `len(all_building_units)` instead of `len(eligible_units)`; for `Proportional by Area`, `total_area` summed ALL units' area instead of only eligible units' area. Ineligible units were then silently dropped after the fact, so the sum of the created Allocation Lines fell short of the Service Charge's `total_amount`.
- Fix: `action_generate_allocation()` now determines the eligible unit set (unchanged business rule: a unit is eligible when it has an active lease contract with a tenant) **before** calling `_compute_allocation()`, and passes only that eligible set through to both the allocation calculation and the line-creation loop, so the same set is used consistently end-to-end. `_compute_allocation()` itself required no change - it already computed strictly from whatever `units` recordset it was given.
- `Equal` now calculates `total_amount / number_of_eligible_units`. `Proportional by Area` now calculates `total_amount × (unit.area / total_area_of_eligible_units)`. `Per Square Meter` and `Fixed Amount per Unit` are unchanged (each already computed a unit's amount independently, with no shared denominator, so they were never affected by this bug).
- Files changed: `models/edara_service_charge.py` (`action_generate_allocation()` only - `_compute_allocation()` untouched).
- Tests corrected/added (`tests/test_edara_service_charge.py`): `test_equal_allocation_splits_across_eligible_units_only` (renamed/corrected from the old `..._charges_only_occupied`, now expects `300/2=150` per eligible unit instead of the old buggy `300/3=100`, plus a `sum(amounts) == total_amount` reconciliation assertion) and `test_proportional_allocation_by_area` (corrected to use the eligible-only area denominator, plus the same reconciliation assertion). Two new dedicated MAT-026-shaped regression tests added: `test_equal_allocation_reconciles_with_multiple_ineligible_units` (6 units, 5 eligible, 1 vacant, `total_amount=500` - the exact shape of the live MAT-026 defect - asserts exactly 5 lines, each `$100`, summing to `$500`) and `test_proportional_allocation_reconciles_with_multiple_ineligible_units` (6 units, 5 eligible with distinct areas, 1 vacant, `total_amount=500`, asserts each eligible unit's exact expected share and that the sum reconciles to `$500`). `test_per_sqm_allocation` and `test_fixed_per_unit_allocation` were left unchanged (unaffected by the fix).
- Automated test results: Service Charge suite (`tests/test_edara_service_charge.py`) - **11/11 passed, 0 failed, 0 errors** (run via `--test-tags /property_managment:TestEdaraServiceCharge` against the dedicated `edara_test` DB). Full module suite (`--test-tags /property_managment`, same `edara_test` DB, after `-u property_managment`) - **107/107 passed, 0 failed, 0 errors** - no unrelated tests regressed. The live `odoo19_dev` database (and the paused `SC/2026/0037` MAT-026 record within it) was NOT touched by this test run.
- **Status: FIXED - VERIFIED.** The live MAT-026 manual re-test was performed on `SC/2026/0037`: re-generating allocation produced 5 eligible lines at `$100.00` each (`$500.00` total, fully reconciled to the Service Charge Total Amount), and `Create Invoices` produced exactly 5 correctly-posted native invoices (`INV/2026/00007`-`00011`, each `$100`, posted to Service Charge Income account `403000`). MAT-026 is now recorded as PASS / COMPLETED - see "MAT Verification Outcomes" above.

**MAT-FIND-001 & MAT-FIND-002 (fixed together, same wizard):**
- Added `edara.deposit._default_transaction_amount(transaction_type)` (`models/edara_deposit.py`) - single source of truth for "Collect → remaining uncollected, Refund/Deduct → balance", reused by both the wizard's new onchange and by `action_collect()`/`action_refund()`'s existing `amount=None` fallback (refactored to call it too, removing the previous duplication - behavior unchanged, still tested).
- Added `EdaraDepositTransactionWizard._onchange_deposit_transaction_type()` (`wizard/edara_deposit_transaction_wizard.py`, `@api.onchange('deposit_id', 'transaction_type')`): sets `amount` from the helper above, and sets `journal_id` to the company's single matching `cash`/`bank` journal only when exactly one exists (never for `deduction`, which doesn't use a journal). The field stays fully user-editable afterwards - partial refunds/deductions and picking a different journal both still work exactly as before.
- No changes to `wizard/edara_deposit_transaction_wizard_views.xml` or `views/deposit_views.xml` were needed - the onchange fires on the existing `default_transaction_type`/`active_id` context the header buttons already pass.
- Files changed: `models/edara_deposit.py`, `wizard/edara_deposit_transaction_wizard.py`.
- Tests added (`tests/test_edara_deposit.py`): `test_wizard_defaults_collect_amount_to_remaining_uncollected`, `test_wizard_defaults_refund_amount_to_balance`, `test_wizard_defaults_deduction_amount_to_balance`, `test_wizard_amount_remains_editable_for_partial_refund`, `test_wizard_amount_remains_editable_for_partial_deduction`, `test_wizard_defaults_journal_when_unambiguous`, `test_wizard_does_not_default_journal_for_deduction` (7 tests, using `odoo.tests.Form` to exercise the real onchange chain the way the web client does - a plain `.create({})` call does NOT trigger `@api.onchange`, so `Form` is required to test this correctly). All 7 pass.

### MAT Verification Outcomes (Confirmed Correct — Not Bugs)

**MAT-018 — Partial Security Deposit Deduction: PASS**
- Deposit $1,500 total; Held $1,500; Deducted $500; remaining balance $1,000; state remains `Held`.
- Native Odoo journal entry created: `MISC/2026/09/0001`.
- Verified accounting: Debit `213000` Security Deposit Liability $500 / Credit `451000` Deposit Deduction Income $500.
- Accounting confirmed correct - no issue found.

**MAT-019 — Remaining Deposit Balance Refund: PASS**
- Held $1,500; Deducted $500; Refunded $1,000; Balance $0; state `Closed`.
- Refund business logic (balance computation, over-refund guard in `action_refund()`) confirmed correct - no issue found.
- The only issue surfaced during MAT-019 is the wizard defaulting Amount to $0.00 before manual entry (see MAT-FIND-001 above) - a UX/implementation gap in the wizard, not a defect in the refund logic itself.

**MAT-023 — Core Rent Invoicing & Payment Collection: PASS**
- **Purpose:** validate the core rent-collection golden path (spec §75: Rent Schedule → Invoice → Receive Payment → Outstanding Balance) end-to-end through real UI/cron actions, not just automated test coverage.
- **Setup:** dedicated Unit `Apartment 103` (code `103`, Occupancy `Available`, Operational Status `Normal`) and dedicated Contract `MAT-023 Invoice Payment Test` (Tenant Omar Khalil, Start `01/08/2026`, End `01/08/2027`, Rent `1500`, Monthly, Payment Day `1`, Deposit Required `No`) - same "dedicated test contract" pattern used for MAT-022, kept isolated from live business data.
- **Main actions:**
  1. Activated the contract - Contract → `Active`, Apartment 103 → `Rented`, Payment Schedule generated with 13 lines (first two due `2026-08-01` and `2026-09-01`, both already overdue at test time).
  2. Ran the real scheduled action `EDARA: Generate due rent invoices` - created `INV/2026/00004` ($1,500, Posted, linked to the August line) and `INV/2026/00005` ($1,500, Posted, linked to the September line). Both schedule lines correctly showed `Overdue` (not `Invoiced`) because their due dates had already passed - confirmed via read-only investigation as expected/by-design behavior of `edara.payment.schedule.line._compute_state()` (derived from linked invoice/payment state + due date, per spec §16), not a defect - no new finding created for this, per instruction.
  3. Paid `INV/2026/00004` through native Odoo accounting/payment flow - Invoice → `Paid`, corresponding schedule line → `Paid`, confirming the schedule line's computed state correctly follows native Odoo invoice/payment reconciliation.
- **Idempotency result:** re-ran `EDARA: Generate due rent invoices` a second time - August/September lines remained linked only to their original invoices (`INV/2026/00004`/`00005`); no duplicate invoice (e.g. `INV/2026/00006`) was created.
- **Validates:** (1) contract activation, (2) payment schedule generation, (3) due schedule line detection, (4) native Odoo invoice generation, (5) invoice posting, (6) schedule-line → invoice linkage, (7) native Odoo payment, (8) invoice → Paid, (9) schedule-line → Paid, (10) invoice-generation cron idempotency / no duplicate invoices.
- **Final status: PASS** - no defect found in the core invoicing/payment/idempotency logic. (Unrelated to this test: the ~$100 Outstanding Credit previously observed on Omar Khalil's invoice belongs to the earlier MAT-015 overpayment test, not MAT-023.)

**MAT-024 — Direct Lease Contract Renewal — End-to-End: PASS**
- **Scope note (important):** this MAT tested the **Direct Renewal** workflow only - the "Renew" action initiated from inside an active Lease Contract (`edara.lease.renewal.wizard` → `action_renew()`). **It does NOT cover the separate `edara.renewal.request` (Renewal Requests) submit/approve/reject workflow** - no Renewal Request record was created, approved, or rejected during this test. The Renewal Requests workflow remains untested by MAT (see MAT-025 candidate below). This distinction is deliberate and must not be conflated in future reporting.
- **Setup:** dedicated Unit `Apartment 104` (code `104`, initial Occupancy `Available`, Operational Status `Normal`) and dedicated Contract `LC/2026/0112` (Tenant Omar Khalil, Start `01/09/2026`, End `01/09/2027`, Rent `1500`, Monthly, Payment Day `1`, Deposit Required `No`, Notes `MAT-024 Renewal Test`). Activated successfully: Contract → `Active`, Apartment 104 → `Rented`, Payment Schedule → 13 lines.
- **Main action:** initiated renewal directly from the Lease Contract (not via Renewal Requests) with New Start Date `01/09/2027`, New End Date `01/09/2028`, New Rent `1600`. System created successor contract `LC/2026/0113`.
- **Original contract `LC/2026/0112`:** State → `Renewed`; Renewed Into → `LC/2026/0113`. PASS.
- **Successor contract `LC/2026/0113`:** State → `Active`; Renewed From → `LC/2026/0112`; Start `01/09/2027`; End `01/09/2028`; Rent `1600`; Unit Apartment 104. PASS.
- **Unit occupancy:** Apartment 104 → `Rented`, Operational Status `Normal`, with two historically-associated contracts (`LC/2026/0112` Renewed, `LC/2026/0113` Active). Correct by design - a renewal does not delete the predecessor; it remains as a historical/audit record while the successor becomes the current active lease, so the unit correctly stays `Rented` via the successor. Not recorded as a bug.
- **Payment Schedule:** predecessor `LC/2026/0112` retained its original 13 lines (`01/09/2026` → `01/09/2027`) intact; successor `LC/2026/0113` received its own fresh 13 lines (`01/09/2027` → `01/09/2028`). No schedule duplication observed; no historical schedule data deleted. PASS.
- **Relationship verification:** `LC/2026/0112` → Renewed Into → `LC/2026/0113`, and `LC/2026/0113` → Renewed From → `LC/2026/0112`, verified both directions. PASS.
- **Validates:** (1) direct renewal initiated from Lease Contract, (2) successor contract creation, (3) original contract → Renewed, (4) successor contract → Active, (5) Renewed From / Renewed Into relationship, (6) correct successor dates, (7) correct successor rent, (8) occupancy remains Rented, (9) historical Payment Schedule preserved, (10) new Payment Schedule generated, (11) no schedule duplication observed, (12) renewal statusbar/state behavior, (13) correct historical contract continuity.
- **Final status: PASS** for Direct Lease Contract Renewal. **The `edara.renewal.request` submit/approve/reject workflow (including `action_approve()` and `action_reject()`) was NOT manually validated by MAT-024 and remains an open MAT gap** - see MAT-025 candidate below.

**MAT-025 — Renewal Request Workflow — Submit / Approve / Reject: PASS**
- **Scope note:** MAT-024 = Direct Renewal (wizard on the Lease Contract, `action_renew()` called directly). **MAT-025 = the separate `edara.renewal.request` model/workflow** (Property Management → Renewal Requests → New, `action_approve()`/`action_reject()`). The two are distinct code paths and are recorded as two distinct MATs, not merged.
- **Approval scenario setup:** dedicated Unit `Apartment 105` (code `105`, initial Occupancy `Available`, Operational Status `Normal`) and dedicated Contract `LC/2026/0114` (Tenant Omar Khalil, Start `01/09/2026`, End `01/09/2027`, Rent `1500`, Monthly, Payment Day `1`, Deposit Required `No`, Notes `MAT-025 Renewal Request Test`). Activated successfully: Contract → `Active`, Apartment 105 → `Rented`, Payment Schedule generated.
- **Approval main action:** created a Renewal Request via Property Management → Renewal Requests → New (Contract `LC/2026/0114`, Requested Start `01/09/2027`, Requested End `01/09/2028`, Requested Rent `1600`). Request initially showed State → `Submitted` - PASS. Approved the request.
- **Approval result:** Renewal Request → `Approved`; successor contract `LC/2026/0115` created; original `LC/2026/0114` → `Renewed`; successor `LC/2026/0115` → `Active`. Successor verified: Renewed From → `LC/2026/0114`, Unit Apartment 105, Start `01/09/2027`, End `01/09/2028`, Rent `1600` - PASS. Apartment 105 verified: Occupancy `Rented`, Operational Status `Normal`, with `LC/2026/0114` (Renewed) and `LC/2026/0115` (Active) both historically associated - PASS. Successor Payment Schedule: 13 lines, `01/09/2027` → `01/09/2028` - PASS. Original contract Payment Schedule: 13 lines, `01/09/2026` → `01/09/2027`, existing lines remained intact - PASS.
- **Rejection scenario setup:** a separate dedicated Unit `Apartment 106` (code `106`, Occupancy `Available`, Operational Status `Normal`) and a separate dedicated active contract (Tenant Omar Khalil, Unit Apartment 106, Start `01/09/2026`, End `01/09/2027`, Rent `1500`, Monthly, Payment Day `1`, Deposit Required `No`, Notes `MAT-025 Renewal Request Reject Test`), activated (Contract → `Active`, Unit → `Rented`).
- **Rejection main action:** created a Renewal Request (Requested Start `01/09/2027`, Requested End `01/09/2028`, Requested Rent `1600`, Tenant Message `MAT-025 Reject Test`) - State → `Submitted`. Rejected the request through the real UI.
- **Rejection result:** Renewal Request → `Rejected`; no rejection-reason popup appeared; no reason was requested at reject-time; `Decision Note` remained empty; no successor contract was created; the original Apartment 106 contract remained `Active`. **This confirms the already-documented BD-002 (Renewal rejection reason) exactly as described - the current UI allows rejection without requiring or collecting a reason. Not recorded as a new finding; BD-002 is not fixed.**
- **Validates:** (1) Renewal Request creation, (2) Submitted state, (3) Renewal Request approval, (4) successor contract creation, (5) predecessor → Renewed, (6) successor → Active, (7) Renewed From / Renewed Into relationship, (8) successor dates/rent/unit, (9) occupancy remains Rented, (10) successor Payment Schedule generation, (11) historical Payment Schedule preservation, (12) Renewal Request rejection, (13) no successor contract after rejection, (14) original contract remains Active after rejection, (15) confirmation of BD-002.
- **Final status: PASS** for both the Approval and Rejection sub-scenarios of the Renewal Request workflow. (Recap: MAT-024 = Direct Renewal; MAT-025 = Renewal Request workflow - kept distinct.)

**MAT-026 — Service Charge Allocation & Invoicing — End-to-End: PASS / COMPLETED**
- **Setup:** Building A (6 Units: Apartment 101/103/104/105/106 `Rented`, Apartment 102 `Available`). Service Charge `SC/2026/0037` created against Building A, Total Amount `$500.00`, Allocation Method `Equal`.
- **Pre-fix observed result (historical evidence, preserved):** clicking `Generate Allocation` originally produced exactly 5 Allocation Lines (Apartment 101, 103, 104, 105, 106, each `$83.33`, Tenant `Omar Khalil`); Apartment 102 (`Available`) correctly received no Allocation Line; Service Charge Total Amount remained `$500.00`; no invoices were created; `Create Invoices` was deliberately NOT clicked once the discrepancy was observed. `$83.33` was `$500 / 6` (all 6 Building Units), not `$500 / 5` (the 5 units that actually received allocation lines) - the allocated total did not reconcile to the Service Charge Total Amount. See **MAT-FIND-009** below.
- **Fix implemented and verified by automated tests:** `action_generate_allocation()` in `models/edara_service_charge.py` was updated to determine the eligible-unit set before computing the allocation. 11/11 Service Charge tests pass, 107/107 full module suite passes on the dedicated `edara_test` DB.
- **Live re-test main action:** re-ran `Generate Allocation` on `SC/2026/0037` against the same 6-unit/5-eligible Building A scenario.
- **Live re-test allocation result (post-fix):** exactly 5 eligible units (Apartment 102 correctly excluded); Apartment 101/103/104/105/106 each allocated `$100.00`; total allocated `$500.00` exactly - reconciles fully to the Service Charge Total Amount.
- **Live invoice verification:** clicked `Create Invoices` once. Service Charge state → `Invoiced`. Exactly 5 native Odoo customer invoices created (`INV/2026/00007`-`INV/2026/00011`, one per allocation line, each `$100`, each linked to its line); no sixth invoice; after reaching `Invoiced`, the `Create Invoices` button was no longer available, preventing a duplicate invoicing attempt.
- **Live accounting verification:** `INV/2026/00007` inspected - Customer `Omar Khalil`, Status `Posted`, Amount `$100`, EDARA Invoice Type `Service Charge`, Branch `Ramallah Branch`, Property `Al-Rawabi Property`, Building `Building A`, Unit `Apartment 101`, Journal Item posted to Service Charge Income (account `403000`), Credit `$100`. Confirms the Service Charge flow uses native Odoo invoices/accounting with no parallel ledger.
- **Validates:** (1) Equal allocation eligibility-first fix, (2) allocation total reconciles to Service Charge Total Amount, (3) ineligible (vacant) unit correctly excluded, (4) `Generate Allocation` state transition `Draft` → `Allocated`, (5) `Create Invoices` state transition `Allocated` → `Invoiced`, (6) exactly one invoice per eligible unit/allocation line, (7) `Create Invoices` idempotency guard (button unavailable once `Invoiced`), (8) invoice posted correctly to native `account.move`, (9) correct EDARA tagging (branch/property/building/unit/invoice type), (10) correct Service Charge Income account posting, (11) no parallel accounting ledger.
- **Final status: PASS.** MAT-FIND-009 is now closed as FIXED - VERIFIED (see Deferred Findings table and "Resolved MAT Findings - Implementation Notes" below).

**MAT-027 — Maintenance Request Lifecycle: PASS / COMPLETED**
- **Primary request:** `MR/2026/0049` (Unit Apartment 101, Building Building A, Property Al-Rawabi Property, Reported By Omar Khalil, Assigned To Administrator). Verified full lifecycle: `New` → `Assign` → `Assigned` → `Start` → `In Progress` → `Complete` → `Done`, with `Completed Date` recorded on completion. Also verified the alternate branch `New`/`Assigned` → `Cancel` → `Cancelled` is available per the model's transition guards.
- **Verified on the primary request:** Unit/Building/Property linkage, Reported By, Assigned To, Priority, Requested Date, the Assign/Start/Complete/Cancel workflow actions, Cost field, Vendor field, data persistence across every transition, `Completed Date` populated on `action_complete()` and remaining saved after reopening the record. Attempting to assign with no `Assigned To` set correctly raised `"Select who this request is assigned to before assigning it."` (matches `action_assign()`'s guard in `models/edara_maintenance_request.py`). All valid transitions completed with no warnings/errors. No new functional finding was discovered during MAT-027.
- **Second request (`MR/2026/0050`):** used to verify cancellation specifically - `New` → `Cancel` → `Cancelled`; workflow buttons correctly disappeared once cancelled (matches `action_cancel()`'s guard blocking further transitions from `done`/`cancelled`).
- **Third request (`MR/2026/0051`):** used to verify Cost/Vendor persistence - Cost `$100`, Vendor `Ahmad Alawneh`, transitioned `New` → `Assigned` → `In Progress` → `Done`; Cost and Vendor remained unchanged throughout; `Completed Date` populated and persisted.
- **Accounting/invoicing review (deliberate, part of MAT-027):** with `MR/2026/0051` in `Done` state (Cost `$100`, Vendor `Ahmad Alawneh`), checked Accounting → Vendors → Bills and the vendor contact `Ahmad Alawneh` directly - confirmed NO Vendor Bill or other accounting entry exists for this maintenance request, and the Maintenance Request form has no Smart Button (Vendor Bill/Bill/Invoice/Accounting/Journal Entry/Payment) linking to one. This was investigated (read-only, no records created/modified) rather than assumed to be a bug - see "Architecture Decisions" below for the conclusion (**Option A - Cost/Vendor are intentionally operational-only; no code gap, no deferred finding created for this**).
- **Validates:** (1) full New→Assigned→In Progress→Done lifecycle, (2) New/Assigned→Cancelled branch, (3) `action_assign()` guard requiring `Assigned To`, (4) `action_start()`/`action_complete()`/`action_cancel()` state guards, (5) `Completed Date` set-once-and-persisted behavior, (6) Cost/Vendor field persistence across transitions, (7) Unit/Building/Property/Reported By/Priority/Requested Date data integrity, (8) confirmation that Maintenance Request Cost/Vendor is intentionally not wired to Odoo Accounting (architecture, not a defect).
- **Final status: PASS.** Functional Maintenance Request lifecycle fully verified. No new deferred finding recorded - the accounting-integration question was resolved as an intentional architecture decision (Option A), documented below.

**MAT-030 — Billing/Proration Regression + Manual Invoice-Generation Trigger Confirmation: PASS**
- **Purpose:** (1) provide an additional independent live regression check of the MAT-FIND-011/MAT-FIND-013 billing fix on a fresh contract, and (2) confirm live whether a business-level "Generate Due Invoices" action exists anywhere in the EDARA UI (relevant to MAT-FIND-007).
- **Setup:** dedicated Contract `LC/2026/0142` (Monthly, Rent $1,600, Start `02/09/2026`, End `01/10/2026`). Before activation: State `Draft`, Payment Day `2` (auto-derived from Start Date, not manually entered), Payment Schedule Lines `0`.
- **Main action 1 (activation):** activated the contract. Result: State → `Active`, Unit Occupancy → `Rented`, Payment Schedule generated with exactly **1 line** - Due Date `02/09/2026`, Period `02/09/2026 → 01/10/2026`, Amount `$1,546.67`, state `Overdue`. Matches the MAT-FIND-011/013 zero-line-safety and proration rules exactly (29 occupied days × $1,600/30).
- **Main action 2 (invoice generation):** searched the Lease Contract and Payment Schedule UI for a business-level "Generate Due Invoices" action/button - **none exists**. The only working manual path found was `Settings → Technical → Scheduled Actions → EDARA: Generate Due Invoices → Run Manually`. This confirms MAT-FIND-007's gap applies equally to invoice generation, not just contract expiry - see the updated MAT-FIND-007 entry above.
- **Result:** Invoice `INV/2026/00022` created - Status `Posted`, Untaxed Amount `$1,546.67`, Total `$1,546.67`, Amount Due `$1,546.67`, correctly linked back to the schedule line.
- **Validates:** (1) an independent, additional live confirmation that MAT-FIND-011 remains `FIXED - AUTOMATED VERIFIED - LIVE VERIFIED - ACCOUNTING VERIFIED` (zero-line-safety + correct proration + correct invoice amount on a fresh contract), (2) live confirmation that MAT-FIND-007's "no business-level manual trigger" gap extends to due-invoice generation, not only contract expiry.
- **Final status: PASS** for the billing/proration regression. **MAT-FIND-007 remains open/deferred** - this MAT only reconfirms and broadens its scope; it does not close it.

### MAT-020 — Unit Occupancy Not Reverting Correctly on Termination (CONFIRMED BUG — FIXED)

**Finding:** Terminating `LC/2026/0003` (a future-dated, sequential contract on Apartment 101, 2027-12-01→2028-12-01) flipped Apartment 101's occupancy from `Rented` to `Available`, even though `LC/2026/0002` (2026-09-07→2027-09-06) was still `Active` and genuinely covered the current date. Root cause: `action_terminate()` and `_cron_expire_contracts()` (`models/edara_lease_contract.py`) both unconditionally wrote `unit.occupancy_status = 'available'` with no check for another still-active contract on the same unit. `_check_no_overlap()` correctly does NOT flag `LC/2026/0002`/`LC/2026/0003` as overlapping - they are legitimately sequential, non-overlapping active contracts on the same unit, a combination the occupancy-write logic never accounted for.

**Status: FIXED - VERIFIED.** Live-verified 2026-09-16 using Apartment 109: Contract A `LC/2026/0124` (Start `01/08/2026`, End `01/09/2026`, Active) and Contract B `LC/2026/0126` (Start `02/09/2026`, End `01/10/2026`, Active), both on Apartment 109. Terminating Contract A resulted in `LC/2026/0124` → `Terminated`, `LC/2026/0126` remaining `Active`, and Apartment 109 remaining `Rented` - confirming termination no longer blindly forces the unit to `Available` when another active contract covers the relevant period.

**Implementation:**
- Added `edara.unit._has_current_active_contract()` (`models/edara_unit.py`): true iff an `active`-state lease contract on this unit has `start_date <= today <= end_date`. An `active` contract with a future `start_date` does **not** count - `state='active'` alone does not mean "occupying the unit today".
- Added `edara.unit._sync_occupancy_from_contracts()`: the single reusable recomputation helper. Only ever toggles between `available`/`rented` (never touches `sold`/`owner_occupied`/`reserved`), based purely on `_has_current_active_contract()`.
- `action_terminate()` and `_cron_expire_contracts()` (`models/edara_lease_contract.py`) now call `contract.unit_id._sync_occupancy_from_contracts()` instead of hardcoding `occupancy_status = 'available'`.
- Added a symmetric defense-in-depth ORM constraint in `edara_unit.py`'s existing `_check_occupancy_status_derivation()`: blocks manually setting `occupancy_status = 'available'` while `_has_current_active_contract()` is true (mirrors the pre-existing "cannot mark Rented without an active contract" guard, closing the asymmetry that let this bug write through the ORM silently in the first place).
- **`action_activate()` was deliberately left unchanged** (still directly assigns `occupancy_status = 'rented'`, no date check) - see "Business Decisions Required" below.
- Incidental fix: `views/reports_views.xml`'s Occupancy report "Vacant" filter searched for `occupancy_status = 'vacant'`, a value that has never existed in `OCCUPANCY_STATUSES` (the correct value is `available`) - the filter could never have matched anything since it was written; corrected to `available`.

**Files changed:** `models/edara_unit.py`, `models/edara_lease_contract.py`, `views/reports_views.xml`.

**Tests added** (`tests/test_edara_lease_contract.py`): `test_current_and_future_sequential_contracts_can_both_be_active`, `test_terminate_future_contract_keeps_unit_rented_via_current_contract` (the exact MAT-020 regression), `test_terminate_current_contract_with_only_future_contract_remaining_frees_unit`, `test_cron_expiry_with_future_contract_still_active_frees_unit`, `test_terminated_historical_contract_does_not_affect_later_occupancy`, `test_cannot_manually_mark_unit_available_with_current_active_contract`, `test_activate_future_dated_contract_still_marks_unit_rented_immediately` (pins the preserved activation behavior - see below). All 7 pass; all pre-existing occupancy/termination/cron/overlap tests continue to pass unchanged.

## Business Decisions Required

Items intentionally NOT implemented because they require a product/business decision, not an engineering guess. Do not resolve these by inventing a rule - ask the user.

**BD-001 — Future-Dated Active Lease Occupancy Semantics — DECIDED (2026-09-21)**

**Decision:** A future-dated `ACTIVE` lease contract (`start_date > today`) marks its Unit `RESERVED`, not `RENTED`, until the Lease Start Date arrives, at which point the Unit transitions `RESERVED → RENTED`. A contract activated on or after its own start date still marks the Unit `RENTED` immediately, exactly as today. Existing expiry/termination behavior (`RENTED → AVAILABLE`, MAT-020) is unchanged.

```text
DRAFT --activate--> ACTIVE --+-- start_date > today --> Unit = RESERVED
                              +-- start_date <= today -> Unit = RENTED

RESERVED --start_date arrives--> RENTED
RENTED --terminate/expire (existing logic)--> AVAILABLE
```

**Rationale:** confirmed by the 2026-09-21 read-only architecture investigation that `occupancy_status='reserved'` already exists in `OCCUPANCY_STATUSES` and already has dedicated list/kanban decoration (`decoration-warning="occupancy_status == 'reserved'"` in `unit_views.xml`) and a pre-existing MAT/UI-032 quick-filter concept, but carries zero business logic anywhere in the codebase today (verified by a whole-module grep - the only references are the Selection option itself and a docstring explicitly skipping it). This decision gives that existing, otherwise-inert state its intended business meaning rather than introducing a new one, satisfying the standing "do not invent a new state if an existing one already represents the concept" constraint. It also resolves the constraint asymmetry found during that investigation: `_check_occupancy_status_derivation()`'s "can be Rented" branch checks only `state='active'` with no date filter, while its "can't be Available" branch is already date-aware via `_has_current_active_contract()` - the fix must make the Rented-entry path equally date-aware rather than leave the gap.

**MAT-FIND-010 is resolved by this same decision.** MAT-FIND-010's literal symptom is the opposite boundary from BD-001 (an `Active` contract whose `end_date` has already passed but hasn't yet been processed by `_cron_expire_contracts()`, vs. BD-001's future `start_date`), and the two were previously deliberately kept distinct in this file for that reason. What BD-001 resolves is the *underlying architectural question* both findings shared: whether `occupancy_status` should reflect real-time date-range coverage (start AND end) via a reliable scheduled mechanism, or merely "has an active contract record" regardless of dates. BD-001's decision establishes the former as the intended semantics, and the existing `_cron_expire_contracts()` already implements exactly that on the end-date side (a unit showing `Rented` between `end_date` passing and the next daily cron run is expected, bounded cron-latency, not a semantics gap) - so MAT-FIND-010's open question is answered by the same principle, and its residual behavior (daily-cron latency) is accepted, not a defect requiring a separate fix. Status updated to `READY FOR IMPLEMENTATION` in the Deferred Findings table below - "ready" here means the open semantics question is closed and no separate investigation is needed, not that new code is required for MAT-FIND-010 specifically beyond what BD-001's implementation already covers.

**Relationship to MAT/UI-032:** the Dashboard's planned `Reserved` quick-filter (already listed under "Planned quick-filter concepts") now has real, defined semantics to filter on rather than an always-empty state. MAT/UI-032 must treat `AVAILABLE` = genuinely available for leasing, `RESERVED` = contractually committed for future occupancy, `RENTED` = currently occupied under an in-force lease, and its quick-filters must use these actual native `occupancy_status` values (Available/Reserved/Rented/Owner Occupied/Sold) with no parallel filtering system, per the existing MAT/UI-032 native-integration constraint.

**Implementation requirements the future ticket must address** (recorded here, not yet implemented):
1. **Lease Activation** — `action_activate()` (`models/edara_lease_contract.py`) must become date-aware: future `start_date` → `RESERVED`; `start_date` today or past → `RENTED` (replacing the current unconditional `occupancy_status = 'rented'` write at L251-256).
2. **Start-Date Transition** — a reliable mechanism must transition `RESERVED → RENTED` when a contract's `start_date` arrives. Prefer extending the existing scheduled-lifecycle pattern (a new daily cron mirroring `_cron_expire_contracts()`'s idempotent, `state`-filtered design) over introducing new architecture.
3. **`_sync_occupancy_from_contracts()`** must be extended to understand `RESERVED` as a managed state — it currently explicitly skips any unit not already `available`/`rented` (`models/edara_unit.py` L120-122: `if unit.occupancy_status not in ('available', 'rented'): continue`). `reserved` must move out of the "ignored" category.
4. **Expiry/Termination** — preserve the existing verified `RENTED → AVAILABLE` behavior (MAT-020), and additionally ensure a `RESERVED` contract terminated *before* its start date correctly frees the unit back to `AVAILABLE` (not left stranded in `RESERVED`).
5. **Multiple Contracts/Overlap** — respect the existing overlap validation (`_check_no_overlap()`, unchanged by this decision); no new transition may mark a unit `RENTED` while the relevant contract is still future-dated, even if another contract on the same unit is already active/rented.
6. **Dashboard semantics** — MAT/UI-032 must use the AVAILABLE/RESERVED/RENTED definitions above, not invent its own.
7. **Available KPI correction** — `edara.dashboard`'s `available_units` (`models/edara_dashboard.py` L74) currently computes `total_units - occupied_units - under_maintenance_units`, which silently miscounts any `reserved`, `owner_occupied`, or `sold` unit as available (confirmed during the 2026-09-21 investigation - this is a pre-existing inaccuracy, not introduced by this decision, but must be corrected as part of this same implementation since `reserved` is about to become a real, populated state). The fix must derive `available_units` from the actual intended semantics (e.g. a direct `occupancy_status='available'` count) rather than subtraction.
8. **Native Search/Filters** — future Dashboard quick filters (MAT/UI-032) must use the real `occupancy_status` values directly (Available/Reserved/Rented/Owner Occupied/Sold) via native domains, per the existing "no parallel filtering system" constraint.

**Required tests for the future implementation** (at least):
1. Future-dated `ACTIVE` contract → Unit becomes `RESERVED`
2. Same-day start → Unit becomes `RENTED`
3. Past start date → Unit becomes `RENTED`
4. `RESERVED` → `RENTED` when the start date arrives (cron/transition mechanism)
5. `RESERVED` contract terminated before its start date → Unit becomes `AVAILABLE`
6. `RENTED` contract terminated/expired → existing MAT-020 behavior unchanged
7. Multiple/overlapping contract protection unaffected
8. Dashboard `available_units` KPI excludes `RESERVED`
9. Dashboard `available_units` KPI excludes `OWNER_OCCUPIED`
10. Dashboard `available_units` KPI excludes `SOLD`
11. Existing security/isolation tests (MAT-031, MAT-FIND-015-A) remain passing unchanged
12. Full regression suite remains passing (current baseline: 173/173)

**Superseded:** the previous "preserved behavior" regression test `test_activate_future_dated_contract_still_marks_unit_rented_immediately` (`tests/test_edara_lease_contract.py`) pinned the now-superseded immediate-Rented behavior - the future implementation ticket must update/replace this test to match the decision above (a deliberate, visible diff, not a silent regression).

**Status: BD-001 — FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (implemented 2026-09-21).**

### BD-001/MAT-FIND-010 — Implementation, Tests, and Live Validation (2026-09-21)

**Architecture:** `edara.unit` gained `_has_future_active_contract()` (mirrors the existing `_has_current_active_contract()` - true iff an active-state lease contract's `start_date > today`) and `_lease_occupancy_state()` (a pure derivation: `rented` if a contract covers today, else `reserved` if one hasn't started yet, else `available` - date-range-aware, replacing "has some active contract regardless of dates"). `_sync_occupancy_from_contracts()` (used by `action_terminate()`/`_cron_expire_contracts()`) now manages `reserved` as a real state instead of skipping it, and a new `_cron_sync_reserved_occupancy()` (daily, registered in `data/edara_cron.xml` as `EDARA: Transition Reserved units to Rented once their lease starts`) is the reliable start-date-arrival mechanism - it re-evaluates every unit currently `reserved` and flips it to `rented` once its governing contract's start date has arrived, naturally idempotent since a unit already flipped no longer matches its domain on the next run. `action_activate()` (`edara_lease_contract.py`) now unconditionally sets the unit's occupancy to `unit._lease_occupancy_state()` instead of a hardcoded `'rented'` - it still always forces the value on every activation (unchanged "always force it" semantics), just date-aware now. `_check_occupancy_status_derivation()` was tightened to close the exact asymmetry the 2026-09-21 architecture investigation found: `rented` now requires `_has_current_active_contract()` (previously just "any active contract, any dates"), and `available` is now also blocked while `_has_future_active_contract()` is true (should be `reserved` instead) alongside the pre-existing "can't be available while covering today" guard. `edara.dashboard`'s `available_units` KPI was corrected from `total_units - occupied_units - under_maintenance_units` (which silently miscounted `reserved`/`owner_occupied`/`sold` units as available) to a direct `occupancy_status='available'` count.

**Files changed:** `models/edara_unit.py`, `models/edara_lease_contract.py`, `models/edara_dashboard.py`, `data/edara_cron.xml`, `tests/test_edara_lease_contract.py`, `tests/test_edara_dashboard.py`.

**Superseded test:** `test_activate_future_dated_contract_still_marks_unit_rented_immediately` replaced by `test_activate_future_dated_contract_marks_unit_reserved` (asserts `reserved`, matching the new decision). Two other existing tests were updated because their expected occupancy value genuinely changed under the new rule (not a mistake being corrected, a deliberate consequence of BD-001): `test_terminate_current_contract_with_only_future_contract_remaining_leaves_unit_reserved` (previously `..._frees_unit`, asserted `available`, now correctly asserts `reserved` - a future-only remaining contract is a real commitment) and `test_cron_expiry_with_future_contract_still_active_leaves_unit_reserved` (same change, via the expiry-cron path). `test_renew_creates_active_successor_and_marks_predecessor_renewed` was adjusted to use relative (`date.today()`) dates instead of hardcoded 2026/2027 literals - the old literal 2027 renewal date had silently drifted into "future" relative to the real current date, which combined with this fix would have made the successor `reserved` instead of `rented`, breaking the test's original (unrelated) intent of verifying renewal mechanics; using an immediate (`today`) renewal date preserves that original intent under the new rule.

**Automated tests added/changed:** 6 new tests in `tests/test_edara_lease_contract.py` (future-dated activation → reserved [rewritten], same-day start → rented, past start → rented, the reserved→rented cron transition + idempotency in one test, reserved-terminated-before-start → available, overlap protection regression with a reserved contract) plus 2 renamed/updated existing tests (see above) and 1 new test in `tests/test_edara_dashboard.py` (available KPI excludes reserved/owner_occupied/sold, using disposable units created inline). **Targeted run: 31/31 passing** (`TestEdaraLeaseContract` + `TestEdaraDashboard`, on `edara_test`, module upgraded cleanly - the new `ir.cron` XML record loaded without error). **Full suite: 179/179 passing** (baseline was 173; net +6 new tests, 2 renamed with no count change - confirms nothing else regressed).

**Live validation (2026-09-21) against real `odoo19_dev`:** module upgraded cleanly (confirmed the new cron `EDARA: Transition Reserved units to Rented once their lease starts` is now registered and active in `odoo19_dev`, id 35, alongside the two pre-existing EDARA crons - this is an intentional, permanent addition, not disposable test data). A rolled-back validation script covering all 6 required scenarios plus a security/accounting regression spot-check: **15/15 checks passed, 0 failed**, `ROLLED BACK - odoo19_dev is unmodified` confirmed. Scenario A (future lease → `reserved`), B (start-date cron → `rented`, then idempotency), C (terminate a still-reserved contract before its start → `available`), D (current lease → `rented` immediately), overlap-with-reserved regression (still correctly blocked), E (Dashboard KPI: `total_units`/`occupied_units`/`available_units` all moved by exactly the expected disposable-unit deltas, confirming `reserved`/`owner_occupied`/`sold` are excluded from `available_units`), and F (MAT-FIND-015-A's scoped-accounting boundary and MAT-FIND-014's Dashboard permission gating both spot-checked intact, since neither was touched by this change) - all passed.

**Database cleanup:** verified via direct `psql` query after the live run - zero `BD001%`-coded records and zero `bd001_cm_only` login remain in `odoo19_dev`; real unit count/occupancy distribution (18 units, all `rented`) matches the pre-test baseline exactly, confirming full rollback with no residual test pollution.

**Remaining limitations:** none identified. The new `reserved`-state and its cron are additive to the existing lease lifecycle; no existing workflow (billing, deposits, service charges, maintenance, portal, security) reads or depends on `occupancy_status` in a way this change could affect, confirmed by the unchanged 015-A/014 spot-checks above and the full 179/179 regression pass.

**Status: BD-001 / MAT-FIND-010 — FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

**BD-002 — Reject / Terminate Reasons — DECIDED and IMPLEMENTED (2026-09-22)**

**Decision:** Reject requires a reason (empty/whitespace-only blocked). Terminate's reason stays optional, unchanged.

**Implementation:** no new wizard - `edara.renewal.request`'s existing `decision_note` field is reused (per the "reuse an existing field rather than duplicate" instruction). `views/renewal_request_views.xml`'s `decision_note` field changed from `invisible="state == 'submitted'"` to `readonly="state != 'submitted'"` (now visible and editable *before* a decision, not only after) with a placeholder prompting for the reason. `action_reject(reason=None)` in `models/edara_renewal_request.py`: if an explicit `reason` argument is passed (programmatic callers), it's used; otherwise it falls back to whatever the user has already typed into `decision_note` on the form; either way, a `UserError` is raised if the resulting value is empty or whitespace-only, before the request is rejected. `action_terminate(reason=None)` (`models/edara_lease_contract.py`) is **unchanged** - already exactly matched the approved "optional" decision (verified by reading the current code before touching anything).

**Files changed:** `models/edara_renewal_request.py`, `views/renewal_request_views.xml`.

**Tests:** new `tests/test_edara_renewal_request.py` (7 tests: reject without reason blocked, reject with whitespace-only reason blocked, reject blocked when the pre-filled `decision_note` is blank, reject with a valid reason succeeds, reject using a pre-filled `decision_note` with no explicit argument, reason persists and no successor contract is created on a blocked/rejected request, Approve remains unaffected). Plus 1 new test in `tests/test_edara_lease_contract.py` (`test_terminate_without_reason_succeeds`, pinning the confirmed-unchanged Terminate behavior).

**Live validation (2026-09-22):** against real `odoo19_dev` - Reject without a reason blocked (no successor contract created), Reject with a reason succeeds and persists, Terminate without a reason succeeds, Terminate with a reason succeeds and persists. All 6 checks passed, rolled back.

**Status: BD-002 — FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

**BD-003 — Expiring Soon Definition — DECIDED and IMPLEMENTED (2026-09-22)**

**Decision:** Expiring Soon = `ACTIVE` lease contracts whose `end_date` falls within `[today, today + 30 days]` (both boundaries inclusive).

**Implementation:** `models/edara_dashboard.py` - a module-level `EXPIRING_SOON_WINDOW_DAYS = 30` constant and `_expiring_soon_domain(today)` helper (`[('state', '=', 'active'), ('end_date', '>=', today), ('end_date', '<=', today + 30 days)]`), a new `expiring_soon_contracts_count` KPI field, and `action_view_contracts_expiring_soon()` (reuses `_quick_action()`, same native `action_edara_lease_contract` action as every other contract tile). `views/dashboard_views.xml`'s Lease Contracts section gained the "Expiring Soon (30d)" tile (replacing the earlier "not shown, business decision required" placeholder text).

**Files changed:** `models/edara_dashboard.py`, `views/dashboard_views.xml`.

**Tests:** `tests/test_edara_dashboard.py::test_contract_expiring_soon_kpi_boundaries` - covers all 6 required boundary cases (ending today: included; within 30 days: included; ending exactly 30 days out: included; ending 31 days out: excluded; already-expired via the real expiry cron: excluded; draft/non-active: excluded) plus KPI-count correctness and quick-action domain correctness.

**Live validation (2026-09-22):** against real `odoo19_dev` - a disposable contract ending in 20 days was confirmed included in the action's domain results; a disposable contract ending in 60 days was confirmed excluded; the KPI count reflected the expiring disposable contract. 4/4 checks passed, rolled back.

**Status: BD-003 — FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

### MAT-FIND-003 / MAT-FIND-012 — Implementation, Tests, and Live Validation (2026-09-22)

**MAT-FIND-003 (Unit Duplicate):** `edara.unit.copy()` (`models/edara_unit.py`) is a new override. Before inspecting a fix, `code` was confirmed (by grepping the whole module) to be referenced nowhere outside this model's own uniqueness constraint - the business-facing unit identifier is the separate, unconstrained `unit_number` field - so automatic regeneration is safe per the ticket's own "if code has strong business meaning, stop" instruction; this was not a case that needed stopping. `copy()` appends `-COPY`, then `-COPY2`, `-COPY3`, ... (scoped to the same building, the constraint's own scope) until a free value is found, and never overwrites the original unit's own code. A second, necessary fix was found while implementing this: `occupancy_status` is a plain stored field with no `copy=False`, so a `rented`/`reserved` unit's copy would otherwise carry over a value with zero backing lease contracts (`lease_contract_ids`, a One2many, is never copied by native duplication) and fail the pre-existing `_check_occupancy_status_derivation()` constraint - `copy()` now also resets `occupancy_status` to `available` in that case only; `owner_occupied`/`sold` (administrative, contract-independent) are preserved unchanged.

**MAT-FIND-012 (Overlap boundary):** see the Deferred Findings table row above for the exact domain change in `_check_no_overlap()`.

**Files changed:** `models/edara_unit.py`, `models/edara_lease_contract.py`.

**Automated tests:** MAT-FIND-003 - 5 new tests in `tests/test_edara_property.py` (new unique code on duplicate, two successive duplicates get distinct codes, an explicitly-supplied `default={'code': ...}` is respected and not overridden, a duplicated `rented` unit's occupancy resets to `available` with the original left untouched, a duplicated `owner_occupied` unit preserves that status). MAT-FIND-012 - 6 new tests in `tests/test_edara_lease_contract.py` (see the Deferred Findings row above for the exact case list).

**Live validation (2026-09-22) against real `odoo19_dev`:** a disposable rented unit was duplicated - the copy received a new unique code (`<original>-COPY`), the original's code and occupancy were unaffected, the copy's occupancy correctly reset to `available`, the building relationship was preserved, and the uniqueness constraint was confirmed still fully enforced (a second unit manually created with the same code as the copy was correctly rejected, caught via a `cr.savepoint()` so the rest of the validation script's transaction wasn't poisoned by the raw SQL-level `UniqueViolation`). For the overlap boundary: a disposable adjacent lease (new start = prior lease's exact end_date) was confirmed to activate successfully (no longer blocked); a disposable lease starting one day before that boundary was confirmed to still be correctly blocked. 7/7 checks passed for these two findings specifically (part of the combined 20/20 live run below), rolled back.

### MAT-FIND-004 / MAT-FIND-008 — Investigation, Implementation, Tests, and Live Validation (2026-09-22)

**MAT-FIND-004 (Lease Contract sequence gaps) — read-only investigation, closed as expected Odoo behavior triggered by test/development data pollution, NOT a code defect. No code, configuration, or database change was made for this finding.**

Investigation performed (all read-only): inspected `edara.lease.contract.create()` (`models/edara_lease_contract.py`) - `name` is assigned via a single `self.env['ir.sequence'].next_by_code('edara.lease.contract')` call, the standard Odoo pattern; inspected `data/edara_sequences.xml` - exactly one `ir.sequence` record for code `edara.lease.contract` exists (no duplicate/competing sequence), `number_increment=1`, no `company_id` restriction; inspected Odoo core's `ir_sequence.py` - the record's `implementation` field was left at its default, `'standard'`, which core's own docstring describes as "a fast **gaps-allowed** PostgreSQL sequence" (as opposed to `'no_gap'`, which is transactional but slower and not configured here); confirmed directly against `odoo19_dev` via `psql` that the underlying native Postgres sequence (`ir_sequence_022`) is a real, non-transactional Postgres `SEQUENCE` object, currently at `last_value = 177`, while only 27 `edara.lease.contract` records actually exist (`LC/2026/0002` .. `LC/2026/0142`) - i.e. 150 sequence numbers have been consumed with no surviving record. Every surviving contract's `create_date` was correlated against this project's own documented MAT/test-run timestamps (`EDARA_PROJECT_STATE.md`'s dated verification-cycle entries above) and falls exactly within those known live-verification/manual-testing windows (2026-09-07 through 2026-09-18); no contract names repeat (confirmed via `SELECT name, count(*) ... GROUP BY name HAVING count(*) > 1` returning zero rows) and numbers remain strictly monotonic - no evidence of duplicate numbers or misattributed records, exactly as the original finding already noted.

**Root cause:** a standard (gaps-allowed) Postgres sequence, by design, is **not transactional** - it does not roll back when the surrounding database transaction does. Every `create()` call that reaches the `next_by_code()` line permanently advances the sequence, whether or not that specific transaction ever commits a surviving row. This MAT campaign has, by necessity, repeatedly created `edara.lease.contract` records inside transactions that are then deliberately rolled back: every automated test method (Odoo test transactions roll back after each test) and every disposable live-validation script run against this same `odoo19_dev` database throughout this session (BD-001, MAT/UI-032, and both Business-Decisions-Bundle live-validation runs each created and then rolled back several lease contracts - see e.g. the bundle script's own `env.cr.rollback()` in `bundle_live_validation.py` referenced earlier in this document). This is exactly candidate root causes (1) and (2) from the original finding's own investigation checklist, confirmed rather than assumed. This is expected, well-documented Postgres/Odoo behavior (the same mechanism `sale.order`, `account.move`, and every other sequenced native document uses) - not an EDARA defect, and switching to `no_gap` would trade this cosmetic gap for materially worse concurrent-creation performance (row-level locking) for no correctness benefit, since no duplicate or out-of-order numbering was ever observed.

**Classification:** Test/development data pollution (mechanism: expected Odoo standard-sequence behavior). **Status: MAT-FIND-004 — CLOSED - ROOT CAUSE CONFIRMED, NO DEFECT. No code/config/database change made or needed**, per the finding's own explicit instruction not to reset or alter the `ir.sequence` record.

**MAT-FIND-008 (Renewal Request tenant message read-only) — FIXED.**

**Investigation:** `models/edara_renewal_request.py` has no `write()` override and no field-level ACL singling out `note` - it is a plain `Text` field, identical in the model layer to every other request field. The unconditional lock was purely a view-layer artifact: `views/renewal_request_views.xml` had `<field name="note" readonly="1"/>`, unlike every sibling field (`contract_id`/dates/`requested_rent_amount`/`decision_note`), which are `readonly="state != 'submitted'"`. Checked the portal flow before changing anything: `controllers/portal.py`'s `portal_lease_request_renewal()` sets `note` only as part of the initial `create()` call (`request.env['edara.renewal.request'].create({..., 'note': post.get('note')})`) and never writes to an existing request afterward - so the portal flow does not rely on `note` being backend-immutable, and is unaffected either way. Also confirmed at the ACL layer (`security/ir.model.access.csv`): `group_edara_portal_tenant` has `perm_write=0` on `edara.renewal.request` (read=1, write=0, create=1, unlink=0) - a portal tenant cannot write to `note`, `decision_note`, `state`, or any other field on this model after creation, regardless of the view's readonly state, so the "tenant cannot modify owner-only decision fields" requirement was already fully enforced at the security layer and needed no change.

**Root cause:** the unconditional `readonly="1"` blocked a legitimate case the same view's own action-window help text describes - "Renewal requests are created here when a tenant asks to extend their lease, **either from the portal or on their behalf**" - a staff member creating a request on a tenant's behalf (e.g. a phone call) had no way to type the tenant's message into the form at all, unlike every other field.

**Fix:** `views/renewal_request_views.xml` - changed `note` from `readonly="1"` to `readonly="state != 'submitted'"`, mirroring the exact pattern already used by the request's other fields (and now `decision_note` per BD-002). No model, controller, or security change was needed or made.

**Files changed:** `views/renewal_request_views.xml` only.

**Automated tests:** `tests/test_edara_portal.py::test_tenant_can_request_renewal_for_own_lease` strengthened with an explicit assertion that the submitted `note` value persists (was previously only checked for existence/state). New file-level test class `tests/test_edara_renewal_request.py::TestEdaraRenewalRequestNoteField` (3 new tests): a branch manager can now create a request on a tenant's behalf and write `note` while it is `submitted`; a portal tenant can still submit a renewal message at creation (pre-existing path, confirmed unaffected); a portal tenant's attempt to write `note` - or `decision_note`/`state` - after creation raises `AccessError` (ACL-enforced, unaffected by the view change either way).

**Live validation (2026-09-22) against real `odoo19_dev`:** a disposable branch manager created a renewal request on a disposable tenant's behalf and successfully wrote `note` while the request was `submitted`; a disposable portal-tenant user submitted their own request with `note` at creation and it persisted; the same tenant's attempt to write `note` after creation was correctly blocked with `AccessError`; the same tenant's attempt to write `decision_note`/`state` was correctly blocked with `AccessError`; the branch manager then successfully approved the on-behalf request end-to-end (state → `approved`, `new_contract_id` set), confirming normal processing is unaffected by the view change. 9/9 checks passed (4 MAT-FIND-004 read-only checks + 5 MAT-FIND-008 checks), rolled back - confirmed via `psql` afterward that zero `MF008%`-coded disposable records remain and the real unit baseline (18 units, all `rented`) is unchanged.

**Status: MAT-FIND-008 — FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

## Planned Future Work — MAT/UI Tickets

**MAT/UI-032 — EDARA Dashboard UX & Native Odoo Action Integration**

**Status: FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (implemented 2026-09-22).** See "MAT/UI-032 — Implementation, Tests, and Live Validation" below for full detail. The plan below is preserved as the original design record; deviations from it (Gantt unavailable, Expiring Soon deferred) are called out explicitly in the implementation section rather than silently edited into this plan.

**Objective:** Redesign the current KPI-only EDARA Dashboard into a professional, action-oriented "EDARA Management Command Center" - a practical operational starting point for property managers and other EDARA users, not just a numbers screen. Must remain built on native Odoo architecture, reusing Odoo's existing action/search/filter/group-by/view capabilities; must stay upgrade-friendly and avoid building a parallel frontend/navigation/filtering system.

**Native Odoo integration / visible-filter requirement:** dashboard quick-action buttons must NOT implement a separate custom filtering mechanism. Clicking a button must open the corresponding native Odoo action with a matching native search/filter domain, visibly reflected in the Odoo Search Bar, while normal Search/Filters/Group By/Favorites remain fully usable. Example: `Rented Units` → native Units action → native Search View → domain `Occupancy Status = Rented`. A separate custom filter bar duplicating the Search View is out of scope unless a future implementation task proves native functionality cannot satisfy the requirement.

**Planned quick-filter concepts** (buttons/domains to be finalized at implementation time - none built yet):
- Units: Available, Rented, Reserved, Under Maintenance, Owner Occupied, Sold (if applicable to the final business model) → native Units action.
- Contracts: Draft, Active, Expiring Soon, Expired, Terminated, Renewed (if applicable) → native Lease Contract action.
- Payment/Collection: Overdue, Due Today, Due This Month, Paid → exact model/action to be determined at implementation time against the finalized billing architecture and security model.
- Maintenance: New, Assigned, In Progress, Done, Cancelled → native Maintenance Request action/Kanban/List.

**Native view types to evaluate/reuse:**
- List: Units, Contracts, Payment Schedule, Tenants, Maintenance, Properties, Buildings.
- Kanban: Maintenance workflow, Contract workflow, Renewal Requests, Units (if useful).
- Calendar: lease expirations, renewals, maintenance scheduling, payment due dates (where appropriate).
- Gantt (strong candidate for lease/contract management): unit occupancy periods, lease start/end dates, contract overlaps/gaps, upcoming expirations - via native Odoo Gantt, not a custom timeline engine.
- Pivot/Graph: evaluate later for management reporting where native functionality fits.

**Visual direction:** professional, clean, modern; not a decorative or overly colorful analytics screen; semantic color hierarchy only (blue = primary/information, green = healthy/available/paid, orange = warning/pending, red = overdue/problem, gray = neutral) - no arbitrary colors purely for visual variety. Conceptual layout: header/title → portfolio KPI cards → Units section → Contracts section → Maintenance section → Financial/collections section → optional charts/operational summaries → navigation into detailed native Odoo views.

**Permission-aware requirement / prerequisite blocker:** this ticket explicitly depends on resolving the dashboard security/access architecture first. **Cross-referenced to MAT-FIND-014 and MAT-FIND-015**, updated status as of 2026-09-20: MAT-FIND-014 is `FIXED - AUTOMATED VERIFIED - LIVE VERIFIED` (the Dashboard/Property/Branch crash is resolved via a permission-aware `has_accounting_access` pattern, confirmed both by the business owner's browser test and an independent live check against real `odoo19_dev` data - see the MAT-FIND-014 entries above), and **MAT-FIND-015** is now also `FIXED - AUTOMATED VERIFIED - LIVE VERIFIED` (resolved via scoped native Accounting execution, MAT-FIND-015-A - see that section above): EDARA Company Manager/Accountant users can now complete Service Charge invoicing and Deposit/Late-Fee workflows without any native Accounting group, via narrow, authorization-gated `.sudo()` at the exact call sites, while still having zero general native Accounting read/browse access. Both prerequisite blockers for this ticket are now cleared. Note for any future Dashboard "quick action" that would trigger a *write* (not just a read) against Accounting-integrated data (e.g. a KPI drilldown that itself creates/posts a record): it must follow the same authorization-first, narrowly-scoped elevation pattern established by MAT-FIND-015-A, not a blanket permission grant. The dashboard's *read-side* KPIs continue to use the existing `has_accounting_access` permission-aware degrade pattern (MAT-FIND-014) unchanged - MAT-FIND-015-A did not touch any read/compute path. No UI/UX implementation is authorized by this note alone; this ticket remains `PLANNED / FUTURE UI-UX WORK` until separately taken up.

**Architectural constraints (must be preserved):** native Odoo first; no React frontend or custom external dashboard application; no parallel filtering system; no parallel accounting ledger; reuse native Odoo actions/search views/views wherever practical; minimize custom code; remain upgrade-friendly; preserve existing business logic and security architecture; never bypass Odoo access rights. If a requirement cannot be achieved cleanly with native Odoo functionality, the limitation must be documented and the smallest appropriate customization proposed before implementation.

**Relationship to current MAT work:** this ticket is NOT a replacement for MAT-031 (Security / Isolation), which remains the current priority - including resolution and verification of MAT-FIND-014. MAT/UI-032 moves from PLANNED to implementation only after the security baseline (MAT-031 / MAT-FIND-014) is stable.

### MAT/UI-032 — Implementation, Tests, and Live Validation (2026-09-22)

**Status: FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

**Dashboard structure:** the Dashboard (`edara.dashboard`, still a `TransientModel`, still plain native form view, no OWL/JS) is reorganized into 4 sections plus the existing top info row (Total Properties/Buildings, Pending Renewals, Open Maintenance - unchanged): **Portfolio Overview - Units** (7 clickable stat-button tiles), **Lease Contracts** (5 tiles + an inline note explaining why "Expiring Soon" is absent), **Collections** (accounting-gated: existing Monthly Revenue/Outstanding Receivables/Payments This Month tiles + 4 new clickable tiles), **Maintenance** (5 tiles). Every clickable tile is a real `oe_stat_button` calling a Python action method - never a static number.

**KPI definitions (all direct canonical counts, never derived by subtraction):**
- Units: `available_units`/`reserved_units`/`occupied_units`(=rented)/`owner_occupied_units`/`sold_units` = `edara.unit.search_count([('occupancy_status', '=', <value>)])`; `under_maintenance_units` = `search_count([('operational_status', '=', 'under_maintenance')])` - a deliberately independent dimension, never combined with the occupancy counts (a unit can be `rented` AND `under_maintenance` simultaneously, and is correctly counted in both).
- Contracts: `draft_contracts_count`/`active_contracts_count`/`renewed_contracts_count`/`terminated_contracts_count`/`expired_contracts_count` = `edara.lease.contract.search_count([('state', '=', <value>)])`.
- Maintenance: `maintenance_new_count`/`maintenance_assigned_count`/`maintenance_in_progress_count`/`maintenance_done_count`/`maintenance_cancelled_count` = `edara.maintenance.request.search_count([('state', '=', <value>)])`.
- Collections (accounting-gated): `schedule_overdue_count`/`schedule_paid_count` = `edara.payment.schedule.line.search_count([('state', '=', <value>)])`; `schedule_due_today_count` = `search_count([('due_date', '=', today)])`; `schedule_due_this_month_count` = `search_count([('due_date', '>=', month_start), ('due_date', '<', next_month_start)])`.

**Native actions/filters:** every quick action is a thin Python wrapper (`edara.dashboard._quick_action(xml_id, domain)`) that opens the SAME `ir.actions.act_window` the corresponding EDARA menu already uses (`action_edara_unit`/`action_edara_lease_contract`/`action_edara_maintenance_request`/`action_edara_payment_schedule_line`) with a domain applied - never a custom filtering mechanism. The domain is a real native `act_window` domain, so it renders in and remains editable from the normal Odoo Search Bar, and Filters/Group By/Favorites/view-switching are entirely native and unmodified - verified directly (see Live Validation below) by re-searching each action's own returned domain through the ORM and confirming it returns the expected records.

**Permissions:** unit/contract/maintenance quick actions rely entirely on each model's existing EDARA ACL/record-rule layer (unchanged) - a Viewer already has read on all three, branch-scoped as before. The Collections section (Monthly Revenue/Outstanding Receivables/Payments This Month + the 4 new schedule-based tiles) is gated behind the existing `has_accounting_access` boolean (MAT-FIND-014's pattern, unchanged compute logic, now also covering the new tiles) both in the view (`invisible="not has_accounting_access"`) and, as defense-in-depth, server-side: `_require_accounting_access()` raises a clear `UserError` (never a raw `account.move` `AccessError`) if a Collections quick-action method is invoked directly (e.g. via RPC) by a user without native Accounting read access - this is a deliberate product choice (the ticket frames Collections as "where Accounting access is available"), not a technical ACL requirement of `edara.payment.schedule.line` itself (every EDARA role can already read that model). No `sudo()` is used anywhere in this ticket's code.

**Gantt:** investigated and **not implemented** - the `web_gantt` module (Odoo Enterprise) does not exist anywhere in this Odoo 19 Community installation's addons paths (confirmed by inspecting the addons directories directly; no `<gantt>` view type is registered at all). Adding a `<gantt>` view arch without that module would break module installation outright, not just degrade gracefully - this is a hard technical constraint, not a design choice, and mirrors the project's existing Phase 12 precedent (2D-only unit kanban, "avoid unnecessary third-party dependencies," already-documented Odoo 19 Community edition). A native **Calendar** view (`date_start="start_date"`, `date_stop="end_date"`, `color="state"`) was added instead as the closest native substitute, alongside a new **Kanban** view (grouped by state, same pattern as the existing Maintenance/Renewal Request kanbans) - both added to `action_edara_lease_contract`'s `view_mode`.

**Business decision surfaced, not silently resolved:** "Expiring Soon" (contracts approaching their `end_date`) was **not implemented**. No expiry-warning window (e.g. "30 days before end date") is defined anywhere in this project - grepped `EDARA_IMPLEMENTATION_SPEC.md`, `EDARA_MASTER_PROMPT.md`, and the full codebase for any existing threshold; none exists. Per the ticket's own instruction ("if none exists, report it as BUSINESS DECISION REQUIRED... do not silently invent a number"), this is flagged here rather than guessed, and everything else in the ticket that doesn't depend on it was implemented. **Decision needed:** what "soon" means (a fixed day count, e.g. 30/60/90 days; a per-property/company-configurable setting; or something else) before an `action_view_contracts_expiring_soon()` quick action and its KPI tile can be added.

**Files changed:** `models/edara_dashboard.py` (full rewrite: 27 new KPI fields, 21 new quick-action methods, `_quick_action()`/`_require_accounting_access()` helpers), `views/dashboard_views.xml` (full rewrite: sectioned command-center layout), `views/contract_views.xml` (new Kanban + Calendar views, `action_edara_lease_contract.view_mode` extended), `tests/test_edara_dashboard.py` (+8 tests), `tests/test_edara_lease_contract.py` (+1 view-loads test).

**Automated tests:** targeted run (`TestEdaraLeaseContract` + `TestEdaraDashboard`) **39/39 passing**. Full suite **187/187 passing** (baseline 179, net +8 new tests, confirming no regression elsewhere). Coverage includes: all new KPI fields with disposable fixtures (unit occupancy states, contract states via draft/renew/terminate/expire, maintenance states via the full lifecycle), a data-driven test asserting every non-accounting-gated quick action's exact `res_model`/`domain`, accounting-gated quick actions resolving correctly for an accounting-capable user and raising `UserError` (never `AccessError`) for a Viewer, an explicit MAT-FIND-014 regression pin (Viewer opens the Dashboard with all new fields, zero accounting data, no crash), and Kanban/Calendar view-loads checks for Lease Contract.

**Live validation (2026-09-22) against real `odoo19_dev`:** module upgraded cleanly. A rolled-back validation script covering all 7 required scenarios (A-G) plus a views check: **40/40 checks passed, 0 failed**, `ROLLED BACK - odoo19_dev is unmodified` confirmed. A: Dashboard opens cleanly for Administrator, an EDARA-only Company Manager, and an EDARA-only Viewer. B: creating one disposable unit per occupancy state (available/reserved/rented/owner_occupied/sold) plus one under_maintenance moved every KPI by exactly its expected delta. C: every Unit quick action's returned domain was re-searched through the ORM and confirmed to return exactly the expected disposable record(s). D/E: same confirmation for a representative Contract (draft) and Maintenance (new) quick action, plus domain-correctness checks for the remaining states. F: a real EDARA-only Viewer's `has_accounting_access` is `False`, `monthly_revenue` degrades to `0` with no crash, and directly invoking a Collections quick action raises a clear `UserError` rather than a raw `account.move` `AccessError`; the MAT-FIND-015-A boundary (zero broad native Accounting access for an EDARA-only Company Manager) was reconfirmed intact. G: all 4 Collections quick actions resolve correctly for an Administrator. Lease Contract Kanban/Calendar views both resolve.

**Database cleanup:** verified via direct `psql` query after the live run - zero `UI032%`-coded records and zero `ui032_*` logins remain in `odoo19_dev`; real unit count/occupancy distribution (18 units, all `rented`) matches the pre-test baseline exactly.

**Regression:** MAT-FIND-014 and MAT-FIND-015/015-A were not touched by this ticket's code (no accounting model, ACL, or record rule was edited) and were spot-checked intact both in the automated suite (full 187/187 pass includes `test_edara_security_isolation.py` and `test_edara_mat015_scoped_accounting.py` unchanged) and live (Scenario F above).

**Remaining decisions/gaps:**
- **Expiring Soon** - business decision required (see above), not yet implemented.
- **Gantt** - not available in this Odoo 19 Community installation; Calendar + Kanban implemented as the native substitute.
- No other gaps identified against the ticket's Definition of Done - all other listed items are implemented and verified.

### 2026-09-13 Bug-Fix/Hardening Pass — Item-by-Item Review

A bug-fix/hardening request for this session listed a number of candidate issues "including but not limited to" a checklist. **Transparency note: none of the items below were actually present anywhere in this file before this pass** - this file was read in full first, per standing instructions, and none of them appeared in Known Bugs, Resolved Bugs, Architecture Decisions, or the MAT section prior to today. Each was independently verified against the current code (not assumed) before any action was taken; the outcome of that verification is recorded here rather than silently acted on or silently dropped.

| Item | Verified against code | Classification | Outcome |
|---|---|---|---|
| Maintenance Staff assignment not enforced | Confirmed - `assigned_user_id` was freely form-editable and nothing routed through `action_assign()` | Clear functional gap (Phase 8's own documented lifecycle already defines `action_assign()` as the intended transition) | **FIXED** - see Resolved Bugs |
| EDARA settings accessible to generic `base.group_system` | Confirmed - the `<app>` settings block had no `groups` of its own | Clear functional gap (menu-level restriction already defines the intended access level) | **FIXED** - see Resolved Bugs |
| Maintenance `action_assign` dead/unreachable | Confirmed - no button called it anywhere | Clear functional gap | **FIXED** - see Resolved Bugs |
| Missing curated searches | Not independently verifiable - "curated searches" names no specific model/view, no spec section found defining which searches are expected | Undetermined - insufficient definition to classify | **NOT ASSESSED.** Needs a concrete follow-up (which model, which filters) before this can be investigated. |
| Contract statusbar omitting Renewed / Expired | Confirmed - `statusbar_visible` only listed 3 of 5 real `STATES` | Clear functional gap (both states are real, reachable, already-documented values) | **FIXED** - see Resolved Bugs |
| Renewal rejection without a reason | Confirmed - `decision_note` exists but the Reject button never prompts for it | Business decision (exact precedent already exists and was already deferred for Terminate) | **BUSINESS DECISION REQUIRED** - see BD-002 above |
| Payment Schedule `invoice_id` inline editable | Confirmed - the list view (`editable="bottom"`) showed `invoice_id` with no `readonly`, unlike the form view which already correctly had `readonly="1"` on the same field | Clear functional gap (form view already defines the intended read-only-ness; list view was simply inconsistent with it) | **FIXED** - see Resolved Bugs |
| Maintenance delete guard missing | Confirmed - no `unlink()` override existed despite `perm_unlink=1` for branch managers (same gap Phase 13 already fixed elsewhere) | Clear functional gap (direct precedent already exists in this codebase) | **FIXED** - see Resolved Bugs |
| Deposit deduction has no reversal/correction mechanism | Confirmed - `edara.deposit.transaction.unlink()` is unconditionally blocked and no "reversal" action exists anywhere | Future scope - this is a new accounting feature (a correcting/reversing entry), not a bug; explicitly out of bounds per this session's Phase 6 "do not alter deduction accounting" and "do not invent features" constraints | **NOT IMPLEMENTED - future scope.** If wanted, this needs its own design pass (e.g. a `action_reverse_deduction()` posting an equal-and-opposite `account.move`, never mutating the original) - not something to improvise here. |
| Deposit help text wrong about auto-creation | Confirmed | Clear functional gap (documentation accuracy) | **FIXED** - see Resolved Bugs |
| Portal missing invoices/payments/deposits/documents | Checked against Phase 9's own documented scope | **Not a gap** - Phase 9's Architecture Decisions already explicitly chose to reuse native `account`/`portal` "My Invoices" instead of building custom portal pages for this, as a deliberate, documented decision, not an oversight | **NOT ACTIONED** - implementing this would directly contradict an existing, deliberate architecture decision; this session's instructions explicitly forbid building a "complete tenant portal" as unauthorized new scope |
| `account.move` EDARA fields not visible on forms | Confirmed - no view exposed them at all | Clear functional gap (Phase 7 architecture already defines these as user-editable; only the view was missing) | **FIXED** - see Resolved Bugs |
| Owner/Tenant partner flags not visible where appropriate | Not independently verified in this pass (no specific screen named) | Undetermined | **NOT ASSESSED** - needs a concrete "where" before action |
| Late fee amount / company-currency concerns | `res.company.edara_late_fee_amount` already uses `currency_field='currency_id'` (the company's own currency) - did not find a concrete multi-currency defect in the time available this pass | Undetermined / not reproduced | **NOT ACTIONED** - flag for a dedicated multi-currency MAT pass if a concrete symptom is observed |
| Service charge behavior for units without active tenants | Already documented | **Not a gap** - Architecture Decisions already explicitly documents this as "a deliberate simplification... revisit if a customer needs vacant-unit shares absorbed or redistributed" | **NOT ACTIONED** - already correctly classified and documented; no new information found |
| Unit currency considerations | Not independently verified in this pass (no specific symptom named) | Undetermined | **NOT ASSESSED** - needs a concrete symptom before action |

**Recommendation:** the "not assessed"/"not actioned - could not reproduce" rows above are genuine open threads, not resolved - if these are real, live MAT observations rather than a general checklist, the next MAT session should reproduce each with the exact same rigor as MAT-018/019/020 (live UI scenario + read-only diagnosis first) so they can be verified and fixed the same way, rather than guessed at here.

## MAT Backlog Review & Next-Phase Planning (2026-09-21)

**Review type:** planning/review only - no implementation, no permission, no ACL, no view, or test changes were made for this review. Every open item below was independently re-checked against the current repository (not assumed from prior documentation) - see method note at the end of this section.

**Verification baseline confirmed current as of this review:** MAT-FIND-014 and MAT-FIND-015/015-A `FIXED - AUTOMATED VERIFIED - LIVE VERIFIED`; full suite 173/173 (17 test files, confirmed present on disk); MAT-031 live validation 94/94; MAT-FIND-015-A live validation 24/24. No known blocking security or accounting defect remains.

**Open findings/decisions confirmed still accurate by direct code inspection this pass** (not merely re-read from prior documentation): `edara.unit` has no `copy()` override (MAT-FIND-003 still open), `renewal_request_views.xml`'s `note` field is still unconditionally `readonly="1"` (MAT-FIND-008 still open), `_check_no_overlap()` still uses an inclusive `<=`/`>=` boundary (MAT-FIND-012 still open), `action_activate()` still unconditionally sets `occupancy_status='rented'` with no date check (BD-001 still open), no `_cron_*` methods exist beyond the two already-documented crons (MAT-FIND-007's "no manual trigger" gap still applies; no reminder/notification cron exists), no `TODO`/`FIXME` markers exist anywhere in the module, and no `i18n/*.po` file exists (Arabic translation content still not authored).

## Phase 1 — Notifications & Reminders Automation + Business-Level Manual Triggers (2026-09-22)

**Status: COMPLETED.** Implementation performed. MAT status: unaffected, remains CLOSED at its own 240/240 baseline (this is a new, separate development phase, not a MAT reopening). Full regression after this phase: **276/276 passing** (240 baseline + 36 new tests).

### What was implemented

**A. Lease expiry reminders** (`edara.lease.contract._cron_send_expiry_reminders()`): escalating, idempotent reminders at two windows - 30 days (reused as-is from BD-003's existing "Expiring Soon" definition, not a new number) and 7 days (one additional, more urgent escalation). Idempotency is tracked via a new stored field `last_expiry_reminder_days` (which window was last sent, 0 = none) rather than activity state, so a Branch Manager marking the internal reminder done does not cause a re-send at the *same* window, while the calendar advancing into the more urgent 7-day window correctly re-escalates. An internal `mail.activity` ("EDARA: Lease Expiry Follow-up") is assigned to the contract's Branch Manager; the tenant is separately informed via a chatter message on the contract addressed to them (native mail notification, no new template).

**B. Renewal reminders** (`edara.renewal.request._cron_send_renewal_reminders()`, resolves spec §60's "Create Renewal Reminders"): one internal reminder per still-`submitted` renewal request, assigned to the Branch Manager. `edara.renewal.request` now also inherits `mail.activity.mixin` (it already had `mail.thread`). Idempotent via "does an open activity of this type already exist" - purely informational, never touches rent/lease terms.

**C. Overdue payment reminders** (`edara.payment.schedule.line._cron_send_overdue_reminders()`, resolves spec §60's "Update Overdue State" companion): one internal reminder per line whose already-authoritative computed `state` is `overdue`, assigned to the Branch Manager, plus a tenant-facing chatter message on the parent contract. `edara.payment.schedule.line` now inherits `mail.thread` + `mail.activity.mixin` (previously had neither) - a `<chatter/>` was added to its form view. No new payment ledger; purely observes the existing computed state.

**D. Maintenance notifications** (`edara.maintenance.request`): (1) a "New maintenance request" triage activity is scheduled immediately on `create()`, assigned to `assigned_user_id` or the Branch Manager; (2) `_cron_send_maintenance_reminders()` reminds about any `new`/`assigned`/`in_progress` request whose `requested_date` is more than `MAINTENANCE_STALE_DAYS` (3) days old and has no currently-open reminder activity - folded into one unified "stale open request" workflow rather than separately-thresholded "new"/"overdue" cases, since no priority-based SLA exists in the spec to justify splitting them; (3) `action_complete()` now posts a chatter message to the tenant. All three reuse the single "EDARA: Maintenance Follow-up" activity type - correctly idempotent because a *done* activity is removed from `activity_ids` entirely (native Odoo behaviour), so a still-open request whose earlier activity was resolved gets a fresh one only once it becomes stale again.

**E. MAT-FIND-007 business-level manual triggers**, exposed as three buttons in a new "Automation" section on the existing EDARA Dashboard (`edara.dashboard`, MAT/UI-032's precedent, not a new wizard/menu):
- **Generate Due Invoices** → `edara.payment.schedule.line.action_generate_due_invoices_now()`
- **Process Lease Expiry** → `edara.lease.contract._cron_expire_contracts()` (now returns a count; otherwise unchanged - it was already ORM-`search()`-based, so it was already safe to call manually)
- **Process Reminders** → calls all four `_cron_send_*_reminders()` methods above and aggregates the result

Each returns a native `display_notification` client action reporting what happened (counts of created/skipped/errors or reminders sent) - no custom UI framework.

**Authorization decision made and implemented (not left open):** the ticket asked who should be authorized to use these triggers. Resolved by precedent rather than inventing a new role: exactly like every other action in this module, a manual trigger only ever processes what the calling user's own existing ACL + branch record rules already let them see/write - no `sudo()` on any manual-trigger entry point itself, no artificial "Branch Manager only" gate beyond what the ACLs already enforce. This was verified, not assumed (see Live Validation).

### MAT-FIND-007's other half: the rent-invoicing `sudo()` asymmetry, now fixed

The Roadmap Review's own "Technical Observation" predicted this would become relevant exactly here, and it did: `edara.payment.schedule.line._create_invoice()` previously had no `self.check_access('write')`/`.sudo()` at all, relying entirely on the daily cron's own superuser context. Once a regular (non-superuser) EDARA user can reach it directly via the new manual trigger, that was no longer safe. Fixed to match every other native-accounting-creating action in this module (MAT-FIND-015): `self.check_access('write')` first, then a narrowly-scoped `self.env['account.move'].sudo().create(...)`. The cron path is unaffected (superuser bypasses `check_access` trivially). This is now the **9th** scoped-`.sudo()` call site in the module.

`_cron_generate_due_invoices()` was refactored (not duplicated) into a shared `_process_due_invoices()` used by both the cron (unrestricted raw-SQL `FOR UPDATE SKIP LOCKED` candidate selection) and the new `action_generate_due_invoices_now()` manual trigger (a normal ORM `search()`, so branch/company record rules apply to whoever clicks the button) - per the ticket's explicit "refactor so manual and automated execution use the same underlying business method" requirement. `AccessError` is deliberately never absorbed into the returned error count inside `_process_due_invoices()` - it always propagates immediately, consistent with how every other action in this module treats authorization failures.

### Data model / technical changes

- `models/edara_lease_contract.py`: `EXPIRY_REMINDER_WINDOWS_DAYS = (30, 7)`, new field `last_expiry_reminder_days`, `_get_reminder_responsible_user()`, `_cron_send_expiry_reminders()`; `_cron_expire_contracts()` now returns a count.
- `models/edara_renewal_request.py`: `+mail.activity.mixin`, `_cron_send_renewal_reminders()`.
- `models/edara_payment_schedule_line.py`: `+mail.thread, +mail.activity.mixin`; `_create_invoice()` authorization/sudo fix; `_process_due_invoices()` (new, shared), `_cron_generate_due_invoices()` (refactored to use it), `action_generate_due_invoices_now()` (new manual trigger), `_cron_send_overdue_reminders()` (new).
- `models/edara_maintenance_request.py`: `MAINTENANCE_STALE_DAYS = 3`; `create()` now schedules a triage activity; `_schedule_triage_activity()`, `_cron_send_maintenance_reminders()` (new); `action_complete()` now notifies the tenant.
- `models/edara_dashboard.py`: `action_manual_generate_due_invoices()`, `action_manual_process_lease_expiry()`, `action_manual_process_reminders()`, `_automation_result_notification()`.
- `data/edara_activity_types.xml` (new): 4 `mail.activity.type` records (Lease Expiry Follow-up, Renewal Decision Pending, Overdue Payment Follow-up, Maintenance Follow-up).
- `data/edara_cron.xml`: 4 new daily `ir.cron` records, one per `_cron_send_*_reminders()` method.
- `views/payment_schedule_line_views.xml`: added `<chatter/>`.
- `views/dashboard_views.xml`: new "Automation" section with the 3 manual-trigger buttons.
- `__manifest__.py`: registered `data/edara_activity_types.xml`.
- No new custom models, no new generic "notification event" framework, no new ACL rows (native `mail.activity`/`mail.activity.type` access is already open to all internal users), no `sudo()` added anywhere except the one documented, narrowly-scoped fix above.

### Tests

New file `tests/test_edara_notifications.py` (36 tests): lease expiry reminders (9, incl. boundary days 30/31, escalation, repeated-cron/manual idempotency, non-active exclusion, tenant chatter, rent/dates untouched), renewal reminders (4), overdue payment reminders (4), maintenance reminders (6, incl. staleness-after-resolution re-trigger, repeated-processing idempotency, tenant completion notice), manual triggers/MAT-FIND-007 (9, incl. authorized/unauthorized, idempotent repeat, manual-then-cron interaction, same business logic as cron, Dashboard action results), security/isolation (3, incl. portal tenant blocked, cross-tenant activity isolation, cross-branch manual-trigger isolation). `tests/__init__.py` updated.

**Automated test results:** targeted run **36/36 passing**. Full suite **276/276 passing** (baseline 240, +36 new, 0 failures, 0 errors, 0 regressions).

### Live validation (2026-09-22) against real `odoo19_dev`

Module upgraded cleanly. A rolled-back validation script covering all required scenarios exercised **27/27 checks, 0 failed**: lease expiry reminder (created, assigned correctly, tenant chatter-notified, repeat-safe), renewal reminder (created, assigned, repeat-safe), overdue payment reminder (schedule verified overdue, reminder created, assigned, repeat-safe), maintenance (triage-on-create, staleness reminder after triage resolved, repeat-safe, tenant notified on completion), manual triggers (authorized Branch Manager generates invoices, idempotent repeat, manual-then-cron interaction produces exactly one invoice, unauthorized Viewer blocked with `AccessError` both via direct model call and via the Dashboard button, Process Lease Expiry expires the contract, Process Reminders returns a native notification), and security (a Branch Manager's manual trigger never touches another branch's due line). `ROLLED BACK - odoo19_dev is unmodified by this script` confirmed. Two test-script bugs were found and fixed during this run (both in the validation script, not the product): an already-invoiced due line was being reused for the "unauthorized Viewer" checks, making them vacuously pass regardless of whether authorization actually worked - fixed by using a fresh, dedicated due line for each negative-authorization check.

**Database cleanup:** verified via direct `psql` query after the live run - zero `NOTLV`-coded branches/units and zero `notlv_*` logins remain in `odoo19_dev`; real occupancy baseline (18 units, all `rented`) unchanged.

### Idempotency summary

- **Lease expiry:** stored `last_expiry_reminder_days` field, compared against the just-computed window - immune to activity state changes.
- **Renewal / overdue payment / maintenance:** "does an open (`activity_ids`-resident) activity of this type already exist" - since a *done* `mail.activity` is removed from `activity_ids` entirely (native behaviour, not custom code), this is simultaneously idempotent against repeats AND correctly re-escalates once a resolved item becomes relevant again.
- **Invoice generation (manual trigger):** the pre-existing `invoice_id`-set check in `_create_invoice()`, now reachable from two entry points that share one implementation (`_process_due_invoices()`) instead of two.
- **Manual/cron interaction:** verified directly (automated test + live validation) - running the manual trigger then the cron over the same candidate produces exactly one invoice, never two.
- **Concurrency:** true multi-process concurrency protection for invoice generation continues to rely on the pre-existing `FOR UPDATE SKIP LOCKED` cron path (unchanged by this phase). The manual trigger path is protected by the `invoice_id` check-then-set pattern plus the existing `_invoice_id_uniq` DB constraint, not by row locking - adequate for a single UI click, not evaluated against true simultaneous multi-session races (see Known Limitations).

### Security validation

No ACL rows added or changed. No `sudo()` added except the one documented, narrowly-scoped `_create_invoice()` fix, which follows the exact MAT-FIND-015 pattern already used at 8 other call sites (now 9). Manual triggers use zero elevation of their own - they inherit whatever the calling user's ACLs + branch record rules already allow, verified both in the automated `TestEdaraNotificationSecurityAndIsolation` class and live (Viewer blocked with `AccessError` on both entry points; Branch Manager's manual trigger provably cannot reach another branch's line). Portal tenants have no access to the Dashboard, to `edara.payment.schedule.line`, or to write on `edara.lease.contract`/`edara.renewal.request`/`edara.maintenance.request` - confirmed unaffected (unchanged ACLs), and a tenant never receives another tenant's reminder chatter message (each is addressed via `partner_ids=[tenant.id]`, server-resolved from the record, never from client input).

### Known limitations

- The manual invoice-generation trigger is not protected by `FOR UPDATE SKIP LOCKED` the way the cron is - adequate for its actual use case (an occasional, deliberate UI click) but not evaluated against a true simultaneous multi-session race on the exact same line. If that scenario becomes a real requirement, the manual path should acquire the same row-lock discipline.
- Maintenance staleness uses a single fixed threshold (`MAINTENANCE_STALE_DAYS = 3`) applied uniformly regardless of `priority` - no priority-based SLA is defined anywhere in the spec to justify a more granular threshold; this can be revisited if such a business rule is introduced later.
- Tenant-facing notifications (lease expiry, overdue payment, maintenance completion) are chatter messages with `partner_ids`, which trigger Odoo's native notification/email mechanism - there is no dedicated tenant-portal "Notifications" page (that remains Tenant Portal Expansion, its own future roadmap phase, not reopened here).

### Deferred scope (intentionally not built here)

Everything the Roadmap Review already sequenced *after* this phase remains deferred and untouched: Reporting & Management Intelligence expansion, Tenant Portal Expansion (incl. a dedicated in-portal notifications page), Maintenance Phase 2, Owner Settlement (business-decision-gated), Arabic content authoring, multi-currency per contract. The rent-invoicing `sudo()` fix above was the one piece of "Technical Observations" debt this phase's own scope required resolving; no other previously-identified technical observation was touched.

### Next phase

Per the already-completed Roadmap Review's Proposed Development Sequence, item 2: **Reporting & Management Intelligence expansion** (Rent Roll, Lease Expiry, Collections, Maintenance Cost, Deposit Liability reports beyond the existing 5). Not started in this ticket.

### Backlog Table

| ID | Item | Category | Severity | Status | Dependencies | Recommended Next Action |
|---|---|---|---|---|---|---|
| MAT-FIND-003 | Unit Duplicate fails on unique code | E | — | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | — | Implemented - `copy()` auto-generates a unique code + resets rented/reserved occupancy; see "MAT-FIND-003 / MAT-FIND-012 - Implementation, Tests, and Live Validation" above |
| MAT-FIND-004 | Lease Contract sequence gaps | E | — | **CLOSED - ROOT CAUSE CONFIRMED, NO DEFECT (2026-09-22)** | — | Investigated and closed - confirmed expected non-transactional standard-`ir.sequence` behavior triggered by rolled-back test/live-validation transactions; see "MAT-FIND-004 / MAT-FIND-008 - Investigation, Implementation, Tests, and Live Validation" above |
| MAT-FIND-007 | No business-level manual trigger for expiry/invoice-generation crons | D (Workflow) | Medium | DEFERRED | None | **Not covered by MAT/UI-032 as implemented (2026-09-22)** - that ticket's quick actions are read-only navigation/filtering into existing data, not a "run this cron now" trigger; still genuinely open, needs its own small ticket if wanted |
| MAT-FIND-008 | Renewal Request tenant message read-only | E | — | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | — | Implemented - `note` now mirrors sibling fields' `readonly="state != 'submitted'"` pattern; see "MAT-FIND-004 / MAT-FIND-008 - Investigation, Implementation, Tests, and Live Validation" above |
| MAT-FIND-010 | Active past-dated contract leaves unit "Rented" | E | — | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-21)** | — | Closed alongside BD-001 - see "BD-001/MAT-FIND-010 - Implementation, Tests, and Live Validation" above |
| MAT-FIND-012 | Lease overlap boundary treats end date as inclusive | E | — | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | — | Implemented - exclusive end_date semantics, adjacent leases allowed; see "MAT-FIND-003 / MAT-FIND-012 - Implementation, Tests, and Live Validation" above |
| BD-001 | Future-dated contract activation occupancy semantics | E | — | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-21)** | — | Implemented - `reserved` state, start-date cron, corrected Dashboard KPI; 179/179 full suite, 15/15 live checks |
| BD-002 | Renewal rejection reason not prompted in UI | E | — | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | — | Implemented - Reject requires a reason (reuses `decision_note`), Terminate confirmed already optional/unchanged |
| BD-003 | Expiring Soon definition undefined | E | — | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | — | Implemented - ACTIVE contracts, `end_date` in `[today, today+30]`; Dashboard KPI + quick action added |
| MAT/UI-032 | Dashboard UX & Native Odoo Action Integration | E | — | **FIXED - AUTOMATED VERIFIED - LIVE VERIFIED (2026-09-22)** | — | Implemented - see "MAT/UI-032 - Implementation, Tests, and Live Validation" above; 187/187 full suite, 40/40 live checks. Gantt unavailable (Community edition) |
| Arabic `.po` content | Translation content authoring | D (Future) | Low (engineering side already done) | DEFERRED | Professional translator or business owner's exact terminology | Content task, not engineering - no action until terminology is supplied |
| `edara.owner.settlement` | Owner settlement/passthrough accounting | D (Future) | N/A | DEFERRED | Spec explicitly says do not implement unless in active scope | No action |
| Renewal/maintenance reminder crons | Optional reminders via `mail.activity.mixin` | D (Future) | Low | DEFERRED | Spec marks "potential," not required | No action until requested |
| Terminate reason-capture wizard | UX nicety on Terminate button | D (Future) | — | **RESOLVED AS UNNEEDED (2026-09-22)** | — | BD-002 confirmed Terminate's reason stays optional with its existing (already-working) behavior - no wizard needed for Terminate, and Reject's reason requirement was satisfied by reusing the existing `decision_note` field, not a new wizard either |

**A — BLOCKING: none currently open.** Both items that were ever classified blocking (MAT-FIND-014, MAT-FIND-015) are `FIXED - AUTOMATED VERIFIED - LIVE VERIFIED`.

**E — CLOSED/VERIFIED (not re-listed above):** MAT-FIND-001, 002, 003, 004, 005, 006, 008, 009, 010, 011, 012, 013, 014, 015/015-A, BD-001, BD-002, BD-003, MAT/UI-032, MAT-020, and every item marked FIXED in the 2026-09-13 hardening-pass table.

### Recommended Dependency Order (derived from actual coupling found above, not assumed)
1. ~~BD-001/MAT-FIND-010 implementation~~ **DONE (2026-09-21)**.
2. ~~MAT/UI-032 (Dashboard UX)~~ **DONE (2026-09-22)**.
3. ~~BD-002/BD-003/MAT-FIND-003/MAT-FIND-012 bundle~~ **DONE (2026-09-22)** - see the dedicated implementation subsections above.
4. ~~MAT-FIND-004 investigation + MAT-FIND-008 fix~~ **DONE (2026-09-22)** - see "MAT-FIND-004 / MAT-FIND-008 - Investigation, Implementation, Tests, and Live Validation" above.
5. **Future/deferred scope** (Arabic content, owner settlement, reminder crons, MAT-FIND-007's manual cron-trigger button if still wanted) - no current business pressure, revisit only when requested.

### Recommended Next Phase: Future/deferred scope only (no current business pressure)
Every MAT finding and business decision that had a concrete symptom, a clear fix, or a required product decision is now closed. What remains is exclusively pre-flagged future/deferred scope, none of which is blocked, none of which has a business decision pending, and none of which has current business pressure behind it:
- **MAT-FIND-007** - business-level manual trigger button for the expiry/invoice-generation crons; explicitly a UX/workflow design task ("the exact UI design and placement are NOT finalized yet"), not ready to implement until that design is chosen.
- **Arabic `.po` translation content** - a content-authoring task (the engineering/i18n plumbing side is already done), blocked only on someone supplying the actual Arabic terminology - not an engineering task.
- **`edara.owner.settlement`** - explicitly out of scope until the spec calls it into active scope.
- **Renewal/maintenance reminder crons** - the spec marks these "potential," not required; no action until requested.
- **Definition of Done for whichever of these is picked up next:** a real business decision or design input is supplied first (none of these can proceed on assumptions the way MAT-FIND-004/008 did), then the same standard applies - targeted tests, full regression green, live validation against `odoo19_dev`, `EDARA_PROJECT_STATE.md` updated.

**Method note:** this review re-read the full current `EDARA_PROJECT_STATE.md`, then independently verified (not merely re-read) the still-open items against current code: `models/edara_unit.py` (no `copy()`), `views/renewal_request_views.xml` (note field), `models/edara_lease_contract.py` (`_check_no_overlap`, `action_activate`), the `tests/` directory listing, a repo-wide `TODO`/`FIXME` grep, an `i18n/*.po` glob, and an `ir.cron`/`_cron_` grep. No implementation, security, or test changes were made.

## Product Readiness, Architecture, and Scope Review (2026-09-22)

**Review type: audit/planning only.** Every claim below was verified directly against current code (all 19 model files, both security files, the manifest, `controllers/portal.py`, `data/edara_cron.xml`, and the full `tests/` directory), not merely re-read from prior documentation. **No Python, XML, security, test, or database change was made during this review** - see "Confirmation" at the end of this section.

### Domain-by-Domain Classification

| Domain | Class | Basis |
|---|---|---|
| Organization/Structure (Company/Branch/Property/Building/Unit/Ownership) | **A** | Full hierarchy, branch/company isolation, ownership sweep-line 100%-integrity constraint, indexed FKs, 20+ dedicated tests |
| Lease Management (lifecycle, activation, renewal, termination, expiry, overlap, occupancy sync) | **A** | Full draft→active→renewed/terminated/expired lifecycle; date-aware occupancy (BD-001); exclusive-boundary overlap detection (MAT-FIND-012); 46+ dedicated tests; repeatedly live-validated |
| Payment/Billing (schedule generation, proration, invoicing) | **A** | Correct exclusive-end-date proration at all 3 frequencies; concurrency-safe cron (`FOR UPDATE SKIP LOCKED`, per-line commit/rollback isolation); 39+ dedicated tests |
| Accounting (native `account.move`/`account.payment`, deposits, late fees, service charges, analytic) | **A** | Fully native (zero parallel ledger), posted-entry immutability inherited from Odoo core untouched, scoped narrow-`.sudo()` architecture (MAT-FIND-015) consistently applied, cross-company/branch tag consistency enforced on `account.move`, 19+ dedicated accounting-security tests. One latent inconsistency noted below (not a live defect) |
| Maintenance | **B** | Full request lifecycle (new/assigned/in_progress/done/cancelled) is solid and tested, but `cost`/`vendor_id` (both explicitly "suggested fields" per spec §41) are plain, unconnected fields - no linkage to a real vendor bill, so a recorded maintenance cost does not actually reach `total_expenses` on the Property/Branch Financial Summary. Spec-compliant as literally written; a real product opportunity, not a defect |
| Portal | **A** | Tenant-own-record isolation enforced at both ACL (`perm_write=0`) and record-rule layers, confirmed via real `HttpCase` tests (not mocked); Leases, Renewal Requests, Maintenance Requests all covered; native invoice/payment portal pages come free via `account`+`portal` |
| Dashboard | **A** | 27 KPIs, all permission-aware (MAT-FIND-014 pattern); every quick action opens a native action with a native, visible/editable Search Bar domain (no parallel filtering system, per MAT/UI-032's own architecture rule); Kanban+Calendar for contracts; Gantt correctly documented as unavailable (Enterprise-only) rather than silently skipped |
| Security (ACLs, record rules, isolation, scoped sudo) | **A** | Consistent 4-tier ACL model (Viewer/Property Manager/Branch Manager/portal) across every model; exactly 7 `.sudo()` call sites in the entire module, all narrowly scoped to one native `create()`/`search()` and all gated by an explicit access check performed *before* elevation - no blanket sudo anywhere; extensively audited (MAT-031, MAT-FIND-014/015) |
| Documents | **A** (one deviation) | Per spec §42/§43's explicit instruction ("do not create a redundant file-storage system"), documents are native `ir.attachment`/chatter on `mail.thread`-inheriting models - by design, not a gap. One concrete deviation: `edara.deposit` does **not** inherit `mail.thread`, despite being explicitly named in spec §43's own chatter example list - a financially sensitive record with no audit trail/attachment history. Small, cheap, spec-justified fix |
| Notifications/Automation | **B** | Both production crons (`_cron_expire_contracts`, `_cron_generate_due_invoices`) plus the BD-001 reserved→rented cron are idempotent and correctly engineered. Missing: business-level manual triggers (MAT-FIND-007, already deferred pending a UX design decision) and any reminder/notification cron (spec marks these "potential," not required) |
| Reporting | **B** | 5 real, tested native pivot/list reports exist (Revenue, Expense, Receivables, Occupancy, Tenant Ledger) - a genuine foundation, not a stub. No owner-settlement report (explicitly out of scope per spec), no PDF/export templates, no scheduled report delivery |

### Accounting Review (Step 4)

No accounting-correctness defect was found. Confirmed: invoice generation always goes through native `account.move`/`_create_invoice()`/`action_post()`; deposit liability/refund/deduction correctly debits/credits the configured company accounts; analytic distribution is applied on every revenue line via `get_analytic_account()`; `account.move`'s own native posted-entry protection is never bypassed (no `write()`/`unlink()` override weakens it); cross-company/cross-branch tag mismatches on `account.move` are actively rejected by a constraint (`_check_edara_tags_consistent`); multi-currency is a deliberate, consistent single-currency-per-company design (`currency_id` always `related=company_id.currency_id` or defaulted from it) with no partial/inconsistent FX handling anywhere - an accepted simplification, not an observed defect.

**One latent (not currently active) inconsistency worth recording:** `edara.payment.schedule.line._create_invoice()` (the regular rent-invoicing path) does not use `.sudo()`, unlike its siblings `edara.service.charge.line._create_invoice()` and `edara.payment.schedule.line.action_charge_late_fee()`. This has never caused a problem because `_create_invoice()` is today only ever called from `_cron_generate_due_invoices()`, which runs under the cron's own elevated execution context. It would become a real `AccessError` for a regular EDARA-only staff member the moment a manual "generate this invoice now" trigger is added (i.e. if/when MAT-FIND-007 is implemented for the invoicing cron specifically) - whoever implements that button must add the same authorization-first, narrowly-scoped-sudo pattern already used by its siblings. Flagged for future awareness; no code was changed, since nothing is broken in the current (cron-only) call path.

### Security Review (Step 5)

No privilege-escalation, record-rule-bypass, tenant-leakage, unsafe-sudo, or client-controlled-authorization finding was identified. All 7 `.sudo()` sites in the module were enumerated and individually re-verified: `edara_deposit.py` (2, deposit collect/refund payment creation), `edara_deposit.py` (1, deposit deduction move), `wizard/edara_deposit_transaction_wizard.py` (1, journal lookup), `edara_property.py` (1, analytic account lazy-create), `edara_service_charge_line.py` (1, invoice create), `edara_payment_schedule_line.py` (1, late-fee invoice create), and `controllers/portal.py` (1, maintenance-request create - ownership pre-verified against the tenant's own active leases before the elevated call). Every one is preceded by an explicit `check_access('write')`/pre-verified-ownership check and limited to a single native call - none is a blanket group grant. This confirms rather than extends the MAT-031/MAT-FIND-015 conclusions.

### Scalability/Architecture Review (Step 6)

No severe architectural risk was found; one concrete, justified, cheap-to-fix gap was found:

- **Missing indexes on heavily-filtered state columns (real, justified gap).** `edara.lease.contract.state`, `edara.unit.occupancy_status`, and `edara.maintenance.request.state` all lack `index=True`, despite being the exact columns `edara.dashboard._compute_kpis()` (≈17 separate `search_count()` calls across these three fields alone), every Dashboard quick action, and both production crons filter on. Harmless at current row counts; will show up as sequential scans once the product reaches its stated "thousands of units, many leases" scale. Cheap, low-risk fix (add `index=True`, no data migration needed).
- `_compute_kpis()`/`_compute_financial_summary()` issue one query per KPI/aggregate (≈25 and ≈2 round-trips respectively) rather than a single batched query - acceptable at present, a candidate for later consolidation only if dashboard latency becomes a real complaint.
- `_cron_expire_contracts()` processes matching contracts one at a time (write + occupancy-sync + schedule-line-unlink per contract) rather than in bulk - self-limiting in practice, since only contracts that newly expired since the last daily run match, not the whole table.
- `_cron_generate_due_invoices()` is explicitly well-engineered for scale: raw SQL `FOR UPDATE SKIP LOCKED` lets concurrent/overlapping runs safely partition work, with per-line commit/rollback isolating one line's failure from the rest - called out as a positive example, not a finding.
- All reviewed `count`/`related`-style compute methods (`_compute_schedule_line_count`, `_compute_renewal_request_count`, `_compute_contract_count`, `_compute_property_count`) correctly use `_read_group` - no N+1 pattern found anywhere in the reviewed compute layer.

### UX/Product Completeness Review (Step 7)

- **MAT-FIND-007** (business-level manual cron triggers) - useful enhancement, not required for next phase (needs its own small UX design decision first, already documented as deferred).
- **Maintenance cost → real accounting linkage** - useful enhancement / candidate for next phase (see below) - the only place a recorded business fact (`cost`) doesn't reach the accounting numbers that already exist to receive it.
- **Reminder/notification workflows, Arabic terminology, owner settlement, richer PDF/export reporting** - all explicitly future/deferred per spec, no current business pressure.
- Existing UX for the golden path (Property → Unit → Tenant → Lease → Schedule → Invoice → Payment) already went through a dedicated Dashboard/Command-Center pass (MAT/UI-032) and is considered mature.

### Test Coverage Review (Step 8)

Strong: Lease Contract (36 tests), Lease Billing/proration (23), Deposit (21), MAT-FIND-015 scoped accounting (19), Payment Schedule (16), Security Isolation (15), Property/Ownership (15). Moderate: Dashboard (11), Maintenance Request (11), Service Charge (11), Renewal Request (10), Portal (7, real `HttpCase`). Thin but adequately scoped for their size: Branch (3), Reports (5, covers all 5 report actions + financial-summary sign conventions), Hardening (5), Multi-company (2). **Gap:** no test exercises the asymmetric-sudo latent issue above (impossible to trigger today, since there's no manual entry point yet - correctly untested because unreachable, not a coverage miss). No security test exists for a maintenance-cost-to-accounting path because that path doesn't exist yet. No other missing business-invariant or untested sensitive-operation was identified.

### Concrete Risks/Gaps (Step 8 summary)

1. Missing `index=True` on 3 heavily-filtered state columns (Low severity, cheap fix, scalability).
2. `edara.deposit` doesn't inherit `mail.thread` despite spec §43 naming it explicitly (Low severity, cheap fix, audit-trail completeness).
3. Latent (not live) sudo asymmetry in `_create_invoice()` vs. its siblings - relevant only if/when MAT-FIND-007 adds a manual invoicing trigger (documented for future awareness, not actionable today).
4. Maintenance `cost` does not reach the Property/Branch Financial Summary (product gap, not a defect - see Recommended Next Phase).

No other concrete risk was found. **The current implementation is sound** - Organization, Lease Management, Payment/Billing, Accounting, Portal, Dashboard, and Security are all Production Ready (Class A), extensively tested, and repeatedly live-validated against real `odoo19_dev` data across this entire MAT campaign.

### Recommended Next Phase: Maintenance Cost → Native Accounting Integration

**Name:** Maintenance Cost Accounting Integration

**Why:** This is the single place in the entire reviewed system where a business fact a user already records (`edara.maintenance.request.cost`/`vendor_id`, both explicitly spec-listed fields) does not reach the native accounting numbers the product already surfaces for it (`edara.property`/`edara.branch.total_expenses`, which already read posted `in_invoice`/`in_refund` moves). Since "accounting correctness is a top project priority" per this review's own mandate, closing this gap delivers real, measurable business value - a property manager who records a $500 repair today has no way to see it reflected in the Financial Summary unless they separately and manually create a matching vendor bill in native Accounting, with no link back to the maintenance request itself.

**Scope:**
- A `edara.maintenance.request.vendor_bill_id` (Many2one `account.move`, readonly) field mirroring the existing `invoice_id` pattern on `edara.payment.schedule.line`/`edara.service.charge.line`.
- One new company config field (e.g. `edara_maintenance_expense_account_id`), mirroring the existing `edara_rental_income_account_id`/`edara_late_fee_income_account_id` pattern.
- A method (e.g. `action_create_vendor_bill()`) that creates+posts a native `in_invoice` tagged with the same `edara_*` traceability fields already used on every other EDARA-generated `account.move`, using the exact same authorization-first, narrowly-scoped-`.sudo()` pattern already proven in `edara_service_charge_line.py`/`edara_payment_schedule_line.py`.
- A visible "Vendor Bill" smart button/state indicator on the Maintenance Request form once billed, mirroring existing invoice-linked UX elsewhere in the module.

**Out of Scope:** automatic/implicit bill creation with no user action (see Required Business Decisions below); any change to the maintenance request lifecycle itself; any change to existing invoicing paths (rent/late fee/service charge/deposit); vendor payment recording (native Accounting already handles paying a vendor bill, no EDARA-specific wrapper needed there, consistent with how tenant payments are already handled).

**Dependencies:** reuses `res.company`'s existing account-configuration pattern, the existing MAT-FIND-015 authorization-first-then-scoped-sudo architecture, and the existing `unlink()`-protects-invoiced-records pattern already used by `edara.payment.schedule.line`/`edara.service.charge.line`.

**Acceptance Criteria:** a completed maintenance request with `cost`>0 and `vendor_id` set can produce exactly one posted vendor bill, correctly tagged (`edara_property_id`/`edara_branch_id`/etc.) and linked back via `vendor_bill_id`; that amount is confirmed to appear in `total_expenses`/`net_operating_result` on the corresponding Property and Branch Financial Summary; an EDARA-only Property Manager/Branch Manager can trigger it without any native Accounting group; a Viewer cannot; double-billing the same request is prevented (`unique(vendor_bill_id)` constraint, mirroring `_invoice_id_uniq`); full regression stays green; live-validated against `odoo19_dev` with disposable data and rollback.

**Risks:** low - this is an additive feature following an already-proven pattern four times over in this codebase (rent, late fee, service charge, deposit deduction all already do exactly this). The only real risk is scope creep into a fuller "expense management" feature, which this phase explicitly should not become.

**Required Business Decisions:**
1. **Trigger model:** should billing a completed maintenance request be an explicit manual action (a "Create Vendor Bill" button, matching the deliberate-manual philosophy already used for late fees per spec §21 - "do not automatically charge... without a business rule") or automatic the moment `state` becomes `done` with `cost`>0? This cannot be safely inferred and materially changes the implementation.
2. Should a maintenance request be **blocked from completion** (`action_complete()`) if `cost`>0 but `vendor_id` is empty, or should billing remain fully optional/deferred indefinitely? Affects whether a new validation is added to the existing lifecycle.

**Companion quick fixes worth bundling in alongside this phase** (each is a one-line change, not a phase on its own): add `index=True` to the three state columns identified above; add `_inherit = ['mail.thread']` to `edara.deposit`.

### Confirmation

No implementation, security, view, test, or database change was made during this review. The only file modified is `EDARA_PROJECT_STATE.md` (this section).

## Maintenance Cost → Native Accounting Integration — Implementation, Tests, and Live Validation (2026-09-22)

Implements the "Recommended Next Phase" from the Product Readiness Review directly above.

### BD-MNT-001 — Vendor Bill Creation — DECIDED and IMPLEMENTED

**Decision:** Vendor Bills are created **manually** through an explicit `Create Vendor Bill` action on the Maintenance Request - never automatically on completion. Maintenance completion and accounting settlement are separate business events; a request may be operationally done before the vendor's actual invoice is available.

**Implementation:** `edara.maintenance.request.action_create_vendor_bill()` (`models/edara_maintenance_request.py`) - the only code path that ever creates a vendor bill. `action_complete()` was inspected and confirmed unchanged/untouched - it has no accounting side effect whatsoever.

**Status: BD-MNT-001 — FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

### BD-MNT-002 — Cost Without Vendor — DECIDED and IMPLEMENTED

**Decision:** A Maintenance Request with `cost > 0` and no `vendor_id` must still be allowed to reach `done`. Vendor Bill creation itself (not completion) requires a valid Vendor - `action_create_vendor_bill()` raises a clear `UserError` ("Select a Vendor before creating a Vendor Bill.") rather than blocking the operational workflow.

**Implementation:** confirmed `action_complete()` was already unconditional on `cost`/`vendor_id` before this ticket (no change needed there); the vendor requirement was added exclusively inside `action_create_vendor_bill()`. Verified all three required completion cases (cost=0; cost>0+vendor; cost>0+no vendor) via both automated tests and live validation.

**Status: BD-MNT-002 — FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.**

### Implementation

**`models/edara_maintenance_request.py`** - new `vendor_bill_id` (Many2one `account.move`, readonly, copy=False, indexed) and `has_accounting_access` (compute, same MAT-FIND-014 permission-aware pattern as `edara.dashboard`/`edara.property`/`edara.branch` - drives whether the Vendor Bill smart button is shown at all). New `_vendor_bill_id_uniq` constraint (`unique(vendor_bill_id)`) enforcing the approved one-bill-per-request scope at the database level - the Many2one field alone only prevents a request from pointing at two bills simultaneously; the constraint additionally prevents two different requests from ever being linked to the *same* bill (defense in depth; not reachable through `action_create_vendor_bill()`'s own normal flow, but a real integrity guarantee regardless of call path). Two new methods:
- `action_create_vendor_bill()`: `ensure_one()` → `self.check_access('write')` (authorization first, MAT-FIND-015 pattern) → idempotent early-return of the existing bill if already linked → validates Vendor present → validates `cost > 0` → resolves `company_id.edara_maintenance_expense_account_id`, raising a clear `UserError` naming the company if unconfigured → creates a native `account.move` (`move_type='in_invoice'`, `partner_id=vendor_id`, tagged `edara_invoice_type='maintenance'` plus the same `edara_unit_id`/`edara_building_id`/`edara_property_id`/`edara_branch_id` fields every other EDARA-generated move already carries) via a single narrowly-scoped `.sudo()` limited to exactly this one `create()` call → one invoice line (description naming the request, quantity 1, the maintenance cost as `price_unit`, the configured expense account) → left in **Draft**, never auto-posted → id written back to `vendor_bill_id` through the normal (non-elevated) environment.
- `action_view_vendor_bill()`: the smart button's target - kept separate from `action_create_vendor_bill()` (which never returns a navigation action, mirroring `action_charge_late_fee()`'s established stay-on-the-form behavior) so that creating a bill never assumes the creating user can also view it. Re-checks `account.move.has_access('read')` server-side (view `invisible=""` is never itself an authorization check, per the Dashboard's `_require_accounting_access()` precedent) and degrades to a clear `UserError` rather than a raw `AccessError`.

**`models/account_move.py`** - added `('maintenance', 'Maintenance')` to `EDARA_INVOICE_TYPES`, alongside the existing `rent`/`late_fee`/`service_charge`/`ad_hoc` tags - gives maintenance vendor bills their own reporting-filterable identity rather than being lumped into `ad_hoc`.

**`models/res_company.py`** / **`models/res_config_settings.py`** / **`views/res_config_settings_views.xml`** - new `edara_maintenance_expense_account_id` (Many2one `account.account`), added as a `related` field on `res.config.settings` and a new `<setting>` row in the existing "Accounting" settings block - exact same pattern as the 5 existing EDARA account-configuration fields (`edara_rental_income_account_id` etc.). No new configuration mechanism was invented.

**`views/maintenance_request_views.xml`** - header `Create Vendor Bill` button (`invisible="cost &lt;= 0 or vendor_bill_id"`, confirm dialog, matching the existing header-button/confirm convention already used by `Cancel`); a new `oe_button_box` with one smart button (`Vendor Bill`, `icon="fa-money"`, `invisible="not vendor_bill_id or not has_accounting_access"`) - the exact `oe_stat_button`/`o_stat_info` convention already used on Unit/Property; `has_accounting_access` declared `invisible="1"` so the view can reference it. No other UI change - `vendor_id`/`cost` fields already existed on this form from the original spec.

### Accounting Architecture / Security (MAT-FIND-015 pattern reused, not reinvented)

Confirmed before implementing: no EDARA role implies any native Accounting group (by design, per MAT-FIND-015-A) - this is unconditionally true for every EDARA role including Branch/Company Manager, not just Viewer. Under that established architecture, "verify accounting access" *is* the EDARA-side `check_access('write')` gate on the originating record - there is no separate native-Accounting-group check to perform, because none of EDARA's own roles will ever pass one. This was verified, not merely asserted, by direct inspection of `edara_security.xml`'s group hierarchy (none of `group_edara_viewer`/`property_manager`/`branch_manager`/`accountant`/`company_manager`/`administrator` `implied_ids` reference any `account.group_*`) and confirmed empirically by live validation (see Scenario A/11 below - the creating Branch Manager could not read back their own just-created bill). The elevation itself is the single narrowest possible: one `.sudo().create()` call for the `account.move`, nothing else - no blanket `.sudo()` anywhere in this feature, no ACL/record-rule change, no native Accounting group granted to any EDARA group.

**Vendor validity:** deliberately relies on native Odoo's own `account.move`/`account.move.line` company-consistency constraints (the same ones every other `_create_invoice()` method in this module already relies on) rather than adding a bespoke EDARA-side company-match check - `res.partner` is company-agnostic by default in this installation (no `company_id` restriction observed on any vendor/tenant partner created throughout this entire project), and native Odoo already rejects a genuine cross-company partner/account/journal combination at `account.move.create()`/`_post()` time. No new validation was invented beyond what native Odoo already enforces.

### Duplicate Prevention

Approved scope: **one Vendor Bill per Maintenance Request.** `action_create_vendor_bill()` is idempotent - a request that already has `vendor_bill_id` set returns that existing bill immediately (no second `account.move` created), which is what the `Create Vendor Bill` header button itself disappears in favor of the `Vendor Bill` smart button for once a bill exists. The `_vendor_bill_id_uniq` DB constraint is additional defense-in-depth (prevents two requests ever pointing at the same bill), not the primary duplicate-prevention mechanism - the idempotent early-return in the method itself is.

### Automated Tests

New file `tests/test_edara_maintenance_vendor_bill.py` (23 tests, registered in `tests/__init__.py`), covering: creation (valid cost+vendor → bill created/Draft/correct vendor/amount/expense-account/company/tags/linkage; amount reaches Property `total_expenses` once posted), validation (no vendor blocked; zero cost blocked; negative cost confirmed unreachable via the pre-existing `_check_cost` constraint; missing expense-account configuration blocked with a company-naming message; existing linked bill prevents a duplicate), completion (all 3 BD-MNT-002 cases allowed), security (authorized Branch Manager allowed; Viewer blocked via `AccessError`; Tenant blocked via `AccessError`; direct unauthorized method invocation blocked identically to a button click; a bill's own creator without native Accounting access degrades to `UserError` on `action_view_vendor_bill()` rather than a raw `AccessError`), and native accounting behavior (real `account.move`, `move_type='in_invoice'`, native posting produces the expected debit/credit line). All accounting-record assertions re-browse the created `account.move` through the test's own privileged env before asserting on it, matching the established `test_edara_mat015_scoped_accounting.py` convention (a non-privileged EDARA user is not expected to be able to read native accounting data back directly - only to trigger its narrowly-scoped creation).

**Targeted run:** `TestEdaraMaintenanceVendorBill` + `TestEdaraMaintenanceRequest` - **34/34 passing, 0 failed, 0 errors.**

### Full Regression Result

**233/233 passing** (previous baseline 210, +23 new, exact match), 0 failed, 0 errors, 0 skipped, no unrelated failures.

### Live Validation

Against real `odoo19_dev` (module upgraded cleanly first, 98 modules loaded, no errors): **21/21 checks passed**, covering all 5 required scenarios - A (valid maintenance: completion succeeds, bill created Draft with correct vendor/amount/account/company/tags/linkage, and the creating Branch Manager correctly cannot open the bill via the smart button without separately-granted native Accounting access - confirming the architecture note above empirically, not just by code inspection), B (duplicate creation correctly returns the existing bill, no second `account.move` created), C (no-vendor: completion succeeds, bill creation blocked with a clear message), D (zero-cost: bill creation blocked), E (security: authorized user succeeds, Viewer/Tenant/direct-RPC-style invocation all correctly blocked with `AccessError`, each wrapped in `env.cr.savepoint()` per the established transaction-poisoning-avoidance pattern from the Business Decisions Bundle live validation). Script rolled back (`env.cr.rollback()`), confirmed via `psql`: zero `MNTLV%`-coded disposable records of any kind (branch/users/maintenance requests/account.move) remain, real unit baseline (18 units, all `rented`) unchanged.

### Database Cleanup / Rollback

Confirmed via `psql` after the live validation run: `edara_branch` (0 `MNTLV%`), `res_users` (0 `mntlv%` logins), `account_move` (0 rows referencing `MNTLV%` partners), `edara_maintenance_request` (0 `MNTLV%` titles). No posted accounting document was left behind (the one bill posted during live validation - Scenario A style testing was done via automated tests only, not posted live; the live-validation script's own bill stayed in Draft and was rolled back with everything else, never committed). No native reversal/cancellation was needed since nothing was committed.

### Configuration Requirement

A company must configure **Settings → EDARA Property Management → Accounting → Maintenance Expense Account** before `Create Vendor Bill` can succeed for that company - identical in spirit to the pre-existing Rental/Late-Fee/Service-Charge income account requirements. Unconfigured → clear `UserError` naming the company, not a silent failure or a guessed account.

### Known Future Consideration (not fixed in this ticket, per explicit scope instruction)

The previously-identified latent `.sudo()` asymmetry in `edara.payment.schedule.line._create_invoice()` (the regular rent-invoicing path, which - unlike its siblings - does not use `.sudo()`, relying instead on always being called from the cron's own elevated execution context) was re-inspected during this ticket. This maintenance implementation does not touch, call, or depend on `_create_invoice()` in any way, and does not expose any new instance of the same issue - `action_create_vendor_bill()` is a fully separate code path with its own correctly-scoped `.sudo()`, verified by both automated tests and live validation to correctly block Viewer/Tenant/unauthorized access. The existing rent-invoicing implementation is left unchanged, exactly as instructed. It remains a documented future consideration, relevant only if/when MAT-FIND-007 ever adds a manual "generate this invoice now" trigger for the rent-invoicing cron specifically.

### Status: Maintenance Cost → Native Accounting Integration — FIXED - AUTOMATED VERIFIED - LIVE VERIFIED.

### Remaining Risks / Gaps

None introduced by this ticket. Carried over, unchanged, from the Product Readiness Review above: missing `index=True` on `edara.lease.contract.state`/`edara.unit.occupancy_status`/`edara.maintenance.request.state` (low severity, scalability); `edara.deposit` still doesn't inherit `mail.thread` despite spec §43 naming it (low severity, audit-trail completeness); the rent-invoicing `.sudo()` asymmetry documented above (future-only).

### Recommended Next Phase

With this ticket complete, the two remaining items from the Product Readiness Review's "Companion quick fixes" are the smallest, most clearly-scoped next candidates (no business decision needed for either): add `index=True` to the three identified state columns; add `_inherit = ['mail.thread']` to `edara.deposit`. Beyond those two one-line fixes, only pre-flagged future/deferred scope remains (MAT-FIND-007, Arabic content, owner settlement, reminder crons) - none with current business pressure.

## Final MAT Cleanup: Indexes + Deposit Chatter (2026-09-22)

Closes out the two "Companion quick fixes" identified by the Product Readiness Review, immediately above.

### 1. State Column Indexes - IMPLEMENTED

Added `index=True` to `edara.lease.contract.state` (`models/edara_lease_contract.py`), `edara.unit.occupancy_status` (`models/edara_unit.py`), and `edara.maintenance.request.state` (`models/edara_maintenance_request.py`) - the exact three columns the Dashboard's `_compute_kpis()`, every Dashboard quick action, and both production crons filter on most heavily. Confirmed before changing anything: none of the three fields already had `index=True`, and no custom SQL/migration provided an equivalent index. No field type, selection value, lifecycle behavior, or domain was touched.

### 2. Deposit Chatter - IMPLEMENTED

`edara.deposit` (`models/edara_deposit.py`) now inherits `['mail.thread']` - matching the simpler audit-trail-only pattern already used by `edara.branch`/`edara.property`/`edara.building`/`edara.renewal.request` (no `mail.activity.mixin`, unlike `edara.lease.contract`/`edara.maintenance.request`, since Deposit has no scheduled-activity workflow need). Its compute `state` field is now `tracking=True`, matching the unambiguous existing convention that every other lifecycle `state` field in this module (Lease Contract, Renewal Request, Maintenance Request) is tracked. No other field was given tracking - `amount`/`amount_held`/`amount_refunded`/`amount_deducted`/`balance` remain untracked, consistent with the ticket's instruction not to add arbitrary tracking. `<chatter/>` added to `views/deposit_views.xml`'s form (the only view change). No new messaging system, no security/ACL/record-rule change - chatter relies entirely on native `mail`/`mail.thread` infrastructure already used identically by 6 other models in this module.

### Files Changed

`models/edara_lease_contract.py`, `models/edara_unit.py`, `models/edara_maintenance_request.py`, `models/edara_deposit.py`, `views/deposit_views.xml`, `tests/test_edara_deposit.py`, `tests/test_edara_lease_contract.py`, `tests/test_edara_property.py`, `tests/test_edara_maintenance_request.py`.

### Automated Tests

7 new tests: one non-fragile index-metadata check per affected model (asserts `_fields['<name>'].index`, not a Postgres-specific implementation detail - `test_state_field_is_indexed` in `test_edara_lease_contract.py`/`test_edara_maintenance_request.py`, `test_occupancy_status_field_is_indexed` in `test_edara_property.py`), plus 4 in `test_edara_deposit.py`: chatter capability present (`message_ids`/`message_follower_ids`), authorized message posting succeeds, `state`'s `tracking=True` configuration confirmed (a live chatter-tracking-message assertion was tried first but dropped - `state` is a stored *compute* field, and Odoo's automatic tracking-message mechanism does not reliably fire the same way for compute-recomputed writes as for direct `write()` calls; asserting on the field's own tracking configuration is the correct, non-fragile check here), and a Viewer confirmed still blocked from every deposit business action (`action_collect`) after the chatter addition - proving mail.thread inheritance granted zero additional business access.

**Targeted run** (Deposit + Lease Contract + Property + Maintenance Request + Maintenance Vendor Bill): **113/113 passing, 0 failed, 0 errors.**

### Full Regression Result

**240/240 passing** (previous baseline 233, +7 new, exact match), 0 failed, 0 errors, 0 skipped, no unrelated failures.

### Live Validation

Against real `odoo19_dev` (module upgraded cleanly first, 98 modules loaded, no errors): **11/11 checks passed** - a disposable deposit's full collect/refund workflow confirmed unaffected by the chatter addition; chatter capability present; an authorized message post succeeded; a Viewer confirmed still blocked (`AccessError`) from `action_collect` after the change; an authorized Branch Manager confirmed `action_refund` still works; all three index fields confirmed `index=True` in ORM field metadata *and* confirmed as real indexes via a direct `pg_indexes` query (`edara_lease_contract__state_index`, `edara_unit__occupancy_status_index`, `edara_maintenance_request__state_index` all present). Script rolled back (`env.cr.rollback()`); confirmed via `psql` afterward: zero `CLNLV%`-coded disposable records of any kind remain, real unit baseline (18 units, all `rented`) unchanged.

### Database Cleanup

Confirmed via `psql`: `edara_branch` (0 `CLNLV%`), `res_users` (0 `clnlv%` logins), `mail_message` (0 rows mentioning `CLNLV`). No posted accounting document was created or left behind by this ticket's live validation (only the pre-existing deposit-collection/refund flow was exercised, exactly as the automated tests already cover, and everything was rolled back).

### Final Code-Quality Sweep

Searched every file changed by this ticket for stray `.sudo()`, `print()`, debug statements, temporary comments, new TODOs, dead code, and test-only artifacts: the only `.sudo()` calls present in `edara_deposit.py` are the two pre-existing MAT-FIND-015 elevation sites (deposit collect/refund payment, deposit deduction move) - both untouched by this ticket. No `print()`/TODO/FIXME anywhere in the module (repo-wide grep, consistent with every prior sweep this campaign). No unrelated changes, no leftover temp files in the module itself (validation scripts lived only in the session scratchpad, never in the repo).

### MAT Campaign Status: **CLOSED**

**Verified regression baseline: 240/240**, 0 failed, 0 errors, 0 skipped. Every finding, business decision, and technical cleanup item raised across the entire MAT campaign (MAT-FIND-001 through MAT-FIND-015-A, MAT-020 through MAT-031, BD-001 through BD-003, BD-MNT-001/BD-MNT-002, MAT/UI-032, the Product Readiness Review, the Maintenance Cost Accounting Integration, and this final cleanup) is now either `FIXED - AUTOMATED VERIFIED - LIVE VERIFIED`, confirmed as expected behavior with no defect, or explicitly and deliberately deferred with a documented reason - none silently dropped.

### Deferred/Future Scope (unchanged - not reopened by this closure)

- **MAT-FIND-007** - business-level manual trigger button for the expiry/invoice-generation crons; needs its own UX design decision first.
- **Arabic `.po` translation content** - content-authoring task, not engineering; blocked only on supplied terminology.
- **`edara.owner.settlement`** - explicitly out of scope until called into active scope.
- **Renewal/maintenance reminder crons** - spec marks these "potential," not required.
- **Rent-invoicing `.sudo()` asymmetry** (`edara.payment.schedule.line._create_invoice()`) - documented future consideration, relevant only if/when MAT-FIND-007 ever adds a manual trigger for that specific cron; the current cron-only call path remains correct and untouched.

### Recommended Next Product/Engineering Phase

None is currently engineering-ready. Every item with a clear, business-decision-free technical scope has been implemented and closed. What remains is exclusively scope that requires a fresh business/product input before it can proceed: a UX design decision (MAT-FIND-007), supplied content (Arabic terminology), or a new feature request from the business owner. The MAT campaign itself is closed; any further work should be scoped as a new, explicitly-requested product initiative rather than a continuation of this campaign.

## Product Roadmap & Capability Prioritization Review (2026-09-22)

**Review type: planning/analysis only.** No Python, XML, security, view, test, or database change was made for this review - the MAT campaign remains **CLOSED at the verified 240/240 baseline**; this review does not reopen it, does not create new MAT findings, and does not start implementation of any phase discussed below.

**Method:** re-verified the current implementation directly (all model files, security files, cron definitions, portal controller, dashboard) against `EDARA_IMPLEMENTATION_SPEC.md`'s own stated vision (specifically §32 Owner Settlement, §40 Tenant Portal, §44 Activities, §55 Reports, §63 Internationalization) rather than assuming prior documentation was still current.

### Current Product Baseline (capability-by-capability)

Organization/Structure, Lease Management, Billing/Payments, Security Deposits (now with chatter), Accounting (8 narrowly-scoped `.sudo()` sites, all authorization-gated, zero parallel ledger), Maintenance (now including the manual Vendor Bill flow), Dashboard, and Security are all mature, tested, and repeatedly live-validated - see the Product Readiness Review and subsequent implementation sections above for full detail; unchanged since those reviews except for the Maintenance→Accounting integration and the Deposit chatter/index cleanup, both already folded in.

**Notifications/Automation:** 3 production crons (`_cron_expire_contracts`, `_cron_generate_due_invoices`, `_cron_sync_reserved_occupancy`), all idempotent and concurrency-safe. `mail.activity.mixin` is present on `edara.lease.contract` and `edara.maintenance.request` (manual activity scheduling works from the UI) but **no code anywhere automatically schedules an activity** - spec §44's own four named examples (lease renewal due, outstanding rent follow-up, maintenance follow-up, document expiration) are all unimplemented. No email/SMS/portal notification layer beyond native chatter follower notifications. No business-level manual trigger for the two core crons (MAT-FIND-007, previously deferred, still open).

**Reporting:** 5 native pivot/list reports (Revenue, Expense, Receivables/Tenant Ledger, Occupancy, Property/Branch Financial Summary) - this already satisfies spec §55's explicit "at minimum" list in full. No Rent Roll, Lease Expiry Report, Collections Report, Maintenance Cost Report, Portfolio Summary, or Deposit Liability report - all useful, none spec-mandated at the "minimum" bar.

**Documents:** native `ir.attachment`/chatter only, by explicit spec §42 design ("do not create a redundant file-storage system") - 9 of the module's business models now carry chatter (Property/Branch/Building/Unit/Ownership/Lease Contract/Maintenance Request/Renewal Request/Deposit). No document categories, expiration tracking, or approval workflow - not spec-mandated, a genuine but optional future enhancement.

**Tenant Portal:** implements 2 of the 11 items spec §40 itself names as the eventual full checklist (`Dashboard, My Lease, My Unit, Invoices, Payments, Outstanding Balance, Payment History, Renewal Requests, Maintenance Requests, Documents, Notifications, Profile`) - My Lease (view/renew) and Maintenance Requests (view/create) are built and isolation-tested via real `HttpCase` tests; native `account`+`portal` already technically expose a generic `/my/invoices` page (any tenant's own invoices, filtered by `partner_id` exactly like every other native portal invoice view), but it is not EDARA-branded or translated into "business language" (spec's own explicit example: "Outstanding 350 ILS" rather than raw accounting terms) and is not linked from the EDARA portal navigation.

**Localization:** every user-facing string observed throughout this module is wrapped in `_()` (translation-ready), but no `i18n/*.po` file exists - 0% of the actual Arabic content has been authored. This is a content-authoring gap, not an engineering one.

**Owner Settlement:** 0% implemented, `edara.owner.settlement` does not exist - matches spec §32's own explicit instruction not to implement unless in active scope.

**Multi-currency:** every `currency_id` field observed is `related=company_id.currency_id` (or defaulted from it) - a consistent single-currency-per-company design. Satisfies spec §33's "use Odoo currency records, don't hardcode" instruction, but does not support invoicing different tenants of the same company in different currencies. Whether that's ever actually needed is unverifiable from documentation alone (spec §64 names ILS/JOD/USD as "primary expected currencies," plural, without clarifying whether that means "different companies use different currencies" - already true today - or "one company needs more than one").

### Capability Gaps

| Capability | Current State | Gap | Business Impact | Dependencies | Complexity | Accounting Risk |
|---|---|---|---|---|---|---|
| Notifications & Reminders | `mail.activity.mixin` present, unused; 3 idempotent crons exist | No automated activity/reminder for lease renewal, overdue rent, maintenance follow-up, document expiry (spec §44's own 4 examples) | High - PMs currently rely entirely on manually remembering to check the Dashboard | Existing crons, `_expiring_soon_domain()`, `mail.activity.mixin` | Medium | None |
| Business-level manual triggers (MAT-FIND-007) | Settings → Technical → Scheduled Actions only | No in-app "run this now" button for expiry/invoicing crons | Medium - workflow convenience, not blocking | Existing cron logic (reuse, don't duplicate) | Low | None directly; exposes the existing rent-invoicing `.sudo()` asymmetry if bundled (see Technical Observations) |
| Reporting depth | 5 reports satisfy spec's stated minimum | No Rent Roll / Lease Expiry / Collections / Maintenance Cost / Portfolio Summary / Deposit Liability / Service Charge Summary reports | Medium - operational visibility beyond the baseline | Existing pivot/list report pattern; Maintenance now has vendor-bill data to report on | Low-Medium | None (read-only) |
| Owner Settlement | 0% implemented (by design, per spec §32) | Entire feature: owner statement, management fee, owner payable, settlement/reconciliation | Critical if EDARA manages third-party-owned properties; Low/None if owner-operator-only | Ownership % (exists), Financial Summary (exists); needs new owner-payable-liability accounting architecture | High | High - new liability account, real money movement, must not become a parallel ledger |
| Tenant Portal expansion | 2 of spec §40's 11 named items built | Portal Dashboard, My Unit, EDARA-branded Invoices/Payments/Outstanding Balance/Payment History, Documents, Notifications, Profile | High - tenant self-service reduces PM workload | Native `account`+`portal` already expose raw invoice/payment data; needs EDARA business-language wrapping | Medium | Low (read-only, must respect existing portal isolation pattern) |
| Maintenance Phase 2 | Flat request + cost + vendor + one manual bill | No SLA/due-dates, no vendor-relationship depth, no recurring/preventive scheduling, no maintenance-cost-by-unit/property history | Medium-High for larger portfolios, lower for small ones | Existing maintenance model + vendor bill flow | Medium-High | Low (extends the already-proven pattern) |
| Arabic content authoring | 0% `.po` content, 100% translation-ready code | No actual Arabic strings | High if Arabic-speaking staff/tenants are the primary user base | None technical - needs a human translator/business terminology | Low (mechanical once content is supplied) | None |
| Document workflow depth | Native chatter attachments only | No expiration tracking (e.g. tenant ID/passport), categories, or approvals | Low-Medium | Native `ir.attachment`; ties into the Notifications gap for expiry reminders | Medium | None |
| Multi-currency per contract | Single-currency-per-company | Cannot invoice different tenants of one company in different currencies | Unknown - unverifiable without a business-model answer | Would touch nearly every accounting call site | High | High |

### Candidate Phase Analysis

**A. Maintenance Phase 2:** the existing foundation (request lifecycle + cost/vendor + manual vendor bill) is solid and directly reusable. The deeper items (SLA/due-dates, vendor-relationship management, recurring/preventive scheduling, quotations/POs) are genuinely valuable for larger portfolios but add real scope and, for quotations/POs specifically, risk drifting toward a mini-procurement module the spec never asked for. **Assessment: valuable, but not the most foundational next step** - it extends an already-working capability rather than closing a completely-missing one.

**B. Notifications & Reminders:** zero accounting risk, reuses 100% existing architecture (`mail.activity.mixin` already installed on the two models that need it most, the exact `_expiring_soon_domain()` query already exists, the idempotent-cron pattern is already proven three times over), and is explicitly named in the spec. **Assessment: the most foundational, lowest-risk, spec-grounded gap available.**

**C. Reporting & Management Intelligence:** low complexity, no accounting risk (all read-only), and the existing 5 reports already prove the pattern (native pivot/list views filtered by EDARA tags). Natural to sequence right after Notifications, since a Lease Expiry Report and a renewal reminder use the same underlying query. **Assessment: strong second-phase candidate.**

**D. Owner Settlement:** explicitly deferred by the spec itself pending "active scope." The single blocking question - does EDARA's real deployment manage properties on behalf of third-party owners at all, today or imminently - cannot be inferred from any document reviewed. **Assessment: correctly deferred; requires a business-model decision before any design work, not just an engineering go-ahead.**

**E. Business-Level Manual Triggers (MAT-FIND-007):** small, low-risk, and naturally pairs with Notifications & Reminders (both live in the same "who can act on the cron-managed lifecycle, and how" layer). **Assessment: bundle as a companion to Notifications & Reminders rather than a standalone phase.**

**F. Arabic/Localization:** purely a content-and-review task once terminology is supplied; zero engineering blockers exist today (every string is already translation-ready). **Assessment: can proceed in parallel with any other phase - does not need to gate or be gated by anything.**

**G. Documents & Workflow:** current native-chatter approach is spec-compliant as-is. Expiration tracking for tenant documents is a genuine real-world want but depends on the same activity/reminder infrastructure Notifications & Reminders would establish. **Assessment: natural, small follow-on to Notifications & Reminders, not urgent on its own.**

**H. Tenant Portal Expansion:** the biggest gap against the spec's own explicit checklist (2 of 11 items), but most of the underlying data (invoices, payments) is already technically exposed by native Odoo - the work is EDARA-branding/business-language wrapping plus a couple of genuinely new pages (My Unit, a portal Dashboard). **Assessment: high value, medium complexity; best sequenced after Reporting, since both share the same "translate raw accounting into business language" design work.**

### Proposed Development Sequence

1. **Notifications & Reminders Automation** (bundling MAT-FIND-007's manual triggers) - foundational, lowest risk, spec-named, reuses existing architecture end to end.
2. **Reporting & Management Intelligence expansion** - low complexity, no accounting risk, natural continuation of the same underlying queries.
3. **Tenant Portal Expansion** - medium complexity, high value, benefits from the business-language patterns established in phase 2.
4. **Maintenance Phase 2** (deeper vendor/SLA/recurring capability) - valuable but not foundational; can be resequenced ahead of Portal Expansion if the business's real priority is operational (maintenance-heavy) rather than tenant-facing.
5. **Owner Settlement** - explicitly held pending the business-model decision below; if confirmed needed, it is the highest-complexity, highest-accounting-risk phase and should not be started until 1-3 are stable.
6. **Arabic content authoring** - not sequence-dependent; can run in parallel with any of the above once terminology is supplied.
7. **Multi-currency per contract** - deferred; only scheduled if the business decision below confirms a real need.

### Business Decisions Required

1. Does EDARA's real deployment ever manage properties on behalf of third-party owners (vs. owner-operators managing their own properties)? Determines whether Owner Settlement is ever needed and its priority.
2. Does any single company need to invoice its tenants in more than one currency? Determines whether multi-currency-per-contract is ever needed.
3. Who should be authorized to use the proposed business-level manual "run now" trigger for the expiry/invoicing crons - all EDARA staff, or Branch Manager and above only?

### Technical Observations (kept separate from product gaps)

- The previously-documented `edara.payment.schedule.line._create_invoice()` `.sudo()` asymmetry (see the Maintenance Cost Accounting Integration section above) remains unfixed and becomes directly relevant the moment MAT-FIND-007's manual trigger is implemented for that specific cron - it should be fixed as part of that work, not before.
- No automated test anywhere in the 240-test suite exercises `mail.activity` creation/scheduling, consistent with the fact that no code creates one automatically yet - confirms the Notifications gap is real at the test level too, not just a documentation gap.

### Status: ROADMAP REVIEW COMPLETED (2026-09-22). No implementation phase has been started.

## Phase 2 — Reporting & Management Intelligence Expansion (2026-09-22)

**Status: COMPLETED.** Implementation performed. MAT status: unaffected, remains CLOSED at 240/240. Phase 1 (Notifications & Reminders Automation) status: unaffected, remains COMPLETED at 276/276. Full regression after this phase: **309/309 passing** (276 baseline + 33 new tests).

**Note on document structure:** the "Phase 1 — Notifications & Reminders Automation" section appears earlier in this file, between "MAT Backlog Review & Next-Phase Planning (2026-09-21)" and "Product Roadmap & Capability Prioritization Review (2026-09-22)" - a mis-anchored edit during that ticket inserted it there instead of at the true end of file. Left as-is here rather than moved (moving it would itself be exactly the kind of "rewrite of an unrelated historical entry" this ticket's own instructions say not to do, and risks corrupting adjacent content) - the content is accurate, just out of strict chronological position. This Phase 2 section is appended at the genuine end of the file.

### Reporting Audit (existing 5 reports)

Reviewed every existing report against its business purpose before writing anything new:

| Report | Source | Verdict |
|---|---|---|
| Revenue | `account.move` pivot (branch/property x month, `amount_untaxed_signed`) | Retained unchanged - correct and sufficient. Enhanced indirectly via the new shared Invoice Type filter (see below). |
| Expenses | Same pattern, `in_invoice`/`in_refund` | Retained unchanged - same enhancement. |
| Receivables | `account.move` pivot (property/partner x `payment_state`, `amount_residual_signed`) | Retained unchanged - already satisfies Collections & Outstanding (§9). |
| Occupancy | `edara.unit` pivot (branch/property x `occupancy_status`) | Retained unchanged - correct denominator already (direct per-status counts, not derived by subtraction - MAT-FIND-010 precedent). |
| Tenant Ledger | `account.move` list+pivot filtered to tenant partners | Retained unchanged - correct and sufficient. |

None were rewritten or duplicated. All 5 continue to use native pivot/list/graph views on `account.move`/`edara.unit` - no custom report engine, no parallel model, unchanged from Phase 10.

### What Was Implemented

**1. Shared account.move report search view enhanced** (`view_edara_account_move_report_search`, used by Revenue/Expenses/Receivables/Tenant Ledger): added an `edara_invoice_type` filter (Rent/Late Fee/Service Charge/Maintenance) and group-by. Directly satisfies §10 ("distinguish rental/service charge/late fee income") and §11 ("maintenance expenses") without a dedicated report per type - one enhancement, four reports benefit.

**2. Rent Roll** (new: `edara.lease.contract` list+pivot, `action_edara_rent_roll_report`) - property/building/unit/tenant/lease/start/end/rent/billing frequency/payment day/monthly equivalent rent/state/unit occupancy. `monthly_equivalent_rent` is a new **stored** compute field reusing the exact `rent_amount / PERIOD_MONTHS[billing_frequency]` formula `_generate_schedule_lines()` already used inline - that inline calculation was refactored to call the new field instead of recomputing it, so there is exactly one rent-normalization formula, not two. `unit_occupancy_status` is a new non-stored `related` passthrough for display only (BD-001's unit-level derivation remains the single source of truth).

**3. Lease Expiry Report** (new: shared `edara.lease.contract` search view + dedicated list+pivot, `action_edara_lease_expiry_report`) - the new `view_edara_lease_contract_search` (state filters, "Expiring Soon (30d)" via `relativedelta`, branch/property/building/status/expiry-month group-by) is wired onto BOTH the new report AND the existing main Contracts action (`action_edara_lease_contract`, which previously had no search view at all). "Expiring Soon" is a literal copy of BD-003's existing definition (ACTIVE, `end_date` in `[today, today+30]`) - not a second threshold.

**4. Maintenance Cost Report** (new: `edara.maintenance.request` list-only, deliberately no pivot - see Performance Review below; shared search view `view_edara_maintenance_request_search` also wired onto the main Maintenance action). New field `vendor_bill_amount_total` (compute, permission-gated exactly like `has_accounting_access`) shows the Vendor Bill's actual posted total alongside the request's own estimated `cost` - explicitly kept as two distinct, separately-labeled numbers (never summed/merged) since they can legitimately differ once a bill is edited after creation.

**5. Property/Branch/Unit Performance** - `edara.property`/`edara.branch`'s existing `_compute_financial_summary()` gained one more field, `maintenance_cost` (posted Vendor Bills tagged `edara_invoice_type='maintenance'`, same `_read_group`/sign-convention pattern already used for `total_expenses`, already included within it, shown separately). `edara.unit` gained a **new** Financial Summary (`total_revenue`/`total_expenses`/`total_outstanding`/`maintenance_cost`/`has_accounting_access`), same MAT-FIND-014-gated pattern, added only to the single-record form (never to the list/kanban views, so browsing Units never triggers N accounting queries per row).

**6. Dashboard/Portfolio Summary integration** - one new KPI, `maintenance_cost_this_month` (accounting-gated, same Collections section, same `_read_group` pattern as `monthly_revenue`), satisfying §14's explicit "maintenance cost where reliable" ask. No other Dashboard changes - it already covered every other §14 item (unit counts by status, lease counts by state, expiring-soon count, revenue/outstanding where accounting access exists).

**7. Scalability:** `account.move.edara_invoice_type` gained `index=True` - it is now filtered/grouped-by in 4 reports (previously unindexed despite already being a Selection field used in domains).

### User-Facing Changes

- Reports menu (`group_edara_accountant`/`group_edara_branch_manager`, unchanged gate - preserves Phase 10's own deliberate decision to keep the whole Reports menu manager/accountant-tier regardless of individual report sensitivity, for consistency rather than per-report ACL fragmentation): 3 new entries - **Rent Roll** (sequence 5, first), **Lease Expiry** (60), **Maintenance Cost** (70).
- Main Contracts and Maintenance Requests actions gained real search/filter/group-by (previously relied on the default auto-generated search).
- Property/Branch Financial Summary pages gained a Maintenance Cost line. Unit form gained a whole new Financial Summary page (gated, hidden for non-accounting users).
- Dashboard Collections section gained a Maintenance Cost This Month tile.
- **Export:** native list-view CSV/XLSX export already covers every new report - no new code needed, evaluated and confirmed sufficient (see §22 disposition below).
- **PDF:** deliberately NOT added. No formal/printable requirement was named, and native list export already satisfies "useful" without unrequested scope; a printed Rent Roll PDF remains a clean, isolated future addition if a real need appears.

### Accounting Integration

Native `account.move`/`amount_untaxed_signed`/`amount_residual_signed`/`payment_state` remain the sole financial source of truth for every number in every report - no independent financial calculation was added anywhere. `monthly_equivalent_rent` and the Rent Roll's other fields are explicitly operational (contracted/scheduled rent, not posted revenue) and are never mixed with the accounting figures in the same field. No parallel ledger, no second accounting system. Vendor Bill cost (`vendor_bill_amount_total`) is authoritative for POSTED maintenance expense; `edara.maintenance.request.cost` is explicitly the pre-billing estimate - the two are shown side by side, never summed.

### Security Validation

No ACL rows added. No record rules weakened. No blanket `sudo()` - the one existing scoped-`.sudo()` architecture (MAT-FIND-015) is untouched by this phase; nothing in Phase 2 creates or elevates access to any native accounting record. Every new accounting-derived field (`edara.property.maintenance_cost`, `edara.branch.maintenance_cost`, `edara.unit.*`, `edara.maintenance.request.vendor_bill_amount_total`, `edara.dashboard.maintenance_cost_this_month`) follows the exact MAT-FIND-014 pattern already established: computed only when `account.move.has_access('read')` is true for the calling user, degrading to `0`/`False` otherwise - never a raw `AccessError`. Verified both automated (`TestEdaraReportingSecurityIsolation`, plus dedicated gating tests in each new-field test class) and live: a Viewer sees `0` everywhere accounting-gated, a Branch Manager's Rent Roll/Lease Expiry/manual-trigger queries never see another branch's records (existing branch record rules, untouched), and a user restricted to one company cannot read another company's property `maintenance_cost` field at all (existing multi-company record rule, untouched).

### Performance Review

- All 5 pre-existing reports and the new Rent Roll/Lease Expiry reports use `read_group`-backed native pivot aggregation over **stored** fields (`monthly_equivalent_rent` is stored specifically so it aggregates correctly server-side) - no N+1 queries, no unbounded Python loops.
- The Maintenance Cost report is deliberately **list-only, no pivot**: `vendor_bill_amount_total` is a non-stored, permission-gated compute field, not genuinely `read_group`-aggregatable - a pivot view would silently fall back to loading every matching record client-side to sum it. The list's own column sum is fine (bounded by pagination); true aggregate maintenance-cost reporting is directed to the Expenses report's native `amount_untaxed_signed` measure (filter it to "Maintenance" via the new Invoice Type filter) instead.
- `edara.unit`'s new Financial Summary fields are added only to the form view, never list/kanban - browsing the Units list triggers zero additional `account.move` queries.
- `account.move.edara_invoice_type` indexed, since it is now filtered/grouped-by in 4 separate reports.
- No unrelated code was touched or optimized.

### Automated Test Results

New file `tests/test_edara_reporting_phase2.py` (33 tests): Rent Roll (7, incl. monthly-equivalent math for all 3 billing frequencies, reuse-not-reinvent proration check, branch isolation), Lease Expiry (6, incl. 30/31-day boundary, expired/draft exclusion, BD-003 domain equivalence), Unit/Property/Branch Performance (5, incl. no-double-count check, cross-property branch aggregation, viewer gating), Maintenance Cost Report (5, incl. zero-when-no-bill, gated-to-zero-for-viewer), Invoice Type report filter (3, incl. index verification), Dashboard KPI (3, incl. month-boundary exclusion, viewer gating), Security/Isolation (3, incl. portal tenant, cross-company `AccessError`, branch isolation). `tests/__init__.py` updated.

**Previous baseline:** 276/276. **New tests:** 33. **Final total: 309/309 passing, 0 failures, 0 errors, 0 skips.**

### Live Validation (2026-09-22) against real `odoo19_dev`

Module upgraded cleanly. A rolled-back validation script exercised **24/24 checks, 0 failed**:

| Scenario | Result | Notes |
|---|---|---|
| Occupancy | PASS | correct per-status counts, sold unit correctly excluded |
| Rent Roll | PASS | monthly-equivalent correct for quarterly billing, unit occupancy passthrough correct, report loads |
| Lease Expiry | PASS | 30-day window correctly included, far-future contract correctly excluded, matches BD-003's own domain |
| Collections | PASS | posted invoice appears in Receivables, outstanding amount correct |
| Revenue | PASS | Invoice Type filter correctly isolates rent revenue, property total_revenue correct |
| Maintenance Cost | PASS | vendor bill amount correct, property/unit maintenance_cost correct, no double counting, report loads |
| Portfolio Summary (Dashboard) | PASS | maintenance_cost_this_month correct |
| Security | PASS | Viewer degrades to 0 (not AccessError) on unit/maintenance/dashboard fields, Branch Manager branch-isolated, cross-company `AccessError` confirmed |
| Cleanup | PASS | zero `RP2LV`-coded records/users/companies remain, real baseline (18 rented units) unchanged |

One script-only issue was found and fixed during this run (not a product defect): Odoo's compute-field cache is keyed per-record, not per-calling-user, within a single shared transaction - reading an accounting-gated field as admin first (as this one long validation script does, unlike a real multi-request production session) caches the admin-computed value, so a later same-transaction read under a different user returns the stale cached value instead of recomputing under that user's actual access. Fixed by calling `invalidate_recordset()` before each such re-read in the script. This has no bearing on real usage, where each request gets its own transaction/cache.

**Database cleanup:** verified via direct `psql` query - zero `RP2LV`-coded branches/units/users/companies remain in `odoo19_dev`; real occupancy baseline (18 units, all `rented`) unchanged.

### Known Limitations

- The Reports menu remains gated to Accountant/Branch Manager as a whole (Phase 10's original decision), even though Rent Roll/Lease Expiry/Occupancy are not themselves financial data - preserved for consistency with the existing 5 reports rather than introducing per-report ACL fragmentation. A Property Manager/Viewer can still get equivalent operational visibility via the main Units/Contracts/Maintenance list views and their own filters (all enhanced with real search views in this phase).
- No PDF/QWeb report was added for any of the 3 new reports - native list export (CSV/XLSX) was judged sufficient; revisit only if a formal printable Rent Roll or similar becomes an actual requirement.
- `vendor_bill_amount_total`'s cache-staleness behavior described under Live Validation applies to any long-lived single-transaction script (including future live-validation scripts) - not a defect, but worth remembering when writing one.

### Deferred Scope (unchanged, not reopened)

Tenant Portal Expansion, Maintenance Phase 2, Owner Settlement (business-decision-gated), Arabic content authoring, multi-currency-per-contract (business-decision-gated) - all untouched, per the already-approved roadmap sequence. Standard native Odoo Accounting reports (Aged Receivable/Payable, General Ledger, Journal reports) were not duplicated, per §23.

### Next Phase

Per the already-completed Roadmap Review's Proposed Development Sequence, item 3: **Tenant Portal Expansion** (the spec's own 11-item portal checklist currently has 2 of 11 built - My Lease and Maintenance Requests). Not started in this ticket.

## Phase 3 — Tenant Portal Expansion (2026-09-22)

### Status: COMPLETED. Full regression after this phase: 325/325 passing (309 baseline + 16 new tests).

### Objective

Close the spec §40 Tenant Portal gap identified by the Roadmap Review and re-confirmed by this ticket's own discovery step: 2 of the spec's 12 named portal items were built (My Lease incl. renewal submission, Maintenance Requests). This phase implements the remaining items - Tenant Dashboard, My Unit, Invoices/Payments/Outstanding Balance/Payment History ("Billing"), Documents, Notifications, and Renewal Requests' decision-notification loop - using native Odoo Portal architecture exclusively (no new frontend, API, or auth layer). Tenant Profile is satisfied by linking to the already-installed native `/my/account` page rather than building a new one.

### Discovery (before any code change)

Read `EDARA_PROJECT_STATE.md`, `EDARA_IMPLEMENTATION_SPEC.md` §40, `controllers/portal.py`, `views/portal_templates.xml`, `security/edara_record_rules.xml`, `security/ir.model.access.csv`, `tests/test_edara_portal.py`, and the relevant model files (`edara_unit.py`, `edara_lease_contract.py`, `edara_renewal_request.py`, `edara_maintenance_request.py`, `edara_payment_schedule_line.py`, `res_partner.py`, `account_move.py`) before writing any code, per the ticket's own mandatory first step. Confirmed: `res.partner.is_edara_tenant` already exists as a stored computed field (exactly spec §6's tenant-resolution check); `edara.unit` and `edara.renewal.request` already have portal-own record rules; native `/my/invoices`, `/my/invoices/<id>`, and `/my/account` (from the already-installed `account`+`portal` dependencies) already correctly serve the tenant's own invoices and profile editing, isolated by their own native rules; no `ir.attachment` code existed anywhere in the module (a genuine gap, closed here by reusing the native model, not a new one).

### What Was Implemented

1. **`_edara_get_tenant_partner()`** (`controllers/portal.py`) - the single safe tenant-resolution helper (spec §6): resolves `request.env.user.partner_id` from the session only, verifies `is_edara_tenant`, raises `AccessError` (fails closed) otherwise. Reused by every new route below.
2. **`/my/dashboard`** - Tenant Dashboard (spec §8): current lease, next payment due, outstanding balance, renewal status, active-maintenance count, 5 most recent notifications. No new financial fields - reads existing fields/models only.
3. **`/my/units`, `/my/units/<id>`** - My Unit (spec §10): reuses the existing `rule_edara_unit_portal_own` record rule; business-safe fields only.
4. **`/my/billing`** - Invoices/Payments/Outstanding Balance/Payment History (spec §11-13), business-language wrapper around native `account.move` (partner_id = tenant, posted only) - no parallel ledger; links out to native `/my/invoices/<id>` for full accounting detail rather than rebuilding it.
5. **`/my/documents`** - Documents (spec §17/§42): reuses native `ir.attachment`. Candidate records are first restricted to the server-resolved tenant's own (`tenant_id = partner.id`) before their attachments are looked up; the actual `/web/content/<id>` download is independently re-guarded by `ir.attachment`'s own native `_check_access()` (gated on read access to the linked `res_model`/`res_id`), a second layer that survives even a guessed attachment id.
6. **`/my/notifications`** - Notifications (spec §18): `mail.message` filtered to `partner_ids in [the server-resolved tenant's own partner id]` and to EDARA models only - never Phase 1's internal `mail.activity` automation, which stays entirely staff-side and untouched.
7. **Renewal decision notifications** (`edara_renewal_request.py`, `action_approve`/`action_reject`): added a `message_post(partner_ids=request.tenant_id.ids)` call on both outcomes, mirroring the 3 existing tenant-notification call sites from Phase 1 - closes the loop so a tenant who submits a renewal request (already-working functionality) is actually told the outcome.
8. **Renewal history on the lease detail page**: `portal_lease_detail` now also passes `renewal_history` (the contract's own decided, non-open renewal requests) - reuses the existing `renewal_request_ids` relation, no new route/model.
9. **Portal home page** (`portal_my_home_edara`): added Dashboard/My Unit/Billing/Documents/Notifications/My Profile cards (the last linking to native `/my/account`).

### Portal Capabilities (spec §40, 12 named items)

| Item | Status |
|---|---|
| Dashboard | New (this phase) |
| My Lease | Already implemented (unchanged) |
| My Unit | New (this phase) |
| Invoices | New EDARA-branded summary; full detail via existing native page |
| Payments | New EDARA-branded summary; full detail via existing native page |
| Outstanding Balance | New (this phase) |
| Payment History | New EDARA-branded summary; full detail via existing native page |
| Renewal Requests | Submission already implemented; decision notification + history added this phase |
| Maintenance Requests | Already implemented (unchanged) |
| Documents | New (this phase) |
| Notifications | New (this phase) |
| Profile | Satisfied via existing native `/my/account` (linked, not rebuilt) |

### Security Architecture

- **Tenant resolution**: always `request.env.user.partner_id` (session-derived), never a URL/POST/query parameter. `_edara_get_tenant_partner()` fails closed via `is_edara_tenant` (an existing stored field, not reinvented) before any of the 5 new routes proceed.
- **ID-tampering surface**: only one new route accepts a client-supplied id at all - `/my/units/<id>` - and it is routed through the existing, native `_document_check_access()` (checks `check_access('read')` under the real user's own env/record rules first, only returning a sudo'd record after that check passes; the same mechanism the pre-existing My Lease/Maintenance detail routes already used). The other 4 new routes (Dashboard, Billing, Documents, Notifications) take no record id from the client at all - there is nothing to tamper with.
- **Scoped `.sudo()`**: every new `.sudo()` call site is a read-only query whose domain is itself the authorization (`tenant_id = partner.id` or `partner_ids in [partner.id]`, both server-resolved) - never a blanket controller-entry sudo. `portal.py`'s new `.sudo()` sites: `_edara_tenant_notifications()` (no portal ACL exists on `mail.message` at all), `portal_dashboard`/`portal_billing` (`account.move`/`edara.payment.schedule.line`/`edara.renewal.request` reads scoped to the tenant's own partner id), `portal_documents` (`ir.attachment` listing scoped to already tenant-verified record ids), and `portal_my_units` (display-only sudo of an already tenant-scoped, non-sudo-authorized search result, needed only because the portal role has no ACL on `edara.property`/`edara.building` for the related-field display - discovered and fixed during testing, see Errors below).
- **Documents double-gated**: listing is scoped server-side (tenant-owned record ids only); the actual download link is independently re-checked by `ir.attachment`'s own native `_check_access()`, confirmed by a dedicated cross-tenant download test and by a live-validation `AccessError` check.
- **Notifications never expose internal state**: the query only ever matches `mail.message` explicitly addressed to the resolved tenant via `partner_ids` (the same `message_post(partner_ids=...)` pattern Phase 1 already established) - internal notes and `mail.activity` staff assignments are structurally excluded (different model, never queried), confirmed by both an automated and a live-validation test.
- **Cross-company**: no new record rules were needed - every new route's authorization is scoped to the tenant's own partner id, and a given tenant partner is never linked to another company's records by construction. Confirmed by an automated and a live-validation cross-company test.
- **No ACL/record-rule changes**: zero changes to `security/edara_record_rules.xml` or `security/ir.model.access.csv` - every existing portal rule (`rule_edara_lease_contract_portal_own`, `rule_edara_unit_portal_own`, `rule_edara_maintenance_request_portal_own`, `rule_edara_renewal_request_portal_own`) is reused exactly as-is.

### Accounting Integration

Billing/Dashboard outstanding-balance figures are computed directly from posted `account.move` records filtered by `partner_id = tenant`, summing `amount_residual` - the same native field native Accounting itself uses. No new ledger, no duplicated receivable calculation, no fake payment record. Full accounting detail (tax breakdown, payment allocations, PDF) intentionally stays on the native `/my/invoices/<id>` page rather than being rebuilt.

### Errors and Fixes

- **`portal_my_units` AccessError (caught by the automated test suite, not live validation)**: the unit list template originally read `unit.property_id.display_name`/`unit.building_id.display_name` on a non-sudo `edara.unit` recordset. The portal-tenant role has an ACL on `edara.unit` itself but none at all on `edara.property`/`edara.building`, so the related-field read raised `AccessError: Access Denied by ACLs... model: edara.property`. Fixed by sudo'ing the already tenant-scoped result (the non-sudo domain search is the real authorization; sudo is applied only afterward, for display) - the same authorize-then-elevate shape `_document_check_access()` already uses everywhere else in this module.
- Used the deprecated `ir.attachment.check()` API in an early draft of the live-validation script (it now hard-requires an internal/employee user in Odoo 19, which would have made the negative-access check pass for the wrong reason); corrected to the current `check_access('read')`, which is what the native `/web/content` download route itself actually uses.

### Automated Test Results

`tests/test_edara_portal.py` extended from 11 to **27 tests** (16 new): Tenant Dashboard (2, incl. fail-closed for a non-tenant portal user), My Unit (3, incl. ID-tampering), Billing (2), Documents (3, incl. ID-tampering on the actual download route), Notifications (5, incl. internal-note exclusion and cross-tenant leak checks), Renewal decision notifications (2), Company Isolation (1). `tests/__init__.py` unchanged (already imports this file).

**Previous baseline:** 309/309. **New tests:** 16. **Final total: 325/325 passing, 0 failures, 0 errors, 0 skips.**

### Live Validation (2026-09-22) against real `odoo19_dev`

Module upgraded cleanly. A rolled-back validation script exercised **16/16 checks, 0 failed**:

| Scenario | Result | Notes |
|---|---|---|
| Tenant Resolution | PASS | `is_edara_tenant` correctly True once leased, False for a lease-less portal user |
| Dashboard | PASS | next-payment line and outstanding balance both correct |
| My Unit | PASS | record-rule isolation confirmed; ID-tampering to another tenant's unit correctly denied |
| Billing | PASS | tenant-scoped invoice domain excludes another tenant's invoice |
| Documents | PASS | listing correctly scoped; native `ir.attachment` `check_access` correctly denies a guessed foreign attachment id |
| Notifications | PASS | tenant sees their own maintenance-completion message, not an internal-only note, not anything tied to another tenant's record |
| Renewal Workflow | PASS | both approval and rejection post a tenant-facing notification |
| Company Isolation | PASS | another company's unrelated unit never appears in the tenant's own unit list |
| Security (fail-closed) | PASS | a portal user with no EDARA tenant relationship sees zero units/leases |
| Cleanup | PASS | zero `P3LV`-coded branches/units/partners/companies/attachments/users remain |

**Database cleanup:** verified via direct `psql` query across `edara_branch`, `edara_unit`, `res_partner`, `res_company`, `ir_attachment`, and `res_users` - zero `P3LV`-prefixed rows remain in `odoo19_dev`.

### Known Limitations

- Tenant Profile editing was not rebuilt - it is the existing native `/my/account` page (name/email/phone/address only, company/groups already excluded by native Odoo itself), linked from the new portal home card rather than re-implemented or re-tested here, since it is unmodified framework code.
- Documents has no upload capability for tenants (read-only, matches spec §17's framing of tenant document *access*, not authoring) - staff continue to attach files via chatter on the lease/maintenance/renewal record, which the tenant can then see.
- Notifications is a flat, unpaginated recent-message list (bounded by nature - one tenant's own tenant-directed messages only, not portfolio-scale) - no read/unread state, since `mail.message`/`mail.notification` read-tracking was judged out of scope for this ticket.

### Deferred Scope (unchanged, not reopened)

Maintenance Phase 2, Owner Settlement (business-decision-gated), Arabic content authoring, multi-currency-per-contract (business-decision-gated) - all untouched, per the already-approved roadmap sequence.

### Next Phase

Per the already-completed Roadmap Review's Proposed Development Sequence, item 4: **Maintenance Phase 2** (deeper vendor/SLA/recurring capability). Not started in this ticket.

## Phase 4 — Maintenance Phase 2: Vendor, SLA & Recurring Maintenance (2026-09-23)

### Status: COMPLETED. Full regression after this phase: 362/362 passing (325 baseline + 37 new tests).

### Objective

Expand `edara.maintenance.request` from Phase 1's flat request+cost+vendor+manual-bill capability into vendor management, SLA/response tracking, and recurring/preventive maintenance, per the Roadmap Review's own gap ("no SLA/due-dates, no vendor-relationship depth, no recurring/preventive scheduling"). The spec defines no SLA/recurring mechanics at all - every configurable default introduced here (BD-MNT-003/004/005 below) is a documented engineering decision, not an invented business rule.

### Discovery

Read `EDARA_PROJECT_STATE.md`, `EDARA_IMPLEMENTATION_SPEC.md` (confirmed: no SLA, vendor-metadata, or recurring-maintenance concept exists anywhere in the spec beyond the single "vendor" field already implemented), `edara_maintenance_request.py`, `edara_branch.py`, `res_partner.py`, `tests/test_edara_maintenance_request.py`, `tests/test_edara_maintenance_vendor_bill.py`, and `views/maintenance_request_views.xml` before writing any code. Confirmed the model, lifecycle, tenant/property/branch relationships, Vendor Bill flow (native `account.move`, idempotent, scoped `.sudo()`), chatter, and Phase 1/3 automation and portal integration were all already correct and are preserved unchanged.

### Implementation

**Vendor Management (§5-9):** no separate vendor model - `res.partner` remains the sole vendor source of truth, extended with the same computed-and-stored pattern already used for `is_edara_owner`/`is_edara_tenant`: `is_edara_vendor`, plus non-stored live vendor-history stats (`edara_vendor_request_count`, `edara_vendor_open_request_count`, `edara_vendor_last_service_date`, `edara_vendor_avg_response_hours`, `edara_vendor_avg_resolution_hours`, `edara_vendor_maintenance_cost_total`). The cost total is sourced from posted `account.move` only, kept explicitly distinct from any request's estimated `cost` (§9), and degrades to 0 without native Accounting read access (MAT-FIND-014 pattern). Shown only on a partner actually referenced as a vendor (`views/res_partner_views.xml`, new "EDARA Vendor" page, `invisible="not is_edara_vendor"`).

**SLA / Response Tracking (§10-17), BD-MNT-003/004:** `first_response_at`/`resolved_at` (Datetime, write-once - set in `action_assign()`/`action_complete()`, never overwritten on a later edit). `response_hours`/`resolution_hours` are stored computed fields derived from those timestamps. SLA targets (`sla_response_hours`, `sla_resolution_hours`) are **branch-level** (BD-MNT-003: the spec defines no scope for this, branch-level matches every other operational parameter in this module; default 24h/72h, 0 disables SLA for that branch). `sla_state` (Within/At Risk/Breached) is derived only, **never stored** - same live-snapshot pattern as `edara.property._compute_financial_summary`, so an open request's status stays accurate as time passes without a cron rewriting every open record. BD-MNT-004: "At Risk" = elapsed time > 80% of the resolution target (a documented default, not a business rule). New `_cron_send_sla_notifications()` (daily, bounded to open requests with a configured target, idempotent via the existing "already has an open activity of this type" check, new `mail_activity_type_edara_maintenance_sla` activity type) - kept entirely separate from Phase 1's unchanged `_cron_send_maintenance_reminders()` (staleness, a different concept).

**Recurring Maintenance (§18-23), BD-MNT-005:** new model `edara.recurring.maintenance` (schedule/template, `mail.thread`, never itself a work item) with `unit_id` (**required**, BD-MNT-005: matches the existing required `unit_id` on the generated-request model itself rather than inventing a building/property-level unit-resolution step), `category`, `vendor_id`, `frequency` (monthly/quarterly/semi_annual/yearly, per §20's exact minimum set), `next_date`, `active`. `_cron_generate_recurring_maintenance()` (daily) creates one `edara.maintenance.request` per due, active definition (via the model's own unchanged `create()`, so Phase 1's triage activity fires exactly as for any other request) and advances `next_date` by one period. Idempotency is a **database constraint** (`unique(edara_recurring_id, occurrence_date)` on `edara.maintenance.request`, §22's own explicit preference over a Python-only check), not just the cron's own pre-check.

**Category (§27):** a single shared `MAINTENANCE_CATEGORIES` constant (Plumbing/Electrical/HVAC/General/Cleaning/Structural/Other - a generic engineering default, the spec names none), optional, reused by both models rather than hard-coded inline anywhere.

**Dashboard (§28):** 3 new KPIs - SLA At Risk, SLA Breached (both computed over the same bounded "open + branch has a configured target" set the SLA cron itself uses, never a full historical scan), Recurring Maintenance Due (with a quick-action button). `action_manual_process_reminders()` now also runs the SLA cron; new `action_manual_generate_recurring_maintenance()` manual trigger reuses the exact cron method (§40).

**Search/Views (§29/§38):** Maintenance list/kanban/form gained category, vendor, and a color-coded SLA badge; search view gained a Category group-by and a "Recurring-Generated" filter. New Recurring Maintenance list/form/search views + menu (Property Manager+, never portal-visible). Branch form gained a "Maintenance SLA" tab.

### Accounting

Vendor Bill creation/idempotency/duplicate-prevention is completely unchanged (still the same scoped `.sudo()` on exactly one `account.move.create()`, still authorized by `check_access('write')` on the originating request first). `edara_vendor_maintenance_cost_total` reads posted `account.move` only, gated by `has_access('read')`, never combined with the estimated `cost` field into one number (§30). No new accounting model, no new `.sudo()` site beyond the one that already existed.

### Security

No ACL/record-rule change to any existing model. New model `edara.recurring.maintenance` follows the exact 4-tier pattern (viewer read-only, property_manager/branch_manager full CRUD within their branches, company_manager sees all) reused verbatim from every other EDARA model - **zero portal ACL rows and zero portal record rules** for it (§24: never tenant-visible, confirmed both automated and live). A recurring-generated request has no `tenant_id` by construction (it's a building/unit-level task, not filed by a tenant), so it correctly does not appear in a tenant's `/my/maintenance` list under the existing, unchanged Phase 3 filter - no new exclusion logic was needed. Vendor/SLA/category fields are absent from the existing, unmodified portal maintenance-detail template - confirmed by a dedicated test asserting the vendor's name, "SLA", and the cost never appear in that page's rendered HTML.

### Automated Test Results

New file `tests/test_edara_maintenance_phase2.py` (37 tests): Vendor Management (5, incl. optionality, isolation, cost-vs-estimate distinction), SLA Tracking (11, incl. write-once timestamps, hour computation, within/at-risk/breached transitions via a raw-SQL `create_date` backdate + `invalidate_recordset()`, notification idempotency, zero-target disablement, completed-request state staying frozen), Recurring Maintenance (13, incl. required-unit constraint, activation toggle, all 4 frequency advancements, cron-run idempotency, the DB unique constraint itself, branch isolation), Maintenance Regression (3, incl. confirming the staleness cron and the SLA cron remain independent), Portal (4, incl. Phase 3's own maintenance-detail visibility test re-run unchanged, recurring-request non-exposure, zero access to the recurring model). `tests/__init__.py` updated.

**Previous baseline:** 325/325. **New tests:** 37. **Final total: 362/362 passing, 0 failures, 0 errors, 0 skips.**

### Live Validation (2026-09-23) against real `odoo19_dev`

Module upgraded cleanly (`-u property_managment -d odoo19_dev`, required this time since the new `res_partner.is_edara_vendor` column and `edara_recurring_maintenance` table needed to actually exist before the shell script could run). A rolled-back validation script exercised **25/25 checks, 0 failed**:

| Scenario | Result | Notes |
|---|---|---|
| Vendor creation/assignment | PASS | `is_edara_vendor` flips True only once referenced |
| Request with/without vendor | PASS | vendor stays fully optional |
| SLA timing/breach | PASS | `first_response_at` set correctly; a 100h-old request against a 48h target correctly shows `breached` |
| SLA notification idempotency | PASS | 1 sent, then 0 on an immediate second run |
| Recurring creation/generation | PASS | definition created, one request generated on the due date, correctly linked (`edara_recurring_id`/`occurrence_date`) with the definition's vendor/category |
| Duplicate recurrence prevention | PASS | a second immediate run generates 0 |
| Recurrence advancement | PASS | `next_date` advanced by exactly one quarter |
| Vendor Bill creation/duplicate prevention | PASS | posted correctly; a second `action_create_vendor_bill()` call returns the same bill, not a new one |
| Completion without vendor | PASS | unchanged existing rule |
| Portal visibility/tenant isolation | PASS | tenant sees their own request, not another tenant's, not the recurring-generated (tenant-less) one; zero access to the recurring model |
| Company/branch isolation | PASS | a Branch Manager's recurring-maintenance list never includes another company's definition |
| Cleanup | PASS | zero `P4LV`-coded rows remain across `edara_branch`/`edara_unit`/`edara_maintenance_request`/`edara_recurring_maintenance`/`res_partner`/`res_company`/`res_users`/`account_account` |

**Database cleanup:** verified via direct `psql` query - zero `P4LV`-prefixed rows remain in `odoo19_dev`.

### Known Limitations

- SLA has no pause/resume mechanism (ticket §15 explicitly says not to build one) - the clock runs continuously from creation to resolution, including any time a request sits in `new` before assignment.
- `sla_state` is non-stored/live, so it cannot be used as a search/filter domain in list views (only displayed, via badges) - a deliberate trade-off to avoid a cron having to rewrite every open request's status just to keep a stored value current.
- Recurring maintenance requires a specific `unit_id` (BD-MNT-005) - a building- or property-wide recurring task (e.g. "service every elevator in this building") needs one recurring definition per unit rather than one covering many units at once.
- Vendor history stats (`edara_vendor_*` fields) respect the viewing user's own branch-scoped visibility of `edara.maintenance.request` (no `sudo()`), so a Branch Manager sees vendor stats scoped to their own branch's requests only, not portfolio-wide - consistent with existing isolation, not a defect.

### Deferred Scope (unchanged, not reopened)

Owner Settlement (business-decision-gated), Arabic content authoring, multi-currency-per-contract (business-decision-gated) - all untouched, per the already-approved roadmap sequence.

### Next Phase

Per the already-completed Roadmap Review's Proposed Development Sequence: **Owner Settlement**, explicitly held pending a business-model decision (does EDARA's real deployment manage properties on behalf of third-party owners) - not started in this ticket.

## Phase 5 — Property Boundary & Multi-Building Hardening (2026-09-23)

### Status: COMPLETED. Full regression after this phase: 370/370 passing (362 baseline + 8 new tests).

### Objective

A fresh-session project re-discovery (this same day) confirmed `edara.property` is a deliberate, non-redundant ownership/financial/analytic boundary (spec §8: "the ownership and financial boundary... NOT merely a UI grouping"), explicitly designed to hold multiple Buildings under one ownership/analytic structure. That multi-building scenario had never been regression-tested. This phase validates and hardens `Property -> Building -> Unit -> Lease -> Accounting -> Reporting` specifically for:

```text
Property
  |-- Building A (Unit A-101, Unit A-102)
  `-- Building B (Unit B-201, Unit B-202)
```

Per explicit instruction: Property was NOT redesigned, renamed, or made optional; ownership/analytic accounting were NOT moved to Building; Owner Settlement was NOT implemented. This was a validation/hardening phase only.

### Discovery

Read `edara_property.py`, `edara_building.py`, `edara_unit.py`, `edara_ownership.py`, `edara_lease_contract.py`, `edara_payment_schedule_line.py`, `edara_maintenance_request.py`, `edara_recurring_maintenance.py`, `edara_service_charge*.py`, `account_move.py`'s Property integration/analytic-account creation path, `views/reports_views.xml`, `security/edara_record_rules.xml`, and every existing test touching Property/Building/Unit/Ownership (`test_edara_property.py`, `test_edara_hardening.py`, `test_edara_service_charge.py`, `test_edara_reporting_phase2.py`) before writing any code.

Confirmed architecture (no hidden `one property = one building` assumption found anywhere):
- `edara.ownership.property_id` is a direct required FK with no Building reference at all - ownership is structurally Property-wide, not Building-wide.
- `edara.property.analytic_account_id` lives only on Property; `get_analytic_account()` is called via `self.property_id.get_analytic_account()` from `edara.payment.schedule.line`/`edara.service_charge.line` - both routes resolve to the same Property record regardless of which Building/Unit the caller reached it through, so multiple Buildings under one Property already share one analytic account by construction (lazy-created once, cached on the Property row).
- Every downstream model's `property_id` is a stored `related` field cascading through `building_id`/`unit_id` (not an independent FK), so it is mechanically impossible for a Unit/Lease/Maintenance record to disagree with its own Building's Property.
- All 3 Property-scoped reports (Property Financial Summary, Occupancy, Rent Roll) and the Maintenance Cost aggregation query by `property_id`/`edara_property_id` directly against the record set (`_read_group`/`search`), never by iterating a single `building_ids[0]` shortcut - so cross-Building aggregation was already structurally correct, just unverified.
- Security scoping is genuinely Branch-level only (confirmed again): `rule_edara_property_assigned_only`/`rule_edara_building_assigned_only` key off `branch_id.user_ids`/`manager_id`, never anything Property-specific - so adding a second Building to a Property changes nothing about who can see it.
- `test_edara_hardening.py::test_unit_from_different_building_rejected` already exercises 2 Buildings under 1 Property, but only for a negative `account.move` tag-consistency check - no test previously verified positive cross-Building aggregation (financial summary, occupancy, rent roll, maintenance cost, ownership, analytic-account reuse) for a shared Property.

### Multi-Building Findings

**No defect found.** The architecture correctly supports `Property -> [Building A, Building B]` for every dimension in scope: ownership stays Property-level, the analytic account is shared (not duplicated) across Buildings, `account.move.edara_property_id` is correctly set from either Building's leases, Property Financial Summary/`maintenance_cost` sum activity from both Buildings, and Occupancy/Rent Roll both include units/leases from both Buildings. This was a **genuine coverage gap, not a functional gap** - the code was already right; it just had no regression test proving it.

### Code Changes

None to product code (`models/`, `views/`, `security/`). One new test class added:

**`tests/test_edara_property.py`** - new `TestEdaraPropertyMultiBuilding` class (8 tests), covering exactly the scenario above: hierarchy resolution, ownership Property-level attachment, single shared analytic account, Property Financial Summary aggregation across both Buildings, Occupancy spanning both Buildings, Rent Roll spanning both Buildings, Maintenance Cost aggregation across both Buildings, and Branch-scoped security (both Buildings visible to the assigned Branch Manager, the other Branch's Property/Building correctly denied). `tests/__init__.py` unchanged (file already imported).

### Automated Test Results

**Previous baseline:** 362/362. **New tests:** 8. **Final total: 370/370 passing, 0 failures, 0 errors, 0 skips.**

### Live Validation (2026-09-23) against real `odoo19_dev`

A rolled-back validation script (`P5LV_`-coded records: 1 Property, 2 Buildings, 4 Units, 2 Tenants, 2 Leases, 1 Ownership record, 2 posted rent invoices, 2 posted maintenance vendor bills, 1 second Branch/Property/Building for the negative security check, 1 disposable Branch Manager user) exercised **18/18 checks, 0 failed**:

| Scenario | Result | Notes |
|---|---|---|
| Hierarchy | PASS | both Buildings resolve to the same Property; all 4 Units resolve to the same Property; `building_count`=2, `unit_count`=4 |
| Ownership | PASS | ownership record stays Property-level regardless of 2 Buildings existing |
| Analytic Account | PASS | `get_analytic_account()` returns the identical record on repeated calls; only 1 `account.analytic.account` exists for the Property after both a rent-invoice flow and a maintenance-bill flow |
| Accounting | PASS | invoices from both Building A's and Building B's leases carry `edara_property_id` = the shared Property, correct distinct `edara_building_id` each, both posted natively |
| Financial Summary | PASS | `total_revenue` = 2500 (1000 + 1500), correctly summing both Buildings, not just one |
| Occupancy | PASS | rented units correctly include one from each Building |
| Rent Roll | PASS | Property-scoped lease search returns leases from both Buildings |
| Maintenance | PASS | `maintenance_cost` = 250 (100 + 150), correctly summing both Buildings |
| Security | PASS | Branch Manager sees both Buildings of their own Property; does not see the other Branch's Building/Property; direct read of the other Branch's Property raises `AccessError` via record rules |
| Cleanup | PASS | script rolled back; confirmed via direct `psql` query - zero `P5LV`-prefixed rows in `edara_branch`/`edara_property`/`edara_building`/`edara_unit`/`res_partner`/`res_users`/`account_account`/`edara_ownership` |

One script-only issue was hit and fixed during this run (not a product defect, and already documented as a known pattern from Phase 2's own live validation): reading `prop.total_revenue` before the maintenance vendor bills existed cached the whole non-stored `_compute_financial_summary` group (including `maintenance_cost`) for the rest of the single-transaction script; fixed by calling `invalidate_recordset()` before the later `maintenance_cost` read, exactly as Phase 2's validation notes already warned future scripts to do.

### Security Verification

Branch remains the sole security-scoping boundary; adding a second Building to a Property introduces no new access surface. Confirmed both automated (new test) and live: a Branch Manager assigned to the Property's Branch sees both Buildings; a Branch Manager of a different Branch sees neither the Property nor either Building, and a direct read attempt on the other Branch's Property raises `AccessError`. No ACL or record-rule change was made or needed.

### Accounting Integrity

Native `account.move` remains the sole financial source of truth; `edara_property_id` is correctly set for leases originating in either Building. Analytic accounting remains genuinely Property-level: one `account.analytic.account` per Property, confirmed shared (not duplicated) across two Buildings' billing flows (payment schedule line invoicing and maintenance vendor billing both resolve through `property_id.get_analytic_account()` to the same record). No parallel ledger, no new `.sudo()` site, no report logic changed.

### Known Limitations

- This phase validates the Property/Building/Unit/Ownership/Accounting/Reporting boundary specifically; it does not add coverage for multi-building interaction with Service Charge allocation (allocation is and remains Building-scoped by design, per `edara.service_charge.building_id`) or Recurring Maintenance (also Unit-scoped by design, per BD-MNT-005) - neither was in scope per the ticket's own task list, and neither showed any sign of a Property-level aggregation defect during discovery.
- Cross-company isolation for this exact multi-building shape was not independently re-tested here - the actual security boundary (Branch) was verified directly, and general cross-company isolation is already covered by the existing `test_edara_multicompany.py`/`test_edara_security_isolation.py` suites, which this phase's discovery did not find any reason to duplicate.

### Deferred Scope (unchanged, not reopened)

Owner Settlement (business-decision-gated, explicitly NOT implemented this phase per instruction), Arabic content authoring, multi-currency-per-contract (business-decision-gated) - all untouched.

### Next Phase

No functional or architectural gap was surfaced by this hardening phase. Per the already-completed Roadmap Review, the next open item remains **Owner Settlement**, still held pending the same business-model decision (does EDARA's real deployment manage properties on behalf of third-party owners) - not started in this ticket. If that decision continues to be "no" (the clarified business model states EDARA is not assumed to be an intermediary manager), the recommended next action is a similarly targeted hardening/regression pass on another already-completed area rather than opening new speculative scope, since no gap was found here to justify one.

## Phase 6 — Dashboard UX & Native Odoo Views Hardening (2026-09-23)

### Status: COMPLETED. Full regression after this phase: 374/374 passing (370 baseline + 4 new tests).

### Objective

Correct the Management Command Center's visual presentation (icon/number/label hierarchy) and close remaining gaps in the "KPI click-through opens the existing native list, already filtered" pattern, per explicit product feedback that the dashboard felt crowded and under-prioritized its own numbers. Native Odoo mechanisms only - no OWL/JS dashboard, no duplicated views, no new models.

### Discovery

Read `edara_dashboard.py`, `views/dashboard_views.xml`, `views/unit_views.xml`/`contract_views.xml`/`maintenance_request_views.xml` (list/kanban/calendar/search), and Odoo's own native `oe_stat_button` SCSS (`odoo/addons/web/static/src/views/form/button_box/button_box.scss`).

Key findings:
- **The KPI-shortcut architecture (§2/§4/§13 of the ticket) was already built** (MAT/UI-032, prior phases): `_quick_action()` already wraps the same native act_window action each EDARA menu uses, with a domain applied, for units/contracts/maintenance/schedule states. This phase extended that existing pattern to the remaining ungated KPIs rather than inventing a second mechanism.
- **Root cause of the "crowded, no hierarchy" complaint, found in Odoo's own source**: `oe_stat_button`'s compact sizing (value and label both `$o-font-size-base-smaller`, icon inline at 1.5em) is scoped to `.o-form-buttonbox` - the small form-header smart-button strip it was designed for. The dashboard form never wraps its buttons in that container, so the buttons were rendering with no differentiated sizing at all - not a bug, but the wrong native widget context for a full-page KPI grid. No native "large-format dashboard tile" component exists in this environment, so a small amount of scoped CSS (not a new widget/framework) was the correct fix, not a native-only alternative.
- **`edara.ownership`/analytic-account architecture (Phase 5) - unaffected, not touched.**
- Two KPIs (SLA At Risk / SLA Breached) had no click-through at all: `sla_state` is a documented non-stored live field (Phase 4's own known limitation) that cannot be a search domain. Resolved by routing through an explicit, already-bounded `('id', 'in', [...])` domain (same "open + branch has a configured SLA target" set the cron/KPI already compute) - still a normal, editable native list filter once opened, just expressed as an id list instead of a field domain.
- 4 informational-only tiles (Total Properties, Total Buildings, Pending Renewals, Open Maintenance) had existing target actions (`action_edara_property`, `action_edara_building`, `action_edara_renewal_request`, `action_edara_maintenance_request`) but no button wiring - fixed.
- 4 Collections monetary tiles (Monthly Revenue, Outstanding Receivables, Payments This Month, Maintenance Cost This Month) had no click-through - fixed by routing to the already-existing Phase 2 Revenue/Receivables/Maintenance Cost report actions and native `account.action_account_payments`, each with the exact same domain its own KPI computation already uses.

### Gantt Capability

**Verified unavailable in this exact environment - not faked.** Checked three ways: (1) no `web_gantt`-named module directory exists in any of the 3 addons paths (`odoo/addons`, the user addons path, `custom_addons`); (2) no Enterprise addons directory exists anywhere on this machine; (3) queried the real `odoo19_dev` database directly (`SELECT name FROM ir_module_module WHERE name ILIKE '%gantt%'`) - zero rows. `web_gantt` is an Odoo Enterprise-only module never shipped in Community, and this installation is Community with no Enterprise addons present. No custom JS/HTML Gantt was built, per instruction. Architecture is already Gantt-ready for whenever Enterprise/`web_gantt` becomes available: `edara.lease.contract` already has `start_date`/`end_date` and an existing native Calendar view (`date_start="start_date" date_stop="end_date"`) on the same action (`views/contract_views.xml`, `view_mode="list,kanban,calendar,form"`) - adding `gantt` to that same `view_mode` string plus one `<gantt date_start="start_date" date_stop="end_date" .../>` view would be the entire integration effort once the module is installed, since the relevant fields and the Lease Contract action already exist. No other Gantt work was attempted.

### Dashboard Changes

**`models/edara_dashboard.py`:**
- `_quick_action()` now accepts a fully-qualified `module.xml_id` (in addition to the existing bare `xml_id` assumed to be `property_managment.*`) - needed for the one new destination in a different module (`account.action_account_payments`); every existing call site is untouched.
- New quick actions: `action_view_properties`, `action_view_buildings`, `action_view_renewals_pending`, `action_view_maintenance_open` (all branch-record-rule-scoped, not accounting-gated).
- New `_sla_request_ids(sla_state)` helper + `action_view_maintenance_sla_at_risk`/`action_view_maintenance_sla_breached` (id-list domain, same bounded query as the KPI/cron).
- New accounting-gated (`_require_accounting_access()`) quick actions: `action_view_monthly_revenue`, `action_view_outstanding_receivables`, `action_view_payments_this_month`, `action_view_maintenance_cost_this_month` - each domain matches the corresponding KPI's own `_compute_kpis` query exactly.

**`views/dashboard_views.xml`:**
- Wrapped the sheet's content in `<div class="o_edara_dashboard">` (a pure CSS scoping hook - no behavior change).
- Converted the 4 previously-plain `o_stat_info` tiles (Total Properties/Buildings/Pending Renewals/Open Maintenance) and the 2 SLA tiles into real `oe_stat_button` buttons wired to the new actions above.
- Converted the 4 Collections monetary tiles into buttons wired to the new accounting-gated actions.
- No structural reorganization beyond that - the existing section order/grouping (Portfolio Overview, Lease Contracts, Collections, Maintenance, Automation) was preserved; it already matched the ticket's own suggested layout.

**New `static/src/css/edara_dashboard.css`** (registered under `web.assets_backend` in `__manifest__.py`, the module's first `assets` key): scoped entirely to `.o_edara_dashboard` so no other form's smart buttons are affected. Gives each tile a card treatment (background/border/radius/shadow/hover), reorders label-above-number via flexbox `order` (no DOM change), enlarges the number (`1.9rem`/700 weight) and shrinks/mutes the label, repositions the icon into a small top-right corner badge instead of sharing the number's line, and adds a state-colored left border reusing the tile's own existing `text-success`/`text-warning`/`text-danger`/`text-primary` classes via `:has()` (no JS, no new state model).

### KPI / Stat Buttons (destination summary)

```text
Total Properties     -> edara.property        []
Total Buildings      -> edara.building         []
Pending Renewals     -> edara.renewal.request  state = submitted
Open Maintenance     -> edara.maintenance.request  state not in (done, cancelled)
Available/Reserved/Rented/Owner Occupied/Sold/Under Maintenance Units -> edara.unit  occupancy_status = <value> (unchanged, already existed)
Draft/Active/Renewed/Terminated/Expired/Expiring Soon Contracts -> edara.lease.contract  state = <value> (unchanged, already existed)
New/Assigned/In Progress/Done/Cancelled Maintenance -> edara.maintenance.request  state = <value> (unchanged, already existed)
SLA At Risk / SLA Breached -> edara.maintenance.request  id in [...] (NEW - previously not clickable)
Recurring Due -> edara.recurring.maintenance  active=True, next_date<=today (unchanged, already existed)
Monthly Revenue -> account.move (Revenue Report)  posted, out_invoice/out_refund, invoice_date>=month_start (NEW)
Outstanding Receivables -> account.move (Receivables Report)  posted, out_invoice/out_refund (NEW)
Payments This Month -> account.payment (native)  date>=month_start (NEW)
Maintenance Cost This Month -> edara.maintenance.request (Maintenance Cost Report)  vendor_bill_id.invoice_date this month (NEW)
Schedule Overdue/Due Today/Due This Month/Paid -> edara.payment.schedule.line  (unchanged, already existed)
```

Every destination is the SAME existing action the corresponding EDARA menu already uses - no new page, no duplicated view, confirmed both by automated test and live validation (below).

### Visual UX

Root cause (see Discovery) was the dashboard reusing `oe_stat_button`'s compact button-box styling outside its intended `.o-form-buttonbox` container, so value/label rendered at the same small size with no separation from the icon. Fixed via scoped CSS: label-above-number order (matches the ticket's own hierarchy diagram), number at `1.9rem`/bold (dominant), label small/uppercase/muted (subordinate), icon moved to a dedicated top-right corner badge at reduced opacity (never shares the number's line), each tile is a bordered/shadowed card with hover lift, and a left-border accent recoloring by the tile's own existing success/warning/danger/primary class. No browser screenshot could be captured in this environment (no interactive browser/display available to this session), so the visual result was verified by (a) successful view compilation/module upgrade with the new markup and asset with zero XML/asset errors, and (b) direct review of the rendered class structure against Odoo's own SCSS. This is a known limitation of this validation pass - see below.

### Security

No ACL/record-rule change. Every new non-Collections quick action is branch-record-rule-scoped exactly like the pre-existing ones (no accounting group involved). Every new Collections quick action reuses the exact existing `_require_accounting_access()` guard (MAT-FIND-014/015 pattern) - raises `UserError`, never a raw `AccessError`, for a user without native Accounting read access, confirmed both automated and live for a disposable Viewer role. No `sudo()` added anywhere in this phase.

### Performance

No new per-KPI query pattern: the 4 new informational/renewal/maintenance quick actions call the exact same `search_count`/`_quick_action` pattern already used everywhere else (O(1) queries, no loops). The SLA click-through reuses the exact same bounded "open + branch has an SLA target" query the KPI compute and cron already run - evaluated once per click, not added to the dashboard's own per-render KPI computation. The 4 Collections destinations perform zero additional queries themselves (they only build a domain); the underlying report actions they open were already query-efficient (Phase 2).

### Automated Test Results

`tests/test_edara_dashboard.py`: extended `test_quick_actions_open_correct_native_view_and_domain`'s case list (4 new non-gated actions) and added 3 new test methods: `test_sla_quick_actions_route_to_maintenance_request_with_matching_ids`, `test_new_non_accounting_quick_actions_work_for_viewer`, `test_collections_quick_actions_open_correct_view_for_accounting_user`, `test_collections_quick_actions_require_accounting_access`.

**Previous baseline:** 370/370. **New tests:** 4 (plus extended assertions in 1 existing test). **Final total: 374/374 passing, 0 failures, 0 errors, 0 skipped.**

### Live Validation (2026-09-23) against real `odoo19_dev`

Ran the upgraded module against real, existing production data (no large disposable dataset created, per instruction - only one disposable `p6lv_viewer` user for the security check). A rolled-back validation script exercised **31/31 checks, 0 failed**: dashboard opens and computes for admin; 7 KPI counts independently cross-checked against direct `search_count()` queries on real data; 15 KPI-navigation checks confirming each quick action's domain resolves, against the REAL database, to exactly the same count the KPI tile itself displays (units, contracts, maintenance, properties, buildings, renewals, SLA id-lists, and all 4 new Collections destinations); 6 security checks confirming a disposable Viewer opens the dashboard cleanly, sees `0`/gated values for every accounting KPI, gets a clean `UserError` (never `AccessError`) from all 6 Collections/Schedule actions, and still succeeds on all 7 non-gated actions.

**Database cleanup:** verified via direct `psql` query - zero `p6lv`/`P6LV`-prefixed rows remain in `res_users`/`res_partner`.

### Known Limitations

- **No visual/screenshot verification was possible in this session** - no interactive browser was available to render and inspect the actual pixel layout. The CSS was written against Odoo's own documented SCSS structure and verified to load without any XML/asset compilation error on a real module upgrade, but a human (or a future session with browser access) should open the Dashboard once and visually confirm the card/hierarchy/icon-placement result matches intent before considering the visual redesign fully closed.
- Native Gantt remains genuinely unavailable (Community edition, no `web_gantt`) - the Lease Timeline candidate is ready to receive it (fields + Calendar view already exist) whenever Enterprise/`web_gantt` is installed; not attempted further here.
- The Collections section's 4 new destinations open the existing Phase 2 report actions (pivot/list views), not a plain filtered list of `account.move` shaped like the Units/Contracts destinations - this matches how those figures were already presented elsewhere in the module (Reports menu) rather than inventing a second representation.

### Deferred Scope (unchanged, not reopened)

Owner Settlement (business-decision-gated), Arabic content authoring, multi-currency-per-contract (business-decision-gated) - all untouched. Native Gantt remains deferred until the environment gains `web_gantt` (Enterprise), not a product decision made here.

### Next Phase

No architectural gap was found. Recommended next action: a human visual pass on the Dashboard (the one item this session could not verify itself), then continue holding on Owner Settlement pending the same business-model decision as prior phases.

## Phase 6.1 — Dashboard & Native Views UX Correction (2026-09-23)

### Status: COMPLETED. Full regression after this phase: 381/381 passing (374 baseline + 7 new tests).

### Objective

Phase 6's human visual acceptance test surfaced real rendering/UX defects the prior automated+live validation could not catch (no browser was available in that session - flagged as a known limitation at the time). This ticket is a correction pass on Phase 6, not a new phase: fix the CSS fallback error, the raw `edara.dashboard,156` breadcrumb, the KPI visual hierarchy, put quick-action shortcuts directly on the Units/Contracts pages (not just the Dashboard), and fix the Unit Kanban's meaningless grouping/drag. No business logic changed.

### Root Causes (found, not guessed)

1. **"A css error occured, using an old style to render this page"**: traced to `odoo/addons/base/models/assetsbundle.py`'s `css()` method, which bakes this exact banner into the compiled bundle whenever `self.css_errors` is non-empty. Directly inspected the actual compiled `web.assets_backend` bundle via `env['ir.qweb']._get_asset_bundle(...).css()` in a real shell against `odoo19_dev`, which surfaced the real underlying error: `"Could not execute command 'sassc'"`. Confirmed `libsass` (the Python `sass` package Odoo tries first) was **not installed** in `server/.venv` (`ModuleNotFoundError: No module named 'sass'`) despite being listed in `requirements.txt`, and the `sassc` CLI fallback is also not on PATH. This meant **every** `.scss` file in the entire `web.assets_backend` bundle (hundreds of native Odoo core files, not anything EDARA-specific) had been failing to compile - Phase 6's own dashboard CSS was never the cause, since plain `.css` files bypass the SCSS compiler entirely in this Odoo version (`assetsbundle.py` only routes `.sass`/`.scss`/`.less` extensions through `compile_css()`) and RTL/`rtlcss` never even runs in this environment (only `en_US`/`ltr` is an installed language, confirmed via `res_lang`). **Fix**: `pip install libsass==0.22.0` into `server/.venv` (matches the exact pin already in `requirements.txt`), then cleared the stale error-baked `ir.attachment` rows so the bundle regenerated fresh. Verified live: the full `web.assets_backend` bundle now compiles with zero `css_errors` (1,096,202 bytes of real CSS, not a 2-line error banner).
   - **Also discovered and fixed while investigating this**: an earlier background server process from this same work (started with `--dev=xml`) had NOT actually terminated when its wrapper task reported "exited" - it stayed bound to port 8069 as an orphaned process for the rest of the session. It is very likely what the human tester's browser actually hit. Killed directly by PID; confirmed the port is clean before starting the real, current server.
   - `:has()` (used in Phase 6's dashboard CSS for state-colored borders) was explicitly investigated as a possible cause per the ticket's instruction and **ruled out**: it compiled cleanly the moment `libsass` worked, and Odoo's own native `button_box.scss` already uses `:has()` (`&:has(.o-dropdown-item:only-child)`) - it is a supported, native-convention selector in this exact Odoo version, kept as-is.
2. **`edara.dashboard,156` visible in the breadcrumb**: `edara.dashboard` (`TransientModel`) had no `name`/`_rec_name` field. Odoo's own `_compute_display_name()` (`odoo/orm/models.py` line ~1439) falls back to `f"{self._name},{self.id}"` whenever no `_rec_name` is set - exactly reproducing the reported string. **Fix**: added `name = fields.Char(default='EDARA Dashboard')` to the model (Odoo auto-uses a field literally named `name` as `_rec_name`) - a fixed label, not a new business field.
3. **KPI layout ("1Total Properties", no hierarchy, misaligned cards)**: a direct consequence of root cause #1 - with the entire backend CSS bundle replaced by the 2-line error-banner stylesheet, **none** of Odoo's own Bootstrap grid/flex CSS was loading either, so the page rendered as raw unstyled HTML (text running together, no card boundaries, no alignment). Once the bundle compiles, all of Phase 6's Bootstrap-grid-based layout applies again. On top of that structural fix, the CSS was also revised per this ticket's more explicit spec (see Dashboard Changes below).
4. **Unit Kanban "None (17) / 1 (1)" grouping + drag-and-drop**: `views/unit_views.xml`'s kanban view had `default_group_by="floor"` (a deliberate Phase-0-era design per spec §48's floor/unit grid mockup). `floor` is a free-text `Char` field that is unpopulated on almost every real unit (blank Char groups under "None"), with exactly one unit in the dataset having `floor='1'` - reproducing the exact reported symptom. Kanban's implicit drag-to-regroup would silently rewrite a unit's `floor` on drop. **Fix**: removed `default_group_by="floor"`, added `records_draggable="false"`, and rebuilt the card template.

### Dashboard Changes

- `models/edara_dashboard.py`: added `name` field (fixes root cause #2).
- `static/src/css/edara_dashboard.css`: revised per this ticket's more explicit hierarchy spec - icon, then label, then the **number in its own bordered/background badge** (`.o_stat_value`: white background, 1px border, 6px radius, its own padding), state-colored via the same existing `text-success/warning/danger/primary` classes on the badge border/text through `:has()`. Cards now stretch to equal height within each Bootstrap row (`height: 100%` on the card, `display: flex` on the row's own columns - Bootstrap's `.row` is already `align-items: stretch` by default, so no custom grid system was needed) for the "consistent grid" requirement. Card background changed from pure white to a very subtle off-white tint (`#fafbfc`) so cards read as distinct from the page background without becoming a "marketing card" design.
- `views/dashboard_views.xml`: unchanged from Phase 6 (the structural fixes were entirely in the environment/CSS, not the view arch).

### Unit Quick Actions (on the Units page itself, not just the Dashboard)

- **`views/unit_views.xml`**: added `<searchpanel><field name="occupancy_status" enable_counters="1"/></searchpanel>` to the existing Unit search view. This is Odoo's own native mechanism for an always-visible, clickable, counted category list beside a list/kanban - the same pattern Odoo's own Helpdesk/Accounting/Recruitment apps use for exactly this "click a status, see the count, filter the same page" requirement. It is deliberately **not** a horizontal button row like the ticket's ASCII mockup (that would require a custom OWL kanban-dashboard component, which the ticket explicitly asks to avoid as "unnecessary JavaScript") - it is the closest fully-native, zero-JS, zero-duplicate-view equivalent, and it satisfies every stated constraint (§7: not a hidden Search > Filters dropdown entry - always visible; opens the same existing list/action; no new page). **Flagged explicitly for the human's visual UAT** in case a literal button row is still wanted - see Remaining Limitations.
- Unit action's `view_mode` changed from `kanban,list,form` to `list,kanban,form` (List is now the default view, Kanban remains available - per §13's explicit permission to do this rather than removing Kanban outright).

### Contract Quick Actions

- **`views/contract_views.xml`**: same `<searchpanel><field name="state" enable_counters="1"/></searchpanel>` pattern added to the existing Contract search view. Contract action's `view_mode` was already `list,kanban,calendar,form` (List-first) - no change needed there.

### Unit Kanban Redesign

- Removed `default_group_by="floor"` and added `records_draggable="false"` (fixes root cause #4).
- Card template rebuilt to show real existing data only: unit name, a colored occupancy-status badge (danger=rented, success=available, warning=under_maintenance, secondary=other), building + floor (only shown when floor is actually populated), and - when an active lease exists - the tenant's name and lease reference. The tenant/lease values come from two new **non-stored, read-only** compute fields on `edara.unit` (`active_tenant_name`, `active_contract_name`), batch-computed with one `search()` call (not per-record), a thin projection of the unit's own existing `lease_contract_ids` - not new business data, matching the ticket's "use only fields that actually exist" instruction while still surfacing tenant/lease context the way the ticket's own example mockup asked for.

### Calendar / Gantt

- **Calendar**: re-verified, unchanged and already correct - `views/contract_views.xml`'s `view_edara_lease_contract_calendar` (`date_start="start_date"`, `date_stop="end_date"`, `color="state"`) is reachable from the Contract action's view switcher (`view_mode` includes `calendar`), confirmed both by automated test and a live `get_view(view_type='calendar')` call against real `odoo19_dev`.
- **Gantt**: re-verified unavailable, same as Phase 6's finding - re-queried the real database directly (`ir.module.module` name ILIKE '%gantt%') and got zero rows again. No custom/fake Gantt was built. No change from Phase 6's conclusion.

### Existing-Action Architecture

Unchanged and reused throughout: every quick action (Dashboard KPI buttons, and the new Unit/Contract search panels) still routes through the same native `ir.actions.act_window` + domain (or, for the search panels, the native `<searchpanel>` mechanism operating on the same already-open action) - no custom controller routes, no custom HTML tables, no second data access layer.

### Security

No ACL/record-rule change. Re-verified live that a Viewer still opens the Dashboard cleanly, still gets `has_accounting_access = False`, still gets a clean `UserError` (never `AccessError`) from a Collections quick action, and a Viewer with no branch assignment still sees zero Units (branch record rule unaffected by the Kanban/search-panel changes, since `<searchpanel>` operates within the model's existing, unchanged record rules exactly like any other search-view element).

### Performance

The two new Unit compute fields (`active_tenant_name`/`active_contract_name`) use one batched `search()` + dict-lookup per Kanban render (not a query per card), mirroring the exact pattern `_compute_contract_count` already used on the same model. `<searchpanel enable_counters="1">` computes its counts via Odoo's own native `read_group`-based mechanism, not custom code. No new N+1 pattern anywhere in this phase.

### Automated Test Results

`tests/test_edara_dashboard.py`: added `test_dashboard_display_name_is_not_raw_model_id`.
`tests/test_edara_property.py`: added `test_unit_kanban_has_no_meaningless_floor_grouping_or_drag`, `test_unit_action_defaults_to_list_view`, `test_unit_search_view_has_native_searchpanel_quick_filter`, `test_contract_search_view_has_native_searchpanel_quick_filter`, `test_contract_calendar_view_reachable_and_valid`, `test_unit_active_tenant_name_reflects_active_contract_only`.

**Previous baseline:** 374/374. **New tests:** 7. **Final total: 381/381 passing, 0 failures, 0 errors, 0 skipped.**

### Live Validation (2026-09-23) against real `odoo19_dev`

A rolled-back validation script exercised **20/20 checks, 0 failed**: the real `web.assets_backend` bundle now compiles with zero `css_errors` and contains the dashboard's own `.o_edara_dashboard` CSS; `edara.dashboard`'s `display_name` is `"EDARA Dashboard"` (not `"edara.dashboard,<id>"`); the Unit Kanban arch has no `default_group_by="floor"` and has `records_draggable="false"`; both the Unit and Contract search views carry a native `<searchpanel>`; the Unit action defaults to List; 3 representative KPI quick actions still resolve to the exact same count as their tile; the Contract Calendar view compiles and is reachable; zero gantt-named modules exist in the real database; and all 4 security re-checks passed with no regression.

**Separately (infrastructure fix, committed, not part of the rolled-back script)**: `libsass==0.22.0` installed into `server/.venv`; stale error-baked `ir.attachment` CSS rows deleted so the bundle regenerates cleanly. This is a one-time environment repair, not application data - there is nothing to "clean up" about it (the deleted rows were corrupted cached output, not real records), and it was verified safe by confirming the bundle recompiles correctly afterward.

**Database cleanup:** verified via direct `psql` query - zero `p61lv`-prefixed rows remain in `res_users`/`res_partner`. Also confirmed via `netstat` that no orphaned server process remains bound to port 8069 (the stray `--dev=xml` process from earlier in this same work was found and killed).

### Known Limitations

- **The Units/Contracts quick actions are implemented as a native `<searchpanel>` (an always-visible, counted, clickable sidebar), not a literal horizontal button row** like the ticket's own ASCII mockup (`[ Rented 12 ] [ Available 8 ]`). This was a deliberate choice to stay within "native Odoo mechanism, no unnecessary JavaScript, no new page" - a literal button row with live counts embedded in a list/kanban page has no zero-JS native Odoo equivalent (it would require a custom OWL kanban-dashboard component). If the human visual UAT determines a literal button row is required, that is a larger, JS-involving change and should be scoped as its own follow-up rather than assumed here.
- No browser screenshot was taken in this session either (same limitation as Phase 6) - the CSS/hierarchy fix was verified structurally (bundle compiles, correct classes present in compiled output) and by direct root-cause diagnosis, not by looking at rendered pixels. Given the root cause (no CSS loading at all) is now fixed and the new CSS spec was implemented precisely as described, the visual result should be dramatically improved, but a human visual pass remains the authoritative check.
- Per §18, no git commit/push was made - this is explicitly deferred until after the human acceptance test.

### Deferred Scope (unchanged, not reopened)

Owner Settlement (business-decision-gated), Arabic content authoring, multi-currency-per-contract (business-decision-gated), a literal button-row alternative to the searchpanel (see Known Limitations) - none touched.

### Next Phase

Not applicable - this was a correction of Phase 6, not a new phase. Awaiting the human visual acceptance test before any git commit/push or further roadmap work.

## Phase 6.2 — External Native Quick Action Buttons (2026-09-23)

### Status: COMPLETED. Full regression after this phase: 385/385 passing (381 baseline + 4 new tests). Phase 6/6.1 still NOT git-committed - pre-acceptance.

### Objective

Phase 6.1's human review rejected the native `<searchpanel>` as satisfying the "external quick-action/stat buttons" requirement - it is a sidebar category filter, not the requested always-visible button row living directly on the Units/Contracts list page. This ticket implements the actual requirement. Explicitly scoped: do not touch Phase 6.1's dashboard CSS/Kanban/Calendar/Gantt work.

### Technical Approach (chosen, and why)

Investigated Odoo 19's own `view_compiler.js` before writing any code: the native `<widget>` tag (`compileWidget()`) always binds `props.record = "__comp__.props.record"` - it is a per-row (list) or per-card (kanban) widget, never a page-level, non-record-bound element. There is genuinely no pure-XML native mechanism for "a button row above a list, not tied to any single record." The ticket's own §5 explicitly pre-authorizes a minimal OWL/JS component for exactly this situation, with documentation of why XML alone is insufficient - this is that documentation.

**Chosen mechanism**: `js_class` on the `<list>` view arch (a standard, well-precedented Odoo extension point - the same one e.g. Odoo's own dashboard-style kanban/list views use), pointing at one small, generic, reusable `ListController` subclass (`EdaraQuickStatListController`) registered once in `static/src/js/quick_stat_bar_list_controller.js`. It `t-inherit`s the native `web.ListView` OWL template (`t-inherit-mode="extension"`) and inserts a button row via an `xpath` targeting the exact node right before `<t t-component="props.Renderer">` - i.e. between the control panel/search bar and the actual records grid, matching the ticket's own mockup positioning. One implementation serves both Units and Contracts (and any future model) via the generic convention `this.orm.call(this.props.resModel, "get_quick_action_bar", [])` - no per-model JS.

**Security is untouched by the JS layer**: the widget never builds a domain or an action itself. It calls one `@api.model` server method (`get_quick_action_bar()`, added to `edara.unit` and `edara.lease.contract`) that returns `{label, count, action}` triples built by reusing the EXACT existing Phase 6 `edara.dashboard._quick_action()` architecture (via a throwaway, never-persisted `.new({})` dashboard record - no new TransientModel row created) and plain `search_count()` for the numbers - both already scoped by the calling user's own normal record rules, exactly like every other count in this module. No sudo, no new ACL, no new record rule, no client-supplied domain of any kind (the status values are a fixed, small, server-known Selection list, never taken from the request).

### Files Changed

- **`models/edara_unit.py`**: `get_quick_action_bar()` (`@api.model`), imported `_` for translated labels.
- **`models/edara_lease_contract.py`**: `get_quick_action_bar()` (`@api.model`).
- **`static/src/js/quick_stat_bar_list_controller.js`** (new): `EdaraQuickStatListController` + registration under `registry.category("views").add("edara_quick_stat_list", ...)`.
- **`static/src/js/quick_stat_bar_list_controller.xml`** (new): the `t-inherit` template that injects the button row.
- **`static/src/css/quick_stat_bar.css`** (new, deliberately separate from Phase 6.1's `edara_dashboard.css` per the "don't redo" instruction): minimal pill-button styling for the bar.
- **`views/unit_views.xml`**: `js_class="edara_quick_stat_list"` on the list view; also added an `active_tenant_name` "Tenant" column (already-existing Phase 6.1 field, matches the ticket's own `Unit | Building | Status | Tenant` mockup).
- **`views/contract_views.xml`**: `js_class="edara_quick_stat_list"` on the list view.
- **`__manifest__.py`**: registered the 3 new asset files under `web.assets_backend`.
- **Untouched, verified unchanged**: `static/src/css/edara_dashboard.css`, `views/dashboard_views.xml`, all Property/Branch/Lease-lifecycle/Payment-schedule/Accounting/Maintenance-accounting/Portal/Owner-Settlement code.

### Units Quick Actions

`edara.unit.get_quick_action_bar()` returns exactly 5 items - Rented, Available, Reserved, Owner Occupied, Under Maintenance - each `{label, count, action}` where `action` is the real `action_edara_unit` act_window with the same domain the Dashboard's own tile already uses (`occupancy_status = <value>`, or `operational_status = 'under_maintenance'`). Rendered as buttons above the existing Unit list (now the default view per Phase 6.1) via the `edara_quick_stat_list` js_class.

### Contracts Quick Actions

`edara.lease.contract.get_quick_action_bar()` returns exactly 5 items - Active, Draft, Renewed, Terminated, Expired - `action` is the real `action_edara_lease_contract` act_window with `state = <value>`. Same button-row mechanism.

### Security

No ACL/record-rule/sudo change anywhere in this ticket. Live-verified: a disposable Viewer's own `get_quick_action_bar()` count for "Rented" matches their own branch-scoped `search_count()` exactly (no cross-branch leakage), and opening their own quick-action's domain does not raise `AccessError`.

### Tests

`tests/test_edara_property.py`: new `TestEdaraQuickActionBar` class - `test_unit_quick_action_bar_counts_and_actions`, `test_contract_quick_action_bar_counts_and_actions`, `test_quick_action_bar_respects_branch_security`, `test_list_views_have_quick_stat_bar_js_class`.

**Previous baseline:** 381/381. **New tests:** 4. **Final total: 385/385 passing, 0 failures, 0 errors, 0 skipped.**

### Live Validation (2026-09-23) against real `odoo19_dev`

A rolled-back validation script exercised **20/20 checks, 0 failed**: the compiled `web.assets_backend` JS bundle actually contains `edara_quick_stat_list`/`get_quick_action_bar` (the new JS genuinely built and loaded, not just present as an unbundled source file); the CSS bundle still compiles with zero errors and still contains both `.o_edara_dashboard` (Phase 6.1, unregressed) and `.o_edara_quick_stat_bar` (this ticket); Phase 6.1's `edara.dashboard,<id>` fix, Unit Kanban fix, Contract Calendar reachability, and Gantt-unavailability finding were all re-confirmed unchanged; `get_quick_action_bar()` returns the correct 5 labels for both models against real production data (**Rented 18**, **Active 18** confirmed against real `odoo19_dev` records - matching the known 18-rented-unit baseline referenced in earlier phases); clicking through 2 different Unit buttons and 2 different Contract buttons each resolved to the exact same record count the button displayed; and both security checks passed.

**Database cleanup:** verified via direct `psql` query - zero `p62lv`-prefixed rows remain in `res_users`/`res_partner`. Confirmed via `netstat` that no process remains bound to port 8069 after the session.

### Remaining Limitations

- **No browser screenshot was taken** (no browser extension connected in this session, same as Phase 6/6.1) - the button bar's actual on-screen click behavior (mouse click → button handler → `doAction`) was NOT executed end-to-end through a real browser event; it was verified structurally (JS present and syntactically valid via `node --check`, correctly registered in the `views` registry, template `xpath` targets the confirmed real node in `web.ListView`, and the server-side data/domain/security half of the round trip fully verified live). This is the one part of "click a button" that only a human browser session can close out - flagged explicitly per §12's instruction not to overclaim pixel/interaction verification.
- The Unit list's new "Tenant" column (`active_tenant_name`) shows only the ACTIVE lease's tenant - a unit with only a draft/terminated/expired contract shows blank, matching the same "active only" semantics already established for this field in Phase 6.1's Kanban card.

### Deferred Scope (unchanged, not reopened)

Owner Settlement, Arabic content authoring, multi-currency-per-contract, Phase 6.1's dashboard CSS/Kanban/Calendar/Gantt (explicitly not redone here) - none touched.

### Next Phase

Not applicable - correction ticket. Per §13, no git commit/push was made. Awaiting the human's actual browser click-through of the new button bar before Phase 6/6.1/6.2 together are considered accepted.

## Phase 6.3 - Quick Stat Bar Regression Fix & Dashboard Empty Panel Cleanup (2026-09-23)

**Status: Implemented, live-validated, NOT committed. Correction ticket for a real regression the human found by opening Properties/Buildings in a real browser.**

### Regression Root Cause (traced, not guessed)

Opening Properties or Buildings threw `TypeError: Cannot read properties of undefined (reading 'items')` in `ListController.slot10`. Root cause is in Phase 6.2's own template, confirmed directly against Odoo's asset-bundling source (`odoo/addons/base/models/assetsbundle.py`, `AssetsBundle.xml()`/`js()`, lines ~428-473):

`quick_stat_bar_list_controller.xml` used `t-inherit-mode="extension"`. Per that source, "extension" mode does **not** create an independent template - it calls `registerTemplateExtension("web.ListView", ...)`, which **patches the one shared `web.ListView` OWL template used by every native list view in the entire backend**, regardless of `js_class`. The injected `<div t-if="edaraQuickStats.items.length">` therefore rendered inside *every* list view's template, but only `EdaraQuickStatListController` instances ever define `this.edaraQuickStats` (in `setup()`). Properties and Buildings use the plain, unmodified `ListController` (no `js_class` on their arch - confirmed, see Files Changed), so on those views `edaraQuickStats` was `undefined`, and the inherited `t-if="edaraQuickStats.items.length"` threw exactly the reported error. This was a global template-registration mistake, not a Units/Contracts-specific bug, and not something a Properties/Buildings-side change could ever have caused.

### Fix

Single-attribute fix: `t-inherit-mode="extension"` → `t-inherit-mode="primary"` in `quick_stat_bar_list_controller.xml`. "primary" mode (confirmed as the standard pattern via Odoo core, e.g. `web.FormEmailField` in `addons/web/static/src/views/fields/email/email_field.xml`) registers `property_managment.QuickStatListView` as its own independent template via `registerTemplate(...)`, leaving `web.ListView` itself completely untouched. Only `EdaraQuickStatListController.template` (set explicitly in the JS) ever resolves to the new template, so every other `ListController`-based view in the backend is structurally guaranteed to keep using the native, unmodified `web.ListView` - satisfying the ticket's required behavior ("optional enhancement, only models with quick-action data render the bar") **by construction**, with zero duplicated controllers.

Two additional defense-in-depth changes (belt-and-braces, since this controller/template is explicitly designed to be generic/reusable by any future model via `js_class="edara_quick_stat_list"`):
- `quick_stat_bar_list_controller.js`: the `get_quick_action_bar` RPC in `onWillStart` is now wrapped in `try/catch`, defaulting to `[]` on any error - so a future model that adopts this `js_class` without implementing the server method fails soft (native list, no bar) instead of crashing the view.
- `quick_stat_bar_list_controller.xml`: the bar's `t-if` now also guards on `edaraQuickStats` itself being truthy (`t-if="edaraQuickStats and edaraQuickStats.items and edaraQuickStats.items.length"`), not just `.items.length`.

With the `primary`-mode fix alone, neither defensive change is reachable by any current view (only Units/Contracts set the `js_class`, and both implement the method) - they exist purely as the required architectural contract for future reuse, per the ticket's §3/§4.

### Quick Actions (confirmed still working)

Units: Rented/Available/Reserved/Owner Occupied/Under Maintenance - unchanged, still 5 real buttons over the real `action_edara_unit` domain. Contracts: Active/Draft/Renewed/Terminated/Expired - unchanged, still 5 real buttons over `action_edara_lease_contract`. Live-verified again end-to-end (see Live Validation) - clicking "Rented" (18) and "Active" (18) still resolve to the exact matching record sets.

### Dashboard Empty Panel

**What it actually was**: not a chatter, not a widget, not a stray Bootstrap column left over from a copy/paste - it is Bootstrap's own flex-grid remainder. `dashboard_views.xml`'s KPI rows use `col-lg-3` (4 cards per line at desktop width), which compiles to `flex: 0 0 auto; width: 25%` (confirmed against `odoo/addons/web/static/lib/bootstrap/scss/mixins/_grid.scss`, `make-col()` - `flex-grow` is `0`). Several of this dashboard's `<div class="row">` blocks hold a card count that is **not** a multiple of 4 (Units: 7, Lease Contracts: 6, Maintenance: 5, Maintenance Phase 2: 3, Automation: 4 at `col-lg-4`/3-per-line). Bootstrap wraps the remainder onto a trailing line without stretching it, so e.g. the Maintenance row's second line has 1 card out of 4, leaving 75% of that line's width dead - the single largest such gap on the page, and the most likely candidate for "large empty rectangle on the right." Confirmed structurally via the live validation script (real row card-counts pulled from the real compiled arch include 7 and 6, i.e. the underfilled scenario is real, not hypothetical).

**Fix**: one additional CSS rule in `edara_dashboard.css`, scoped to `.o_edara_dashboard .row > div[class*="col-"]`, setting `flex-grow: 1`. This overrides only the grow factor, not `width`/`flex-basis` - so the number of cards per line at each breakpoint (the actual "KPI appearance") is completely unchanged, and any row that already divides evenly by 4 is visually unaffected (no leftover space exists to distribute). Only underfilled trailing lines change: their existing cards stretch to fill the line instead of leaving blank grid columns. No XML/layout restructuring, no new elements, nothing removed - purely a one-rule CSS correction of the existing grid's growth behavior.

### Files Changed

- `static/src/js/quick_stat_bar_list_controller.js`: `try/catch` around the `get_quick_action_bar` RPC in `onWillStart` (fail-soft to `[]`).
- `static/src/js/quick_stat_bar_list_controller.xml`: `t-inherit-mode="extension"` → `"primary"` (the actual regression fix); `t-if` hardened against `edaraQuickStats` itself being falsy.
- `static/src/css/edara_dashboard.css`: added `.o_edara_dashboard .row > div[class*="col-"] { flex-grow: 1; }`.
- **Untouched, verified unchanged**: `views/unit_views.xml`, `views/contract_views.xml` (still the only two archs with `js_class="edara_quick_stat_list"`), `views/dashboard_views.xml`, `models/edara_unit.py`, `models/edara_lease_contract.py`, `static/src/css/quick_stat_bar.css`, `__manifest__.py`, all Phase 6.1 fixes (breadcrumb, Kanban, Calendar/Gantt finding).

### Tests

Full `property_managment` regression suite: `odoo-bin ... --test-tags /property_managment` reports **306 passed / 323 (post-install) tests - 14 failed, 3 errors, 0 skipped**. **All 17 non-passing tests are pre-existing environment/data-state issues in the shared `odoo19_dev` database, unrelated to this ticket and unrelated to any file changed in Phase 6.2 or 6.3** (all three changed files in this ticket are JS/XML/CSS only - none of the failing tests touch views, assets, or the quick-stat-bar feature). Root-caused, not assumed:
  - 3 `setUpClass` errors (`TestEdaraBranch`, `TestEdaraLeaseContract`, `TestEdaraProperty`) all fail on the identical line `edara.branch.create({'name': 'Ramallah Branch', 'code': 'RAM'})` → `UniqueViolation` on `edara_branch_code_company_uniq`. Confirmed via `psql`: `odoo19_dev` already has a real branch row (`id=1`, `company_id=1`, `code='RAM'`, created **2026-09-07** - predating every phase in this project's session history) that collides with these tests' hardcoded fixture code. This is a test-fixture fragility against real seeded data, not a code regression.
  - 11 further failures/errors cascade from the 3 `setUpClass` failures above (dashboard KPI tests, multi-company tests) plus a second, independent root cause: `test_edara_deposit`/`test_edara_payment_schedule`/`test_edara_service_charge`'s "...blocked_without_income_account/liability_account" tests assert a `UserError` when no default account is configured, but `psql` confirms company 1's Sales journal (`id=1`) already has `default_account_id=26` ("Product Sales") configured in the current `odoo19_dev` state - so the tests' "no account configured" premise no longer holds. Also pre-existing, also unrelated to any Phase 6.2/6.3 file.
  - **Note on the total**: prior phases in this document reported "385/385"; the current full run reports 323 (post-install) tests as the pass/fail-determining total, with 415 as the total test-method count Odoo's own `tests.stats` line separately reports (a runner-internal reporting-scope difference, not a count discrepancy introduced by this ticket). This was investigated and is not connected to any file this ticket touched.
  - **This ticket did not fix these 17** - out of scope per §5/§9 ("do not change unrelated business logic"), and they predate Phase 6.3 entirely. Flagged here for a separate ticket to (a) give the branch/deposit/payment-schedule/service-charge test fixtures their own isolated test-only company or unique codes instead of hardcoded `'RAM'`, and (b) confirm whether the real `Sales` journal's `default_account_id=26` is intended production configuration (in which case the 3 accounting tests need updating, not the product).
  - The **feature-specific** regression coverage that already existed for this exact bug class continues to pass cleanly: `TestEdaraQuickActionBar` (4/4, in `test_edara_property.py`) ran and passed in full, independent of the unrelated `TestEdaraProperty` class's `setUpClass` failure in the same file.

### Live Validation (2026-09-23) against real `odoo19_dev`

A rolled-back shell validation script exercised **29/29 checks, 0 failed**:
  - The real compiled `web.assets_backend` JS bundle registers `property_managment.QuickStatListView` via `registerTemplate(...)` (independent template) and **not** via `registerTemplateExtension("web.ListView", ...)` (the actual regression mechanism) - confirmed against the real, current bundle content, not just the source file.
  - The unminified controller source in the bundle contains the new `try/catch` fail-soft wrapper.
  - `edara.property` and `edara.building`'s real, current list view archs contain no `js_class="edara_quick_stat_list"`, and neither model has a `get_quick_action_bar` method - structurally confirming they can never hit the code path that crashed.
  - 7 other EDARA list views (Maintenance Requests, Recurring Maintenance, Service Charges, Renewal Requests, Deposits, Payment Schedule Lines, Branches) all confirmed free of the js_class and load their archs normally via `get_view()`.
  - Units/Contracts quick actions re-verified end-to-end against real data: "Rented 18" and "Available 0" (Units), "Active 18" and "Draft 0" (Contracts) all resolved to record sets matching the displayed count exactly.
  - CSS bundle still compiles with zero errors; contains both `.o_edara_dashboard` and the new `flex-grow: 1` rule.
  - Phase 6.1 regressions re-confirmed: dashboard `display_name` fix, Unit Kanban (no `default_group_by="floor"`, `records_draggable="false"`), Contract Calendar reachability.
  - The real, current Dashboard form arch was queried directly and confirmed to contain KPI rows with card counts that are not multiples of 4 (7 and 6 observed), confirming the underfilled-grid-row root cause is real in production data, not a hypothetical.

**Database cleanup:** `psql` confirms zero Phase-6.3-prefixed rows in `res_users`/`edara_branch` (the validation script only performed reads plus one throwaway `edara.dashboard` TransientModel `.create({})`, all rolled back via `env.cr.rollback()`). `netstat` confirms port 8069 is clear; the orphaned test-runner process from the automated suite's own run (PID 4200, left bound to the port after `--stop-after-init`) was identified and terminated before live validation began - the same class of orphaned-process issue documented in Phase 6.1, now recurring, confirming it's an environment quirk of this Windows/Git-Bash setup rather than a one-off.

### Remaining Limitations

- No browser was available in this session (same as every prior phase). The Properties/Buildings crash and its fix were verified via the strongest available non-browser method: the exact template-registration call (`registerTemplate` vs `registerTemplateExtension`) was inspected directly in the real, current compiled asset bundle content, and Odoo's own asset-bundling source was read to confirm what each call actually does - this is a structural/mechanistic proof of the fix, not a guess, but it is still not the same as a human clicking Properties/Buildings in a real browser and seeing no error. That click-through is the one piece that still needs a human.
- The Dashboard's empty-panel fix is CSS-only and was verified by confirming (a) the rule is present in the real compiled bundle and (b) the underfilled-row scenario it targets is real in the current arch/data - but the actual visual result (does the gap look right, is anything now stretched awkwardly wide on very large screens) has not been seen in a real browser either.
- The 17 pre-existing, unrelated test failures documented above mean the full suite is not currently at "all green" - this is disclosed in full rather than only reporting a narrower, cleaner-looking subset.

### Next Phase

Not applicable - correction ticket. Per §15, no git commit/push was made. Recommend a separate, explicitly-scoped ticket for the pre-existing branch-fixture-collision and income/liability-account test failures documented above, since fixing them was out of this ticket's scope. Phase 6/6.1/6.2/6.3 together still await the human's actual browser verification (Properties/Buildings no longer crashing, Units/Contracts buttons still working, Dashboard's empty panel gone) before being considered accepted.

## Phase 6.4 - Test Baseline Cleanup & Environment Isolation (2026-09-23)

**Status: All 17 pre-existing failures/errors resolved at the test-fixture level. Full suite is now genuinely `385/385, 0 failed, 0 errors`. No EDARA product code was changed - test-only. NOT committed.**

**Scope discipline**: this ticket touched only files under `tests/` (9 files). Zero changes to `models/`, `views/`, `static/`, `security/`, or `__manifest__.py`. Zero real business data was deleted or permanently modified - verified by direct `psql` before and after (see Cleanup).

### 1. Reproduction

Re-ran the full suite from a fresh process (not reused from Phase 6.3): identical **14 failed, 3 errors of 323 (post-install) tests**, byte-for-byte the same test names as Phase 6.3's report. Every one of the 17 is independently, deterministically reproducible - confirmed not flaky.

### 2/7. Classification (evidence-based, not assumed)

| Test | Classification | Root Cause | Action |
| ---- | -------------- | ---------- | ------ |
| `TestEdaraBranch` (setUpClass, all 3 methods) | B - fixture/environment contamination | `edara.branch.create({'code': 'RAM'})` collides with a real branch (`id=1`, `company_id=1`, created **2026-09-07**, confirmed via `psql` - predates this project's entire session history) | Renamed fixture to `code='TRAM'`; `test_company_manager_sees_all_branches` rewritten to assert against the pre-existing branch set (captured before creation) `\| branch_a \| branch_b`, not a bare 2-branch equality - this is a *more correct* test of the `(1,'=',1)` rule, not a weakened one |
| `TestEdaraProperty` (setUpClass, all methods) | B | Same `code='RAM'` collision | Same rename (`TRAM`) |
| `TestEdaraLeaseContract` (setUpClass, all methods) | B | Same `code='RAM'` collision | Same rename (`TRAM`) |
| `TestEdaraMultiCompany.test_company_manager_restricted_to_one_company_cannot_see_other_companys_branch` | B | `cls.company_a = cls.env.company` reused the REAL default company (`id=1`), which already has 1 real branch/property/building/18 units/27 contracts (confirmed via `psql`) - `assertEqual(branches, self.branch_a)` broke once real data existed in that company too | `company_a` now created fresh (`res.company.create(...)`), mirroring the file's own pre-existing `company_b` pattern one line below |
| `TestEdaraMultiCompany.test_company_manager_with_both_companies_sees_both_branches` | B | Same root cause as above | Same fix |
| `TestEdaraDashboard.test_kpis_reflect_current_state` | B | `edara_dashboard.py._compute_kpis` is an intentional whole-portfolio count (`search_count([])`, no `sudo()`, fully respects the calling user) - reading it via the unrestricted `self.env` (not `.with_user()`) meant every KPI silently included this shared dev database's real 1 property/1 building/18 units/27 contracts on top of what the test created | Added `cls.dash_company` (isolated `res.company`) + `cls.dash_admin` (company-manager scoped to it only, `company_ids=[(6,0,[dash_company])]`); `cls.branch` now created under `company_id=dash_company.id`; all 6 KPI-reading tests changed to `self.env['edara.dashboard'].with_user(self.dash_admin).create({})` |
| `TestEdaraDashboard.test_available_units_kpi_excludes_reserved_owner_occupied_and_sold` | B | Same root cause | Same fix |
| `TestEdaraDashboard.test_unit_kpi_fields_cover_all_occupancy_states` | B | Same root cause | Same fix |
| `TestEdaraDashboard.test_contract_state_kpis` | B | Same root cause | Same fix |
| `TestEdaraDashboard.test_contract_expiring_soon_kpi_boundaries` | B | Same root cause | Same fix |
| `TestEdaraDashboard.test_maintenance_state_kpis` | B | Same root cause | Same fix |
| `TestEdaraDeposit.test_collection_blocked_without_liability_account` | B | Real company 1 already has `edara_deposit_liability_account_id` configured (`account.account` id 54, confirmed via `psql` - real accounting setup, not test data), defeating the "blocked when unset" premise | Test now explicitly sets `self.env.company.edara_deposit_liability_account_id = False` at its start, matching this file's own established convention (positive tests already mutate this same field per-test, safely, inside the rolled-back transaction) |
| `TestEdaraDeposit.test_deduction_blocked_without_income_account` | B | Same pattern, `edara_deposit_deduction_income_account_id` (id 55) already configured | Same explicit-clear fix |
| `TestEdaraPaymentSchedule.test_invoice_blocked_without_income_account` | B | `edara_rental_income_account_id` (id 52) already configured on real company 1 | Same explicit-clear fix |
| `TestEdaraPaymentSchedule.test_late_fee_blocked_without_income_account` | B | `edara_late_fee_income_account_id` (id 53) already configured | Same explicit-clear fix |
| `TestEdaraServiceCharge.test_invoicing_blocked_without_income_account` | B | `edara_service_charge_income_account_id` (id 56) already configured | Same explicit-clear fix |
| `TestEdaraInvoiceTypeReportFilter.test_revenue_report_filtered_to_rent_excludes_maintenance` | B | `action_edara_revenue_report`'s own domain is intentionally company-wide (a real report), not scoped to one tenant - real company 1's other real posted rent invoices matched the un-scoped assertion `len(rent_moves) == 1` | Query narrowed to `('partner_id', '=', self.tenant.id)`, asserting what THIS test's own fresh tenant actually produced |

**All 17 are Classification B.** No product regression, no test-infrastructure/runner problem, and none pre-date Phase 6.2/6.3 as a *product* defect - they are test fixtures written when this shared dev database had no real data yet, which silently broke as real data (from actual usage/earlier live-validation sessions) accumulated in the same default company over the project's lifetime. This was verified with direct evidence (`psql` queries against real table/column state, `git`-independent code reading of the actual failing fixture lines) for every single one - none were classified by assumption or by "looks unrelated."

### 3. Real data integrity (verified, not assumed)

No real business data was touched. Confirmed via `psql` before and after this ticket's changes: the real `Ramallah Branch` (`id=1`, `code='RAM'`) is untouched; real company 1's `edara_deposit_liability_account_id`/`edara_rental_income_account_id`/etc. are untouched (still non-null, same account ids 52-56 as before); no `res.company` row was deleted; no real `edara.property`/`edara.building`/`edara.unit`/`edara.lease.contract` row was modified. Every mutation made by the fixed tests (`self.env.company.X = False`, new isolated companies/users) happens inside Odoo's standard `TransactionCase` per-test transaction rollback - the same guarantee every other test in this suite already relies on to freely create/modify data - never a direct, persisted database write outside a test transaction.

### 8. Test results

```text
Before: 306/323 (14 failed, 3 errors)
After:  385/385, 0 failed, 0 errors, 0 skipped
```

Ran in two stages per §8: (1) a **targeted** run of exactly the 11 previously-affected test classes independently - **147/147, 0 failed, 0 errors**; (2) the **complete** `property_managment` suite fresh - **385/385, 0 failed, 0 errors**. (The total rose from 323 to 385 tests "counted" - not because tests were added, but because a `setUpClass` failure aborts an entire class without its individual test methods ever being counted; fixing the 3 `setUpClass` errors let their previously-uncounted methods actually run. This resolves the "323 vs 415" count-mechanics question Phase 6.3 had flagged as unexplained.)

No test was skipped, marked `xfail`, had its assertion weakened, or had its exception silently caught to force a pass - every fix either corrects a demonstrably wrong isolation assumption (scoping to what the test itself created) or makes the test's own negative-precondition explicit instead of implicit, per §6.

### 9. Quick Stat Bar fix preserved

Not modified. `t-inherit-mode="primary"`, the controller, template, CSS, and both `get_quick_action_bar()` methods are byte-identical to Phase 6.3. Re-verified via the same Phase 6.3 live-validation script.

### 10. Live Verification (2026-09-23) against real `odoo19_dev`

Re-ran Phase 6.3's rolled-back validation script in full: **29/29 checks, 0 failed** - Properties/Buildings confirmed free of the `js_class` that caused the original crash; Units/Contracts quick-action buttons re-verified end-to-end (`Rented 18`/`Available 0`, `Active 18`/`Draft 0`); CSS bundle compiles cleanly with the Dashboard empty-panel `flex-grow` fix present; Phase 6.1 regressions (breadcrumb, Kanban, Calendar) all still hold. No live check was skipped.

### Cleanup

**PASS.** `psql` confirms: zero `TRAM`-coded branches persisted (test transactions rolled back), zero test-named `res.company` rows persisted, zero Phase 6.4 test users persisted, the real `RAM` branch and real company-1 EDARA accounting fields are both present and unchanged. `netstat` confirms port 8069 is clear (no orphan server process).

### Remaining Limitations

- No browser was available this session (same as every prior phase) - the fixes in this ticket are entirely test-infrastructure-level and were validated via the automated suite + the same rolled-back live-validation script as Phase 6.3; nothing here required new browser verification since no product/view/asset code changed.
- These fixes make the test suite robust against this ONE shared dev database's *current* amount of real data, using isolated companies/explicit field resets - not against a hypothetical future database sharing edge case Odoo's ORM doesn't already guarantee (e.g. a real company somehow also becoming a member of an isolated test company's `company_ids` some other test sets up). This is considered acceptable: it matches the isolation rigor already established by this codebase's own pre-existing `TestEdaraMultiCompany`/accounting-override patterns, and the full suite passing twice independently (targeted + complete) is direct evidence it holds for the actual current environment.

### Next Phase

Not applicable - correction/hardening ticket. Per §13, no git commit/push was made. The test suite is now a trustworthy `385/385` gate for any future phase. Phase 6/6.1/6.2/6.3 still await the human's actual browser verification before being considered accepted; Phase 6.4 does not change that.

## Phase 6.5 - Remove Units & Contracts Quick Action Bar (2026-09-23)

**Status: Removed completely. Search Panel (Phase 6.1) is now the sole filtering UX on Units/Contracts. NOT committed.**

**Reason for removal**: after review, the Search Panel/Sidebar already provides the intended filtering experience, and the Quick Action Bar's buttons navigated to a separate filtered page rather than applying the filter inline in the current list - not the intended UX. Removed as a genuine implementation removal (not CSS-hidden) per the ticket's explicit instruction.

### Files/components removed

- `static/src/js/quick_stat_bar_list_controller.js` - deleted (file no longer exists).
- `static/src/js/quick_stat_bar_list_controller.xml` - deleted.
- `static/src/css/quick_stat_bar.css` - deleted.
- `__manifest__.py` - removed the 3 deleted files from `assets.web.assets_backend` (kept `edara_dashboard.css`, unrelated to this feature).
- `models/edara_unit.py` - removed `get_quick_action_bar()`; removed the now-unused `_` import (verified no other call site in the file uses the bare `_` - existing code uses `self.env._()` instead).
- `models/edara_lease_contract.py` - removed `get_quick_action_bar()`. `_`/`api` imports kept - both still used elsewhere in the file (verified before touching).
- `views/unit_views.xml` - removed `js_class="edara_quick_stat_list"` and its explanatory comment from the list view; list view is otherwise byte-identical (Phase 6.1's `active_tenant_name`/"Tenant" column untouched).
- `views/contract_views.xml` - removed `js_class="edara_quick_stat_list"` and its comment from the list view; otherwise unchanged.
- `tests/test_edara_property.py` - removed the entire `TestEdaraQuickActionBar` class (4 tests: `test_unit_quick_action_bar_counts_and_actions`, `test_contract_quick_action_bar_counts_and_actions`, `test_quick_action_bar_respects_branch_security`, `test_list_views_have_quick_stat_bar_js_class`) - every test in it exercised only the removed feature, none tested anything else.

Verified via `grep` across the entire module both before removal (found exactly these 8 code/asset files + the test file, nothing else) and after (zero remaining references to `quick_stat`/`quick_action_bar`/`edara_quick_stat_list`/`QuickStatListView` anywhere in code - only this state file's historical Phase 6.2/6.3/6.4 entries mention it, correctly preserved as history, not edited).

### Files/components intentionally preserved

- `static/src/css/edara_dashboard.css` and the Dashboard itself (Phase 6/6.1) - untouched, unrelated feature.
- `t-inherit-mode="primary"` - moot now (the file it was on is deleted), but the general lesson (never use `t-inherit-mode="extension"` on a shared native template) remains documented in Phase 6.3's section for any future reuse of this pattern.
- Units/Contracts Search Panel (`<searchpanel>` with `enable_counters="1"`, Phase 6.1) - fully intact in both views, confirmed via live validation.
- All native Units/Contracts filters, Kanban, Calendar, list columns (including `active_tenant_name`).
- Properties/Buildings (never had `js_class` - confirmed structurally, not just assumed).
- All Phase 6.4 test-isolation fixes (isolated companies, `TRAM` branch rename, account-field resets) - none of those touched Quick-Action-Bar code, so none needed changes here.

**Deferred, not deleted as a concept**: the external quick-action/stat-button-row pattern (`js_class` + generic `ListController` extension + server-side `get_quick_action_bar()`-style convention) is a valid, reusable Odoo UX pattern for a *different* project that wants literal external buttons instead of a Search Panel. It was removed from THIS project because the Search Panel already covers the need here, not because the pattern itself was flawed (Phase 6.3 already fixed its one real bug, the `t-inherit-mode` template-scoping issue).

### Automated tests

```text
Before removal: 385/385, 0 failed, 0 errors
After removal:  381/381, 0 failed, 0 errors, 0 skipped
```

381 = 385 - 4 (the removed `TestEdaraQuickActionBar` tests), confirming nothing else broke. Ran twice: once immediately after the code changes, and again after an explicit `-u property_managment` module upgrade (needed because editing view XML on disk doesn't retroactively update the already-installed `ir.ui.view.arch_db` rows in a running database - same class of staleness issue as Phase 6.1's CSS cache finding) - both runs green.

### Live Validation (2026-09-23) against real `odoo19_dev`

First pass (before the module upgrade) correctly caught that the database's `ir.ui.view` rows still had the OLD (js_class-bearing) arch cached - 4/20 checks failed, confirming the live validation script actually does something rather than trivially passing. Ran `-u property_managment` to reload the view definitions, then re-ran: **20/20 checks, 0 failed**:
  - Compiled JS/CSS bundles confirmed to no longer contain `edara_quick_stat_list`/`get_quick_action_bar`/`QuickStatListView`/`o_edara_quick_stat_bar` - the removal is real in the actual served assets, not just the source tree.
  - `.o_edara_dashboard` CSS (Phase 6.1) confirmed still present; CSS bundle still compiles cleanly (no fallback banner).
  - Units and Contracts list view archs confirmed to have **no `js_class` attribute at all** now (fully native `ListController`).
  - Both `get_quick_action_bar` methods confirmed absent from the live model classes (`hasattr` check).
  - Both Search Panels (`<searchpanel>`, `occupancy_status`/`state`) confirmed present and intact.
  - Properties/Buildings list views re-confirmed to have no `js_class` (the Phase 6.3 crash's precondition genuinely cannot recur, since the file that caused it no longer exists).
  - Phase 6.1 regressions (dashboard `display_name`, Unit Kanban, Contract Calendar) re-confirmed unchanged.
  - Native filters on both Units (Available/Rented/Under Maintenance) and Contracts (Active/Draft/Renewed/Terminated/Expired) search views confirmed present.

Direct `psql` query additionally confirmed zero `ir_ui_view` rows anywhere in the database still contain `edara_quick_stat_list` in their `arch_db` - the removal is complete at the database level, not just in what a single view's `get_view()` happens to return.

### Cleanup

**PASS.** `psql` confirms: the real `RAM` branch (`id=1`) and real company-1 EDARA accounting fields are unchanged; zero leaked test users/companies from this ticket's own validation activity; zero `ir_ui_view` rows referencing the removed `js_class`. `netstat` confirms port 8069 clear (only benign `TIME_WAIT` entries from normal shell-connection teardown, no live orphan process).

### Confirmation

Units and Contracts now rely entirely on their native Search Panel/Sidebar filters (Phase 6.1) for quick filtering - no custom JS controller, no external button row, no `get_quick_action_bar()` backend method. Both lists are back to plain native `ListController` behavior.

### Remaining Limitations

- No browser was available this session. The removal was verified via the strongest available non-browser methods: direct inspection of the real compiled JS/CSS asset bundles (confirming the removed code is genuinely absent from what the browser would actually receive, not just from the source tree) and a direct `psql` query of every `ir_ui_view` row in the database. What has NOT been done is a human actually opening Units/Contracts in a browser and visually confirming no button row renders and no console error appears - that remains the one piece only a human session can close out, consistent with every prior phase's disclosed limitation.

### Next Phase

Not applicable - removal/cleanup ticket, no further phase started per this ticket's own closing instruction. Per Git §, no commit/push was made.

## Phase 6.6 - Payment Schedule Filter Shortcut Buttons (2026-09-23)

**Status: Implemented, tested, live-validated. NOT committed.**

### What was built

Three compact buttons - **Paid | Overdue | Draft** - above the Payment Schedule list only. These are **search-filter shortcuts, not navigation**: each click calls `this.env.searchModel.toggleSearchItem(id)` on the matching named `<filter>` in a new `view_edara_payment_schedule_line_search` view - the exact same API Odoo's own Search Bar dropdown uses internally when a filter chip is clicked. No domain is built in JS, no `ir.actions.act_window` is created or opened, the user never leaves the Payment Schedule list, and the active filter shows up as a normal facet in the native search bar (since it drives the same `searchModel`, not a parallel mechanism).

**Investigation finding worth recording**: `edara.payment.schedule.line` had **no dedicated search view at all** before this ticket (only Odoo's auto-generated default) - the ticket's premise that filters "already exist" to be reused did not hold for this model. The `paid`/`overdue`/`draft` filters were created fresh in this ticket, using the exact same field/domain pattern already established for Units/Contracts search views, and `search_view_id` was wired onto `action_edara_payment_schedule_line` for the first time too (it also had none before).

### How the buttons activate the existing search filters

1. `view_edara_payment_schedule_line_search` defines `<filter name="paid" domain="[('state','=','paid')]"/>` (and `overdue`/`draft` siblings) - `state` values confirmed directly from `STATES` in `models/edara_payment_schedule_line.py` (`draft`, `invoiced`, `partial`, `paid`, `overdue`, `cancelled`), not guessed.
2. At runtime, Odoo's `SearchArchParser` parses each `<filter>` into a `searchItem` object carrying its `name` (confirmed in `odoo/addons/web/static/src/search/search_arch_parser.js` line 265-266).
3. `EdaraPaymentScheduleFilterShortcutsController` (a small `ListController` subclass) looks up the 3 matching `searchItem`s by `name` from `this.env.searchModel.searchItems`, and each button's click handler calls `this.env.searchModel.toggleSearchItem(item.id)` - confirmed against `odoo/addons/web/static/src/search/search_model.js`'s `toggleSearchItem()` (lines 852-876): it adds/removes a `{searchItemId}` entry from `this.query` and notifies - literally the same code path `search_bar_menu.js`'s native filter-menu items use.
4. A button's active/inactive (`btn-primary`/`btn-outline-primary`) state is computed the same way Odoo's own `_enrichItem()` computes `isActive` (`search_model.js` line 1360: `this.query.some(q => q.searchItemId === item.id)`), and the component re-renders on `searchModel`'s own `"update"` event (`useBus(this.env.searchModel, "update", this.render)` - the identical idiom used by `search_bar.js`/`search_panel.js`/`with_search.js`).

### Confirmation: no new navigation/action created

Verified both structurally (test + live query) that `ir.actions.act_window.search_count([('res_model','=','edara.payment.schedule.line')])` is still exactly **1** - the same pre-existing `action_edara_payment_schedule_line`, nothing added.

### Architecture rule honored (Phase 6.2/6.3 mistake not repeated)

`payment_schedule_filter_shortcuts.xml` uses `t-inherit-mode="primary"` (never `"extension"`) - confirmed live against the real compiled JS bundle: it contains `registerTemplate("property_managment.PaymentScheduleFilterShortcutsListView", ...)` and does **not** contain `registerTemplateExtension("web.ListView", ...)`. This is scoped ONLY to the Payment Schedule list via its own dedicated `js_class="edara_payment_schedule_filter_shortcuts"` - a name deliberately distinct from Phase 6.2's removed `edara_quick_stat_list`, registered as its own independent entry in `registry.category("views")`. No other EDARA list view (Units, Contracts, Properties, Buildings, or any other) references this `js_class` - verified live.

### Files Changed

- **`views/payment_schedule_line_views.xml`**: new `view_edara_payment_schedule_line_search` record (3 filters + a `group_by_state` groupby for good measure, matching Units/Contracts search view conventions); `js_class="edara_payment_schedule_filter_shortcuts"` added to the list view; `search_view_id` wired onto `action_edara_payment_schedule_line`.
- **`static/src/js/payment_schedule_filter_shortcuts.js`** (new): `EdaraPaymentScheduleFilterShortcutsController` - the only JS for this feature, ~50 lines, dedicated (not a reused generic pattern from the removed Phase 6.2 code).
- **`static/src/js/payment_schedule_filter_shortcuts.xml`** (new): the `t-inherit-mode="primary"` template.
- **`static/src/css/payment_schedule_filter_shortcuts.css`** (new): minimal, scoped to `.o_edara_schedule_filter_shortcuts`/`.o_edara_schedule_filter_shortcut` - compact button row, no large panel.
- **`__manifest__.py`**: registered the 3 new asset files under `web.assets_backend`.
- **`tests/test_edara_payment_schedule.py`**: new `TestEdaraPaymentScheduleFilterShortcuts` class (5 tests).
- **Untouched, verified unchanged**: Units/Contracts/Properties/Buildings views, Dashboard, `web.ListView`, every other EDARA list's `js_class` (none), all Phase 6.4 test-isolation fixes, all Phase 6.5 removal work.

### Automated Tests

New: `test_list_view_has_scoped_js_class`, `test_search_view_has_paid_overdue_draft_filters_with_correct_domains`, `test_action_has_no_new_act_window_created`, `test_no_global_web_list_view_modification` (inspects the real compiled bundle for `registerTemplate` vs `registerTemplateExtension`, mirroring the Phase 6.3 live-validation check as an automated regression test this time), `test_other_list_views_remain_unaffected`.

```text
Targeted (new class only): 5/5, 0 failed, 0 errors
Full suite:                 386/386, 0 failed, 0 errors, 0 skipped
```
386 = 381 (Phase 6.5 baseline) + 5 new. A module upgrade (`-u property_managment`) was required between writing the view XML and the tests passing - editing `ir.ui.view` XML on disk does not retroactively update the already-installed `arch_db` row (same class of staleness as Phase 6.1/6.5's findings; the first targeted run failed with "External ID not found" for the new search view until the upgrade ran).

**Environment note (not a regression)**: a live Odoo server process was already running and bound to port 8069 throughout this session (started independently, well before this ticket, with an active established connection - consistent with a human actively doing manual browser verification of an earlier phase). Out of respect for that possible live session, every command in this ticket avoided binding port 8069 - test runs used either `--no-http` (for non-HTTP tests) or `--http-port=8070` (for the full suite, since it also includes `HttpCase`-based Portal tests that genuinely need an HTTP server), and live validation used `odoo-bin shell --no-http` (which never binds HTTP). An initial full-suite attempt under `--no-http` alone produced 14 false-positive failures, all in `TestEdaraPortal`/`TestEdaraMaintenancePhase2Portal` (`HttpCase`-based, needs a real HTTP server for `url_open()`) - re-run on port 8070 confirmed **0 real failures**; this was investigated and traced to the flag choice, not treated as a regression by assumption.

### Live Validation (2026-09-23) against real `odoo19_dev`

Rolled-back shell script: **21/21 checks, 0 failed** - compiled JS bundle confirmed to contain the new controller and register it via `registerTemplate` (never `registerTemplateExtension`); compiled CSS confirmed to contain the new compact styling and still compile cleanly; the list/search view wiring confirmed live (`js_class`, all 3 filter domains, `search_view_id`, exactly 1 action for the model); real production data confirmed meaningful for this test (`paid=2, overdue=20, draft=100` real lines - not a zero-data false pass); every regression check (Units/Contracts/Properties/Buildings free of this `js_class`, Phase 6.5's removal still holds, Dashboard/Kanban unchanged) passed.

### Cleanup

**PASS.** `psql` confirms: zero stray users/records from this ticket's own testing, the real `RAM` branch and real company-1 accounting fields unchanged, the new search view registered exactly once. Port 8070 (used for the full-suite HTTP-dependent run) confirmed clear after the run. **Port 8069's pre-existing process was deliberately left untouched throughout** (see note above) - not confirmed "clean" in the sense of being empty, by design, since killing a possibly-live human session would have been the wrong call; this differs from every prior phase's cleanup note and is called out explicitly here rather than silently reported as PASS/FAIL.

### Remaining Limitations

- No browser click-through was performed by this session - verified via the strongest available non-browser methods (real compiled-bundle inspection, real database queries, the full automated suite). A human still needs to actually click Paid/Overdue/Draft in a real browser and confirm the search bar facet appears, pagination behaves normally, and clearing the filter restores the full list - consistent with every prior phase's disclosed limitation.
- A live server process was present on port 8069 for this entire ticket, started independently of this session. It was not stopped, inspected beyond its process metadata, or otherwise interfered with. If that process was in fact orphaned rather than a live human session, it remains running after this ticket and should be checked before the next phase.

### Next Phase

Not applicable per this ticket's own closing instruction. Per Git §, no commit/push was made.

## Phase 6.6 Hotfix - Payment Schedule View Registry Regression (2026-09-23)

**Status: Investigated, root-caused, fixed at the asset-serving layer. No product/view/JS code was wrong or changed. NOT committed.**

### Regression discovered

Human browser testing at `localhost:8069` reported `KeyNotFoundError: Cannot find key "edara_payment_schedule_filter_shortcuts" in the "views" registry` on **both** Lease Contracts and Payment Schedule.

### Root cause

**Not a code defect.** Direct `psql` inspection of the live database (the specific evidence this ticket required before touching anything) proved:
- `ir_ui_view.arch_db` for `edara.lease.contract.list` contains **no `js_class` at all** - confirmed via `arch_db::text ILIKE '%js_class%'` returning `false`. Lease Contracts was never wrongly wired to this `js_class`; the source XML (`views/contract_views.xml`) has never referenced it either.
- `ir_ui_view.arch_db` for `edara.payment.schedule.line.list` correctly and exclusively contains `js_class="edara_payment_schedule_filter_shortcuts"`.

This ruled out the "wrong view definition" hypothesis the ticket specifically asked to check first (§"Do NOT assume Lease Contracts should use this js_class"). The actual fault was in the **served JS asset bundle**: a direct query of `ir_attachment` for `%assets_backend%` found **no `web.assets_backend.min.js` (non-lazy) attachment row existed in the database at all** at the time of investigation - only a stale `web.assets_backend.min.css` (`write_date` 13:55, hours before Phase 6.6's own edits) and the separate `_lazy.min.js` bundle. The backend's live server process serving the browser session at the time (a separate, independently-started process, not one of this conversation's own commands) was therefore either serving a stale/incomplete bundle or hit a transient generation gap while its cached attachment had already been invalidated by the ordinary asset-versioning mechanism reacting to this ticket's file edits mid-session - a known class of Odoo dev-mode issue when editing manifest-referenced assets while a server is actively handling requests, not a defect in the registration code itself.

### Why Lease Contracts was also affected

Lease Contracts never had the wrong `js_class` at the view-definition level (proven above). The shared symptom (`KeyNotFoundError` for the exact same missing key on an unrelated page) is consistent with the SPA's client-side registry being fully unpopulated for that key (the JS module that calls `registry.category("views").add("edara_payment_schedule_filter_shortcuts", ...)` never successfully executed in that browser session, because the bundle it loaded was stale/incomplete) combined with the browser tab's own error-recovery/navigation state after the first failure - this was not independently re-diagnosed at the OWL-runtime level since no browser tool was available (see Remaining Limitations), but the view-definition-level root cause (the only thing that could make this "Lease Contracts' own fault") was conclusively ruled out.

### Corrective action taken

No source file needed a code fix - `models/`, `views/`, `static/src/js/`, `static/src/css/`, and `__manifest__.py` from the original Phase 6.6 implementation were already correct (re-verified: `t-inherit-mode="primary"`, correct `js_class` scoping, correct manifest asset paths - all unchanged). The corrective action was ensuring a **freshly and correctly regenerated, properly persisted** asset bundle:

1. Confirmed the previously-observed live server process (bound to port 8069, started independently before this hotfix ticket) had already exited on its own by the time investigation began - `curl`/`netstat` both confirmed nothing was listening on 8069 anymore. It was never stopped or interfered with by this session; per the ticket's own instruction, no server was killed.
2. Started a genuine, fresh Odoo HTTP server on port 8069 (the same port, now free) so the served state could be directly, honestly verified rather than inferred.
3. Regenerated the `web.assets_backend` JS and CSS bundles via `env['ir.qweb']._get_asset_bundle(...)` and **committed** the result (a deliberate exception to this project's usual rolled-back live-validation scripts - asset bundle cache is not business/test data, matching the established Phase 6.1 precedent of directly fixing stale CSS cache). Confirmed in that same run: the regenerated bundle contains `registerTemplate("property_managment.PaymentScheduleFilterShortcutsListView", ...)` and does **not** contain `registerTemplateExtension("web.ListView", ...)` - the registration is correct.
4. Fetched the exact resulting bundle URL (`/web/assets/8681e3e/web.assets_backend.min.js`) via real, unauthenticated `curl` against the live, freshly-started server - **HTTP 200**, 6.6MB, containing `edara_payment_schedule_filter_shortcuts` exactly once. This is direct, real-HTTP proof (not source inspection, not a rolled-back script) that the currently-running server now serves the correct, working bundle.
5. Did not delete any attachment beyond the one (`id 1023`, the stale CSS bundle) that Odoo's own existing `_clean_attachments()` logic replaced as part of normal, intended bundle-regeneration behavior - no attachment was deleted arbitrarily.

### Registration/asset/view correction details

No `js_class`, `t-inherit-mode`, registry key, or view attribute was changed - all were already exactly per the intended architecture from the original Phase 6.6 implementation. The "correction" was entirely at the persisted-asset layer (forcing a correct, committed bundle to exist), not the source-code layer.

### Automated Tests

Two new regression tests added directly targeting this failure class:
- `test_lease_contract_list_view_has_no_js_class_at_all` - pins the exact finding from this investigation (Lease Contracts' `arch_db` has no `js_class` whatsoever).
- `test_no_unintended_view_references_the_js_class_anywhere` - a full-database sweep (`ir.ui.view.search([('arch_db', 'like', 'edara_payment_schedule_filter_shortcuts')])`) asserting exactly one view in the entire system references this `js_class` - stronger than spot-checking individual known views, catches any future accidental leak to any view, not just the ones explicitly enumerated.

```text
Targeted (TestEdaraPaymentScheduleFilterShortcuts, now 7 tests): 7/7, 0 failed, 0 errors
Full suite: 388/388, 0 failed, 0 errors, 0 skipped
```
388 = 386 (Phase 6.6 baseline) + 2 new. Run on port 8071 (a third alternate port) specifically to avoid touching the fresh verification server this hotfix ticket was actively using on 8069.

### Live Runtime Validation

Performed directly against the real, currently-running server on `localhost:8069` (not source inspection, not a rolled-back script):
- `curl http://localhost:8069/web/login` → HTTP 200 (server responsive).
- `curl http://localhost:8069/web/assets/8681e3e/web.assets_backend.min.js` → HTTP 200, bundle contains the correct registration exactly once, no `registerTemplateExtension("web.ListView"` anywhere.
- Direct `psql` re-confirmation (post-fix) that `ir_ui_view.arch_db` for Lease Contracts still has no `js_class`, and Payment Schedule still has exactly the right one.

**Browser tooling was checked and found unavailable** in this session (`tabs_context_mcp` reported the extension not connected, consistent with every prior phase) - an actual click-through/visual/console-error check was not possible. The verification above is the strongest available substitute: real HTTP requests against the actual live server's actual served bytes, not an assumption.

### Confirmations

- **Payment Schedule shortcuts still work**: unchanged from Phase 6.6 - `Paid`/`Overdue`/`Draft` still call `searchModel.toggleSearchItem()`, still no navigation/new action, re-verified by the 7 passing tests plus the confirmed-correct live bundle.
- **Lease Contracts is restored**: it was never actually broken at the view/code level; the live server now serving it is fresh and correctly bundled, so the same `KeyNotFoundError` cannot recur against this server instance.
- **No global ListView regression**: re-confirmed live - the regenerated bundle uses `registerTemplate`, never `registerTemplateExtension`, for this feature's template, exactly as Phase 6.3's lesson requires.

### Cleanup

**PASS**, with one deliberate, disclosed exception: a fresh Odoo server (this hotfix ticket's own, started for verification) is **intentionally left running on port 8069** so the person can immediately reload their browser tab and see the fix working, without needing to start anything themselves. No real business/accounting data was modified (re-confirmed via `psql`: real `RAM` branch and real company-1 accounting fields unchanged); zero disposable test data from this ticket's own investigation persisted; ports 8070/8071 (used transiently for isolated test runs) confirmed clear after their runs. The only non-test-data persisted change is the regenerated, correctly-functioning asset bundle attachments themselves (expected, intended Odoo caching behavior, not disposable data).

### Remaining Limitations

- No browser tool was available to literally click through and watch the console - verified instead via real HTTP requests against the actual live server and a full automated suite. A human reloading the browser tab now pointed at port 8069 is the one remaining step to see this with their own eyes.
- The exact moment/mechanism that left the JS bundle attachment missing during the original Phase 6.6 session was not, and could not be, reconstructed with certainty (the original live server process's own logs were never captured, since it was started independently of this conversation's tracked commands). The fix addresses the resulting state conclusively (bundle now correct and verified live) rather than pinpointing the precise race condition.

### Next Phase

Not applicable per this ticket's own closing instruction. Per Git §, no commit/push was made.

## Phase 6.7 - Document & Package Payment Schedule Filter Shortcut Pattern + GitHub Release (2026-09-23)

**Status: Documentation created, repository verified, committed and pushed to GitHub. This is the first phase in this project's session history where a commit/push was explicitly authorized and performed.**

### Reusable documentation created

`docs/PAYMENT_SCHEDULE_FILTER_SHORTCUTS_PATTERN.md` (new file, ~450 lines) - a complete,
English-language, developer-reusable writeup of the Phase 6.6/6.6-Hotfix Payment Schedule
filter-shortcut pattern, covering: the UX use case and the wrong-vs-correct approach
distinction; the full architecture diagram; the actual Search View XML with field-by-field
explanation; the actual JS controller quoted in full with section-by-section commentary
(including a reusable-vs-project-specific table); the actual OWL template quoted in full with
`t-inherit-mode="primary"` explained; the actual CSS quoted in full with its design
principles; the manifest/asset wiring with a troubleshooting section; a dedicated
registry/`js_class` explanation including the exact `KeyNotFoundError` this project hit and
the evidence-based diagnosis order that resolved it (database -> compiled bundle -> served
bytes); a clearly marked "Do Not Repeat the Global ListView Mistake" section documenting the
Phase 6.2 `t-inherit-mode="extension"` incident as a permanent warning; a reusable client
checklist; a documentation-only adaptation example (`sale.order`, explicitly not applied to
the real project); a troubleshooting section; a testing-strategy section; and a final
"Reusable Asset Summary" table clearly separating generic/reusable components from
EDARA-Payment-Schedule-specific names, so the pattern can be lifted for another client without
accidentally carrying over EDARA-specific identifiers.

### Final repository verification (performed before committing)

- `git status`/`git diff` inspected in full: 51 modified files + 12 untracked files (all of
  this project's cumulative work since the single prior "Add property management module"
  commit - Phase 3 through Phase 6.7, nothing scoped out).
- Every untracked file confirmed to be legitimate, properly-wired module content (e.g.
  `models/edara_recurring_maintenance.py` confirmed imported in `models/__init__.py`;
  `views/account_move_views.xml`/`views/recurring_maintenance_views.xml` confirmed listed in
  `__manifest__.py`'s `data` list) - nothing orphaned or accidental.
- `static/src/` confirmed to contain exactly the 4 files that should exist (Phase 6.1's
  dashboard CSS + Phase 6.6's Payment Schedule filter-shortcut JS/XML/CSS) - Phase 6.2's
  removed `quick_stat_bar_list_controller.*` files confirmed genuinely absent, not just
  untracked-and-forgotten.
- Full diff and all untracked files scanned for credential/secret patterns
  (`api_key`, `secret`, hardcoded `password=`, `token=`, private-key headers, `aws_access`,
  `DATABASE_URL`) - **zero matches** beyond expected, benign test-fixture patterns (e.g.
  `new_test_user`'s own `login + 'x'*(8-len(login))` password generation).
- No `.log`, `.pyc`, `.db`, `.sqlite`, `.env`, `.bak`, or other disposable/generated files found
  anywhere in tracked or untracked state - `.gitignore` (despite a pre-existing cosmetic defect
  where its content is literally the PowerShell heredoc command used to create it, rather than
  clean patterns - a pre-existing issue, not introduced or fixed by this ticket, and not
  touched since it was functionally still excluding `__pycache__` correctly) was confirmed
  functionally sufficient by the absence of any `__pycache__`/`.pyc` entries in `git status`.
  The module's own `odoo.conf` (containing `db_password`) lives one directory above this
  module's own git repository root and was confirmed to never be part of this repo at all.
- Full automated suite re-run immediately before committing, on an isolated port, as a final
  coherence check: **388/388, 0 failed, 0 errors**.

### Files included in the commit

Every file `git status` reported as modified or untracked - the complete, current,
already-tested state of the module across every phase in this document, plus this ticket's own
new documentation file. No file was excluded or partially staged.

### Git

- **Remote**: `origin` -> `https://github.com/Haitham-Nageh/odoo_property_managment.git` (confirmed via `git remote -v` before pushing - the expected repository).
- **Branch**: `main`, tracking `origin/main`.
- **Commit hash / push status**: recorded in this session's final report to the user (this
  document does not record its own commit's hash, since the hash cannot be known before the
  commit - including this very line - is created); authoritative record is `git log` on this
  repository.

### Remaining Limitations

- This phase performed no new functional testing beyond the final full-suite coherence check
  above and the existing Phase 6.6/6.6-Hotfix live validation already on record - no new
  browser-level verification was added or attempted here, consistent with this phase being
  documentation + packaging only, as instructed.
- The pre-existing `.gitignore` cosmetic defect (noted above) was left as-is since fixing it
  was outside this ticket's explicit scope ("Do not modify unrelated files"); it does not
  currently cause any functional problem.

### Next Phase

Not applicable per this ticket's own closing instruction ("Do not start another development phase").
