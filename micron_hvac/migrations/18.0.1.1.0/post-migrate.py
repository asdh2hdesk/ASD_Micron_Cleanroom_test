# -*- coding: utf-8 -*-
"""Seed the SOP governing standard on databases that already hold the SOPs.

`data/validation_master_data.xml` is now noupdate="1", so upgrading no longer
overwrites SOPs and instruments the user has edited. That also means the new
`standard_ref` field would stay empty on existing databases — this fills it in
once, for the five standard validation SOPs, without touching anything else.
"""

STANDARDS = [
    ('VL-001', 'ISO 14644-3:2019 Annex B1 / EU GMP Annex 1:2022'),
    ('VL-002', 'ISO 14644-3:2019 Annex B6 / EU GMP Annex 1:2022'),
    ('VL-003', 'ISO 14644-1:2015 / ISO 14644-3:2019 Annex B3'),
    ('VL-004', 'ISO 14644-3:2019 Annex B12 / ISPE Baseline Guide Vol. 5'),
    ('VL-005', 'EU GMP Annex 1:2022 / WHO TRS 986 Annex 3'),
]


def migrate(cr, version):
    if not version:
        return
    for code, standard in STANDARDS:
        cr.execute(
            """
            UPDATE hvac_sop_revision
               SET standard_ref = %s
             WHERE (standard_ref IS NULL OR standard_ref = '')
               AND sop_code LIKE %s
            """,
            (standard, '%%%s%%' % code),
        )
