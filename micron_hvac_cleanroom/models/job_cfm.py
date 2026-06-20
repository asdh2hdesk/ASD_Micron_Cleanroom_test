from odoo import api, fields, models


class MicronCfmLine(models.Model):
    _name = "micron.cfm.line"
    _description = "CFM / ACPH Reading Line"
    _order = "sr_no asc, id asc"

    job_id = fields.Many2one("micron.job.order", required=True, ondelete="cascade")
    sr_no = fields.Integer(string="Sr. No.", required=True, default=1)
    room_name = fields.Char(string="Room Name & No.")
    filter_code = fields.Char(string="Filter Code")
    actual_cfm = fields.Float(string="Actual CFM", digits=(16, 2))
    # total_cfm is the sum of all actual_cfm in the same room group
    total_cfm = fields.Float(string="Total CFM", digits=(16, 2), compute="_compute_acph", store=True)
    room_vol_ft3 = fields.Float(string="Room Vol. (Ft³)", digits=(16, 2))
    acph = fields.Float(string="ACPH", digits=(16, 2), compute="_compute_acph", store=True)
    acph_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="Result",
        compute="_compute_acph_result",
        store=True,
    )
    remarks = fields.Char(string="Remarks")

    @api.depends("actual_cfm", "room_vol_ft3", "job_id.cfm_line_ids.actual_cfm", "job_id.cfm_line_ids.room_name")
    def _compute_acph(self):
        for rec in self:
            # Sum all CFM lines for same room (group by room_name)
            if rec.room_name and rec.job_id:
                siblings = rec.job_id.cfm_line_ids.filtered(lambda l: l.room_name == rec.room_name)
                total = sum(siblings.mapped("actual_cfm"))
            else:
                total = rec.actual_cfm or 0.0
            rec.total_cfm = total
            if rec.room_vol_ft3 and rec.room_vol_ft3 != 0:
                rec.acph = (total * 60.0) / rec.room_vol_ft3
            else:
                rec.acph = 0.0

    @api.depends("acph", "job_id.sop_cfm_id.min_value", "job_id.run_ach")
    def _compute_acph_result(self):
        for rec in self:
            if not rec.job_id.run_ach:
                rec.acph_result = "na"
                continue
            sop = rec.job_id.sop_cfm_id
            if not sop or not rec.acph:
                rec.acph_result = "fail"
                continue
            min_ok = (sop.min_value == 0.0) or (rec.acph >= sop.min_value)
            max_ok = (sop.max_value == 0.0) or (rec.acph <= sop.max_value)
            rec.acph_result = "pass" if min_ok and max_ok else "fail"

    _sql_constraints = [
        ("sr_no_positive", "CHECK(sr_no > 0)", "Serial number must be greater than zero."),
    ]
