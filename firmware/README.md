# firmware/ — Ground Sentinel (ESP32 + GPS box), not started here

Spec: HANDOVER §9.1 and the hardware session's guide. What the backend expects:

- `POST http://<laptop-ip>:8000/api/sentinel` every ~2 s, JSON:
  `{"id":"sentinel-1","ts":<millis>,"lat":..,"lon":..,"alt":..,"fix":true,"sats_used":8,"sats_in_view":11,"avg_snr":38.5,"hdop":0.9,"status":"OK","snr_list":[..]}`
- `status` is one of `OK`, `SEARCHING` (no fix / no sky view yet), `JAMMING`, `SPOOF`. Extra fields are kept.
- The laptop must run the API with `--host 0.0.0.0` so the ESP32 can reach it, and Windows Firewall must allow Python on private networks.
- No packet for 10 s shows the box as OFFLINE on the dashboard.

Test from the laptop without the box:

```bash
curl -X POST http://localhost:8000/api/sentinel -H "Content-Type: application/json" -d "{\"id\":\"sentinel-1\",\"fix\":true,\"sats_used\":8,\"avg_snr\":38.5,\"status\":\"OK\"}"
```
