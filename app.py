"""Live BITDXUSDB data feed API (Render-ready).

Two interfaces, one deterministic generator:

1. Plain feed (JSON or CSV):
     GET /              -> current tick (JSON default, ?format=csv / Accept: text/csv)
     GET /tick?ts=<ms>  -> tick for a specific millisecond timestamp
     GET /health        -> liveness check

2. TradingView UDF datafeed (for the charting library):
     GET /api/datafeed/config
     GET /api/datafeed/time
     GET /api/datafeed/symbols?symbol=BITDXUSDB
     GET /api/datafeed/search?query=...&limit=...
     GET /api/datafeed/history?symbol=...&from=<unix s>&to=<unix s>&resolution=1S|5S|...|1D

Ticks are generated deterministically per wall-clock second, in the same style
as the static 7-day dataset (day-by-day zigzag targets bridged by a seeded
random walk). No state, no database; identical requests get identical answers.
Past the 7-day table, daily targets keep extending with seeded up/down swings.
"""

import math
import os
import random
import time

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

SYMBOL = "BITDXUSDB"
# Milliseconds of tick index 0 (matches the generated 7-day dataset).
BASE_TS = 1788647842262
BASE_SEC = BASE_TS // 1000
SECOND_MS = 1000
DAY_SECONDS = 86400

# Chained daily targets for the first 7 days: day 0: 1 -> 5, ..., day 6: 8 -> 5.
# end_of_day(d) is DAY_POINTS[d + 1].
DAY_POINTS = [1.0, 5.0, 3.0, 5.0, 9.0, 2.0, 8.0, 5.0]

# ~8% daily volatility expressed as per-second noise for the intraday walk.
SIGMA = 0.08 / math.sqrt(DAY_SECONDS)

# Palette of percentage swings used to extend the chart past day 7.
UP_MOVES = [0.6, 0.9, 1.3, 2.0, 3.0]
DOWN_MOVES = [-0.4, -0.55, -0.7, -0.8]

# Output caps for history requests (keeps each request fast).
MAX_SCAN_SECONDS = 150_000   # most recent seconds scanned per history request
MAX_BARS = 5_000             # bars returned per history request

# TradingView UDF resolution -> length in seconds.
RES_SECONDS = {
    "1S": 1,
    "5S": 5,
    "15S": 15,
    "30S": 30,
    "1": 60,
    "5": 300,
    "15": 900,
    "30": 1800,
    "60": 3600,
    "240": 14400,
    "1D": 86400,
}

# _ext_targets[k] == price at the end of day k; starts from DAY_POINTS and
# grows lazily as wall-clock time moves past the initial 7 days.
_ext_targets = list(DAY_POINTS)

# day index -> list of 86401 log-prices (per second boundary), cached.
_bridge_cache = {}
MAX_CACHED_DAYS = 3


# ---------------------------------------------------------------- generation

def end_of_day(day):
    """Price at the end of `day` (== start of day+1), deterministic forever."""
    while len(_ext_targets) - 1 <= day:
        k = len(_ext_targets) - 1  # next day to define
        rng = random.Random(424_242 + k)
        moves = UP_MOVES if rng.random() < 0.5 else DOWN_MOVES
        _ext_targets.append(_ext_targets[-1] * (1.0 + moves[rng.randrange(len(moves))]))
    return _ext_targets[day + 1]


def day_start(day):
    return DAY_POINTS[0] if day == 0 else end_of_day(day - 1)


def day_offsets(day):
    """Brownian-bridge log-price offsets for one day, start..end, reproducible."""
    cached = _bridge_cache.get(day)
    if cached is not None:
        return cached

    l0, l1 = math.log(day_start(day)), math.log(end_of_day(day))
    rng = random.Random(777 + day)
    n = DAY_SECONDS
    w = [0.0]
    for _ in range(n):
        w.append(w[-1] + SIGMA * rng.gauss(0, 1))
    w_n = w[n]

    offsets = []
    for k in range(n + 1):
        frac = k / n
        offsets.append(l0 + (l1 - l0) * frac + w[k] - frac * w_n)
    _bridge_cache[day] = offsets

    while len(_bridge_cache) > MAX_CACHED_DAYS:
        del _bridge_cache[min(_bridge_cache)]
    return offsets


def rnd01(j, salt):
    """Cheap deterministic pseudo-random in [0, 1) for a tick index `j`."""
    x = math.sin(j * 12.9898 + salt * 78.233) * 43758.5453
    return x - math.floor(x)


def second_ohlc(j):
    """OHLCV floats of the tick with 0-based index `j` (deterministic)."""
    day, pos = divmod(j, DAY_SECONDS)
    pos += 1  # 1..86400 boundary index inside the day
    offsets = day_offsets(day)
    open_ = math.exp(offsets[pos - 1])
    close = math.exp(offsets[pos])
    high = max(open_, close) * (1 + 0.0002 + 0.0018 * rnd01(j, 1))
    low = min(open_, close) * (1 - 0.0002 - 0.0018 * rnd01(j, 2))
    volume = 0.05 + 0.30 * rnd01(j, 3)
    return open_, high, low, close, volume


def tick_at(ts_ms):
    """Full tick dict for the second containing ts_ms (plain feed format)."""
    elapsed = max(1, (ts_ms - BASE_TS) // SECOND_MS)
    j = elapsed - 1
    open_, high, low, close, volume = second_ohlc(j)
    return {
        "symbol": SYMBOL,
        "rate": f"{close:.5f}",
        "high": f"{high:.5f}",
        "low": f"{low:.5f}",
        "open": f"{open_:.5f}",
        "close": f"{close:.5f}",
        "timestamp": str(BASE_TS + elapsed * SECOND_MS),
        "volume": f"{volume:.2f}",
    }


# ------------------------------------------------------------------ plain feed

CSV_FIELDS = ["symbol", "rate", "high", "low", "open", "close", "timestamp", "volume"]


def tick_to_csv(tick):
    return ",".join(CSV_FIELDS) + "\n" + ",".join(tick[f] for f in CSV_FIELDS) + "\n"


def wanted_format():
    fmt = request.args.get("format", "").lower()
    if fmt == "csv" or "text/csv" in request.headers.get("Accept", ""):
        return "csv"
    return "json"


def respond(tick):
    if wanted_format() == "csv":
        return Response(tick_to_csv(tick), mimetype="text/csv")
    return jsonify(tick)


@app.get("/")
def current_tick():
    return respond(tick_at(int(time.time() * 1000)))


@app.get("/tick")
def query_tick():
    ts = request.args.get("ts", type=int)
    if ts is None:
        ts = int(time.time() * 1000)
    return respond(tick_at(ts))


@app.get("/health")
def health():
    return jsonify({"status": "ok", "symbol": SYMBOL})


# ------------------------------------------- TradingView UDF datafeed endpoints

@app.get("/api/datafeed/config")
def datafeed_config():
    return jsonify(
        {
            "supports_search": True,
            "supports_group_request": False,
            "supports_marks": False,
            "supports_timescale_marks": False,
            "supports_time": True,
            "supports_time_scale": True,
            "supported_resolutions": list(RES_SECONDS.keys()),
        }
    )


@app.get("/api/datafeed/time")
def datafeed_time():
    return jsonify({"serverTime": int(time.time())})


@app.get("/api/datafeed/symbols")
def datafeed_symbols():
    symbol = request.args.get("symbol", SYMBOL)
    return jsonify(
        {
            "symbol": symbol,
            "ticker": symbol,
            "full_name": symbol,
            "description": f"{symbol} (live synthetic feed)",
            "exchange": "BITDX",
            "type": "crypto",
            "session": "24x7",
            "timezone": "UTC",
            "minmov": 1,
            "pricescale": 100000,
            "tick_size": 0.00001,
            "has_intraday": True,
            "has_seconds": True,
            "has_daily": True,
            "has_weekly_and_monthly": False,
            "supported_resolutions": list(RES_SECONDS.keys()),
            "volume_precision": 2,
            "data_status": "streaming",
        }
    )


@app.get("/api/datafeed/search")
def datafeed_search():
    q = (request.args.get("query") or request.args.get("q") or "").strip().lower()
    limit = request.args.get("limit", type=int) or 30
    matches = q in SYMBOL.lower() or q == ""
    return jsonify(
        [
            {
                "symbol": SYMBOL,
                "ticker": SYMBOL,
                "full_name": SYMBOL,
                "description": f"{SYMBOL} (live synthetic feed)",
                "exchange": "BITDX",
                "type": "crypto",
            }
        ][:limit]
        if matches
        else []
    )


def _history_subday(from_j, to_j, bucket_sec):
    """Aggregate ticks j in [from_j, to_j] into OHLCV buckets."""
    buckets = {}  # bucket start (unix s) -> [open, high, low, close, volume]
    for j in range(from_j, to_j + 1):
        tick_end_sec = BASE_SEC + j + 1
        bucket = (tick_end_sec // bucket_sec) * bucket_sec
        open_, high, low, close, volume = second_ohlc(j)
        agg = buckets.get(bucket)
        if agg is None:
            buckets[bucket] = [open_, high, low, close, volume]
        else:
            if high > agg[1]:
                agg[1] = high
            if low < agg[2]:
                agg[2] = low
            agg[3] = close
            agg[4] += volume

    times = sorted(buckets)[-MAX_BARS:]
    if not times:
        return {"s": "no_data"}
    out = {"s": "ok", "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for t in times:
        o, h, l, c, v = buckets[t]
        out["t"].append(t)
        out["o"].append(round(o, 5))
        out["h"].append(round(h, 5))
        out["l"].append(round(l, 5))
        out["c"].append(round(c, 5))
        out["v"].append(round(v, 2))
    return out


def _history_daily(d0, d1):
    """One candle per generated day (aligned to the feed's day boundaries)."""
    times, os_, hs, ls, cs, vs = [], [], [], [], [], []
    for d in range(d0, d1 + 1):
        if len(times) >= MAX_BARS:
            break
        open_ = day_start(d)
        close = end_of_day(d)
        # small deterministic wick + volume around the day's open/close
        hi = max(open_, close) * (1 + 0.005 + 0.01 * rnd01(d + 10**6, 5))
        lo = min(open_, close) * (1 - 0.005 - 0.01 * rnd01(d + 10**6, 6))
        vol = 17280.0 * (0.90 + 0.20 * rnd01(d + 10**6, 7))
        times.append(BASE_SEC + d * DAY_SECONDS)
        os_.append(round(open_, 5))
        hs.append(round(hi, 5))
        ls.append(round(lo, 5))
        cs.append(round(close, 5))
        vs.append(round(vol, 2))
    if not times:
        return {"s": "no_data"}
    return {"s": "ok", "t": times, "o": os_, "h": hs, "l": ls, "c": cs, "v": vs}


@app.get("/api/datafeed/history")
def datafeed_history():
    res = request.args.get("resolution", "1")
    bucket_sec = RES_SECONDS.get(res)
    if bucket_sec is None:
        return jsonify({"s": "error", "errmsg": f"unsupported resolution: {res}"}), 400

    now = int(time.time())
    to = int(request.args.get("to", now))
    from_ = request.args.get("from")
    countback = request.args.get("countback", type=int)
    if from_ is None and countback:
        from_ = to - countback * bucket_sec
    if from_ is None:
        from_ = to - 1000 * bucket_sec
    from_ = max(int(from_), BASE_SEC)
    to = max(int(to), from_)

    if res == "1D":
        d0 = (from_ - BASE_SEC - 1) // DAY_SECONDS
        d1 = (to - BASE_SEC - 1) // DAY_SECONDS
        if d1 < d0:
            return jsonify({"s": "no_data", "nextTime": BASE_SEC})
        return jsonify(_history_daily(d0, d1))

    # tick j ends at unix second BASE_SEC + j + 1
    j_start = max(0, from_ - BASE_SEC - 1)
    j_end = to - BASE_SEC - 1
    if j_end < j_start:
        return jsonify({"s": "no_data", "nextTime": BASE_SEC + 1})
    if j_end - j_start + 1 > MAX_SCAN_SECONDS:
        j_start = j_end - MAX_SCAN_SECONDS + 1
    return jsonify(_history_subday(j_start, j_end, bucket_sec))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
