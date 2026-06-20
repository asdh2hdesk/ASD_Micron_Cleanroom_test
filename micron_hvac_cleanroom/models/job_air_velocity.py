from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MicronAirVelocityLine(models.Model):
    _name = "micron.air.velocity.line"
    _description = "Air Velocity Reading"
    _order = "sr_no asc, id asc"

    def init(self):
        # Safety cleanup for legacy data after field type migration (char -> many2one).
        self.env.cr.execute(
            """
            UPDATE micron_air_velocity_line l
               SET equipment_name_id = NULL
             WHERE equipment_name_id IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM micron_equipment e
                     WHERE e.id = l.equipment_name_id
               )
            """
        )

    job_id = fields.Many2one("micron.job.order", required=True, ondelete="cascade")
    sr_no = fields.Integer(string="Sr. No.", required=True, default=1)
    equipment_name_id = fields.Many2one("micron.equipment", string="Equipment Name & ID")
    filter_no = fields.Char(string="Filter No.")
    reading_1 = fields.Float(string="Reading 1", digits=(16, 3))
    reading_2 = fields.Float(string="Reading 2", digits=(16, 3))
    reading_3 = fields.Float(string="Reading 3", digits=(16, 3))
    reading_4 = fields.Float(string="Reading 4", digits=(16, 3))
    reading_5 = fields.Float(string="Reading 5", digits=(16, 3))
    row_avg = fields.Float(string="Average Air Velocity", digits=(16, 3), compute="_compute_row_avg", store=True)
    row_pass = fields.Boolean(string="Row Pass", compute="_compute_row_acceptance")
    row_fail = fields.Boolean(string="Row Fail", compute="_compute_row_acceptance")
    unit = fields.Char(default="m/s")
    remarks = fields.Char(string="Remarks")

    _sql_constraints = [
        ("sr_no_positive", "CHECK(sr_no > 0)", "Serial number must be greater than zero."),
    ]

    @api.depends("reading_1", "reading_2", "reading_3", "reading_4", "reading_5")
    def _compute_row_avg(self):
        for rec in self:
            values = [rec.reading_1, rec.reading_2, rec.reading_3, rec.reading_4, rec.reading_5]
            if values:
                rec.row_avg = sum(values) / 5.0
            else:
                rec.row_avg = 0.0

    @api.depends(
        "row_avg",
        "job_id.run_air_velocity",
        "job_id.sop_air_velocity_id.min_value",
        "job_id.sop_air_velocity_id.max_value",
    )
    def _compute_row_acceptance(self):
        """
        Used only for UI decorations (green/red) on the readings table.
        Validation is done against SOP min/max in the selected SOP template.
        """
        for rec in self:
            rec.row_pass = False
            rec.row_fail = False

            if not rec.job_id.run_air_velocity:
                continue

            sop = rec.job_id.sop_air_velocity_id
            if not sop:
                continue

            row_val = rec.row_avg or 0.0
            min_value = sop.min_value or 0.0
            max_value = sop.max_value or 0.0

            min_ok = (min_value == 0.0) or (row_val >= min_value)
            max_ok = (max_value == 0.0) or (row_val <= max_value)
            in_spec = bool(min_ok and max_ok)

            rec.row_pass = in_spec
            rec.row_fail = not in_spec

    @api.constrains("job_id", "sr_no")
    def _check_unique_sr_no(self):
        for rec in self:
            duplicate = self.search_count(
                [("id", "!=", rec.id), ("job_id", "=", rec.job_id.id), ("sr_no", "=", rec.sr_no)]
            )
            if duplicate:
                raise ValidationError("Serial number must be unique within a job.")
