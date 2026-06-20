from odoo import models, fields, api, _


class HvacNcr(models.Model):
    _name = 'hvac.ncr'
    _description = 'Non-Conformance Report (NCR)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char('NCR No.', required=True, copy=False, default='New', tracking=True)
    test_sheet_id = fields.Many2one('hvac.test.sheet', string='Source Test Sheet')
    job_id = fields.Many2one('hvac.job', string='Job Order')
    partner_id = fields.Many2one(related='job_id.partner_id', store=True, string='Client')
    description = fields.Text('Non-Conformance Description', required=True)
    severity = fields.Selection([
        ('minor', 'Minor'),
        ('major', 'Major'),
        ('critical', 'Critical'),
    ], default='minor', required=True, tracking=True)
    raised_by = fields.Many2one('res.users', string='Raised By', default=lambda s: s.env.uid)
    raised_date = fields.Date('Raised On', default=fields.Date.today)
    capa_id = fields.Many2one('hvac.capa', string='CAPA Reference')
    state = fields.Selection([
        ('open', 'Open'),
        ('under_review', 'Under Review'),
        ('closed', 'Closed'),
    ], default='open', tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hvac.ncr') or 'New'
        return super().create(vals_list)

    def action_create_capa(self):
        capa = self.env['hvac.capa'].create({
            'ncr_id': self.id,
            'job_id': self.job_id.id,
        })
        self.write({'capa_id': capa.id, 'state': 'under_review'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hvac.capa',
            'res_id': capa.id,
            'view_mode': 'form',
        }


class HvacCapa(models.Model):
    _name = 'hvac.capa'
    _description = 'Corrective and Preventive Action (CAPA)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char('CAPA No.', required=True, copy=False, default='New', tracking=True)
    ncr_id = fields.Many2one('hvac.ncr', string='Source NCR')
    job_id = fields.Many2one('hvac.job', string='Job Order')
    root_cause = fields.Text('Root Cause Analysis')
    corrective_action = fields.Text('Corrective Action Taken')
    preventive_action = fields.Text('Preventive Action Proposed')
    responsible_id = fields.Many2one('res.users', string='Responsible Person')
    target_date = fields.Date('Target Completion Date')
    actual_date = fields.Date('Actual Completion Date')
    effectiveness_review = fields.Text('Effectiveness Review')
    state = fields.Selection([
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('verified', 'Verified & Closed'),
    ], default='open', tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hvac.capa') or 'New'
        return super().create(vals_list)

    def action_close(self):
        self.write({'state': 'verified', 'actual_date': fields.Date.today()})
        if self.ncr_id:
            self.ncr_id.write({'state': 'closed'})
