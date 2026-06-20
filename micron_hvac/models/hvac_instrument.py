from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HvacInstrument(models.Model):
    _name = 'hvac.instrument'
    _description = 'HVAC Measuring Instrument Registry'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char('Instrument Name', required=True)
    asset_code = fields.Char('Asset / Tag Code', required=True, copy=False, tracking=True)
    instrument_type = fields.Selection([
        ('anemometer', 'Anemometer'),
        ('manometer', 'Manometer / Magnehelic Gauge'),
        ('thermometer', 'Digital Thermometer / RTD Probe'),
        ('hygrometer', 'Hygrometer / Psychrometer'),
        ('pressure_gauge', 'Pressure Gauge / Transducer'),
        ('flow_hood', 'Air Flow Hood / Balometer'),
        ('particle_counter', 'Particle Counter (Lasair / OPC)'),
        ('aerosol_photometer', 'Aerosol Photometer (PAO / DOP)'),
        ('temp_rh_logger', 'Temperature & RH Data Logger'),
    ], required=True, string='Instrument Type', tracking=True)
    make = fields.Char('Make / Brand')
    model_no = fields.Char('Model No.')
    serial_no = fields.Char('Serial No.', required=True, copy=False)
    range_description = fields.Char('Measurement Range', help='e.g. 0–30 m/s, -20 to 200°C')
    resolution = fields.Char('Resolution', help='e.g. 0.01 m/s, 0.1°C')
    accuracy_class = fields.Char('Accuracy Class / Spec', help='e.g. ±2%, ±0.3°C')
    purchase_date = fields.Date('Purchase Date')
    location = fields.Char('Storage / Home Location')
    calibration_interval = fields.Integer(
        'Calibration Interval (days)', default=365,
        help='How frequently this instrument must be recalibrated.'
    )
    last_calibration_date = fields.Date('Last Calibration Date', tracking=True)
    next_calibration_date = fields.Date(
        'Next Calibration Due', compute='_compute_next_cal', store=True
    )
    calibration_status = fields.Selection([
        ('valid', 'Valid'),
        ('due_soon', 'Due Soon (≤30 days)'),
        ('overdue', 'Overdue'),
        ('not_calibrated', 'Not Yet Calibrated'),
    ], compute='_compute_cal_status', store=True, string='Calibration Status', tracking=True)
    latest_cert_no = fields.Char('Latest Certificate No.', compute='_compute_latest_cert', store=True)
    calibration_ids = fields.One2many('hvac.calibration', 'instrument_id', string='Calibration History')
    calibration_count = fields.Integer(compute='_compute_cal_count', string='# Calibrations')
    active = fields.Boolean(default=True)
    notes = fields.Text('Notes')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('last_calibration_date', 'calibration_interval')
    def _compute_next_cal(self):
        for rec in self:
            if rec.last_calibration_date and rec.calibration_interval:
                rec.next_calibration_date = rec.last_calibration_date + timedelta(days=rec.calibration_interval)
            else:
                rec.next_calibration_date = False

    @api.depends('next_calibration_date', 'last_calibration_date')
    def _compute_cal_status(self):
        today = fields.Date.today()
        for rec in self:
            if not rec.last_calibration_date:
                rec.calibration_status = 'not_calibrated'
            elif not rec.next_calibration_date or rec.next_calibration_date < today:
                rec.calibration_status = 'overdue'
            elif (rec.next_calibration_date - today).days <= 30:
                rec.calibration_status = 'due_soon'
            else:
                rec.calibration_status = 'valid'

    def _compute_cal_count(self):
        for rec in self:
            rec.calibration_count = len(rec.calibration_ids)

    @api.depends('calibration_ids.name', 'calibration_ids.calibration_date')
    def _compute_latest_cert(self):
        for rec in self:
            latest = rec.calibration_ids.sorted('calibration_date')
            rec.latest_cert_no = latest[-1].name if latest else ''

    def action_view_calibrations(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Calibration Records',
            'res_model': 'hvac.calibration',
            'view_mode': 'list,form',
            'domain': [('instrument_id', '=', self.id)],
            'context': {'default_instrument_id': self.id},
        }

    _sql_constraints = [
        ('serial_uniq', 'unique(serial_no)', 'Serial number must be unique across all instruments.'),
        ('asset_uniq', 'unique(asset_code, company_id)', 'Asset code must be unique per company.'),
    ]


class HvacCalibration(models.Model):
    _name = 'hvac.calibration'
    _description = 'Instrument Calibration Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'calibration_date desc'

    name = fields.Char('Certificate No.', required=True, copy=False, default='New', tracking=True)
    instrument_id = fields.Many2one('hvac.instrument', string='Instrument', required=True, ondelete='cascade')
    instrument_type = fields.Selection(related='instrument_id.instrument_type', store=True)
    calibration_date = fields.Date('Date of Calibration', required=True)
    valid_until = fields.Date('Valid Until', required=True)
    calibrated_by = fields.Char('Calibrated By (Lab / Agency)', required=True)
    lab_accreditation_no = fields.Char('Lab Accreditation No.', help='e.g. NABL Cert No.')
    reference_standard = fields.Char('Reference Standard Used', help='e.g. Fluke 718 — NIST traceable')
    traceability = fields.Char('Traceability To', default='NABL / NPL India')
    calibration_method = fields.Char('Calibration Method / Procedure')
    result = fields.Selection([
        ('pass', 'PASS — Within Specified Tolerance'),
        ('conditional', 'CONDITIONAL — Use with Noted Restrictions'),
        ('fail', 'FAIL — Out of Tolerance, Remove from Service'),
    ], required=True, default='pass', tracking=True, string='Calibration Result')
    error_found = fields.Char('Observed Error / Deviation')
    correction_factor = fields.Char('Correction / Adjustment Applied')
    certificate = fields.Binary('Calibration Certificate (PDF)')
    certificate_filename = fields.Char('Certificate Filename')
    state = fields.Selection([
        ('active', 'Active'),
        ('expired', 'Expired'),
    ], compute='_compute_state', store=True, string='Validity Status')
    remarks = fields.Text('Remarks')
    company_id = fields.Many2one(related='instrument_id.company_id', store=True)

    @api.depends('valid_until')
    def _compute_state(self):
        today = fields.Date.today()
        for rec in self:
            rec.state = 'active' if rec.valid_until and rec.valid_until >= today else 'expired'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hvac.calibration') or 'New'
        records = super().create(vals_list)
        for rec in records:
            if rec.result != 'fail':
                rec.instrument_id.write({'last_calibration_date': rec.calibration_date})
        return records
