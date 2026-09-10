# EDARA Property Management — UI & Fields Implementation Inventory

**Purpose:** A complete, accurate map of the CURRENT implementation of `custom_addons/property_managment` (Odoo 19), for manual acceptance testing. Everything below was verified directly against the current source code, current XML views, current security configuration, and the live `odoo19_dev` database — not against the original spec or memory. Where the spec described something not present in the code, it is marked **Not implemented / not exposed**. Where the code does something beyond the spec, it is marked **Implemented beyond original specification**.

This document does not modify any business logic — it is pure documentation.

---

## 1. Complete Navigation Tree

```
EDARA Property Management  (menu_edara_root, ROOT/APPLICATION MENU, web_icon=property_managment,static/description/icon.png, groups=group_edara_viewer)
├── Dashboard                (menu_edara_dashboard, seq 5, action_edara_dashboard_open [ir.actions.server -> edara.dashboard form])
├── Properties                (menu_edara_property, seq 10, action_edara_property [act_window, edara.property])
├── Buildings                 (menu_edara_building, seq 20, action_edara_building [act_window, edara.building])
├── Units                     (menu_edara_unit, seq 30, action_edara_unit [kanban,list,form on edara.unit])
├── Contracts                 (menu_edara_lease_contract, seq 40, action_edara_lease_contract [act_window, edara.lease.contract])
├── Payment Schedule          (menu_edara_payment_schedule_line, seq 50, action_edara_payment_schedule_line [act_window, edara.payment.schedule.line])
├── Security Deposits         (menu_edara_deposit, seq 60, action_edara_deposit [act_window, edara.deposit])
├── Service Charges           (menu_edara_service_charge, seq 70, action_edara_service_charge [act_window, edara.service.charge])
├── Maintenance                (menu_edara_maintenance_request, seq 80, action_edara_maintenance_request [kanban,list,form on edara.maintenance.request])
├── Renewal Requests           (menu_edara_renewal_request, seq 90, action_edara_renewal_request [kanban,list,form on edara.renewal.request])
├── Reports                   (menu_edara_reports, seq 95, NO action — pure folder, groups=group_edara_accountant,group_edara_branch_manager)
│   ├── Revenue                (menu_edara_revenue_report, seq 10, action_edara_revenue_report [pivot,graph,list on account.move])
│   ├── Expenses                (menu_edara_expense_report, seq 20, action_edara_expense_report [pivot,graph,list on account.move])
│   ├── Receivables              (menu_edara_receivables_report, seq 30, action_edara_receivables_report [pivot,graph,list on account.move])
│   ├── Occupancy                (menu_edara_occupancy_report, seq 40, action_edara_occupancy_report [pivot,graph,list on edara.unit])
│   └── Tenant Ledger            (menu_edara_tenant_ledger_report, seq 50, action_edara_tenant_ledger_report [list,pivot on account.move])
└── Configuration              (menu_edara_configuration, seq 100, NO action — pure folder, groups=group_edara_branch_manager)
    ├── Branches                 (menu_edara_branch, seq 10, action_edara_branch [act_window, edara.branch])
    └── Settings                  (menu_edara_settings, seq 90, action_edara_config_settings [form, res.config.settings], groups=group_edara_company_manager — STRICTER than the Configuration folder itself)
```

**DB cross-check** (odoo19_dev, `ir_model_data` rows where `module='property_managment'`, queried live via `psql`):

| Object type | Count |
|---|---|
| `ir.ui.menu` | 20 (matches the 20 `<menuitem>` records above exactly) |
| `ir.actions.act_window` | 19 |
| `ir.actions.server` | 3 (`Open EDARA Dashboard`, plus the 2 cron jobs — `ir.cron` shares the `ir.actions.server` table in Odoo 14+) |
| `ir.cron` | 2 |
| `res.groups` | 8 |
| `ir.rule` | 43 |
| `ir.ui.view` | 42 |
| `ir.model` (new/extended models owned by this module) | 21 |
| `ir.model.access` | 47 (CSV file has 48 data rows including header — one blank/comment line difference is immaterial) |
| `ir.sequence` | 3 |

### Menu table

| Menu Name | XML ID | Parent | Groups | Action | Action Type | Target Model | View Modes | Root/App Menu? |
|---|---|---|---|---|---|---|---|---|
| EDARA Property Management | menu_edara_root | (none) | group_edara_viewer | (none) | — | — | — | **Yes** — App Switcher entry |
| Dashboard | menu_edara_dashboard | menu_edara_root | (inherited) | action_edara_dashboard_open | ir.actions.server (code) | edara.dashboard | form | No |
| Properties | menu_edara_property | menu_edara_root | (inherited) | action_edara_property | ir.actions.act_window | edara.property | list, form | No |
| Buildings | menu_edara_building | menu_edara_root | (inherited) | action_edara_building | ir.actions.act_window | edara.building | list, form | No |
| Units | menu_edara_unit | menu_edara_root | (inherited) | action_edara_unit | ir.actions.act_window | edara.unit | kanban, list, form | No |
| Contracts | menu_edara_lease_contract | menu_edara_root | (inherited) | action_edara_lease_contract | ir.actions.act_window | edara.lease.contract | list, form | No |
| Payment Schedule | menu_edara_payment_schedule_line | menu_edara_root | (inherited) | action_edara_payment_schedule_line | ir.actions.act_window | edara.payment.schedule.line | list, form | No |
| Security Deposits | menu_edara_deposit | menu_edara_root | (inherited) | action_edara_deposit | ir.actions.act_window | edara.deposit | list, form | No |
| Service Charges | menu_edara_service_charge | menu_edara_root | (inherited) | action_edara_service_charge | ir.actions.act_window | edara.service.charge | list, form | No |
| Maintenance | menu_edara_maintenance_request | menu_edara_root | (inherited) | action_edara_maintenance_request | ir.actions.act_window | edara.maintenance.request | kanban, list, form | No |
| Renewal Requests | menu_edara_renewal_request | menu_edara_root | (inherited) | action_edara_renewal_request | ir.actions.act_window | edara.renewal.request | kanban, list, form | No |
| Reports | menu_edara_reports | menu_edara_root | group_edara_accountant, group_edara_branch_manager | (none) | — | — | — | No — pure folder |
| Revenue | menu_edara_revenue_report | menu_edara_reports | (inherited) | action_edara_revenue_report | ir.actions.act_window | account.move | pivot, graph, list | No |
| Expenses | menu_edara_expense_report | menu_edara_reports | (inherited) | action_edara_expense_report | ir.actions.act_window | account.move | pivot, graph, list | No |
| Receivables | menu_edara_receivables_report | menu_edara_reports | (inherited) | action_edara_receivables_report | ir.actions.act_window | account.move | pivot, graph, list | No |
| Occupancy | menu_edara_occupancy_report | menu_edara_reports | (inherited) | action_edara_occupancy_report | ir.actions.act_window | edara.unit | pivot, graph, list | No |
| Tenant Ledger | menu_edara_tenant_ledger_report | menu_edara_reports | (inherited) | action_edara_tenant_ledger_report | ir.actions.act_window | account.move | list, pivot | No |
| Configuration | menu_edara_configuration | menu_edara_root | group_edara_branch_manager | (none) | — | — | — | No — pure folder |
| Branches | menu_edara_branch | menu_edara_configuration | (inherited) | action_edara_branch | ir.actions.act_window | edara.branch | list, form | No |
| Settings | menu_edara_settings | menu_edara_configuration | group_edara_company_manager | action_edara_config_settings | ir.actions.act_window | res.config.settings | form | No |

`menu_edara_reports` and `menu_edara_configuration` are pure folder menus with no `action` — Odoo simply expands their children in the navbar; they are not independently "openable" screens.

Children with no explicit `groups=` inherit visibility purely from whether their own target model's ACL grants read access to the user's groups — Odoo does not cascade a parent menu's `groups=` onto children automatically. Only 4 places in this file carry an explicit `groups=`: `menu_edara_root`, `menu_edara_reports`, `menu_edara_configuration`, `menu_edara_settings`. See §12 for the full access breakdown per role.

---

## 2. Module metadata (manifest)

- Technical name: `property_managment` (contains a typo — "managment" — permanent by design; not to be renamed).
- Display name: `EDARA Property Management`. Version `19.0.1.0.0`.
- Category (manifest, free text): `Real Estate/Property Management`. Separately, `ir.module.category` record `module_category_edara` = "EDARA Property Management" (sequence 20) groups the security groups in Settings > Users — these are two different mechanisms, not to be confused.
- Depends: `base`, `mail`, `portal`, `account`.
- `application: True`, `installable: True`, `auto_install: False`.
- No `assets` key — **no custom JS, SCSS/CSS, or OWL components anywhere in the module** (confirmed: zero `.js`/`.scss`/`.css` files exist). The only static asset is `static/description/icon.png` (the App Switcher icon).
- No demo data file declared.
- 19 data files loaded in this order: `security/edara_security.xml`, `security/ir.model.access.csv`, `security/edara_record_rules.xml`, `data/edara_sequences.xml`, `data/edara_analytic_plan.xml`, `data/edara_cron.xml`, `views/dashboard_views.xml`, `views/branch_views.xml`, `views/property_views.xml`, `views/building_views.xml`, `views/unit_views.xml`, `wizard/edara_lease_renewal_wizard_views.xml`, `wizard/edara_deposit_transaction_wizard_views.xml`, `views/payment_schedule_line_views.xml`, `views/deposit_views.xml`, `views/service_charge_views.xml`, `views/maintenance_request_views.xml`, `views/renewal_request_views.xml`, `views/reports_views.xml`, `views/contract_views.xml`, `views/res_partner_views.xml`, `views/res_config_settings_views.xml`, `views/portal_templates.xml`, `views/edara_menus.xml`.

---

## 3. Complete Model Inventory (Fields, Forms, Lists, Kanban, Search, Buttons, State Machines, Relationships)

Each model below is documented in full: fields table, form view, list/kanban view, search view, buttons/actions, state machine (if any), relationships, required/optional fields for creation, and gaps proven from code. This section subsumes the spec's §3–§8 (models, forms, lists, search, buttons, state machines) on a per-model basis; §7/§8 also each get a cross-model master table afterward for quick scanning.

### 3.1 edara.branch

**Human name:** EDARA Branch · **Inherits:** `mail.thread` · **Order:** `name`
**Purpose:** Represents an operational region/office; scopes staff access and reporting. Explicitly NOT a separate legal company (per the model's own action help text).

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| (no override) | `name` | Char | Yes | No | Yes | No | No | — | — | Branch name, tracked |
| (no override) | `code` | Char | Yes | No | Yes | No | No | — | — | Short unique code per company (e.g. RAM, NBL); tracked; unique per company + non-empty constraint |
| Company | `company_id` | Many2one | Yes | No | Yes | No | No | `self.env.company` | res.company | indexed |
| Branch Manager | `manager_id` | Many2one | No | No | Yes | No | No | — | res.users | tracked |
| Assigned Staff | `user_ids` | Many2many | No | No | Yes | No | No | — | res.users via `edara_branch_users_rel` | "Internal users who can access records scoped to this branch" |
| (no override) | `active` | Boolean | No | No | Yes | No | No | True | — | archive flag |
| (no override) | `street` | Char | No | No | Yes | No | No | — | — | |
| (no override) | `city` | Char | No | No | Yes | No | No | — | — | |
| Properties | `property_ids` | One2many | No | No | No | No | No | — | edara.property via `branch_id` | |
| (property_count) | `property_count` | Integer | No | No | No | Yes | No | — | — | compute, depends `property_ids`, via `_read_group` |
| Currency | `currency_id` | Many2one | No | No | No | No | `company_id.currency_id` | — | res.currency | related, not stored |
| Total Revenue | `total_revenue` | Monetary | No | No | No | Yes | No | — | — | `@api.depends()` — no deps, always recomputed on read |
| Total Expenses | `total_expenses` | Monetary | No | No | No | Yes | No | — | — | same compute |
| Net Operating Result | `net_operating_result` | Monetary | No | No | No | Yes | No | — | — | revenue − expenses |
| Total Outstanding | `total_outstanding` | Monetary | No | No | No | Yes | No | — | — | sum of `amount_residual_signed` on posted customer moves |

Financial summary: queries `account.move` where `edara_branch_id=branch.id`, `state='posted'`, `move_type in (out_invoice,out_refund)` for revenue/outstanding, and `in_invoice/in_refund` for expenses (sign-flipped). Not stored — recalculated every read.

**Form View** (`view_edara_branch_form`): Ribbon "Archived" (`invisible="active"`). Smart button: **Properties** (`action_view_properties`, counter=`property_count`, icon `fa-building-o`). Title `name`. Group left: `code`, `company_id` (groups=`base.group_multi_company`), `manager_id`, `active` (invisible=1). Group right: `street`, `city`, `phone`, `email`. Notebook: "Assigned Staff" tab (`user_ids`), "Financial Summary" tab (`currency_id` invisible, `total_revenue`, `total_expenses`, `net_operating_result`, `total_outstanding`). Chatter: present (mail.thread only, no activity mixin).

**List View** (`view_edara_branch_list`): | Column | Field | Widget | Optional | Notes | — Name(default), Code(default), Company(default, `groups=base.group_multi_company`), Branch Manager(default), City(default). No decorations; falls back to model `_order='name'`.

**Search View:** None defined — `action_edara_branch` has no `search_view_id`; default auto-generated name search only.

**Buttons/Actions:** Properties smart button → `action_edara_property` filtered `branch_id=self.id`. No state machine (`edara.branch` has no `state` field).

**Action** `action_edara_branch`: `view_mode="list,form"`, empty-state help present.

**Relationships:** `property_ids` (O2M) → `edara.property.branch_id`; `user_ids` (M2M) ↔ `res.users`. Every property/building/unit/contract carries a related+stored `branch_id`.

**Required for creation:** `name`, `code`, `company_id` (defaults current company). **Optional but important:** `manager_id`, `user_ids` (branch-scoped access depends on this), `street`/`city`/`phone`/`email`.

**Gaps:** None found.

---

### 3.2 edara.property

**Human name:** EDARA Property · **Inherits:** `mail.thread` · **Order:** `name`

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| (none) | `name` | Char | Yes | No | Yes | No | No | — | — | "e.g. Al-Irsal Complex"; tracked |
| (none) | `code` | Char | Yes | No | Yes | No | No | — | — | tracked; unique per company |
| Branch | `branch_id` | Many2one | Yes | No | Yes | No | No | — | edara.branch | tracked, indexed |
| Company | `company_id` | Many2one | No | No | Yes | No | `branch_id.company_id` | — | res.company | related+stored |
| (none) | `active` | Boolean | No | No | Yes | No | No | True | — | |
| (none) | `street` | Char | No | No | Yes | No | No | — | — | |
| (none) | `city` | Char | No | No | Yes | No | No | — | — | |
| Buildings | `building_ids` | One2many | No | No | No | No | No | — | edara.building via `property_id` | |
| (building_count) | `building_count` | Integer | No | No | No | Yes | No | — | — | depends `building_ids` |
| (unit_count) | `unit_count` | Integer | No | No | No | Yes | No | — | — | depends `building_ids.unit_ids` |
| Ownership | `ownership_ids` | One2many | No | No | No | No | No | — | edara.ownership via `property_id` | |
| Analytic Account | `analytic_account_id` | Many2one | No | Yes | Yes | No | No | — | account.analytic.account | copy=False; lazily created by `get_analytic_account()` |
| Currency | `currency_id` | Many2one | No | No | No | No | `company_id.currency_id` | — | res.currency | |
| Total Revenue/Expenses/Net Operating Result/Total Outstanding | (same pattern as branch) | Monetary | No | No | No | Yes | No | — | — | scoped by `edara_property_id` |

**Form View** (`view_edara_property_form`): Ribbon "Archived". Smart buttons: **Buildings** (`action_view_buildings`, counter `building_count`, `fa-building`), **Units** (`action_view_units`, counter `unit_count`, `fa-home`), **Expenses** (`action_view_expenses`, plain stat, `fa-money`), **Invoices** (`action_view_invoices`, plain stat, `fa-file-text-o`). Title `name`. Group: left `code`, `branch_id`, `company_id` (groups=multi_company, readonly), `active` (invisible); right `street`, `city`. Notebook: **"Ownership"** tab — editable-bottom list of `ownership_ids` (columns: `owner_id`, `ownership_percentage`, `date_from`, `date_to`) — **this is the only UI for `edara.ownership` in the entire module**, no standalone menu/action/form exists for it. **"Buildings"** tab — read-only nested list (`name`, `code`, `floor_count`, `unit_count`). **"Financial Summary"** tab. Chatter present.

**List View** (`view_edara_property_list`): Name, Code, Branch, Buildings(`building_count`), Units(`unit_count`), City — all default widget, no optional columns, no decorations. No dedicated search view (`action_edara_property` has no `search_view_id`).

**Buttons/Actions:**

| UI Label | Method | Type | Precondition | What It Does |
|---|---|---|---|---|
| Buildings | `action_view_buildings` | object | none | Opens `action_edara_building`, domain `property_id=self.id` |
| Units | `action_view_units` | object | none | Opens `action_edara_unit`, domain `property_id=self.id` |
| Expenses | `action_view_expenses` | object | none | Opens **native** `account.action_move_in_invoice_type`, domain `edara_property_id=self.id`, context default `move_type=in_invoice` |
| Invoices | `action_view_invoices` | object | none | Opens **native** `account.action_move_out_invoice_type`, domain `edara_property_id=self.id`, context default `move_type=out_invoice` |
| `get_analytic_account()` | Python-only, no button | — | called internally | Lazily creates/returns the property's analytic account under `analytic_plan_edara_property` |

No state machine.

**Relationships:** `branch_id` (M2O); `building_ids` (O2M) → `edara.building.property_id`; `ownership_ids` (O2M) → `edara.ownership.property_id`; `analytic_account_id` (M2O, lazy) → `account.analytic.account`.

**Required for creation:** `name`, `code`, `branch_id`. **Optional but important:** `street`, `city`, ownership rows (business-critical for owner tracking but not enforced at create time).

**Gaps:** `edara.ownership` has no standalone menu/action/list/form (see §3.3) — a tester should not expect an "Ownership" menu anywhere; it's only reachable as the Property form's embedded tab.

---

### 3.3 edara.ownership

**Human name:** EDARA Property Ownership · **Inherits:** `mail.thread` · **Order:** `property_id, date_from desc`
**Purpose:** A time-boxed ownership-percentage record linking an owner (`res.partner`) to a property. No standalone menu — only reachable as the embedded, editable list in the Property form's "Ownership" tab (see §3.2).

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| Property | `property_id` | Many2one | Yes | No | Yes | No | No | — | edara.property | tracked, indexed |
| Branch | `branch_id` | Many2one | No | No | Yes | No | `property_id.branch_id` | — | edara.branch | related+stored, indexed |
| Company | `company_id` | Many2one | No | No | Yes | No | `property_id.company_id` | — | res.company | related+stored, indexed |
| Owner | `owner_id` | Many2one | Yes | No | Yes | No | No | — | res.partner | tracked, indexed |
| Ownership % | `ownership_percentage` | Float | Yes | No | Yes | No | No | — | — | tracked; must be `0 < x <= 100` |
| From | `date_from` | Date | Yes | No | Yes | No | No | today | — | tracked |
| To | `date_to` | Date | No | No | Yes | No | No | — | — | tracked; empty = open-ended (current) period; must be ≥ `date_from` |
| (active) | `active` | Boolean | No | No | Yes | No | No | True | — | |

**Constraints:** percentage range (0,100]; `date_to >= date_from`; and a sweep-line total-ownership check — for every property, at every boundary date (any record's `date_from`/`date_to`), the sum of `ownership_percentage` of all overlapping active records must not exceed 100% (raises `ValidationError` naming the property and the offending date).

**Views:** No standalone form/list/search/action exists — only the embedded editable-bottom list inside `view_edara_property_form`'s "Ownership" tab (columns: `owner_id`, `ownership_percentage`, `date_from`, `date_to`).

**Buttons/Actions:** none (no `action_*` methods on this model). **No state machine.**

**Relationships:** `property_id` (M2O) → `edara.property`; back-referenced from `res.partner.edara_ownership_ids` (see §3.13).

**Required for creation:** `property_id`, `owner_id`, `ownership_percentage`, `date_from` (defaults today). **Optional:** `date_to`.

**Gaps:** No standalone menu/action — cannot browse ownership globally across properties, filter by owner, or reach an ownership record's own form. (Confirmed: no `action_edara_ownership`/`view_edara_ownership_*` anywhere in the module.)

---

### 3.4 edara.building

**Human name:** EDARA Building · **Inherits:** `mail.thread` · **Order:** `name`

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| (none) | `name` | Char | Yes | No | Yes | No | No | — | — | tracked |
| (none) | `code` | Char | Yes | No | Yes | No | No | — | — | tracked; unique per property |
| Property | `property_id` | Many2one | Yes | No | Yes | No | No | — | edara.property | tracked, indexed |
| Branch | `branch_id` | Many2one | No | No | Yes | No | `property_id.branch_id` | — | edara.branch | related+stored |
| Company | `company_id` | Many2one | No | No | Yes | No | `property_id.company_id` | — | res.company | related+stored |
| (none) | `active` | Boolean | No | No | Yes | No | No | True | — | |
| (none) | `street` | Char | No | No | Yes | No | No | — | — | |
| Floors | `floor_count` | Integer | No | No | Yes | No | No | — | — | |
| Units | `unit_ids` | One2many | No | No | No | No | No | — | edara.unit via `building_id` | |
| (unit_count) | `unit_count` | Integer | No | No | No | Yes | No | — | — | depends `unit_ids` |
| Service Charges | `service_charge_ids` | One2many | No | No | No | No | No | — | edara.service.charge via `building_id` | |
| (service_charge_count) | `service_charge_count` | Integer | No | No | No | Yes | No | — | — | |
| (contract_count) | `contract_count` | Integer | No | No | No | Yes | No | — | — | via `edara.lease.contract._read_group` on related stored `building_id` |
| (maintenance_request_count) | `maintenance_request_count` | Integer | No | No | No | Yes | No | — | — | same pattern |

**Form View** (`view_edara_building_form`): Ribbon "Archived". Smart buttons (all four present, Contracts+Maintenance added in a prior Phase 15 audit): Units, Service Charges, Contracts, Maintenance. Title `name`. Group: left `code`, `property_id`, `branch_id`(readonly); right `street`, `floor_count`. No notebook. Chatter present.

**List View**: Name, Code, Property, Branch(`groups=base.group_no_one` — debug-only), Floors, Units. No search view; no decorations.

**Buttons/Actions:** Units→`action_view_units`; Service Charges→`action_view_service_charges`; Contracts→`action_view_contracts`; Maintenance→`action_view_maintenance_requests`. All domain-filter to `building_id=self.id`. No state machine.

**Relationships:** `property_id` (M2O); `unit_ids` (O2M) → `edara.unit.building_id`; `service_charge_ids` (O2M). Contracts/Maintenance counted transitively through units, not a direct O2M.

**Required for creation:** `name`, `code`, `property_id`. **Optional:** `street`, `floor_count`.

**Gaps:** None found.

---

### 3.5 edara.unit

**Human name:** EDARA Unit · **Inherits:** `mail.thread` · **Order:** `building_id, floor, name`

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| (none) | `name` | Char | Yes | No | Yes | No | No | — | — | "e.g. A-101"; tracked |
| (none) | `code` | Char | Yes | No | Yes | No | No | — | — | tracked; unique per building |
| Building | `building_id` | Many2one | Yes | No | Yes | No | No | — | edara.building | tracked, indexed |
| Property | `property_id` | Many2one | No | No | Yes | No | `building_id.property_id` | — | edara.property | related+stored |
| Branch | `branch_id` | Many2one | No | No | Yes | No | `building_id.branch_id` | — | edara.branch | related+stored |
| Company | `company_id` | Many2one | No | No | Yes | No | `building_id.company_id` | — | res.company | related+stored |
| (none) | `active` | Boolean | No | No | Yes | No | No | True | — | |
| Floor | `floor` | Char | No | No | Yes | No | No | — | — | drives kanban grouping/search |
| Unit Number | `unit_number` | Char | No | No | Yes | No | No | — | — | separate identifier from name/code |
| Type | `unit_type` | Selection | Yes | No | Yes | No | No | `apartment` | see below | tracked |
| Area (sqm) | `area` | Float | No | No | Yes | No | No | — | — | |
| Bedrooms | `bedrooms` | Integer | No | No | Yes | No | No | — | — | |
| Bathrooms | `bathrooms` | Integer | No | No | Yes | No | No | — | — | |
| Default Rent | `rent_amount_default` | Monetary | No | No | Yes | No | No | — | — | currency_field=`currency_id` |
| Currency | `currency_id` | Many2one | No | No | Yes | No | No (independent, NOT related) | `env.company.currency_id` | res.currency | fixed at unit-creation time; does not follow building/property/company like the other `*_id` fields |
| Occupancy | `occupancy_status` | Selection | Yes | No | Yes | No | No | `available` | see below | tracked; "Rented" only settable via an active lease contract (constraint-enforced) |
| Operational State | `operational_status` | Selection | Yes | No | Yes | No | No | `normal` | see below | tracked |
| Lease Contracts | `lease_contract_ids` | One2many | No | No | No | No | No | — | edara.lease.contract via `unit_id` | |
| (contract_count) | `contract_count` | Integer | No | No | No | Yes | No | — | — | |
| Maintenance Requests | `maintenance_request_ids` | One2many | No | No | No | No | No | — | edara.maintenance.request via `unit_id` | |
| (maintenance_request_count) | `maintenance_request_count` | Integer | No | No | No | Yes | No | — | — | |

**Selection — `unit_type`:** Apartment, Office, Shop, Warehouse, Villa, Parking, Commercial Space, Other.
**Selection — `occupancy_status`:** Available, Reserved, Rented, Owner Occupied, Sold.
**Selection — `operational_status`:** Normal, Under Maintenance.

**Constraints:** `_check_status_consistency` — cannot be `operational_status=under_maintenance` while `occupancy_status=available` simultaneously. `_check_occupancy_status_derivation` — `occupancy_status=rented` only valid if an active `edara.lease.contract` exists for the unit (blocks direct manual edit to "Rented").

**Form View** (`view_edara_unit_form`): Ribbon "Archived". Smart buttons: Contracts (`contract_count`), Maintenance (`maintenance_request_count`). Title `name`. Group 1 left: `code`, `building_id`, `property_id`(readonly, `base.group_no_one`), `branch_id`(readonly, `base.group_no_one`), `active`(invisible), `unit_type`, `floor`, `unit_number`. Group 1 right: `area`, `bedrooms`, `bathrooms`, `rent_amount_default`, `currency_id`(`base.group_multi_currency`). Group 2: `occupancy_status` | `operational_status`. No notebook. Chatter present.

**List View** (`view_edara_unit_list`): Name, Building, Property(`base.group_no_one`), Type, Floor, Area, Default Rent, currency(column_invisible), Occupancy, Operational State. **Decorations:** `decoration-success` when available, `decoration-danger` when rented, `decoration-warning` when reserved, `decoration-muted` when under_maintenance.

**Kanban View** (`view_edara_unit_kanban`): `default_group_by="floor"`, class `o_kanban_small_column` (floor-grid per spec §48). Card `t-name="card"`: colored div — `bg-warning` under_maintenance, else `bg-danger` rented, else `bg-success` available, else `bg-secondary` (reserved/owner_occupied/sold); shows `name`(bold) + `occupancy_status`(small).

**Search View** (`view_edara_unit_search`): Search fields `name`, `building_id`, `floor`. Filters: Available, Rented, Under Maintenance. Group By: Building, Floor, Occupancy.

**Action** `action_edara_unit`: `view_mode="kanban,list,form"`, `search_view_id` pinned.

**Buttons/Actions:** Contracts→`action_view_contracts` (domain `unit_id=self.id`); Maintenance→`action_view_maintenance_requests` (domain `unit_id=self.id`). No direct state-transition buttons on the unit itself — occupancy/operational status are set as constrained plain fields, or driven indirectly by contract actions (§3.6) and maintenance actions (§3.11).

**Relationships:** `building_id` (M2O); `lease_contract_ids`/`maintenance_request_ids` (O2M, inverse FKs).

**Required for creation:** `name`, `code`, `building_id`, `unit_type`(defaults apartment), `occupancy_status`(defaults available), `operational_status`(defaults normal). **Optional but important:** `area`, `bedrooms`, `bathrooms`, `rent_amount_default`, `floor` (needed for kanban grouping), `unit_number`.

**Gaps:**
- `currency_id` is an independent stored field (defaults to company currency at creation time) rather than related like the other hierarchy fields — a unit's currency will NOT follow its company if the company's currency later changes.
- `unit_number`, `code`, `name` are three separate free-text identifiers with no cross-validation between them; only `code` has a uniqueness constraint (per building).

---

### 3.6 edara.lease.contract

**Human name:** EDARA Lease Contract · **Inherits:** `mail.thread`, `mail.activity.mixin` · **Order:** `start_date desc, id desc`
**Purpose:** The rental agreement between a tenant and a unit; drives payment-schedule generation, unit occupancy status, and renewal/termination lifecycle.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| (sequence-based) | `name` | Char | Yes | Yes (view) | Yes | No | No | `_('New')`, replaced by sequence `edara.lease.contract` (`LC/%(year)s/`, pad 4) | — | Contract reference, e.g. "LC/2026/0001" |
| Company | `company_id` | Many2one | — | — | Yes | Yes | `unit_id.company_id` | — | res.company | |
| Branch | `branch_id` | Many2one | — | — | Yes | Yes | `unit_id.branch_id` | — | edara.branch | |
| Property | `property_id` | Many2one | — | — | Yes | Yes | `unit_id.property_id` | — | edara.property | |
| Building | `building_id` | Many2one | — | — | Yes | Yes | `unit_id.building_id` | — | edara.building | |
| Unit | `unit_id` | Many2one | Yes | `state != draft` (view) | Yes | No | No | — | edara.unit | tracked |
| Tenant | `tenant_id` | Many2one | Yes | `state != draft` (view) | Yes | No | No | — | res.partner | tracked |
| Start Date | `start_date` | Date | Yes | `state != draft` (view) | Yes | No | No | — | — | tracked |
| End Date | `end_date` | Date | Yes | `state not in (draft,active)` (view) | Yes | No | No | — | — | tracked, must be after start_date |
| Currency | `currency_id` | Many2one | Yes | — | Yes | No | No | `env.company.currency_id` | res.currency | shown only under multi_currency; own field, NOT related — a contract can hold a currency different from the company's |
| Rent | `rent_amount` | Monetary | Yes | — | Yes | No | No | — | — | must be > 0, tracked |
| Billing Frequency | `billing_frequency` | Selection | Yes | — | Yes | No | No | `monthly` | monthly/quarterly/yearly | tracked; drives schedule spacing |
| Payment Day of Month | `payment_day` | Integer | No | — | Yes | No | No | 1 | — | 1–28 only |
| Deposit Required | `deposit_required` | Boolean | No | — | Yes | No | No | True | — | |
| Deposit Amount | `deposit_amount` | Monetary | No | — | Yes | No | No | — | — | shown only if deposit_required |
| Status | `state` | Selection | Yes | — | Yes | No | No | `draft` | draft/active/renewed/terminated/expired | tracked, copy=False |
| Termination Date | `termination_date` | Date | No | Yes | Yes | No | No | — | — | copy=False, tracked |
| Termination Reason | `termination_reason` | Text | No | Yes | Yes | No | No | — | — | copy=False |
| Renewed From | `predecessor_contract_id` | Many2one | No | Yes | Yes | No | No | — | edara.lease.contract | copy=False |
| Renewed Into | `successor_contract_id` | Many2one | No | Yes | Yes | No | No | — | edara.lease.contract | copy=False |
| Notes | `notes` | Text | No | — | Yes | No | No | — | — | |
| Payment Schedule | `schedule_line_ids` | One2many | No | — | Yes | No | No | — | edara.payment.schedule.line (inverse `contract_id`) | |
| (schedule_line_count) | `schedule_line_count` | Integer | No | Yes | No | Yes | No | — | — | via `_read_group` |
| Renewal Requests | `renewal_request_ids` | One2many | No | — | Yes | No | No | — | edara.renewal.request (inverse `contract_id`) | |
| (renewal_request_count) | `renewal_request_count` | Integer | No | Yes | No | Yes | No | — | — | |

**Form View** (`view_edara_lease_contract_form`): **Header:** `Activate` (object, btn-primary, visible only `state==draft`), `Renew` (action → wizard, visible only `state==active`), `Terminate` (object, `confirm=` prompt, visible only `state==active`). Statusbar `state`, `statusbar_visible="draft,active,terminated"` — **`renewed` and `expired` are reachable states NOT listed in `statusbar_visible`** (see Gaps).

**Smart buttons:** Schedule (`action_view_schedule_lines`, counter `schedule_line_count`, `fa-calendar`). Deposit (`action_view_deposit`, static, `fa-shield`, visible only if `deposit_required` — **clicking it creates an `edara.deposit` if none exists yet**, a create-as-side-effect button, not pure navigation). Renewals (`action_view_renewal_requests`, counter `renewal_request_count`, `fa-refresh`).

**Title:** `name` (readonly). **Main group:** left `unit_id`, `tenant_id`, `branch_id`/`property_id`/`building_id` (readonly, `base.group_no_one`); right `start_date`, `end_date`, `rent_amount`, `currency_id`(multi_currency), `billing_frequency`, `payment_day`. **Second group:** "Deposit" (`deposit_required`, `deposit_amount` invisible unless required); "Renewal / Termination" (whole group invisible unless predecessor/successor set or terminated — `predecessor_contract_id`, `successor_contract_id`, `termination_date`, `termination_reason`, all readonly). **Notebook:** "Notes" tab (`notes`). **Chatter:** present, with tracked fields (unit_id, tenant_id, start_date, end_date, rent_amount, billing_frequency, state, termination_date).

**List View** (`view_edara_lease_contract_list`): name, Tenant, Unit, Start Date, End Date, Rent(monetary), currency(column_invisible), Status(badge). Decorations: `decoration-success` active, `decoration-muted` terminated/expired/renewed. No `<list>`-level order override (model `_order='start_date desc, id desc'`).

**Search View:** **None defined.** No custom filters/group-bys — bare auto-generated search box only.

**Buttons/Actions**

| UI Label | Method/Action | Type | Precondition | What It Does | Result |
|---|---|---|---|---|---|
| Activate | `action_activate` | object, header | `state==draft`; unit not sold; unit not under_maintenance | Sets unit occupied, generates schedule lines | draft → active |
| Renew | `%(action_edara_lease_renewal_wizard)d` | action, opens wizard (target=new) | `state==active` | Opens the wizard (§3.9) | wizard confirms → `action_renew` |
| Terminate | `action_terminate` | object, header, `confirm=` | `state==active` | Sets termination_date=today, frees unit, deletes uninvoiced future schedule lines (`due_date>termination_date`) | active → terminated |
| Schedule (smart btn) | `action_view_schedule_lines` | object | always | Opens Payment Schedule filtered to contract | navigation |
| Deposit (smart btn) | `action_view_deposit` | object | `deposit_required` | Find-or-create `edara.deposit`, opens its form | may CREATE a deposit |
| Renewals (smart btn) | `action_view_renewal_requests` | object | always | Opens Renewal Requests filtered to contract | navigation |

`action_renew(new_start, new_end, new_rent)` (Python-only, called by the wizard AND by `edara.renewal.request.action_approve` — not a directly-clickable button of its own): requires `state==active`; creates a successor contract copying unit/tenant/currency/billing_frequency/payment_day/deposit settings with `predecessor_contract_id=self.id`; sets predecessor `state=renewed`, `successor_contract_id`; calls `new_contract.action_activate()` — unit stays continuously "rented", no gap.

**State Machine**

| Current State | Action | New State | Side Effects |
|---|---|---|---|
| draft | `action_activate` | active | Unit → rented; `_generate_schedule_lines()` creates lines start→end per frequency/payment_day; blocked if unit sold or under_maintenance |
| active | `action_terminate(reason)` | terminated | termination_date=today, reason set; unit → available; uninvoiced future lines deleted |
| active | `action_renew(...)` (wizard or approved renewal request) | renewed (this contract); new contract created active | Successor created+activated; unit stays rented |
| active, past end_date | `_cron_expire_contracts()` (daily) | expired | Only contracts still active with `end_date<today`; unit → available; **all** uninvoiced lines unlinked; idempotent |
| draft | `unlink()` | (deleted) | Only draft contracts deletable; all other states → `UserError` |

Also: `_check_no_overlap` blocks two active contracts on the same unit with overlapping dates.

**Relationships:** Branch→Property→Building→Unit→**Contract** (all related+stored on contract). Contract→`schedule_line_ids` (cascade). Contract→`renewal_request_ids`. Contract↔`edara.deposit` (not a stored field — looked up on demand). Self-referencing predecessor/successor chain (no ondelete override, defaults `set null`). `edara.renewal.request.contract_id` → contract, `ondelete=restrict`.

**Required for creation:** `unit_id`, `tenant_id`, `start_date`, `end_date`(after start), `rent_amount`(>0), `currency_id`(defaults company), `billing_frequency`(defaults monthly), `payment_day`(defaults 1). **Optional but important:** `deposit_required`+`deposit_amount`, `notes`. **System-set:** `name`, `state`, company/branch/property/building (derived from unit).

**Gaps:**
1. Statusbar missing `renewed`/`expired` in `statusbar_visible` even though both are reachable states.
2. No search view — no "My Contracts"/"Expiring Soon" filters or group-bys.
3. "Deposit" smart button is create-as-side-effect, not pure navigation (idempotent via find-or-create, but worth an explicit test that double-clicking doesn't duplicate).

---

### 3.7 edara.payment.schedule.line

**Human name:** EDARA Payment Schedule Line · No mail.thread/chatter · **Order:** `due_date, id`
**Purpose:** One rent-due installment for a contract; the link between a contract's billing periods and the `account.move` invoice each period produces.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| Contract | `contract_id` | Many2one | Yes | Yes (form) | Yes | No | No | — | edara.lease.contract, `ondelete=cascade` | |
| Tenant | `tenant_id` | Many2one | — | — | Yes | No | `contract_id.tenant_id` | — | res.partner | |
| Unit | `unit_id` | Many2one | — | — | Yes | No | `contract_id.unit_id` | — | edara.unit | |
| Property | `property_id` | Many2one | — | — | Yes | No | `contract_id.property_id` | — | edara.property | |
| Building | `building_id` | Many2one | — | — | Yes | No | `contract_id.building_id` | — | edara.building | |
| Branch | `branch_id` | Many2one | — | — | Yes | No | `contract_id.branch_id` | — | edara.branch | |
| Company | `company_id` | Many2one | — | — | Yes | No | `contract_id.company_id` | — | res.company | |
| Currency | `currency_id` | Many2one | — | — | Yes | No | `contract_id.currency_id` | — | res.currency | |
| (ordering) | `sequence` | Integer | — | — | Yes | No | No | 10 | — | drag-handle |
| Due Date | `due_date` | Date | Yes | editable in list | Yes | No | No | — | — | indexed |
| Amount | `amount` | Monetary | Yes | — | Yes | No | No | — | — | currency_field=currency_id |
| Description | `description` | Char | — | — | Yes | No | No | — | — | |
| Invoice | `invoice_id` | Many2one | — | Yes (form; **NOT readonly in list — see Gaps**) | Yes | No | No | — | account.move | copy=False; unique (1 line : 1 invoice) |
| Status | `state` | Selection | — | (fully computed) | Yes | Yes | No | — | draft/invoiced/partial/paid/overdue/cancelled | see logic below |

**`state` computation** (`@api.depends('invoice_id.payment_state','invoice_id.state','due_date')`): no invoice → `overdue` if past due else `draft`. Invoice cancelled → `cancelled`. Otherwise mapped from `invoice.payment_state`: `not_paid`/`blocked`/`invoicing_legacy`→`invoiced`; `in_payment`/`paid`→`paid`; `partial`→`partial`; `reversed`→`cancelled`; and if mapped=`invoiced` but past due → escalated to `overdue`.

**Form View** (`view_edara_payment_schedule_line_form`): Header button **Charge Late Fee** (object, btn-secondary, visible only `state==overdue`, `confirm=` prompt). No statusbar widget (state shown as a plain badge field). Body: `contract_id`(readonly), `due_date`, `amount`, `currency_id`(invisible), `description`, `invoice_id`(readonly), `state`(badge). No chatter.

**List View** (`view_edara_payment_schedule_line_list`): `editable="bottom"`, `create="0"` (no manual row creation — lines are only ever produced by `_generate_schedule_lines()`). Columns: sequence(handle), contract_id(column_invisible), Due Date(editable), Description(editable), Amount(editable, monetary), currency(column_invisible), Invoice(**editable — see Gaps**), Status(badge). Decorations: `decoration-danger` overdue, `decoration-success` paid.

**Search View:** None defined.

**Buttons/Actions**

| UI Label | Method | Model | Type | Precondition | What It Does | Result |
|---|---|---|---|---|---|---|
| Charge Late Fee | `action_charge_late_fee` | edara.payment.schedule.line | object | `state==overdue`; company must have `edara_late_fee_income_account_id` AND `edara_late_fee_amount` configured | Creates+posts a **separate** `out_invoice` (`edara_invoice_type='late_fee'`) for the flat configured amount, tagged to contract/unit/building/property/branch, analytic-distributed 100% to the property's analytic account | New posted invoice; does NOT touch the original line's `invoice_id`/state |
| (no button) | `_create_invoice()` | edara.payment.schedule.line | Python-only, called by cron/manually | `invoice_id` empty; company must have `edara_rental_income_account_id` | Creates+posts an `out_invoice` (`edara_invoice_type='rent'`), sets `self.invoice_id` | `state` becomes invoiced/overdue |

**State Machine** (fully computed, never directly written):

| Current State | Trigger | New State |
|---|---|---|
| draft | `due_date` passes, no invoice | overdue |
| draft/overdue | `_cron_generate_due_invoices()` creates+posts invoice | invoiced (or overdue if already past due) |
| invoiced | invoice `payment_state`→partial | partial |
| invoiced/partial | invoice `payment_state`→paid/in_payment | paid |
| invoiced/partial/paid | invoice cancelled or `payment_state`→reversed | cancelled |
| invoiced (unpaid), `due_date<today` | time passes | overdue |

**Relationships:** `contract_id`→contract, `ondelete=cascade`. `invoice_id`→`account.move`, unique 1:1. `unlink()` override: **any line with `invoice_id` set cannot be deleted** (`UserError`) — preserves audit trail; uninvoiced lines remain freely deletable.

**Required for creation (programmatic only — see Gaps):** `contract_id`, `due_date`, `amount`; `sequence`/`description` optional.

**Gaps:**
1. **Payment Schedule list is `editable="bottom"` and does NOT mark `invoice_id` readonly at the list-column level** (only the form marks it readonly) — a user could inline-edit which invoice a schedule line points to directly from the list, bypassing the system-managed `_create_invoice()` linkage. Worth a manual data-integrity test.

---

### 3.8 edara.renewal.request

**Human name:** EDARA Lease Renewal Request · **Inherits:** `mail.thread` · **Order:** `id desc`
**Purpose:** A tenant- (portal) or staff-initiated request to renew an active contract, subject to staff approval; approval delegates into `edara.lease.contract.action_renew`.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| Contract | `contract_id` | Many2one | Yes | `state != submitted` (view) | Yes | No | No | — | edara.lease.contract, `ondelete=restrict` | |
| Tenant | `tenant_id` | Many2one | — | Yes (view) | Yes | No | `contract_id.tenant_id` | — | res.partner | |
| Unit | `unit_id` | Many2one | — | Yes (view) | Yes | No | `contract_id.unit_id` | — | edara.unit | |
| Branch | `branch_id` | Many2one | — | — | Yes | No | `contract_id.branch_id` | — | edara.branch | not shown on form |
| Company | `company_id` | Many2one | — | — | Yes | No | `contract_id.company_id` | — | res.company | not shown on form |
| Currency | `currency_id` | Many2one | — | Yes (invisible) | Yes | No | `contract_id.currency_id` | — | res.currency | |
| Requested Start Date | `requested_start_date` | Date | Yes | `state != submitted` | Yes | No | No | — | — | before end date |
| Requested End Date | `requested_end_date` | Date | Yes | `state != submitted` | Yes | No | No | — | — | |
| Requested Rent | `requested_rent_amount` | Monetary | Yes | `state != submitted` | Yes | No | No | — | — | currency_field=currency_id |
| Tenant Message | `note` | Text | — | Yes (view) | Yes | No | No | — | — | requester's free text |
| Status | `state` | Selection | Yes | — | Yes | No | No | `submitted` | submitted/approved/rejected | tracked, copy=False |
| Decision Note | `decision_note` | Text | — | invisible when submitted | Yes | No | No | — | — | copy=False; **not settable from the UI Reject button** (see Gaps) |
| New Contract | `new_contract_id` | Many2one | — | Yes | Yes | No | No | — | edara.lease.contract | copy=False; set by `action_approve` |

**Form View** (`view_edara_renewal_request_form`): Header: `Approve`(object, btn-primary, visible only submitted), `Reject`(object, visible only submitted, `confirm=`). Statusbar `state`, `statusbar_visible="submitted,approved,rejected"` (complete — covers all 3 states, unlike the contract's). Body: left `contract_id`/`tenant_id`/`unit_id` (readonly once not submitted); right `currency_id`(invisible), `requested_start_date`/`requested_end_date`/`requested_rent_amount` (readonly once not submitted). Second group: `note`(readonly), `decision_note`(invisible while submitted, editable otherwise), `new_contract_id`(readonly, invisible unless set). Chatter present.

**List View:** Contract, Tenant, Requested Start/End, Requested Rent(monetary), currency(column_invisible), Status(badge). Decorations: `decoration-info` submitted, `decoration-muted` rejected, `decoration-success` approved.

**Kanban View** (`view_edara_renewal_request_kanban`): `default_group_by="state"`, `o_kanban_small_column`. Card: contract_id(bold), tenant_id(muted), requested date range. No color-coding beyond column grouping. Action's `view_mode="kanban,list,form"` — kanban is the default landing view.

**Search View:** None defined.

**Buttons/Actions**

| UI Label | Method | Type | Precondition | What It Does | Result |
|---|---|---|---|---|---|
| Approve | `action_approve` | object | `state==submitted` | Calls `contract_id.action_renew(...)`, sets `new_contract_id` | submitted→approved; successor contract created+activated |
| Reject | `action_reject` | object, `confirm=` | `state==submitted` | Sets state; **`reason` param defaults to None since a plain button click can't pass an argument** | submitted→rejected, `decision_note` left empty |

**State Machine**

| Current State | Action | New State | Side Effects |
|---|---|---|---|
| submitted | `action_approve` | approved | Delegates to `action_renew`; new contract created+activated |
| submitted | `action_reject(reason)` | rejected | `decision_note` set if reason provided (UI button passes none) |

Constraints: only one **submitted** request per contract at a time; a request can only be submitted while its contract is active; end date after start date.

**Relationships:** `contract_id`→contract (`ondelete=restrict` — a contract can never be deleted while it has ANY renewal request, submitted/approved/rejected). `new_contract_id`→contract (no ondelete override). Reachable from the contract's "Renewals" smart button and from the tenant portal.

**Required for creation:** `contract_id`, `requested_start_date`, `requested_end_date`(after start), `requested_rent_amount`. **Optional:** `note`. **System-set:** `state`, `tenant_id`/`unit_id`/`branch_id`/`company_id`/`currency_id` (related from contract).

**Gaps:**
1. Reject button cannot capture a reason from the UI in one step (Python supports `reason` but no form control passes it) — `decision_note` is separately editable after rejection as a two-step workaround.
2. No search view.

---

### 3.9 edara.lease.renewal.wizard (TransientModel)

**Human name:** Renew Lease Contract · No chatter.
**Purpose:** Staff-facing quick-renew dialog opened from the contract form's "Renew" header button.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Default | Relation | Help |
|---|---|---|---|---|---|---|---|
| Contract | `contract_id` | Many2one | Yes | invisible on form | via `default_get`, from `active_id` context | edara.lease.contract | |
| New Start Date | `new_start_date` | Date | Yes | — | via `default_get`: `contract.end_date + 1 day` | — | |
| New End Date | `new_end_date` | Date | Yes | — | (none — user fills) | — | |
| New Rent | `new_rent_amount` | Monetary | Yes | — | via `default_get`: `contract.rent_amount` | — | currency_field=currency_id |
| Currency | `currency_id` | Many2one | — | — | related `contract_id.currency_id` | res.currency | |

**Form View** (target=new dialog): `contract_id`(invisible), `currency_id`(invisible), `new_start_date`, `new_end_date`, `new_rent_amount`. Footer: **Renew** (object `action_confirm`, btn-primary), **Cancel** (special=cancel).

**Buttons/Actions:** Renew → calls `contract_id.action_renew(new_start_date, new_end_date, new_rent_amount)`, returns an act_window opening the **new** contract's form directly.

**Required:** `new_start_date`, `new_end_date`, `new_rent_amount` (pre-filled with defaults but still required/editable).

---

### 3.10 edara.deposit

**Human name:** EDARA Security Deposit · No mail.thread/chatter · **Order:** `id desc`
**Purpose:** One deposit record per lease contract (1:1, DB-constrained), tracking held/refunded/deducted amounts derived entirely from its transaction ledger.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| Contract | `contract_id` | Many2one | Yes | No (form-readonly via view) | Yes | No | No | — | edara.lease.contract, `ondelete=restrict` | |
| Tenant | `tenant_id` | Many2one | No | related | Yes | No | `contract_id.tenant_id` | — | res.partner | |
| Unit | `unit_id` | Many2one | No | related | Yes | No | `contract_id.unit_id` | — | edara.unit | |
| Property | `property_id` | Many2one | No | related | Yes | No | `contract_id.property_id` | — | edara.property | **not shown on form** |
| Building | `building_id` | Many2one | No | related | Yes | No | `contract_id.building_id` | — | edara.building | **not shown on form** |
| Branch | `branch_id` | Many2one | No | related | Yes (indexed) | No | `contract_id.branch_id` | — | edara.branch | **not shown on form**; used for record-rule scoping |
| Company | `company_id` | Many2one | No | related | Yes (indexed) | No | `contract_id.company_id` | — | res.company | **not shown on form** |
| Currency | `currency_id` | Many2one | No | related | Yes | No | `contract_id.currency_id` | — | res.currency | |
| Deposit Amount | `amount` | Monetary | Yes | No (editable) | Yes | No | No | — | — | agreed/target amount |
| Transactions | `transaction_ids` | One2many | No | readonly in view | — | No | inverse `deposit_id` | — | edara.deposit.transaction | full ledger |
| Amount Held | `amount_held` | Monetary | No | Yes | Yes | Yes | No | — | — | sum of `held` transactions |
| Amount Refunded | `amount_refunded` | Monetary | No | Yes | Yes | Yes | No | — | — | sum of `refund` transactions |
| Amount Deducted | `amount_deducted` | Monetary | No | Yes | Yes | Yes | No | — | — | sum of `deduction` transactions |
| Balance | `balance` | Monetary | No | Yes | Yes | Yes | No | — | — | held − refunded − deducted |
| State | `state` | Selection | No | Yes | Yes | Yes | No | — | see below | derived, never set manually |

**Selection — `state`:** `draft`("Not Collected", held≤0), `held`("Held", held>0 and balance>0), `closed`("Closed", held>0 and balance≤0). Compute depends `transaction_ids.transaction_type`, `transaction_ids.amount`.

**Constraint:** `_contract_uniq` — unique(contract_id).

**Form View** (`view_edara_deposit_form`): **Header:** "Collect Deposit"(action→wizard, `default_transaction_type=held`, btn-primary, `invisible="balance>=amount"`), "Refund"(same wizard, `default_transaction_type=refund`, `invisible="balance<=0"`), "Deduct"(same wizard, `default_transaction_type=deduction`, `invisible="balance<=0"`). `state` statusbar, `statusbar_visible="draft,held,closed"`. Title: `contract_id`(readonly). Main groups: left `tenant_id`(readonly), `unit_id`(readonly); right `currency_id`(invisible), `amount`(editable), `amount_held`/`amount_refunded`/`amount_deducted`/`balance`(all readonly). Notebook: "Transactions" tab — embedded readonly list of `transaction_ids` (columns: date, transaction_type(badge), amount, currency(column_invisible), payment_id, move_id, description). No smart buttons. No chatter.

**List View:** Contract, Tenant, Amount, Balance, currency(column_invisible), State(badge). No `default_order` override (model `id desc`).

**Search View:** **None defined.**

**Buttons/Actions**

| UI Label | Method | Precondition | What It Does |
|---|---|---|---|
| Collect Deposit → wizard | `action_collect(journal_id, amount=None)` | amount defaults to `amount-amount_held`; `UserError` if resulting ≤0 | Creates+posts an inbound `account.payment` (customer) via `_create_deposit_payment`, creates a `held` transaction |
| Refund → wizard | `action_refund(journal_id, amount=None)` | amount defaults to `balance`; `UserError` if ≤0 or >balance | Creates+posts an outbound `account.payment`, creates a `refund` transaction |
| Deduct → wizard | `action_deduct(amount, description)` | amount >0 and ≤balance; requires `edara_deposit_liability_account_id` AND `edara_deposit_deduction_income_account_id` configured | Creates+posts an `account.move` (`move_type=entry`) debiting liability/crediting deduction-income, creates a `deduction` transaction |

**State Machine**

| Current State | Trigger | New State | Side Effects |
|---|---|---|---|
| draft (held=0) | `action_collect` | held (if balance>0) | `account.payment` posted |
| held | `action_refund` (full) | closed | outbound `account.payment` posted |
| held | `action_deduct` (full) | closed | `account.move` journal entry posted |
| held | partial refund/deduct | held (unchanged) | same accounting, balance reduced |

**Accounting detail:** Collect/Refund route through `_create_deposit_payment('inbound'/'outbound', ...)` → `account.payment` with `edara_is_security_deposit=True` (custom field, §3.15), which forces `destination_account_id = company.edara_deposit_liability_account_id` via an override of `_compute_destination_account_id`; blocked with `UserError` if that account isn't configured. Deduct creates a raw journal `entry` (not an invoice), two lines: debit liability / credit `edara_deposit_deduction_income_account_id`, both tagged `partner_id=tenant_id`, posted immediately; blocked if either account missing. **No credit note/reversal action exists for a deduction** — not reversible from this UI. **No analytic distribution** on the deduction entry (unlike service-charge/late-fee invoices).

**Relationships:** contract(1)→deposit(0..1), DB-unique. deposit(1)→transaction(0..n), `ondelete=restrict` on the transaction side. Accessed via `edara.lease.contract.action_view_deposit()` (get-or-create smart button).

**Required for creation:** `contract_id`, `amount` (in practice created lazily via the contract's smart button, though nothing blocks manual "New" from the Security Deposits list).

**Gaps:**
1. **Help text mismatch**: `action_edara_deposit`'s empty-state help says deposits are "created automatically when a lease contract with 'Deposit Required' is activated" — **not true**; `action_activate()` contains no deposit-creation logic. A deposit only exists once the contract's Deposit smart button is clicked at least once.
2. No search/filter/group-by view.
3. No reversal/correction action for a deduction.
4. Deduction journal entry has no analytic distribution (inconsistent with service-charge/late-fee invoices).
5. `branch_id`/`property_id`/`building_id` are related+stored (used for record-rule scoping) but **not shown anywhere in the deposit form** — only `tenant_id`/`unit_id` are visible.

---

### 3.11 edara.deposit.transaction

**Human name:** EDARA Deposit Transaction · No mail.thread, no standalone form/list/menu · **Order:** `id desc`
**Purpose:** Append-only ledger line for one deposit event, always pointing to the real `account.payment` or `account.move` — explicitly "never a parallel ledger" per the code's own comment.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|
| Deposit | `deposit_id` | Many2one | Yes | No | Yes (indexed) | No | — | edara.deposit, `ondelete=restrict` | Parent deposit |
| Contract | `contract_id` | Many2one | No | related | Yes (indexed) | `deposit_id.contract_id` | — | edara.lease.contract | |
| Branch | `branch_id` | Many2one | No | related | Yes (indexed) | `deposit_id.branch_id` | — | edara.branch | record-rule scoping |
| Company | `company_id` | Many2one | No | related | Yes (indexed) | `deposit_id.company_id` | — | res.company | |
| Currency | `currency_id` | Many2one | No | related | Yes | `deposit_id.currency_id` | — | res.currency | |
| Type | `transaction_type` | Selection | Yes | No | Yes | No | — | held/refund/deduction | |
| Amount | `amount` | Monetary | Yes | No | Yes | No | — | — | always positive; sign/effect implied by type |
| Date | `date` | Date | No | No | Yes | No | today | — | |
| Description | `description` | Char | No | No | Yes | No | — | — | required by the wizard only for deductions |
| Payment | `payment_id` | Many2one | No | Yes | Yes | No | — | account.payment | set for held/refund |
| Journal Entry | `move_id` | Many2one | No | Yes | Yes | No | — | account.move | set for deduction |

**Selection — `transaction_type`:** `held`("Held"), `refund`("Refund"), `deduction`("Deduction").

**Views:** No standalone form/list/search/action — only ever rendered embedded (readonly) inside `edara.deposit`'s "Transactions" tab. No standalone menu to browse transactions across deposits.

**Buttons/Actions:** None. Sole behavioral override: `unlink()` **always raises** `UserError("Deposit transactions are part of the financial audit trail and cannot be deleted.")` — records can never be deleted by any user regardless of group.

**Relationships:** deposit(1)→transaction(0..n). Each transaction points to exactly one of `payment_id`/`move_id`, matching its type.

**Required for creation (programmatic only):** `deposit_id`, `transaction_type`, `amount`.

**Gaps:** No dedicated cross-deposit audit list/menu — only reachable per-deposit.

---

### 3.12 edara.deposit.transaction.wizard (TransientModel)

**Human name:** Record Deposit Transaction
**Purpose:** Single-purpose wizard collecting amount/journal/reason for whichever of collect/refund/deduct was requested, then delegates to the corresponding `edara.deposit` method.

**Fields**

| Field Label | Technical Name | Type | Required | Default | Relation | Help |
|---|---|---|---|---|---|---|
| (Deposit) | `deposit_id` | Many2one | Yes | `context.get('active_id')` | edara.deposit | hidden (`invisible=1`) |
| (Company) | `company_id` | Many2one | No | related `deposit_id.company_id` | res.company | hidden, scopes `journal_id`'s domain |
| (Currency) | `currency_id` | Many2one | No | related `deposit_id.currency_id` | res.currency | hidden |
| Transaction Type | `transaction_type` | Selection | Yes | `context.get('default_transaction_type','held')` | held/refund/deduction | hidden — set entirely by which header button opened the wizard |
| Amount | `amount` | Monetary | Yes | — | — | |
| Payment Journal | `journal_id` | Many2one | Conditional | — | account.journal, domain `type in (cash,bank), company_id=company_id` | required/shown only for held/refund |
| Reason | `description` | Char | Conditional | — | — | required/shown only for deduction |

**Form View** (target=new dialog): hidden technical fields all `invisible=1`; visible: `amount`(always), `journal_id`(`invisible/required` tied to `transaction_type != 'deduction'`), `description`(tied to `transaction_type == 'deduction'`). Footer: **Confirm** (object `action_confirm`, btn-primary), **Cancel** (special=cancel). No chatter.

**Action:** `action_edara_deposit_transaction_wizard` — not bound to any menu, only reachable via the three header buttons on the deposit form.

**Buttons/Actions:** Confirm — dispatches to `deposit_id.action_collect/action_refund/action_deduct` per `transaction_type`, enforcing `journal_id` (held/refund) or `description` (deduction) required with `UserError` if missing; closes the dialog on success.

**Required:** `amount` always; `journal_id` for held/refund; `description` for deduction.

---

### 3.13 edara.service.charge

**Human name:** EDARA Service Charge · No mail.thread/chatter · **Order:** `date desc, id desc`
**Purpose:** A building-level charge campaign (e.g. quarterly maintenance fee) allocated across the building's occupied units by one of four methods, then invoiced per unit.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Computed | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|---|
| Name | `name` | Char | Yes(ORM) | readonly | Yes | No | No | `_('New')`, sequence `edara.service.charge` (`SC/%(year)s/`, pad 4) | — | |
| Building | `building_id` | Many2one | Yes | `state != draft` | Yes (indexed) | No | No | — | edara.building | |
| Property | `property_id` | Many2one | No | readonly, `base.group_no_one` only | Yes (indexed) | No | `building_id.property_id` | — | edara.property | |
| Branch | `branch_id` | Many2one | No | readonly, `base.group_no_one` only | Yes (indexed) | No | `building_id.branch_id` | — | edara.branch | |
| Company | `company_id` | Many2one | No | — | Yes (indexed) | No | `building_id.company_id` | — | res.company | not shown in form |
| Currency | `currency_id` | Many2one | No | invisible | Yes | No | No | `env.company.currency_id` | res.currency | |
| Date | `date` | Date | Yes | No | Yes | No | No | today | — | |
| Description | `description` | Char | No | No | Yes | No | No | — | — | |
| Allocation Method | `allocation_method` | Selection | Yes | `state != draft` | Yes | No | No | `equal` | see below | |
| Total Amount | `total_amount` | Monetary | business-required for equal/proportional | No | Yes | No | No | — | — | |
| Rate per m² | `rate_per_sqm` | Monetary | business-required for per_sqm | No | Yes | No | No | — | — | |
| Fixed Amount per Unit | `fixed_amount_per_unit` | Monetary | business-required for fixed_per_unit | No | Yes | No | No | — | — | |
| Allocation | `line_ids` | One2many | No | readonly=1 | — | No | inverse `charge_id` | — | edara.service.charge.line | |
| State | `state` | Selection | No | Yes | Yes | Yes | No | — | draft/allocated/invoiced | depends `line_ids.invoice_id` |

**Selection — `allocation_method`:** `equal`("Equal": total/unit-count), `proportional`("Proportional by Area": `total * unit.area/building_total_area`), `per_sqm`("Per Square Meter": `rate_per_sqm * unit.area`), `fixed_per_unit`("Fixed Amount per Unit").
**Selection — `state`:** `draft`(no lines), `allocated`(has lines, not all invoiced), `invoiced`(all lines invoiced).

**Form View** (`view_edara_service_charge_form`): Header: "Generate Allocation"(object, btn-primary, `invisible="state=='invoiced'"`, re-runnable in draft/allocated), "Create Invoices"(object, `invisible="state != 'allocated'"`). Statusbar `statusbar_visible="draft,allocated,invoiced"`. Title `name`(readonly). Left group: `building_id`(readonly once not draft), `branch_id`/`property_id`(readonly, `base.group_no_one`), `date`, `description`. Right group: `currency_id`(invisible), `allocation_method`(readonly once not draft), `total_amount`(invisible unless equal/proportional), `rate_per_sqm`(invisible unless per_sqm), `fixed_amount_per_unit`(invisible unless fixed_per_unit). Notebook "Allocation" tab: readonly list of `line_ids` (unit_id, tenant_id, amount, currency(column_invisible), invoice_id). No smart buttons, no chatter.

**List View:** Name, Building, Date, Allocation Method, Total Amount, currency(column_invisible), State(badge). No decorations.

**Search View:** **None defined.**

**Buttons/Actions**

| UI Label | Method | Precondition | What It Does | Result |
|---|---|---|---|---|
| Generate Allocation | `action_generate_allocation` | `state != invoiced`; building must have units with active-contract tenants | Deletes uninvoiced existing lines, computes per-unit shares, creates one line per eligible unit (**silently skips units with no active tenant, no warning**) | draft/allocated → allocated |
| Create Invoices | `action_invoice_lines` | `state == allocated` | Calls `_create_invoice()` on every uninvoiced line | allocated → invoiced once every line invoiced |

**State Machine**

| Current State | Action | New State | Side Effects |
|---|---|---|---|
| draft | `action_generate_allocation` | allocated | Creates lines per eligible unit |
| allocated | `action_generate_allocation` (re-run) | allocated | Deletes+regenerates uninvoiced lines (invoiced lines protected by unlink guard, preserved) |
| allocated | `action_invoice_lines` | invoiced | Posts one `out_invoice` per line |

**Accounting detail:** `edara.service.charge.line._create_invoice()` creates+posts `out_invoice`, `account_id=company.edara_service_charge_income_account_id` (blocks if unset), `analytic_distribution` set to the property's analytic account (100%), `edara_invoice_type='service_charge'`. Idempotent per line.

**Relationships:** building(1)→service_charge(0..n). charge(1)→line(0..n), `ondelete=cascade` (but invoiced lines protected by the line's own `unlink()` guard, which the ORM cascade path also respects). line→unit, tenant, invoice (1:1 via unique constraint).

**Required for creation:** `building_id`, `date`(defaults today), `allocation_method`(defaults equal). **Required before Generate Allocation succeeds:** `total_amount`>0 (equal/proportional), `rate_per_sqm`>0 (per_sqm), `fixed_amount_per_unit`>0 (fixed_per_unit); proportional additionally needs units' `area` set. **Required before Create Invoices succeeds:** `edara_service_charge_income_account_id` configured.

**Gaps:**
1. No search/filter/group-by view.
2. `branch_id`/`property_id` visible only under `base.group_no_one` (developer mode) — an ordinary Branch Manager/Accountant cannot see which branch/property a charge belongs to on the form itself.
3. Silent skip of units without an active tenant during allocation — no on-screen indication of which/how many were excluded.
4. No per-line manual override of allocation amounts once generated (the embedded list is fully readonly) — must re-run Generate Allocation to change anything.

---

### 3.14 edara.service.charge.line

**Human name:** EDARA Service Charge Line · **Order:** `id`
**Purpose:** One per-unit allocation row under a service charge; becomes invoiced via `action_invoice_lines`/`_create_invoice`.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Related | Default | Relation | Help |
|---|---|---|---|---|---|---|---|---|---|
| Service Charge | `charge_id` | Many2one | Yes | — | Yes (indexed) | No | — | edara.service.charge, `ondelete=cascade` | |
| Unit | `unit_id` | Many2one | Yes | — | Yes (indexed) | No | — | edara.unit | |
| Tenant | `tenant_id` | Many2one | Yes | — | Yes (indexed) | No | — | res.partner | from unit's active contract at generation time |
| Property | `property_id` | Many2one | No | related | Yes (indexed) | `charge_id.property_id` | — | edara.property | |
| Building | `building_id` | Many2one | No | related | Yes (indexed) | `charge_id.building_id` | — | edara.building | |
| Branch | `branch_id` | Many2one | No | related | Yes (indexed) | `charge_id.branch_id` | — | edara.branch | |
| Company | `company_id` | Many2one | No | related | Yes (indexed) | `charge_id.company_id` | — | res.company | |
| Currency | `currency_id` | Many2one | No | related | Yes | `charge_id.currency_id` | — | res.currency | |
| Amount | `amount` | Monetary | Yes | field-level No (embedded view forces readonly) | Yes | No | — | — | allocated amount |
| Invoice | `invoice_id` | Many2one | No | Yes | Yes (indexed) | No | — | account.move, copy=False | unique per line |

**Constraint:** `_invoice_id_uniq` — unique(invoice_id).

**Views:** No standalone form/list/search — only embedded (readonly) inside the parent's "Allocation" tab.

**Buttons/Actions:** `unlink()` override raises `UserError` if any selected line has `invoice_id` set (Phase 13 hardening fix). `_create_invoice()` — Python-only, called by the parent's "Create Invoices"; idempotent.

**Relationships:** charge(1)→line(0..n). line→unit, tenant, invoice (1:1).

**Required for creation (programmatic only):** `charge_id`, `unit_id`, `tenant_id`, `amount`.

**Gaps:** covered under §3.13 (no manual-edit UI; no visible "locked" indicator on invoiced rows besides `invoice_id` being set).

---

### 3.15 edara.maintenance.request

**Human name:** EDARA Maintenance Request · **Inherits:** `mail.thread`, `mail.activity.mixin` · **Order:** `requested_date desc, id desc`
**Purpose:** Tracks a repair/maintenance issue for a unit, from report through assignment, work, completion or cancellation, with optional vendor/cost tracking. Creatable internally or by a tenant via the portal.

**Fields**

| Field Label | Technical Name | Type | Required | Readonly | Stored | Related | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|---|
| Reference | `name` | Char | Yes | Yes (view) | Yes | No | `_('New')`, sequence `edara.maintenance.request` (`MR/%(year)s/`, pad 4) | — | |
| (page `<h1>`) | `title` | Char | Yes | No | Yes | No | — | — | short issue title |
| Description | `description` | Text | No | No | Yes | No | — | — | |
| Reported By | `tenant_id` | Many2one | No | No | Yes | No | — | res.partner | forced to logged-in tenant on portal submissions |
| Unit | `unit_id` | Many2one | Yes | No | Yes | No | — | edara.unit | |
| (`base.group_no_one`) | `building_id` | Many2one | No | Yes (view) | Yes | `unit_id.building_id` | — | edara.building | debug-only display |
| (`base.group_no_one`) | `property_id` | Many2one | No | Yes (view) | Yes | `unit_id.property_id` | — | edara.property | debug-only display |
| (not on form) | `branch_id` | Many2one | No | — | Yes | `unit_id.branch_id` | — | edara.branch | stored for filtering/reporting |
| (not on form) | `company_id` | Many2one | No | — | Yes | `unit_id.company_id` | — | res.company | multi-company scoping |
| Assigned To | `assigned_user_id` | Many2one | No | No | Yes | No | — | res.users | |
| Priority | `priority` | Selection | Yes | No | Yes | No | `normal` | low/normal/high/urgent | |
| Status | `state` | Selection | Yes | No (statusbar) | Yes | No | `new` | new/assigned/in_progress/done/cancelled | |
| Requested Date | `requested_date` | Date | Yes | No | Yes | No | today | — | |
| Completed Date | `completed_date` | Date | No | Yes | Yes | No | — | — | auto-set on Complete |
| (invisible=1) | `currency_id` | Many2one | No | — | Yes | No | `env.company.currency_id` | res.currency | backs `cost` widget only |
| Vendor | `vendor_id` | Many2one | No | No | Yes | No | — | res.partner | external contractor |
| Cost | `cost` | Monetary | No | No | Yes | No | — | — | must be ≥0 |

**Selection — `priority`:** Low, Normal(default), High, Urgent. **Selection — `state`:** New(default), Assigned, In Progress, Done, Cancelled.

**Form View** (`view_edara_maintenance_request_form`): Header: **Start**(object, btn-primary, `invisible="state not in ('new','assigned')"`), **Complete**(object, btn-primary, `invisible="state not in ('assigned','in_progress')"`), **Cancel**(object, `invisible="state in ('done','cancelled')"`, `confirm=`). Statusbar `statusbar_visible="new,assigned,in_progress,done"` (cancelled reachable but not a statusbar step). Title `title`. Group left: `name`(readonly), `unit_id`, `building_id`/`property_id`(readonly, `base.group_no_one`), `tenant_id`. Group right: `priority`, `assigned_user_id`, `requested_date`, `completed_date`(`invisible="not completed_date"`). Group "Cost": `currency_id`(invisible), `vendor_id`, `cost`. `description` full-width. Chatter present (thread + activities).

**List View** (`view_edara_maintenance_request_list`): Reference, Title, Unit, Priority(badge), Assigned To, Requested Date, Status(badge). Decorations: `decoration-danger` urgent, `decoration-muted` done/cancelled. No `default_order` override.

**Kanban View** (`view_edara_maintenance_request_kanban`): `default_group_by="state"`, `o_kanban_small_column`. Card `t-name="card"`: `title`(bold), `unit_id`(muted), footer `priority`(badge) + `assigned_user_id`(`widget="many2one_avatar_user"`, right-aligned).

**Search View:** **None defined** — auto-generated default search only.

**Action** `action_edara_maintenance_request`: `view_mode="kanban,list,form"`, empty-state help present. No `domain`/`context`/`search_view_id`.

**Buttons/Actions**

| UI Label | Method | Type | Precondition | What It Does | Result |
|---|---|---|---|---|---|
| Start | `action_start()` | object | `state in (new,assigned)` else `UserError` | Sets `in_progress` | new/assigned → in_progress |
| Complete | `action_complete()` | object | `state in (assigned,in_progress)` else `UserError` | `state=done`, `completed_date=today` | assigned/in_progress → done |
| Cancel | `action_cancel()` | object, `confirm=` | `state not in (done,cancelled)` else `UserError` | `state=cancelled` | any non-terminal → cancelled |
| *(no button)* | `action_assign(user_id)` | Python-only, **not wired to any UI element** | `state in (new,assigned)` | Sets `assigned_user_id`, `state=assigned` | see Gaps |

**State Machine**

| Current State | Action | New State |
|---|---|---|
| new | `action_start()` | in_progress |
| new | `action_assign(user_id)` *(unreachable from UI)* | assigned |
| assigned | `action_start()` | in_progress |
| assigned | `action_assign(user_id)` *(unreachable)* | assigned (reassignment) |
| assigned/in_progress | `action_complete()` | done |
| new/assigned/in_progress | `action_cancel()` | cancelled |
| done/cancelled | any transition | blocked (`UserError`) |

No cron touches this model's state — all transitions are user-driven button clicks (except `action_assign`, unreachable).

**Relationships:** `unit_id`(M2O, required) — building/property/branch/company are all related+stored pass-throughs from `unit_id`, no direct FK. `tenant_id`/`vendor_id`/`assigned_user_id` all optional M2O. No One2many back-references anywhere in the module point to this model (no smart button on Unit/Property to Maintenance beyond what's documented — Building does have one, per §3.4). No `unlink()` override — any user with delete access can remove a request in any state (unlike payment-schedule/service-charge lines).

**Required for creation — internal form:** `title`, `unit_id`, `priority`(defaults normal), `requested_date`(defaults today).

**Required — portal form** (`POST /my/maintenance/new`): `title`, `description`, `unit_id`(strictly validated against the tenant's own active-contract units, else `UserError`), `tenant_id`(always forced server-side to the logged-in user's partner), `priority`(defaults normal). Portal never sets `assigned_user_id`/`vendor_id`/`cost`/`completed_date`. Created via `.sudo()` (documented as necessary only because a portal user lacks `ir.sequence` read access — ownership already verified beforehand).

**Gaps:**
1. **`action_assign(user_id)` is dead code from a UI perspective** — no button, wizard, or portal route calls it. The only way to set `assigned_user_id` from the UI is editing the field directly, which does NOT transition `state` to `assigned`.
2. No search view — no "My Requests"/"Urgent"/"Unassigned" filters despite the kanban being grouped by state.
3. No `unlink()` guard — any user with delete rights can remove a request in any state, unlike payment-schedule/service-charge lines.
4. No automatic staleness/escalation — no cron touches this model at all.

---

### 3.16 edara.dashboard (TransientModel)

See full detail in **§14 Dashboard Inventory** below (kept together with its KPI table per the spec's own dashboard section).

---

### 3.17 account.move extension

`_inherit = 'account.move'` (`models/account_move.py`)

| Field Label | Technical Name | Type | Required | Readonly | Stored | Default | Selection/Relation | Help/Meaning |
|---|---|---|---|---|---|---|---|---|
| EDARA Invoice Type | `edara_invoice_type` | Selection | No | No | Yes | none | rent/late_fee/service_charge/ad_hoc | Tags the kind of EDARA document. Set programmatically by `_create_invoice()` (rent/service_charge) and `action_charge_late_fee()` (late_fee). `ad_hoc` is defined but **never set by any code path** — selectable manually but unused by automation. |
| Lease Contract | `edara_contract_id` | Many2one | No | No | Yes | none | edara.lease.contract | Set for rent invoices; drives `_onchange_edara_contract_id` autofill |
| Branch | `edara_branch_id` | Many2one | No | No | Yes | none | edara.branch | Plain editable, NOT related-from-contract (deliberate — a vendor bill has no contract) |
| Property | `edara_property_id` | Many2one | No | No | Yes | none | edara.property | same |
| Building | `edara_building_id` | Many2one | No | No | Yes | none | edara.building | same |
| Unit | `edara_unit_id` | Many2one | No | No | Yes | none | edara.unit | same |

**Onchange methods:** `_onchange_edara_contract_id` (autofills unit/building/property/branch from contract); `_onchange_edara_property_id` (autofills branch from property).

**Constraint** `_check_edara_tags_consistent` (Phase 13 hardening): raises `ValidationError` if branch's company ≠ move's company, property's company ≠ move's company, property's branch ≠ selected branch, building's property ≠ selected property, or unit's building ≠ selected building.

**⚠ Confirmed gap:** these six fields exist as plain editable columns on `account.move` but appear ONLY in `views/reports_views.xml` (as pivot/list columns and group-by filters) — **never added to the standard Odoo Invoicing/Bill form** (no inherited `account.move` form view exists in this module). A user manually creating/editing a vendor bill has no visible field to set/review any of them; they're set purely programmatically for EDARA-generated invoices. For vendor bills opened via `edara.property.action_view_expenses()`, the property is only a creation-time context default, invisible on the form afterward.

### 3.18 account.payment extension

`_inherit = 'account.payment'` (`models/account_payment.py`)

| Field Label | Technical Name | Type | Default | Help |
|---|---|---|---|---|
| Security Deposit | `edara_is_security_deposit` | Boolean | False | Internal routing flag, `copy=False`. Set only by `edara.deposit._create_deposit_payment()`. **Not exposed in any view** (zero XML references) — by design, an internal marker, not a UI gap. |

**Override:** `_compute_destination_account_id` — when `True`, forces `destination_account_id = company.edara_deposit_liability_account_id` (raises `UserError` if unconfigured). This is the entire mechanism routing deposit payments to the liability account instead of the tenant's normal receivable account.

### 3.19 res.partner extension

`_inherit = 'res.partner'` (`models/res_partner.py`)

| Field Label | Technical Name | Type | Stored | Computed | Depends | Default | Relation | Help |
|---|---|---|---|---|---|---|---|---|
| EDARA Ownerships | `edara_ownership_ids` | One2many | No | No | — | — | edara.ownership via `owner_id` | |
| EDARA Owner | `is_edara_owner` | Boolean | Yes | Yes | `edara_ownership_ids.active` | — | — | True if the partner has any active ownership row |
| EDARA Lease Contracts | `edara_lease_contract_ids` | One2many | No | No | — | — | edara.lease.contract via `tenant_id` | |
| EDARA Tenant | `is_edara_tenant` | Boolean | Yes | Yes | `edara_lease_contract_ids` | — | — | True if the partner has ANY lease contract regardless of state (even draft/terminated/expired keeps this True — the dependency is the O2M itself, not a state-filtered one) |
| National ID / Registration No. | `edara_national_id` | Char | Yes | No | — | — | — | free text, no format validation |

**Form View** (`view_partner_form_edara`, xpath after `//field[@name='category_id']` on `base.view_partner_form`): adds `edara_national_id`(visible), `is_edara_owner`(invisible=1), `is_edara_tenant`(invisible=1). No list/kanban/search overrides for `res.partner`.

**Gap:** `is_edara_owner`/`is_edara_tenant` are added to the arch but immediately marked `invisible=1` with nothing else in this xpath block referencing them as a visibility condition — no Owner/Tenant badge is visible on the Contacts form from this xpath. (They may be consumed by search views elsewhere, e.g. the Tenant Ledger report's domain on `partner_id.is_edara_tenant`, but that's a different, unrelated usage.)

---

## 4–8. Cross-model summary tables

Full per-model form/list/kanban/search/button/state-machine detail is in §3 above (kept together per model, which is the more useful shape for a tester). The tables below let a tester scan across the whole module at once.

### 4. All Form Views

| Model | View XML ID | Header Buttons | Statusbar | Smart Buttons | Chatter |
|---|---|---|---|---|---|
| edara.branch | view_edara_branch_form | none | none | Properties | Yes (thread only) |
| edara.property | view_edara_property_form | none | none | Buildings, Units, Expenses, Invoices | Yes (thread only) |
| edara.building | view_edara_building_form | none | none | Units, Service Charges, Contracts, Maintenance | Yes (thread only) |
| edara.unit | view_edara_unit_form | none | none | Contracts, Maintenance | Yes (thread only) |
| edara.lease.contract | view_edara_lease_contract_form | Activate, Renew, Terminate | draft/active/terminated (renewed+expired missing) | Schedule, Deposit(create-on-click), Renewals | Yes (thread+activity) |
| edara.payment.schedule.line | view_edara_payment_schedule_line_form | Charge Late Fee | none (badge field) | none | No |
| edara.renewal.request | view_edara_renewal_request_form | Approve, Reject | submitted/approved/rejected (complete) | none | Yes (thread only) |
| edara.lease.renewal.wizard | view_edara_lease_renewal_wizard_form | Renew, Cancel (footer) | — | — | No (transient) |
| edara.deposit | view_edara_deposit_form | Collect Deposit, Refund, Deduct | draft/held/closed | none | No |
| edara.deposit.transaction.wizard | view_edara_deposit_transaction_wizard_form | Confirm, Cancel (footer) | — | — | No (transient) |
| edara.service.charge | view_edara_service_charge_form | Generate Allocation, Create Invoices | draft/allocated/invoiced | none | No |
| edara.maintenance.request | view_edara_maintenance_request_form | Start, Complete, Cancel | new/assigned/in_progress/done (cancelled missing) | none | Yes (thread+activity) |
| res.partner (edara xpath) | view_partner_form_edara | (inherits native) | — | — | (native) |
| edara.dashboard | view_edara_dashboard_form | none | — | — | No (transient, no chatter) |
| res.config.settings (edara block) | (inherits base.res_config_settings_view_form) | (native save/discard) | — | — | — |

### 5. All List Views

| Model | View XML ID | Editable | Create allowed | Decorations | Notes |
|---|---|---|---|---|---|
| edara.branch | view_edara_branch_list | No | Yes | none | |
| edara.property | view_edara_property_list | No | Yes | none | |
| edara.building | view_edara_building_list | No | Yes | none | |
| edara.unit | view_edara_unit_list | No | Yes | success/danger/warning/muted (occupancy+maintenance) | |
| edara.lease.contract | view_edara_lease_contract_list | No | Yes | success/muted (state) | |
| edara.payment.schedule.line | view_edara_payment_schedule_line_list | **bottom** | **No** (`create="0"`) | danger/success (overdue/paid) | `invoice_id` inline-editable — see §3.7 Gaps |
| edara.renewal.request | view_edara_renewal_request_list | No | Yes | info/muted/success (state) | |
| edara.deposit | view_edara_deposit_list | No | Yes | none | |
| edara.service.charge | view_edara_service_charge_list | No | Yes | none | |
| edara.maintenance.request | view_edara_maintenance_request_list | No | Yes | danger/muted (priority/state) | |

### 6. All Search Views

| Model | Search View | Exists? | Filters | Group By |
|---|---|---|---|---|
| edara.branch | — | **No** | — | — |
| edara.property | — | **No** | — | — |
| edara.building | — | **No** | — | — |
| edara.unit | view_edara_unit_search | **Yes** | Available, Rented, Under Maintenance | Building, Floor, Occupancy |
| edara.lease.contract | — | **No** | — | — |
| edara.payment.schedule.line | — | **No** | — | — |
| edara.renewal.request | — | **No** | — | — |
| edara.deposit | — | **No** | — | — |
| edara.service.charge | — | **No** | — | — |
| edara.maintenance.request | — | **No** | — | — |
| account.move (reports) | view_edara_account_move_report_search | **Yes** | Posted, Draft, This Year | Branch, Property, Tenant/Partner, Month |
| edara.unit (reports) | view_edara_unit_report_search | **Yes** | Rented, Vacant | Branch, Property, Status |

Only 3 custom search views exist in the entire module. Every high-traffic operational list (Properties, Buildings, Contracts, Payment Schedule, Deposits, Service Charges, Renewal Requests) relies on Odoo's bare auto-generated search box with no curated filters or group-bys — a systemic, provable gap (see §20).

### 7. Master Button/Action Table

| UI Label | Model | Technical Method/Action | Type | Preconditions | What It Does | Result |
|---|---|---|---|---|---|---|
| Properties (smart btn) | edara.branch | `action_view_properties` | object | none | Filtered list | navigation |
| Buildings (smart btn) | edara.property | `action_view_buildings` | object | none | Filtered list | navigation |
| Units (smart btn) | edara.property | `action_view_units` | object | none | Filtered list | navigation |
| Expenses (smart btn) | edara.property | `action_view_expenses` | object | none | Native vendor-bills list, scoped | navigation |
| Invoices (smart btn) | edara.property | `action_view_invoices` | object | none | Native customer-invoices list, scoped | navigation |
| Units (smart btn) | edara.building | `action_view_units` | object | none | Filtered list | navigation |
| Service Charges (smart btn) | edara.building | `action_view_service_charges` | object | none | Filtered list | navigation |
| Contracts (smart btn) | edara.building | `action_view_contracts` | object | none | Filtered list | navigation |
| Maintenance (smart btn) | edara.building | `action_view_maintenance_requests` | object | none | Filtered list | navigation |
| Contracts (smart btn) | edara.unit | `action_view_contracts` | object | none | Filtered list | navigation |
| Maintenance (smart btn) | edara.unit | `action_view_maintenance_requests` | object | none | Filtered list | navigation |
| Activate | edara.lease.contract | `action_activate` | object header | state==draft; unit not sold/under_maintenance | unit→rented, schedule generated | draft→active |
| Renew | edara.lease.contract | wizard action | action | state==active | opens wizard | (see wizard) |
| Terminate | edara.lease.contract | `action_terminate` | object header, confirm | state==active | unit→available, future lines removed | active→terminated |
| Schedule (smart btn) | edara.lease.contract | `action_view_schedule_lines` | object | always | filtered list | navigation |
| Deposit (smart btn) | edara.lease.contract | `action_view_deposit` | object | deposit_required | **find-or-CREATE** deposit | navigation + possible create |
| Renewals (smart btn) | edara.lease.contract | `action_view_renewal_requests` | object | always | filtered list | navigation |
| Charge Late Fee | edara.payment.schedule.line | `action_charge_late_fee` | object header | state==overdue; both late-fee accounts configured | posts separate late-fee invoice | new invoice, line state unchanged |
| Approve | edara.renewal.request | `action_approve` | object header | state==submitted | delegates to contract.action_renew | submitted→approved |
| Reject | edara.renewal.request | `action_reject` | object header, confirm | state==submitted | sets state, no reason capturable from UI | submitted→rejected |
| Renew (wizard) | edara.lease.renewal.wizard | `action_confirm` | object footer | fields filled | calls contract.action_renew | opens new contract form |
| Collect Deposit | edara.deposit | wizard action | action header | balance<amount | opens wizard(default held) | wizard→action_collect |
| Refund | edara.deposit | wizard action | action header | balance>0 | opens wizard(default refund) | wizard→action_refund |
| Deduct | edara.deposit | wizard action | action header | balance>0 | opens wizard(default deduction) | wizard→action_deduct |
| Confirm | edara.deposit.transaction.wizard | `action_confirm` | object footer | journal_id(held/refund) or description(deduction) | dispatches to deposit action | closes dialog |
| Generate Allocation | edara.service.charge | `action_generate_allocation` | object header | state != invoiced; eligible units exist | creates/regenerates lines | draft/allocated→allocated |
| Create Invoices | edara.service.charge | `action_invoice_lines` | object header | state==allocated | invoices every uninvoiced line | allocated→invoiced |
| Start | edara.maintenance.request | `action_start` | object header | state in (new,assigned) | →in_progress | state change |
| Complete | edara.maintenance.request | `action_complete` | object header | state in (assigned,in_progress) | →done, completed_date set | state change |
| Cancel | edara.maintenance.request | `action_cancel` | object header, confirm | state not in (done,cancelled) | →cancelled | state change |
| *(dead, no UI)* | edara.maintenance.request | `action_assign` | Python-only | — | — | **unreachable — see §20** |
| Dashboard (menu) | edara.dashboard | `action_open` via `action_edara_dashboard_open` | ir.actions.server | none | creates fresh record, opens form | navigation |

### 8. Master State Machine Table

| Model | Field | All Values | Manually Triggerable? | Cron-Triggerable? |
|---|---|---|---|---|
| edara.lease.contract | state | draft, active, renewed, terminated, expired | draft→active, active→terminated, active→renewed (all manual) | active→expired (`_cron_expire_contracts`, daily) |
| edara.payment.schedule.line | state | draft, invoiced, partial, paid, overdue, cancelled | never written directly — 100% computed from `invoice_id`/`due_date` | invoice creation via `_cron_generate_due_invoices` (daily) indirectly drives state |
| edara.renewal.request | state | submitted, approved, rejected | submitted→approved, submitted→rejected (manual only) | none |
| edara.deposit | state | draft, held, closed | never written directly — 100% computed from transactions | none |
| edara.service.charge | state | draft, allocated, invoiced | never written directly — 100% computed from `line_ids.invoice_id` | none |
| edara.maintenance.request | state | new, assigned, in_progress, done, cancelled | new/assigned→in_progress, assigned/in_progress→done, any-non-terminal→cancelled (manual); new/assigned→assigned via `action_assign` **unreachable from UI** | none |

---

## 9. Relationship Map Between Models

```
res.company
 └─ edara.branch (company_id, required)
     ├─ edara.property (branch_id, required)
     │   ├─ edara.building (property_id, required)
     │   │   ├─ edara.unit (building_id, required)
     │   │   │   ├─ edara.lease.contract (unit_id, required)
     │   │   │   │   ├─ edara.payment.schedule.line (contract_id, required, cascade)
     │   │   │   │   │   └─ account.move (invoice_id, 1:1, unique)  ← _create_invoice() / _cron_generate_due_invoices
     │   │   │   │   ├─ edara.renewal.request (contract_id, required, restrict)
     │   │   │   │   │   └─ (on approve) creates a new edara.lease.contract (predecessor/successor chain)
     │   │   │   │   └─ edara.deposit (contract_id, required, restrict; UNIQUE — 1 deposit per contract)
     │   │   │   │       └─ edara.deposit.transaction (deposit_id, required, restrict)
     │   │   │   │           ├─ account.payment (payment_id — held/refund)
     │   │   │   │           └─ account.move (move_id — deduction, move_type=entry)
     │   │   │   └─ edara.maintenance.request (unit_id, required)
     │   │   └─ edara.service.charge (building_id, required)
     │   │       └─ edara.service.charge.line (charge_id, required, cascade) → unit_id, tenant_id
     │   │           └─ account.move (invoice_id, 1:1, unique)  ← _create_invoice()
     │   └─ edara.ownership (property_id, required) → owner_id (res.partner)
     └─ res.users (via edara_branch_users_rel, "assigned staff") / manager_id

res.partner (tenant)
 ├─ edara.lease.contract.tenant_id (O2M back-ref: edara_lease_contract_ids, drives is_edara_tenant)
 ├─ edara.maintenance.request.tenant_id (optional)
 ├─ edara.renewal.request.tenant_id (related from contract)
 └─ edara.deposit.tenant_id (related from contract)

res.partner (owner)
 └─ edara.ownership.owner_id (O2M back-ref: edara_ownership_ids, drives is_edara_owner)

account.move (EDARA-tagged via edara_branch_id/edara_property_id/edara_building_id/edara_unit_id/edara_contract_id/edara_invoice_type)
 ├─ produced by: rent (_create_invoice on schedule line), late_fee (action_charge_late_fee), service_charge (_create_invoice on charge line)
 ├─ vendor bills (in_invoice) via native Odoo Invoicing UI, tagged only with edara_property_id (context default)
 └─ account.payment: registered via NATIVE "Register Payment" button only (no EDARA wrapper), except deposit collect/refund which go through edara.deposit._create_deposit_payment()

account.analytic.plan (analytic_plan_edara_property, one global record)
 └─ account.analytic.account (one per edara.property, lazily created by get_analytic_account())
     ← referenced via analytic_distribution on rent/late_fee/service_charge invoice lines (100%)
```

**Cascade/ondelete summary:**

| Parent → Child | ondelete | Historical preservation |
|---|---|---|
| edara.lease.contract → edara.payment.schedule.line | cascade | Line's own `unlink()` blocks deletion once `invoice_id` is set, regardless of parent-cascade path |
| edara.service.charge → edara.service.charge.line | cascade | Same pattern — line's `unlink()` guard protects invoiced lines |
| edara.deposit → edara.deposit.transaction | (transaction side: restrict) | Transaction `unlink()` always blocked — permanent audit trail |
| edara.lease.contract → edara.renewal.request | (request side: restrict) | Contract cannot be deleted while any renewal request (any state) references it |
| edara.lease.contract → edara.deposit | (deposit side: restrict) | Deposit references its contract with restrict |
| edara.lease.contract itself | — | `unlink()` blocked entirely once `state != draft` |
| edara.branch/property/building/unit | (no explicit unlink guard found on these 4 models themselves) | Deletion relies on Odoo's default FK protection from any contract/etc. still referencing them |

---

## 10. Accounting UI Inventory (native Odoo models used, verified from code)

**What creates an `account.move`:**
1. **Rent invoices** — `edara.payment.schedule.line._create_invoice()`, called manually or by the daily `_cron_generate_due_invoices` cron. Posted immediately (`action_post()`), `account_id=edara_rental_income_account_id`, `analytic_distribution` 100% to the property's analytic account, `edara_invoice_type='rent'` plus the full tag chain.
2. **Late fee invoices** — `edara.payment.schedule.line.action_charge_late_fee()`. Manual-only, no cron trigger. Same structure, `account_id=edara_late_fee_income_account_id`, `edara_invoice_type='late_fee'`.
3. **Service charge invoices** — `edara.service.charge.line._create_invoice()`. Same structure, `account_id=edara_service_charge_income_account_id`, `edara_invoice_type='service_charge'`.
4. **Deposit deduction** — `edara.deposit.action_deduct()`. NOT an invoice — a plain `move_type='entry'` journal entry (debit liability / credit deduction-income), posted immediately.
5. **Vendor bills/expenses (`in_invoice`)** — created via the **native** Odoo Invoicing UI (Accounting > Vendor Bills, or the Property form's "Expenses" smart button, which opens the native `account.action_move_in_invoice_type` with a domain/context default on `edara_property_id`). No EDARA-specific creation code exists for vendor bills.

**What creates an `account.payment`:**
- **Deposit collection/refund** — `edara.deposit._create_deposit_payment()`, called by `action_collect`/`action_refund`. Creates+posts `account.payment` (`payment_type=inbound/outbound`, `partner_type=customer`), tagged `edara_is_security_deposit=True`.
- **Rent/service-charge/late-fee payment registration** — **entirely native**. Zero custom payment-registration code exists (no override of `action_register_payment`, no `account.payment.register` wizard extension). EDARA relies entirely on the native "Register Payment" button that Odoo unconditionally places on every `account.move` form.

**Partial payment / overpayment:** entirely native. `edara.payment.schedule.line.state` is a computed, stored field that reads `invoice_id.payment_state` (Odoo's own native reconciliation outcome) through a mapping table. No EDARA code ever touches `account.move.line.reconcile()` directly.

**Security deposit accounting:** `edara_deposit_liability_account_id` (destination of every deposit payment, enforced via `account.payment._compute_destination_account_id` override) + `edara_deposit_deduction_income_account_id` (credited on deduction). Full transaction detail in §3.10.

**Deposit refund:** `edara.deposit.action_refund()` — outbound `account.payment`, same liability-account routing. No reversal exists for a completed deduction.

**Service charge accounting:** `edara_service_charge_income_account_id` (credited on every service-charge invoice line). Full detail in §3.13/§3.14.

**Late fee:** `edara_late_fee_income_account_id` (credited) + `edara_late_fee_amount` (flat amount, company currency — see currency note below) — manual-trigger only, never automatic.

**Expenses:** native vendor bills, scoped only by the `edara_property_id` context default at creation time (not persisted-visible afterward since no view exposes the field — see §3.17 gap).

**Credit notes / reversals:** no EDARA-specific code anywhere — handled purely through native Odoo credit-note creation (the standard "Credit Note" button on any posted customer invoice). EDARA's only involvement is that its Revenue report correctly nets the resulting `out_refund` moves via `amount_untaxed_signed`.

**Analytic accounting:** one shared `account.analytic.plan` (`analytic_plan_edara_property`), one lazily-created `account.analytic.account` per property (`edara.property.get_analytic_account()`). `analytic_distribution` is set in exactly three places: rent invoice creation, late-fee invoice creation, service-charge invoice creation — always 100% to the property's analytic account. Vendor bills get no automatic analytic distribution (native behavior, not a gap).

**Currency:** `res.company.currency_id` is the ultimate source. `edara.branch.currency_id`/`edara.property.currency_id` are `related='company_id.currency_id'` (always follow company). `edara.lease.contract.currency_id` is its OWN field (defaults to company currency but independently settable, no constraint tying it back) — every downstream model (schedule line, deposit, service charge... wait, service charge is building-scoped, its own `currency_id` defaults to company currency independently) inherits the **contract's** currency for the contract-chain models. `res.config.settings.edara_late_fee_amount` is denominated in the **company's** currency, but gets charged onto a contract-currency invoice with **no explicit conversion code found** — a real risk if any contract uses a non-company currency (see §20).

**Exact native Odoo models involved (confirmed, none invented):** `account.move`, `account.move.line`, `account.payment`, `account.account`, `account.analytic.plan`, `account.analytic.account`. No `account.payment.register` wizard extension, no `account.reconcile.model` involvement, no custom `account.journal` model.

---

## 11. Payment Schedule UI (dedicated section)

See §3.7 for the full field table, form, list, buttons, and state machine. Summary of the specific points requested:

- **Fields:** contract_id, tenant_id/unit_id/property_id/building_id/branch_id/company_id/currency_id (all related from contract), sequence, due_date, amount, description, invoice_id, state.
- **Statuses:** draft, invoiced, partial, paid, overdue, cancelled — 100% computed, never directly written.
- **Buttons:** "Charge Late Fee" only (form header, overdue-only).
- **Invoice relationship:** 1:1 unique (`_invoice_id_uniq`); set by `_create_invoice()`, never re-settable through the form (readonly), but **is** editable inline from the list view (§3.7 gap).
- **Due date / Amount / Currency:** editable inline in the list (`editable="bottom"`) and on the form; currency is related from the contract (not independently settable per line).
- **Contract / Tenant / Unit:** contract_id required and readonly once set; tenant/unit/property/building/branch/company all related+stored, read-only display only.
- **Invoice state / Payment state:** not separate fields — folded into the single computed `state` via the `INVOICE_PAYMENT_STATE_TO_LINE_STATE` mapping.
- **Generation logic:** `edara.lease.contract._generate_schedule_lines()` — one line per billing period from `start_date` to `end_date`, due on `payment_day` of each period's month, spaced by `billing_frequency` (1/3/12 months). Called on `action_activate()` and again (for the new contract) on renewal. **Only touches uninvoiced lines** — deletes and regenerates the uninvoiced set, never regenerates already-invoiced history.
- **Cancellation behavior:** lines are never "cancelled" directly — a line becomes `cancelled` only via its linked invoice being cancelled/reversed. Uninvoiced lines are deleted (not soft-cancelled) by `action_terminate()` (future lines only) and `_cron_expire_contracts()` (all remaining uninvoiced lines).
- **Cron behavior:** `_cron_generate_due_invoices()`, daily, `FOR UPDATE SKIP LOCKED` raw SQL selecting `invoice_id IS NULL AND due_date <= today`, re-checks `contract.state == 'active'` per line, per-line try/except with commit-or-rollback (skipped in tests).
- **Duplicate prevention:** the unique DB constraint on `invoice_id` (`_invoice_id_uniq`) plus `FOR UPDATE SKIP LOCKED` in the cron query together prevent the same line from being invoiced twice, even under concurrent cron runs.

---

## 12. Security UI Inventory

8 EDARA-specific groups exist (verified against `odoo19_dev`): `group_edara_viewer`, `group_edara_property_manager`, `group_edara_branch_manager`, `group_edara_maintenance`, `group_edara_accountant`, `group_edara_company_manager`, `group_edara_administrator`, `group_edara_portal_tenant`. No other EDARA groups exist — no separate "Owner" portal group; owners are not portal users in this implementation.

Privilege axes (Settings > Users, "EDARA Property Management" category `module_category_edara`): `privilege_edara_access_level` (the main ladder), `privilege_edara_maintenance` (independent toggle), `privilege_edara_accounting` (independent toggle).

| Group Name | XML ID | Intended Role (from `comment`) | Implied Groups | Sequence/Privilege |
|---|---|---|---|---|
| Viewer | group_edara_viewer | Read-only access to properties, units, contracts and tenants within assigned branches. | base.group_user | seq 10, Access Level |
| Property Manager | group_edara_property_manager | Operational management within assigned branches; can record payments but not access journals directly. | group_edara_viewer | seq 20, Access Level |
| Branch Manager | group_edara_branch_manager | Full operational control of assigned branches. | group_edara_property_manager | seq 30, Access Level |
| Maintenance Staff | group_edara_maintenance | Can manage maintenance requests assigned to them within their branches. | group_edara_viewer | Maintenance privilege |
| Accountant | group_edara_accountant | Full financial access within assigned branches; operational data read-only. | group_edara_viewer | Accounting privilege |
| Company Manager | group_edara_company_manager | Full access across all branches of the company. | group_edara_branch_manager, group_edara_accountant | seq 40, Access Level |
| Administrator | group_edara_administrator | Full technical and functional access, including configuration. | group_edara_company_manager | seq 50, Access Level. Seeded with `user_ids: base.user_admin, base.user_root` (added so the instance admin has App Switcher access out of the box) |
| Portal Tenant | group_edara_portal_tenant | Tenant portal access — restricted to own unit/lease/invoices/requests. | base.group_portal | NOT on the Access Level ladder — does not carry group_edara_viewer |

Because of `implied_ids`, `group_edara_administrator` effectively carries everything down the ladder plus everything `group_edara_accountant` grants. `group_edara_maintenance`/`group_edara_accountant` are independent add-on toggles on top of Viewer, not mutually exclusive with the ladder.

### Per-group model access (47 CSV rows total)

**`group_edara_viewer`** (read-only baseline, carried by every non-portal role):

| Model | Create | Read | Write | Delete |
|---|---|---|---|---|
| edara.branch, edara.property, edara.building, edara.unit, edara.ownership, edara.lease.contract, edara.payment.schedule.line, edara.deposit, edara.deposit.transaction, edara.service.charge, edara.service.charge.line, edara.maintenance.request, edara.renewal.request | 0 | 1 | 0 | 0 |
| edara.dashboard | 1 | 1 | 1 | 0 |

(`edara.dashboard`'s `perm_write=1` is not a real mutation grant — the model has zero stored fields; it exists solely to satisfy Odoo's `ir.actions.server` execution guard, per the earlier Access Error fix this session.)

**`group_edara_property_manager`** (adds on top of Viewer): create+write (no delete) on edara.property, edara.building, edara.unit, edara.lease.contract, edara.payment.schedule.line, edara.service.charge, edara.service.charge.line, edara.maintenance.request, edara.renewal.request. Full CRUD on `edara.lease.renewal.wizard`. No access beyond Viewer read to edara.branch, edara.ownership, edara.deposit, edara.deposit.transaction.

**`group_edara_branch_manager`** (adds on top of Property Manager): full CRUD on edara.branch, edara.property, edara.building, edara.unit, edara.ownership, edara.lease.contract, edara.payment.schedule.line, edara.service.charge, edara.service.charge.line, edara.maintenance.request, edara.renewal.request. Write-but-not-delete on edara.deposit, edara.deposit.transaction.

**`group_edara_maintenance`** (adds on top of Viewer): create+write (no delete) on edara.maintenance.request only.

**`group_edara_accountant`** (adds on top of Viewer): create+write on edara.deposit, edara.deposit.transaction. Full CRUD on edara.deposit.transaction.wizard. No access beyond Viewer read to property/building/unit/contract.

**`group_edara_company_manager`**: full CRUD on edara.branch (upgrade over Branch Manager's branch access, which had none beyond Viewer). Everything else inherited via implied_ids.

**`group_edara_administrator`**: no separate CSV rows — 100% of access comes from implied_ids; its only distinct grant is the `user_ids` seeding on the group record.

**`group_edara_portal_tenant`** (does NOT inherit Viewer — this is its complete grant):

| Model | Create | Read | Write | Delete |
|---|---|---|---|---|
| edara.lease.contract | 0 | 1 | 0 | 0 |
| edara.unit | 0 | 1 | 0 | 0 |
| edara.maintenance.request | 1 | 1 | 0 | 0 |
| edara.renewal.request | 1 | 1 | 0 | 0 |

No portal ACL access to branch/property/building/ownership/deposit/deposit.transaction/service.charge/service.charge.line/dashboard/wizards.

### Menu-level `groups=` gates (on top of the ACL table)

- `menu_edara_root` (whole app): `group_edara_viewer` — Portal Tenant never sees the EDARA app in the backend App Switcher at all; portal tenants only reach data via `/my/...` routes.
- `menu_edara_reports` (+5 children): `group_edara_accountant, group_edara_branch_manager`.
- `menu_edara_configuration`: `group_edara_branch_manager`.
- `menu_edara_settings`: `group_edara_company_manager`.
- All other menus carry no explicit `groups=` — visibility governed purely by ACL read on the target model (every non-portal EDARA group has Viewer-or-above read on all of them, so in practice every internal EDARA role sees every operational menu; what differs is whether buttons/fields are editable).

### Record Rules (43 total)

**Repeated 3-rule pattern**, applied identically to `edara.branch, edara.property, edara.building, edara.unit, edara.ownership, edara.lease.contract, edara.payment.schedule.line, edara.deposit, edara.deposit.transaction, edara.service.charge, edara.service.charge.line, edara.maintenance.request, edara.renewal.request` (13 models):

| Rule | Groups | Domain | Purpose |
|---|---|---|---|
| `<Model>: multi-company` | none (global) | `[('company_id','in',company_ids)]` | Base multi-company wall, applies to everyone |
| `<Model>: assigned branches only` | group_edara_viewer | `['\|',('branch_id.user_ids','in',[user.id]),('branch_id.manager_id','=',user.id)]` (edara.branch itself uses `user_ids`/`manager_id` directly, no `branch_id.` prefix) | Restricts a plain Viewer-tier user to branches they're assigned to or manage |
| `<Model>: company manager sees all` | group_edara_company_manager | `[(1,'=',1)]` | ORs with the restrictive rule (same-model rules across a user's groups OR together) — Company Manager/Administrator see every branch of their company(ies), still bounded by the multi-company rule |

Net effect: Viewer/Property Manager/Branch Manager/Maintenance/Accountant are all branch-scoped (assigned or managed branches only); Company Manager and Administrator see every branch of every company they belong to.

**Portal-own rules** (the only rules applying to `group_edara_portal_tenant`, standalone — it doesn't carry Viewer):

| Rule | Model | Domain |
|---|---|---|
| rule_edara_lease_contract_portal_own | edara.lease.contract | `[('tenant_id','=',user.partner_id.id)]` |
| rule_edara_unit_portal_own | edara.unit | `[('lease_contract_ids.tenant_id','=',user.partner_id.id)]` |
| rule_edara_maintenance_request_portal_own | edara.maintenance.request | `[('tenant_id','=',user.partner_id.id)]` |
| rule_edara_renewal_request_portal_own | edara.renewal.request | `[('tenant_id','=',user.partner_id.id)]` |

These 4 rules are the actual enforcement mechanism behind the portal's anti-ID-forging protection (§13).

**Gap (proven):** `group_edara_maintenance`'s stated intent ("assigned to them within their branches") is only enforced at the branch level by the shared rule — there is **no rule restricting a maintenance staff member to only requests assigned to them** (no domain references `assigned_user_id`). A real gap between stated intent and enforced rule.

---

## 13. Portal Inventory

Implemented via `controllers/portal.py`'s `EdaraPortal(CustomerPortal)` (extends native `portal`) + `views/portal_templates.xml`. `auth='user'` on every route (`group_edara_portal_tenant` implies `base.group_portal`).

| Route | Method | Page Title | Model(s) | Purpose |
|---|---|---|---|---|
| `/my/leases`, `/my/leases/page/<int:page>` | GET | "My Leases" | edara.lease.contract | Paginated list of own contracts |
| `/my/leases/<int:contract_id>` | GET | "My Lease" | edara.lease.contract, edara.renewal.request | Detail + renewal request form (if active, no pending request) |
| `/my/leases/<int:contract_id>/renew` | POST | (redirect) | edara.renewal.request (create) | Submits a renewal request |
| `/my/maintenance`, `/my/maintenance/page/<int:page>` | GET | "My Maintenance Requests" | edara.maintenance.request | Paginated list of own requests |
| `/my/maintenance/new` | GET | "New Maintenance Request" | edara.lease.contract (compute active units) | Creation form scoped to tenant's own active unit(s) |
| `/my/maintenance/new` | POST | (redirect) | edara.maintenance.request (create) | Creates a request |
| `/my/maintenance/<int:request_id>` | GET | "Maintenance Request" | edara.maintenance.request | Read-only detail, no status-change actions exposed |

Plus: `_prepare_home_portal_values` adds `lease_count`/`maintenance_count` to `/my`; `portal_my_home_edara` adds two cards ("My Lease", "Maintenance Requests") to the portal landing page.

**Fields shown:**
- **My Leases:** Reference, Unit, Start Date, End Date, Rent, Status (raw state string, not translated in the template).
- **My Lease detail:** Unit, Property, Start Date, End Date, Rent, Status; renewal form if eligible (New Start defaults to current end_date, New End required, Proposed Rent defaults to current, optional Message) or an info banner if a request is already pending.
- **My Maintenance Requests:** Reference, Title, Unit, Priority(raw), Status(raw); "New Maintenance Request" button.
- **New Maintenance Request form:** Unit(select, from active-lease units only), Priority(select, defaults Normal), Title(required), Description(optional).
- **Maintenance Request detail:** Unit, Priority, Status, Requested On, Completed On(if set), Description(if set). No buttons — a tenant cannot cancel/edit/comment; no chatter widget on this template.

**Not implemented / not exposed:** Invoices, Payments, Security Deposits, Documents — no route or template exists for any of these on the portal, despite `edara.deposit` and `account.move` records existing for the tenant.

**Tenant identity mechanism:** every route uses `request.env.user.partner_id`.
1. **List routes:** explicit domain `[('tenant_id','=', user.partner_id.id)]` passed to `search()`, PLUS the `rule_edara_*_portal_own` ir.rule applies since these run as the actual portal user — belt-and-suspenders.
2. **Detail routes with an id in the URL:** use the **native** `self._document_check_access(model, id)` (`odoo/addons/portal/controllers/portal.py`) — browses `with_user(SUPERUSER_ID)` to check existence (raises `MissingError` if absent), then separately calls `document.check_access('read')` **as the actual logged-in user**, which is exactly where the portal-own ir.rule domains get enforced; re-raises `AccessError` if it fails (no `access_token` is ever passed by these routes). **Forged/guessed IDs are blocked by the ir.rule record rules via the native framework helper, not by bespoke per-route code** — structural protection, not something that could be forgotten on a new route.
3. `/my/leases/<id>/renew` (POST) additionally re-verifies `contract_sudo.tenant_id.id != user.partner_id.id` explicitly — a redundant defense-in-depth second check.
4. `/my/maintenance/new` (POST) has no existing record to check — instead validates the submitted `unit_id` against `_edara_tenant_active_units()` before calling `.sudo().create(...)`; `tenant_id` is always hardcoded server-side, never taken from POST data, so a tenant cannot spoof filing as someone else even though create runs sudo (sudo is needed only for `ir.sequence` read access).

---

## 14. Dashboard Inventory

Model `edara.dashboard` (TransientModel). View `view_edara_dashboard_form`, single form, `create="false" edit="false" delete="false"`. Opened via `menu_edara_dashboard` → `action_edara_dashboard_open` (`ir.actions.server`, code `action = model.action_open()`) → `action_open()` creates a fresh record and returns `action_edara_dashboard` (`ir.actions.act_window`, `target=current`) pinned to the record.

All 11 KPI tiles are computed live in one method `_compute_kpis` (`@api.depends()` — recomputed on every open, never stored), rendered as static Bootstrap `o_stat_info` tiles. **None of the 11 tiles has a click-through/drill-down action** — confirmed: no `<button>`, no `oe_stat_button`, no `t-on-click` anywhere in the KPI block; they are plain text.

| Label | Value Field | Source Model | Calculation | Filters | Drill-down? |
|---|---|---|---|---|---|
| Total Properties | total_properties | edara.property | `search_count([])` | none | No |
| Total Buildings | total_buildings | edara.building | `search_count([])` | none | No |
| Total Units | total_units | edara.unit | `search_count([])` | none | No |
| Occupied Units | occupied_units | edara.unit | `search_count([('occupancy_status','=','rented')])` | none | No |
| Available Units | available_units | edara.unit | computed in Python: total − occupied − under_maintenance | none | No |
| Under Maintenance | under_maintenance_units | edara.unit | `search_count([('operational_status','=','under_maintenance')])` | none | No |
| Monthly Revenue | monthly_revenue | account.move | `_read_group` sum of `amount_untaxed_signed`, posted, out_invoice/out_refund | current calendar month only | No |
| Outstanding Receivables | outstanding_receivables | account.move | `_read_group` sum of `amount_residual_signed`, posted, out_invoice/out_refund | all-time | No |
| Pending Renewals | upcoming_renewals_count | edara.renewal.request | `search_count([('state','=','submitted')])` | submitted only | No |
| Open Maintenance | open_maintenance_count | edara.maintenance.request | `search_count([('state','not in',('done','cancelled'))])` | excludes done/cancelled | No |
| Payments This Month | recent_payments_count | account.payment | `search_count([('date','>=', month_start)])` | current calendar month only | No |

None of the counting queries scope by company/branch beyond whatever the underlying model's own record rules apply implicitly for the viewing user (no explicit `company_id`/`branch_id` filter in the dashboard's own domains).

Access: `edara.dashboard` → `group_edara_viewer` only (read=1, write=1 — the write grant exists solely to satisfy the server-action execution guard, not real data mutation, since the model has zero stored fields), create=1, unlink=0.

---

## 15. Reports Inventory

**No PDF/XLSX/QWeb reports exist anywhere in this module** (confirmed: zero matches for "ir.actions.report", "report_type", or "qweb" anywhere in the codebase). All 5 "reports" are native Odoo pivot/graph/list `ir.actions.act_window` views on `account.move`/`edara.unit` — no separate report engine.

| Report Name | Model | Type | Menu Location | Search View | Default Filters | Group By | Export |
|---|---|---|---|---|---|---|---|
| Revenue Report | account.move | pivot(default), graph, list | Reports > Revenue | view_edara_account_move_report_search | posted out_invoice/out_refund; `search_default_this_year=1` | Branch, Property, Tenant/Partner, Month | native pivot/list export only |
| Expenses Report | account.move | pivot(default), graph, list | Reports > Expenses | same | posted in_invoice/in_refund; `search_default_this_year=1` | same | native |
| Receivables Report | account.move | pivot(default), graph, list | Reports > Receivables | same | posted out_invoice/out_refund | same; pivot pre-configured Property×Partner rows, Payment Status columns | native |
| Occupancy Report | edara.unit | pivot(default), graph, list | Reports > Occupancy | view_edara_unit_report_search | none | Branch, Property, Status; pivot pre-configured Branch×Property rows, Occupancy Status columns | native |
| Tenant Ledger | account.move | list(default), pivot | Reports > Tenant Ledger | view_edara_account_move_report_search | posted + `partner_id.is_edara_tenant=True` + out_invoice/out_refund; `search_default_group_by_partner=1` | same shared search view | native; list columns: Partner, Invoice Date, Invoice Type, Property, Unit, Total(sum), Outstanding(sum), Payment Status |

Access: gated entirely by `menu_edara_reports`'s `groups="group_edara_accountant,group_edara_branch_manager"` — Property Manager and plain Viewer cannot see the Reports folder at all (menu-only gate; the underlying models' ACLs would technically allow read for Viewer, so this is purely a navigation restriction, not an ACL restriction).

---

## 16. Configuration Inventory

One Settings block exists: **Settings > EDARA Property Management > Accounting** (also reachable at `menu_edara_settings`, gated `group_edara_company_manager`). Exactly 6 configurable fields, all on `res.company`, mirrored read/write onto `res.config.settings` (pure passthrough, no logic in the settings model itself):

| Label | Technical Field | Type | Default | Effect on Business Logic | Who Can Configure |
|---|---|---|---|---|---|
| Rental Income Account | `edara_rental_income_account_id` | Many2one → account.account | none | Credited on every rent invoice; blocks rent-invoice generation (manual or cron) if unset | group_edara_company_manager |
| Late Fee Income Account | `edara_late_fee_income_account_id` | Many2one → account.account | none | Credited on every late-fee invoice; blocks "Charge Late Fee" if unset | same |
| Late Fee Amount | `edara_late_fee_amount` | Monetary (company currency) | 0.0 | Flat amount charged when staff invoke "Charge Late Fee"; blocks the action if falsy; **never applied automatically — no cron references it** | same |
| Service Charge Income Account | `edara_service_charge_income_account_id` | Many2one → account.account | none | Credited on every service-charge invoice; blocks "Create Invoices" if unset | same |
| Security Deposit Liability Account | `edara_deposit_liability_account_id` | Many2one → account.account | none | Destination account for every deposit collect/refund payment; blocks collect/refund if unset | same |
| Deposit Deduction Income Account | `edara_deposit_deduction_income_account_id` | Many2one → account.account | none | Credited (liability debited) on a deposit deduction; blocks "Deduct" if unset | same |

None of these 6 fields is DB-required — every one is enforced only at point-of-use with a `UserError` naming the specific missing account and pointing to "Settings > EDARA Property Management". This is a deliberate, consistent pattern (matches the spec's "configurable, not hardcoded, with clear blocking errors" requirement).

**Not configurable anywhere in this module (confirmed absent):** sequences (fixed in `data/edara_sequences.xml`, no UI to change prefixes/padding), branch defaults, maintenance settings/SLAs, currencies (inherited from `res.company`/contract, no EDARA-specific currency setting), property configuration defaults.

**Gap (proven):** The EDARA Settings block is reachable through **two entry points** that aren't obviously the same screen: `menu_edara_settings` (gated `group_edara_company_manager`) AND the native Settings app's own app-tab list (reachable by anyone with `base.group_system`, a *different* permission not gated by any EDARA group). A user with generic Odoo Settings access but no EDARA group membership can still reach and edit EDARA's accounting configuration via General Settings, bypassing the `group_edara_company_manager` restriction on the EDARA-menu path to the identical screen.

---

## 17. Automated Behavior (complete cron/automation inventory)

| Automation | XML ID | Frequency | Model | Method | Conditions | Result | Idempotency |
|---|---|---|---|---|---|---|---|
| Generate due rent invoices | ir_cron_edara_generate_due_invoices | Daily, active | edara.payment.schedule.line | `_cron_generate_due_invoices()` | No `invoice_id` yet AND `due_date<=today`; re-checks `contract.state=='active'` at execution (second defense layer beyond `action_terminate()` already removing future uninvoiced lines) | Creates+posts one rent `out_invoice` per eligible line, sets `invoice_id` | Raw SQL `FOR UPDATE SKIP LOCKED` lets concurrent/overlapping runs partition work instead of double-invoicing; per-line try/except with commit-or-rollback so one failure doesn't roll back the batch or get silently retried as already-invoiced |
| Expire lease contracts past end date | ir_cron_edara_expire_contracts | Daily, active | edara.lease.contract | `_cron_expire_contracts()` | `state=='active'` AND `end_date<today` | Contract→expired, unit→available, uninvoiced schedule lines deleted | `state=='active'` filter naturally excludes already-processed contracts on rerun; single-transaction field flips only, no external posting, no lock dance needed |

No other `ir.cron`, scheduled action, reminder, or cleanup job exists anywhere in the module. Renewal/maintenance reminder crons are explicitly NOT implemented (documented in `EDARA_PROJECT_STATE.md`'s "Remaining Work" as a spec-optional item deliberately not built — **Not implemented / not exposed**).

---

## 18. Required vs Optional Fields — Creation Summary

### Create Branch — Required
1. Name (`name`)
2. Code (`code`) — unique per company
3. Company (`company_id`) — defaults to current company

Optional but business-important: Branch Manager (`manager_id`), Assigned Staff (`user_ids` — branch-scoped access depends on this), Street/City/Phone/Email.

### Create Property — Required
1. Name
2. Code — unique per company
3. Branch (`branch_id`)

Optional but important: Street/City, Ownership rows (not enforced at creation, but business-critical).

### Create Ownership row — Required
1. Property (auto-filled when created from the Property form)
2. Owner (`owner_id`)
3. Ownership % (`ownership_percentage`) — 0 < x ≤ 100, and total across all active rows for a property must never exceed 100%
4. From date — defaults today

Optional: To date (empty = open-ended).

### Create Building — Required
1. Name
2. Code — unique per property
3. Property (`property_id`)

Optional: Street, Floor Count.

### Create Unit — Required
1. Name
2. Code — unique per building
3. Building (`building_id`)
4. Type (`unit_type`) — defaults Apartment
5. Occupancy (`occupancy_status`) — defaults Available (cannot be manually set to "Rented")
6. Operational State (`operational_status`) — defaults Normal

Optional but important: Area, Bedrooms, Bathrooms, Default Rent, Floor (needed for kanban grouping), Unit Number.

### Create Owner (res.partner) — Required
Just standard Contact creation (Name). `is_edara_owner` is fully derived (never manually set) — becomes True automatically once an ownership row exists. Optional: National ID/Registration No.

### Create Tenant (res.partner) — Required
Just standard Contact creation (Name). `is_edara_tenant` is fully derived — becomes True automatically once any lease contract exists (regardless of its state). Optional: National ID/Registration No.

### Create Contract — Required
1. Unit (`unit_id`)
2. Tenant (`tenant_id`)
3. Start Date
4. End Date — must be after Start Date
5. Rent (`rent_amount`) — must be > 0
6. Currency — defaults to company currency
7. Billing Frequency — defaults Monthly
8. Payment Day — defaults 1 (must be 1–28)

Optional but business-important: Deposit Required (defaults True) + Deposit Amount, Notes. System-set: Name (sequence), Status (draft), Company/Branch/Property/Building (all derived from Unit).

### Create Payment Schedule Line — Not user-created
Generated exclusively by `_generate_schedule_lines()` on contract activation/renewal (`create="0"` on the list). If created programmatically: Contract, Due Date, Amount required.

### Create Renewal Request — Required
1. Contract (`contract_id`)
2. Requested Start Date
3. Requested End Date — after start
4. Requested Rent

Optional: Tenant Message (`note`).

### Create Deposit — Required (in practice, lazily via the contract's Deposit smart button)
1. Contract
2. Amount

### Record a Deposit Transaction (wizard) — Required
- Amount always.
- Journal (`journal_id`) — required for Collect/Refund only.
- Reason (`description`) — required for Deduct only.

### Create Service Charge — Required
1. Building (`building_id`)
2. Date — defaults today
3. Allocation Method — defaults Equal

Then, before "Generate Allocation" succeeds: Total Amount>0 (Equal/Proportional), Rate per m²>0 (Per Sqm), Fixed Amount per Unit>0 (Fixed per Unit); Proportional additionally needs unit `area` set.

### Create Maintenance Request — Required (internal form)
1. Title
2. Unit
3. Priority — defaults Normal
4. Requested Date — defaults today

Portal form additionally strictly validates Unit against the tenant's own active-lease units, and always forces Tenant to the logged-in user (fields the portal never lets a tenant set: Assigned To, Vendor, Cost, Completed Date).

---

## 19. Recommended Manual Test Dependency Order

Determined from the actual foreign-key/required-field dependencies traced through §3 and §9, not the original spec's example order:

1. **Company / Branch** — `res.company` must exist (native Odoo); create `edara.branch` (needs company). Nothing else in the module can be created without at least one branch.
2. **Property** — needs a branch. Creates the analytic-account lazy-creation point later.
3. **Building** — needs a property.
4. **Unit** — needs a building. Establishes `occupancy_status=available`/`operational_status=normal` as the baseline every later test starts from.
5. **Owner (res.partner) + Ownership row** — needs a property; owner itself is just a Contact, independently creatable at any point, but the Ownership row needs the property to exist. Not required for any other model to function (contracts don't reference ownership), but should be tested for its own 100%-total constraint.
6. **Tenant (res.partner)** — independently creatable at any point (just a Contact); becomes "is_edara_tenant" only once step 7 happens.
7. **Lease Contract** — needs a Unit + a Tenant. Creating in `draft` tests the create-time validations (dates, rent>0, payment_day range). This is the first model whose *activation* has real side effects worth testing.
8. **Activate the Contract** — tests: unit→rented, schedule-line generation, the sold/under_maintenance blocking checks, the overlap-prevention constraint (requires a second contract attempt on the same unit).
9. **Payment Schedule** — auto-created by step 8; test the daily cron (`_cron_generate_due_invoices`) or manually inspect `_create_invoice()`'s blocking error if `edara_rental_income_account_id` isn't configured yet (**Configuration must be set up before this step can succeed** — test the "unconfigured account" error path first, then configure and retest).
10. **Configuration (Settings > EDARA Property Management)** — should realistically be tested EARLY (before step 9's invoice generation can succeed) alongside step 1, since 5 of its 6 fields gate invoice/payment actions used throughout steps 9–13. Listed here to flag the dependency, but in practice: configure all 6 accounts right after step 1/2 setup, then deliberately blank one at a time later to test each specific blocking error.
11. **Invoice (account.move, native)** — produced by step 9; test partial/full payment via the native "Register Payment" button, credit-note reversal via the native "Credit Note" button.
12. **Payment (account.payment, native)** — produced by step 11's Register Payment.
13. **Deposit** — needs an active Contract (created lazily via the contract's Deposit smart button, or manually). Test Collect → Refund/Deduct, and the three account-configuration blocking errors (liability account, deduction-income account).
14. **Service Charge** — needs a Building with at least one Unit under an active-tenant Contract (step 7/8 must already exist for at least one unit in the building, else "Generate Allocation" silently produces zero/fewer lines). Test all 4 allocation methods, then "Create Invoices" (needs the service-charge income account from step 10).
15. **Maintenance Request** — needs a Unit (Tenant/Contract optional — staff can log one without a tenant). Test both the internal form and the portal form (portal needs an active Contract for the logged-in tenant to have any unit selectable). Test the `action_assign` dead-code gap explicitly (confirm it truly cannot be triggered from any UI).
16. **Renewal Request** — needs an active Contract (portal or internal). Test Approve (delegates into contract renewal, same effects as step 8's `action_renew`) and Reject.
17. **Contract Expiry cron** — set a contract's `end_date` in the past (or wait) and run `_cron_expire_contracts` to test the automatic expire path, distinct from manual Terminate.
18. **Dashboard** — read-only aggregate of everything above; test last, after enough data exists in steps 1–17 to produce non-zero KPIs.
19. **Reports** — same, test last; requires posted invoices (steps 9–11) to show meaningful Revenue/Expenses/Receivables/Tenant Ledger data, and Units (step 4) for Occupancy.
20. **Security / Multi-branch / Multi-company** — should be tested throughout, not just at the end: create a second branch and a second company early, and repeat key steps (7, 8, 13) as a Viewer-tier user assigned to only one branch to confirm the record-rule scoping (§12) at every stage, not as an afterthought.
21. **Portal** — test in parallel with steps 7–16 from the tenant's perspective (a portal user with `group_edara_portal_tenant`, linked via `res.partner` to a Tenant from step 6): confirm they can only ever see their own contract/units/requests, and confirm ID-forging protection (try a known-different contract/request ID in the URL and confirm `AccessError`).

---

## 20. Potential UI / Product Gaps

Only gaps directly proven from the code (not speculation), collected from every model section above:

**Access/Security**
1. `group_edara_maintenance`'s stated intent ("assigned to them within their branches") is not enforced — no record rule restricts a maintenance staff member to only requests where `assigned_user_id` is themselves; the only enforced scoping is branch-level (§12).
2. EDARA Settings (6 accounting-account fields) is reachable via two separate entry points with different permission gates: `menu_edara_settings` (`group_edara_company_manager`) vs. the native Settings app's own tab (`base.group_system`, unrelated to any EDARA group) — a generic Odoo Settings admin with no EDARA role can still edit EDARA's accounting configuration (§16).

**Dead/unreachable code**
3. `edara.maintenance.request.action_assign(user_id)` exists in Python but is wired to zero buttons/wizards/portal routes anywhere — cannot be triggered from any UI (§3.15).

**Missing search/filter UI (systemic)**
4. Only 3 of 10+ operational list views have a custom search view (`edara.unit`, plus the 2 report search views) — Properties, Buildings, Contracts, Payment Schedule, Deposits, Service Charges, Renewal Requests, and Maintenance (despite being kanban-grouped by state) all rely on Odoo's bare auto-generated search box with no curated filters or group-bys (§6).

**Incomplete UI elements**
5. Contract statusbar (`statusbar_visible="draft,active,terminated"`) omits the two reachable states `renewed` and `expired`.
6. Renewal Request's Reject button cannot capture a decision reason in one step — the Python method supports it but no form control passes it.

**Data-integrity looseness**
7. Payment Schedule's list view does not mark `invoice_id` readonly at the column level (only the form does) — a user can inline-edit which invoice a line points to directly from the list.
8. `edara.maintenance.request` has no `unlink()` guard — unlike payment-schedule/service-charge lines, any user with delete rights can remove a request in any state including `done`, with no audit-trail protection.
9. Deposit deduction has no reversal/correction action from the UI once posted, and its journal entry gets no analytic distribution (unlike every other EDARA-generated invoice line).

**Help text / behavior mismatch**
10. `edara.deposit`'s empty-state help text claims deposits are "created automatically when a lease contract with 'Deposit Required' is activated" — the code contains no such automatic creation; a deposit only exists once someone clicks the contract's Deposit smart button at least once.

**Portal gaps**
11. No portal page exists for Invoices, Payments, Security Deposits, or Documents — a tenant can see their lease and file/view maintenance requests, but has no visibility into what they owe, have paid, or their deposit status (§13).
12. The portal maintenance detail page has no chatter/messaging — a tenant who files a request cannot see staff replies beyond the raw status field.

**Field exposure gaps**
13. `account.move`'s six EDARA tag fields (`edara_branch_id`/`edara_property_id`/`edara_building_id`/`edara_unit_id`/`edara_contract_id`/`edara_invoice_type`) have onchange logic clearly written for manual entry, but appear on no form view anywhere in the module — only as Reports pivot columns. A vendor bill has no visible field to review/set these (§3.17).
14. `res.partner`'s `is_edara_owner`/`is_edara_tenant` fields are added to the Contact form but immediately marked `invisible=1` with nothing else in that xpath block using them for conditional display — no Owner/Tenant badge is visible on the Contacts form itself (§3.19).
15. `edara.deposit`'s `branch_id`/`property_id`/`building_id` are related+stored (and used for record-rule scoping) but not shown anywhere on the deposit form.
16. `edara.service.charge`'s `branch_id`/`property_id` are visible only under Odoo's `base.group_no_one` developer toggle — an ordinary Branch Manager/Accountant cannot see which branch/property a charge belongs to on the form itself.

**Modeling inconsistencies (not bugs, but worth testing)**
17. `edara.unit.currency_id` is an independent stored field (fixed at creation) rather than related through the branch/property/building/company chain like every sibling `*_id` field — will not follow a later company-currency change.
18. `edara_late_fee_amount` is configured in the company's currency but charged onto an invoice in the contract's (possibly different) currency, with no explicit conversion code found in `action_charge_late_fee()`.
19. `edara.service.charge.action_generate_allocation()` silently skips units with no active-contract tenant — no on-screen indication of which/how many units were excluded from an allocation.
20. `edara.ownership` and `edara.deposit.transaction` both have full model/security-rule implementations but no standalone menu/action anywhere — reachable only as embedded read/edit lists inside Property and Deposit forms respectively. (Likely intentional, given both are join-table-like records, but worth a tester's awareness so they don't go looking for an "Ownership" or "Deposit Transactions" menu.)

**Implemented beyond original specification**
- Native "Register Payment" reuse for all rent/service-charge/late-fee invoices, with zero custom wrapper code — satisfies the spec's payment-registration requirement entirely through native Odoo, a deliberate simplification recorded in prior project history.
- The `edara.dashboard`'s `perm_write=1` grant, added this session, is a security-adjacent implementation detail (satisfying Odoo's own `ir.actions.server` execution guard) not anticipated by the original spec text.

**Not implemented / not exposed (per spec vs. code, confirmed by this inventory)**
- Actual Arabic `.po` translation content (translation-*readiness* is done — every string wrapped in `_()` — but no translated content exists).
- `edara.owner.settlement` (§32 of the spec) — no model, no view, no menu.
- Renewal/maintenance reminder crons — spec listed these as merely "potential"; genuinely absent from `data/edara_cron.xml`.
- A termination-reason-capture wizard — termination reason is a plain `confirm=`-prompted field passed as a Python kwarg (`action_terminate(reason=...)`), not a structured input widget; in practice the header button's `confirm=` dialog has no text-input capability, so the reason is only ever settable by directly editing `termination_reason` on the form before/after terminating, not through a dedicated capture UI.
- Portal visibility into invoices/payments/deposits (see gap #11 above — also a genuine spec-vs-implementation gap, not just a UX nicety).

---

## 21. Accuracy Statement

Every fact in this document was verified against one or more of: (a) direct reading of the current `.py`/`.xml` source files in `custom_addons/property_managment` during this session (not memory, not the spec); (b) live queries against the `odoo19_dev` PostgreSQL database (`ir_model_data`, `ir_model`, `res_groups`, `ir_cron`, `ir_act_server` row counts and names); (c) cross-referencing Odoo 19's own native source (e.g. `odoo/addons/portal/controllers/portal.py`'s `_document_check_access`, `odoo/addons/account/views/account_move_views.xml`'s native Register Payment button) where a claim depended on native framework behavior. No business logic was modified while producing this document.

---

## 22. Final Validation — Coverage Confirmation

**Models documented:** 21 — `edara.branch`, `edara.property`, `edara.building`, `edara.unit`, `edara.ownership`, `edara.lease.contract`, `edara.payment.schedule.line`, `edara.renewal.request`, `edara.lease.renewal.wizard`, `edara.deposit`, `edara.deposit.transaction`, `edara.deposit.transaction.wizard`, `edara.service.charge`, `edara.service.charge.line`, `edara.maintenance.request`, `edara.dashboard`, plus 5 extended native models (`account.move`, `account.payment`, `res.company`, `res.config.settings`, `res.partner`). Matches the DB's `ir.model` ownership count of 21 exactly.

**Form views documented:** 15 (one per model with a form, §4 table).
**List views documented:** 10 (§5 table).
**Kanban views documented:** 3 — `edara.unit`, `edara.maintenance.request`, `edara.renewal.request`.
**Search views documented:** 3 that exist (`edara.unit`, and the 2 report search views) — and the 7 that do NOT exist, explicitly enumerated (§6).
**Menus documented:** 20 of 20 (matches DB count exactly, §1).
**Actions/buttons documented:** 19 `ir.actions.act_window` + 3 `ir.actions.server` (matches DB counts exactly, §1) + every object-type form/list button across every model (§7 master table, 27 rows).
**Security groups documented:** 8 of 8 (matches DB count exactly, §12).
**Record rules documented:** all 43 (as 2 repeating patterns — 3-rule ×13 models + 4-rule portal-own ×4 models = 39+4=43, matches DB count exactly, §12).
**Cron/automations documented:** 2 of 2 (matches DB count exactly, §17).
**Portal routes/pages documented:** 7 routes across 4 page types (Leases list/detail, Maintenance list/detail/new) + the `/my` home-page extension (§13).
**Reports documented:** 5 of 5 — confirmed zero QWeb/PDF reports exist (§15).
**Accounting integrations documented:** every `account.move`/`account.payment` creation path, every configurable account, analytic accounting, currency handling, credit notes/reversals (§10).

**Confirmed UI/product gaps:** 20 distinct, individually numbered and proven gaps (§20), plus 5 confirmed "Not implemented / not exposed" spec items and 2 "Implemented beyond original specification" items.
