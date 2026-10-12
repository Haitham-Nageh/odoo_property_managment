/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";

const ALLOWED_METHODS = [
    "action_view_contracts_active",
    "action_view_contracts_scheduled",
    "action_view_contracts_draft",
    "action_view_contracts_renewed",
    "action_view_contracts_terminated",
    "action_view_contracts_expired",
    "action_view_contracts_cancelled",
];

const MIN_PERCENT_SHARE = 15;

const EMPTY = { total: 0, groups: [] };

export class EdaraLifecycleBarField extends Component {
    static template = "property_managment.EdaraLifecycleBarField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.isProcessingClick = false;
    }

    get chartData() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) {
            return EMPTY;
        }
        try {
            return typeof raw === "string" ? JSON.parse(raw) : raw;
        } catch {
            return EMPTY;
        }
    }

    /** Non-zero segments, in group order, for the proportional bar. */
    get visibleSegments() {
        return this.chartData.groups.flatMap((g) => g.segments).filter((s) => s.count > 0);
    }

    /** Segments narrower than this share keep only their count; the percentage stays in the tooltip/legend. */
    showPercent(seg) {
        return seg.percent >= MIN_PERCENT_SHARE;
    }

    segmentTitle(seg) {
        return `${seg.label}: ${seg.count} (${seg.percent}%)`;
    }

    async onSegmentClick(actionMethod) {
        if (this.isProcessingClick || !ALLOWED_METHODS.includes(actionMethod)) {
            return;
        }
        this.isProcessingClick = true;
        try {
            if (this.props.record && typeof this.props.record.save === "function" && this.props.record.isDirty) {
                await this.props.record.save();
            }
            const resId = this.props.record.resId;
            if (!resId) {
                return;
            }
            const action = await this.orm.call("edara.dashboard", actionMethod, [[resId]], {
                context: this.props.record.context,
            });
            if (action) {
                await this.action.doAction(action);
            }
        } finally {
            this.isProcessingClick = false;
        }
    }
}

export const edaraLifecycleBarField = {
    component: EdaraLifecycleBarField,
    supportedTypes: ["text"],
};

registry.category("fields").add("edara_lifecycle_bar", edaraLifecycleBarField);
