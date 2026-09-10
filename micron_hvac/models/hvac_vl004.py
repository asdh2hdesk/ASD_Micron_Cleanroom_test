from odoo import models, fields, api

from .hvac_criteria import ISO_LIMITS


class HvacVl004Line(models.Model):
    """
    One row = one 1-minute monitoring interval during recovery test.
    Matches VL-004 Annexure I — Recovery Study (AHU Condition table).
    Acceptance: recovery to ISO class within NMT 15 minutes
    (ISO 14644-3:2019 Annex B12 / ISPE Baseline Guide Vol. 5).

    Per-row evaluation follows SOP MHPL-SOP-VL-004:
      · Initial    — must be at or below the class limit (step 1.5)
      · Generation — must reach at least 100× the class limit (step 2.2)
      · Recovery   — still decaying until it falls to the class limit (step 3.3)
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

    # ── Instrument settings (printed on the annexure header) ─────────────
    flow_rate = fields.Char('Flow Rate', default='28.3 LPM')
    sample_volume = fields.Char('Sample Volume', default='0.0283 m³/min')

    # ── Particle counts (particles/m³) ───────────────────────────────────
    count_05um = fields.Float(
        '0.5 µm Count (particles/m³)',
        digits=(14, 0),
    )
    count_50um = fields.Float(
        '5.0 µm Count (particles/m³)',
        digits=(14, 0),
    )

    # ── Acceptance limit for the room's class (from the sheet) ───────────
    limit_05um = fields.Float(
        'Class Limit 0.5 µm (particles/m³)',
        compute='_compute_limit', store=True, readonly=False, digits=(14, 0),
        help='ISO class limit the room must fall back to, taken from the '
             'Room ISO Class on the worksheet.',
    )
    challenge_limit = fields.Float(
        'Min Challenge Count (particles/m³)',
        compute='_compute_limit', store=True, digits=(14, 0),
        help='Challenge must reach this count to be valid (SOP step 2.2 — '
             'at least 100× the class limit).',
    )

    # ── Per-row evaluation ───────────────────────────────────────────────
    result = fields.Selection(
        [
            ('pass', 'PASS'),
            ('fail', 'FAIL'),
            ('recovering', 'RECOVERING'),
            ('na', 'N/A'),
        ],
        string='Result',
        compute='_compute_result', store=True,
    )
    class_regained = fields.Boolean(
        'ISO Class Regained',
        compute='_compute_class_regained', store=True,
        help='First recovery interval at or below the class limit that stays '
             'below for two consecutive readings — this row establishes Time B.',
    )

    remark = fields.Char('Remark / Observation')

    # ────────────────────────────────────────────────────────────────────
    # Computes
    # ────────────────────────────────────────────────────────────────────

    @api.depends('sheet_id.recovery_iso_class', 'sheet_id.lim_recovery_limit_05um',
                 'sheet_id.lim_challenge_factor')
    def _compute_limit(self):
        for rec in self:
            sheet = rec.sheet_id
            limit = sheet.lim_recovery_limit_05um if sheet else 0.0
            if not limit:
                limit = float(ISO_LIMITS['iso8']['05um'])
            rec.limit_05um = limit
            rec.challenge_limit = limit * ((sheet.lim_challenge_factor if sheet else 0) or 100.0)

    @api.depends('ahu_condition', 'count_05um', 'limit_05um', 'challenge_limit')
    def _compute_result(self):
        for rec in self:
            if not rec.count_05um or not rec.limit_05um:
                rec.result = 'na'
            elif rec.ahu_condition == 'initial':
                # SOP 1.5 — baseline must already be at or below class
                rec.result = 'pass' if rec.count_05um <= rec.limit_05um else 'fail'
            elif rec.ahu_condition == 'generation':
                # SOP 2.2 — challenge must be at least 100× the class limit
                rec.result = 'pass' if rec.count_05um >= rec.challenge_limit else 'fail'
            else:
                # SOP 3.3 — recovery intervals decay towards the class limit
                rec.result = 'pass' if rec.count_05um <= rec.limit_05um else 'recovering'

    @api.depends('sheet_id.vl004_line_ids.count_05um',
                 'sheet_id.vl004_line_ids.ahu_condition',
                 'sheet_id.vl004_line_ids.limit_05um',
                 'sheet_id.vl004_line_ids.sequence')
    def _compute_class_regained(self):
        for sheet in self.mapped('sheet_id'):
            regained = sheet._vl004_regained_line()
            for line in sheet.vl004_line_ids:
                line.class_regained = line == regained
        for rec in self.filtered(lambda r: not r.sheet_id):
            rec.class_regained = False
