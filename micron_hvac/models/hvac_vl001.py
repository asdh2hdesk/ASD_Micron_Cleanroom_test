from odoo import models, fields, api


class HvacVl001Line(models.Model):
    """
    One row = one HEPA filter measurement location.
    Matches the column structure of Annexure I–IV (MHPL-SOP-VL-001).
    """
    _name = 'hvac.vl001.line'
    _description = 'Air Velocity & CFM Measurement Line (SOP VL-001)'
    _order = 'sequence, id'

    sheet_id = fields.Many2one('hvac.test.sheet', required=True, ondelete='cascade')
    sequence = fields.Integer('Seq', default=10)

    # ── Location ────────────────────────────────────────────────────
    room_name = fields.Char('Room Name & No.',
                             help='Room name and number as per cleanroom drawing (e.g. Production Room — R-14)')
    equipment_name = fields.Char('Equipment / Area Name',
                                  help='For Annexure II: LAF unit, BSC, or equipment tag')
    filter_id = fields.Char('Filter ID',
                             help='Filter tag as per equipment drawing (e.g. F-01, HEPA-B01-14)')

    # ── 5-point velocity traverse readings (FPM) ─────────────────
    vel_1 = fields.Float('V1 (FPM)', digits=(16, 2))
    vel_2 = fields.Float('V2 (FPM)', digits=(16, 2))
    vel_3 = fields.Float('V3 (FPM)', digits=(16, 2))
    vel_4 = fields.Float('V4 (FPM)', digits=(16, 2))
    vel_5 = fields.Float('V5 (FPM)', digits=(16, 2))

    # ── Computed averages ─────────────────────────────────────────
    avg_fpm = fields.Float('Avg (FPM)', compute='_compute_avgs', store=True, digits=(16, 2))
    avg_ms  = fields.Float('Avg (m/s)', compute='_compute_avgs', store=True, digits=(5, 3))

    # ── Filter dimensions (for CFM calculation) ───────────────────
    filter_size_ft2 = fields.Float('Filter Size (Ft²)', digits=(6, 2),
                                    help='Filter face area in square feet (Width × Height)')

    # ── Computed air flows ────────────────────────────────────────
    cfm = fields.Float('CFM', compute='_compute_cfm', store=True, digits=(7, 0),
                        help='Individual filter flow = Avg FPM × Filter Size (Ft²)')
    cmh = fields.Float('CMH (m³/h)', compute='_compute_cfm', store=True, digits=(7, 0),
                        help='CFM × 1.699 — SI equivalent for Annexure IV')

    # ── Room volume (entered once per room; repeat for each filter in same room) ──
    room_vol_ft3 = fields.Float('Room Vol (Ft³)', digits=(10, 0))
    room_vol_m3  = fields.Float('Room Vol (m³)', compute='_compute_vols', store=True, digits=(8, 2))

    # ── ACPH and room total CFM (computed from all filters sharing same room_name) ──
    total_room_cfm = fields.Float('Room Total CFM', compute='_compute_acph', store=True, digits=(7, 0),
                                   help='Sum of CFM from all filters in this room')
    acph = fields.Float('ACPH', compute='_compute_acph', store=True, digits=(6, 1),
                         help='= (Total Room CFM × 60) ÷ Room Volume (Ft³)')

    remark = fields.Char('Remark / Observation')

    # ── Acceptance limits (pre-set from SOP; editable per line if needed) ────
    min_vel_ms = fields.Float('Min (m/s)', digits=(4, 2), default=0.36)
    max_vel_ms = fields.Float('Max (m/s)', digits=(4, 2), default=0.54)
    min_acph   = fields.Float('Min ACPH', digits=(5, 0), default=20.0)

    # ── Pass / Fail results ───────────────────────────────────────
    vel_result  = fields.Selection([('pass','PASS'),('fail','FAIL'),('na','N/A')],
                                    compute='_compute_results', store=True, string='Vel. Result')
    acph_result = fields.Selection([('pass','PASS'),('fail','FAIL'),('na','N/A')],
                                    compute='_compute_results', store=True, string='ACPH Result')

    # ─────────────────────────────────────────────────────────────
    # Computes
    # ─────────────────────────────────────────────────────────────

    @api.depends('vel_1', 'vel_2', 'vel_3', 'vel_4', 'vel_5')
    def _compute_avgs(self):
        for rec in self:
            vals = [v for v in [rec.vel_1, rec.vel_2, rec.vel_3, rec.vel_4, rec.vel_5] if v]
            if vals:
                avg = sum(vals) / len(vals)
                rec.avg_fpm = round(avg, 2)
                rec.avg_ms  = round(avg / 196.85, 3)
            else:
                rec.avg_fpm = 0.0
                rec.avg_ms  = 0.0

    @api.depends('avg_fpm', 'filter_size_ft2')
    def _compute_cfm(self):
        for rec in self:
            cfm = rec.avg_fpm * rec.filter_size_ft2
            rec.cfm = round(cfm, 0)
            rec.cmh = round(cfm * 1.699, 0)

    @api.depends('room_vol_ft3')
    def _compute_vols(self):
        for rec in self:
            rec.room_vol_m3 = round(rec.room_vol_ft3 / 35.3147, 2) if rec.room_vol_ft3 else 0.0

    @api.depends(
        'cfm', 'room_name', 'room_vol_ft3',
        'sheet_id.vl001_line_ids.cfm',
        'sheet_id.vl001_line_ids.room_name',
    )
    def _compute_acph(self):
        for rec in self:
            if rec.room_name and rec.room_vol_ft3 and rec.sheet_id:
                same_room = rec.sheet_id.vl001_line_ids.filtered(
                    lambda l: l.room_name == rec.room_name
                )
                total = sum(same_room.mapped('cfm'))
                rec.total_room_cfm = round(total, 0)
                rec.acph = round((total * 60.0) / rec.room_vol_ft3, 1)
            else:
                rec.total_room_cfm = rec.cfm
                rec.acph = 0.0

    @api.depends('avg_ms', 'min_vel_ms', 'max_vel_ms', 'acph', 'min_acph')
    def _compute_results(self):
        for rec in self:
            # Velocity result
            ms = rec.avg_ms
            lo = rec.min_vel_ms
            hi = rec.max_vel_ms
            if ms:
                if lo and hi:
                    rec.vel_result = 'pass' if lo <= ms <= hi else 'fail'
                elif hi:
                    rec.vel_result = 'pass' if ms <= hi else 'fail'
                elif lo:
                    rec.vel_result = 'pass' if ms >= lo else 'fail'
                else:
                    rec.vel_result = 'na'
            else:
                rec.vel_result = 'na'

            # ACPH result
            if rec.acph and rec.min_acph:
                rec.acph_result = 'pass' if rec.acph >= rec.min_acph else 'fail'
            else:
                rec.acph_result = 'na'
