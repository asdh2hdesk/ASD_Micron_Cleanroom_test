from odoo import models, fields, api


class HvacVl002Line(models.Model):
    """
    One row = one HEPA filter scanned by aerosol photometer.
    Matches the column structure of VL-002 Annexure I (PAO / HEPA Filter Integrity Test).
    Acceptance: downstream leakage NMT 0.01% of upstream challenge (ISO 14644-3:2019 Annex B6).
    """
    _name = 'hvac.vl002.line'
    _description = 'HEPA Filter Integrity (PAO) Line — SOP VL-002'
    _order = 'sequence, id'

    sheet_id = fields.Many2one('hvac.test.sheet', required=True, ondelete='cascade')
    sequence = fields.Integer('Seq', default=10)

    # ── Filter identification ────────────────────────────────────────────
    room_name = fields.Char(
        'Room Name & No.',
        help='Room name and number as per cleanroom drawing',
    )
    filter_id = fields.Char(
        'Filter Tag No.',
        help='Filter tag as per equipment drawing (e.g. HEPA-B01-14, F-01)',
    )
    filter_location = fields.Char(
        'Filter Location / Position',
        help='Describe where in the room or AHU this filter is mounted',
    )

    # ── PAO upstream concentrations (µg/L) ──────────────────────────────
    upstream_before = fields.Float(
        'Upstream Conc. Before (µg/L)',
        digits=(8, 3),
        help='Upstream challenge concentration BEFORE scanning this filter (20–80 µg/L)',
    )
    upstream_after = fields.Float(
        'Upstream Conc. After (µg/L)',
        digits=(8, 3),
        help='Upstream challenge concentration AFTER scanning this filter',
    )

    # ── Downstream leakage reading ───────────────────────────────────────
    downstream_pct = fields.Float(
        'Downstream Leakage (%)',
        digits=(8, 4),
        help='Maximum downstream photometer reading as % of upstream concentration',
    )

    # ── Computed: upstream recovery check ───────────────────────────────
    upstream_recovery_pct = fields.Float(
        'Upstream Recovery (%)',
        compute='_compute_recovery',
        store=True,
        digits=(6, 1),
        help='= (After / Before) × 100. Must be 85–115% for valid test.',
    )
    recovery_valid = fields.Boolean(
        'Recovery Valid (85–115%)',
        compute='_compute_recovery',
        store=True,
    )

    # ── Acceptance limits (editable per line if protocol specifies otherwise) ──
    max_leakage_pct = fields.Float(
        'Max Allowable Leakage (%)',
        digits=(6, 4),
        default=0.01,
        help='ISO 14644-3:2019 Annex B6 — NMT 0.01%',
    )
    min_recovery_pct = fields.Float('Min Recovery (%)', default=85.0)
    max_recovery_pct = fields.Float('Max Recovery (%)', default=115.0)

    # ── Pass / Fail ──────────────────────────────────────────────────────
    pao_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='PAO Result',
        compute='_compute_pao_result',
        store=True,
    )

    remark = fields.Char('Remark / Observation')

    # ────────────────────────────────────────────────────────────────────
    # Computes
    # ────────────────────────────────────────────────────────────────────

    @api.depends('upstream_before', 'upstream_after',
                 'min_recovery_pct', 'max_recovery_pct')
    def _compute_recovery(self):
        for rec in self:
            if rec.upstream_before and rec.upstream_after:
                pct = (rec.upstream_after / rec.upstream_before) * 100.0
                rec.upstream_recovery_pct = round(pct, 1)
                rec.recovery_valid = (
                    rec.min_recovery_pct <= pct <= rec.max_recovery_pct
                )
            else:
                rec.upstream_recovery_pct = 0.0
                rec.recovery_valid = False

    @api.depends(
        'downstream_pct', 'max_leakage_pct',
        'upstream_before', 'recovery_valid',
    )
    def _compute_pao_result(self):
        for rec in self:
            if not rec.upstream_before:
                rec.pao_result = 'na'
                continue
            leakage_ok = rec.downstream_pct <= rec.max_leakage_pct
            # Recovery check — only fail result if recovery is also out of range
            # (per ISO 14644-3:2019 the test must be repeated if recovery fails)
            if not leakage_ok:
                rec.pao_result = 'fail'
            elif not rec.recovery_valid and rec.upstream_after:
                # recovery check failed — mark conditional / note in remark
                rec.pao_result = 'fail'
            else:
                rec.pao_result = 'pass'
