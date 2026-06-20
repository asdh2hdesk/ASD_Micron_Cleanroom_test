from odoo import api, fields, models


class MicronEquipment(models.Model):
    _name = "micron.equipment"
    _description = "Micron Test Equipment"
    _rec_name = "display_name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    serial_number = fields.Char()
    instrument_type = fields.Selection(
        [
            ("anemometer", "Anemometer (Vane Probe)"),
            ("air_capture_hood", "Air Capture Hood"),
            ("particle_counter", "Particle Counter"),
            ("aerosol_photometer", "Aerosol Photometer"),
            ("manometer", "Manometer / Pressure Gauge"),
            ("thermohygrometer", "Thermo-Hygrometer"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
    )
    calibration_date = fields.Date(string="Calibration Date")
    calibration_due_date = fields.Date(required=True)
    model_no = fields.Char(string="Model No.")
    is_active = fields.Boolean(default=True)
    notes = fields.Text()
    display_name = fields.Char(compute="_compute_display_name", store=True)

    _sql_constraints = [
        ("code_unique", "unique(code)", "Equipment code must be unique."),
    ]

    def init(self):
        # Ensure stored computed labels are populated after module upgrade.
        self.search([])._compute_display_name()

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            if rec.code and rec.name:
                rec.display_name = f"[{rec.code}] {rec.name}"
            elif rec.name:
                rec.display_name = rec.name
            elif rec.code:
                rec.display_name = rec.code
            else:
                rec.display_name = "Unnamed"
