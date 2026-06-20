from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HvacJob(models.Model):
    _name = 'hvac.job'
    _description = 'HVAC Service Job Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char('Job No.', required=True, copy=False, default='New', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Client', required=True, tracking=True, domain="[('is_company', '=', True)]")
    contact_person = fields.Many2one('res.partner', string='Client Contact Person', domain="[('parent_id', '=', partner_id)]")
    contact_phone = fields.Char('Contact Phone / Email')
    project_name = fields.Char('Project / Building Name', required=True)
    site_address = fields.Text('Site Address')
    job_type = fields.Selection([
        ('commissioning', 'Commissioning'),
        ('performance_test', 'Performance Testing'),
        ('inspection', 'Inspection'),
    ], required=True, string='Job Type', tracking=True)
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'High'),
        ('2', 'Critical'),
    ], default='0', string='Priority')

    # Scheduling
    scheduled_date = fields.Datetime('Scheduled Start', tracking=True)
    estimated_duration = fields.Float('Estimated Duration (hrs)', digits=(5, 1))
    actual_start = fields.Datetime('Actual Start')
    actual_end = fields.Datetime('Actual End')

    # Workforce
    lead_technician_id = fields.Many2one('hr.employee', string='Lead Technician', tracking=True)
    technician_ids = fields.Many2many(
        'hr.employee', 'hvac_job_tech_rel', 'job_id', 'emp_id',
        string='Assigned Technicians'
    )

    # Linked Documents
    test_sheet_ids = fields.One2many('hvac.test.sheet', 'job_id', string='Test Worksheets')
    test_sheet_count = fields.Integer(compute='_compute_counts', string='# Test Sheets')
    instrument_line_ids = fields.One2many('hvac.job.instrument.line', 'job_id', string='Instruments on Job')
    ncr_ids = fields.One2many('hvac.ncr', 'job_id', string='Non-Conformance Reports')
    ncr_count = fields.Integer(compute='_compute_counts', string='# NCRs')

    # Calibration gate
    calibration_valid = fields.Boolean(
        'Instruments Calibration OK', compute='_compute_cal_valid', store=True
    )
    calibration_warning = fields.Char(compute='_compute_cal_valid', string='Cal. Warning')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, string='Status')

    notes = fields.Text('Internal Notes')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    def _compute_counts(self):
        for rec in self:
            rec.test_sheet_count = len(rec.test_sheet_ids)
            rec.ncr_count = len(rec.ncr_ids)

    @api.depends('instrument_line_ids.instrument_id.calibration_status')
    def _compute_cal_valid(self):
        for rec in self:
            invalid = rec.instrument_line_ids.filtered(
                lambda l: l.instrument_id.calibration_status in ('overdue', 'not_calibrated')
            )
            rec.calibration_valid = not bool(invalid)
            if invalid:
                names = ', '.join(invalid.mapped('instrument_id.name'))
                rec.calibration_warning = f'Overdue/uncalibrated: {names}'
            else:
                rec.calibration_warning = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hvac.job') or 'New'
        return super().create(vals_list)

    def action_schedule(self):
        if not self.technician_ids and not self.lead_technician_id:
            raise UserError(_('Assign at least one technician before scheduling the job.'))
        if not self.scheduled_date:
            raise UserError(_('Set a scheduled start date before scheduling.'))
        self.write({'state': 'scheduled'})

    def action_start(self):
        if not self.calibration_valid:
            raise UserError(_(
                'Cannot start job — one or more instruments have expired or missing calibration.\n'
                f'{self.calibration_warning}'
            ))
        self.write({'state': 'in_progress', 'actual_start': fields.Datetime.now()})

    def action_complete(self):
        open_sheets = self.test_sheet_ids.filtered(lambda s: s.state not in ('done', 'verified'))
        if open_sheets:
            raise UserError(_('Complete all test worksheets before marking the job as done.'))
        self.write({'state': 'done', 'actual_end': fields.Datetime.now()})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_open_ncrs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Non-Conformance Reports',
            'res_model': 'hvac.ncr',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }

    def action_view_test_sheets(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Test Worksheets',
            'res_model': 'hvac.test.sheet',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }


class HvacJobInstrumentLine(models.Model):
    _name = 'hvac.job.instrument.line'
    _description = 'Instrument Taken on Job'
    _order = 'instrument_id'

    job_id = fields.Many2one('hvac.job', required=True, ondelete='cascade')
    instrument_id = fields.Many2one('hvac.instrument', required=True, string='Instrument')
    instrument_type = fields.Selection(related='instrument_id.instrument_type', store=True)
    calibration_status = fields.Selection(
        related='instrument_id.calibration_status', store=True, string='Cal. Status'
    )
    next_calibration_date = fields.Date(
        related='instrument_id.next_calibration_date', store=True, string='Cal. Due'
    )
    latest_cert_no = fields.Char(related='instrument_id.latest_cert_no', store=True, string='Cert No.')
    purpose = fields.Char('Used For / Measurement Purpose')
