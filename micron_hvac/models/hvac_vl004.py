from odoo import models, fields, api

# ISO 14644-1:2015 class limits for 0.5 µm (particles/m³) — used for baseline check
_ISO_LIMIT_05UM = {
    'iso5': 3_520,
    'iso6': 35_200,
    'iso7': 352_000,
    'iso8': 3_520_000,
    'iso9': 35_200_000,
}


class HvacVl004Line(models.Model):
    """
    One row = one 1-minute monitoring interval during recovery test.
    Matches VL-004 Annexure I — Recovery Study (AHU Condition table).
    Acceptance: recovery to ISO class within NMT 15 minutes
    (ISO 14644-3:2019 Annex B12 / ISPE Baseline Guide Vol. 5).
    """
    _name = 'hvac.vl004.line'
    _description = 'Recovery Study Interval Line — SOP VL-004'
    _order = 'sequence, id'

    sheet_id = fields.Many2one('hvac.test.sheet', required=True, ondelete='cascade')
    sequence = fields.Integer('Seq', default=10)

    # ── AHU Condition / Phase ────────────────────────────────────────────
    room_name = fields.Char(
        'Room Name & No.',
        help='Room name and number as per cleanroom drawing',
    )
    ahu_condition = fields.Selection(
        [
            ('initial',    'Initial (Baseline)'),
            ('generation', 'Generation (Challenge)'),
            ('recovery',   'Recovery'),
        ],
        string='AHU Condition',
        required=True,
        default='recovery',
        help='Phase of the recovery study for this time interval',
    )

    # ── Timing ───────────────────────────────────────────────────────────
    time_start = fields.Char(
        'Start Time',
        help='Time at start of this 1-minute interval (e.g. 10:30)',
    )
    time_end = fields.Char(
        'End Time',
        help='Time at end of this 1-minute interval (e.g. 10:31)',
    )

    # ── Particle counts (particles/m³) ───────────────────────────────────
    count_05um = fields.Float(
        '0.5 µm Count (particles/m³)',
        digits=(14, 0),
    )
    count_50um = fields.Float(
        '5.0 µm Count (particles/m³)',
        digits=(14, 0),
    )

    remark = fields.Char('Remark / Observation')

