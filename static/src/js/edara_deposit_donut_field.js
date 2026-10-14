/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useEffect, signal, useProps } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { getBorderWhite } from "@web/core/colors/colors";
import { _t } from "@web/core/l10n/translation";

const colorScheme = cookie.get("color_scheme");

// Only these dashboard methods may be invoked from a donut segment or legend row.
const ALLOWED_METHODS = [
    "action_view_deposits_still_held",
    "action_view_deposits_unsettled_closed",
    "action_view_deposits_settled",
];

const EMPTY = { total: 0, currency: "", currency_symbol: "", currency_precision: 2, slices: [] };

export class EdaraDepositDonutField extends Component {
    static template = "property_managment.EdaraDepositDonutField";
    props = useProps({
        ...standardFieldProps,
    });

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        const ref = signal.ref();
        Object.defineProperty(ref, "el", {
            get() {
                return ref();
            },
        });
        this.canvasRef = ref;
        this.chart = null;
        this.isProcessingClick = false;

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
        });

        useEffect(() => {
            this.renderChart();
            return () => {
                if (this.chart) {
                    this.chart.destroy();
                    this.chart = null;
                }
            };
        });
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

    get isEmpty() {
        const data = this.chartData;
        return !data.slices || !data.slices.some((s) => s.amount > 0);
    }

    formatAmount(value) {
        const precision = this.chartData.currency_precision ?? 2;
        const sym = this.chartData.currency_symbol || this.chartData.currency || "";
        const num = (value || 0).toLocaleString(undefined, {
            minimumFractionDigits: precision,
            maximumFractionDigits: precision,
        });
        return sym ? `${sym} ${num}` : num;
    }

    get centerAmount() {
        return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
            this.chartData.total || 0
        );
    }

    get totalLabel() {
        return _t("Total Collected");
    }

    countLabel(slice) {
        return _t("%s deposits", slice.count);
    }

    sliceTitle(slice) {
        return `${slice.label}: ${this.formatAmount(slice.amount)} (${this.countLabel(slice)})`;
    }

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
        if (!this.canvasRef.el || this.isEmpty) {
            return;
        }
        const slices = this.chartData.slices;
        this.chart = new Chart(this.canvasRef.el, {
            type: "doughnut",
            data: {
                labels: slices.map((s) => s.label),
                datasets: [
                    {
                        data: slices.map((s) => s.amount),
                        backgroundColor: slices.map((s) => s.color),
                        borderColor: getBorderWhite(colorScheme),
                        borderWidth: 2,
                        hoverOffset: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ` ${this.sliceTitle(slices[ctx.dataIndex])}`,
                        },
                    },
                },
                onClick: (event, elements) => {
                    if (elements && elements.length > 0) {
                        this.onSliceClick(slices[elements[0].index].action_method);
                    }
                },
                onHover: (event, elements) => {
                    const canvas = this.canvasRef.el;
                    if (canvas) {
                        canvas.style.cursor = elements && elements.length > 0 ? "pointer" : "default";
                    }
                },
            },
        });
    }

    async onSliceClick(actionMethod) {
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

export const edaraDepositDonutField = {
    component: EdaraDepositDonutField,
    supportedTypes: ["text"],
};

registry.category("fields").add("edara_deposit_donut", edaraDepositDonutField);
