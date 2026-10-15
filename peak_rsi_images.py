"""Charts of trades whose P1 RSI was read from a candle other than P1's own.

    python peak_rsi_images.py [count] [--tf M5] [--period 3M] [--pairs EURUSD]

The sample alternates M / W and cycles Win / Loss / Breakeven. Images go to
output/images/<label>/peak_rsi/<pair>/<Buy|Sell>/<result>/
"""

import sys

import pandas as pd

import generate_images as gi


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    sys.argv = [a for a in sys.argv if not a.isdigit()]
    gi.RUN = gi.cfg.get_run()
    valid = gi.load_setups("valid")
    peak = valid[valid["rsi_away"] != 0]
    print(f"{len(peak)} of {len(valid)} trades read P1's RSI from another candle")
    n = min(int(args[0]) if args else gi.ask_count("How many images?", len(peak)), len(peak))

    chosen, used = [], set()
    for i in range(n):
        kind, result = "MW"[i % 2], ("Win", "Loss", "Breakeven")[i % 3]
        pool = peak[(peak["pattern"].str[0] == kind) & (peak["result"] == result) & ~peak.index.isin(used)]
        row = (pool if len(pool) else peak[~peak.index.isin(used)]).sample(n=1, random_state=7 + i)
        used.update(row.index)
        chosen.append(row)
    if not chosen:
        return

    sizes = peak.groupby(["symbol", "direction", "result"]).size().to_dict()
    for _, row in pd.concat(chosen).sort_values("p1_time").iterrows():
        path = gi.image_path(row, "peak_rsi", sizes)
        if gi.draw(row, "valid", path):
            print("  " + str(path.relative_to(gi.RUN.images_dir)))


if __name__ == "__main__":
    main()
