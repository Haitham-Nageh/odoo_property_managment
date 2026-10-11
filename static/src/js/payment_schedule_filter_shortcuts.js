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
import { useState, onWillStart, onWillUnmount, status } from "@odoo/owl";

const SHORTCUT_FILTER_NAMES = ["paid", "overdue", "draft"];

const STATE_COLOR_MAP = {
    draft: "secondary",
    paid: "success",
    overdue: "danger",
};

export class EdaraPaymentScheduleFilterShortcutsController extends ListController {
    setup() {
        super.setup();
        this._isDestroyed = false;
        this._countRequestId = 0;
        this._loadingCounts = false;
        this._needsReloadCounts = false;
        this._pendingScope = null;
        this._currentScopeKey = null;

        this.state = useState({
            counts: {
                draft: 0,
                paid: 0,
                overdue: 0,
            },
        });

        onWillStart(async () => {
            await this.loadStateCounts();
        });

        useBus(this.env.searchModel, "update", async () => {
            const domain = this.env.searchModel?.domain;
            const context = this.env.searchModel?.context;
            await this.loadStateCounts({ domain, context });
        });

        onWillUnmount(() => {
            this._isDestroyed = true;
        });
    }

    get modelParams() {
        const params = super.modelParams;
        const parentOnRootLoaded = params.hooks?.onRootLoaded;
        return {
            ...params,
            hooks: {
                ...params.hooks,
                onRootLoaded: async (root) => {
                    if (parentOnRootLoaded) {
                        await parentOnRootLoaded(root);
                    }
                    this.onRootLoaded(root);
                },
            },
        };
    }

    onRootLoaded(root) {
        if (this._isDestroyed || (status && status(this) === "destroyed")) {
            return;
        }
        const domain = root?.domain ?? this.effectiveDomain;
        const context = root?.context ?? this.effectiveContext;
        this.loadStateCounts({ domain, context });
    }

    get effectiveDomain() {
        const searchDomain = this.env.searchModel?.domain;
        if (Array.isArray(searchDomain)) {
            return searchDomain;
        }
        const rootDomain = this.model?.root?.domain;
        if (Array.isArray(rootDomain)) {
            return rootDomain;
        }
        return Array.isArray(this.props.domain) ? this.props.domain : [];
    }

    get effectiveContext() {
        const searchContext = this.env.searchModel?.context;
        if (searchContext && typeof searchContext === "object") {
            return searchContext;
        }
        const rootContext = this.model?.root?.context;
        if (rootContext && typeof rootContext === "object") {
            return rootContext;
        }
        return (this.props.context && typeof this.props.context === "object")
            ? this.props.context
            : {};
    }

    async onRecordSaved(record) {
        await super.onRecordSaved(...arguments);
        await this.loadStateCounts({ force: true });
    }

    async loadStateCounts(options = {}) {
        if (this._isDestroyed || (status && status(this) === "destroyed")) {
            return;
        }

        const domain = Array.isArray(options.domain)
            ? options.domain
            : (Array.isArray(this.effectiveDomain) ? this.effectiveDomain : []);
        const context =
            options.context && typeof options.context === "object"
                ? options.context
                : ((this.effectiveContext && typeof this.effectiveContext === "object")
                      ? this.effectiveContext
                      : {});
        const force = Boolean(options.force);

        const scopeKey = JSON.stringify([domain, context]);

        // Deduplication: if scope has not changed and not forced, skip redundant request
        if (!force && this._currentScopeKey === scopeKey) {
            return;
        }

        this._currentScopeKey = scopeKey;

        // If an aggregation request is already in-flight, record pending scope and coalesce
        if (this._loadingCounts) {
            this._needsReloadCounts = true;
            this._pendingScope = { domain, context };
            return;
        }

        this._loadingCounts = true;
        this._needsReloadCounts = false;
        this._pendingScope = null;
        const currentRequestId = ++this._countRequestId;
        const requestScopeKey = scopeKey;

        try {
            let groups;
            if (this.orm.webReadGroup) {
                const res = await this.orm.webReadGroup(
                    "edara.payment.schedule.line",
                    domain,
                    ["state"],
                    ["__count"],
                    { context }
                );
                groups = res && res.groups ? res.groups : res;
            } else {
                groups = await this.orm.call(
                    "edara.payment.schedule.line",
                    "read_group",
                    [],
                    { domain, fields: ["state"], groupby: ["state"], context }
                );
            }

            // Discard obsolete response if destroyed, newer request dispatched, or scope changed
            if (
                this._isDestroyed ||
                (status && status(this) === "destroyed") ||
                currentRequestId !== this._countRequestId ||
                requestScopeKey !== this._currentScopeKey
            ) {
                return;
            }

            const counts = { draft: 0, paid: 0, overdue: 0 };
            for (const group of groups || []) {
                if (group && group.state in counts) {
                    counts[group.state] = group.__count ?? group.state_count ?? 0;
                }
            }
            Object.assign(this.state.counts, counts);
        } catch (e) {
            console.error("Failed to load payment schedule state counts", e);
            this._currentScopeKey = null;
        } finally {
            this._loadingCounts = false;
            if (
                this._needsReloadCounts &&
                !this._isDestroyed &&
                (!status || status(this) !== "destroyed")
            ) {
                const nextScope = this._pendingScope;
                this._pendingScope = null;
                this.loadStateCounts({ ...nextScope, force: true });
            }
        }
    }

    get edaraFilterShortcuts() {
        const items = Object.values(this.env.searchModel.searchItems).filter(
            (item) => item.type === "filter" && SHORTCUT_FILTER_NAMES.includes(item.name)
        );
        return SHORTCUT_FILTER_NAMES.map((name) => items.find((item) => item.name === name))
            .filter(Boolean)
            .map((item) => ({
                id: item.id,
                name: item.name,
                description: item.description,
                color: STATE_COLOR_MAP[item.name] || "primary",
                count: this.state.counts[item.name] ?? 0,
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
