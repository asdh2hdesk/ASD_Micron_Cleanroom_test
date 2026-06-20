from odoo import fields, models


class MicronCleanRoomArea(models.Model):
    _name = "micron.clean.room.area"
    _description = "Clean Room Area"

    name = fields.Char(required=True)
    client_id = fields.Many2one(
        "res.partner",
        required=True,
        domain=[("is_company", "=", True)],
    )
    site_reference = fields.Char()
    area_grade = fields.Selection(
        [
            ("a", "Grade A"),
            ("b", "Grade B"),
            ("c", "Grade C"),
            ("d", "Grade D"),
            ("other", "Other"),
        ],
        default="other",
    )
    active = fields.Boolean(default=True)
