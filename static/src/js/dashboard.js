/** @odoo-module **/

import { registry } from "@web/core/registry";

console.log("odoo_gen_bi dashboard module loaded"); // DEBUG: Validating file load on SH

import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";

export class ChartCard extends Component {
    setup() {
        this.canvasRef = useRef("chartCanvas");
        this.chartInstance = null;

        onMounted(async () => {
            await loadBundle("web.chartjs_lib"); // Ensure Chart.js is loaded
            this.renderChart();
        });

        onWillUnmount(() => {
            if (this.chartInstance) {
                this.chartInstance.destroy();
            }
        });
    }

    renderChart() {
        if (!this.canvasRef.el) return;
        if (this.chartInstance) this.chartInstance.destroy();

        if (typeof Chart === 'undefined') {
            console.error("Chart.js not loaded");
            return;
        }

        const ctx = this.canvasRef.el.getContext("2d");
        const chartData = JSON.parse(this.props.chart.chart_data);
        const chartType = this.props.chart.chart_type || 'bar';

        this.chartInstance = new Chart(ctx, {
            type: chartType,
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
            }
        });
    }

    async deleteChart(id) {
        await this.props.onDelete(id);
    }
}
ChartCard.template = "odoo_gen_bi.ChartCard";
ChartCard.props = {
    chart: Object,
    onDelete: Function,
};

export class BiDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            prompt: "",
            groupBy: "",
            filterBy: "",
            sortBy: "",
            previewTitle: "",
            charts: [],
            preview: null,
            loading: false,
        });

        this.previewCanvasRef = useRef("previewCanvas");
        this.previewChartInstance = null;

        onMounted(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadCharts();
        });
    }

    async loadCharts() {
        const result = await this.orm.searchRead("bi.dashboard.item", [], ["name", "chart_data", "chart_type"]);
        this.state.charts = result;
    }

    async onGenerate() {
        if (!this.state.prompt) return;

        // Construct full prompt
        let fullPrompt = this.state.prompt;
        if (this.state.groupBy) fullPrompt += `. Group by ${this.state.groupBy}`;
        if (this.state.filterBy) fullPrompt += `. Filter by ${this.state.filterBy}`;
        if (this.state.sortBy) fullPrompt += `. Sort by ${this.state.sortBy}`;

        this.state.loading = true;
        try {
            const result = await this.orm.call("bi.dashboard.item", "action_generate_preview", [fullPrompt]);
            this.state.preview = result;
            // Set default title if not already set (or reset it)
            this.state.previewTitle = this.state.prompt;

            if (result.warning) {
                this.notification.add(result.warning, { type: "warning", sticky: true });
            }

            // Wait for DOM to update then render
            setTimeout(() => this.renderPreviewChart(), 100);
        } catch (e) {
            this.notification.add("Error generating chart: " + e.message, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async renderPreviewChart() {
        if (!this.state.preview || !this.previewCanvasRef.el) return;
        if (this.previewChartInstance) this.previewChartInstance.destroy();

        if (typeof Chart === 'undefined') {
            try {
                await loadBundle("web.chartjs_lib");
            } catch (e) {
                console.error("Failed to load Chart.js bundle", e);
            }
        }

        if (typeof Chart === 'undefined') {
            this.notification.add("Chart.js library failed to load. Please refresh.", { type: "danger" });
            return;
        }

        const ctx = this.previewCanvasRef.el.getContext("2d");
        const chartData = JSON.parse(this.state.preview.chart_data);

        this.previewChartInstance = new Chart(ctx, {
            type: this.state.preview.chart_type,
            data: chartData,
            options: { responsive: true, maintainAspectRatio: false }
        });
    }

    async savePreview() {
        if (!this.state.preview) return;
        try {
            await this.orm.create("bi.dashboard.item", [{
                name: this.state.previewTitle || this.state.prompt,
                prompt: this.state.prompt,
                sql_query: this.state.preview.sql,
                chart_type: this.state.preview.chart_type,
                chart_data: this.state.preview.chart_data
            }]);
            this.state.preview = null;
            this.state.prompt = "";
            if (this.previewChartInstance) {
                this.previewChartInstance.destroy();
                this.previewChartInstance = null;
            }
            await this.loadCharts();
            this.notification.add("Chart saved!", { type: "success" });
        } catch (e) {
            this.notification.add("Error saving chart: " + e.message, { type: "danger" });
        }
    }

    discardPreview() {
        this.state.preview = null;
        if (this.previewChartInstance) {
            this.previewChartInstance.destroy();
            this.previewChartInstance = null;
        }
    }

    async onDeleteChart(id) {
        if (confirm("Are you sure you want to delete this chart?")) {
            try {
                await this.orm.unlink("bi.dashboard.item", [id]);
                await this.loadCharts();
            } catch (e) {
                this.notification.add("Error deleting chart: " + e.message, { type: "danger" });
            }
        }
    }

    onInputKeydown(ev) {
        if (ev.key === "Enter") {
            this.onGenerate();
        }
    }
}

BiDashboard.template = "odoo_gen_bi.Dashboard";
BiDashboard.components = { ChartCard };

registry.category("actions").add("odoo_gen_bi.dashboard", BiDashboard);
console.log("odoo_gen_bi.dashboard registered in actions category"); // DEBUG

