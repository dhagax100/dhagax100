"""Why do pullback entries shrink the stop but still lose expectancy?

Hypothesis: adverse selection. A limit order inside the confirmation leg only
fills when price comes back -- and the setups that never come back are the ones
that ran straight to target. If true, waiting for a better price systematically
discards the best trades, and the loss there outweighs the tighter stop.

Tests it directly: for every day, take the market entry AND check whether the
pullback limit would have filled, then compare the market-entry outcome of the
filled group against the never-filled group. Same signal, same day, same
target -- the only difference is whether price offered a retracement.
"""
import json
import os

import numpy as np
import pandas as pd

import entry_models as em
import optimize_strategy as opt

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR


def classify(ctx, retrace=0.5, expiry=60, stop_buffer=3.0, cost=1.0, min_range=25):
    """Market-entry outcome for a day, plus whether the pullback would fill."""
    long_ = ctx["side"] == "low"
    highs, lows, closes = ctx["highs"], ctx["lows"], ctx["closes"]
    level, opposite, arange = ctx["level"], ctx["opposite"], ctx["asian_range"]
    if arange / PIP < min_range or len(closes) < 30:
        return None

    rec = closes > level if long_ else closes < level
    if not rec.any():
        return None
    c = int(np.argmax(rec))
    if c >= len(closes) - 5:
        return None

    extreme = lows[:c + 1].min() if long_ else highs[:c + 1].max()
    leg_end = highs[:c + 1].max() if long_ else lows[:c + 1].min()
    stop = extreme - stop_buffer * PIP if long_ else extreme + stop_buffer * PIP
    entry = closes[c] + cost * PIP if long_ else closes[c] - cost * PIP
    risk = (entry - stop) if long_ else (stop - entry)
    reward = (opposite - entry) if long_ else (entry - opposite)
    if risk <= 0.5 * PIP or reward <= 0:
        return None

    h, l = highs[c + 1:], lows[c + 1:]
    if len(h) == 0:
        return None
    if long_:
        i_s = int(np.argmax(l <= stop)) if (l <= stop).any() else None
        i_t = int(np.argmax(h >= opposite)) if (h >= opposite).any() else None
    else:
        i_s = int(np.argmax(h >= stop)) if (h >= stop).any() else None
        i_t = int(np.argmax(l <= opposite)) if (l <= opposite).any() else None
    if i_s is not None and (i_t is None or i_s <= i_t):
        r, outcome = -1.0, "LOSS"
    elif i_t is not None:
        r, outcome = reward / risk, "WIN"
    else:
        r, outcome = 0.0, "BE"

    span = abs(leg_end - extreme)
    limit = (leg_end - retrace * span) if long_ else (leg_end + retrace * span)
    w = slice(c + 1, min(c + 1 + expiry, len(closes)))
    seg_lo, seg_hi = lows[w], highs[w]
    filled = bool((seg_lo <= limit).any()) if long_ else bool((seg_hi >= limit).any())

    return {"date": ctx["date"], "filled": filled, "market_outcome": outcome,
            "market_r": round(float(r), 3), "risk_pips": round(risk / PIP, 1)}


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    contexts = opt.build_contexts(raw)
    rows = [x for c in contexts for x in [classify(c)] if x is not None]
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)

    print(f"Days with a valid reclaim setup (Asian range >= 25 pips): {len(df)}\n")
    print("=== Market-entry outcome, split by whether a 50% pullback would have filled ===")
    tab = df.groupby("filled").agg(
        days=("market_r", "size"),
        win_rate=("market_outcome", lambda s: round((s == "WIN").mean() * 100, 1)),
        mean_r=("market_r", lambda s: round(s.mean(), 3)),
        total_r=("market_r", lambda s: round(s.sum(), 1)),
    )
    print(tab.to_string())

    filled = df[df["filled"]]
    never = df[~df["filled"]]
    print(f"\nSetups that NEVER pulled back: {len(never)} "
          f"({len(never)/len(df)*100:.1f}% of all setups)")
    print(f"  their market-entry win rate: {(never['market_outcome']=='WIN').mean()*100:.1f}%")
    print(f"  filled group's win rate:     {(filled['market_outcome']=='WIN').mean()*100:.1f}%")
    print(f"\nShare of ALL winning setups that never pulled back: "
          f"{(never['market_outcome']=='WIN').sum()}/{(df['market_outcome']=='WIN').sum()}"
          f" = {(never['market_outcome']=='WIN').sum()/max(1,(df['market_outcome']=='WIN').sum())*100:.1f}%")
    print(f"Total R sacrificed by skipping never-filled setups: "
          f"{never['market_r'].sum():+.1f}R of {df['market_r'].sum():+.1f}R total")

    out = {"n_days": int(len(df)),
           "filled": {"n": int(len(filled)),
                      "win_rate": round(float((filled["market_outcome"] == "WIN").mean() * 100), 1),
                      "mean_r": round(float(filled["market_r"].mean()), 3),
                      "total_r": round(float(filled["market_r"].sum()), 1)},
           "never_filled": {"n": int(len(never)),
                            "win_rate": round(float((never["market_outcome"] == "WIN").mean() * 100), 1),
                            "mean_r": round(float(never["market_r"].mean()), 3),
                            "total_r": round(float(never["market_r"].sum()), 1)}}
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "pullback_diagnosis.json"), "w") as f:
        json.dump(out, f, indent=2)
    df.to_csv(os.path.join(OUT_DIR, "pullback_diagnosis.csv"), index=False)
    print("\nSaved pullback_diagnosis.json")


if __name__ == "__main__":
    main()
