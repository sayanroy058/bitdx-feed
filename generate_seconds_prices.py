import json
import math
import random

SYMBOL = "BITDXUSDB"
BASE_TS = 1788647842262  # ms, matches the sample
DAY_SECONDS = 86400
DAYS = 7

random.seed(BASE_TS)

# Chained daily targets: day 1 goes DAY_POINTS[0] -> DAY_POINTS[1],
# day 2 DAY_POINTS[1] -> DAY_POINTS[2], etc. Edit freely.
# day1 1->5, day2 5->3, day3 3->5, day4 5->9, day5 9->2, day6 2->8, day7 8->5
DAY_POINTS = [1.0, 5.0, 3.0, 5.0, 9.0, 2.0, 8.0, 5.0]
assert len(DAY_POINTS) == DAYS + 1, "need DAYS+1 chained targets"

N = DAYS * DAY_SECONDS

# ~8% daily volatility, per-second std dev for the noise around each day's path
SIGMA = 0.08 / math.sqrt(DAY_SECONDS)


def bridge_day(start, end, n):
    """Return n log-price offsets: a Brownian bridge from start to end price
    (in log space), so each day opens at `start` and closes exactly at `end`."""
    # random walk W with W[0] = 0
    w = [0.0]
    for _ in range(n):
        w.append(w[-1] + SIGMA * random.gauss(0, 1))
    l0, l1 = math.log(start), math.log(end)
    offsets = []
    for i in range(1, n + 1):
        frac = i / n
        # bridge: pull W_i toward 0 at the day's end so we land exactly on `end`
        bridge = w[i] - frac * w[n]
        offsets.append(l0 + (l1 - l0) * frac + bridge)
    return offsets


entries = []
prev_close = DAY_POINTS[0]

for d in range(DAYS):
    offsets = bridge_day(DAY_POINTS[d], DAY_POINTS[d + 1], DAY_SECONDS)
    for i, logp in enumerate(offsets, start=1):
        ts = BASE_TS + (d * DAY_SECONDS + i) * 1000
        open_ = prev_close
        close = math.exp(logp)
        high = max(open_, close) * (1 + random.uniform(0.0002, 0.002))
        low = min(open_, close) * (1 - random.uniform(0.0002, 0.002))
        volume = round(random.uniform(0.05, 0.35), 2)

        entries.append(
            {
                "symbol": SYMBOL,
                "rate": f"{close:.5f}",
                "high": f"{high:.5f}",
                "low": f"{low:.5f}",
                "open": f"{open_:.5f}",
                "close": f"{close:.5f}",
                "timestamp": str(ts),
                "volume": f"{volume:.2f}",
            }
        )
        prev_close = close

with open("next_7_days_seconds.json", "w") as f:
    json.dump(entries, f, separators=(",", ":"))

columns = ["symbol", "rate", "high", "low", "open", "close", "timestamp", "volume"]
with open("next_7_days_seconds.csv", "w") as f:
    f.write(",".join(columns) + "\n")
    for e in entries:
        f.write(",".join(e[c] for c in columns) + "\n")

print(f"Wrote {len(entries)} entries (json + csv)")
print(f"last close: {entries[-1]['close']}")