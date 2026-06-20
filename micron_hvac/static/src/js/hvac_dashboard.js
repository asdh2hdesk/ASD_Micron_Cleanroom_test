/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { deserializeDate, deserializeDateTime, formatDate, formatDateTime } from "@web/core/l10n/dates";

export class HvacDashboard extends Component {
    setup() {
        console.log("HVAC Dashboard component initialized");
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            stats: {
                totalJobs: 0,
                activeJobs: 0,
                calibrationAlerts: 0,
                openNcrs: 0,
                passRate: 0
            },
            recentJobs: [],
            calibrationAlertsList: [],
            recentNcrs: [],
            loading: true,
            dateFrom: this.getDefaultDateFrom(),
            dateTo: this.getDefaultDateTo(),
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.loadDashboardData();
        });

        onMounted(() => {
            this.renderCharts();

            // Auto-refresh every 30 seconds
            this.refreshInterval = setInterval(() => {
                this.loadDashboardData().then(() => {
                    this.renderCharts();
                });
            }, 30000);

            // Handle resizing
            this.resizeHandler = () => {
                if (this.jobStatusChart) this.jobStatusChart.resize();
                if (this.testTrendChart) this.testTrendChart.resize();
                if (this.instrumentCalChart) this.instrumentCalChart.resize();
                if (this.ncrSeverityChart) this.ncrSeverityChart.resize();
            };
            window.addEventListener('resize', this.resizeHandler);
        });

        onWillUnmount(() => {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
            }
            if (this.resizeHandler) {
                window.removeEventListener('resize', this.resizeHandler);
            }
            this.destroyCharts();
        });
    }

    getDefaultDateFrom() {
        const date = new Date();
        date.setDate(date.getDate() - 30);
        return date.toISOString().split('T')[0];
    }

    getDefaultDateTo() {
        return new Date().toISOString().split('T')[0];
    }

    onDateInput(ev, field) {
        this.state[field] = ev.target.value;
        this.onDateChange();
    }

    onDateChange() {
        this.loadDashboardData().then(() => {
            this.renderCharts();
        });
    }

    formatOdooDate(value) {
        if (!value) return "";
        try {
            const d = deserializeDate(value);
            return formatDate(d);
        } catch {
            return value;
        }
    }

    formatOdooDatetime(value) {
        if (!value) return "";
        try {
            const dt = deserializeDateTime(value);
            return formatDateTime(dt);
        } catch {
            return value;
        }
    }

    async loadDashboardData() {
        this.state.loading = true;
        try {
            const dateFrom = this.state.dateFrom;
            const dateTo = this.state.dateTo;

            // Domains
            const jobDomain = [];
            const testDomain = [];
            const ncrDomain = [];

            if (dateFrom) {
                jobDomain.push(['scheduled_date', '>=', dateFrom + ' 00:00:00']);
                testDomain.push(['test_date', '>=', dateFrom]);
                ncrDomain.push(['raised_date', '>=', dateFrom]);
            }
            if (dateTo) {
                jobDomain.push(['scheduled_date', '<=', dateTo + ' 23:59:59']);
                testDomain.push(['test_date', '<=', dateTo]);
                ncrDomain.push(['raised_date', '<=', dateTo]);
            }

            // Fetch HVAC Jobs
            const jobs = await this.orm.searchRead(
                "hvac.job",
                jobDomain,
                ["name", "partner_id", "scheduled_date", "lead_technician_id", "priority", "state"],
                { limit: 1000, order: "scheduled_date desc" }
            );

            // Fetch HVAC Test Worksheets
            const worksheets = await this.orm.searchRead(
                "hvac.test.sheet",
                testDomain,
                ["name", "test_date", "overall_result", "sop_test_code"],
                { limit: 1000, order: "test_date desc" }
            );

            // Fetch Instruments
            const instruments = await this.orm.searchRead(
                "hvac.instrument",
                [],
                ["name", "asset_code", "instrument_type", "calibration_status", "next_calibration_date"],
                { limit: 1000 }
            );

            // Fetch Non-Conformances
            const ncrs = await this.orm.searchRead(
                "hvac.ncr",
                ncrDomain,
                ["name", "severity", "state", "raised_date", "job_id"],
                { limit: 1000, order: "raised_date desc" }
            );

            // Process Stats
            const totalJobs = jobs.length;
            const activeJobs = jobs.filter(j => j.state === 'in_progress').length;
            const calibrationAlerts = instruments.filter(i => ['overdue', 'due_soon', 'not_calibrated'].includes(i.calibration_status)).length;
            const openNcrs = ncrs.filter(n => n.state === 'open').length;

            const totalTestSheets = worksheets.length;
            const passedTestSheets = worksheets.filter(w => w.overall_result === 'pass').length;
            const passRate = totalTestSheets > 0 ? ((passedTestSheets / totalTestSheets) * 100).toFixed(1) : "0.0";

            this.state.stats = {
                totalJobs,
                activeJobs,
                calibrationAlerts,
                openNcrs,
                passRate
            };

            // Lists
            this.state.recentJobs = jobs.slice(0, 5);
            this.state.calibrationAlertsList = instruments
                .filter(i => ['overdue', 'due_soon', 'not_calibrated'].includes(i.calibration_status))
                .sort((a, b) => {
                    if (a.calibration_status === 'overdue' && b.calibration_status !== 'overdue') return -1;
                    if (a.calibration_status !== 'overdue' && b.calibration_status === 'overdue') return 1;
                    return 0;
                })
                .slice(0, 5);
            this.state.recentNcrs = ncrs.slice(0, 5);

            // Prepare charts structure
            this.prepareChartData(jobs, worksheets, instruments, ncrs);

        } catch (error) {
            console.error("Error loading HVAC dashboard data:", error);
        } finally {
            this.state.loading = false;
        }
    }

    prepareChartData(jobs, worksheets, instruments, ncrs) {
        // 1. Job Status distribution
        const jobStates = { draft: 0, scheduled: 0, in_progress: 0, done: 0, cancelled: 0 };
        jobs.forEach(j => {
            if (jobStates[j.state] !== undefined) {
                jobStates[j.state]++;
            }
        });

        this.jobStatusData = {
            labels: ['Draft', 'Scheduled', 'In Progress', 'Completed', 'Cancelled'],
            datasets: [{
                data: [jobStates.draft, jobStates.scheduled, jobStates.in_progress, jobStates.done, jobStates.cancelled],
                backgroundColor: ['#e2e8f0', '#bae6fd', '#fef3c7', '#dcfce7', '#fee2e2'],
                borderColor: ['#94a3b8', '#38bdf8', '#fbbf24', '#4ade80', '#f87171'],
                borderWidth: 1.5
            }]
        };

        // 2. Test Results Trend (Group by test_date)
        const trendsByDate = {};
        worksheets.forEach(w => {
            const dateStr = w.test_date || 'Unknown';
            if (!trendsByDate[dateStr]) {
                trendsByDate[dateStr] = { pass: 0, fail: 0, conditional: 0 };
            }
            if (w.overall_result === 'pass') trendsByDate[dateStr].pass++;
            else if (w.overall_result === 'fail') trendsByDate[dateStr].fail++;
            else if (w.overall_result === 'conditional') trendsByDate[dateStr].conditional++;
        });

        const sortedDates = Object.keys(trendsByDate).sort().slice(-10); // Last 10 test dates
        this.testTrendData = {
            labels: sortedDates.map(d => this.formatOdooDate(d)),
            datasets: [
                {
                    label: 'Pass',
                    data: sortedDates.map(d => trendsByDate[d].pass),
                    backgroundColor: 'rgba(74, 222, 128, 0.75)',
                    borderColor: 'rgba(74, 222, 128, 1)',
                    borderWidth: 1
                },
                {
                    label: 'Fail',
                    data: sortedDates.map(d => trendsByDate[d].fail),
                    backgroundColor: 'rgba(248, 113, 113, 0.75)',
                    borderColor: 'rgba(248, 113, 113, 1)',
                    borderWidth: 1
                },
                {
                    label: 'Conditional',
                    data: sortedDates.map(d => trendsByDate[d].conditional),
                    backgroundColor: 'rgba(251, 191, 36, 0.75)',
                    borderColor: 'rgba(251, 191, 36, 1)',
                    borderWidth: 1
                }
            ]
        };

        // 3. Instrument Calibration Status
        const calStatus = { valid: 0, due_soon: 0, overdue: 0, not_calibrated: 0 };
        instruments.forEach(i => {
            if (calStatus[i.calibration_status] !== undefined) {
                calStatus[i.calibration_status]++;
            }
        });

        this.instrumentCalData = {
            labels: ['Valid', 'Due Soon (≤30d)', 'Overdue', 'Not Calibrated'],
            datasets: [{
                data: [calStatus.valid, calStatus.due_soon, calStatus.overdue, calStatus.not_calibrated],
                backgroundColor: ['#4ade80', '#fbbf24', '#f87171', '#94a3b8'],
                borderColor: '#ffffff',
                borderWidth: 2
            }]
        };

        // 4. NCR Severity Breakdown
        const ncrSeverity = { minor: 0, major: 0, critical: 0 };
        ncrs.forEach(n => {
            if (ncrSeverity[n.severity] !== undefined) {
                ncrSeverity[n.severity]++;
            }
        });

        this.ncrSeverityData = {
            labels: ['Minor', 'Major', 'Critical'],
            datasets: [{
                label: 'NCR Count',
                data: [ncrSeverity.minor, ncrSeverity.major, ncrSeverity.critical],
                backgroundColor: ['#60a5fa', '#f97316', '#ef4444'],
                borderColor: '#ffffff',
                borderWidth: 1.5
            }]
        };
    }

    renderCharts() {
        this.destroyCharts();

        if (!window.Chart || this.state.loading) return;

        // Job Status
        const ctxJob = document.getElementById('jobStatusChart');
        if (ctxJob) {
            this.jobStatusChart = new Chart(ctxJob, {
                type: 'doughnut',
                data: this.jobStatusData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right' }
                    }
                }
            });
        }

        // Test Trend
        const ctxTest = document.getElementById('testTrendChart');
        if (ctxTest) {
            this.testTrendChart = new Chart(ctxTest, {
                type: 'bar',
                data: this.testTrendData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { stacked: true },
                        y: { stacked: true, beginAtZero: true, ticks: { stepSize: 1 } }
                    }
                }
            });
        }

        // Instrument Cal
        const ctxCal = document.getElementById('instrumentCalChart');
        if (ctxCal) {
            this.instrumentCalChart = new Chart(ctxCal, {
                type: 'pie',
                data: this.instrumentCalData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right' }
                    }
                }
            });
        }

        // NCR Severity
        const ctxNcr = document.getElementById('ncrSeverityChart');
        if (ctxNcr) {
            this.ncrSeverityChart = new Chart(ctxNcr, {
                type: 'bar',
                data: this.ncrSeverityData,
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: { beginAtZero: true, ticks: { stepSize: 1 } }
                    }
                }
            });
        }
    }

    destroyCharts() {
        if (this.jobStatusChart) this.jobStatusChart.destroy();
        if (this.testTrendChart) this.testTrendChart.destroy();
        if (this.instrumentCalChart) this.instrumentCalChart.destroy();
        if (this.ncrSeverityChart) this.ncrSeverityChart.destroy();
    }

    // Window Action Redirections
    openJobs(state = null) {
        const domain = state ? [['state', '=', state]] : [];
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hvac.job',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            name: state ? `Job Orders - ${state.toUpperCase()}` : 'All Job Orders',
        });
    }

    openWorksheets(result = null) {
        const domain = result ? [['overall_result', '=', result]] : [];
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hvac.test.sheet',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            name: result ? `Test Sheets - ${result.toUpperCase()}` : 'All Test Worksheets',
        });
    }

    openInstruments(status = null) {
        let domain = [];
        if (status === 'alerts') {
            domain = [['calibration_status', 'in', ['overdue', 'due_soon', 'not_calibrated']]];
        } else if (status) {
            domain = [['calibration_status', '=', status]];
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hvac.instrument',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            name: 'Measuring Instrument Registry',
        });
    }

    openNCRs(state = null) {
        const domain = state ? [['state', '=', state]] : [];
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hvac.ncr',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            name: state ? `Non-Conformance Reports - ${state.toUpperCase()}` : 'All Non-Conformance Reports',
        });
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
