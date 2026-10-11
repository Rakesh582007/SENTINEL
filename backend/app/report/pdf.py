"""Incident report PDF (HANDOVER §6.4).  STATUS: TODO

    incident_pdf(incident: dict) -> bytes

`incident` is IncidentTracker.get(id). One A4 page with ReportLab:
title, time window in IST, kind (jamming / spoofing), affected H3 cells,
aircraft table (hex, flight, first bad time IST), approximate area
(centre + radius, labelled "approximate area for investigation"),
a one-paragraph plain-text summary, an "INJECTED TEST ATTACK" banner when
incident["injected"] is true, data credits (adsb.fi, adsb.lol) and the footer
"Auto-generated for analyst review - not an official report".
Served by GET /api/incidents/{id}/report.pdf (api/routes.py).
"""
from __future__ import annotations


def incident_pdf(incident: dict) -> bytes:
    raise NotImplementedError("report/pdf.py: implement per the module docstring")
