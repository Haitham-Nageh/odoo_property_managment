/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useEffect, useRef } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { getCustomColor } from "@web/core/colors/colors";
import { _t } from "@web/core/l10n/translation";

const colorScheme = cookie.get("color_scheme");
const CHART_LABEL_COLOR = getCustomColor(
    colorScheme,
    "#111827",
    "#E4E4E4"
);
const CHART_GRID_COLOR = getCustomColor(
    colorScheme,
    "rgba(0,0,0,.1)",
    "rgba(255,255,255,.15)"
);

export class EdaraRevenueTrendChartField extends Component {
    static template = "property_managment.EdaraRevenueTrendChartField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.canvasRef = useRef("canvas");
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
            return {
                currency: "",
                currency_symbol: "",
                total_revenue: 0,
                months: [],
            };
        }
        try {
            return typeof raw === "string" ? JSON.parse(raw) : raw;
        } catch {
            return {
                currency: "",
                currency_symbol: "",
                total_revenue: 0,
                months: [],
            };
        }
    }

    get isAllZero() {
        const data = this.chartData;
        if (!data.months || data.months.length === 0) {
            return true;
        }
        return data.months.every((m) => m.value === 0);
    }

    get currencyFallback() {
        return _t("Company Currency");
    }

    getCurrencyFallback() {
        return this.currencyFallback;
    }

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }

        const data = this.chartData;
        if (!this.canvasRef.el || this.isAllZero || !data.months || data.months.length === 0) {
            return;
        }

        const months = data.months;
        const currencySymbol = data.currency_symbol || data.currency || "";

        const config = {
            type: "bar",
            data: {
                labels: months.map((m) => m.label),
                datasets: [
                    {
                        label: "Revenue",
                        data: months.map((m) => m.value),
                        backgroundColor: "#10B981",
                        hoverBackgroundColor: "#059669",
                        borderRadius: 4,
                        borderSkipped: false,
                        maxBarThickness: 48,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            label: (context) => {
                                const val = context.parsed.y != null ? context.parsed.y : 0;
                                const formatted = val.toLocaleString(undefined, {
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2,
                                });
                                const labelPrefix = _t("Revenue: ");
                                return ` ${labelPrefix}${currencySymbol ? currencySymbol + " " : ""}${formatted}`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: {
                            display: false,
                        },
                        ticks: {
                            font: { size: 12 },
                            color: CHART_LABEL_COLOR,
                        },
                    },
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: CHART_GRID_COLOR,
                        },
                        ticks: {
                            font: { size: 11 },
                            color: CHART_LABEL_COLOR,
                            callback: (value) => {
                                return `${currencySymbol ? currencySymbol + " " : ""}${value.toLocaleString()}`;
                            },
                        },
                    },
                },
                onClick: (event, elements) => {
                    if (elements && elements.length > 0) {
                        const index = elements[0].index;
                        this.onBarClick(index);
                    }
                },
                onHover: (event, elements) => {
                    const canvas = this.canvasRef.el;
                    if (canvas) {
                        canvas.style.cursor = elements && elements.length > 0 ? "pointer" : "default";
                    }
                },
            },
        };

        this.chart = new Chart(this.canvasRef.el, config);
    }

    async onBarClick(monthIndex) {
        if (this.isProcessingClick) {
            return;
        }
        if (typeof monthIndex !== "number" || monthIndex < 0 || monthIndex > 5) {
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
            const action = await this.orm.call(
                "edara.dashboard",
                "action_view_revenue_trend_month",
                [[resId], monthIndex],
                { context: this.props.record.context }
            );
            if (action) {
                await this.action.doAction(action);
            }
        } finally {
            this.isProcessingClick = false;
        }
    }
}

export const edaraRevenueTrendChartField = {
    component: EdaraRevenueTrendChartField,
    supportedTypes: ["text"],
};

registry.category("fields").add("edara_revenue_trend_chart", edaraRevenueTrendChartField);
