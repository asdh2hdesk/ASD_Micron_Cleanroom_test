{
    'name': 'Micron HVAC — Digital Management System',
    'version': '18.0.1.0.0',
    'category': 'Services/HVAC',
    'summary': 'HVAC Test Management, SOP Revisions, Instrument Calibration & Job Scheduling',
    'description': """
        Complete digital management system for HVAC service companies:
        - SOP Template Library with full revision control and approval workflow
        - Instrument Calibration Registry with due-date alerts and job gate
        - Test Management with parametric result recording and auto Pass/Fail
        - Job Scheduling linked to Sales Orders with technician dispatch
        - Non-Conformance Reports (NCR) and CAPA tracking
        - Professional SOP Template PDF and Test Certificate PDF (mirrored structure)
    """,
    'author': 'Rakesh ASD',
    'website': 'https://www.asdsoftwares.com',
    'depends': ['base', 'mail', 'hr', 'calendar'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/validation_master_data.xml',
        'views/hvac_sop_views.xml',
        'views/hvac_instrument_views.xml',
        'views/hvac_test_views.xml',
        'views/hvac_job_views.xml',
        'views/hvac_ncr_views.xml',
        'views/menu.xml',
        'report/report_actions.xml',
        'report/report_sop_template.xml',
        'report/report_test_certificate.xml',
        'report/report_vl001_annexures.xml',
        'report/report_vl002_annexures.xml',
        'report/report_vl003_annexures.xml',
        'report/report_vl004_annexures.xml',
        'report/report_vl005_annexures.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
