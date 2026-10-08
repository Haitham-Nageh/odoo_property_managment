/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

export class EdaraBranchFilterWidget extends Component {
    static template = "property_managment.EdaraBranchFilterWidget";
    static props = {
        ...standardFieldProps,
    };

    get allBranchesLabel() {
        return _t("All Branches");
    }

    get currentBranchId() {
        const val = this.props.record.data[this.props.name];
        if (!val) {
            return false;
        }
        if (typeof val === "object") {
            if ("id" in val) {
                return val.id;
            }
            if (Array.isArray(val)) {
                return val[0];
            }
        }
        if (typeof val === "number") {
            return val;
        }
        return false;
    }

    get isAllBranchesSelected() {
        return !this.currentBranchId;
    }

    get accessibleBranches() {
        const list = this.props.record.data.accessible_branch_ids;
        if (!list) {
            return [];
        }
        if (list.records && Array.isArray(list.records)) {
            return list.records.map((rec) => ({
                id: rec.resId || rec.data.id,
                name: rec.data.display_name || rec.data.name || String(rec.resId),
            }));
        }
        if (Array.isArray(list)) {
            return list.map((item) => {
                if (Array.isArray(item)) {
                    return { id: item[0], name: item[1] || String(item[0]) };
                }
                if (typeof item === "object" && item !== null) {
                    return {
                        id: item.id || item.resId,
                        name: item.display_name || item.name || String(item.id),
                    };
                }
                return { id: item, name: String(item) };
            });
        }
        return [];
    }

    async onSelectBranch(branch) {
        if (this.props.readonly) {
            return;
        }
        if (!branch) {
            if (this.isAllBranchesSelected) {
                return;
            }
            await this.props.record.update({
                [this.props.name]: false,
            });
        } else {
            if (this.currentBranchId === branch.id) {
                return;
            }
            await this.props.record.update({
                [this.props.name]: { id: branch.id, display_name: branch.name },
            });
        }
    }
}

export const edaraBranchFilterField = {
    component: EdaraBranchFilterWidget,
    displayName: _t("Branch Filter"),
    supportedTypes: ["many2one"],
    fieldDependencies: [
        { name: "accessible_branch_ids", type: "many2many" },
    ],
};

registry.category("fields").add("edara_branch_filter", edaraBranchFilterField);
