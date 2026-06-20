from odoo import api, fields, models


class MicronDiffPressureLine(models.Model):
    _name = "micron.diff.pressure.line"
    _description = "Differential Pressure Reading Line"
    _order = "sr_no asc, id asc"

    job_id = fields.Many2one("micron.job.order", required=True, ondelete="cascade")
    sr_no = fields.Integer(string="Sr. No.", required=True, default=1)
    room_from = fields.Char(string="From Room (Higher Pressure)")
    room_to = fields.Char(string="To Room (Lower Pressure / Adjacent)")
    pressure_pa = fields.Float(string="Differential Pressure (Pa)", digits=(16, 2))
    result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="Result",
        compute="_compute_result",
        store=True,
    )
    remarks = fields.Char(string="Remarks")

    @api.depends(
        "pressure_pa",
        "job_id.run_diff_pressure",
        "job_id.sop_diff_pressure_id.min_value",
        "job_id.sop_diff_pressure_id.max_value",
    )
    def _compute_result(self):
        for rec in self:
            if not rec.job_id.run_diff_pressure:
                rec.result = "na"
                continue
            sop = rec.job_id.sop_diff_pressure_id
            if not sop:
                rec.result = "na"
                continue
            min_ok = (sop.min_value == 0.0) or (rec.pressure_pa >= sop.min_value)
            max_ok = (sop.max_value == 0.0) or (rec.pressure_pa <= sop.max_value)
            rec.result = "pass" if min_ok and max_ok else "fail"

    _sql_constraints = [
        ("sr_no_positive", "CHECK(sr_no > 0)", "Serial number must be greater than zero."),
    ]
