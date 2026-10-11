# data/sample — 19 minutes of real traffic for replay out of the box

Recorded by `backend/scripts/record.py` on Sunday 11 Oct 2026, 12:20–12:39 IST, region `north_india` (Amritsar 250 NM, J&K 150 NM, Delhi 150 NM), from adsb.fi and adsb.lol. About 9,900 aircraft records.

The backend replays this automatically when `data/recordings/` is empty, so a fresh clone shows a working map before anyone has recorded anything. Your own recordings take over as soon as they exist.

It contains one real GPS-integrity loss: **FDX5384** (Boeing 777F, N857FD) at 37,000 ft near 33.5N 72.9E, around 12:32 IST, reported NIC 0 / NACp 0, and adsb.fi flagged `gpsOkBefore`. A single aircraft is not evidence of jamming; it is the kind of signal the crowd method aggregates.

Data credit: [adsb.fi](https://adsb.fi) and [adsb.lol](https://adsb.lol) contributors. Shared here only for non-commercial testing of this student project.
