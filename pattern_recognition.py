"""Find every W/M setup - the ones that traded and the ones refused - and save them as CSVs.

    python pattern_recognition.py [--tf M5] [--period 3M] [--pairs EURUSD GBPUSD]

Writes output/setups/<label>/valid.csv and invalid.csv.
"""

import json
from concurrent.futures import ProcessPoolExecutor
from functools import partial

import pandas as pd

import engine
import settings as cfg

VALID_COLUMNS = [
    "id", "symbol", "pattern", "direction",
    "p1_time", "p1_price", "p1_rsi", "rsi_away", "rsi_time",
    "m_time", "m_price", "m_rsi", "p2_time", "p2_price", "p2_rsi", "fib",
    "zero_start_time", "zero_start_price", "zero_time", "zero_price",
    "zero_swing_pips", "p1_to_m_pips",
    "entry_time", "entry_price", "sl", "tp", "be_price", "be_time",
    "risk_pips", "reward_pips", "lot",
    "exit_time", "exit_price", "result", "pnl_pips", "pnl_cash", "r",
]
INVALID_COLUMNS = [
    "symbol", "pattern", "direction",
    "p1_time", "p1_price", "p1_rsi", "rsi_away", "rsi_time",
    "m_time", "m_price", "m_rsi", "p2_time", "p2_price", "p2_rsi",
    "fib_level", "risk_pips", "refused_at", "reason",
]


def pip_value(pair, last_close):
    """USD per pip per standard lot: the broker snapshot if it has the pair, else derived
    for USD-quoted and USD-based pairs. Crosses need the snapshot (bot.pip_calculator)."""
    if cfg.PIP_SNAPSHOT.exists():
        value = json.loads(cfg.PIP_SNAPSHOT.read_text())["pip_value_per_std_lot_usd"].get(pair)
        if value is not None:
            return value
    raw = (0.01 if pair.endswith("JPY") else 0.0001) * 100_000
    if pair.endswith("USD"):
        return raw
    if pair.startswith("USD"):
        return raw / last_close
    raise SystemExit(f"{pair}: no pip value - run `python -m bot.pip_calculator --save` first")


def run_pair(pair, run):
    path = run.data_path(pair)
    if not path.exists():
        print(f"{pair}: skipped, no file {path}")
        return [], []
    frame = engine.load_bars(path)
    value = pip_value(pair, float(frame["close"].iloc[-1]))
    trades, refused = engine.simulate(frame, pair, cfg.rule_settings(), value)
    s = engine.summarise(trades)
    print(f"{pair}: {len(frame)} bars, {s['trades']} trades "
          f"({s['wins']} win / {s['losses']} loss / {s['breakeven']} breakeven), "
          f"{len(refused)} refused")
    return trades, refused


def main():
    run = cfg.get_run()
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(partial(run_pair, run=run), run.pairs))
    trades = [t for r in results for t in r[0]]
    refused = [x for r in results for x in r[1]]

    run.setups_dir.mkdir(parents=True, exist_ok=True)
    for name, rows, cols in (("valid", trades, VALID_COLUMNS), ("invalid", refused, INVALID_COLUMNS)):
        out = run.setups_dir / f"{name}.csv"
        pd.DataFrame(rows, columns=cols).to_csv(out, index=False)
        print(f"written: {out}")


if __name__ == "__main__":
    main()
