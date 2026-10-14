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
const CHART_LABEL_COLOR = getCustomColor(colorScheme, "#111827", "#E4E4E4");
const CHART_GRID_COLOR = getCustomColor(colorScheme, "rgba(0,0,0,.1)", "rgba(255,255,255,.15)");

const EMPTY = {
    currency: "",
    currency_symbol: "",
    currency_id: null,
    currency_precision: 2,
    period: "monthly",
    totals: { scheduled: 0, collected: 0, overdue: 0, upcoming: 0, outstanding: 0, collection_rate: null },
    buckets: [],
};

export class EdaraCollectionsChartField extends Component {
    static template = "property_managment.EdaraCollectionsChartField";
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
        return !data.buckets || data.buckets.every((b) => b.scheduled === 0);
    }

    get currencyLabel() {
        return this.chartData.currency_symbol || this.chartData.currency || "";
    }

    formatAmount(value) {
        const precision = this.chartData.currency_precision != null ? this.chartData.currency_precision : 2;
        return (value || 0).toLocaleString(undefined, {
            minimumFractionDigits: precision,
            maximumFractionDigits: precision,
        });
    }

    get collectionRateLabel() {
        const rate = this.chartData.totals.collection_rate;
        return rate === null || rate === undefined ? "–" : `${rate}%`;
    }

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
        const data = this.chartData;
        if (!this.canvasRef.el || this.isEmpty) {
            return;
        }
        const buckets = data.buckets;
        const sym = this.currencyLabel;
        const fmt = (v) => `${sym ? sym + " " : ""}${this.formatAmount(v)}`;
        const segments = [
            { key: "collected", label: _t("Collected"), color: "#10B981" },
            { key: "overdue", label: _t("Overdue"), color: "#EF4444" },
            { key: "upcoming", label: _t("Upcoming"), color: "#F59E0B" },
        ];
        this.segmentKeys = segments.map((s) => s.key);

        this.chart = new Chart(this.canvasRef.el, {
            type: "bar",
            data: {
                labels: buckets.map((b) => b.label),
                datasets: segments.map((s) => ({
                    label: s.label,
                    data: buckets.map((b) => b[s.key]),
                    backgroundColor: s.color,
                    maxBarThickness: 48,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: "bottom",
                        labels: { boxWidth: 10, boxHeight: 10, color: CHART_LABEL_COLOR, font: { size: 11 } },
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ` ${ctx.dataset.label}: ${fmt(ctx.parsed.y || 0)}`,
                            footer: (items) => {
                                const b = buckets[items[0].dataIndex];
                                return `${_t("Scheduled")}: ${fmt(b.scheduled)}`;
                            },
                        },
                    },
                },
                scales: {
                    x: { stacked: true, grid: { display: false }, ticks: { color: CHART_LABEL_COLOR, font: { size: 11 } } },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        grid: { color: CHART_GRID_COLOR },
                        ticks: {
                            color: CHART_LABEL_COLOR,
                            font: { size: 11 },
                            callback: (value) => value.toLocaleString(),
                        },
                    },
                },
                onClick: (event, elements) => {
                    if (elements && elements.length > 0) {
                        this.onBarClick(elements[0].index, this.segmentKeys[elements[0].datasetIndex]);
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

    async onBarClick(bucketIndex, measure) {
        if (this.isProcessingClick) {
            return;
        }
        const data = this.chartData;
        if (typeof bucketIndex !== "number" || bucketIndex < 0 || bucketIndex >= data.buckets.length) {
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
                "action_view_collections_bucket",
                [[resId], bucketIndex, measure, data.currency_id || null],
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

export const edaraCollectionsChartField = {
    component: EdaraCollectionsChartField,
    supportedTypes: ["text"],
};

registry.category("fields").add("edara_collections_chart", edaraCollectionsChartField);
