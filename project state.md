# EDARA Property Management — verified project state

Updated **2026-10-14T21:08:50+03:00 (Asia/Hebron)**. This report supersedes the unverified or outdated conclusions in the October 13 report. Historical implementation notes remain in `EDARA_PROJECT_STATE.md`. This is development verification, not a production-readiness declaration.

## Environment and safeguards

- Odoo `20.0+e-20261004`; module `20.0.1.5.0`.
- Root: `D:\Odoo\Projects\Odoo 20.0e.20261004`; server is not a Git repository. The module directory is the Git repository.
- Database: `edara_odoo20_dev`, actual PostgreSQL **17.9** (server version `170009`) on port `5432`; browser HTTP `8069`; automated HTTP tests `18069`. The previous PostgreSQL 16 assertion was incorrect.
- Configuration: `dev_config/odoo20-dev.conf`; Python: `python/python.exe` under the Odoo 20 root. Credentials are intentionally omitted.
- Branch `odoo20-port`; baseline commit before this checkpoint: `6558e21643c62f3b4a0a726d83fdd3eaf6e93df0`. The stabilization work was committed afterwards as the checkpoint `feat(property-management): stabilize Odoo 20 dashboard and workflows` (see `git log`). A curated subset of the evidence is preserved in `docs/verification/2026-10-14/`; full logs and screenshots remain outside Git in `server/edara_verification/`.
- During verification no backup, database deletion/recreation, broad business-record deletion, manual attachment cleanup, commit, reset, branch switch or push was performed (the checkpoint commit/push happened afterwards, as a separate step). Native asset rebuilding replaced its own stale bundles.
- Odoo 19 files, configuration, database and processes were not modified.

## Verified PASS — dashboard icons and client behavior

The live dashboard originally had three distinct defects:

1. Standard view buttons used names absent from Odoo's bundled Material Symbols subset: `trending_up`, `event`, `domain`, `apartment`, `meeting_room`. Replaced with supported `show_chart`, `calendar_today`, `business`, and `home` equivalents.
2. OWL/chart/view markup and Python-generated attention/activity HTML still used Font Awesome classes, which have no backend icon styling in this build. Replaced with `class="oi" data-icon="..."`, preserving color and size utilities. View-button colors remain separate `icon_class` attributes.
3. Maintenance status cards, heading and SLA chevrons used FontAwesome private-use glyphs in SCSS. Replaced those with supported Material Symbols ligatures and explicit font/ligature/direction rules. Existing layout, labels, colors, chart data and KPI definitions were preserved.

All dashboard areas were inspected: quick actions, financial overview, revenue trend, collections, attention cards, portfolio distribution, lifecycle bar, deposits, service invoicing, maintenance status/SLA, and recent activity. Five additional unsupported names in the existing branch/building/property/contract form changes were corrected (`business`, `flash_on`, `calendar_today`, `security`).

- Final Arabic dashboard: **57 displayed icons**, no detected missing glyphs, no browser console errors or failed asset responses.
- Final English dashboard: **57 displayed icons**; administrator language was temporarily changed and restored. Initial session-only English attempts were normalized back to Arabic by Odoo and are not counted as English verification.
- Empty-state browser fixture: 50 icons passed. The response fixture used actual Python empty renderers and zero chart data; it did not alter business records.
- Actual branch/chart/shortcut interaction results: 18 passed, 0 failed; details in `dashboard-interactions.json`.
- Final screenshots and all JSON/browser evidence are under `server/edara_verification/`: `before-financial.png`, `before-maintenance.png`, `before-activity.png`, `before-portfolio.png`; corresponding `after-*` and `final-*` screenshots; `final-ltr-dashboard.png`; `after-empty-dashboard.png`; `final-schedule-filters.png`; `portal-dashboard.png`, `portal-own-lease.png`.

## Verified PASS — review of existing changes

The initial working tree contained 24 modified tracked files plus untracked `project state.md` and `.claude/settings.local.json`. Every existing diff was reviewed. The installed Owl runtime and native components confirm `useProps()`, callable `signal.ref()`, `proxy()` and component expressions qualified with `this.`. The small `.el` getters on refs remain compatible; no unnecessary refactor was introduced. Payment-shortcut inheritance targets the actual `this.props.Renderer` expression and stays scoped to its own list view.

All 39 module XML files parse; all declared backend assets exist. All literal icons in modified XML were checked against the bundled font's actual GSUB ligatures. `git diff --check` passes. The Odoo 20 iterable form of `concat()` replaces a deprecated call that produced server warnings.

The pre-existing local tool settings contain embedded credentials. Their values were not copied into this report or source changes; the file was preserved and a targeted `.gitignore` rule now protects it. No generated verification artifact is inside the module repository.

## Verified PASS — actual installments and financial KPIs

There are **43** actual lines, not 36 total: 36 on three active leases and seven retained owed periods on terminated leases. Full due dates, original/final states, unpaid amounts, currencies, invoices and contracts are in **`server/edara_verification/installments.csv`** and `data-inspection-before.json` / `data-inspection.json`.

| Contract | Contract state | Lines | Overdue | Paid | Future draft |
|---|---|---:|---:|---:|---:|
| LC/2026/1908 | active | 12 | 3 | 4 | 5 |
| LC/2026/1909 | active | 12 | 12 | 0 | 0 |
| LC/2026/1910 | active | 12 | 4 | 0 | 8 |
| LC/2026/1911 | terminated | 6 | 6 | 0 | 0 |
| LC/2026/1917 | terminated | 1 | 1 | 0 | 0 |

The dashboard defines overdue as stored installment `state = 'overdue'`, within normal user/branch record rules, independently of the reporting period. Amount uses invoice residual when invoiced, otherwise schedule amount, converted to company currency at the current date. Paid/cancelled states and future lines are excluded. Retained pre-termination debt is intentionally billable under the existing lifecycle implementation; the draft contract has no schedule lines.

The original 22 items matched stored states but four October 13 lines had become past due without recomputation. The root cause was a stored computation depending on due date: midnight does not invalidate an ORM field dependency. Added private `_refresh_overdue_states()`, called before the existing overdue-reminder selection, reusing the existing computation and caller's scope. No invoices, late fees, schedule dates or amounts are created/changed by that refresh. Refreshed only IDs `18596`, `18617`, `18631`, `18650` in this database.

Final states: **{'overdue': 26, 'paid': 4, 'draft': 13}**. Independent record calculation and displayed KPI both give **26 overdue**, amount **124,320.98 ILS**. This is scheduled debt, including uninvoiced periods; it is a different population from posted receivables.

Other verified KPIs: units **12**, occupied **3**, available **8**, active leases **3**; posted receivables **26,300.01 ILS**; period revenue **14,300.01 ILS**; maintenance expense **450.00 ILS**. Branch counts are Ramallah 7 units and Al Quds 5 units. Current period due count is 4, paid installments 4.

## Verified PASS — accounting and currencies

Company `EDARA Real Estate Co.` uses **ILS** (currency record 89). Flat late fee is **50 ILS**. Actual mappings and account types:

| Purpose | Account | Type |
|---|---|---|
| Rental income | 401000 | income |
| Late fee income | 451000 | income_other |
| Service charge income | 402000 | income |
| Security deposit liability | 201200 | liability_current |
| Deposit deduction income | 452000 | income_other |
| Maintenance expense | 613000 | expense |

Existing bill 867 for `MR/2026/0601` was genuinely draft, including its debit/credit rows. It was posted once as **BILL/2026/10/0001**, dated October 13, 2026: debit 613000 **450 ILS**, credit accounts payable **450 ILS**, property analytic **205:100%**. Repeated bill creation returned the same bill, and repeated completion was blocked; no second bill/expense was created. Completing maintenance does not automatically create a bill by design.

All **23 posted moves** are balanced. The four existing rent invoices/payments have zero receivable residual and matching full reconciliations. Native customer and vendor payment reconciliation also passed in the rollback workflow run. Rent, late-fee and service invoices credit their configured income accounts and debit receivables; deposit collection credits liability, refund debits liability, deduction debits liability/credits deduction income; maintenance bills debit expense/credit payable.

Actual company-specific USD rate is dated **2026-10-13**, stored `0.27027 USD per ILS`, inverse **3.7000037000037 ILS/USD**. USD rent invoice 874 stores ±2,500 USD in `amount_currency` and ±9,250.01 ILS balances. Deduction move 876 stores ±1,000 USD and ±3,700.00 ILS. These actual stored lines were inspected; no currency or rate configuration was changed.

Service charge `SC/2026/0179` totals **5,000 ILS**, allocated 2,000/3,000 to units A-102/A-201, invoices 868/869, income 402000 and analytic **204:100%**. Property, building, branch, tenant, amounts and journal lines match. Each allocation maps to exactly one corresponding lease (2018/2016). The current service-charge model stores unit/tenant rather than an explicit contract field; invoice `edara_contract_id` is blank by that existing design.

## Verified PASS — workflows and portal authorization

The rollback script passed **38 checks**, covering lease creation/activation/schedules; overlap prevention; rent/late-fee mapping and duplicate prevention; payment reconciliation and paid installment; renewal request approval and existing renewal wizard; termination and protected terms; deposit collection, partial deduction/refund, excessive/duplicate action rejection and final terminated-lease refund; maintenance hierarchy, assignment, SLA timestamps, stages, billing, completion and vendor reconciliation. All test business records rolled back and counts returned to baseline. See `workflow-checks.json` for individual names and rolled-back IDs.

Layla's existing user (396) was exercised through real Chromium HTTP requests with actual user permissions: **39 passed**, 0 failed. Own lease 2017 and unit 2066 were visible; other tenants' contracts/units/maintenance/invoices were denied via direct URLs and ORM requests. Protected writes, internal models and private methods were denied. Valid CSRF foreign maintenance and renewal submissions were rejected. Anonymous access required login. Direct deposit-model access is internal-only, including for the owning tenant; there is no custom deposit detail route. Portal pages rendered without exceptions. Automated HttpCase tests separately exercise valid maintenance and renewal submissions within rollback transactions.

## Reproducible tests and actual outcomes

Run from the Odoo 20 **server** directory:

```powershell
& 'D:/Odoo/Projects/Odoo 20.0e.20261004/python/python.exe' edara_verification/run_module_tests.py --final
& 'D:/Odoo/Projects/Odoo 20.0e.20261004/python/python.exe' edara_verification/workflow_checks.py
& 'D:/Odoo/Projects/Odoo 20.0e.20261004/python/python.exe' edara_verification/inspect_data.py
python edara_verification/review_static.py
```

The launcher executes native Odoo `-d edara_odoo20_dev -u property_managment --test-enable --test-tags=/property_managment --stop-after-init --http-port=18069 --max-cron-threads=0`, using the existing config. It imports native Odoo initialization, then disables only `TransactionCase._gc_filestore` to preserve files. Business/security assertions, database savepoints and rollback remain enabled. It does not suppress failing tests.

- Final suite: **845 selected, 844 passed, 0 failed, 0 errors, 1 skipped**. Exact names/results: `test-results.json`, `full-suite-final.log` and `automated-tests.csv`.
- Focused overdue class: 6 tests, zero failures/errors using the safe launcher.
- Added regressions: `TestEdaraOverduePaymentReminders.test_reminder_refreshes_uninvoiced_line_after_day_rollover` and `.test_reminder_refreshes_unpaid_invoice_after_day_rollover`. Both first failed with the original stale states, then passed after the fix.
- Earlier native run: six assertions passed but filestore teardown failed. Earlier full run: 10 failures (nine fixture-isolation failures and one launcher UTC initialization failure), corrected and rerun. They are retained in evidence, not counted as passes.
- The historical “27 tests” is a prose matrix with no linked runnable implementation. The actual repository contains 29 automated test modules and 845 methods. It was not treated as 27 executed automated passes.

Browser checks can be reproduced after running `bootstrap_sessions.py` and starting the target server: `node edara_verification/browser_check.cjs final`, `... final-ltr`, `node edara_verification/dashboard_interactions.cjs`, `node edara_verification/portal_check.cjs`. The scripts use the existing cached Playwright/Chromium paths. Run `cleanup_sessions.py` afterward. Session secrets must remain private and outside Git.

## Failed / Blocked / Not tested / Known limitations

- **Failed (historical, superseded):** original icon glyph check; two new rollover regressions before the fix; fixture-isolation/launcher failures in the first full run. Final suite failures/errors are stated above.
- **Blocked:** an unmodified native teardown crashes in Odoo core `_gc_file_store_unsafe` / `_full_path` on interrupted `.__gc` checklist markers (one native run also logged file permission errors). Files were preserved. Full verification used the documented cleanup-disabled launcher; native GC itself has not been repaired or certified. Required next action: repair/update the Odoo core interrupted-marker handling separately, then rerun native tests without the launcher override.
- **Not tested / skipped:** TestMatFind015DepositWizardJournalResolution.test_wizard_confirm_succeeds_end_to_end_for_edara_only_user : This company does not have exactly one Cash/Bank journal - ambiguous case is covered separately.
- **Not tested:** Layla's password login (temporary server-created sessions were used without changing passwords); real bank-statement settlement of outstanding clearing accounts; live payment-provider processing; external email delivery.
- **Known limitation:** closed USD deposit 460 has zero USD business balance but **0.01 ILS credit** left in the liability ledger: collection 18,500.02, refund 14,800.01, deduction 3,700.00. Those liability entries are not reconciled. No arbitrary write-off or accounting-configuration change was made; a settlement/reconciliation policy is still needed.
- **Known limitation:** service-charge invoices have no explicit stored lease link, though current unit/tenant/date matches were verified.
- **Environment:** `markdown2` and `rtlcss` are absent; these produce existing server warnings. The Arabic dashboard currently has computed LTR direction, matching its baseline; full RTL asset conversion was not certified. Arabic/English icon rendering was visually checked. A second pre-existing variadic `concat(*sorted_list)` at dashboard line 251 still produces an Odoo 20 deprecation warning; it remains functional. Expected access-denial and negative-constraint logs are explained by the security/negative tests. Browser navigation timeouts during early/cold/concurrent attempts were retried and are not counted as successful checks.

## Exact files, Git state and cleanup

All existing OWL migrations and legitimate view changes were preserved. Files modified by this stabilization task: `.gitignore`, `models/edara_dashboard.py`, `models/edara_payment_schedule_line.py`, `static/src/scss/edara_dashboard.scss`, the occupancy/revenue/collections XML templates, `views/dashboard_views.xml`, `views/branch_views.xml`, `views/building_views.xml`, `views/property_views.xml`, `views/contract_views.xml`, `tests/test_edara_notifications.py`, `tests/test_edara_reporting_phase2.py`, and this state file. Test fixtures were scoped rather than deleting demo data.

No new persistent business/demo records were created. Persistent changes were posting existing bill 867 and refreshing four stale installment states. Rollback tests consumed ordinary record/sequence IDs but left no test business rows. Dashboard openings created ordinary transient snapshots.

Cleanup: task-created sessions removed **3**; private session file removed **True**. Task-started process verification: **{'remaining_task_browser_pids': [], 'remaining_task_odoo_pids': [], 'http_8069_closed': True, 'postgres_5432_listening': True, 'test_http_18069_closed': True}**. The original administrator language preference was restored. All task-started Odoo/browser processes were stopped; no pre-existing Odoo 19 process was stopped.

Tracked modified files at verification time: **30**. At the end of verification no commit or push had been made; this state file and the curated evidence in `docs/verification/2026-10-14/` were then included in the checkpoint commit. Local tool settings (`.claude/settings.local.json`) are ignored and never committed.

Status listing at verification time (before the checkpoint commit):

```text
 M .gitignore
 M models/edara_dashboard.py
 M models/edara_payment_schedule_line.py
 M static/src/js/edara_branch_filter_widget.js
 M static/src/js/edara_collections_chart_field.js
 M static/src/js/edara_collections_chart_field.xml
 M static/src/js/edara_deposit_donut_field.js
 M static/src/js/edara_deposit_donut_field.xml
 M static/src/js/edara_lifecycle_bar_field.js
 M static/src/js/edara_lifecycle_bar_field.xml
 M static/src/js/edara_occupancy_chart_field.js
 M static/src/js/edara_occupancy_chart_field.xml
 M static/src/js/edara_revenue_chart_field.js
 M static/src/js/edara_revenue_chart_field.xml
 M static/src/js/edara_service_invoice_field.js
 M static/src/js/edara_service_invoice_field.xml
 M static/src/js/payment_schedule_filter_shortcuts.js
 M static/src/js/payment_schedule_filter_shortcuts.xml
 M static/src/scss/edara_dashboard.scss
 M static/src/xml/edara_branch_filter_widget.xml
 M tests/test_edara_notifications.py
 M tests/test_edara_reporting_phase2.py
 M views/branch_views.xml
 M views/building_views.xml
 M views/contract_views.xml
 M views/dashboard_views.xml
 M views/maintenance_request_views.xml
 M views/property_views.xml
 M views/recurring_maintenance_views.xml
 M views/unit_views.xml
?? "project state.md"
```
