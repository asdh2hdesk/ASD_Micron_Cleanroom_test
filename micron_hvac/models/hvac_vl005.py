from odoo import models, fields, api


class HvacVl005Line(models.Model):
    """
    One row = one data logger / measurement location.
    Matches VL-005 Annexure I — Temperature & Relative Humidity Study.
    Standards: EU GMP Annex 1, WHO TRS 986, Schedule M (Revised) 2023.
    Default acceptance: 18–27°C, 30–65% RH (pharmaceutical cleanroom general).
    """
    _name = 'hvac.vl005.line'
    _description = 'Temperature & RH Study Line — SOP VL-005'
    _order = 'sequence, id'

    sheet_id = fields.Many2one('hvac.test.sheet', required=True, ondelete='cascade')
    sequence = fields.Integer('Seq', default=10)

    # ── Data logger / position ────────────────────────────────────────────
    room_name = fields.Char(
        'Room Name & No.',
        help='Room name and number as per cleanroom drawing',
    )
    logger_id = fields.Char(
        'Logger ID',
        help='Unique logger identifier (e.g. Logger-1, P1, TRH-001)',
    )
    position = fields.Char(
        'Position Description',
        help='Physical placement description (e.g. Near Supply Diffuser, Centre, Corner NE)',
    )

    # ── Temperature readings (°C) ─────────────────────────────────────────
    temp_mean = fields.Float('Mean Temp (°C)', digits=(5, 2))
    temp_min  = fields.Float('Min Temp (°C)',  digits=(5, 2))
    temp_max  = fields.Float('Max Temp (°C)',  digits=(5, 2))
    temp_range = fields.Float(
        'Temp Range (°C)',
        compute='_compute_ranges',
        store=True,
        digits=(4, 2),
        help='Max - Min at this logger position. Specification: NMT 2°C variation.',
    )

    # ── Relative Humidity readings (%RH) ─────────────────────────────────
    rh_mean = fields.Float('Mean RH (%)', digits=(5, 2))
    rh_min  = fields.Float('Min RH (%)',  digits=(5, 2))
    rh_max  = fields.Float('Max RH (%)',  digits=(5, 2))
    rh_range = fields.Float(
        'RH Range (%)',
        compute='_compute_ranges',
        store=True,
        digits=(4, 2),
        help='Max - Min at this logger position. Specification: NMT 5% RH variation.',
    )

    # ── Acceptance limits (per-line, editable — default general pharma cleanroom) ──
    temp_min_limit = fields.Float('Temp Min Limit (°C)', default=18.0, digits=(5, 1))
    temp_max_limit = fields.Float('Temp Max Limit (°C)', default=27.0, digits=(5, 1))
    rh_min_limit   = fields.Float('RH Min Limit (%)',    default=30.0, digits=(5, 1))
    rh_max_limit   = fields.Float('RH Max Limit (%)',    default=65.0, digits=(5, 1))
    max_temp_range_limit = fields.Float(
        'Max Allowed Temp Range (°C)', default=2.0,
        help='Max allowed temperature variation at a single logger position over monitoring period.',
    )
    max_rh_range_limit = fields.Float(
        'Max Allowed RH Range (%)', default=5.0,
        help='Max allowed RH variation at a single logger position over monitoring period.',
    )

    # ── Pass / Fail results ───────────────────────────────────────────────
    temp_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='Temp Result',
        compute='_compute_results',
        store=True,
    )
    rh_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='RH Result',
        compute='_compute_results',
        store=True,
    )
    stability_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='Stability Result',
        compute='_compute_results',
        store=True,
        help='Pass if both temp_range ≤ max_temp_range_limit AND rh_range ≤ max_rh_range_limit',
    )

    remark = fields.Char('Remark / Observation')

    # ────────────────────────────────────────────────────────────────────
    # Computes
    # ────────────────────────────────────────────────────────────────────

    @api.depends('temp_max', 'temp_min', 'rh_max', 'rh_min')
    def _compute_ranges(self):
        for rec in self:
            rec.temp_range = (
                round(rec.temp_max - rec.temp_min, 2)
                if rec.temp_max or rec.temp_min else 0.0
            )
            rec.rh_range = (
                round(rec.rh_max - rec.rh_min, 2)
                if rec.rh_max or rec.rh_min else 0.0
            )

    @api.depends(
        'temp_mean', 'temp_min_limit', 'temp_max_limit',
        'rh_mean',   'rh_min_limit',   'rh_max_limit',
        'temp_range', 'rh_range',
        'max_temp_range_limit', 'max_rh_range_limit',
    )
    def _compute_results(self):
        for rec in self:
            # Temperature mean within limits
            if rec.temp_mean:
                rec.temp_result = (
                    'pass'
                    if rec.temp_min_limit <= rec.temp_mean <= rec.temp_max_limit
                    else 'fail'
                )
            else:
                rec.temp_result = 'na'

            # RH mean within limits
            if rec.rh_mean:
                rec.rh_result = (
                    'pass'
                    if rec.rh_min_limit <= rec.rh_mean <= rec.rh_max_limit
                    else 'fail'
                )
            else:
                rec.rh_result = 'na'

            # Stability (variation at this location)
            temp_stable = (
                rec.temp_range <= rec.max_temp_range_limit
                if rec.temp_range else True
            )
            rh_stable = (
                rec.rh_range <= rec.max_rh_range_limit
                if rec.rh_range else True
            )
            if rec.temp_mean or rec.rh_mean:
                rec.stability_result = (
                    'pass' if temp_stable and rh_stable else 'fail'
                )
            else:
                rec.stability_result = 'na'
