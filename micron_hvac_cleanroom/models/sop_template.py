from odoo import api, fields, models


class MicronSopRevisionHistory(models.Model):
    _name = "micron.sop.revision.history"
    _description = "SOP Revision History"
    _order = "revision desc"

    sop_id = fields.Many2one("micron.sop.template", required=True, ondelete="cascade")
    revision = fields.Char(string="Rev. No.", required=True)
    date = fields.Date(string="Date")
    description = fields.Text(string="Changes / Reason for Revision")
    changed_by = fields.Char(string="Changed By")

    _sql_constraints = [
        ("sop_rev_unique", "unique(sop_id, revision)", "Revision number must be unique per SOP."),
    ]


class MicronSopTemplate(models.Model):
    _name = "micron.sop.template"
    _description = "SOP Acceptance Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # ── Identity ─────────────────────────────────────────────────────────────
    name = fields.Char(string="Title", required=True, tracking=True)
    sop_no = fields.Char(string="SOP No.", required=True, tracking=True, help="e.g. MHPL/VL/001-03")
    code = fields.Char(string="Short Code", required=True, help="e.g. MHPL-VL-001")
    revision = fields.Char(string="Revision", default="01", tracking=True, help="Current revision e.g. 03")
    supersedes = fields.Char(string="Supersedes", help="e.g. MHPL/VL/001-02")
    test_type = fields.Selection(
        [
            ("air_velocity", "Air Velocity Measurement"),
            ("ach", "Air Change Rate (CFM/ACPH)"),
            ("particle_count", "Particle Count Test"),
            ("filter_integrity", "HEPA Filter Integrity (PAO)"),
            ("temp_humidity", "Temperature & Humidity"),
            ("diff_pressure", "Differential Pressure"),
            ("recovery", "Recovery Test"),
            ("lighting_noise", "Lighting / Noise"),
        ],
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("obsolete", "Obsolete")],
        default="approved",
        string="Status",
        tracking=True,
    )
    active = fields.Boolean(default=True)

    # ── Dates ─────────────────────────────────────────────────────────────────
    date_prepared = fields.Date(string="Date Prepared")
    effective_date = fields.Date(string="Effective Date")
    next_review_date = fields.Date(string="Next Review Date")
    total_pages = fields.Integer(string="Total Pages", default=1)

    # ── Signatures ────────────────────────────────────────────────────────────
    prepared_by = fields.Char(string="Prepared By")
    checked_by = fields.Char(string="Checked By")
    approved_by = fields.Char(string="Approved By")
    prepared_by_date = fields.Date(string="Prepared Date")
    checked_by_date = fields.Date(string="Checked Date")
    approved_by_date = fields.Date(string="Approved Date")

    # ── SOP Content (HTML rich text — mirrors the actual SOP layout) ──────────
    purpose = fields.Html(
        string="1.0 Purpose",
        sanitize_attributes=False,
    )
    scope = fields.Html(
        string="2.0 Scope",
        sanitize_attributes=False,
    )
    responsibilities = fields.Html(
        string="3.0 Responsibilities",
        sanitize_attributes=False,
    )
    definitions = fields.Html(
        string="4.0 Definitions",
        sanitize_attributes=False,
    )
    procedure = fields.Html(
        string="5.0 Procedure",
        sanitize_attributes=False,
    )
    acceptance_criteria_html = fields.Html(
        string="6.0 Acceptance Criteria",
        sanitize_attributes=False,
    )
    frequency = fields.Html(
        string="7.0 Frequency",
        sanitize_attributes=False,
    )
    references = fields.Html(
        string="8.0 References",
        sanitize_attributes=False,
    )
    abbreviations = fields.Html(
        string="9.0 Abbreviations",
        sanitize_attributes=False,
    )

    # ── Acceptance values (for programmatic evaluation in job lines) ──────────
    min_value = fields.Float(string="Min. Acceptance Value", digits=(16, 4))
    max_value = fields.Float(string="Max. Acceptance Value", digits=(16, 4))
    unit = fields.Char(string="Unit")
    notes = fields.Text(string="Internal Notes")

    # ── Revision History ─────────────────────────────────────────────────────
    revision_history_ids = fields.One2many(
        "micron.sop.revision.history",
        "sop_id",
        string="Revision History",
    )

    # ── Constraints ──────────────────────────────────────────────────────────
    _sql_constraints = [
        ("code_unique", "unique(code)", "SOP short code must be unique."),
        ("sop_no_unique", "unique(sop_no)", "SOP No. must be unique."),
    ]

    def action_approve(self):
        self.write({"state": "approved"})

    def action_obsolete(self):
        self.write({"state": "obsolete"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_print_sop(self):
        self.ensure_one()
        return self.env.ref("micron_hvac_cleanroom.action_report_micron_sop_document").report_action(self)

    def get_revision_label(self):
        """Returns SOP number label like MHPL/VL/001-03"""
        return self.sop_no or self.code
