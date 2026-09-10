from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .hvac_criteria import (
    DEFAULT_STANDARDS,
    ISO_CLASS_SELECTION,
    ISO_LIMITS,
    PRIMARY_PARAM,
    STANDARD_LIMITS,
    looks_like_standard,
    short_standard,
    sop_limits,
)


class HvacTestSheet(models.Model):
    _name = 'hvac.test.sheet'
    _description = 'HVAC Test Worksheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char('Test Sheet No.', required=True, copy=False, default='New')
    job_id = fields.Many2one('hvac.job', string='Job Order', ondelete='cascade', tracking=True)
    partner_id = fields.Many2one(related='job_id.partner_id', store=True, string='Client')
    sop_revision_id = fields.Many2one(
        'hvac.sop.revision', string='SOP Revision Used', required=True,
        domain="[('state','=','approved')]", tracking=True
    )

    # ── Derived test code from SOP — drives which reading tab is visible ──
    sop_test_code = fields.Char(
        string='SOP Test Code',
        compute='_compute_sop_test_code',
        store=True,
        help='Auto-detected from the selected SOP code (e.g. VL-001, VL-002, …)',
    )

    vl001_subtype = fields.Selection([
        ('both', 'Both (Air Velocity & CFM/ACPH)'),
        ('velocity', 'Air Velocity Only'),
        ('cfm', 'CFM & ACPH Only'),
    ], string='VL-001 Test Sub-type', default='both', tracking=True)

    @api.depends('sop_revision_id', 'sop_revision_id.sop_id.code')
    def _compute_sop_test_code(self):
        for rec in self:
            code = (rec.sop_revision_id.sop_id.code or '').upper()
            if 'VL-001' in code:
                rec.sop_test_code = 'VL-001'
            elif 'VL-002' in code:
                rec.sop_test_code = 'VL-002'
            elif 'VL-003' in code:
                rec.sop_test_code = 'VL-003'
            elif 'VL-004' in code:
                rec.sop_test_code = 'VL-004'
            elif 'VL-005' in code:
                rec.sop_test_code = 'VL-005'
            else:
                rec.sop_test_code = ''

    # Equipment Info
    ahu_tag = fields.Char('AHU / Equipment Tag', help='Equipment tag number as per drawing')
    design_cfm = fields.Float('Design Air Flow (CFM)', digits=(10, 0))

    # Test conditions
    test_date = fields.Date('Test Date', default=fields.Date.today, tracking=True)
    test_start_time = fields.Float('Start Time', digits=(5, 2))
    test_end_time = fields.Float('End Time', digits=(5, 2))
    ambient_temp = fields.Float('Ambient Dry Bulb Temp (°C)', digits=(5, 1))
    ambient_rh = fields.Float('Ambient Relative Humidity (%)', digits=(5, 1))

    technician_ids = fields.Many2many('hr.employee', 'test_sheet_tech_rel', 'sheet_id', 'emp_id',
                                      string='Technicians')
    lead_tech_id = fields.Many2one('hr.employee', string='Lead Technician')
    witnessed_by = fields.Char('Witnessed By (Internal)')
    client_rep = fields.Char('Client Representative')
    client_rep_designation = fields.Char('Client Rep. Designation')

    # ── Specialised measurement lines per SOP type ────────────────────────
    vl001_line_ids = fields.One2many(
        'hvac.vl001.line', 'sheet_id',
        string='Air Velocity & CFM Measurements (VL-001)'
    )
    vl002_line_ids = fields.One2many(
        'hvac.vl002.line', 'sheet_id',
        string='HEPA Filter PAO Readings (VL-002)'
    )
    vl003_line_ids = fields.One2many(
        'hvac.vl003.line', 'sheet_id',
        string='Particle Count Locations (VL-003)'
    )
    vl004_line_ids = fields.One2many(
        'hvac.vl004.line', 'sheet_id',
        string='Recovery Study Intervals (VL-004)'
    )
    vl005_line_ids = fields.One2many(
        'hvac.vl005.line', 'sheet_id',
        string='Temperature & RH Loggers (VL-005)'
    )
    instrument_used_ids = fields.Many2many(
        'hvac.instrument', 'test_sheet_instrument_rel', 'sheet_id', 'instrument_id',
        string='Instruments Used'
    )

    air_velocity_samples_text = fields.Text(string="Air Velocity Samples Text")
    air_velocity_source_file = fields.Binary(string="Samples File (PDF/Image)")
    air_velocity_source_filename = fields.Char(string="File Name")

    pao_source_file = fields.Binary(string="PAO Source File (PDF/Image)")
    pao_source_filename = fields.Char(string="PAO Source Filename")
    pao_samples_text = fields.Text(string="PAO Samples Text")

    nvpc_source_file = fields.Binary(string="NVPC Source File (PDF/Image)")
    nvpc_source_filename = fields.Char(string="NVPC Source Filename")
    nvpc_samples_text = fields.Text(string="NVPC Samples Text")

    recovery_source_file = fields.Binary(string="Recovery Source File (PDF/Image)")
    recovery_source_filename = fields.Char(string="Recovery Source Filename")
    recovery_samples_text = fields.Text(string="Recovery Samples Text")

    acceptance_criteria_html = fields.Html(
        string='Acceptance Criteria',
        compute='_compute_acceptance_criteria_html',
        help='Displays acceptance criteria parameters from the selected SOP revision'
    )

    # ══════════════════════════════════════════════════════════════════════
    #  ACCEPTANCE CRITERIA — SOP / ISO standard vs. client standard
    # ══════════════════════════════════════════════════════════════════════
    criteria_id = fields.Many2one(
        'hvac.acceptance.criteria', string='Client Acceptance Criteria',
        tracking=True,
        domain="['&', ('state', '=', 'approved'),"
               " '|', ('partner_id', '=', False), ('partner_id', '=', partner_id)]",
        help='Client protocol / URS that overrides the SOP limits. '
             'Leave empty to test purely against the SOP / ISO standard.',
    )
    criteria_source = fields.Selection(
        [('sop', 'SOP / ISO Standard'), ('client', 'Client Standard')],
        string='Limits Basis', compute='_compute_criteria_source', store=True,
        help='Basis actually applied to this test, derived from the selected criteria set.',
    )
    criteria_label = fields.Char(
        'Criteria Reference', compute='_compute_criteria_source', store=True,
        help='Full line printed on the certificate and annexures.',
    )
    criteria_text = fields.Char(
        'Acceptance Criteria', compute='_compute_criteria_source', store=True,
        help='The acceptance limits in words, e.g. "0.45 m/s ± 20 %".',
    )
    criteria_standard_ref = fields.Char(
        'Governing Standard', compute='_compute_criteria_source', store=True,
        help='Standard the criteria are drawn from (ISO / EU GMP / ISPE …).',
    )
    criteria_protocol_ref = fields.Char(
        'Client Protocol No.', compute='_compute_criteria_source', store=True,
    )

    # ── Effective limits applied to this worksheet ────────────────────────
    # Resolved as: standard default → SOP revision parameters → client criteria.
    # Editable so a one-off deviation can be recorded without changing the master.
    lim_min_vel_ms = fields.Float('Min Velocity (m/s)', digits=(4, 2),
                                  compute='_compute_limits', store=True, readonly=False)
    lim_max_vel_ms = fields.Float('Max Velocity (m/s)', digits=(4, 2),
                                  compute='_compute_limits', store=True, readonly=False)
    lim_min_acph = fields.Float('Min ACPH', digits=(5, 0),
                                compute='_compute_limits', store=True, readonly=False)
    lim_max_leakage_pct = fields.Float('Max Leakage (%)', digits=(6, 4),
                                       compute='_compute_limits', store=True, readonly=False)
    lim_min_recovery_pct = fields.Float('Min Upstream Recovery (%)', digits=(5, 1),
                                        compute='_compute_limits', store=True, readonly=False)
    lim_max_recovery_pct = fields.Float('Max Upstream Recovery (%)', digits=(5, 1),
                                        compute='_compute_limits', store=True, readonly=False)
    lim_iso_class = fields.Selection(ISO_CLASS_SELECTION, string='Particle Count ISO Class',
                                     compute='_compute_limits', store=True, readonly=False)
    lim_limit_05um = fields.Float('Limit 0.5 µm (particles/m³)', digits=(14, 0),
                                  compute='_compute_limits', store=True, readonly=False)
    lim_limit_50um = fields.Float('Limit 5.0 µm (particles/m³)', digits=(14, 0),
                                  compute='_compute_limits', store=True, readonly=False)
    lim_max_recovery_min = fields.Float('Max Recovery Time (min)', digits=(5, 2),
                                        compute='_compute_limits', store=True, readonly=False)
    lim_recovery_limit_05um = fields.Float('Class Limit 0.5 µm (particles/m³)', digits=(14, 0),
                                           compute='_compute_limits', store=True, readonly=False,
                                           help='Count the room must fall back to for the '
                                                'recovery study.')
    lim_challenge_factor = fields.Float('Min Challenge (× class limit)', digits=(6, 2),
                                        compute='_compute_limits', store=True, readonly=False,
                                        help='SOP step 2.2 — a valid challenge must reach this '
                                             'multiple of the class limit.')
    lim_temp_min = fields.Float('Min Temperature (°C)', digits=(5, 1),
                                compute='_compute_limits', store=True, readonly=False)
    lim_temp_max = fields.Float('Max Temperature (°C)', digits=(5, 1),
                                compute='_compute_limits', store=True, readonly=False)
    lim_rh_min = fields.Float('Min RH (%)', digits=(5, 1),
                              compute='_compute_limits', store=True, readonly=False)
    lim_rh_max = fields.Float('Max RH (%)', digits=(5, 1),
                              compute='_compute_limits', store=True, readonly=False)
    lim_max_temp_range = fields.Float('Max Temp Variation (°C)', digits=(4, 2),
                                      compute='_compute_limits', store=True, readonly=False)
    lim_max_rh_range = fields.Float('Max RH Variation (%)', digits=(4, 2),
                                    compute='_compute_limits', store=True, readonly=False)
    lim_nominal_vel_ms = fields.Float('Nominal Velocity (m/s)', digits=(4, 2),
                                      compute='_compute_limits', store=True, readonly=False,
                                      help='Design velocity the tolerance band is built around. '
                                           'Printed as "0.45 m/s ± 20 %".')
    lim_tolerance_pct = fields.Float('Velocity Tolerance (± %)', digits=(5, 1),
                                     compute='_compute_limits', store=True, readonly=False)

    # ── VL-004 Recovery Study — sheet-level summary fields ────────────────
    recovery_iso_class = fields.Selection(
        ISO_CLASS_SELECTION,
        string='Room ISO Class (Recovery)',
        compute='_compute_limits', store=True, readonly=False,
        help='ISO class of the room — determines acceptance limit for particle count',
    )
    recovery_time_a = fields.Char(
        'Time A — Challenge Stopped',
        compute='_compute_recovery_times', store=True, readonly=False,
        help='End of the last Generation interval. Filled from the rows below; '
             'type over it if the instrument clock differs.',
    )
    recovery_time_b = fields.Char(
        'Time B — ISO Class Regained',
        compute='_compute_recovery_times', store=True, readonly=False,
        help='End of the first Recovery interval at or below the class limit that '
             'stays below for two consecutive readings (SOP step 3.3).',
    )
    recovery_baseline_ok = fields.Boolean(
        'Baseline At Class', compute='_compute_recovery_gates', store=True,
        help='SOP step 1.5 — the Initial count must already be at or below the class limit.',
    )
    recovery_challenge_ok = fields.Boolean(
        'Challenge Valid', compute='_compute_recovery_gates', store=True,
        help='SOP step 2.2 — the challenge must reach the required multiple of the class limit.',
    )
    recovery_sustained_ok = fields.Boolean(
        'Class Sustained', compute='_compute_recovery_gates', store=True,
        help='SOP step 3.3 — the count must stay at or below the class limit for two '
             'consecutive readings.',
    )
    recovery_validity_note = fields.Char(
        'Test Validity', compute='_compute_recovery_gates', store=True,
    )
    recovery_period_min = fields.Float(
        'Recovery Period (min)',
        digits=(5, 2),
        compute='_compute_recovery_period', store=True, readonly=False,
        help='B - A in decimal minutes. Computed from the two times above; '
             'override manually if needed. Acceptance limit comes from the '
             'SOP / client criteria (ISO 14644-3:2019 default: NMT 15 min).',
    )

    # ── Computed per-test-type Pass/Fail summaries ────────────────────────
    velocity_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='Velocity/ACPH Overall Result',
        compute='_compute_specialized_results',
        store=True,
    )
    pao_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='PAO Overall Result',
        compute='_compute_specialized_results',
        store=True,
    )
    particle_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='Particle Count Overall Result',
        compute='_compute_specialized_results',
        store=True,
    )
    recovery_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='Recovery Study Result',
        compute='_compute_specialized_results',
        store=True,
    )
    th_result = fields.Selection(
        [('pass', 'PASS'), ('fail', 'FAIL'), ('na', 'N/A')],
        string='Temp & RH Overall Result',
        compute='_compute_specialized_results',
        store=True,
    )

    # Result
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Completed'),
        ('verified', 'Verified & Issued'),
    ], default='draft', tracking=True, string='Status')
    overall_result = fields.Selection([
        ('pass', 'PASS'),
        ('fail', 'FAIL'),
        ('conditional', 'CONDITIONAL PASS'),
    ], compute='_compute_overall_result', store=True, string='Overall Result')
    remarks = fields.Text('General Remarks / Observations')
    client_signature = fields.Binary('Client Signature')
    tech_signature = fields.Binary('Lead Technician Signature')
    ncr_ids = fields.One2many('hvac.ncr', 'test_sheet_id', string='NCRs Raised')
    ncr_count = fields.Integer(compute='_compute_ncr_count')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends(
        'velocity_result', 'pao_result', 'particle_result', 'recovery_result', 'th_result',
    )
    def _compute_overall_result(self):
        for rec in self:
            # Collect results from specialized test type results only
            statuses = []
            for spec_res in [
                rec.velocity_result, rec.pao_result, rec.particle_result,
                rec.recovery_result, rec.th_result,
            ]:
                if spec_res and spec_res != 'na':
                    statuses.append(spec_res)

            if not statuses:
                rec.overall_result = False
                continue
            if 'fail' in statuses:
                rec.overall_result = 'fail'
            elif 'conditional' in statuses:
                rec.overall_result = 'conditional'
            elif all(s == 'pass' for s in statuses):
                rec.overall_result = 'pass'
            else:
                rec.overall_result = False

    @staticmethod
    def _clock_to_minutes(value):
        """'10:35' or '10:35:20' → minutes since midnight. False if unparsable."""
        parts = (value or '').strip().replace('.', ':').split(':')
        try:
            nums = [int(p) for p in parts if p != '']
        except ValueError:
            return False
        if len(nums) < 2:
            return False
        hours, minutes = nums[0], nums[1]
        seconds = nums[2] if len(nums) > 2 else 0
        if not (0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60):
            return False
        return hours * 60 + minutes + seconds / 60.0

    def _vl004_regained_line(self):
        """First recovery interval at/below the class limit, sustained (SOP 3.3)."""
        self.ensure_one()
        recovery = self.vl004_line_ids.filtered(lambda l: l.ahu_condition == 'recovery')
        ordered = recovery.sorted(lambda l: (l.sequence, l.id))
        for index, line in enumerate(ordered):
            if not line.limit_05um or not line.count_05um:
                continue
            if line.count_05um > line.limit_05um:
                continue
            following = ordered[index + 1:index + 2]
            if not following or following.count_05um <= following.limit_05um:
                return line
        return self.env['hvac.vl004.line']

    @api.depends('vl004_line_ids.ahu_condition', 'vl004_line_ids.time_end',
                 'vl004_line_ids.count_05um', 'vl004_line_ids.limit_05um',
                 'vl004_line_ids.sequence')
    def _compute_recovery_times(self):
        for rec in self:
            if not rec.vl004_line_ids:
                rec.recovery_time_a = rec.recovery_time_a or False
                rec.recovery_time_b = rec.recovery_time_b or False
                continue
            generation = rec.vl004_line_ids.filtered(
                lambda l: l.ahu_condition == 'generation'
            ).sorted(lambda l: (l.sequence, l.id))
            rec.recovery_time_a = generation[-1].time_end if generation else False
            regained = rec._vl004_regained_line()
            rec.recovery_time_b = regained.time_end if regained else False

    @api.depends('vl004_line_ids.ahu_condition', 'vl004_line_ids.count_05um',
                 'vl004_line_ids.limit_05um', 'vl004_line_ids.challenge_limit',
                 'vl004_line_ids.sequence')
    def _compute_recovery_gates(self):
        for rec in self:
            lines = rec.vl004_line_ids
            if not lines:
                rec.recovery_baseline_ok = True
                rec.recovery_challenge_ok = True
                rec.recovery_sustained_ok = True
                rec.recovery_validity_note = False
                continue

            initial = lines.filtered(lambda l: l.ahu_condition == 'initial' and l.count_05um)
            challenge = lines.filtered(lambda l: l.ahu_condition == 'generation' and l.count_05um)
            rec.recovery_baseline_ok = (
                all(l.result == 'pass' for l in initial) if initial else True
            )
            rec.recovery_challenge_ok = (
                any(l.result == 'pass' for l in challenge) if challenge else True
            )
            rec.recovery_sustained_ok = bool(rec._vl004_regained_line())

            problems = []
            if not rec.recovery_baseline_ok:
                problems.append(_('baseline count above the class limit (SOP 1.5)'))
            if not rec.recovery_challenge_ok:
                problems.append(_('challenge below %g\u00d7 the class limit (SOP 2.2)')
                                % (rec.lim_challenge_factor or 100.0))
            if not rec.recovery_sustained_ok:
                problems.append(_('class not regained and held for two readings (SOP 3.3)'))
            note = '; '.join(problems)
            rec.recovery_validity_note = (note[0].upper() + note[1:]) if note else False

    @api.depends('recovery_time_a', 'recovery_time_b')
    def _compute_recovery_period(self):
        for rec in self:
            start = rec._clock_to_minutes(rec.recovery_time_a)
            end = rec._clock_to_minutes(rec.recovery_time_b)
            if start is False or end is False:
                rec.recovery_period_min = rec.recovery_period_min or 0.0
                continue
            if end < start:          # test ran past midnight
                end += 24 * 60
            rec.recovery_period_min = round(end - start, 2)

    @api.depends(
        'vl001_line_ids.vel_result', 'vl001_line_ids.acph_result',
        'vl002_line_ids.pao_result',
        'vl003_line_ids.result_05', 'vl003_line_ids.result_50',
        'vl005_line_ids.temp_result', 'vl005_line_ids.rh_result',
        'recovery_period_min', 'vl001_subtype', 'lim_max_recovery_min',
        'recovery_baseline_ok', 'recovery_challenge_ok', 'recovery_sustained_ok',
        'vl004_line_ids',
    )
    def _compute_specialized_results(self):
        for rec in self:
            # ── Air Velocity & ACPH (VL-001) ──────────────────────────
            vel_lines = rec.vl001_line_ids
            if vel_lines:
                if rec.vl001_subtype == 'velocity':
                    all_vel = vel_lines.mapped('vel_result')
                elif rec.vl001_subtype == 'cfm':
                    all_vel = vel_lines.mapped('acph_result')
                else:
                    all_vel = vel_lines.mapped('vel_result') + vel_lines.mapped('acph_result')
                rec.velocity_result = 'fail' if 'fail' in all_vel else (
                    'pass' if 'pass' in all_vel else 'na'
                )
            else:
                rec.velocity_result = 'na'

            # ── PAO (VL-002) ──────────────────────────────────────────
            pao_lines = rec.vl002_line_ids
            if pao_lines:
                pao_results = pao_lines.mapped('pao_result')
                rec.pao_result = 'fail' if 'fail' in pao_results else (
                    'pass' if 'pass' in pao_results else 'na'
                )
            else:
                rec.pao_result = 'na'

            # ── Particle Count (VL-003) ───────────────────────────────
            pc_lines = rec.vl003_line_ids
            if pc_lines:
                all_pc = pc_lines.mapped('result_05') + pc_lines.mapped('result_50')
                rec.particle_result = 'fail' if 'fail' in all_pc else (
                    'pass' if 'pass' in all_pc else 'na'
                )
            else:
                rec.particle_result = 'na'

            # ── Recovery Study (VL-004) ───────────────────────────────
            # A test whose baseline, challenge or sustained-class checks fail is
            # not a valid recovery study, however short the measured period.
            recovery_limit = rec.lim_max_recovery_min or STANDARD_LIMITS['max_recovery_min']
            gates_ok = (rec.recovery_baseline_ok and rec.recovery_challenge_ok
                        and rec.recovery_sustained_ok)
            if rec.vl004_line_ids and not gates_ok:
                rec.recovery_result = 'fail'
            elif rec.recovery_period_min:
                rec.recovery_result = (
                    'pass' if rec.recovery_period_min <= recovery_limit else 'fail'
                )
            else:
                rec.recovery_result = 'na'

            # ── Temp & RH (VL-005) ────────────────────────────────────
            th_lines = rec.vl005_line_ids
            if th_lines:
                all_th = th_lines.mapped('temp_result') + th_lines.mapped('rh_result')
                rec.th_result = 'fail' if 'fail' in all_th else (
                    'pass' if 'pass' in all_th else 'na'
                )
            else:
                rec.th_result = 'na'

    # ══════════════════════════════════════════════════════════════════════
    #  Acceptance criteria resolution
    # ══════════════════════════════════════════════════════════════════════

    def _resolve_limits(self):
        """Effective limits for this sheet.

        Resolution order — each layer overrides the previous one:
          1. house standard defaults
          2. the numbers held on the selected SOP revision's parameter list
          3. the client criteria set, for the tests it marks as client standard
        """
        self.ensure_one()
        vals = dict(STANDARD_LIMITS)
        vals.update(sop_limits(self.sop_revision_id))
        if self.criteria_id:
            vals.update(self.criteria_id.get_client_limits())
        return vals

    def _standard_ref(self):
        """Standard the acceptance limits are drawn from, for printing.

        The client protocol may name its own; otherwise it comes from the test
        method on the governing SOP parameter, then the SOP's reference list.
        """
        self.ensure_one()
        if self.criteria_id and self.criteria_id.standard_ref:
            return self.criteria_id.standard_ref
        revision = self.sop_revision_id
        if revision:
            if revision.standard_ref:
                return revision.standard_ref
            # Fall back to the test method, but only when it names a standard
            # rather than describing the procedure.
            code = PRIMARY_PARAM.get(self.sop_test_code or '')
            param = revision.parameter_ids.filtered(lambda p: p.parameter_code == code)
            if param and looks_like_standard(param[0].test_method):
                return short_standard(param[0].test_method)
        default = DEFAULT_STANDARDS.get(self.sop_test_code or '')
        if default:
            return default
        if revision and revision.references:
            return short_standard(revision.references)
        return 'ISO 14644'

    def _criteria_text(self):
        """The acceptance limits in words, as printed on the certificate."""
        self.ensure_one()
        code = self.sop_test_code
        if code == 'VL-001':
            if self.lim_nominal_vel_ms and self.lim_tolerance_pct:
                velocity = '%g m/s \u00b1 %g %% (%.2f \u2013 %.2f m/s)' % (
                    self.lim_nominal_vel_ms, self.lim_tolerance_pct,
                    self.lim_min_vel_ms, self.lim_max_vel_ms,
                )
            else:
                velocity = '%.2f \u2013 %.2f m/s' % (self.lim_min_vel_ms, self.lim_max_vel_ms)
            if self.vl001_subtype == 'velocity':
                return velocity
            acph = 'ACPH NLT %g' % self.lim_min_acph
            if self.vl001_subtype == 'cfm':
                return acph
            return '%s | %s' % (velocity, acph)
        if code == 'VL-002':
            return ('Downstream leakage NMT %g %% | Upstream recovery %g \u2013 %g %%'
                    % (self.lim_max_leakage_pct, self.lim_min_recovery_pct,
                       self.lim_max_recovery_pct))
        if code == 'VL-003':
            label = dict(self._fields['lim_iso_class'].selection).get(self.lim_iso_class, '')
            return ('NMT {:,.0f} particles/m\u00b3 at 0.5 \u00b5m and {:,.0f} at 5.0 \u00b5m \u2014 {}'
                    .format(self.lim_limit_05um, self.lim_limit_50um, label))
        if code == 'VL-004':
            label = dict(self._fields['recovery_iso_class'].selection).get(
                self.recovery_iso_class, '')
            return 'Recovery to %s within NMT %g minutes' % (label, self.lim_max_recovery_min)
        if code == 'VL-005':
            return ('Temperature %.1f \u2013 %.1f \u00b0C | RH %.1f \u2013 %.1f %% | '
                    'Variation NMT %.1f \u00b0C and %.1f %% RH'
                    % (self.lim_temp_min, self.lim_temp_max, self.lim_rh_min, self.lim_rh_max,
                       self.lim_max_temp_range, self.lim_max_rh_range))
        return ''

    @api.depends('criteria_id', 'criteria_id.state', 'sop_test_code', 'vl001_subtype',
                 'sop_revision_id', 'criteria_id.vl001_source', 'criteria_id.vl002_source',
                 'criteria_id.vl003_source', 'criteria_id.vl004_source',
                 'criteria_id.vl005_source', 'criteria_id.standard_ref',
                 'criteria_id.document_ref', 'criteria_id.document_rev',
                 'lim_min_vel_ms', 'lim_max_vel_ms', 'lim_min_acph', 'lim_nominal_vel_ms',
                 'lim_tolerance_pct', 'lim_max_leakage_pct', 'lim_min_recovery_pct',
                 'lim_max_recovery_pct', 'lim_iso_class', 'lim_limit_05um', 'lim_limit_50um',
                 'recovery_iso_class', 'lim_max_recovery_min', 'lim_temp_min', 'lim_temp_max',
                 'lim_rh_min', 'lim_rh_max', 'lim_max_temp_range', 'lim_max_rh_range')
    def _compute_criteria_source(self):
        for rec in self:
            source = 'sop'
            if rec.criteria_id and rec.sop_test_code:
                source = rec.criteria_id.get_source(rec.sop_test_code)
            rec.criteria_source = source
            rec.criteria_standard_ref = rec._standard_ref()
            rec.criteria_protocol_ref = (
                rec.criteria_id.protocol_ref() if rec.criteria_id else ''
            )
            rec.criteria_text = rec._criteria_text()

            reference = (
                _('PROTOCOL No. %s') % rec.criteria_protocol_ref
                if source == 'client' and rec.criteria_protocol_ref
                else rec.criteria_standard_ref
            )
            rec.criteria_label = (
                '%s \u2014 %s' % (rec.criteria_text, _('AS PER %s') % reference)
                if rec.criteria_text else _('AS PER %s') % reference
            )

    @api.depends('criteria_id', 'sop_revision_id',
                 'sop_revision_id.parameter_ids.min_value',
                 'sop_revision_id.parameter_ids.max_value')
    def _compute_limits(self):
        for rec in self:
            vals = rec._resolve_limits()
            rec.lim_min_vel_ms = vals['min_vel_ms']
            rec.lim_max_vel_ms = vals['max_vel_ms']
            rec.lim_min_acph = vals['min_acph']
            rec.lim_max_leakage_pct = vals['max_leakage_pct']
            rec.lim_min_recovery_pct = vals['min_recovery_pct']
            rec.lim_max_recovery_pct = vals['max_recovery_pct']
            rec.lim_iso_class = vals['iso_class']
            rec.lim_limit_05um = vals['limit_05um']
            rec.lim_limit_50um = vals['limit_50um']
            rec.lim_max_recovery_min = vals['max_recovery_min']
            rec.recovery_iso_class = vals['recovery_iso_class']
            recovery_limit = vals.get('recovery_limit_05um') or 0.0
            if not recovery_limit and vals['recovery_iso_class'] != 'custom':
                recovery_limit = float(ISO_LIMITS.get(
                    vals['recovery_iso_class'], ISO_LIMITS['iso8'])['05um'])
            rec.lim_recovery_limit_05um = recovery_limit
            rec.lim_challenge_factor = vals.get('challenge_factor') or 100.0
            rec.lim_temp_min = vals['temp_min']
            rec.lim_temp_max = vals['temp_max']
            rec.lim_rh_min = vals['rh_min']
            rec.lim_rh_max = vals['rh_max']
            rec.lim_max_temp_range = vals['max_temp_range']
            rec.lim_max_rh_range = vals['max_rh_range']

            # Velocity stated as nominal ± tolerance where the basis says so;
            # otherwise derive the tolerance from a symmetric min/max band.
            nominal = vals.get('nominal_vel_ms') or 0.0
            tolerance = vals.get('tolerance_pct') or 0.0
            if nominal and not tolerance and vals['max_vel_ms']:
                tolerance = (vals['max_vel_ms'] - nominal) / nominal * 100.0
                symmetric = abs(nominal * (1 - tolerance / 100.0) - vals['min_vel_ms']) < 0.005
                tolerance = round(tolerance, 1) if symmetric and tolerance > 0 else 0.0
            rec.lim_nominal_vel_ms = nominal
            rec.lim_tolerance_pct = tolerance

    def _line_limit_defaults(self, test_code=None):
        """Limit values to stamp on newly created reading rows of a given test."""
        self.ensure_one()
        code = test_code or self.sop_test_code
        if code == 'VL-001':
            return {
                'min_vel_ms': self.lim_min_vel_ms,
                'max_vel_ms': self.lim_max_vel_ms,
                'min_acph': self.lim_min_acph,
            }
        if code == 'VL-002':
            return {
                'max_leakage_pct': self.lim_max_leakage_pct,
                'min_recovery_pct': self.lim_min_recovery_pct,
                'max_recovery_pct': self.lim_max_recovery_pct,
            }
        if code == 'VL-003':
            vals = {'iso_class': self.lim_iso_class or 'iso8'}
            if self.lim_iso_class == 'custom':
                vals.update({
                    'limit_05um': self.lim_limit_05um,
                    'limit_50um': self.lim_limit_50um,
                })
            return vals
        if code == 'VL-005':
            return {
                'temp_min_limit': self.lim_temp_min,
                'temp_max_limit': self.lim_temp_max,
                'rh_min_limit': self.lim_rh_min,
                'rh_max_limit': self.lim_rh_max,
                'max_temp_range_limit': self.lim_max_temp_range,
                'max_rh_range_limit': self.lim_max_rh_range,
            }
        return {}

    def action_apply_criteria(self):
        """Push the current limits onto reading rows that are already entered."""
        self.ensure_one()
        sheet = self
        if sheet.state in ('done', 'verified'):
            raise UserError(_(
                'This worksheet is already completed — reopen it before '
                'changing the acceptance limits.'
            ))
        updated = 0
        for code, lines in (
            ('VL-001', sheet.vl001_line_ids),
            ('VL-002', sheet.vl002_line_ids),
            ('VL-003', sheet.vl003_line_ids),
            ('VL-005', sheet.vl005_line_ids),
        ):
            defaults = sheet._line_limit_defaults(code)
            if lines and defaults:
                lines.write(defaults)
                updated += len(lines)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Acceptance limits applied'),
                'message': _('%s reading row(s) updated to: %s') % (updated, self.criteria_label or ''),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.depends('ncr_ids')
    def _compute_ncr_count(self):
        for rec in self:
            rec.ncr_count = len(rec.ncr_ids)

    def action_open_ncrs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Non-Conformance Reports',
            'res_model': 'hvac.ncr',
            'view_mode': 'list,form',
            'domain': [('test_sheet_id', '=', self.id)],
            'context': {'default_test_sheet_id': self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hvac.test.sheet') or 'New'
        return super().create(vals_list)

    def _get_active_lines(self):
        """Return the relevant specialised line recordset based on sop_test_code."""
        self.ensure_one()
        mapping = {
            'VL-001': self.vl001_line_ids,
            'VL-002': self.vl002_line_ids,
            'VL-003': self.vl003_line_ids,
            'VL-004': self.vl004_line_ids,
            'VL-005': self.vl005_line_ids,
        }
        return mapping.get(self.sop_test_code, self.env['hvac.vl001.line'])

    def action_start(self):
        self.ensure_one()
        if not self.sop_revision_id:
            raise UserError(_('Please select an approved SOP Revision first.'))
        self.write({'state': 'in_progress'})

    def action_complete(self):
        self.ensure_one()
        lines = self._get_active_lines()
        if not lines and self.sop_test_code:
            raise UserError(_(
                'Please enter at least one reading row before completing the test.'
            ))
        self.write({'state': 'done'})
        if self.overall_result == 'fail':
            self._auto_create_ncr()

    def _auto_create_ncr(self):
        desc = f'Test failure detected on {self.sop_test_code or "unknown"} test sheet {self.name}.'
        self.env['hvac.ncr'].create({
            'test_sheet_id': self.id,
            'job_id': self.job_id.id if self.job_id else False,
            'description': desc,
            'severity': 'major',
        })

    def action_verify(self):
        self.write({'state': 'verified'})

    def action_print_certificate(self):
        return self.env.ref('micron_hvac.action_report_test_certificate').report_action(self)

    def action_print_vl001_annexures(self):
        return self.env.ref('micron_hvac.action_report_vl001_annexures').report_action(self)

    def action_print_vl002_annexures(self):
        return self.env.ref('micron_hvac.action_report_vl002_annexures').report_action(self)

    def action_print_vl003_annexures(self):
        return self.env.ref('micron_hvac.action_report_vl003_annexures').report_action(self)

    def action_print_vl004_annexures(self):
        return self.env.ref('micron_hvac.action_report_vl004_annexures').report_action(self)

    def action_print_vl005_annexures(self):
        return self.env.ref('micron_hvac.action_report_vl005_annexures').report_action(self)

    @api.depends('sop_revision_id', 'sop_revision_id.parameter_ids')
    def _compute_acceptance_criteria_html(self):
        for rec in self:
            if not rec.sop_revision_id or not rec.sop_revision_id.parameter_ids:
                rec.acceptance_criteria_html = False
                continue
            
            html = '<div class="alert alert-warning" style="margin-bottom: 10px;">'
            html += '<strong>Acceptance Criteria (from SOP):</strong><br/>'
            params = rec.sop_revision_id.parameter_ids
            items = []
            for p in params:
                limit = []
                if p.min_value:
                    limit.append(f"Min: {p.min_value}")
                if p.max_value:
                    limit.append(f"Max: {p.max_value}")
                if p.nominal_value:
                    limit.append(f"Nominal: {p.nominal_value}")
                
                limit_str = " / ".join(limit) if limit else "No numerical limit"
                tol = f" ({p.tolerance})" if p.tolerance else ""
                items.append(f"• <strong>{p.name}</strong> ({p.parameter_code or ''}): {limit_str} {p.unit or ''}{tol}")
            
            html += "<br/>".join(items)
            html += '</div>'
            rec.acceptance_criteria_html = html

    def _normalize_instrument_ocr_text(self, text):
        """Light cleanup for common OCR quirks from instrument PDFs."""
        import re
        t = text.replace("\r\n", "\n").replace("\r", "\n")
        t = re.sub(r"(?i)\bmis\b", "m/s", t)
        return t

    def _split_mirrored_line(self, line):
        """
        Split a physical OCR line into left/right logical columns when the printer
        outputs two identical blocks side-by-side (MODEL: ... MODEL: ...).
        Returns [left_part, right_part] or [line] if not mirrored.
        """
        import re
        s = line.strip()
        if not s:
            return []

        # Prefer splitting on second occurrence of these section labels.
        split_markers = (
            r"(?i)\bMODEL\s*:",
            r"(?i)\bSERIAL\s*:",
            r"(?i)\bREV\s*:",
            r"(?i)\bPROBE\s*:",
            r"(?i)\bPROBE#\s*:",
            r"(?i)\bTEST\s*ID\s*:",
            r"(?i)\bSample\s*1\s+Date\s*:",
            r"(?i)\bSample\s*1\s+Time\s*:",
            r"(?i)\bActual\s+Velocity",
            r"(?i)\bAvg\b",
            r"(?i)\bMin\b",
            r"(?i)\bMax\b",
            r"(?i)#\s*Samples",
            r"(?i)\bSamples\b",
        )

        for pat in split_markers:
            rx = re.compile(pat)
            matches = list(rx.finditer(s))
            if len(matches) >= 2:
                cut = matches[1].start()
                left = s[:cut].strip()
                right = s[cut:].strip()
                if left and right:
                    return [left, right]

        # Sample rows: two timestamps on one line → split at second time token.
        time_rx = re.compile(r"\b\d{1,2}[:.]\d{2}[:.]\d{2}\b")
        tms = list(time_rx.finditer(s))
        if len(tms) >= 2:
            cut = tms[1].start()
            left = s[:cut].strip()
            right = s[cut:].strip()
            if left and right:
                return [left, right]

        return [s]

    def _build_two_column_streams(self, raw_text):
        """Turn merged OCR text into two independent column texts (left, right)."""
        left_chunks = []
        right_chunks = []
        for line in raw_text.splitlines():
            parts = self._split_mirrored_line(line)
            if len(parts) == 2:
                left_chunks.append(parts[0])
                right_chunks.append(parts[1])
            else:
                left_chunks.append(parts[0])
        left_text = "\n".join(left_chunks)
        right_text = "\n".join(right_chunks)
        return left_text, right_text

    def _fix_test_id_ocr(self, raw_id):
        """
        Fix frequent OCR mistakes in IDs like M0311881 / M0311883.
        Example from user text: MD311881 -> M0311881
        """
        import re
        tid = (raw_id or "").strip().upper()
        # MD311881 -> M0311881 when pattern matches 7 chars after M
        m = re.match(r"^M[D0](\d{6})$", tid)
        if m:
            return "M0" + m.group(1)
        return tid

    def _parse_velocity_from_ocr_line(self, line):
        """
        Extract (time, velocity) pairs from one line. Handles two-column lines.
        OCR may show 'mis' instead of m/s; digits may be O/D confused — fixed later.
        """
        import re
        s = line
        s = re.sub(r"(?i)\bmis\b", "m/s", s)
        # HH:MM:SS followed by velocity (comma or dot decimal), optional m/s
        pattern = re.compile(
            r"(?P<t>\d{1,2}[:.]\d{2}[:.]\d{2})\s+"
            r"(?P<num>[0-9ODlI][0-9ODlI]*[.,][0-9ODlI]+)\s*(?:m\s*/\s*s)?",
            re.IGNORECASE,
        )
        pairs = []
        for m in pattern.finditer(s):
            num_raw = m.group("num")
            # OCR: O->0, D->0 (when used as digit), l/I->1 in fractional part only sparingly
            num_norm = (
                num_raw.replace("O", "0")
                .replace("o", "0")
                .replace("D", "0")
                .replace("d", "0")
                .replace("l", "1")
                .replace("I", "1")
            )
            num_norm = num_norm.replace(",", ".")
            try:
                val = float(num_norm)
            except ValueError:
                continue
            # Air velocity sanity window (m/s); drop obvious OCR garbage
            if val < 0.05 or val > 5.0:
                continue
            pairs.append(val)
        return pairs

    def _parse_air_velocity_samples_text(self, raw_text):
        """
        Core parser used by both text-paste and file-based imports.
        Returns a list of dicts with keys:
        - filter_no
        - readings: list of up to 5 floats
        """
        import re
        raw = (raw_text or "").strip()
        if not raw:
            raise UserError("No samples text provided.")

        raw = self._normalize_instrument_ocr_text(raw)
        left_text, right_text = self._build_two_column_streams(raw)

        test_pattern = re.compile(r"TEST\s*ID[:\s]+(\S+)", re.IGNORECASE)

        def parse_single_column_stream(stream):
            out = []
            matches = list(test_pattern.finditer(stream))
            if not matches:
                return out
            for idx, match in enumerate(matches):
                test_id = self._fix_test_id_ocr(match.group(1))
                start = match.end()
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(stream)
                block = stream[start:end]
                readings = []
                for line in block.splitlines():
                    readings.extend(self._parse_velocity_from_ocr_line(line))
                if not readings:
                    continue
                sample_values = readings[:5]
                while len(sample_values) < 5:
                    sample_values.append(0.0)
                out.append({"filter_no": test_id, "readings": sample_values})
            return out

        results = parse_single_column_stream(left_text) + parse_single_column_stream(right_text)

        if not results:
            raise UserError("No valid sample readings found in the text.")

        return results

    def _load_air_velocity_rows_from_parsed(self, parsed_rows):
        """Create hvac.vl001.line rows from parsed data, converting m/s to FPM."""
        for sheet in self:
            sheet.vl001_line_ids.unlink()

            # Limits follow the sheet's acceptance criteria
            # (SOP / ISO standard, or the client's standard)
            limits = sheet._line_limit_defaults('VL-001')

            seq_counter = 10
            for row in parsed_rows:
                readings = row["readings"]
                # Convert m/s readings to FPM by multiplying by 196.85
                vals = {
                    "sheet_id": sheet.id,
                    "sequence": seq_counter,
                    "room_name": sheet.ahu_tag or "Room",
                    "filter_id": row["filter_no"],
                    "vel_1": readings[0] * 196.85,
                    "vel_2": readings[1] * 196.85,
                    "vel_3": readings[2] * 196.85,
                    "vel_4": readings[3] * 196.85,
                    "vel_5": readings[4] * 196.85,
                }
                vals.update(limits)
                self.env["hvac.vl001.line"].create(vals)
                seq_counter += 10

    def _extract_text_from_binary_file(self, binary_file, filename):
        import base64
        import io
        if not binary_file:
            raise UserError(_("Please upload a PDF or image file before importing."))
        filename = (filename or "").lower()
        data = base64.b64decode(binary_file)
        buffer = io.BytesIO(data)

        text = ""
        if filename.endswith(".pdf"):
            try:
                import pdfplumber
            except ImportError:
                raise UserError(_("PDF import requires 'pdfplumber' to be installed on the Odoo server."))
            with pdfplumber.open(buffer) as pdf:
                pages_text = [page.extract_text() or "" for page in pdf.pages]
                text = "\n".join(pages_text)
        else:
            try:
                from PIL import Image
                import pytesseract
            except ImportError:
                raise UserError(_("Image import requires 'Pillow' and 'pytesseract' to be installed on the Odoo server."))
            image = Image.open(buffer)
            text = pytesseract.image_to_string(image)

        if not text.strip():
            raise UserError(_("No text could be extracted from the uploaded file."))
        return text

    def action_import_air_velocity_from_text(self):
        """User pastes text and clicks the button."""
        for sheet in self:
            parsed = sheet._parse_air_velocity_samples_text(sheet.air_velocity_samples_text)
            sheet._load_air_velocity_rows_from_parsed(parsed)

    def action_import_air_velocity_from_file(self):
        """User uploads PDF/image; this extracts text and then parses it."""
        for sheet in self:
            text = sheet._extract_text_from_binary_file(sheet.air_velocity_source_file, sheet.air_velocity_source_filename)
            sheet.air_velocity_samples_text = text
            parsed = sheet._parse_air_velocity_samples_text(text)
            sheet._load_air_velocity_rows_from_parsed(parsed)

    # ── PAO Test (VL-002) Parsers and Loaders ─────────────────────────────
    def _parse_pao_samples_text(self, raw_text):
        import re
        raw = (raw_text or "").strip()
        if not raw:
            raise UserError(_("No samples text provided."))

        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        pattern_block = re.compile(r"\b(?:ID|IO|JO|10|1O)[:\s]+(\d+)", re.IGNORECASE)
        matches = list(pattern_block.finditer(raw))
        if not matches:
            raise UserError(_("No valid photometer print slip markers (ID / IO) found in the text."))

        results = []
        for idx, match in enumerate(matches):
            val_id = match.group(1)
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
            block = raw[start:end]

            conc_m = re.search(r"(?i)\bActual\s+(?:Conc|Cone)[:\s]+([0-9.,]+)", block)
            conc = float(conc_m.group(1).replace(",", ".")) if conc_m else 0.0

            pen_m = re.search(r"(?i)\bMax\s+(?:Pen|PE.>n)\.?[:\s]+([0-9.,]+)%?", block)
            if pen_m:
                pen = float(pen_m.group(1).replace(",", "."))
                results.append({
                    'id': val_id,
                    'actual_conc': conc,
                    'max_pen': pen,
                    'is_leakage_scan': True
                })
            else:
                results.append({
                    'id': val_id,
                    'actual_conc': conc,
                    'max_pen': 0.0,
                    'is_leakage_scan': False
                })

        return results

    def _load_pao_rows_from_parsed(self, parsed_rows):
        for sheet in self:
            sheet.vl002_line_ids.unlink()

            limits = sheet._line_limit_defaults('VL-002')
            leakage_scans = [r for r in parsed_rows if r['is_leakage_scan']]
            upstream_scans = [r for r in parsed_rows if not r['is_leakage_scan']]

            seq_counter = 10
            for idx, row in enumerate(leakage_scans):
                upstream_after = row['actual_conc']
                if idx < len(leakage_scans) - 1:
                    upstream_after = leakage_scans[idx + 1]['actual_conc']
                elif upstream_scans:
                    upstream_after = upstream_scans[-1]['actual_conc']

                vals = {
                    "sheet_id": sheet.id,
                    "sequence": seq_counter,
                    "room_name": sheet.ahu_tag or "Room",
                    "filter_id": f"HEPA-{row['id'][-3:]}" if len(row['id']) >= 3 else f"HEPA-{row['id']}",
                    "filter_location": f"Aerosol scan point {idx + 1}",
                    "upstream_before": row['actual_conc'],
                    "downstream_pct": row['max_pen'],
                    "upstream_after": upstream_after,
                }
                vals.update(limits)
                self.env["hvac.vl002.line"].create(vals)
                seq_counter += 10

    def action_import_pao_from_text(self):
        for sheet in self:
            parsed = sheet._parse_pao_samples_text(sheet.pao_samples_text)
            sheet._load_pao_rows_from_parsed(parsed)

    def action_import_pao_from_file(self):
        for sheet in self:
            text = sheet._extract_text_from_binary_file(sheet.pao_source_file, sheet.pao_source_filename)
            sheet.pao_samples_text = text
            parsed = sheet._parse_pao_samples_text(text)
            sheet._load_pao_rows_from_parsed(parsed)

    # ── NVPC Test (VL-003) Parsers and Loaders ────────────────────────────
    def _parse_nvpc_samples_text(self, raw_text):
        import re
        raw = (raw_text or "").strip()
        if not raw:
            raise UserError(_("No samples text provided."))

        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        blocks = raw.split("Final Sample Report")
        results = []
        for block in blocks:
            if not block.strip():
                continue
            loc_m = re.search(r"(?i)\bLocation[:\s]+(\S+(?:\s+\S+)?)", block)
            if not loc_m:
                loc_m = re.search(r"(?i)\bLocation[:\s]+(\S+)", block)
            location = loc_m.group(1).strip() if loc_m else "L1"
            location = re.sub(r"[^a-zA-Z0-9\s-]", "", location).strip()

            c05_m = re.search(r"\b0\.5\s*(?:\|)?\s*\d+\s*(?:\|)?\s*(\d+)", block)
            if not c05_m:
                c05_m = re.search(r"\b0\.5\s*(?:\|)?\s*(\d+)", block)
            count_05 = float(c05_m.group(1)) if c05_m else 0.0

            c50_m = re.search(r"\b5\.0\s*(?:\|)?\s*\d+\s*(?:\|)?\s*(\d+)", block)
            if not c50_m:
                c50_m = re.search(r"\b5\.0\s*(?:\|)?\s*(\d+)", block)
            count_50 = float(c50_m.group(1)) if c50_m else 0.0

            if c05_m or c50_m:
                results.append({
                    'location': location,
                    'count_05': count_05,
                    'count_50': count_50,
                })
        
        if not results:
            raise UserError(_("No valid particle count report blocks found in the text."))
        return results

    def _load_nvpc_rows_from_parsed(self, parsed_rows):
        for sheet in self:
            sheet.vl003_line_ids.unlink()
            limits = sheet._line_limit_defaults('VL-003')
            seq_counter = 10
            for row in parsed_rows:
                loc = row['location']
                room = sheet.ahu_tag or "Room"
                loc_id = loc
                if " " in loc:
                    parts = loc.rsplit(" ", 1)
                    if re.match(r"^L\d+$", parts[1], re.IGNORECASE):
                        room = parts[0]
                        loc_id = parts[1].upper()
                
                vals = {
                    "sheet_id": sheet.id,
                    "sequence": seq_counter,
                    "room_name": room,
                    "location_id": loc_id,
                    "location_desc": f"Sampling point {loc_id}",
                    "test_condition": "in_operation" if "operation" in (sheet.remarks or "").lower() else "at_rest",
                    "count_05um": row['count_05'],
                    "count_50um": row['count_50'],
                }
                vals.update(limits)
                self.env["hvac.vl003.line"].create(vals)
                seq_counter += 10

    def action_import_nvpc_from_text(self):
        for sheet in self:
            parsed = sheet._parse_nvpc_samples_text(sheet.nvpc_samples_text)
            sheet._load_nvpc_rows_from_parsed(parsed)

    def action_import_nvpc_from_file(self):
        for sheet in self:
            text = sheet._extract_text_from_binary_file(sheet.nvpc_source_file, sheet.nvpc_source_filename)
            sheet.nvpc_samples_text = text
            parsed = sheet._parse_nvpc_samples_text(text)
            sheet._load_nvpc_rows_from_parsed(parsed)

    # ── Recovery Study (VL-004) Parsers and Loaders ───────────────────────
    def _parse_recovery_samples_text(self, raw_text):
        import re
        raw = (raw_text or "").strip()
        if not raw:
            raise UserError(_("No samples text provided."))

        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        blocks = raw.split("Final Sample Report")
        results = []
        for block in blocks:
            if not block.strip():
                continue

            times = re.findall(r"\b\d{1,2}:\d{2}:\d{2}\b", block)
            if not times:
                times = re.findall(r"\b\d{1,2}:\d{2}\b", block)

            t_start = times[0] if len(times) >= 1 else "00:00"
            t_end = times[1] if len(times) >= 2 else (times[0] if len(times) == 1 else "00:00")

            c05_m = re.search(r"\b0\.5\s*(?:\|)?\s*\d+\s*(?:\|)?\s*(\d+)", block)
            if not c05_m:
                c05_m = re.search(r"\b0\.5\s*(?:\|)?\s*(\d+)", block)
            count_05 = float(c05_m.group(1)) if c05_m else 0.0

            c50_m = re.search(r"\b5\.0\s*(?:\|)?\s*\d+\s*(?:\|)?\s*(\d+)", block)
            if not c50_m:
                c50_m = re.search(r"\b5\.0\s*(?:\|)?\s*(\d+)", block)
            count_50 = float(c50_m.group(1)) if c50_m else 0.0

            if c05_m or c50_m:
                results.append({
                    'time_start': t_start,
                    'time_end': t_end,
                    'count_05': count_05,
                    'count_50': count_50,
                })

        if not results:
            raise UserError(_("No valid sample report intervals found in the text."))
        return results

    def _load_recovery_rows_from_parsed(self, parsed_rows):
        for sheet in self:
            sheet.vl004_line_ids.unlink()
            
            parsed_rows = sorted(parsed_rows, key=lambda x: x['time_start'])

            max_05_idx = 0
            max_05_val = -1.0
            for idx, r in enumerate(parsed_rows):
                if r['count_05'] > max_05_val:
                    max_05_val = r['count_05']
                    max_05_idx = idx

            seq_counter = 10
            for idx, row in enumerate(parsed_rows):
                if idx < max_05_idx:
                    condition = 'initial'
                elif idx == max_05_idx:
                    condition = 'generation'
                else:
                    condition = 'recovery'

                self.env["hvac.vl004.line"].create({
                    "sheet_id": sheet.id,
                    "sequence": seq_counter,
                    "room_name": sheet.ahu_tag or "Room",
                    "ahu_condition": condition,
                    "time_start": row['time_start'],
                    "time_end": row['time_end'],
                    "count_05um": row['count_05'],
                    "count_50um": row['count_50'],
                })
                seq_counter += 10

            # Time A, Time B, the per-row results and the recovery period are
            # all derived from the rows themselves — nothing to set here.

    def action_import_recovery_from_text(self):
        for sheet in self:
            parsed = sheet._parse_recovery_samples_text(sheet.recovery_samples_text)
            sheet._load_recovery_rows_from_parsed(parsed)

    def action_import_recovery_from_file(self):
        for sheet in self:
            text = sheet._extract_text_from_binary_file(sheet.recovery_source_file, sheet.recovery_source_filename)
            sheet.recovery_samples_text = text
            parsed = sheet._parse_recovery_samples_text(text)
            sheet._load_recovery_rows_from_parsed(parsed)

    @api.onchange('job_id')
    def _onchange_job_id(self):
        for sheet in self:
            if sheet.job_id:
                sheet.lead_tech_id = sheet.job_id.lead_technician_id
                sheet.technician_ids = sheet.job_id.technician_ids
                sheet.client_rep = sheet.job_id.contact_person.name if sheet.job_id.contact_person else False
                
                # Auto-fill instrument list from instruments taken on job
                instruments = sheet.job_id.instrument_line_ids.mapped('instrument_id')
                sheet.instrument_used_ids = instruments

                # Pick up the client's approved acceptance criteria, if any
                if not sheet.criteria_id and sheet.job_id.partner_id:
                    sheet.criteria_id = self.env['hvac.acceptance.criteria'].search([
                        ('state', '=', 'approved'),
                        ('partner_id', '=', sheet.job_id.partner_id.id),
                    ], order='effective_date desc, id desc', limit=1)
