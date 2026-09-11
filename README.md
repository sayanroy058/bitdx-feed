# BI2X/BIUSDB Live Feed API

A self-hostable, deterministic price feed for the synthetic instrument `BI2X/BIUSDB`.
One tick per second, no database, no state — the same request always returns the
same answer, and the feed never runs out of data.

Prices follow a realistic day-by-day zigzag story (1 → 5 → 3 → 5 → 9 → 2 → …)
where each day is a Brownian bridge between daily targets, so the path wanders
up and down intraday yet lands exactly on each day's target.

**The live feed matches the committed dataset.** For its first 7 days the API
serves values that are byte-identical to `next_7_days_seconds.csv` and the
second-wise JSON export — it replays the same seeded random stream. Past day 7
the feed continues deterministically in the same style (seeded up/down swings),
so it never stops and never loops.

**Live deployment:** `https://bitdx-feed.onrender.com`

---

## 1. Plain feed (JSON or CSV)

Ticks always use this field order:
`symbol, rate, high, low, open, close, volume, timestamp`.

### `GET /` — current tick (JSON)

Expected result (values change every second):

```json
{
  "symbol": "BI2X/BIUSDB",
  "rate": "2.42868",
  "high": "2.43274",
  "low": "2.42757",
  "open": "2.42884",
  "close": "2.42868",
  "volume": "0.26",
  "timestamp": "1788694235262"
}
```

### `GET /?format=csv` — current tick as CSV

Expected result (header row + one data row):

```csv
symbol,rate,high,low,open,close,volume,timestamp
BI2X/BIUSDB,2.42868,2.43274,2.42757,2.42884,2.42868,0.26,1788694235262
```

### `GET /` with `Accept: text/csv` — CSV auto-detected

Same CSV output as above.

### `GET /tick?ts=<milliseconds>` — tick at a specific time

Example: `GET /tick?ts=1788998401000` (the very first tick of the feed)

```json
{
  "symbol": "BI2X/BIUSDB",
  "rate": "1.00011",
  "high": "1.00114",
  "low": "0.99866",
  "open": "1.00000",
  "close": "1.00011",
  "volume": "0.23",
  "timestamp": "1788998401000"
}
```

Also supports `?format=csv` / `Accept: text/csv`.

### `GET /health` — liveness check

```json
{"status": "ok", "symbol": "BI2X/BIUSDB"}
```

---

## 2. TradingView UDF datafeed endpoints

Point the TradingView charting library at:

```js
new Datafeeds.UDFCompatibleDatafeed("https://bitdx-feed.onrender.com/api/datafeed")
```

### `GET /api/datafeed/config` — capabilities

```json
{
  "supports_search": true,
  "supports_group_request": false,
  "supports_marks": false,
  "supports_timescale_marks": false,
  "supports_time": true,
  "supports_time_scale": true,
  "supported_resolutions": ["1S", "5S", "15S", "30S", "1", "5", "15", "30", "60", "240", "1D"]
}
```

### `GET /api/datafeed/time` — server time (unix seconds)

```json
{"serverTime": 1788694295}
```

### `GET /api/datafeed/symbols?symbol=BI2X/BIUSDB` — symbol metadata

```json
{
  "symbol": "BI2X/BIUSDB",
  "ticker": "BI2X/BIUSDB",
  "full_name": "BI2X/BIUSDB",
  "description": "BI2X/BIUSDB (live synthetic feed)",
  "exchange": "BITDX",
  "type": "crypto",
  "session": "24x7",
  "timezone": "UTC",
  "minmov": 1,
  "pricescale": 100000,
  "tick_size": 0.00001,
  "has_intraday": true,
  "has_seconds": true,
  "has_daily": true,
  "has_weekly_and_monthly": false,
  "supported_resolutions": ["1S", "5S", "15S", "30S", "1", "5", "15", "30", "60", "240", "1D"],
  "volume_precision": 2,
  "data_status": "streaming"
}
```

### `GET /api/datafeed/search?query=bit&limit=5` — symbol search

```json
[
  {
    "symbol": "BI2X/BIUSDB",
    "ticker": "BI2X/BIUSDB",
    "full_name": "BI2X/BIUSDB",
    "description": "BI2X/BIUSDB (live synthetic feed)",
    "exchange": "BITDX",
    "type": "crypto"
  }
]
```

Returns `[]` when the query does not match.

### `GET /api/datafeed/history?symbol=BI2X/BIUSDB&from=<unix s>&to=<unix s>&resolution=<res>` — OHLCV bars

Supported resolutions (seconds, minutes, daily):

| Resolution | Meaning |
|---|---|
| `1S` `5S` `15S` `30S` | 1/5/15/30 seconds |
| `1` `5` `15` `30` `60` `240` | 1/5/15/30/60/240 minutes |
| `1D` | daily |

`from`/`to` are unix seconds; `countback` is also supported for pagination
(`history?symbol=X&resolution=D&to=<now>&countback=500`).

Expected result when data exists:

```json
{
  "s": "ok",
  "t": [1788998401, 1788998402, 1788998403],
  "o": [1.0, 1.00006, 1.00037],
  "h": [1.00059, 1.0019, 1.00158],
  "l": [0.99975, 0.99972, 0.99938],
  "c": [1.00006, 1.00037, 1.00024],
  "v": [0.13, 0.18, 0.14]
}
```

Expected result when the requested window has no data (e.g. before the feed
started at unix second `1788998400`):

```json
{"s": "no_data", "nextTime": 1788998400}
```

Notes:
- At most 5,000 bars are returned per request (the most recent ones).
- Minute bars are bucketed to UTC clock boundaries.
- `1D` bars align to the feed's generated day boundaries, so daily candles
  reproduce the 1 → 5 → 3 → 5 → 9 → 2 → … story exactly.

---

## 3. Static 7-day dataset (repo file)

`next_7_days_seconds.csv` (604,800 rows = 7 days × 86,400 seconds) is versioned
in this repo. The running API serves these exact values for the corresponding
wall-clock seconds — e.g. requesting the current tick returns the row whose
`timestamp` equals now, byte-for-byte.

Regenerate the exports with:

```bash
python3 generate_seconds_prices.py
```

Columns: `symbol,rate,high,low,open,close,timestamp,volume` (API responses use
the same values in the order `symbol,rate,high,low,open,close,volume,timestamp`).
The JSON export is gitignored (~92 MB; GitHub rejects files over 100 MB).

---

## 4. Run locally

```bash
pip install -r requirements.txt
gunicorn app:app --bind 0.0.0.0:8000
# or: python app.py
```

## 5. Deploy on Render

1. Push this repository to GitHub/GitLab.
2. In [Render](https://render.com): **New + → Blueprint** and connect the repo.
3. `render.yaml` is auto-detected and provisions a free web service
   (`gunicorn app:app` bound to `$PORT`, health check at `/health`).
4. Open `https://<your-service>.onrender.com/` to see the live tick.

## 6. Notes

- Feed epoch: ticks start at unix second `1788998400` (millisecond timestamp
  `1788998400000`) and end their first 7-day window at unix second
  `1789252643`. The `/` endpoint returns the tick for the current wall-clock
  second, so `timestamp` always equals "now" ± 1 s.
- Determinism is guaranteed twice over: identical requests return identical
  data, and within the 7-day window every price also equals the versioned CSV
  / JSON dataset exactly (verified byte-for-byte across sampled seconds).
