"""Test setup. Env vars must be set BEFORE any `app` import (config reads them at import)."""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="gaw-tests-"))
os.environ.setdefault("GAW_AUTOSTART", "false")
os.environ.setdefault("GAW_DB_PATH", str(_TMP / "test.db"))
os.environ.setdefault("GAW_RECORDINGS_DIR", str(_TMP / "recordings"))
os.environ.setdefault("GAW_RECORD_LIVE", "false")

import json  # noqa: E402

import pytest  # noqa: E402

from app.records import Record  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
POLL_TS = 1791701082.0  # 11 Oct 2026 06:44:42 UTC


@pytest.fixture
def gotchas() -> dict:
    return json.loads((FIXTURES / "adsb_gotchas.json").read_text(encoding="utf-8"))


@pytest.fixture
def real_amritsar() -> dict:
    return json.loads((FIXTURES / "adsbfi_amritsar_20261011.json").read_text(encoding="utf-8"))


def pdf_text(pdf: bytes) -> str:
    """Decoded page content of a ReportLab PDF (ASCII85 + Flate streams), for text assertions."""
    import base64
    import re
    import zlib

    out = []
    for m in re.finditer(rb"/ASCII85Decode /FlateDecode \][^>]*>>\s*stream\r?\n(.*?)endstream", pdf, re.S):
        data = m.group(1).strip()
        out.append(zlib.decompress(base64.a85decode(data.removesuffix(b"~>"))).decode("latin-1"))
    return "\n".join(out)


def make(hex_id: str, lat: float, lon: float, ts: float = POLL_TS, **kw) -> Record:
    """A healthy airborne ADS-B record; override any field with kwargs."""
    base = dict(ts=ts, poll_ts=ts, hex=hex_id, source=kw.pop("source", "test"), lat=lat, lon=lon,
                alt_baro=35000, alt_geom=36500, gs=450.0, track=90.0, nic=8, nac_p=10, version=2,
                src_type="adsb_icao", seen=0.5, seen_pos=0.5)
    base.update(kw)
    return Record(**base)
