/** Phase 6.6 (2026-09-23): compact Paid/Overdue/Draft filter-shortcut
 * buttons on the Payment Schedule list only. These are NOT navigation - each
 * button toggles the matching named <filter> already defined in
 * view_edara_payment_schedule_line_search via the standard
 * searchModel.toggleSearchItem() API, i.e. exactly what clicking that same
 * filter in the native Search Bar dropdown already does. No domain is built
 * here, no ir.actions.act_window is created, no navigation happens - the
 * user stays on this same list, the active filter appears as a normal
 * search facet, and clearing/other Search Bar filters keep working
 * unmodified because nothing here bypasses the search model.
 *
 * Scoped to this one view only via js_class on the Payment Schedule list
 * arch, and t-inherit-mode="primary" on its template (see the .xml file) -
 * this must NEVER be "extension" mode, which would patch the shared
 * web.ListView template and affect every other list view in the backend
 * (the exact Phase 6.2 mistake this ticket forbids repeating - see Phase 6.3
 * in EDARA_PROJECT_STATE.md for the full root-cause writeup). */

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
