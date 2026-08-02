"""What does the measured edge mean for a prop-firm challenge?

Bootstraps the walk-forward OUT-OF-SAMPLE trades (the only ones taken with
parameters chosen without seeing them) and simulates a typical evaluation:
reach the profit target before breaching max total drawdown, within a time
limit. Repeated many times at several risk-per-trade settings.

Bootstrapping resamples the real R-multiples with replacement, so the
simulated sequences keep the strategy's actual win rate and payoff shape
while varying the ORDER trades arrive in -- which is exactly the thing that
decides whether a real account survives its bad run early or late.

The edge itself is never inflated here: no trade outcome is invented, the
distribution is only re-ordered.
"""
import json
import os

import numpy as np
import pandas as pd

OUT_DIR = os.path.join(os.path.dirname(__file__), "derived")

PROFIT_TARGET = 0.08   # +8% to pass
MAX_DRAWDOWN = 0.10    # -10% from peak fails (trailing)
DAILY_LOSS_LIMIT = 0.05
TRADES_PER_MONTH = 10  # measured: ~357 OOS trades / ~36 months
MONTH_LIMIT = 6        # generous evaluation window
N_SIMS = 20000
SEED = 7


def simulate(r_samples, risk_frac, rng, max_trades):
    equity, peak = 1.0, 1.0
    for i in range(max_trades):
        r = r_samples[rng.integers(len(r_samples))]
        equity *= (1.0 + risk_frac * r)
        peak = max(peak, equity)
        if equity <= peak * (1.0 - MAX_DRAWDOWN):
            return "FAIL_DD", i + 1, equity
        if equity >= 1.0 + PROFIT_TARGET:
            return "PASS", i + 1, equity
    return "TIMEOUT", max_trades, equity


def main():
    wf = pd.read_csv(os.path.join(OUT_DIR, "walkforward_trades.csv"))
    r = wf["r_multiple"].values.astype(float)
    print(f"Bootstrapping {len(r)} walk-forward out-of-sample trades")
    print(f"  win rate {(wf['outcome']=='WIN').mean()*100:.1f}% | mean {r.mean():+.3f}R | "
          f"median {np.median(r):+.3f}R | best {r.max():+.2f}R | worst {r.min():+.2f}R\n")

    rng = np.random.default_rng(SEED)
    max_trades = TRADES_PER_MONTH * MONTH_LIMIT
    rows = []
    for risk_pct in [0.25, 0.5, 0.75, 1.0, 2.0]:
        outcomes = [simulate(r, risk_pct / 100.0, rng, max_trades) for _ in range(N_SIMS)]
        res = [o[0] for o in outcomes]
        finals = np.array([o[2] for o in outcomes])
        passes = res.count("PASS")
        rows.append({
            "risk_per_trade_pct": risk_pct,
            "pass_rate_pct": round(passes / N_SIMS * 100, 1),
            "fail_drawdown_pct": round(res.count("FAIL_DD") / N_SIMS * 100, 1),
            "timeout_pct": round(res.count("TIMEOUT") / N_SIMS * 100, 1),
            "median_final_equity": round(float(np.median(finals)), 4),
            "median_trades_to_resolve": int(np.median([o[1] for o in outcomes])),
        })
    df = pd.DataFrame(rows)
    print(f"=== Prop challenge simulation ({N_SIMS:,} runs each) ===")
    print(f"target +{PROFIT_TARGET:.0%} | max trailing DD -{MAX_DRAWDOWN:.0%} | "
          f"{TRADES_PER_MONTH} trades/mo | {MONTH_LIMIT}-month limit")
    print(df.to_string(index=False))

    # Expected annual return at each risk level, ignoring pass/fail gates
    print("\n=== Expected 12-month equity path (no challenge gates), same bootstrap ===")
    ann = []
    for risk_pct in [0.25, 0.5, 0.75, 1.0]:
        finals = []
        for _ in range(5000):
            eq = 1.0
            for _ in range(TRADES_PER_MONTH * 12):
                eq *= (1.0 + (risk_pct / 100.0) * r[rng.integers(len(r))])
            finals.append(eq)
        finals = np.array(finals)
        ann.append({"risk_per_trade_pct": risk_pct,
                    "median_return_pct": round(float(np.median(finals) - 1) * 100, 1),
                    "p10_return_pct": round(float(np.percentile(finals, 10) - 1) * 100, 1),
                    "p90_return_pct": round(float(np.percentile(finals, 90) - 1) * 100, 1),
                    "prob_negative_year_pct": round(float((finals < 1).mean() * 100), 1)})
    ann_df = pd.DataFrame(ann)
    print(ann_df.to_string(index=False))

    with open(os.path.join(OUT_DIR, "monte_carlo_prop.json"), "w") as f:
        json.dump({"n_oos_trades": int(len(r)), "mean_r": round(float(r.mean()), 4),
                   "win_rate": round(float((wf["outcome"] == "WIN").mean() * 100), 1),
                   "params": {"profit_target": PROFIT_TARGET, "max_drawdown": MAX_DRAWDOWN,
                              "trades_per_month": TRADES_PER_MONTH, "month_limit": MONTH_LIMIT,
                              "n_sims": N_SIMS},
                   "challenge": rows, "annual": ann}, f, indent=2)
    print("\nSaved monte_carlo_prop.json")


if __name__ == "__main__":
    main()
