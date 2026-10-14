/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useEffect, signal, useProps } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { getCustomColor } from "@web/core/colors/colors";
import { _t } from "@web/core/l10n/translation";

const colorScheme = cookie.get("color_scheme");
const CHART_LABEL_COLOR = getCustomColor(colorScheme, "#555555", "#E4E4E4");
const CHART_GRID_COLOR = getCustomColor(colorScheme, "rgba(0,0,0,.08)", "rgba(255,255,255,.15)");

const EMPTY = { count: 0, amount: 0, currency: "", currency_symbol: "", currency_precision: 2, months: [] };

export class EdaraServiceInvoiceField extends Component {
    static template = "property_managment.EdaraServiceInvoiceField";
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

    get hasActivity() {
        return (this.chartData.months || []).some((m) => m.count > 0);
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

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
        if (!this.canvasRef.el || !this.hasActivity) {
            return;
        }
        const months = this.chartData.months;
        this.chart = new Chart(this.canvasRef.el, {
            type: "bar",
            data: {
                labels: months.map((m) => m.label),
                datasets: [
                    {
                        label: _t("Invoice Amount"),
                        data: months.map((m) => m.amount),
                        backgroundColor: "#0066CC",
                        maxBarThickness: 36,
                        borderRadius: 3,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ` ${this.formatAmount(ctx.parsed.y || 0)}`,
                            footer: (items) => _t("%s invoices", months[items[0].dataIndex].count),
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: CHART_LABEL_COLOR, font: { size: 11 } } },
                    y: {
                        beginAtZero: true,
                        grid: { color: CHART_GRID_COLOR },
                        ticks: {
                            color: CHART_LABEL_COLOR,
                            font: { size: 11 },
                            maxTicksLimit: 4,
                            callback: (value) =>
                                new Intl.NumberFormat(undefined, { notation: "compact" }).format(value),
                        },
                    },
                },
                onClick: (event, elements) => {
                    if (elements && elements.length > 0) {
                        this.openInvoices(elements[0].index);
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

    /** monthIndex undefined -> every generated service-charge invoice; 0-5 -> that bar's month. */
    async openInvoices(monthIndex) {
        if (this.isProcessingClick) {
            return;
        }
        const months = this.chartData.months || [];
        if (monthIndex !== undefined && !(Number.isInteger(monthIndex) && monthIndex >= 0 && monthIndex < months.length)) {
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
            const args = monthIndex === undefined ? [[resId]] : [[resId], monthIndex];
            const action = await this.orm.call("edara.dashboard", "action_view_service_invoices", args, {
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

export const edaraServiceInvoiceField = {
    component: EdaraServiceInvoiceField,
    supportedTypes: ["text"],
};

registry.category("fields").add("edara_service_invoice", edaraServiceInvoiceField);
