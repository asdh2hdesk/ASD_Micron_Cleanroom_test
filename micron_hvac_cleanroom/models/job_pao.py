from odoo import api, fields, models


class MicronPaoLine(models.Model):
    _name = "micron.pao.line"
    _description = "HEPA Filter Integrity (PAO) Line"
    _order = "sr_no asc, id asc"

    job_id = fields.Many2one("micron.job.order", required=True, ondelete="cascade")
    sr_no = fields.Integer(string="Sr. No.", required=True, default=1)
    filter_no = fields.Char(string="Filter No.")
    upstream_conc_before = fields.Float(
        string="Upstream Conc. Before (µg/L)",
        digits=(16, 3),
        help="Upstream aerosol concentration before filter (20–80 µg/L range)",
    )
    downstream_conc_after = fields.Float(
        string="Downstream Conc. After",
        digits=(16, 4),
        help="Downstream aerosol concentration after filter",
    )
    leakage_pct = fields.Float(
        string="Leakage (%)",
        digits=(16, 4),
        compute="_compute_leakage",
        store=True,
        help="Leakage % = (Downstream / Upstream) × 100",
    )
    pao_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="Result",
        compute="_compute_pao_result",
        store=True,
    )
    remarks = fields.Char(string="Remarks")

    @api.depends("upstream_conc_before", "downstream_conc_after")
    def _compute_leakage(self):
        for rec in self:
            if rec.upstream_conc_before and rec.upstream_conc_before != 0:
                rec.leakage_pct = (rec.downstream_conc_after / rec.upstream_conc_before) * 100.0
            else:
                rec.leakage_pct = 0.0

    @api.depends("leakage_pct", "job_id.run_filter_integrity", "job_id.sop_pao_id.max_value")
    def _compute_pao_result(self):
        """Acceptance: leakage NMT 0.01% (or as per SOP max_value)."""
        for rec in self:
            if not rec.job_id.run_filter_integrity:
                rec.pao_result = "na"
                continue
            sop = rec.job_id.sop_pao_id
            # Default acceptance: leakage <= 0.01%
            max_allowed = sop.max_value if sop and sop.max_value else 0.01
            rec.pao_result = "pass" if rec.leakage_pct <= max_allowed else "fail"

    _sql_constraints = [
        ("sr_no_positive", "CHECK(sr_no > 0)", "Serial number must be greater than zero."),
    ]
