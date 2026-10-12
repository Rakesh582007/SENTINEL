"""Incident report PDF (HANDOVER §6.4), A4 with ReportLab.

    incident_pdf(incident: dict, summary=None, summary_label=None) -> bytes   # incident = IncidentTracker.get(id)

Served by GET /api/incidents/{id}/report.pdf.

Layout, top to bottom, written for a reader who has never seen the dashboard:
header band (product, incident id, status) -> injected banner if simulated ->
four key numbers -> "What happened" (one paragraph) -> "Where" (approximate
area for investigation) -> affected aircraft in plain words -> how to read
this report -> footer with sources, receive-only note and page number.
"""
from __future__ import annotations

import io
import time
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

IST_OFFSET_S = 5.5 * 3600
NAVY = colors.HexColor("#0B1B33")
INK = colors.HexColor("#1F2A3A")
MUTED = colors.HexColor("#5B6779")
RULE = colors.HexColor("#D9DEE6")
PANEL = colors.HexColor("#F3F5F9")
ORANGE = colors.HexColor("#F26B1D")
RED = colors.HexColor("#C23B3F")
PURPLE = colors.HexColor("#7B45C4")
GREEN = colors.HexColor("#2E8B57")
MAX_ROWS = 40
INJECTED_BANNER = "INJECTED TEST ATTACK - simulated in the Attack Simulator, not a real-world event."
MIXED_LINE = ("Also contains real (non-injected) degradation: some aircraft below were affected "
              "without any simulated attack (marked \"Real\" in the Source column).")

# Rule-engine reason codes -> words a non-specialist can read.
REASON_TEXT = {
    "low_nacp": "GPS accuracy dropped (NACp)",
    "low_nic": "GPS integrity dropped (NIC)",
    "position_lost": "Stopped reporting a position",
    "gps_lost_flag": "Receiver network saw GPS loss",
    "impossible_jump": "Position jumped impossibly far",
    "alt_offset_outlier": "GPS and pressure altitude disagree",
    "colocation_cluster": "Stacked on one spot with other aircraft",
    "track_mismatch": "Heading does not match movement",
    "recovery_jump": "Position snapped back after GPS loss",
    "feed_glitch": "Data feed glitch (not counted)",
}


def ist(ts: float | None, fmt: str = "%d %b %Y %H:%M:%S") -> str:
    return "ongoing" if ts is None else time.strftime(fmt, time.gmtime(ts + IST_OFFSET_S)) + " IST"


def latlon_text(lat: float, lon: float) -> str:
    """'31.600 N, 74.900 E'; hemispheres from the signs."""
    return f"{abs(lat):.3f} {'N' if lat >= 0 else 'S'}, {abs(lon):.3f} {'E' if lon >= 0 else 'W'}"


def reason_text(code: str | None) -> str:
    if not code:
        return "-"
    return "; ".join(REASON_TEXT.get(c.strip(), c.strip().replace("_", " ")) for c in code.split(","))


def duration_text(opened: float, closed: float | None) -> str:
    if closed is None:
        return "Still open"
    mins = max(0, round((closed - opened) / 60))
    return "under 1 min" if mins < 1 else f"{mins} min" if mins < 90 else f"{mins / 60:.1f} h"


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
        text += (" The area given under Where is a rough estimate from where aircraft first reported problems "
                 "and must be confirmed by investigation.")
    return text


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10.5, leading=15, textColor=INK, alignment=TA_LEFT)
    return {
        "body": base,
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=NAVY,
                             spaceBefore=4, spaceAfter=5),
        "small": ParagraphStyle("small", parent=base, fontSize=8.5, leading=11.5, textColor=MUTED),
        "label": ParagraphStyle("label", parent=base, fontSize=8.5, leading=11, textColor=MUTED),
        "big": ParagraphStyle("big", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9.5, leading=12.5),
        "cellb": ParagraphStyle("cellb", parent=base, fontName="Helvetica-Bold", fontSize=9.5, leading=12.5),
        "head": ParagraphStyle("head", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white),
        "banner": ParagraphStyle("banner", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=colors.white),
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=colors.white),
        "sub": ParagraphStyle("sub", parent=base, fontSize=10, leading=13, textColor=colors.HexColor("#C9D3E3")),
        "chip": ParagraphStyle("chip", parent=base, fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.white,
                               alignment=1),
    }


def _box(content, bg, pad=8, border=None) -> Table:
    t = Table([[content]], colWidths=[178 * mm])
    style = [("BACKGROUND", (0, 0), (-1, -1), bg), ("LEFTPADDING", (0, 0), (-1, -1), pad),
             ("RIGHTPADDING", (0, 0), (-1, -1), pad), ("TOPPADDING", (0, 0), (-1, -1), pad - 1),
             ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]
    if border is not None:
        style.append(("LINEBEFORE", (0, 0), (0, -1), 3, border))
    t.setStyle(TableStyle(style))
    return t


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.line(16 * mm, 14 * mm, A4[0] - 16 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(16 * mm, 9.5 * mm, "SENTINEL - GPS Attack Watch. Auto-generated for analyst review, not an official report. "
                                         "Receive-only: nothing was transmitted.")
    canvas.drawRightString(A4[0] - 16 * mm, 9.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def incident_pdf(incident: dict, summary: str | None = None, summary_label: str | None = None) -> bytes:
    """summary/summary_label: the AI-written or template note (app/ai/summary.py); without it the
    report uses summary_text()."""
    buf = io.BytesIO()
    injected = bool(incident.get("injected"))
    jamming = incident["kind"] == "jamming"
    kind = "GPS jamming" if jamming else "Suspected GPS spoofing"
    tone = RED if jamming else PURPLE
    is_open = incident.get("closed_ts") is None
    n = incident.get("n_aircraft", len(incident.get("aircraft", [])))
    s = _styles()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=20 * mm,
                            title=f"GPS Attack Watch incident {incident['id']}", author="GPS Attack Watch (auto-generated)",
                            subject=INJECTED_BANNER if injected else "GPS interference incident report")
    story: list = []

    # ---- header band
    chip = Table([[Paragraph("OPEN" if is_open else "CLOSED", s["chip"])]], colWidths=[26 * mm])
    chip.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), tone if is_open else MUTED),
                              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    head = Table([[[Paragraph("GPS Interference Incident Report", s["title"]),
                    Paragraph(f"SENTINEL &middot; GPS Attack Watch &middot; Incident {escape(incident['id'])}", s["sub"])],
                   chip]], colWidths=[146 * mm, 32 * mm])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (0, 0), 10), ("TOPPADDING", (0, 0), (-1, -1), 10),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 11), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("LINEBELOW", (0, 0), (-1, -1), 3, tone)]))
    story += [head, Spacer(1, 4 * mm)]

    if injected:
        story.append(_box(Paragraph(INJECTED_BANNER, s["banner"]), ORANGE))
        if incident.get("mixed"):
            story += [Spacer(1, 1.5 * mm), Paragraph(MIXED_LINE, s["small"])]
        story.append(Spacer(1, 4 * mm))

    # ---- key numbers
    def tile(label: str, value: str, note: str = "") -> list:
        return [Paragraph(label, s["label"]), Paragraph(escape(value), s["big"]), Paragraph(escape(note), s["small"])]

    peak = incident.get("max_frac_bad", 0) or 0
    tiles = Table([[
        tile("Type", "Jamming" if jamming else "Spoofing", "suspected" if not jamming else "GPS signal drowned out"),
        tile("Started", ist(incident["opened_ts"], "%H:%M:%S").replace(" IST", ""), ist(incident["opened_ts"], "%d %b %Y") .replace(" IST", "") + " IST"),
        tile("Duration", duration_text(incident["opened_ts"], incident.get("closed_ts")),
             "" if is_open else "ended " + ist(incident["closed_ts"], "%H:%M")),
        tile("Aircraft affected", str(n), f"peak {peak:.0%} with bad GPS" if jamming and peak else "independent aircraft"),
    ]], colWidths=[44.5 * mm] * 4)
    tiles.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LINEAFTER", (0, 0), (-2, -1), 0.8, colors.white), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [tiles, Spacer(1, 6 * mm)]

    # ---- what happened
    story.append(Paragraph("What happened", s["h2"]))
    if summary:
        label = escape(summary_label or "Summary")
        story.append(_box(Paragraph(f"<font color='#5B6779' size='8.5'><b>{label}:</b></font><br/>{escape(summary)}", s["body"]),
                          PANEL, border=NAVY))
    else:
        story.append(Paragraph(summary_text(incident), s["body"]))
    story.append(Spacer(1, 5 * mm))

    # ---- where
    cells = incident.get("cells", [])
    where = [Paragraph("Where", s["h2"])]
    if incident.get("est_lat") is not None:
        where.append(Paragraph(
            f"<b>Approximate area for investigation:</b> centred near {latlon_text(incident['est_lat'], incident['est_lon'])}, "
            f"radius about {incident['est_radius_km']:.0f} km. Estimated from where affected aircraft last had good GPS "
            "or first reported problems. It is a rough area to search, not the location of a transmitter, "
            "and says nothing about who caused it.", s["body"]))
    else:
        where.append(Paragraph("No area estimate (spoofing incidents are located by the aircraft involved, listed below).", s["body"]))
    where.append(Spacer(1, 1.5 * mm))
    where.append(Paragraph(f"Map hexagons involved ({len(cells)}, H3 ids): "
                           + escape(", ".join(cells[:10]) + (" ..." if len(cells) > 10 else "")), s["small"]))
    story += [KeepTogether(where), Spacer(1, 5 * mm)]

    # ---- aircraft to notify (early warnings into this incident's area)
    warned = incident.get("warned", [])
    affected = {a["hex"] for a in incident.get("aircraft", [])}
    story.append(Paragraph(f"Aircraft to notify ({len(warned)})", s["h2"]))
    story.append(Paragraph(
        "Aircraft whose current track and speed took them into this area within the next 15 minutes. "
        "Pass this list to the controlling ATC unit and the airlines so crews can prepare backup navigation. "
        "This system is receive-only: it does not contact aircraft itself.", s["small"]))
    story.append(Spacer(1, 2 * mm))
    if warned:
        rows = [[Paragraph(h, s["head"]) for h in ("Flight", "Aircraft ID", "First warned", "Time to entry then", "Status", "Area")]]
        for w in warned[:MAX_ROWS]:
            eta = w.get("eta_s")
            eta_txt = "-" if eta is None else ("under 1 min" if eta < 60 else f"~{round(eta / 60)} min")
            status = "Entered: GPS affected" if w["hex"] in affected else "Heading in / passed edge"
            rows.append([
                Paragraph(escape(w.get("flight") or "unknown"), s["cellb"]),
                Paragraph(escape(w["hex"].upper()), s["cell"]),
                Paragraph(ist(w["first_warned_ts"], "%H:%M:%S").replace(" IST", ""), s["cell"]),
                Paragraph(eta_txt, s["cell"]),
                Paragraph(status, s["cell"]),
                Paragraph("<font color='#F26B1D'><b>Test attack</b></font>" if w.get("injected") else "Real", s["cell"]),
            ])
        wt = Table(rows, colWidths=[24 * mm, 22 * mm, 25 * mm, 32 * mm, 54 * mm, 21 * mm], repeatRows=1)
        wt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), tone), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PANEL]),
                                ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 4.5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(wt)
        if len(warned) > MAX_ROWS:
            story.append(Paragraph(f"... and {len(warned) - MAX_ROWS} more.", s["small"]))
    else:
        story.append(Paragraph("No aircraft was projected to fly into this area while the incident was open.", s["body"]))
    story.append(Spacer(1, 6 * mm))

    # ---- aircraft
    story.append(Paragraph(f"Affected aircraft ({n})", s["h2"]))
    aircraft = incident.get("aircraft", [])
    if aircraft:
        rows = [[Paragraph(h, s["head"]) for h in ("Flight", "Aircraft ID", "First problem", "What it reported", "Altitude", "Source")]]
        for a in aircraft[:MAX_ROWS]:
            alt = a.get("alt_baro")
            rows.append([
                Paragraph(escape(a.get("flight") or "unknown"), s["cellb"]),
                Paragraph(escape(a["hex"].upper()), s["cell"]),
                Paragraph(ist(a["first_bad_ts"], "%H:%M:%S").replace(" IST", ""), s["cell"]),
                Paragraph(escape(reason_text(a.get("reason"))), s["cell"]),
                Paragraph(f"{alt:,} ft" if isinstance(alt, (int, float)) else "-", s["cell"]),
                Paragraph("<font color='#F26B1D'><b>Injected</b></font>" if a.get("injected") else "Real", s["cell"]),
            ])
        at = Table(rows, colWidths=[24 * mm, 22 * mm, 27 * mm, 61 * mm, 23 * mm, 21 * mm], repeatRows=1)
        at.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PANEL]),
                                ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 4.5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(at)
        if len(aircraft) > MAX_ROWS:
            story.append(Paragraph(f"... and {len(aircraft) - MAX_ROWS} more.", s["small"]))
    else:
        story.append(Paragraph("No individual aircraft details were collected for this incident.", s["body"]))
    story.append(Spacer(1, 6 * mm))

    # ---- how to read
    how = ("Aircraft broadcast their position and how much they trust their GPS about once a second (ADS-B). "
           "An area is flagged when several different aircraft report bad GPS at the same time, so one faulty "
           "aircraft is not enough. " if jamming else
           "Aircraft broadcast their position about once a second (ADS-B). Spoofing is suspected when a reported "
           "position or altitude is physically impossible: a jump faster than any aircraft, GPS and pressure "
           "altitude disagreeing, or several aircraft stacked on one spot. ")
    how += ("Source data: public ADS-B feeds adsb.fi (https://adsb.fi) and adsb.lol (https://adsb.lol). "
            "Detection is rule-based; any written summary only rewords those rules' output.")
    story.append(KeepTogether([Paragraph("How to read this report", s["h2"]), Paragraph(how, s["small"]),
                               Spacer(1, 2 * mm), Paragraph(f"Generated {ist(time.time())}.", s["small"])]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
