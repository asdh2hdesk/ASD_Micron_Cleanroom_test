/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { deserializeDate, deserializeDateTime, formatDate, formatDateTime } from "@web/core/l10n/dates";

// ── Palette ─────────────────────────────────────────────────────────────
const C = {
    indigo: "#6366f1",
    cyan: "#06b6d4",
    teal: "#14b8a6",
    green: "#22c55e",
    amber: "#f59e0b",
    orange: "#fb7185",
    red: "#ef4444",
    slate: "#94a3b8",
    violet: "#a855f7",
};

const TEST_LABELS = {
    "VL-001": "Air Velocity & ACPH",
    "VL-002": "HEPA Integrity (PAO)",
    "VL-003": "Particle Count",
    "VL-004": "Recovery Study",
    "VL-005": "Temperature & RH",
};

export class HvacDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            refreshing: false,
            period: "30",
            dateFrom: this.daysAgo(30),
            dateTo: this.today(),
            lastRefresh: "",
            stats: this.emptyStats(),
            display: this.emptyStats(),
            spark: { tests: [], jobs: [] },
            testTypes: [],
            criteriaSplit: { sop: 0, client: 0 },
            horizon: { d30: 0, d60: 0, d90: 0, overdue: 0 },
            topClients: [],
            feed: [],
            recentJobs: [],
            calibrationAlertsList: [],
            recentNcrs: [],
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.loadDashboardData();
        });

        onMounted(() => {
            this.renderCharts();
            this.animateCounters();

            this.refreshInterval = setInterval(async () => {
                this.state.refreshing = true;
                await this.loadDashboardData({ silent: true });
                this.renderCharts();
                this.animateCounters();
                this.state.refreshing = false;
            }, 30000);

            this.resizeHandler = () => {
                for (const chart of this.charts()) {
                    if (chart) chart.resize();
                }
            };
            window.addEventListener("resize", this.resizeHandler);
        });

        onWillUnmount(() => {
            if (this.refreshInterval) clearInterval(this.refreshInterval);
            if (this.raf) cancelAnimationFrame(this.raf);
            if (this.resizeHandler) window.removeEventListener("resize", this.resizeHandler);
            this.destroyCharts();
        });
    }

    // ── Small helpers ───────────────────────────────────────────────────

    emptyStats() {
        return {
            totalJobs: 0, activeJobs: 0, doneJobs: 0,
            totalTests: 0, passRate: 0, failedTests: 0,
            calibrationAlerts: 0, overdueCal: 0, instrumentHealth: 0,
            openNcrs: 0, criticalNcrs: 0,
        };
    }

    today() {
        return new Date().toISOString().split("T")[0];
    }

    daysAgo(n) {
        const d = new Date();
        d.setDate(d.getDate() - n);
        return d.toISOString().split("T")[0];
    }

    charts() {
        return [this.trendChart, this.jobStatusChart, this.instrumentCalChart, this.ncrSeverityChart];
    }

    formatOdooDate(value) {
        if (!value) return "";
        try {
            return formatDate(deserializeDate(value));
        } catch {
            return value;
        }
    }

    formatOdooDatetime(value) {
        if (!value) return "";
        try {
            return formatDateTime(deserializeDateTime(value));
        } catch {
            return value;
        }
    }

    /** Days from today — negative when the date is already past. */
    daysUntil(dateStr) {
        if (!dateStr) return null;
        const target = new Date(dateStr + "T00:00:00");
        const now = new Date();
        now.setHours(0, 0, 0, 0);
        return Math.round((target - now) / 86400000);
    }

    // ── Period selection ────────────────────────────────────────────────

    async setPeriod(period) {
        this.state.period = period;
        if (period !== "custom") {
            this.state.dateFrom = this.daysAgo(parseInt(period, 10));
            this.state.dateTo = this.today();
            await this.reload();
        }
    }

    async onDateInput(ev, field) {
        this.state[field] = ev.target.value;
        this.state.period = "custom";
        await this.reload();
    }

    async reload() {
        await this.loadDashboardData();
        this.renderCharts();
        this.animateCounters();
    }

    // ── Animated counters ───────────────────────────────────────────────

    animateCounters() {
        if (this.raf) cancelAnimationFrame(this.raf);
        const from = { ...this.state.display };
        const to = this.state.stats;
        const keys = Object.keys(to);
        const started = performance.now();
        const duration = 850;

        const step = (now) => {
            const p = Math.min(1, (now - started) / duration);
            const eased = 1 - Math.pow(1 - p, 3);   // easeOutCubic
            for (const key of keys) {
                const a = from[key] || 0;
                const b = to[key] || 0;
                const value = a + (b - a) * eased;
                this.state.display[key] = key === "passRate"
                    ? Math.round(value * 10) / 10
                    : Math.round(value);
            }
            if (p < 1) {
                this.raf = requestAnimationFrame(step);
            } else {
                Object.assign(this.state.display, to);
                this.raf = null;
            }
        };
        this.raf = requestAnimationFrame(step);
    }

    /** Points for an inline sparkline polyline. */
    sparkPoints(series, width = 132, height = 34) {
        if (!series || !series.length) return "";
        const max = Math.max(1, ...series);
        const step = series.length > 1 ? width / (series.length - 1) : width;
        return series
            .map((v, i) => `${(i * step).toFixed(1)},${(height - 3 - (v / max) * (height - 8)).toFixed(1)}`)
            .join(" ");
    }

    sparkArea(series, width = 132, height = 34) {
        const points = this.sparkPoints(series, width, height);
        if (!points) return "";
        return `0,${height} ${points} ${width},${height}`;
    }

    /** Stroke offset for the SVG progress ring (r=30 → circumference 188.5). */
    ringOffset(percent) {
        const circumference = 188.5;
        return (circumference * (1 - Math.max(0, Math.min(100, percent)) / 100)).toFixed(1);
    }

    // ── Data ────────────────────────────────────────────────────────────

    async loadDashboardData({ silent = false } = {}) {
        if (!silent) this.state.loading = true;
        try {
            const { dateFrom, dateTo } = this.state;
            const jobDomain = [];
            const testDomain = [];
            const ncrDomain = [];

            if (dateFrom) {
                jobDomain.push(["scheduled_date", ">=", dateFrom + " 00:00:00"]);
                testDomain.push(["test_date", ">=", dateFrom]);
                ncrDomain.push(["raised_date", ">=", dateFrom]);
            }
            if (dateTo) {
                jobDomain.push(["scheduled_date", "<=", dateTo + " 23:59:59"]);
                testDomain.push(["test_date", "<=", dateTo]);
                ncrDomain.push(["raised_date", "<=", dateTo]);
            }

            const [jobs, worksheets, instruments, ncrs] = await Promise.all([
                this.orm.searchRead("hvac.job", jobDomain,
                    ["name", "partner_id", "project_name", "scheduled_date",
                     "lead_technician_id", "priority", "state"],
                    { limit: 1000, order: "scheduled_date desc" }),
                this.orm.searchRead("hvac.test.sheet", testDomain,
                    ["name", "test_date", "overall_result", "sop_test_code",
                     "criteria_source", "partner_id", "state"],
                    { limit: 1000, order: "test_date desc" }),
                this.orm.searchRead("hvac.instrument", [],
                    ["name", "asset_code", "instrument_type", "calibration_status",
                     "next_calibration_date"],
                    { limit: 1000 }),
                this.orm.searchRead("hvac.ncr", ncrDomain,
                    ["name", "severity", "state", "raised_date", "job_id"],
                    { limit: 1000, order: "raised_date desc" }),
            ]);

            this.computeStats(jobs, worksheets, instruments, ncrs);
            this.computeInsights(jobs, worksheets, instruments, ncrs);
            this.prepareChartData(jobs, worksheets, instruments, ncrs);

            this.state.lastRefresh = new Date().toLocaleTimeString([], {
                hour: "2-digit", minute: "2-digit",
            });
        } catch (error) {
            console.error("HVAC dashboard: failed to load data", error);
        } finally {
            this.state.loading = false;
        }
    }

    computeStats(jobs, worksheets, instruments, ncrs) {
        const judged = worksheets.filter((w) => w.overall_result);
        const passed = judged.filter((w) => w.overall_result === "pass").length;
        const alerts = instruments.filter((i) =>
            ["overdue", "due_soon", "not_calibrated"].includes(i.calibration_status));
        const valid = instruments.filter((i) => i.calibration_status === "valid").length;

        this.state.stats = {
            totalJobs: jobs.length,
            activeJobs: jobs.filter((j) => j.state === "in_progress").length,
            doneJobs: jobs.filter((j) => j.state === "done").length,
            totalTests: worksheets.length,
            passRate: judged.length ? Math.round((passed / judged.length) * 1000) / 10 : 0,
            failedTests: judged.filter((w) => w.overall_result === "fail").length,
            calibrationAlerts: alerts.length,
            overdueCal: instruments.filter((i) => i.calibration_status === "overdue").length,
            instrumentHealth: instruments.length
                ? Math.round((valid / instruments.length) * 100) : 0,
            openNcrs: ncrs.filter((n) => n.state !== "closed").length,
            criticalNcrs: ncrs.filter((n) => n.severity === "critical" && n.state !== "closed").length,
        };
    }

    computeInsights(jobs, worksheets, instruments, ncrs) {
        // ── 14-day sparkline series ─────────────────────────────────────
        const days = [];
        for (let i = 13; i >= 0; i--) days.push(this.daysAgo(i));
        const countBy = (records, field) => days.map((day) =>
            records.filter((r) => (r[field] || "").slice(0, 10) === day).length);
        this.state.spark = {
            tests: countBy(worksheets, "test_date"),
            jobs: countBy(jobs, "scheduled_date"),
        };

        // ── Pass rate per test type ─────────────────────────────────────
        const byType = {};
        for (const w of worksheets) {
            const code = w.sop_test_code || "—";
            byType[code] = byType[code] || { code, label: TEST_LABELS[code] || code, total: 0, pass: 0, fail: 0 };
            byType[code].total++;
            if (w.overall_result === "pass") byType[code].pass++;
            if (w.overall_result === "fail") byType[code].fail++;
        }
        this.state.testTypes = Object.values(byType)
            .map((t) => ({ ...t, rate: t.total ? Math.round((t.pass / t.total) * 100) : 0 }))
            .sort((a, b) => b.total - a.total);

        // ── Which standard the tests were judged against ────────────────
        this.state.criteriaSplit = {
            sop: worksheets.filter((w) => w.criteria_source !== "client").length,
            client: worksheets.filter((w) => w.criteria_source === "client").length,
        };

        // ── Calibration horizon ─────────────────────────────────────────
        const horizon = { d30: 0, d60: 0, d90: 0, overdue: 0 };
        for (const i of instruments) {
            const days = this.daysUntil(i.next_calibration_date);
            if (days === null) continue;
            if (days < 0) horizon.overdue++;
            else if (days <= 30) horizon.d30++;
            else if (days <= 60) horizon.d60++;
            else if (days <= 90) horizon.d90++;
        }
        this.state.horizon = horizon;

        // ── Busiest clients ─────────────────────────────────────────────
        const byClient = {};
        for (const w of worksheets) {
            if (!w.partner_id) continue;
            const [id, name] = w.partner_id;
            byClient[id] = byClient[id] || { id, name, total: 0, pass: 0 };
            byClient[id].total++;
            if (w.overall_result === "pass") byClient[id].pass++;
        }
        this.state.topClients = Object.values(byClient)
            .map((c) => ({ ...c, rate: c.total ? Math.round((c.pass / c.total) * 100) : 0 }))
            .sort((a, b) => b.total - a.total)
            .slice(0, 5);

        // ── Lists ───────────────────────────────────────────────────────
        this.state.recentJobs = jobs.slice(0, 5);
        this.state.recentNcrs = ncrs.slice(0, 5);
        this.state.calibrationAlertsList = instruments
            .filter((i) => ["overdue", "due_soon", "not_calibrated"].includes(i.calibration_status))
            .map((i) => ({ ...i, days: this.daysUntil(i.next_calibration_date) }))
            .sort((a, b) => (a.days ?? 9999) - (b.days ?? 9999))
            .slice(0, 5);

        // ── Merged activity feed ────────────────────────────────────────
        const feed = [];
        for (const w of worksheets.slice(0, 8)) {
            feed.push({
                id: `t${w.id}`, kind: "test", date: w.test_date,
                icon: w.overall_result === "fail" ? "fa-times-circle" : "fa-flask",
                tone: w.overall_result === "fail" ? "danger"
                    : w.overall_result === "pass" ? "success" : "muted",
                title: `${w.name} — ${TEST_LABELS[w.sop_test_code] || w.sop_test_code || "Test"}`,
                meta: w.partner_id ? w.partner_id[1] : "",
                badge: (w.overall_result || "pending").toUpperCase(),
            });
        }
        for (const n of ncrs.slice(0, 5)) {
            feed.push({
                id: `n${n.id}`, kind: "ncr", date: n.raised_date, icon: "fa-exclamation-triangle",
                tone: n.severity === "critical" ? "danger" : "warning",
                title: `${n.name} — non-conformance`,
                meta: n.job_id ? n.job_id[1] : "",
                badge: (n.severity || "").toUpperCase(),
            });
        }
        this.state.feed = feed
            .filter((f) => f.date)
            .sort((a, b) => (a.date < b.date ? 1 : -1))
            .slice(0, 7);
    }

    // ── Charts ──────────────────────────────────────────────────────────

    gradient(ctx, hex, from = 0.35, to = 0) {
        const canvas = ctx.canvas;
        const grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 240);
        grad.addColorStop(0, this.alpha(hex, from));
        grad.addColorStop(1, this.alpha(hex, to));
        return grad;
    }

    alpha(hex, a) {
        const n = parseInt(hex.slice(1), 16);
        return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
    }

    prepareChartData(jobs, worksheets, instruments, ncrs) {
        // 1. Outcome trend over the last 14 days
        const days = [];
        for (let i = 13; i >= 0; i--) days.push(this.daysAgo(i));
        const on = (day, result) => worksheets.filter(
            (w) => (w.test_date || "") === day && w.overall_result === result).length;

        this.trendSeries = {
            labels: days.map((d) => d.slice(5).replace("-", "/")),
            pass: days.map((d) => on(d, "pass")),
            fail: days.map((d) => on(d, "fail")),
            conditional: days.map((d) => on(d, "conditional")),
        };

        // 2. Job pipeline
        const states = { draft: 0, scheduled: 0, in_progress: 0, done: 0, cancelled: 0 };
        for (const j of jobs) {
            if (states[j.state] !== undefined) states[j.state]++;
        }
        this.jobStates = states;

        // 3. Calibration standing
        const cal = { valid: 0, due_soon: 0, overdue: 0, not_calibrated: 0 };
        for (const i of instruments) {
            if (cal[i.calibration_status] !== undefined) cal[i.calibration_status]++;
        }
        this.calStates = cal;

        // 4. NCR severity
        const sev = { minor: 0, major: 0, critical: 0 };
        for (const n of ncrs) {
            if (sev[n.severity] !== undefined) sev[n.severity]++;
        }
        this.ncrStates = sev;
    }

    baseOptions(extra = {}) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 900, easing: "easeOutQuart" },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(15, 23, 42, 0.92)",
                    padding: 10,
                    cornerRadius: 8,
                    titleFont: { size: 12, weight: "600" },
                    bodyFont: { size: 12 },
                    displayColors: true,
                    boxPadding: 4,
                },
            },
            ...extra,
        };
    }

    renderCharts() {
        this.destroyCharts();
        if (!window.Chart || this.state.loading) return;

        const gridColor = "rgba(148, 163, 184, 0.18)";
        const tickColor = "#94a3b8";

        // ── Outcome trend — smooth area lines ───────────────────────────
        const trendEl = document.getElementById("hvacTrendChart");
        if (trendEl && this.trendSeries) {
            const ctx = trendEl.getContext("2d");
            this.trendChart = new Chart(trendEl, {
                type: "line",
                data: {
                    labels: this.trendSeries.labels,
                    datasets: [
                        {
                            label: "Pass", data: this.trendSeries.pass,
                            borderColor: C.green, backgroundColor: this.gradient(ctx, C.green),
                            fill: true, tension: 0.4, borderWidth: 2.5,
                            pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: C.green,
                        },
                        {
                            label: "Fail", data: this.trendSeries.fail,
                            borderColor: C.red, backgroundColor: this.gradient(ctx, C.red, 0.25),
                            fill: true, tension: 0.4, borderWidth: 2.5,
                            pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: C.red,
                        },
                        {
                            label: "Conditional", data: this.trendSeries.conditional,
                            borderColor: C.amber, backgroundColor: this.gradient(ctx, C.amber, 0.2),
                            fill: true, tension: 0.4, borderWidth: 2,
                            pointRadius: 0, pointHoverRadius: 5, borderDash: [4, 3],
                        },
                    ],
                },
                options: this.baseOptions({
                    interaction: { mode: "index", intersect: false },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: tickColor, font: { size: 10 } } },
                        y: {
                            beginAtZero: true, border: { display: false },
                            grid: { color: gridColor },
                            ticks: { color: tickColor, precision: 0, font: { size: 10 } },
                        },
                    },
                }),
            });
        }

        // ── Job pipeline — doughnut with a hollow centre ────────────────
        const jobEl = document.getElementById("hvacJobChart");
        if (jobEl && this.jobStates) {
            this.jobStatusChart = new Chart(jobEl, {
                type: "doughnut",
                data: {
                    labels: ["Draft", "Scheduled", "In Progress", "Completed", "Cancelled"],
                    datasets: [{
                        data: [
                            this.jobStates.draft, this.jobStates.scheduled,
                            this.jobStates.in_progress, this.jobStates.done,
                            this.jobStates.cancelled,
                        ],
                        backgroundColor: [C.slate, C.cyan, C.amber, C.green, C.orange],
                        borderWidth: 0,
                        hoverOffset: 10,
                        spacing: 3,
                    }],
                },
                options: this.baseOptions({
                    cutout: "72%",
                    plugins: {
                        legend: {
                            display: true, position: "bottom",
                            labels: {
                                boxWidth: 8, boxHeight: 8, usePointStyle: true,
                                pointStyle: "circle", padding: 12,
                                color: tickColor, font: { size: 11 },
                            },
                        },
                        tooltip: this.baseOptions().plugins.tooltip,
                    },
                }),
            });
        }

        // ── Calibration standing ───────────────────────────────────────
        const calEl = document.getElementById("hvacCalChart");
        if (calEl && this.calStates) {
            this.instrumentCalChart = new Chart(calEl, {
                type: "doughnut",
                data: {
                    labels: ["Valid", "Due Soon", "Overdue", "Not Calibrated"],
                    datasets: [{
                        data: [
                            this.calStates.valid, this.calStates.due_soon,
                            this.calStates.overdue, this.calStates.not_calibrated,
                        ],
                        backgroundColor: [C.teal, C.amber, C.red, C.slate],
                        borderWidth: 0, hoverOffset: 10, spacing: 3,
                    }],
                },
                options: this.baseOptions({
                    cutout: "72%",
                    plugins: {
                        legend: {
                            display: true, position: "bottom",
                            labels: {
                                boxWidth: 8, boxHeight: 8, usePointStyle: true,
                                pointStyle: "circle", padding: 12,
                                color: tickColor, font: { size: 11 },
                            },
                        },
                        tooltip: this.baseOptions().plugins.tooltip,
                    },
                }),
            });
        }

        // ── NCR severity — rounded horizontal bars ─────────────────────
        const ncrEl = document.getElementById("hvacNcrChart");
        if (ncrEl && this.ncrStates) {
            this.ncrSeverityChart = new Chart(ncrEl, {
                type: "bar",
                data: {
                    labels: ["Minor", "Major", "Critical"],
                    datasets: [{
                        data: [this.ncrStates.minor, this.ncrStates.major, this.ncrStates.critical],
                        backgroundColor: [C.cyan, C.amber, C.red],
                        borderRadius: 8,
                        borderSkipped: false,
                        barThickness: 22,
                    }],
                },
                options: this.baseOptions({
                    indexAxis: "y",
                    scales: {
                        x: {
                            beginAtZero: true, border: { display: false },
                            grid: { color: gridColor },
                            ticks: { color: tickColor, precision: 0, font: { size: 10 } },
                        },
                        y: { grid: { display: false }, ticks: { color: tickColor, font: { size: 11 } } },
                    },
                }),
            });
        }
    }

    destroyCharts() {
        for (const chart of this.charts()) {
            if (chart) chart.destroy();
        }
        this.trendChart = this.jobStatusChart = this.instrumentCalChart = this.ncrSeverityChart = null;
    }

    // ── Drill-downs ─────────────────────────────────────────────────────

    open(model, domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
            name: name,
        });
    }

    openJobs(state = null) {
        this.open("hvac.job", state ? [["state", "=", state]] : [],
            state ? `Job Orders — ${state.replace("_", " ").toUpperCase()}` : "All Job Orders");
    }

    openWorksheets(result = null) {
        this.open("hvac.test.sheet", result ? [["overall_result", "=", result]] : [],
            result ? `Test Sheets — ${result.toUpperCase()}` : "All Test Worksheets");
    }

    openTestType(code) {
        this.open("hvac.test.sheet", [["sop_test_code", "=", code]],
            `${code} — ${TEST_LABELS[code] || "Test Worksheets"}`);
    }

    openInstruments(status = null) {
        let domain = [];
        if (status === "alerts") {
            domain = [["calibration_status", "in", ["overdue", "due_soon", "not_calibrated"]]];
        } else if (status) {
            domain = [["calibration_status", "=", status]];
        }
        this.open("hvac.instrument", domain, "Measuring Instrument Registry");
    }

    openNCRs(state = null) {
        this.open("hvac.ncr", state ? [["state", "=", state]] : [],
            state ? `Non-Conformance Reports — ${state.toUpperCase()}` : "All Non-Conformance Reports");
    }

    openClient(partnerId) {
        this.open("hvac.test.sheet", [["partner_id", "=", partnerId]], "Client Test Worksheets");
    }

    downloadReport() {
        try {
            window.print();
        } catch (e) {
            console.error("Failed to print HVAC dashboard:", e);
        }
    }
}

HvacDashboard.template = "micron_hvac.HvacDashboard";
registry.category("actions").add("hvac_dashboard", HvacDashboard);
