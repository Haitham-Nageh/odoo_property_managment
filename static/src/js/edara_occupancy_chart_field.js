/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useEffect, useRef } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { getBorderWhite } from "@web/core/colors/colors";

const colorScheme = cookie.get("color_scheme");

export class EdaraOccupancyChartField extends Component {
    static template = "property_managment.EdaraOccupancyChartField";
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
                total: 0,
                slices: [],
                under_maintenance: { count: 0, action_method: "action_view_units_under_maintenance" },
            };
        }
        try {
            return typeof raw === "string" ? JSON.parse(raw) : raw;
        } catch {
            return {
                total: 0,
                slices: [],
                under_maintenance: { count: 0, action_method: "action_view_units_under_maintenance" },
            };
        }
    }

    getPercentage(count) {
        const total = this.chartData.total;
        if (!total || !count) {
            return 0;
        }
        return Math.round((count / total) * 100);
    }

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }

        const data = this.chartData;
        if (!this.canvasRef.el || data.total === 0 || !data.slices || data.slices.length === 0) {
            return;
        }

        const activeSlices = data.slices;
        const config = {
            type: "doughnut",
            data: {
                labels: activeSlices.map((s) => s.label),
                datasets: [
                    {
                        data: activeSlices.map((s) => s.count),
                        backgroundColor: activeSlices.map((s) => s.color),
                        borderColor: getBorderWhite(colorScheme),
                        borderWidth: 2,
                        hoverOffset: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "70%",
                plugins: {
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            label: (context) => {
                                const label = context.label || "";
                                const value = context.parsed || 0;
                                const total = data.total || 1;
                                const pct = Math.round((value / total) * 100);
                                return ` ${label}: ${value} (${pct}%)`;
                            },
                        },
                    },
                },
                onClick: (event, elements) => {
                    if (elements && elements.length > 0) {
                        const index = elements[0].index;
                        const slice = activeSlices[index];
                        if (slice && slice.action_method) {
                            this.onSliceClick(slice.action_method);
                        }
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

    async onSliceClick(actionMethod) {
        if (this.isProcessingClick) {
            return;
        }
        const ALLOWED_METHODS = [
            "action_view_units_available",
            "action_view_units_rented",
            "action_view_units_reserved",
            "action_view_units_owner_occupied",
            "action_view_units_sold",
            "action_view_units_under_maintenance",
        ];
        if (!ALLOWED_METHODS.includes(actionMethod)) {
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
                actionMethod,
                [[resId]],
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

export const edaraOccupancyChartField = {
    component: EdaraOccupancyChartField,
    supportedTypes: ["text"],
};

registry.category("fields").add("edara_occupancy_chart", edaraOccupancyChartField);
