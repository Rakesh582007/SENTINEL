"""Incident report PDF (HANDOVER §6.4), one A4 page with ReportLab.

    incident_pdf(incident: dict) -> bytes      # incident = IncidentTracker.get(id)

Served by GET /api/incidents/{id}/report.pdf.
"""
from __future__ import annotations

import io
import time

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

IST_OFFSET_S = 5.5 * 3600
NAVY = colors.HexColor("#0B1B33")
ORANGE = colors.HexColor("#F26B1D")
MAX_ROWS = 25
INJECTED_BANNER = "INJECTED TEST ATTACK - simulated in the Attack Simulator, not a real-world event."
MIXED_LINE = ("Also contains real (non-injected) degradation: some aircraft below were affected "
              "without any simulated attack (marked without \"(injected)\").")


def ist(ts: float | None, fmt: str = "%d %b %Y %H:%M:%S") -> str:
    return "ongoing" if ts is None else time.strftime(fmt, time.gmtime(ts + IST_OFFSET_S)) + " IST"


def latlon_text(lat: float, lon: float) -> str:
    """'31.600 N, 74.900 E'; hemispheres from the signs."""
    return f"{abs(lat):.3f} {'N' if lat >= 0 else 'S'}, {abs(lon):.3f} {'E' if lon >= 0 else 'W'}"


def summary_text(incident: dict) -> str:
    """The report's summary paragraph, worded by how many aircraft are involved."""
    n = incident.get("n_aircraft", 0)
    what = ("degraded or lost GPS integrity (NIC/NACp) or lost position" if incident["kind"] == "jamming"
            else "positions or altitudes that are physically inconsistent")
    when = (f"Since {ist(incident['opened_ts'], '%H:%M')}" if incident["closed_ts"] is None
            else f"Between {ist(incident['opened_ts'], '%H:%M')} and {ist(incident['closed_ts'], '%H:%M')}")
    if n >= 2:
        text = (f"{when}, {n} aircraft in this area reported {what}. The pattern across several independent "
                "aircraft indicates interference in this area rather than a fault on one aircraft.")
    elif n == 1:
        text = (f"{when}, a single aircraft in this area reported {what}. One aircraft alone is not proof of "
                "interference (it may be a fault on that aircraft), so treat this as a lead to check.")
    else:
        text = f"{when}, cells in this area were in an alarm state, but no individual aircraft details were collected."
    if incident.get("est_lat") is not None:
        text += (" The area above is a rough estimate from where aircraft first reported problems "
                 "and must be confirmed by investigation.")
    return text


def incident_pdf(incident: dict) -> bytes:
    buf = io.BytesIO()
    injected = bool(incident.get("injected"))
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"GPS Attack Watch incident {incident['id']}", author="GPS Attack Watch (auto-generated)",
                            subject=INJECTED_BANNER if injected else "GPS interference incident report")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY, fontSize=18, spaceAfter=2)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey)
    banner = ParagraphStyle("banner", parent=body, textColor=colors.white, backColor=ORANGE, borderPadding=4, fontName="Helvetica-Bold")

    kind = "GPS jamming" if incident["kind"] == "jamming" else "suspected GPS spoofing"
    n = incident.get("n_aircraft", 0)
    story = [Paragraph("GPS Attack Watch - Incident Report", h1),
             Paragraph(f"Incident {incident['id']} &middot; {kind}", body), Spacer(1, 4 * mm)]
    if injected:
        story += [Paragraph(INJECTED_BANNER, banner), Spacer(1, 2 * mm)]
        if incident.get("mixed"):
            story.append(Paragraph(MIXED_LINE, body))
        story.append(Spacer(1, 2 * mm))

    facts = [
        ["Opened", ist(incident["opened_ts"])],
        ["Closed", ist(incident["closed_ts"])],
        ["Type", kind],
        ["Aircraft affected", str(n)],
        ["Peak share of aircraft with bad GPS", f"{incident.get('max_frac_bad', 0):.0%}"],
        ["Affected H3 cells", ", ".join(incident["cells"][:8]) + (" ..." if len(incident["cells"]) > 8 else "")],
    ]
    if incident.get("est_lat") is not None:
        facts.append(["Approximate area for investigation",
                      f"centre {latlon_text(incident['est_lat'], incident['est_lon'])}, radius ~{incident['est_radius_km']:.0f} km"])
    t = Table(facts, colWidths=[62 * mm, 116 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                           ("TEXTCOLOR", (0, 0), (0, -1), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
    story += [t, Spacer(1, 5 * mm)]

    story += [Paragraph("Summary", ss["Heading3"]), Paragraph(summary_text(incident), body), Spacer(1, 4 * mm)]

    rows = [["Aircraft (hex)", "Flight", "First problem", "Reason", "Altitude ft"]]
    for a in incident.get("aircraft", [])[:MAX_ROWS]:
        rows.append([a["hex"].upper(), a.get("flight") or "-", ist(a["first_bad_ts"], "%H:%M:%S"),
                     a["reason"] + (" (injected)" if a.get("injected") else ""), str(a.get("alt_baro") or "-")])
    at = Table(rows, colWidths=[28 * mm, 24 * mm, 30 * mm, 66 * mm, 24 * mm], repeatRows=1)
    at.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5FA")])]))
    story += [Paragraph("Affected aircraft", ss["Heading3"]), at]
    if len(incident.get("aircraft", [])) > MAX_ROWS:
        story.append(Paragraph(f"... and {len(incident['aircraft']) - MAX_ROWS} more.", small))

    story += [Spacer(1, 6 * mm),
              Paragraph("Auto-generated for analyst review - not an official report. Source data: ADS-B broadcasts via "
                        "adsb.fi (https://adsb.fi) and adsb.lol (https://adsb.lol). Receive-only system: nothing was transmitted.", small)]
    doc.build(story)
    return buf.getvalue()
