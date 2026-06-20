from odoo import api, fields, models


class MicronRecoveryLine(models.Model):
    _name = "micron.recovery.line"
    _description = "Recovery Test Reading Line"
    _order = "sr_no asc, id asc"

    job_id = fields.Many2one("micron.job.order", required=True, ondelete="cascade")
    sr_no = fields.Integer(string="Sr. No.", required=True, default=1)
    ahu_condition = fields.Selection(
        [
            ("initial", "Initial"),
            ("generation", "Generation"),
            ("recovery_period", "Recovery Period"),
        ],
        string="AHU Condition",
        required=True,
        default="initial",
    )
    # Stored as Float hours so widget=float_time shows HH:MM
    time_start = fields.Float(string="Start Time", digits=(2, 4), help="Time in HH.MM format (float_time widget)")
    time_end = fields.Float(string="End Time", digits=(2, 4))
    particles_05um = fields.Float(string="0.5µm (particles/m³)", digits=(16, 0))
    particles_50um = fields.Float(string="5.0µm (particles/m³)", digits=(16, 0))
    remarks = fields.Char(string="Remarks")

    _sql_constraints = [
        ("sr_no_positive", "CHECK(sr_no > 0)", "Serial number must be greater than zero."),
    ]
