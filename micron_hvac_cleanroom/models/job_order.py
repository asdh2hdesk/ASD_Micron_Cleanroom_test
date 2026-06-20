from odoo import api, fields, models
from odoo.exceptions import UserError
import re
import base64
import io


class MicronJobOrder(models.Model):
    _name = "micron.job.order"
    _description = "Clean Room Validation Job"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    def init(self):
        # Safety cleanup for legacy data after field type migration (char -> many2one).
        self.env.cr.execute(
            """
            UPDATE micron_job_order j
               SET equipment_used_name = NULL
             WHERE equipment_used_name IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM micron_equipment e
                     WHERE e.id = j.equipment_used_name
               )
            """
        )

    name = fields.Char(
        string="Job Number",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env["ir.sequence"].next_by_code("micron.job.order") or "New",
    )
    client_id = fields.Many2one(
        "res.partner",
        required=True,
        tracking=True,
        domain=[("is_company", "=", True)],
    )
    area_id = fields.Many2one(
        "micron.clean.room.area",
        required=True,
        tracking=True,
        domain="[('client_id', '=', client_id)]",
    )
    engineer_id = fields.Many2one("res.users", required=True, tracking=True)
    planned_date = fields.Datetime(required=True, tracking=True)
    validation_date = fields.Date(string="Validation Date")
    priority = fields.Selection(
        [("0", "Normal"), ("1", "High"), ("2", "Urgent")],
        string="Priority",
        default="0",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft",       "Scheduling"),
            ("confirmed",   "Confirmed"),
            ("in_progress", "Test In Progress"),
            ("review",      "Pending Review"),
            ("done",        "Completed"),
            ("cancel",      "Cancelled"),
        ],
        default="draft",
        tracking=True,
        string="Status",
    )

    ahu_no = fields.Char(string="AHU No.", tracking=True)
    room_no = fields.Char(string="Room Name & No.", tracking=True)
    test_condition = fields.Selection(
        [("at_rest", "At Rest"), ("in_operation", "In Operation"), ("both", "Both")],
        string="Test Condition",
        default="at_rest",
        tracking=True,
    )

    # ── Workflow meta-fields ──────────────────────────────────────────────────
    scheduled_by = fields.Many2one(
        "res.users",
        string="Scheduled By",
        default=lambda self: self.env.user,
        readonly=True,
    )
    actual_start = fields.Datetime(string="Test Start Time", readonly=True)
    actual_end = fields.Datetime(string="Test End Time", readonly=True)
    scheduling_notes = fields.Text(
        string="Instructions to Engineer",
        help="Scheduler's notes / instructions for the assigned engineer",
    )
    engineer_notes = fields.Text(
        string="Engineer's Observations",
        help="Engineer's field observations during the test",
    )
    cancel_reason = fields.Text(string="Cancellation Reason")
    is_assigned_engineer = fields.Boolean(
        string="Is Assigned Engineer",
        compute="_compute_is_assigned_engineer",
    )

    @api.depends("engineer_id")
    def _compute_is_assigned_engineer(self):
        for rec in self:
            rec.is_assigned_engineer = (rec.engineer_id.id == self.env.user.id)

    run_air_velocity = fields.Boolean(string="Air Velocity")
    run_particle_count = fields.Boolean(string="Particle Count")
    run_filter_integrity = fields.Boolean(string="Filter Integrity")
    run_temp_humidity = fields.Boolean(string="Temperature & Humidity")
    run_diff_pressure = fields.Boolean(string="Differential Pressure")
    run_ach = fields.Boolean(string="Air Change Rate")
    run_recovery = fields.Boolean(string="Recovery Test")
    run_lighting_noise = fields.Boolean(string="Lighting / Noise")

    certificate_client_name = fields.Char(string="Certificate Client Name")
    certificate_client_address = fields.Text(string="Client Address")
    test_carried_out_by = fields.Many2one("res.users", string="Test Carried Out By")
    test_witnessed_by = fields.Many2one(
        "res.partner",
        string="Test Witnessed By",
        domain="[('parent_id', '=', client_id)]",
    )
    test_type = fields.Char(string="Test Carried Out", default="AIR VELOCITY MEASUREMENT")
    area_name_text = fields.Char(string="Area Name")

    equipment_used_name = fields.Many2one("micron.equipment", string="Equipment Used")
    equipment_model_no = fields.Char(string="Model No.")
    equipment_serial_no = fields.Char(string="Sr. No.")
    calibration_date = fields.Date(string="Calibration Date")
    calibration_due_date = fields.Date(string="Calibration Due Date")

    air_velocity_line_ids = fields.One2many("micron.air.velocity.line", "job_id")
    air_velocity_avg = fields.Float(compute="_compute_air_velocity_stats", store=True)
    air_velocity_min = fields.Float(compute="_compute_air_velocity_stats", store=True)
    air_velocity_max = fields.Float(compute="_compute_air_velocity_stats", store=True)
    air_velocity_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "Not Applicable")],
        compute="_compute_air_velocity_result",
        store=True,
        default="na",
    )
    sop_air_velocity_id = fields.Many2one(
        "micron.sop.template",
        domain=[("test_type", "=", "air_velocity")],
    )
    acceptance_criteria_text = fields.Char(
        string="Acceptance Criteria",
        default="0.45 m/s +/- 20 % AS PER PROTOCOL No. PSV/PRO/001",
    )
    result_statement = fields.Char(
        string="Result Statement",
        default="Meets / Does Not Meet Validation Acceptance Criteria As Per ISO 14644-3:2019 (E)",
    )
    reviewed_by = fields.Many2one(
        "res.partner",
        string="Test Reviewed By",
        domain="[('parent_id', '=', client_id)]",
    )
    engineer_sign_date = fields.Date(string="Engineer Sign Date")
    witness_sign_date = fields.Date(string="Witness Sign Date")
    reviewer_sign_date = fields.Date(string="Reviewer Sign Date")

    air_velocity_samples_text = fields.Text(string="Air Velocity Samples Text")
    # Uploaded original file (PDF or image) from instrument
    air_velocity_source_file = fields.Binary(string="Samples File (PDF/Image)")
    air_velocity_source_filename = fields.Char(string="File Name")

    # ── CFM / ACPH (Phase 2) ──────────────────────────────────────────────────
    cfm_equipment_id = fields.Many2one(
        "micron.equipment",
        string="CFM Instrument",
        domain=[("instrument_type", "=", "air_capture_hood")],
    )
    sop_cfm_id = fields.Many2one(
        "micron.sop.template",
        string="SOP (CFM/ACPH)",
        domain=[("test_type", "=", "ach")],
    )
    cfm_line_ids = fields.One2many("micron.cfm.line", "job_id", string="CFM Readings")
    cfm_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="CFM Overall Result",
        compute="_compute_cfm_result",
        store=True,
    )

    @api.depends("cfm_line_ids.acph_result", "run_ach")
    def _compute_cfm_result(self):
        for rec in self:
            if not rec.run_ach:
                rec.cfm_result = "na"
                continue
            results = rec.cfm_line_ids.mapped("acph_result")
            if not results:
                rec.cfm_result = "na"
            elif "fail" in results:
                rec.cfm_result = "fail"
            else:
                rec.cfm_result = "pass"

    # ── HEPA Filter Integrity / PAO (Phase 3) ────────────────────────────────
    pao_photometer_id = fields.Many2one(
        "micron.equipment",
        string="Aerosol Photometer",
        domain=[("instrument_type", "=", "aerosol_photometer")],
    )
    pao_pressure_gauge_id = fields.Many2one(
        "micron.equipment",
        string="Pressure Gauge (PAO)",
        domain=[("instrument_type", "=", "manometer")],
    )
    sop_pao_id = fields.Many2one(
        "micron.sop.template",
        string="SOP (Filter Integrity)",
        domain=[("test_type", "=", "filter_integrity")],
    )
    pao_line_ids = fields.One2many("micron.pao.line", "job_id", string="PAO Readings")
    pao_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="PAO Overall Result",
        compute="_compute_pao_result",
        store=True,
    )

    @api.depends("pao_line_ids.pao_result", "run_filter_integrity")
    def _compute_pao_result(self):
        for rec in self:
            if not rec.run_filter_integrity:
                rec.pao_result = "na"
                continue
            results = rec.pao_line_ids.mapped("pao_result")
            if not results:
                rec.pao_result = "na"
            elif "fail" in results:
                rec.pao_result = "fail"
            else:
                rec.pao_result = "pass"

    # ── Particle Count / NVPC (Phase 4) ──────────────────────────────────────
    particle_equipment_id = fields.Many2one(
        "micron.equipment",
        string="Particle Counter",
        domain=[("instrument_type", "=", "particle_counter")],
    )
    particle_flow_rate = fields.Char(string="Flow Rate", default="28.3 LPM")
    particle_sampling_volume = fields.Char(string="Sampling Volume", default="0.0283 m³/min")
    particle_sampling_time = fields.Char(string="Sampling Time", default="1 Min")
    iso_class = fields.Selection(
        [
            ("iso5", "ISO Class 5"),
            ("iso6", "ISO Class 6"),
            ("iso7", "ISO Class 7"),
            ("iso8", "ISO Class 8"),
            ("iso9", "ISO Class 9"),
        ],
        string="ISO Class",
        default="iso8",
    )
    sop_particle_id = fields.Many2one(
        "micron.sop.template",
        string="SOP (Particle Count)",
        domain=[("test_type", "=", "particle_count")],
    )
    particle_line_ids = fields.One2many("micron.particle.line", "job_id", string="Particle Count Readings")
    particle_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="Particle Count Overall Result",
        compute="_compute_particle_result",
        store=True,
    )

    @api.depends("particle_line_ids.result_05", "particle_line_ids.result_50", "run_particle_count")
    def _compute_particle_result(self):
        for rec in self:
            if not rec.run_particle_count:
                rec.particle_result = "na"
                continue
            lines = rec.particle_line_ids
            if not lines:
                rec.particle_result = "na"
                continue
            all_results = lines.mapped("result_05") + lines.mapped("result_50")
            rec.particle_result = "fail" if "fail" in all_results else "pass"

    # ── Recovery Test (Phase 5) ───────────────────────────────────────────────
    recovery_equipment_id = fields.Many2one(
        "micron.equipment",
        string="Recovery Instrument",
        domain=[("instrument_type", "=", "particle_counter")],
    )
    recovery_flow_rate = fields.Char(string="Flow Rate (Recovery)", default="28.3 LPM")
    recovery_sampling_volume = fields.Char(string="Sampling Volume (Recovery)", default="0.0283 m³/min")
    recovery_sampling_time = fields.Char(string="Sampling Time (Recovery)", default="1 Min")
    sop_recovery_id = fields.Many2one(
        "micron.sop.template",
        string="SOP (Recovery)",
        domain=[("test_type", "=", "recovery")],
    )
    recovery_line_ids = fields.One2many("micron.recovery.line", "job_id", string="Recovery Test Readings")
    recovery_period = fields.Char(string="Recovery Period", help="e.g. '03 Min' — time from Generation to Class regained")
    recovery_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="Recovery Overall Result",
        default="na",
    )

    # ── Temperature & Humidity (Phase 6) ─────────────────────────────────────
    temp_humidity_equipment_id = fields.Many2one(
        "micron.equipment",
        string="Thermo-Hygrometer",
        domain=[("instrument_type", "=", "thermohygrometer")],
    )
    sop_temp_humidity_id = fields.Many2one(
        "micron.sop.template",
        string="SOP (Temp & Humidity)",
        domain=[("test_type", "=", "temp_humidity")],
    )
    temp_humidity_line_ids = fields.One2many("micron.temp.humidity.line", "job_id", string="Temp & Humidity Readings")
    temp_humidity_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="T&H Overall Result",
        compute="_compute_temp_humidity_result",
        store=True,
    )

    @api.depends("temp_humidity_line_ids.temp_result", "temp_humidity_line_ids.humidity_result", "run_temp_humidity")
    def _compute_temp_humidity_result(self):
        for rec in self:
            if not rec.run_temp_humidity:
                rec.temp_humidity_result = "na"
                continue
            lines = rec.temp_humidity_line_ids
            if not lines:
                rec.temp_humidity_result = "na"
                continue
            all_results = lines.mapped("temp_result") + lines.mapped("humidity_result")
            rec.temp_humidity_result = "fail" if "fail" in all_results else "pass"

    # ── Differential Pressure (Phase 7) ──────────────────────────────────────
    diff_pressure_equipment_id = fields.Many2one(
        "micron.equipment",
        string="Diff. Pressure Gauge",
        domain=[("instrument_type", "=", "manometer")],
    )
    sop_diff_pressure_id = fields.Many2one(
        "micron.sop.template",
        string="SOP (Diff. Pressure)",
        domain=[("test_type", "=", "diff_pressure")],
    )
    diff_pressure_line_ids = fields.One2many("micron.diff.pressure.line", "job_id", string="Diff. Pressure Readings")
    diff_pressure_result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")],
        string="Diff. Pressure Overall Result",
        compute="_compute_diff_pressure_result",
        store=True,
    )

    @api.depends("diff_pressure_line_ids.result", "run_diff_pressure")
    def _compute_diff_pressure_result(self):
        for rec in self:
            if not rec.run_diff_pressure:
                rec.diff_pressure_result = "na"
                continue
            results = rec.diff_pressure_line_ids.mapped("result")
            if not results:
                rec.diff_pressure_result = "na"
            elif "fail" in results:
                rec.diff_pressure_result = "fail"
            else:
                rec.diff_pressure_result = "pass"

    @api.depends(
        "air_velocity_line_ids.reading_1",
        "air_velocity_line_ids.reading_2",
        "air_velocity_line_ids.reading_3",
        "air_velocity_line_ids.reading_4",
        "air_velocity_line_ids.reading_5",
    )
    def _compute_air_velocity_stats(self):
        for rec in self:
            readings = []
            for line in rec.air_velocity_line_ids:
                readings.extend([
                    v for v in [
                        line.reading_1, line.reading_2, line.reading_3,
                        line.reading_4, line.reading_5
                    ] if v and v != 0.0
                ])
            if readings:
                rec.air_velocity_avg = sum(readings) / len(readings)
                rec.air_velocity_min = min(readings)
                rec.air_velocity_max = max(readings)
            else:
                rec.air_velocity_avg = 0.0
                rec.air_velocity_min = 0.0
                rec.air_velocity_max = 0.0

    @api.depends("run_air_velocity", "air_velocity_avg", "sop_air_velocity_id.min_value", "sop_air_velocity_id.max_value")
    def _compute_air_velocity_result(self):
        for rec in self:
            if not rec.run_air_velocity:
                rec.air_velocity_result = "na"
                continue

            sop = rec.sop_air_velocity_id
            if not sop:
                rec.air_velocity_result = "fail"
                continue

            min_ok = sop.min_value == 0.0 or rec.air_velocity_avg >= sop.min_value
            max_ok = sop.max_value == 0.0 or rec.air_velocity_avg <= sop.max_value
            rec.air_velocity_result = "pass" if min_ok and max_ok else "fail"

    def action_confirm(self):
        """Planner confirms the schedule → notifies assigned engineer."""
        for rec in self:
            if not rec.engineer_id:
                raise UserError("Please assign an engineer before confirming.")
            if not any([rec.run_air_velocity, rec.run_ach, rec.run_filter_integrity,
                        rec.run_particle_count, rec.run_recovery,
                        rec.run_temp_humidity, rec.run_diff_pressure]):
                raise UserError("Please select at least one test to perform.")
            rec.write({"state": "confirmed"})
            rec.message_post(
                body=(
                    f"<b>Job Confirmed &amp; Assigned to {rec.engineer_id.name}.</b><br/>"
                    f"Planned Test Date: {rec.planned_date}<br/>"
                    f"Tests: {'Air Velocity, ' if rec.run_air_velocity else ''}"
                    f"{'CFM/ACPH, ' if rec.run_ach else ''}"
                    f"{'Filter Integrity, ' if rec.run_filter_integrity else ''}"
                    f"{'Particle Count, ' if rec.run_particle_count else ''}"
                    f"{'Recovery, ' if rec.run_recovery else ''}"
                    f"{'Temp & Humidity, ' if rec.run_temp_humidity else ''}"
                    f"{'Diff. Pressure' if rec.run_diff_pressure else ''}"
                ),
                partner_ids=[rec.engineer_id.partner_id.id] if rec.engineer_id.partner_id else [],
            )

    def action_start_test(self):
        """Engineer starts the actual test."""
        self.ensure_one()
        if self.state != "confirmed":
            raise UserError("Job must be in Confirmed state to start testing.")
        self.write({"state": "in_progress", "actual_start": fields.Datetime.now()})
        self.message_post(body=f"<b>Test started by {self.env.user.name}</b> at {fields.Datetime.now().strftime('%d/%m/%Y %H:%M')}")

    def action_submit_review(self):
        """Engineer submits test data for manager review."""
        self.ensure_one()
        self.write({"state": "review", "actual_end": fields.Datetime.now()})
        self.message_post(body=f"<b>Test completed and submitted for review by {self.env.user.name}.</b>")

    def action_approve_done(self):
        """Manager approves and marks as completed."""
        for rec in self:
            rec.write({"state": "done"})
            rec.message_post(body=f"<b>Job approved and marked Completed by {self.env.user.name}.</b>")

    def action_send_back(self):
        """Manager sends back to engineer for corrections."""
        self.ensure_one()
        self.write({"state": "in_progress"})
        self.message_post(body=f"<b>Sent back for corrections by {self.env.user.name}.</b> Please review and re-submit.")

    def action_start(self):
        self.action_confirm()

    def action_complete(self):
        self.action_approve_done()

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.write({"state": "draft"})


    def action_print_test_certificate(self):
        """Open the PDF Test Certificate report for this job."""
        self.ensure_one()
        return self.env.ref("micron_hvac_cleanroom.action_report_micron_test_certificate").report_action(self)

    def _fmt_date(self, value):
        if not value:
            return ""
        return value.strftime("%d/%m/%Y")

    def _fmt_velocity(self, value):
        """Normalize OCR outliers for display in PDF/Excel outputs."""
        if value is None:
            return ""
        try:
            val = float(value)
        except (TypeError, ValueError):
            return ""
        # OCR can produce 42.00 instead of 0.42
        if 5 < val <= 100:
            val = val / 100.0
        elif 100 < val <= 1000:
            val = val / 1000.0
        return f"{val:.2f}"

    def action_download_test_certificate_direct(self):
        """
        Generate and download certificate PDF directly (without wkhtmltopdf).
        Requires reportlab in the Odoo Python environment.
        """
        self.ensure_one()
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.pdfgen import canvas
            from reportlab.lib.utils import ImageReader
        except ImportError:
            raise UserError(
                "Direct PDF download requires the 'reportlab' package. "
                "Install it in Odoo venv: pip install reportlab"
            )

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        left = 24
        right = width - 24
        content_w = right - left
        y = height - 24

        # Company logo (header) + watermark
        logo_b64 = self.env.company.logo
        logo_reader = None
        if logo_b64:
            try:
                logo_reader = ImageReader(io.BytesIO(base64.b64decode(logo_b64)))
            except Exception:
                logo_reader = None

        if logo_reader:
            # Header logo
            pdf.drawImage(
                logo_reader,
                left,
                y - 18,
                width=120,
                height=42,
                preserveAspectRatio=True,
                mask="auto",
            )
            # Watermark logo (faint in center)
            pdf.saveState()
            try:
                pdf.setFillAlpha(0.08)
            except Exception:
                pass
            pdf.drawImage(
                logo_reader,
                left + 55,
                180,
                width=content_w - 110,
                height=content_w - 110,
                preserveAspectRatio=True,
                mask="auto",
            )
            pdf.restoreState()

        # Title (underlined like sample)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawCentredString(width / 2, y, "TEST CERTIFICATE")
        pdf.line(width / 2 - 54, y - 2, width / 2 + 54, y - 2)
        y -= 28

        # Header information
        label_w = 155
        colon_x = left + label_w
        value_x = colon_x + 10
        line_h = 18

        client_value = self.certificate_client_name or self.client_id.name or ""
        if self.certificate_client_address:
            addr = [ln.strip() for ln in self.certificate_client_address.splitlines() if ln.strip()]
            if addr:
                client_value = client_value + "\n" + "\n".join(addr[:2])

        header_rows = [
            ("CLIENT", client_value),
            ("TEST CARRIED OUT BY", self.test_carried_out_by.name if self.test_carried_out_by else ""),
            ("TEST WITNESSED BY", self.test_witnessed_by.name if self.test_witnessed_by else ""),
            ("TEST CARRIED OUT", self.test_type or ""),
            ("VALIDATION DATE", self._fmt_date(self.validation_date)),
            ("AREA NAME", self.area_name_text or self.area_id.name or ""),
        ]

        for label, value in header_rows:
            pdf.setFont("Helvetica", 10)
            pdf.drawString(left + 2, y, label)
            pdf.drawString(colon_x, y, ":")
            is_red = label in ("TEST CARRIED OUT BY", "TEST WITNESSED BY", "VALIDATION DATE", "AREA NAME")
            pdf.setFillColor(colors.red if is_red else colors.black)
            parts = (value or "").splitlines() or [""]
            pdf.drawString(value_x, y, parts[0])
            if label == "CLIENT" and len(parts) > 1:
                yy = y - 14
                pdf.setFillColor(colors.black)
                pdf.setFont("Helvetica", 9.5)
                for p in parts[1:3]:
                    pdf.drawString(value_x, yy, p)
                    yy -= 12
                y -= 24
            pdf.setFillColor(colors.black)
            y -= line_h

        y -= 4

        # Equipment table
        eq_top = y
        eq_h = 52
        c1 = left + content_w * 0.30
        c2 = left + content_w * 0.65
        pdf.setLineWidth(1)
        pdf.rect(left, eq_top - eq_h, content_w, eq_h)
        pdf.line(c1, eq_top - eq_h, c1, eq_top)
        pdf.line(c2, eq_top - eq_h, c2, eq_top)
        pdf.setFillColor(colors.lightgrey)
        pdf.rect(left, eq_top - 16, content_w, 16, stroke=0, fill=1)
        pdf.setFillColor(colors.black)
        pdf.line(left, eq_top - 16, right, eq_top - 16)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(left + 3, eq_top - 11, "EQUIPMENT USED")
        pdf.drawCentredString((c1 + c2) / 2, eq_top - 11, "CALIBRATION DATE")
        pdf.drawCentredString((c2 + right) / 2, eq_top - 11, "CALIBRATION DUE DATE")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(left + 3, eq_top - 31, self.equipment_used_name.name if self.equipment_used_name else "")
        pdf.drawString(left + 3, eq_top - 45, f"Model No. : {self.equipment_model_no or ''}")
        pdf.drawString(left + 116, eq_top - 45, f"Sr.No. : {self.equipment_serial_no or ''}")
        pdf.drawCentredString((c1 + c2) / 2, eq_top - 34, self._fmt_date(self.calibration_date))
        pdf.drawCentredString((c2 + right) / 2, eq_top - 34, self._fmt_date(self.calibration_due_date))
        y = eq_top - eq_h - 10

        # Main readings table
        lines = self.air_velocity_line_ids.sorted(lambda l: (l.sr_no, l.id))
        nrows = max(len(lines), 1)
        h1 = 18
        h2 = 18
        rh = 29
        tbl_h = h1 + h2 + nrows * rh
        tx = left
        tw = content_w
        ty = y

        # Keep total <= table width to avoid right-side overlap/cropping.
        cols = [42, 108, 108, 34, 34, 34, 34, 34, 95]
        diff = int(round(tw - sum(cols)))
        cols[-1] = cols[-1] + diff
        x = [tx]
        for wcol in cols:
            x.append(x[-1] + wcol)

        pdf.rect(tx, ty - tbl_h, tw, tbl_h)
        for xi in x[1:-1]:
            pdf.line(xi, ty - tbl_h, xi, ty)
        pdf.line(tx, ty - h1, tx + tw, ty - h1)
        pdf.line(x[3], ty - h2, x[8], ty - h2)  # subheader line only across reading group
        pdf.line(tx, ty - h1 - h2, tx + tw, ty - h1 - h2)

        # data row lines
        for i in range(nrows):
            row_y = ty - h1 - h2 - (i + 1) * rh
            pdf.line(tx, row_y, tx + tw, row_y)

        # merge first two columns in body area
        body_top = ty - h1 - h2
        body_bottom = ty - tbl_h
        pdf.setFillColor(colors.white)
        pdf.rect(x[0], body_bottom, cols[0], body_top - body_bottom, stroke=0, fill=1)
        pdf.rect(x[1], body_bottom, cols[1], body_top - body_bottom, stroke=0, fill=1)
        pdf.setFillColor(colors.black)
        pdf.rect(x[0], body_bottom, cols[0], body_top - body_bottom, stroke=1, fill=0)
        pdf.rect(x[1], body_bottom, cols[1], body_top - body_bottom, stroke=1, fill=0)

        # table header grey
        pdf.setFillColor(colors.lightgrey)
        pdf.rect(tx, ty - h1, tw, h1, stroke=0, fill=1)
        pdf.rect(x[3], ty - h1 - h2, x[8] - x[3], h2, stroke=0, fill=1)
        pdf.setFillColor(colors.black)

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString((x[0] + x[1]) / 2, ty - 12, "Sr.")
        pdf.drawCentredString((x[0] + x[1]) / 2, ty - 20, "No.")
        pdf.setFillColor(colors.red)
        pdf.drawCentredString((x[1] + x[2]) / 2, ty - 16, "Equipment Name & ID.")
        pdf.setFillColor(colors.black)
        pdf.drawCentredString((x[2] + x[3]) / 2, ty - 16, "Filter No.")
        pdf.drawCentredString((x[3] + x[8]) / 2, ty - 11, "Air Velocity Reading m/s / FPM")
        for i in range(5):
            pdf.drawCentredString((x[3 + i] + x[4 + i]) / 2, ty - h1 - 11, str(i + 1))
        pdf.drawCentredString((x[8] + x[9]) / 2, ty - 12, "Average Air")
        pdf.drawCentredString((x[8] + x[9]) / 2, ty - 20, "Velocity ( m/s)")

        # merged left content text
        equip_name = self.area_name_text or (self.area_id.name if self.area_id else "")
        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString((x[0] + x[1]) / 2, (body_top + body_bottom) / 2, "1")
        pdf.setFillColor(colors.red)
        pdf.drawCentredString((x[1] + x[2]) / 2, (body_top + body_bottom) / 2 + 8, (equip_name or "")[:28])
        pdf.setFillColor(colors.black)

        # data rows (from col3 onwards)
        pdf.setFont("Helvetica", 10)
        for idx in range(nrows):
            line = lines[idx] if idx < len(lines) else None
            cy = body_top - idx * rh - 18
            if line:
                pdf.drawString(x[2] + 3, cy, (line.filter_no or "")[:20])
                vals = [line.reading_1, line.reading_2, line.reading_3, line.reading_4, line.reading_5]
                for i, val in enumerate(vals):
                    text = self._fmt_velocity(val)
                    pdf.drawCentredString((x[3 + i] + x[4 + i]) / 2, cy, text)
                avg_text = self._fmt_velocity(line.row_avg)
                pdf.drawCentredString((x[8] + x[9]) / 2, cy, avg_text)
        # extra blank strip under table like printed certificate
        blank_h = 60
        pdf.rect(left, ty - tbl_h - blank_h, content_w, blank_h)

        y = ty - tbl_h - blank_h - 2

        # Acceptance block
        acc_h = 52
        pdf.rect(left, y - acc_h, content_w, acc_h)
        pdf.line(left, y - 17, right, y - 17)
        pdf.line(left, y - 34, right, y - 34)
        pdf.setFillColor(colors.lightgrey)
        pdf.rect(left, y - 17, content_w, 17, stroke=0, fill=1)
        pdf.rect(left, y - 34, content_w, 17, stroke=0, fill=1)
        pdf.rect(left, y - 51, content_w, 17, stroke=0, fill=1)
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(width / 2, y - 12, f"ACCEPTANCE CRITERIA : {self.acceptance_criteria_text or ''}")
        pdf.drawCentredString(width / 2, y - 29, f"RESULT : {self.result_statement or ''}")
        pdf.drawCentredString(width / 2, y - 46, "ACCEPTANCE CRITERIA:- NMT 15 Min AS PER ISO-14644-3:2019 ( E )")
        y -= acc_h + 8

        # Signatures block
        sig_h = 132
        pdf.rect(left, y - sig_h, content_w, sig_h)
        one_third = content_w / 3
        pdf.line(left + one_third, y - sig_h, left + one_third, y)
        pdf.line(left + 2 * one_third, y - sig_h, left + 2 * one_third, y)
        pdf.line(left, y - 19, right, y - 19)
        pdf.line(left, y - 112, right, y - 112)
        pdf.line(left, y - 128, right, y - 128)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(left + one_third / 2, y - 13, "TEST CARRIED OUT BY")
        pdf.drawCentredString(left + one_third + one_third / 2, y - 13, "TEST WITNESSED BY")
        pdf.drawCentredString(left + 2 * one_third + one_third / 2, y - 13, "TEST REVIEWED BY")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(left + 4, y - 114, "Engg")
        pdf.drawString(left + 2 * one_third + 4, y - 114, "QA")
        pdf.drawCentredString(left + one_third / 2, y - 124, "Sign & Date")
        pdf.drawCentredString(left + one_third + one_third / 2, y - 124, "Sign & Date")
        pdf.drawCentredString(left + 2 * one_third + one_third / 2, y - 124, "Sign & Date")
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(left + one_third / 2, y - 140, "For,Micron HVAC Pvt.Ltd.")
        pdf.drawCentredString(left + one_third + one_third / 2, y - 140, f"For,{self.certificate_client_name or self.client_id.name or ''}")

        pdf.showPage()
        pdf.save()

        pdf_bytes = buffer.getvalue()
        buffer.close()

        filename = f"Test_Certificate_{self.name or self.id}.pdf"
        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(pdf_bytes),
                "mimetype": "application/pdf",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def action_download_test_certificate_excel(self):
        """Generate and download certificate data in Excel format."""
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(
                "Excel download requires 'xlsxwriter'. Install in Odoo venv: pip install xlsxwriter"
            )

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Test Certificate")

        title_fmt = workbook.add_format({"bold": True, "font_size": 14, "align": "center"})
        head_fmt = workbook.add_format({"bold": True, "bg_color": "#D9D9D9", "border": 1, "align": "center"})
        label_fmt = workbook.add_format({"bold": True})
        text_fmt = workbook.add_format({})
        border_fmt = workbook.add_format({"border": 1})
        border_num_fmt = workbook.add_format({"border": 1, "num_format": "0.00", "align": "center"})
        center_fmt = workbook.add_format({"align": "center"})
        red_fmt = workbook.add_format({"font_color": "red"})
        footer_fmt = workbook.add_format({"bold": True, "bg_color": "#D9D9D9", "border": 1, "align": "center"})

        # Column widths
        sheet.set_column("A:A", 10)
        sheet.set_column("B:B", 26)
        sheet.set_column("C:C", 20)
        sheet.set_column("D:H", 9)
        sheet.set_column("I:I", 16)

        row = 0
        sheet.merge_range(row, 0, row, 8, "TEST CERTIFICATE", title_fmt)
        row += 2

        # Header details
        details = [
            ("CLIENT", self.certificate_client_name or self.client_id.name or "", False),
            ("TEST CARRIED OUT BY", self.test_carried_out_by.name if self.test_carried_out_by else "", True),
            ("TEST WITNESSED BY", self.test_witnessed_by.name if self.test_witnessed_by else "", True),
            ("TEST CARRIED OUT", self.test_type or "", False),
            ("VALIDATION DATE", self._fmt_date(self.validation_date), True),
            ("AREA NAME", self.area_name_text or self.area_id.name or "", True),
        ]
        for label, value, red in details:
            sheet.write(row, 0, label, label_fmt)
            sheet.write(row, 1, ":", label_fmt)
            sheet.merge_range(row, 2, row, 8, value, red_fmt if red else text_fmt)
            row += 1

        row += 1
        # Equipment block
        sheet.merge_range(row, 0, row, 2, "EQUIPMENT USED", head_fmt)
        sheet.merge_range(row, 3, row, 5, "CALIBRATION DATE", head_fmt)
        sheet.merge_range(row, 6, row, 8, "CALIBRATION DUE DATE", head_fmt)
        row += 1
        equip_text = self.equipment_used_name.name if self.equipment_used_name else ""
        model_sr = f"Model No.: {self.equipment_model_no or ''}   Sr.No.: {self.equipment_serial_no or ''}"
        sheet.merge_range(row, 0, row, 2, equip_text, border_fmt)
        sheet.merge_range(row, 3, row, 5, self._fmt_date(self.calibration_date), border_fmt)
        sheet.merge_range(row, 6, row, 8, self._fmt_date(self.calibration_due_date), border_fmt)
        row += 1
        sheet.merge_range(row, 0, row, 2, model_sr, border_fmt)
        sheet.merge_range(row, 3, row, 5, "", border_fmt)
        sheet.merge_range(row, 6, row, 8, "", border_fmt)
        row += 2

        # Readings table header
        sheet.merge_range(row, 0, row + 1, 0, "Sr.\nNo.", head_fmt)
        sheet.merge_range(row, 1, row + 1, 1, "Equipment Name & ID.", head_fmt)
        sheet.merge_range(row, 2, row + 1, 2, "Filter No.", head_fmt)
        sheet.merge_range(row, 3, row, 7, "Air Velocity Reading m/s / FPM", head_fmt)
        sheet.merge_range(row, 8, row + 1, 8, "Average Air Velocity", head_fmt)
        row += 1
        for idx in range(5):
            sheet.write(row, 3 + idx, str(idx + 1), head_fmt)
        row += 1

        lines = self.air_velocity_line_ids.sorted(lambda l: (l.sr_no, l.id))
        nrows = max(len(lines), 1)
        equip_name = self.area_name_text or (self.area_id.name if self.area_id else "")

        start_data_row = row
        if lines:
            for line in lines:
                sheet.write(row, 2, line.filter_no or "", border_fmt)
                sheet.write_number(row, 3, line.reading_1 or 0.0, border_num_fmt)
                sheet.write_number(row, 4, line.reading_2 or 0.0, border_num_fmt)
                sheet.write_number(row, 5, line.reading_3 or 0.0, border_num_fmt)
                sheet.write_number(row, 6, line.reading_4 or 0.0, border_num_fmt)
                sheet.write_number(row, 7, line.reading_5 or 0.0, border_num_fmt)
                sheet.write_number(row, 8, line.row_avg or 0.0, border_num_fmt)
                row += 1
        else:
            for col in range(2, 9):
                sheet.write(row, col, "", border_fmt)
            row += 1

        end_data_row = row - 1
        sheet.merge_range(start_data_row, 0, end_data_row, 0, "1", border_fmt)
        sheet.merge_range(start_data_row, 1, end_data_row, 1, equip_name, workbook.add_format({"border": 1, "font_color": "red", "align": "center", "valign": "vcenter"}))

        row += 1
        sheet.merge_range(row, 0, row, 8, f"ACCEPTANCE CRITERIA : {self.acceptance_criteria_text or ''}", footer_fmt)
        row += 1
        sheet.merge_range(row, 0, row, 8, f"RESULT : {self.result_statement or ''}", footer_fmt)
        row += 1
        sheet.merge_range(row, 0, row, 8, "ACCEPTANCE CRITERIA:- NMT 15 Min AS PER ISO-14644-3:2019 ( E )", footer_fmt)
        row += 2

        # Signature section
        sheet.merge_range(row, 0, row, 2, "TEST CARRIED OUT BY", head_fmt)
        sheet.merge_range(row, 3, row, 5, "TEST WITNESSED BY", head_fmt)
        sheet.merge_range(row, 6, row, 8, "TEST REVIEWED BY", head_fmt)
        row += 1
        for _ in range(4):
            sheet.merge_range(row, 0, row, 2, "", border_fmt)
            sheet.merge_range(row, 3, row, 5, "", border_fmt)
            sheet.merge_range(row, 6, row, 8, "", border_fmt)
            row += 1
        sheet.write(row - 1, 0, "Engg", text_fmt)
        sheet.write(row - 1, 6, "QA", text_fmt)
        sheet.merge_range(row, 0, row, 2, "Sign & Date", center_fmt)
        sheet.merge_range(row, 3, row, 5, "Sign & Date", center_fmt)
        sheet.merge_range(row, 6, row, 8, "Sign & Date", center_fmt)
        row += 1
        sheet.merge_range(row, 0, row, 2, "For,Micron HVAC Pvt.Ltd.", center_fmt)
        sheet.merge_range(row, 3, row, 8, f"For,{self.certificate_client_name or self.client_id.name or ''}", center_fmt)

        workbook.close()
        xlsx_bytes = output.getvalue()
        output.close()

        filename = f"Test_Certificate_{self.name or self.id}.xlsx"
        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(xlsx_bytes),
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    @api.onchange("client_id")
    def _onchange_client_id_fill_certificate(self):
        for rec in self:
            if rec.client_id:
                rec.certificate_client_name = rec.client_id.name
                rec.certificate_client_address = rec.client_id.contact_address

    @api.onchange("engineer_id")
    def _onchange_engineer_id_fill_executor(self):
        for rec in self:
            if rec.engineer_id and not rec.test_carried_out_by:
                rec.test_carried_out_by = rec.engineer_id

    @api.onchange("equipment_used_name")
    def _onchange_equipment_used_name(self):
        for rec in self:
            if rec.equipment_used_name:
                rec.equipment_model_no = rec.equipment_used_name.model_no
                rec.equipment_serial_no = rec.equipment_used_name.serial_number
                rec.calibration_due_date = rec.equipment_used_name.calibration_due_date
                # Auto-fill each air-velocity row with the selected equipment.
                for line in rec.air_velocity_line_ids:
                    if not line.equipment_name_id:
                        line.equipment_name_id = rec.equipment_used_name

    def _normalize_instrument_ocr_text(self, text):
        """Light cleanup for common OCR quirks from instrument PDFs."""
        t = text.replace("\r\n", "\n").replace("\r", "\n")
        t = re.sub(r"(?i)\bmis\b", "m/s", t)
        return t

    def _split_mirrored_line(self, line):
        """
        Split a physical OCR line into left/right logical columns when the printer
        outputs two identical blocks side-by-side (MODEL: ... MODEL: ...).
        Returns [left_part, right_part] or [line] if not mirrored.
        """
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
        """Create micron.air.velocity.line rows from parsed data."""
        for job in self:
            job.air_velocity_line_ids.unlink()
            sr_counter = 1
            for row in parsed_rows:
                readings = row["readings"]
                self.env["micron.air.velocity.line"].create(
                    {
                        "job_id": job.id,
                        "sr_no": sr_counter,
                        "equipment_name_id": job.equipment_used_name.id,
                        "filter_no": row["filter_no"],
                        "reading_1": readings[0],
                        "reading_2": readings[1],
                        "reading_3": readings[2],
                        "reading_4": readings[3],
                        "reading_5": readings[4],
                        "unit": "m/s",
                    }
                )
                sr_counter += 1

    def action_import_air_velocity_from_text(self):
        """User pastes text and clicks the button."""
        for job in self:
            parsed = job._parse_air_velocity_samples_text(job.air_velocity_samples_text)
            job._load_air_velocity_rows_from_parsed(parsed)

    def action_import_air_velocity_from_file(self):
        """
        User uploads PDF/image; this extracts text and then parses it.
        NOTE: Requires python libraries:
          - pdfplumber (for PDFs)
          - pillow + pytesseract (for images) and Tesseract installed on server.
        """
        try:
            import pdfplumber
            from PIL import Image
            import pytesseract
        except ImportError:
            raise UserError(
                "PDF/image import requires 'pdfplumber', 'Pillow' and 'pytesseract' to be installed "
                "on the Odoo server."
            )

        for job in self:
            if not job.air_velocity_source_file:
                raise UserError("Please upload a PDF or image file before importing.")

            filename = (job.air_velocity_source_filename or "").lower()
            data = base64.b64decode(job.air_velocity_source_file)
            buffer = io.BytesIO(data)

            text = ""
            if filename.endswith(".pdf"):
                with pdfplumber.open(buffer) as pdf:
                    pages_text = [page.extract_text() or "" for page in pdf.pages]
                    text = "\n".join(pages_text)
            else:
                image = Image.open(buffer)
                text = pytesseract.image_to_string(image)

            if not text.strip():
                raise UserError("No text could be extracted from the uploaded file.")

            # Store extracted text so user can review / debug.
            job.air_velocity_samples_text = text
            parsed = job._parse_air_velocity_samples_text(text)
            job._load_air_velocity_rows_from_parsed(parsed)
