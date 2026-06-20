from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HvacSop(models.Model):
    _name = 'hvac.sop'
    _description = 'HVAC Standard Operating Procedure'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code'

    name = fields.Char('SOP Title', required=True, tracking=True)
    code = fields.Char('SOP Code', required=True, copy=False, tracking=True)
    category = fields.Selection([
        ('cleanroom_validation', 'Cleanroom Validation (Pharma)'),
    ], string='Category', required=True, tracking=True)
    scope = fields.Text('Scope', help='Define the boundaries and applicability of this SOP.')
    purpose = fields.Text('Purpose', help='State the objective of this procedure.')
    active_revision_id = fields.Many2one(
        'hvac.sop.revision', string='Active Revision',
        compute='_compute_active_revision', store=True,
    )
    revision_ids = fields.One2many('hvac.sop.revision', 'sop_id', string='Revisions')
    revision_count = fields.Integer('# Revisions', compute='_compute_revision_count')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('revision_ids.state')
    def _compute_active_revision(self):
        for rec in self:
            approved = rec.revision_ids.filtered(lambda r: r.state == 'approved').sorted('revision_no')
            rec.active_revision_id = approved[-1] if approved else False

    def _compute_revision_count(self):
        for rec in self:
            rec.revision_count = len(rec.revision_ids)

    def action_view_revisions(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'SOP Revisions',
            'res_model': 'hvac.sop.revision',
            'view_mode': 'list,form',
            'domain': [('sop_id', '=', self.id)],
            'context': {'default_sop_id': self.id},
        }

    def action_new_revision(self):
        sorted_revs = self.revision_ids.sorted('revision_no')
        last_rev = sorted_revs[-1] if sorted_revs else None
        next_no = (last_rev.revision_no + 1) if last_rev else 1
        revision = self.env['hvac.sop.revision'].create({
            'sop_id': self.id,
            'revision_no': next_no,
            'version_label': f'Rev {next_no}.0',
            'change_summary': 'New revision — describe changes from previous version.',
        })
        if last_rev:
            for step in last_rev.step_ids:
                step.copy({'revision_id': revision.id})
            for param in last_rev.parameter_ids:
                param.copy({'revision_id': revision.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hvac.sop.revision',
            'res_id': revision.id,
            'view_mode': 'form',
        }

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'SOP Code must be unique per company.'),
    ]


class HvacSopRevision(models.Model):
    _name = 'hvac.sop.revision'
    _description = 'SOP Revision'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sop_id, revision_no desc'
    _rec_name = 'display_name'

    sop_id = fields.Many2one('hvac.sop', string='SOP', required=True, ondelete='cascade')
    sop_code = fields.Char(related='sop_id.code', store=True, string='SOP Code')
    sop_name = fields.Char(related='sop_id.name', store=True, string='SOP Title')
    sop_category = fields.Selection(related='sop_id.category', store=True)
    revision_no = fields.Integer('Revision No.', required=True)
    version_label = fields.Char('Version Label', required=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Under Review'),
        ('approved', 'Approved'),
        ('obsolete', 'Obsolete'),
    ], default='draft', tracking=True, string='Status')
    effective_date = fields.Date('Effective Date')
    next_review_date = fields.Date('Next Review Date')
    change_summary = fields.Text('Summary of Changes')
    reviewed_by = fields.Many2one('res.users', string='Reviewed By', tracking=True)
    reviewed_date = fields.Date('Reviewed On')
    approved_by = fields.Many2one('res.users', string='Approved By', tracking=True)
    approved_date = fields.Datetime('Approved On', tracking=True)
    document = fields.Binary('Attached Document')
    document_name = fields.Char('Document Filename')
    ppe_requirements = fields.Text('PPE Requirements')
    safety_precautions = fields.Text('Safety Precautions')
    references = fields.Text('References / Standards', help='e.g. ASHRAE 62.1, SMACNA, ISO 7730')
    step_ids = fields.One2many('hvac.sop.step', 'revision_id', string='Procedure Steps')
    parameter_ids = fields.One2many('hvac.sop.parameter', 'revision_id', string='Test Parameters')
    required_instrument_ids = fields.Many2many(
        'hvac.instrument', string='Required Instruments',
        help='Instruments that must be calibration-valid before this SOP can be executed.'
    )
    company_id = fields.Many2one(related='sop_id.company_id', store=True)

    @api.depends('sop_id.code', 'version_label')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.sop_id.code} — {rec.version_label}" if rec.sop_id else rec.version_label

    def action_submit_review(self):
        if not self.step_ids:
            raise UserError(_('Add at least one procedure step before submitting for review.'))
        if not self.parameter_ids:
            raise UserError(_('Add at least one test parameter before submitting for review.'))
        self.write({'state': 'review', 'reviewed_date': fields.Date.today()})

    def action_approve(self):
        previous = self.sop_id.revision_ids.filtered(
            lambda r: r.state == 'approved' and r.id != self.id
        )
        previous.write({'state': 'obsolete'})
        self.write({
            'state': 'approved',
            'approved_by': self.env.uid,
            'approved_date': fields.Datetime.now(),
            'effective_date': fields.Date.today(),
        })

    def action_obsolete(self):
        self.write({'state': 'obsolete'})

    def action_reset_draft(self):
        if self.state == 'approved':
            raise UserError(_('An approved revision cannot be reset to draft. Create a new revision instead.'))
        self.write({'state': 'draft'})

    def action_print_sop(self):
        return self.env.ref('micron_hvac.action_report_sop_template').report_action(self)


class HvacSopStep(models.Model):
    _name = 'hvac.sop.step'
    _description = 'SOP Procedure Step'
    _order = 'sequence, id'

    revision_id = fields.Many2one('hvac.sop.revision', required=True, ondelete='cascade')
    sequence = fields.Integer('Step #', default=10)
    name = fields.Char('Step Title', required=True)
    description = fields.Text('Detailed Instructions', required=True)
    warning = fields.Text('Warning / Caution / Note')
    responsible = fields.Selection([
        ('technician', 'Field Technician'),
        ('engineer', 'Commissioning Engineer'),
        ('supervisor', 'Supervisor / QC'),
        ('client', 'Client Representative'),
    ], default='technician', string='Responsible Party')
    estimated_time = fields.Float('Est. Time (min)', digits=(5, 0))


class HvacSopParameter(models.Model):
    _name = 'hvac.sop.parameter'
    _description = 'SOP Test Parameter & Acceptance Criteria'
    _order = 'sequence, id'

    revision_id = fields.Many2one('hvac.sop.revision', required=True, ondelete='cascade')
    sequence = fields.Integer('Seq', default=10)
    parameter_code = fields.Char('Param Code', help='Short code, e.g. SAF, RAT, TSP')
    name = fields.Char('Parameter Name', required=True)
    unit = fields.Char('Unit', required=True)
    test_method = fields.Char('Test Method / Standard', help='e.g. ASHRAE 111, AMCA 210, ISO 5802')
    nominal_value = fields.Float('Nominal / Design', digits=(10, 2))
    min_value = fields.Float('Min. Acceptable', digits=(10, 2))
    max_value = fields.Float('Max. Acceptable', digits=(10, 2))
    tolerance = fields.Char('Tolerance', help='e.g. ±10%, ±0.5°C')
    instrument_type = fields.Selection([
        ('anemometer', 'Anemometer'),
        ('manometer', 'Manometer / Magnehelic'),
        ('thermometer', 'Digital Thermometer / RTD'),
        ('hygrometer', 'Hygrometer / Psychrometer'),
        ('pressure_gauge', 'Pressure Gauge / Transducer'),
        ('flow_hood', 'Air Capture Hood / Balometer'),
        ('particle_counter', 'Particle Counter (Lasair / OPC)'),
        ('aerosol_photometer', 'Aerosol Photometer (PAO / DOP)'),
        ('temp_rh_logger', 'Temperature & RH Data Logger'),
        ('none', 'Visual / Manual Check'),
    ], string='Measuring Instrument')
    remarks = fields.Char('Remarks / Note')
    is_mandatory = fields.Boolean('Mandatory', default=True,
                                  help='Mandatory parameters must pass for overall job result to be PASS.')
