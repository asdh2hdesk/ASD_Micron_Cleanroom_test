from odoo import api, fields, models

# ISO 14644-1 class limits (particles/m³)
ISO_LIMITS = {
    "iso5": {"05": 3520,       "50": 29},
    "iso6": {"05": 35200,      "50": 293},
    "iso7": {"05": 352000,     "50": 2930},
    "iso8": {"05": 3520000,    "50": 29300},
    "iso9": {"05": 35200000,   "50": 293000},
}


class MicronParticleLine(models.Model):
    _name = "micron.particle.line"
    _description = "Non-Viable Particle Count (NVPC) Line"
    _order = "sr_no asc, condition asc, id asc"

    job_id = fields.Many2one("micron.job.order", required=True, ondelete="cascade")
    sr_no = fields.Integer(string="Sr. No.", required=True, default=1)
    room_name = fields.Char(string="Room Name & No.")
    location = fields.Char(string="Location", help="Sampling point e.g. L1, L2, L3 ...")
    condition = fields.Selection(
        [("at_rest", "At Rest"), ("in_operation", "In Operation")],
        string="Condition",
        default="at_rest",
        required=True,
    )
    particles_05um = fields.Float(string="0.5µm (particles/m³)", digits=(16, 0))
    particles_50um = fields.Float(string="5.0µm (particles/m³)", digits=(16, 0))
    result_05 = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="0.5µm Result",
        compute="_compute_results",
        store=True,
    )
    result_50 = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="5.0µm Result",
        compute="_compute_results",
        store=True,
    )
    remarks = fields.Char(string="Remarks")

    @api.depends(
        "particles_05um", "particles_50um",
        "job_id.run_particle_count", "job_id.iso_class",
    )
    def _compute_results(self):
        for rec in self:
            if not rec.job_id.run_particle_count:
                rec.result_05 = "na"
                rec.result_50 = "na"
                continue
            iso_key = rec.job_id.iso_class or "iso8"
            limits = ISO_LIMITS.get(iso_key, {})
            limit_05 = limits.get("05", 0)
            limit_50 = limits.get("50", 0)
            rec.result_05 = "pass" if (not limit_05 or rec.particles_05um <= limit_05) else "fail"
            rec.result_50 = "pass" if (not limit_50 or rec.particles_50um <= limit_50) else "fail"

    _sql_constraints = [
        ("sr_no_positive", "CHECK(sr_no > 0)", "Serial number must be greater than zero."),
    ]
