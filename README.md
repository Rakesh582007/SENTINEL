# SENTINEL — GPS Attack Watch

Team **Ethicals** · SEDHACKS'26 · Domain 01: Space Applications & Defence Technology

Detects GPS **jamming** and **spoofing** over India from public aircraft (ADS-B) data, warns flights heading into affected areas, and auto-generates incident reports. Receive-only: nothing in this project ever transmits a radio signal.

Full spec: [`docs/HANDOVER.md`](docs/HANDOVER.md).

---

## 1. Start recording NOW (no installs needed)

The replay demo is only as good as the data recorded before the event. Run this on the laptop you will demo from, and leave it running until the hackathon starts.

```bash
git clone https://github.com/Rakesh582007/SENTINEL.git
cd SENTINEL
python backend/scripts/record.py --once     # 10-second check: both sources should say "ok"
python backend/scripts/record.py            # leave this running (Ctrl+C to stop)
```

On Windows, use `py` if `python` isn't found. Plug the charger in, and set *Control Panel → Power Options → Choose what closing the lid does → Do nothing*. The recorder itself blocks Windows sleep while it runs.

- Default region `north_india` = Amritsar 250 NM + J&K 150 NM + Delhi 150 NM, every 10 s, from **adsb.fi and adsb.lol** (they see different aircraft; the backend merges them).
- Other regions: `--region nw_border | delhi | all_india`, or custom circles: `--points "31.6,74.9,250;28.6,77.2,150"`.
- Output: `data/recordings/rec_<UTC date>_<UTC hour>_<run>.jsonl.gz`, about 6–7 MB per hour. Not committed to git.
- Restarting is safe; every run writes new files.

Backup idea: the recorder is pure Python standard library, so a teammate's laptop (or an Android phone with Termux + Python) can run a second copy.

## Data credits

Aircraft data from [adsb.fi](https://adsb.fi) (open data API, non-commercial use) and [adsb.lol](https://adsb.lol). The dashboard must show these credits.
