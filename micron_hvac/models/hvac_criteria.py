from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

# ── ISO 14644-1:2015 particle limits (particles/m³) ──────────────────────
ISO_LIMITS = {
    'iso5': {'05um': 3_520,      '50um': 29},
    'iso6': {'05um': 35_200,     '50um': 293},
    'iso7': {'05um': 352_000,    '50um': 2_930},
    'iso8': {'05um': 3_520_000,  '50um': 29_300},
    'iso9': {'05um': 35_200_000, '50um': 293_000},
}

ISO_CLASS_SELECTION = [
    ('iso5', 'ISO Class 5 (Grade A/B)'),
    ('iso6', 'ISO Class 6'),
    ('iso7', 'ISO Class 7 (Grade C)'),
    ('iso8', 'ISO Class 8 (Grade D)'),
    ('iso9', 'ISO Class 9'),
    ('custom', 'Custom — Client Specified Limits'),
]

# Where the limits come from, per test. Shown on the certificate.
SOURCE_SELECTION = [
    ('sop', 'As per SOP / ISO Standard'),
    ('client', 'As per Client Standard'),
]

# Fallback used when neither the SOP nor a client criteria set supplies a value.
# Mirrors the field defaults on the VL line models.
STANDARD_LIMITS = {
    'min_vel_ms': 0.36,
    'max_vel_ms': 0.54,
    'min_acph': 20.0,
    'max_leakage_pct': 0.01,
    'min_recovery_pct': 85.0,
    'max_recovery_pct': 115.0,
    'iso_class': 'iso8',
    'limit_05um': ISO_LIMITS['iso8']['05um'],
    'limit_50um': ISO_LIMITS['iso8']['50um'],
    'recovery_iso_class': 'iso8',
    'max_recovery_min': 15.0,
    'recovery_limit_05um': 0.0,
    'challenge_factor': 100.0,
    'temp_min': 18.0,
    'temp_max': 27.0,
    'rh_min': 30.0,
    'rh_max': 65.0,
    'max_temp_range': 2.0,
    'max_rh_range': 5.0,
    'nominal_vel_ms': 0.0,
    'tolerance_pct': 0.0,
}

# SOP parameter code → (limit key, which bound of the parameter to read)
# Lets the SOP/ISO branch read the real numbers held on the SOP revision
# instead of relying on hardcoded constants.
SOP_PARAM_MAP = {
    'FACE-VEL':       [('min_vel_ms', 'min'), ('max_vel_ms', 'max')],
    'ACPH':           [('min_acph', 'min')],
    'LEAKAGE':        [('max_leakage_pct', 'max')],
    'RECOVERY':       [('min_recovery_pct', 'min'), ('max_recovery_pct', 'max')],
    'PC-0.5-AT-REST': [('limit_05um', 'max')],
    'PC-5.0-AT-REST': [('limit_50um', 'max')],
    'RECOV-TIME':     [('max_recovery_min', 'max')],
    'ROOM-TEMP':      [('temp_min', 'min'), ('temp_max', 'max')],
    'ROOM-RH':        [('rh_min', 'min'), ('rh_max', 'max')],
    'TEMP-RANGE':     [('max_temp_range', 'max')],
    'RH-UNIF':        [('max_rh_range', 'max')],
}


# Primary SOP parameter per test — its test method names the governing standard
PRIMARY_PARAM = {
    'VL-001': 'FACE-VEL',
    'VL-002': 'LEAKAGE',
    'VL-003': 'PC-0.5-AT-REST',
    'VL-004': 'RECOV-TIME',
    'VL-005': 'ROOM-TEMP',
}

# Last-resort standard when neither the SOP nor the client names one
DEFAULT_STANDARDS = {
    'VL-001': 'ISO 14644-3:2019 Annex B1 / EU GMP Annex 1',
    'VL-002': 'ISO 14644-3:2019 Annex B6 / EU GMP Annex 1',
    'VL-003': 'ISO 14644-1:2015',
    'VL-004': 'ISO 14644-3:2019 Annex B12 / ISPE Baseline Guide Vol. 5',
    'VL-005': 'EU GMP Annex 1:2022 / WHO TRS 986',
}


# A method description is not a standard — only text starting like one is used
STANDARD_PREFIXES = (
    'ISO', 'EN ', 'EN1', 'IEST', 'ISPE', 'EU GMP', 'WHO', 'ASHRAE', 'AMCA',
    'ICH', 'USP', 'PDA', 'Schedule M', '21 CFR', 'BS ', 'ANSI', 'NEBB',
)


def looks_like_standard(text):
    return bool(text) and text.strip().upper().startswith(
        tuple(p.upper() for p in STANDARD_PREFIXES)
    )


def short_standard(text):
    """First standard named in a free-text method / reference list.

    'ISO 14644-3:2019 Annex B1 \u2014 5-point velocity traverse at 150mm'
    becomes 'ISO 14644-3:2019 Annex B1'.
    """
    if not text:
        return ''
    line = text.strip().splitlines()[0]
    for sep in ('\u2014', '\u2013', ' - '):
        if sep in line:
            line = line.split(sep)[0]
            break
    return line.strip(' .;:,')


def sop_limits(sop_revision):
    """Read the acceptance limits held on an SOP revision's parameter list."""
    vals = {}
    if not sop_revision:
        return vals
    for param in sop_revision.parameter_ids:
        for key, bound in SOP_PARAM_MAP.get(param.parameter_code or '', []):
            value = param.min_value if bound == 'min' else param.max_value
            if value:
                vals[key] = value
        if param.parameter_code == 'FACE-VEL' and param.nominal_value:
            vals['nominal_vel_ms'] = param.nominal_value
    # SOP 2.2 — a valid challenge is PEAK-CNT / INIT-CNT times the class limit
    peak = sop_revision.parameter_ids.filtered(lambda p: p.parameter_code == 'PEAK-CNT')
    base = sop_revision.parameter_ids.filtered(lambda p: p.parameter_code == 'INIT-CNT')
    if peak and base and peak[0].min_value and base[0].max_value:
        vals['challenge_factor'] = round(peak[0].min_value / base[0].max_value, 2)
    return vals


class HvacAcceptanceCriteria(models.Model):
    """Acceptance criteria set — one record per client protocol / URS.

    Each test (VL-001 … VL-005) is independently marked as following either the
    SOP / ISO standard or the client's own standard. Where the client standard
    is chosen, the numbers typed here drive the Pass/Fail evaluation of every
    reading row on the test worksheet.
    """
    _name = 'hvac.acceptance.criteria'
    _description = 'Acceptance Criteria Set (SOP / Client Standard)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'partner_id, name'

    name = fields.Char('Criteria Set Name', required=True, tracking=True,
                       help='e.g. "Aptar Pharma — Cleanroom Requalification Protocol"')
    code = fields.Char('Reference No.', required=True, copy=False, default='New', tracking=True)
    criteria_type = fields.Selection([
        ('client', 'Client Protocol / URS'),
        ('project', 'Project / Area Specific'),
        ('standard', 'In-House Standard'),
    ], string='Criteria Type', default='client', required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Client', tracking=True,
        domain="[('is_company', '=', True)]",
        help='Leave empty to make this criteria set selectable for every client.',
    )
    project_name = fields.Char('Project / Building')
    room_grade = fields.Char('Room Grade / Area',
                             help='e.g. Grade C — Sterile Block, Oral Solid Dosage Area')

    document_ref = fields.Char('Client Document No.', tracking=True,
                               help='Protocol / URS number issued by the client')
    document_rev = fields.Char('Document Revision')
    effective_date = fields.Date('Effective From', default=fields.Date.today)
    document = fields.Binary('Client Protocol (PDF)')
    document_filename = fields.Char('Filename')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('obsolete', 'Obsolete'),
    ], default='draft', tracking=True, string='Status')

    standard_ref = fields.Char(
        'Governing Standard',
        help='Standard the client protocol is written against, printed on the '
             'certificate and annexures (e.g. "EU GMP Annex 1 / ISPE Baseline Guide Vol. 5"). '
             'Leave empty to print the standard named on the SOP.',
    )
    notes = fields.Text('Notes / Deviations from Standard')
    sheet_ids = fields.One2many('hvac.test.sheet', 'criteria_id', string='Test Sheets Using This')
    sheet_count = fields.Integer('# Test Sheets', compute='_compute_sheet_count')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    # ── VL-001 Air Velocity & ACPH ───────────────────────────────────────
    vl001_source = fields.Selection(SOURCE_SELECTION, string='VL-001 Basis',
                                    default='sop', required=True)
    vl001_limit_mode = fields.Selection([
        ('nominal', 'Nominal \u00b1 Tolerance'),
        ('range', 'Min / Max Range'),
    ], string='Velocity Stated As', default='nominal', required=True)
    vl001_nominal_vel_ms = fields.Float('Nominal Velocity (m/s)', digits=(4, 2), default=0.45)
    vl001_tolerance_pct = fields.Float('Tolerance (\u00b1 %)', digits=(5, 1), default=20.0)
    vl001_min_vel_ms = fields.Float('Min Velocity (m/s)', digits=(4, 2), default=0.36,
                                    compute='_compute_vl001_band', store=True, readonly=False)
    vl001_max_vel_ms = fields.Float('Max Velocity (m/s)', digits=(4, 2), default=0.54,
                                    compute='_compute_vl001_band', store=True, readonly=False)
    vl001_min_acph = fields.Float('Min ACPH', digits=(5, 0), default=20.0)

    # ── VL-002 HEPA Filter Integrity (PAO) ───────────────────────────────
    vl002_source = fields.Selection(SOURCE_SELECTION, string='VL-002 Basis',
                                    default='sop', required=True)
    vl002_max_leakage_pct = fields.Float('Max Leakage (%)', digits=(6, 4), default=0.01,
                                         help='ISO 14644-3:2019 Annex B6 default is NMT 0.01%')
    vl002_min_recovery_pct = fields.Float('Min Upstream Recovery (%)', digits=(5, 1), default=85.0)
    vl002_max_recovery_pct = fields.Float('Max Upstream Recovery (%)', digits=(5, 1), default=115.0)

    # ── VL-003 Non-Viable Particle Count ─────────────────────────────────
    vl003_source = fields.Selection(SOURCE_SELECTION, string='VL-003 Basis',
                                    default='sop', required=True)
    vl003_iso_class = fields.Selection(ISO_CLASS_SELECTION, string='ISO Class', default='iso8')
    vl003_limit_05um = fields.Float('Limit 0.5 µm (particles/m³)', digits=(14, 0),
                                    compute='_compute_vl003_limits', store=True, readonly=False)
    vl003_limit_50um = fields.Float('Limit 5.0 µm (particles/m³)', digits=(14, 0),
                                    compute='_compute_vl003_limits', store=True, readonly=False)

    # ── VL-004 Recovery Study ────────────────────────────────────────────
    vl004_source = fields.Selection(SOURCE_SELECTION, string='VL-004 Basis',
                                    default='sop', required=True)
    vl004_iso_class = fields.Selection(ISO_CLASS_SELECTION, string='Recovery ISO Class', default='iso8')
    vl004_max_recovery_min = fields.Float('Max Recovery Time (min)', digits=(5, 2), default=15.0,
                                          help='ISO 14644-3:2019 Annex B12 default is NMT 15 minutes')
    vl004_limit_05um = fields.Float(
        'Class Limit 0.5 µm (particles/m³)', digits=(14, 0),
        compute='_compute_vl004_limit', store=True, readonly=False,
        help='Count the room must fall back to. Editable when the ISO class is Custom.',
    )
    vl004_challenge_factor = fields.Float(
        'Min Challenge (× class limit)', digits=(6, 2), default=100.0,
        help='A valid challenge must reach this multiple of the class limit '
             '(SOP step 2.2 / ISO 14644-3:2019 — at least 100×).',
    )

    # ── VL-005 Temperature & Relative Humidity ───────────────────────────
    vl005_source = fields.Selection(SOURCE_SELECTION, string='VL-005 Basis',
                                    default='sop', required=True)
    vl005_temp_min = fields.Float('Min Temperature (°C)', digits=(5, 1), default=18.0)
    vl005_temp_max = fields.Float('Max Temperature (°C)', digits=(5, 1), default=27.0)
    vl005_rh_min = fields.Float('Min RH (%)', digits=(5, 1), default=30.0)
    vl005_rh_max = fields.Float('Max RH (%)', digits=(5, 1), default=65.0)
    vl005_max_temp_range = fields.Float('Max Temp Variation (°C)', digits=(4, 2), default=2.0,
                                        help='Max allowed Max−Min at a single logger position')
    vl005_max_rh_range = fields.Float('Max RH Variation (%)', digits=(4, 2), default=5.0)

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)',
         'Criteria reference number must be unique per company.'),
    ]

    # ────────────────────────────────────────────────────────────────────
    # Computes / constraints
    # ────────────────────────────────────────────────────────────────────

    @api.depends('vl004_iso_class')
    def _compute_vl004_limit(self):
        for rec in self:
            if rec.vl004_iso_class == 'custom':
                rec.vl004_limit_05um = rec.vl004_limit_05um or 0.0
            else:
                rec.vl004_limit_05um = float(
                    ISO_LIMITS.get(rec.vl004_iso_class, ISO_LIMITS['iso8'])['05um']
                )

    @api.depends('vl001_limit_mode', 'vl001_nominal_vel_ms', 'vl001_tolerance_pct')
    def _compute_vl001_band(self):
        for rec in self:
            if rec.vl001_limit_mode == 'nominal' and rec.vl001_nominal_vel_ms:
                spread = rec.vl001_nominal_vel_ms * (rec.vl001_tolerance_pct or 0.0) / 100.0
                rec.vl001_min_vel_ms = round(rec.vl001_nominal_vel_ms - spread, 3)
                rec.vl001_max_vel_ms = round(rec.vl001_nominal_vel_ms + spread, 3)
            else:
                rec.vl001_min_vel_ms = rec.vl001_min_vel_ms or 0.36
                rec.vl001_max_vel_ms = rec.vl001_max_vel_ms or 0.54

    @api.depends('vl003_iso_class')
    def _compute_vl003_limits(self):
        for rec in self:
            if rec.vl003_iso_class == 'custom':
                # Keep whatever the client protocol specifies
                rec.vl003_limit_05um = rec.vl003_limit_05um or 0.0
                rec.vl003_limit_50um = rec.vl003_limit_50um or 0.0
            else:
                limits = ISO_LIMITS.get(rec.vl003_iso_class, {})
                rec.vl003_limit_05um = limits.get('05um', 0.0)
                rec.vl003_limit_50um = limits.get('50um', 0.0)

    @api.depends('sheet_ids')
    def _compute_sheet_count(self):
        for rec in self:
            rec.sheet_count = len(rec.sheet_ids)

    @api.constrains(
        'vl001_source', 'vl001_min_vel_ms', 'vl001_max_vel_ms',
        'vl002_source', 'vl002_min_recovery_pct', 'vl002_max_recovery_pct',
        'vl005_source', 'vl005_temp_min', 'vl005_temp_max', 'vl005_rh_min', 'vl005_rh_max',
    )
    def _check_ranges(self):
        for rec in self:
            pairs = []
            if rec.vl001_source == 'client':
                pairs.append((rec.vl001_min_vel_ms, rec.vl001_max_vel_ms, _('Air velocity')))
            if rec.vl002_source == 'client':
                pairs.append((rec.vl002_min_recovery_pct, rec.vl002_max_recovery_pct,
                              _('Upstream recovery')))
            if rec.vl005_source == 'client':
                pairs.append((rec.vl005_temp_min, rec.vl005_temp_max, _('Temperature')))
                pairs.append((rec.vl005_rh_min, rec.vl005_rh_max, _('Relative humidity')))
            for lo, hi, label in pairs:
                if lo and hi and lo > hi:
                    raise ValidationError(
                        _('%s: the minimum limit cannot be greater than the maximum limit.') % label
                    )

    @api.constrains('vl003_source', 'vl003_iso_class', 'vl003_limit_05um', 'vl003_limit_50um')
    def _check_particle_limits(self):
        for rec in self:
            if rec.vl003_source == 'client' and rec.vl003_iso_class == 'custom' \
                    and not (rec.vl003_limit_05um or rec.vl003_limit_50um):
                raise ValidationError(_(
                    'VL-003 is set to custom client limits — enter at least one '
                    'particle count limit (0.5 µm or 5.0 µm).'
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('hvac.acceptance.criteria') or 'New'
        return super().create(vals_list)

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('code', 'New')
        default.setdefault('state', 'draft')
        default.setdefault('name', _('%s (copy)') % self.name)
        return super().copy(default)

    # ────────────────────────────────────────────────────────────────────
    # Workflow
    # ────────────────────────────────────────────────────────────────────

    def action_approve(self):
        for rec in self:
            if rec.criteria_type == 'client' and not rec.partner_id:
                raise UserError(_('Select the client before approving a client protocol.'))
            rec.state = 'approved'

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_obsolete(self):
        self.write({'state': 'obsolete'})

    def action_view_sheets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Test Worksheets'),
            'res_model': 'hvac.test.sheet',
            'view_mode': 'list,form',
            'domain': [('criteria_id', '=', self.id)],
        }

    # ────────────────────────────────────────────────────────────────────
    # API used by the test worksheet
    # ────────────────────────────────────────────────────────────────────

    def get_source(self, test_code):
        """Return 'sop' or 'client' for the given test code (VL-001 … VL-005)."""
        self.ensure_one()
        return {
            'VL-001': self.vl001_source,
            'VL-002': self.vl002_source,
            'VL-003': self.vl003_source,
            'VL-004': self.vl004_source,
            'VL-005': self.vl005_source,
        }.get(test_code, 'sop')

    def get_client_limits(self):
        """Client-specified limits, for the tests marked 'As per Client Standard'.

        Tests left on the SOP / ISO basis return nothing here, so the worksheet
        keeps the SOP numbers for them.
        """
        self.ensure_one()
        vals = {}
        if self.vl001_source == 'client':
            vals.update({
                'min_vel_ms': self.vl001_min_vel_ms,
                'max_vel_ms': self.vl001_max_vel_ms,
                'min_acph': self.vl001_min_acph,
                'nominal_vel_ms': (self.vl001_nominal_vel_ms
                                   if self.vl001_limit_mode == 'nominal' else 0.0),
                'tolerance_pct': (self.vl001_tolerance_pct
                                  if self.vl001_limit_mode == 'nominal' else 0.0),
            })
        if self.vl002_source == 'client':
            vals.update({
                'max_leakage_pct': self.vl002_max_leakage_pct,
                'min_recovery_pct': self.vl002_min_recovery_pct,
                'max_recovery_pct': self.vl002_max_recovery_pct,
            })
        if self.vl003_source == 'client':
            vals.update({
                'iso_class': self.vl003_iso_class,
                'limit_05um': self.vl003_limit_05um,
                'limit_50um': self.vl003_limit_50um,
            })
        if self.vl004_source == 'client':
            vals.update({
                'recovery_iso_class': self.vl004_iso_class,
                'max_recovery_min': self.vl004_max_recovery_min,
                'recovery_limit_05um': self.vl004_limit_05um,
                'challenge_factor': self.vl004_challenge_factor,
            })
        if self.vl005_source == 'client':
            vals.update({
                'temp_min': self.vl005_temp_min,
                'temp_max': self.vl005_temp_max,
                'rh_min': self.vl005_rh_min,
                'rh_max': self.vl005_rh_max,
                'max_temp_range': self.vl005_max_temp_range,
                'max_rh_range': self.vl005_max_rh_range,
            })
        return vals

    def protocol_ref(self):
        """'PSV/PRO/001 Rev 02' — empty when no client document is recorded."""
        self.ensure_one()
        if not self.document_ref:
            return ''
        if self.document_rev:
            return '%s Rev %s' % (self.document_ref, self.document_rev)
        return self.document_ref

    def describe(self):
        """Short human-readable reference for printing on certificates."""
        self.ensure_one()
        parts = [self.name]
        if self.document_ref:
            ref = self.document_ref
            if self.document_rev:
                ref = '%s Rev %s' % (ref, self.document_rev)
            parts.append(ref)
        return ' — '.join(parts)
