from odoo import models, fields, api

# ISO 14644-1:2015 particle limits (particles/m³)
# Keys = iso_class selection value
_ISO_LIMITS = {
    'iso5': {'05um': 3_520,       '50um': 29},
    'iso6': {'05um': 35_200,      '50um': 293},
    'iso7': {'05um': 352_000,     '50um': 2_930},
    'iso8': {'05um': 3_520_000,   '50um': 29_300},
    'iso9': {'05um': 35_200_000,  '50um': 293_000},
}


class HvacVl003Line(models.Model):
    """
    One row = one sampling location (L1, L2 ... LN).
    Matches VL-003 Annexure I — Non-Viable Particle Count (NVPC) Test.
    Standard: ISO 14644-1:2015 / ISO 14644-3:2019 Annex B3.
    """
    _name = 'hvac.vl003.line'
    _description = 'Particle Count (NVPC) Line — SOP VL-003'
    _order = 'sequence, id'

    sheet_id = fields.Many2one('hvac.test.sheet', required=True, ondelete='cascade')
    sequence = fields.Integer('Seq', default=10)

    # ── Sampling location ────────────────────────────────────────────────
    room_name = fields.Char(
        'Room Name & No.',
        help='Room name and number as per cleanroom drawing',
    )
    location_id = fields.Char(
        'Location',
        help='Sampling location label (e.g. L1, L2, L3 …). Min locations N = √Area (m²).',
    )
    location_desc = fields.Char(
        'Location Description',
        help='Where in the room is this location (e.g. Near LAF, Centre, Corner)',
    )

    # ── Test condition ────────────────────────────────────────────────────
    test_condition = fields.Selection(
        [('at_rest', 'At Rest'), ('in_operation', 'In Operation')],
        string='Test Condition',
        default='at_rest',
    )

    # ── Instrument settings ──────────────────────────────────────────────
    flow_rate = fields.Char('Flow Rate', default='28.3 LPM')
    sample_time_min = fields.Float('Sample Time (min)', default=1.0)
    sample_volume = fields.Char('Sample Volume', default='0.0283 m³/min')

    # ── Particle counts (particles/m³) ───────────────────────────────────
    count_05um = fields.Float(
        '0.5 µm Count (particles/m³)',
        digits=(14, 0),
        help='Raw count at 0.5 µm channel converted to particles per m³',
    )
    count_50um = fields.Float(
        '5.0 µm Count (particles/m³)',
        digits=(14, 0),
        help='Raw count at 5.0 µm channel converted to particles per m³',
    )

    # ── ISO class (determines acceptance limits) ─────────────────────────
    iso_class = fields.Selection(
        [
            ('iso5', 'ISO Class 5 (Grade A/B)'),
            ('iso6', 'ISO Class 6'),
            ('iso7', 'ISO Class 7 (Grade C)'),
            ('iso8', 'ISO Class 8 (Grade D)'),
            ('iso9', 'ISO Class 9'),
        ],
        string='ISO Class',
        default='iso8',
        required=True,
    )

    # ── Limits (computed from iso_class) ─────────────────────────────────
    limit_05um = fields.Float(
        'Limit 0.5 µm (particles/m³)',
        compute='_compute_limits',
        store=True,
        digits=(14, 0),
    )
    limit_50um = fields.Float(
        'Limit 5.0 µm (particles/m³)',
        compute='_compute_limits',
        store=True,
        digits=(14, 0),
    )

    # ── Pass / Fail per channel ──────────────────────────────────────────
    result_05 = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='0.5 µm Result',
        compute='_compute_results',
        store=True,
    )
    result_50 = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='5.0 µm Result',
        compute='_compute_results',
        store=True,
    )

    remark = fields.Char('Remark / Observation')

    # ────────────────────────────────────────────────────────────────────
    # Computes
    # ────────────────────────────────────────────────────────────────────

    @api.depends('iso_class')
    def _compute_limits(self):
        for rec in self:
            limits = _ISO_LIMITS.get(rec.iso_class, {})
            rec.limit_05um = limits.get('05um', 0.0)
            rec.limit_50um = limits.get('50um', 0.0)

    @api.depends('count_05um', 'count_50um', 'limit_05um', 'limit_50um')
    def _compute_results(self):
        for rec in self:
            # 0.5 µm
            if rec.count_05um and rec.limit_05um:
                rec.result_05 = 'pass' if rec.count_05um <= rec.limit_05um else 'fail'
            else:
                rec.result_05 = 'na'
            # 5.0 µm
            if rec.count_50um and rec.limit_50um:
                rec.result_50 = 'pass' if rec.count_50um <= rec.limit_50um else 'fail'
            else:
                rec.result_50 = 'na'
