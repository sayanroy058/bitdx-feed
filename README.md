# BITDXUSDB Live Feed API

A self-hostable, deterministic price feed for the synthetic instrument `BITDXUSDB`.
One tick per second, generated on the fly — no database, no state. The same
request always returns the same answer, and the feed never runs out of data.

Prices follow a realistic day-by-day zigzag story (1 → 5 → 3 → 5 → 9 → 2 → …)
where each day is a Brownian bridge between daily targets, so the path wanders
up and down intraday yet lands exactly on each day's target. Past the initial
7-day table, daily targets keep extending with seeded random up/down swings.

## Endpoints

### Plain feed (JSON or CSV)

| Route | Description |
|---|---|
| `GET /` | Current tick. JSON by default |
| `GET /?format=csv` | Current tick as CSV (header + row) |
| `GET /` with `Accept: text/csv` | Current tick as CSV (auto-detected) |
| `GET /tick?ts=<milliseconds>` | Tick for a specific millisecond timestamp |
| `GET /health` | `{"status":"ok"}` — Render health check |

Example JSON response:

```json
{
  "symbol": "BITDXUSDB",
  "rate": "2.39685",
  "high": "2.40180",
  "low": "2.39354",
  "open": "2.39725",
  "close": "2.39685",
  "volume": "0.25",
  "timestamp": "1788693365262"
}
```

Example CSV response:

```csv
symbol,rate,high,low,open,close,volume,timestamp
BITDXUSDB,2.39685,2.40180,2.39354,2.39725,2.39685,0.25,1788693365262
```

### TradingView UDF datafeed

Standard TradingView charting-library datafeed endpoints:

| Route | Purpose |
|---|---|
| `GET /api/datafeed/config` | Datafeed capabilities + supported resolutions |
| `GET /api/datafeed/time` | Server time |
| `GET /api/datafeed/symbols?symbol=BITDXUSDB` | Symbol metadata |
| `GET /api/datafeed/search?query=bit&limit=5` | Symbol search |
| `GET /api/datafeed/history?symbol=BITDXUSDB&from=<unix s>&to=<unix s>&resolution=<res>` | OHLCV bars |

Supported resolutions: `1S, 5S, 15S, 30S, 1, 5, 15, 30, 60, 240, 1D`
(seconds, minutes, and daily). History honors `from`/`to` and `countback`
pagination, returns at most 5,000 bars per request, and responds with
`{"s":"ok","t":[...],"o":[...],"h":[...],"l":[...],"c":[...],"v":[...]}` or
`{"s":"no_data","nextTime":...}`.

Wire it into TradingView's charting library with:

```js
new Datafeeds.UDFCompatibleDatafeed("https://<your-service>.onrender.com/api/datafeed")
```

## Run locally

```bash
pip install -r requirements.txt
gunicorn app:app --bind 0.0.0.0:8000
# or: python app.py
```

## Regenerate the static 7-day dataset

```bash
python3 generate_seconds_prices.py   # writes next_7_days_seconds.json/.csv (604,800 ticks)
```

The exports are intentionally gitignored (100+ MB combined) and not needed by
the API — the server generates the identical series deterministically.

## Deploy on Render

1. Push this repository to GitHub/GitLab.
2. In [Render](https://render.com): **New + → Blueprint** and connect the repo.
3. `render.yaml` is auto-detected and provisions a free web service
   (`gunicorn app:app` bound to `$PORT`, health check at `/health`).
4. Open `https://<your-service>.onrender.com/` to see the live tick.

## Notes

- Feed epoch: ticks start at unix second `1788647843` (timestamp
  `1788647842262` ms). History windows before that return `no_data`.
- Minute bars are bucketed to UTC clock boundaries; `1D` bars align to the
  feed's generated day boundaries so daily candles reproduce the 1→5→3→… story.
