# Odoo 19 Pattern: Search-Filter Shortcut Buttons on a List View

**Source project:** EDARA Property Management (`property_managment`), Phase 6.6 / 6.6 Hotfix.
**Concrete example used throughout:** the `Paid | Overdue | Draft` buttons above the Payment
Schedule list (`edara.payment.schedule.line`).
**Status:** working, tested, live-validated in a real Odoo 19 Community environment.

This document is a **reusable developer asset**. It explains a small, safe, native pattern for
adding compact "filter shortcut" buttons to a single Odoo 19 list view — and, just as
importantly, documents a mistake made earlier in this same project so it is never repeated.

---

## 1. Use Case

The UX goal is a small row of buttons above one list view, e.g.:

```
[ Paid ]  [ Overdue ]  [ Draft ]
```

Clicking a button must behave **exactly as if the user had opened the native Search Bar and
clicked that same filter**:

- stay on the current List View
- activate an **existing** Search Filter (not a new one built ad hoc)
- update the native Search Bar state
- show the active filter as a normal search facet/chip
- preserve native pagination
- let the user clear the filter normally
- **not** open another action
- **not** navigate to another page
- **not** create a second, duplicate, filtered List View

### Wrong approach

```
Button click → build a domain in JS → open a NEW ir.actions.act_window with that domain
```

This was tried earlier in this project (see §9) for a *different* feature (Units/Contracts
"Quick Action Bar", Phase 6.2). It technically filters, but it is navigation: the user leaves
the current view, a new action/breadcrumb entry is created, and the result has nothing to do
with the Search Bar the rest of the page still shows. It was explicitly rejected and removed
(Phase 6.5) for not matching the intended UX.

### Correct approach (this pattern)

```
Button click → searchModel.toggleSearchItem(id) → the SAME existing native <filter>
```

No domain is built in JS. No action is created. The button is a thin trigger for machinery
Odoo's own Search Bar already owns and already renders correctly (facets, clearing, combining
with other filters, pagination — all free).

---

## 2. Architecture

```
Search View  <filter name="paid" domain="[('state','=','paid')]"/>
        │  (parsed at runtime into a searchItem, keyed by its "name")
        ▼
searchModel.searchItems   { id: 7, type: "filter", name: "paid", description: "Paid", domain: "..." }
        │
        │  button.onClick → searchModel.toggleSearchItem(7)
        ▼
searchModel.query          [{ searchItemId: 7 }]   ← same array the Search Bar itself reads
        │
        ▼
List re-renders filtered, facet chip appears in the Search Bar, pagination/clear all native
```

Components involved, each with a single job:

| Piece | Role |
|---|---|
| `<search>` view `<filter>` records | Define the *real*, only source of truth for what "Paid"/"Overdue"/"Draft" mean (a domain). |
| Dedicated `js_class` | Opts exactly one list view arch into the custom controller. Every other list view is untouched. |
| Dedicated `ListController` subclass | Finds the matching `searchItem`s by name and exposes them to the template; forwards clicks to `toggleSearchItem`. |
| Dedicated OWL template (`t-inherit-mode="primary"`) | Injects the button row into that one view's rendering only. |
| Dedicated CSS | Compact, native-looking button row. |
| `__manifest__.py` assets | Ships the JS/XML/CSS as part of the normal backend bundle. |

### Why scoped to one view, not global `web.ListView`

Odoo's `ListController.template` normally resolves to the shared `"web.ListView"` OWL template —
the same one every list view in the backend uses. If you patch that template in place, you
affect every list view, not just the one you meant to change. The scoping mechanism that
prevents this is `t-inherit-mode="primary"` (see §5) plus a `js_class` that only the intended
view opts into. Nothing here ever modifies `"web.ListView"` itself.

---

## 3. Search View

A model needs `<filter>` records that already exist, or need to be added, for each shortcut.
**Check first — do not assume they exist.** In this project, `edara.payment.schedule.line` had
*no* dedicated search view at all before this feature; the filters below were created for it.

Actual project implementation (`views/payment_schedule_line_views.xml`):

```xml
<record id="view_edara_payment_schedule_line_search" model="ir.ui.view">
    <field name="name">edara.payment.schedule.line.search</field>
    <field name="model">edara.payment.schedule.line</field>
    <field name="arch" type="xml">
        <search string="Payment Schedule">
            <field name="contract_id"/>
            <field name="description"/>
            <filter string="Paid" name="paid" domain="[('state', '=', 'paid')]"/>
            <filter string="Overdue" name="overdue" domain="[('state', '=', 'overdue')]"/>
            <filter string="Draft" name="draft" domain="[('state', '=', 'draft')]"/>
            <group>
                <filter string="Status" name="group_by_state" context="{'group_by': 'state'}"/>
            </group>
        </search>
    </field>
</record>
```

...and the search view must be wired onto the action (also missing before this feature):

```xml
<record id="action_edara_payment_schedule_line" model="ir.actions.act_window">
    ...
    <field name="search_view_id" ref="view_edara_payment_schedule_line_search"/>
    ...
</record>
```

Field meanings:

- **`name`** — the technical identifier. This is what the JS looks up by (see §4). It is
  **not** shown to the user.
- **`string`** — the human-readable label. Also used as the button's own label in this pattern
  (`item.description`, see §4), so it doubles as both the Search Bar label and the button text.
- **`domain`** — the actual filtering logic. This is the *only* place the filtering rule is
  defined. The JS never repeats or reconstructs it.

### How the search item is resolved at runtime

Odoo's `SearchArchParser` (`@web/search/search_arch_parser.js`) parses each `<filter
name="...">` into an in-memory `searchItem` object and **preserves the `name` attribute on
it** (`preSearchItem.name = name`). The JS controller (§4) looks up items by exactly that
`name`, not by a hardcoded numeric id (ids are assigned dynamically at parse time and are not
stable across reloads).

---

## 4. JavaScript

Full, actual file (`static/src/js/payment_schedule_filter_shortcuts.js`):

```js
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useBus } from "@web/core/utils/hooks";

const SHORTCUT_FILTER_NAMES = ["paid", "overdue", "draft"];

export class EdaraPaymentScheduleFilterShortcutsController extends ListController {
    setup() {
        super.setup();
        useBus(this.env.searchModel, "update", this.render);
    }

    get edaraFilterShortcuts() {
        const items = Object.values(this.env.searchModel.searchItems).filter(
            (item) => item.type === "filter" && SHORTCUT_FILTER_NAMES.includes(item.name)
        );
        return SHORTCUT_FILTER_NAMES.map((name) => items.find((item) => item.name === name))
            .filter(Boolean)
            .map((item) => ({
                id: item.id,
                description: item.description,
                isActive: this.env.searchModel.query.some((q) => q.searchItemId === item.id),
            }));
    }

    onEdaraFilterShortcutClick(searchItemId) {
        this.env.searchModel.toggleSearchItem(searchItemId);
    }
}
EdaraPaymentScheduleFilterShortcutsController.template =
    "property_managment.PaymentScheduleFilterShortcutsListView";

export const edaraPaymentScheduleFilterShortcutsListView = {
    ...listView,
    Controller: EdaraPaymentScheduleFilterShortcutsController,
};

registry
    .category("views")
    .add("edara_payment_schedule_filter_shortcuts", edaraPaymentScheduleFilterShortcutsListView);
```

Section by section:

- **Imports** — `registry` (to register the new view type), `listView` (the native list view
  definition to extend), `ListController` (the base class to subclass), `useBus` (standard OWL
  hook to subscribe to an event bus). All four are stock `@web` imports; nothing custom.
- **`SHORTCUT_FILTER_NAMES`** — project-specific list of the `<filter name="...">` values to
  surface as buttons, in display order. This is the one line you change per project/model.
- **`EdaraPaymentScheduleFilterShortcutsController extends ListController`** — the dedicated
  controller. It adds *no* new data-fetching, no new routes, nothing beyond what native
  `ListController` already does — it only exposes a getter and a click handler to its template.
- **`useBus(this.env.searchModel, "update", this.render)`** — re-renders the button row whenever
  the search model changes (a filter toggled anywhere — via this button or the native Search
  Bar — updates the "active" highlight everywhere consistently). This is the exact same idiom
  Odoo's own `search_bar.js`/`search_panel.js`/`search_bar_menu.js` use internally.
- **`get edaraFilterShortcuts()`** — **how the buttons locate the corresponding search filter**:
  it reads `this.env.searchModel.searchItems` (an object keyed by dynamically-assigned numeric
  id), filters to `type === "filter"` items whose `name` is one of `SHORTCUT_FILTER_NAMES`, and
  re-orders them to match the declared order. Each result becomes `{id, description, isActive}`
  — `id` is what `toggleSearchItem` needs, `description` is the button's label (reusing the
  filter's own `string=` from the XML — no separate label list to keep in sync), `isActive` is
  computed the same way Odoo's own internal `_enrichItem()` computes it
  (`query.some(q => q.searchItemId === id)`).
- **What happens if a filter cannot be found**: `.filter(Boolean)` after the `.find(...)` call
  silently drops any name with no matching search item. A button for a missing filter simply
  never renders — this fails soft, not with an error. (If **none** of the three are found, the
  template's own `t-if="edaraFilterShortcuts.length"` hides the whole row — see §5.)
- **`onEdaraFilterShortcutClick(searchItemId)`** — **the entire click handler**. It calls
  `this.env.searchModel.toggleSearchItem(searchItemId)` and nothing else. `toggleSearchItem` is
  a native `SearchModel` method (`@web/search/search_model.js`) that adds or removes a
  `{searchItemId}` entry from `searchModel.query` — the exact same array the Search Bar's own
  filter dropdown mutates when a user clicks a filter there. **Why no domain is manually
  constructed here**: the domain already lives on the `<filter>` in the search view (§3); this
  handler never needs to know it.
- **How the current List View is preserved / how multiple buttons are handled**: neither is
  special-cased. Because the click only touches `searchModel.query` (shared page-level state,
  not a route or action), nothing about "which view/page we're on" is ever touched. Multiple
  buttons are just multiple entries in the same array of `{id, description, isActive}` objects,
  rendered by one `t-foreach` in the template (§5) — there is no per-button logic to duplicate.
- **Registration** — `EdaraPaymentScheduleFilterShortcutsController.template = "..."` points the
  controller at the dedicated template (§5). `edaraPaymentScheduleFilterShortcutsListView`
  spreads the native `listView` definition and only overrides `Controller`. The final
  `registry.category("views").add("edara_payment_schedule_filter_shortcuts", ...)` call is what
  makes the `js_class="edara_payment_schedule_filter_shortcuts"` attribute on the list arch (§7)
  resolvable at runtime — **the string here and the `js_class` value in the view XML must be
  byte-for-byte identical**, this is the single most common source of the `KeyNotFoundError`
  documented in §8/§12.

### Reusable vs. project-specific

| Reusable as-is | Project-specific (change per project) |
|---|---|
| The whole `EdaraPaymentScheduleFilterShortcutsController` class shape (rename the class) | `SHORTCUT_FILTER_NAMES` values |
| The `useBus(...searchModel, "update", this.render)` line | The class name itself |
| The `edaraFilterShortcuts` getter logic | The `template` string |
| The `onEdaraFilterShortcutClick` method body | The `registry.category("views").add(...)` key |
| The `{...listView, Controller: ...}` spread pattern | |

---

## 5. OWL/XML Template

Full, actual file (`static/src/js/payment_schedule_filter_shortcuts.xml`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="property_managment.PaymentScheduleFilterShortcutsListView" t-inherit="web.ListView" t-inherit-mode="primary">
        <xpath expr="//t[@t-component='props.Renderer']" position="before">
            <div class="o_edara_schedule_filter_shortcuts" t-if="edaraFilterShortcuts.length">
                <button t-foreach="edaraFilterShortcuts" t-as="item" t-key="item.id"
                        type="button"
                        t-attf-class="btn btn-sm o_edara_schedule_filter_shortcut {{ item.isActive ? 'btn-primary' : 'btn-outline-primary' }}"
                        t-on-click="() => this.onEdaraFilterShortcutClick(item.id)">
                    <t t-esc="item.description"/>
                </button>
            </div>
        </xpath>
    </t>
</templates>
```

- **How the buttons are inserted**: an `<xpath expr="//t[@t-component='props.Renderer']"
  position="before">` finds the exact node where the native `web.ListView` template mounts its
  Renderer (the actual records grid, below the control panel/search bar), and inserts the
  button row immediately before it. This is a stable, confirmed-correct target inside Odoo 19's
  real `web.ListView` template.
- **How the template is scoped**: via `t-name="property_managment.PaymentScheduleFilterShortcutsListView"`
  — a project- and feature-specific name, distinct from `web.ListView` itself. Only the
  Controller that explicitly sets `.template = "property_managment.PaymentScheduleFilterShortcutsListView"`
  (§4) ever resolves to this template. Every other list view keeps using `"web.ListView"`
  untouched.
- **`t-inherit-mode="primary"`** — this is the critical attribute. In Odoo's asset-bundling
  pipeline (`odoo/addons/base/models/assetsbundle.py`), a template with `t-inherit-mode="primary"`
  is compiled into its **own, independent, separately-named** template
  (`registerTemplate("<t-name>", ...)`). It does not touch the template it inherits from.
- **Why `t-inherit-mode="extension"` must never be used here** — `"extension"` mode is compiled
  via `registerTemplateExtension("<t-inherit target>", ...)`, which **patches the target
  template in place**, globally, for every consumer of that template in the whole backend. If
  the target is the shared `"web.ListView"` template (as it is here), *every* list view in the
  backend — not just the one you meant to change — silently gets your injected node. See §9 for
  the real incident this caused in this exact project.

---

## 6. CSS

Full, actual file (`static/src/css/payment_schedule_filter_shortcuts.css`):

```css
.o_edara_schedule_filter_shortcuts {
    display: flex;
    gap: 4px;
    padding: 4px 16px;
}

.o_edara_schedule_filter_shortcut {
    padding: 2px 10px;
    font-size: .8125rem;
}
```

Design principles:

- **Compact, minimal vertical space** — small `padding`/`font-size` on the buttons themselves,
  a single thin `flex` row, not a card/panel.
- **Native Odoo-compatible appearance** — uses Bootstrap's own `btn`/`btn-sm`/`btn-primary`/
  `btn-outline-primary` classes (set in the template, §5) rather than inventing new visual
  language; the CSS here only adjusts spacing/sizing, not color/shape.
- **No oversized action panel** — deliberately the opposite of an earlier design in this same
  project (the removed Phase 6.2 "Quick Action Bar", which rendered larger badge-style buttons
  with counts). This pattern is a plain compact filter-shortcut row, matching what a
  reviewer explicitly asked for ("No unnecessary large panel or excessive spacing").
- **Easy to adapt to other clients** — the two selectors are scoped to a project-specific class
  name (`.o_edara_schedule_filter_shortcuts`), so copying this file to another project only
  requires a find/replace of that one class name (and matching it in the template, §5).

---

## 7. Manifest / Assets

`__manifest__.py` excerpt (actual project state):

```python
'assets': {
    'web.assets_backend': [
        'property_managment/static/src/css/edara_dashboard.css',
        'property_managment/static/src/css/payment_schedule_filter_shortcuts.css',
        'property_managment/static/src/js/payment_schedule_filter_shortcuts.js',
        'property_managment/static/src/js/payment_schedule_filter_shortcuts.xml',
    ],
},
```

- **Which bundle**: `web.assets_backend` — the standard bundle for the logged-in Odoo backend
  (not `web.assets_frontend`, which is the public/portal site bundle, and not
  `web.assets_backend_lazy`, a separate lazily-loaded bundle).
- **Why all three files must be in the same bundle**: the JS registers the `js_class` key at
  module-evaluation time; the XML template must exist in the same runtime for
  `Controller.template = "..."` to resolve; the CSS only matters visually but is conventionally
  shipped alongside. If any one of the three is missing from the manifest's asset list, the
  others being present is not enough — e.g. XML present without the JS registering it produces
  an inert, unused template; JS present without the XML produces a `TemplateNotFoundError`, not
  the `KeyNotFoundError` covered here.
- **Common causes of `KeyNotFoundError: Cannot find key "..." in the "views" registry`**:
  1. The `js_class` string on the view arch and the string passed to
     `registry.category("views").add(...)` differ (typo, copy-paste drift).
  2. The JS file is not listed in `__manifest__.py`'s `assets` at all.
  3. The JS file *is* listed, but the module hasn't been upgraded (`-u <module>`) since it was
     added — Odoo does not hot-reload manifest asset-list changes into an already-running
     server process's served bundle without a real upgrade or restart.
  4. The compiled bundle attachment (`ir.attachment`, cached by content hash) is stale/missing
     and the browser is still running an old, already-loaded bundle from before the file
     existed (a real dev-mode incident hit in this exact project — see §12 for the full,
     evidence-based diagnosis process used to resolve it, and §8 for the mechanism).
- **Importance of upgrading/regenerating assets after changing frontend code**: after adding or
  editing any file in `assets`, run a module upgrade (`odoo-bin -d <db> -u <module>
  --stop-after-init`) so the database and any freshly-started server reflect the change. A
  *live, already-running* server process may also need its own asset bundle to be freshly
  regenerated (see §12) — editing files on disk alone does not retroactively update either the
  database's cached view definitions or a running process's already-served bundle.
- **How to verify the actual compiled bundle** (do this from an `odoo-bin shell` session, not
  by assuming from source):

  ```python
  js_bundle = env['ir.qweb']._get_asset_bundle('web.assets_backend', css=False, js=True)
  js_content = ''.join(a.raw.decode('utf-8', errors='replace') for a in js_bundle.js())

  # Registered as its own independent template (correct):
  assert 'registerTemplate("property_managment.PaymentScheduleFilterShortcutsListView"' in js_content
  # Never patched into the shared template (the Phase 6.2 mistake, §9):
  assert 'registerTemplateExtension("web.ListView"' not in js_content
  ```

  For a bundle actually served by a **live, already-running** process, go one level further and
  fetch the real HTTP URL directly (`curl http://localhost:8069/web/assets/<hash>/web.assets_backend.min.js`)
  rather than trusting a separate script's in-process check — the two can diverge (§12).

---

## 8. Registry / `js_class` Explanation

```text
view arch:  js_class="edara_payment_schedule_filter_shortcuts"
                    │
                    ▼
       registry.category("views")            ← a runtime, client-side (browser JS) registry
                    │   .get("edara_payment_schedule_filter_shortcuts")
                    ▼
   edaraPaymentScheduleFilterShortcutsListView   ← { ...listView, Controller: ... }
                    │
                    ▼
   EdaraPaymentScheduleFilterShortcutsController   ← what actually renders/behaves
```

The `js_class` attribute on a view's XML arch and the string key passed to
`registry.category("views").add(<key>, ...)` in the JS **must match exactly, character for
character**. There is no compile-time or server-side check that they match — the connection is
made entirely at runtime, in the browser, by string lookup.

### The error encountered in this project

```text
KeyNotFoundError: Cannot find key "edara_payment_schedule_filter_shortcuts" in the "views" registry
```

**Investigation order that correctly diagnosed it** (do this before touching any source file):

1. **Check the database view definition first**, not the source tree. `ir.ui.view.arch_db`
   is what the server actually serves; a source file can be correct while the database still
   has an older/different version if a module upgrade wasn't run.

   ```sql
   SELECT id, name, arch_db::text ILIKE '%js_class%' FROM ir_ui_view
   WHERE name = '<your view name>';
   ```

2. **Check whether the exact key string appears in the compiled JS bundle** (§7's verification
   snippet). If it's missing, the registration never ran or was never shipped.
3. **Only if both of the above are correct**, suspect a stale *already-loaded* asset bundle in
   a specific browser tab/server process — i.e. the source and the database are both right, but
   whatever bytes were actually served to that particular running client are not.

**What was actually found in this project**: the source code and the database view definition
were **both already correct** — proven directly, not assumed. The fault was that no
`web.assets_backend.min.js` (non-lazy) attachment existed in the database at the moment the
error was reported; a live server process had a stale or incomplete bundle cached from before
the feature's files existed. The fix was to force a fresh, correctly-verified bundle to be
regenerated and confirm — via a **real HTTP request against the actual running server**, not
just a script — that it now serves correctly. No `js_class`, registration key, or template
attribute ever needed to change. See §12 for the full troubleshooting checklist this produced.

**The lesson**: don't assume "asset cache" as the first guess, and don't assume "source is
correct" either — check the database, then the compiled bundle content, then (only if those
check out) the actually-served bytes of the specific process in question, in that order, with
evidence at each step.

---

## 9. Important: Do Not Repeat the Global ListView Mistake

An earlier feature in this same project (Phase 6.2, "Units/Contracts Quick Action Bar") used:

```xml
<t t-name="..." t-inherit="web.ListView" t-inherit-mode="extension">
```

`"extension"` mode does not create an independent template — it calls
`registerTemplateExtension("web.ListView", ...)`, which **patches the one shared `web.ListView`
template that every native list view in the entire backend uses**, regardless of `js_class`.

The injected node in that case was a `<div t-if="someControllerState.items.length">`. Because
the patch applied globally, it rendered inside **every** list view's template — but only the
one custom Controller actually defined `someControllerState` in its `setup()`. Every other,
unrelated list view (Properties, Buildings — models that never opted into this feature at all)
used the plain native `ListController`, which has no such property, so the inherited
`t-if="someControllerState.items.length"` threw:

```text
Cannot read properties of undefined (reading 'items')
```

...on pages that had nothing to do with the feature being built. This was traced (Phase 6.3 in
this project) directly to `t-inherit-mode`'s actual compiled behavior in
`odoo/addons/base/models/assetsbundle.py`, not guessed.

**The corrected approach, used throughout this document**: `t-inherit-mode="primary"` (§5),
which creates an independent, separately-named template that only a Controller explicitly
opting in via `.template = "..."` ever resolves to. Every other list view is structurally
guaranteed — not just assumed — to keep using the untouched native template.

**Rule for future work**: whenever `t-inherit="web.ListView"` appears, `t-inherit-mode` must be
`"primary"`. Never `"extension"` against a template shared by other, unrelated views.

---

## 10. Reusable Client Checklist

### Requirements

- [ ] Target model identified
- [ ] Existing Search View inspected (does it exist at all? what filters does it already have?)
- [ ] Existing filters identified by their technical `name=` (not just their label)
- [ ] Filter technical values (domain, state values, etc.) confirmed from the actual model code — never guessed
- [ ] Dedicated `js_class` chosen (project- and feature-specific, not reused from another feature)
- [ ] Dedicated `ListController` subclass
- [ ] Dedicated OWL template
- [ ] `t-inherit-mode="primary"` (never `"extension"` against a shared template)
- [ ] No global `web.ListView` patch introduced
- [ ] Search filters defined in XML (added if they didn't already exist)
- [ ] Buttons call `searchModel.toggleSearchItem(id)` — no domain built in JS
- [ ] No `ir.actions.act_window` created for the shortcut buttons
- [ ] JS/XML/CSS all included in `__manifest__.py`'s `assets`
- [ ] Module upgraded (`-u <module>`) after adding/changing the view XML and assets
- [ ] Compiled asset bundle verified (contains the registration, does not contain a
      `registerTemplateExtension` against a shared template)
- [ ] Browser tested (or, if unavailable, the strongest available non-browser equivalent —
      real HTTP fetch of the actual served bundle — performed and documented as a limitation)
- [ ] Search facet verified to appear when a button is clicked
- [ ] Clear filter verified to restore the unfiltered list
- [ ] Pagination verified to keep working under an active shortcut filter
- [ ] Regression tested: every *other* list view in the module confirmed to still have no
      trace of the new `js_class`

---

## 11. How to Adapt It to Another Model

This is a documentation-only example. **Nothing in the actual project was changed to add
this.**

```text
Target Model:      sale.order
Existing Filters:  quotation (state = 'draft' or 'sent'), confirmed (state = 'sale'),
                   cancelled (state = 'cancel')
```

What needs to change:

- **Model** — `res_model` on the list view / wherever the search view is defined.
- **Search view** — add or reuse `<filter name="quotation" domain="[...]"/>`,
  `<filter name="confirmed" domain="[...]"/>`, `<filter name="cancelled" domain="[...]"/>`
  (or whatever the model's own state values actually are — confirm from the model's Python
  `selection`, don't assume).
- **Filter names** — the `SHORTCUT_FILTER_NAMES` array in the JS must list exactly those
  `name=` values.
- **Filter domains** — live only in the XML `<filter domain="...">`, never duplicated in JS.
- **Button labels** — come from each filter's own `string=` (via `item.description`); no
  separate label list to maintain if you follow this pattern as-is.
- **`js_class`** — a new, unique string, e.g. `sale_order_filter_shortcuts` (must not collide
  with any other registered key in the whole database/module ecosystem — a per-project/
  per-feature name is safest).
- **Controller/template names** — e.g. `SaleOrderFilterShortcutsController` /
  `your_module.SaleOrderFilterShortcutsListView`.

What stays conceptually identical:

- A dedicated `ListController` subclass shape (setup → useBus → getter → click handler).
- `SearchModel` / `toggleSearchItem` as the *only* mechanism used to apply a filter.
- `t-inherit-mode="primary"` scoping — never touch the shared template.
- The `{...listView, Controller: YourController}` registration pattern.
- The manifest asset-bundle placement (`web.assets_backend`, all three files together).
- The testing strategy (§13) — structural view/registry checks + a live/real-bundle check +
  (when available) a real browser click-through.

---

## 12. Troubleshooting

### `KeyNotFoundError: Cannot find key "..." in the "views" registry`

Likely causes, roughly in order of how often each turns out to be the real one:

1. **Module not upgraded** after the view XML (`js_class=...`) or the manifest's `assets` list
   changed. Run `odoo-bin -d <db> -u <module> --stop-after-init`.
2. **`js_class` string mismatch** between the view arch and the `registry.category("views").add(<key>, ...)`
   call — check both literally, character for character.
3. **JS file not actually in the manifest's `assets` list** (or in the wrong bundle, e.g.
   `web.assets_frontend` instead of `web.assets_backend`).
4. **JS module execution failure** — a runtime (not syntax) error earlier in the same file can
   prevent the `registry.category("views").add(...)` line from ever running. `node --check`
   only catches syntax errors, not this class of bug — inspect the actual compiled bundle
   content (§7) to confirm the registration call is genuinely present.
5. **Stale/missing compiled asset bundle** on a specific already-running server process or an
   already-loaded browser tab. Diagnose with the order in §8: database first, then bundle
   content, then the actually-served bytes of that specific process — don't jump straight to
   "clear the cache" without evidence. (This was the actual cause in this project — see §8.)

### `Cannot read properties of undefined (reading '...')` on an *unrelated* list view

Potential cause: a `t-inherit-mode="extension"` against a **shared** template (most commonly
`web.ListView`) is leaking a property/getter that only your Controller defines into every
consumer of that template. See §9 for the exact incident and root cause in this project.
Fix: change to `t-inherit-mode="primary"` and give the template its own distinct `t-name`.

### Buttons open another page / a new action

Cause: implemented as `ir.actions.act_window` (or any `doAction()`/navigation call) instead of
the Search Model mechanism.

Correct solution: replace the click handler with `this.env.searchModel.toggleSearchItem(id)`
against an existing named `<filter>` (§3/§4). Never build or open an action for this UX.

---

## 13. Testing Strategy

### Automated

- **Search/filter definitions**: assert the search view's arch contains each expected
  `<filter name="...">` with the exact expected `domain=`.
- **Registry wiring**: assert the list view's arch contains the expected `js_class="..."`.
- **`js_class` isolation**: assert no *other* view in the module references the new `js_class`
  — both spot-checks of specific known views and, ideally, a full sweep
  (`ir.ui.view.search([('arch_db', 'like', '<js_class>')])` asserting exactly one match).
- **No unintended actions**: assert the model's `ir.actions.act_window` count is unchanged
  (no new action was created for the shortcut feature).
- **Compiled asset registration**: from a test, fetch the real compiled bundle
  (`env['ir.qweb']._get_asset_bundle('web.assets_backend', css=False, js=True).js()`) and
  assert it contains `registerTemplate("<your template name>"` and does **not** contain
  `registerTemplateExtension("web.ListView"`.

### Live (against a real database, ideally a real server/browser)

- Click each shortcut button; confirm the list re-filters.
- Confirm the active filter appears as a facet/chip in the native Search Bar.
- Confirm the filtered record count/content matches a direct `search_count()`/`search()` with
  the same domain.
- Confirm clearing the filter (via the facet's own "x" or the Search Bar's clear-all) restores
  the full list.
- Confirm pagination still works normally under an active shortcut filter.
- Open every *other* list view in the module and confirm no console error and no trace of the
  new `js_class`.
- Read the actual browser console for JS/Owl errors, if browser tooling is available.

### Why both matter

Automated tests catch structural regressions instantly and run in CI, but they cannot observe
what a browser actually receives and executes — a stale compiled bundle (§8/§12) is invisible
to a Python-level test that only inspects source files or even a freshly-generated in-process
bundle. Live validation against the actually-served bytes of a real running process is what
caught (and, combined with the automated tests, definitively ruled out several wrong
hypotheses for) the real incident documented in §8/§9.

---

## 14. Reusable Asset Summary

### Generic / reusable

```text
ListController subclass pattern (setup/useBus/getter/click-handler shape)
SearchModel filter activation (searchModel.toggleSearchItem)
OWL button-row template pattern (t-inherit-mode="primary", xpath before props.Renderer)
CSS pattern (compact flex row, native Bootstrap button classes)
Search View <filter> pattern (name/string/domain)
Manifest asset-bundle placement pattern (web.assets_backend, JS+XML+CSS together)
Testing checklist (§13)
Troubleshooting checklist (§12)
Diagnosis-before-editing discipline (§8): database → compiled bundle → served bytes
```

### EDARA Payment Schedule specific (do not copy verbatim into another project)

```text
Model name: edara.payment.schedule.line
Filter names: paid / overdue / draft
Filter domains: state = 'paid' / 'overdue' / 'draft'
js_class value: edara_payment_schedule_filter_shortcuts
Controller class name: EdaraPaymentScheduleFilterShortcutsController
Template name: property_managment.PaymentScheduleFilterShortcutsListView
CSS class names: .o_edara_schedule_filter_shortcuts / .o_edara_schedule_filter_shortcut
```

When reusing this pattern for a different client/project, copy the *generic* column's shape and
replace every value in the *EDARA-specific* column with names appropriate to that project's own
model, filters, and naming conventions.
