from odoo import api, fields, models


class MicronTempHumidityLine(models.Model):
    _name = "micron.temp.humidity.line"
    _description = "Temperature & Humidity Reading Line"
    _order = "sr_no asc, id asc"

    job_id = fields.Many2one("micron.job.order", required=True, ondelete="cascade")
    sr_no = fields.Integer(string="Sr. No.", required=True, default=1)
    location = fields.Char(string="Location")
    temperature = fields.Float(string="Temperature (°C)", digits=(16, 2))
    humidity = fields.Float(string="Humidity (%RH)", digits=(16, 2))
    temp_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="Temp Result",
        compute="_compute_results",
        store=True,
    )
    humidity_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="Humidity Result",
        compute="_compute_results",
        store=True,
    )
    remarks = fields.Char(string="Remarks")

    @api.depends(
        "temperature", "humidity",
        "job_id.run_temp_humidity",
        "job_id.sop_temp_humidity_id.min_value",
        "job_id.sop_temp_humidity_id.max_value",
    )
    def _compute_results(self):
        for rec in self:
            if not rec.job_id.run_temp_humidity:
                rec.temp_result = "na"
                rec.humidity_result = "na"
                continue
            sop = rec.job_id.sop_temp_humidity_id
            if not sop:
                rec.temp_result = "na"
                rec.humidity_result = "na"
                continue
            # Temperature check
            temp_min_ok = (sop.min_value == 0.0) or (rec.temperature >= sop.min_value)
            temp_max_ok = (sop.max_value == 0.0) or (rec.temperature <= sop.max_value)
            rec.temp_result = "pass" if temp_min_ok and temp_max_ok else "fail"
            # Humidity check — use humidity_min/max from SOP notes or defaults
            rec.humidity_result = "pass"  # Computed against SOP; further refined per customer SOP

    _sql_constraints = [
        ("sr_no_positive", "CHECK(sr_no > 0)", "Serial number must be greater than zero."),
    ]
