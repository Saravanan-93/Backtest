"""Chart images of valid and invalid setups.

    python generate_images.py [--tf M5] [--period 3M] [--pairs EURUSD]

Asks: pair, valid or invalid, which result / refusal stage, how many. Reads the CSVs
from pattern_recognition.py and the bars in data/. Images go to
output/images/<label>/<valid|invalid>/<pair>/<Buy|Sell>/<result or stage>/<tag>_<nn>.png
"""

import random
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                # noqa: E402
import pandas as pd                            # noqa: E402
from matplotlib.patches import Rectangle       # noqa: E402

import engine                                  # noqa: E402
import settings as cfg                         # noqa: E402
from strategy import rules                     # noqa: E402

BARS_BEFORE_P1, BARS_AFTER_EXIT, MAX_BARS = 15, 12, 260
BG, GRID, TEXT = "#ffffff", "#e6e9ee", "#2b2f36"
UP, DOWN = "#2e9e6b", "#d1495b"
BLUE, AMBER, PURPLE, TEAL = "#2f6fd1", "#d9962b", "#7a56c9", "#12908e"
SLATE, MILD_TEAL, MILD_AMBER, RSI_LINE = "#8da2c0", "#7fc4c1", "#dcc08a", "#5b6ee1"
TIME_COLUMNS = ["p1_time", "m_time", "p2_time", "entry_time", "exit_time", "be_time",
                "zero_time", "zero_start_time", "rsi_time"]

RUN = None      # set by main()
_bars = {}


def load_setups(kind):
    df = pd.read_csv(RUN.setups_dir / f"{kind}.csv")
    for col in df.columns.intersection(TIME_COLUMNS):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def bars_for(symbol):
    if symbol not in _bars:
        frame = engine.load_bars(RUN.data_path(symbol))
        frame["rsi"] = rules.rsi(frame["close"], 14)
        _bars[symbol] = frame
    return _bars[symbol]


def ask(question, options):
    """options: {name: accepted short answers}. Re-asks until one matches."""
    while True:
        answer = input(question + " ").strip().lower()
        for name, accepted in options.items():
            if answer in accepted or answer == name.lower():
                return name
        print("  please answer one of: " + ", ".join(options))


def ask_count(question, available):
    while True:
        answer = input(question + " ").strip().lower()
        if answer in ("all", "a"):
            return available
        if answer.isdigit() and int(answer) > 0:
            return min(int(answer), available)
        print("  please type a whole number (or 'all')")


def loc(frame, when):
    if when is None or pd.isna(when):
        return None
    try:
        return frame.index.get_loc(pd.Timestamp(when))
    except KeyError:
        return None


def title_for(row, kind):
    head = f"{row['symbol']} | {row['direction']}"
    if kind == "invalid":
        return f"{head} | {row['refused_at']} | Date : {row['p1_time']:%d-%m-%Y} | P1 time : {row['p1_time']:%H:%M}"
    opened, closed = row["entry_time"], row["exit_time"]
    if pd.isna(closed):
        close = "open"
    else:
        close = f"{closed:%H:%M}" if closed.date() == opened.date() else f"{closed:%d-%m-%Y %H:%M}"
    return (f"{head} | {row['result'].upper()} | Date : {opened:%d-%m-%Y} | "
            f"Open time : {opened:%H:%M} | Close time : {close}")


def style(ax):
    ax.set_facecolor(BG)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.tick_params(colors=TEXT, labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#b9c0cc")


def draw(row, kind, path):
    symbol = row["symbol"]
    frame = bars_for(symbol)
    pip = rules.pip_size(symbol)
    selling = row["direction"] == "SELL"

    p1, m, p2 = (loc(frame, row[k]) for k in ("p1_time", "m_time", "p2_time"))
    entry, exit_ = loc(frame, row.get("entry_time")), loc(frame, row.get("exit_time"))
    if p1 is None:
        return False
    if p2 is None and m is not None and not pd.isna(row.get("p2_price")):
        # P2 formed inside a bar that had not closed: find the bar that printed that price
        seg = frame.iloc[m:(entry if entry is not None else m + 60) + 1]
        printed = seg["high"] if selling else seg["low"]
        hit = printed[(printed - row["p2_price"]).abs() < pip * 0.05]
        p2 = frame.index.get_loc(hit.index[0]) if len(hit) else None

    last = max([x for x in (m, p2, entry, exit_) if x is not None] + [p1 + 40])
    if kind == "valid" and exit_ is not None:
        last = exit_
    zero, zero_start = loc(frame, row.get("zero_time")), loc(frame, row.get("zero_start_time"))
    first = max(0, p1 - BARS_BEFORE_P1)
    if zero is not None:
        first = max(0, min(first, (zero_start if zero_start is not None else zero) - 3))
    view = frame.iloc[first:min(len(frame), last + BARS_AFTER_EXIT + 1, first + MAX_BARS)]
    xs, off, right = range(len(view)), first, len(view) - 1

    fig, (ax, rx) = plt.subplots(2, 1, figsize=(13, 7.6), sharex=True,
                                 gridspec_kw={"height_ratios": [3.4, 1], "hspace": 0.06})
    fig.patch.set_facecolor(BG)
    style(ax)
    style(rx)

    for x, (o, h, l, c) in zip(xs, view[["open", "high", "low", "close"]].to_numpy()):
        color = UP if c >= o else DOWN
        ax.vlines(x, l, h, color=color, linewidth=1)
        ax.add_patch(Rectangle((x - 0.32, min(o, c)), 0.64, max(abs(c - o), pip * 0.05),
                               facecolor=color, edgecolor=color, linewidth=0.5))

    span = view["high"].max() - view["low"].min()
    y_lo, y_hi = view["low"].min() - span * 0.08, view["high"].max() + span * 0.08

    def hline(price, color, label, style="--", start=0):
        if not y_lo <= price <= y_hi:
            return
        ax.hlines(price, start, right, colors=color, linestyles=style, linewidth=1.1)
        if label:
            ax.text(right + 0.6, price, label, color=color, fontsize=8, va="center")

    def point(idx, price, label, color, above):
        if idx is None or pd.isna(price) or not 0 <= idx - off <= right:
            return
        ax.scatter([idx - off], [price], s=46, color=color, zorder=5, edgecolor="white", linewidth=0.8)
        ax.annotate(label, (idx - off, price), xytext=(0, 12 if above else -14),
                    textcoords="offset points", ha="center", fontsize=9,
                    fontweight="bold", color=color)

    def leg(a, price_a, b, price_b, color, style="-"):
        if None in (a, b) or pd.isna(price_a) or pd.isna(price_b):
            return
        if 0 <= a - off <= right and 0 <= b - off <= right:
            ax.plot([a - off, b - off], [price_a, price_b], color=color, linewidth=1.5,
                    linestyle=style, alpha=0.9, zorder=2)

    if zero is not None:
        leg(zero_start, row["zero_start_price"], zero, row["zero_price"], MILD_TEAL, ":")
        leg(zero, row["zero_price"], p1, row["p1_price"], SLATE)
    leg(p1, row["p1_price"], m, row["m_price"], SLATE)
    leg(m, row["m_price"], p2, row["p2_price"], SLATE)
    if kind == "valid":
        leg(p2, row["p2_price"], entry, row["entry_price"], MILD_AMBER)

    point(p1, row["p1_price"], "P1", PURPLE, selling)
    point(m, row["m_price"], "M", AMBER, not selling)
    point(p2, row["p2_price"], "P2", BLUE, selling)
    if zero is not None:
        point(zero, row["zero_price"], "0", TEAL, not selling)
        point(zero_start, row["zero_start_price"], "0 swing start", MILD_TEAL, selling)

    if not pd.isna(row["m_price"]):
        hline(row["m_price"], AMBER, "" if kind == "valid" else "M / trigger", ":",
              start=max(0, (m if m is not None else p1) - off))

    if kind == "valid":
        entry_price, tp, sl = row["entry_price"], row["tp"], row["p2_price"]
        ex = entry - off
        end = (exit_ - off) if exit_ is not None else right
        for level, color in ((sl, DOWN), (tp, UP)):
            ax.add_patch(Rectangle((ex, min(entry_price, level)), end - ex,
                                   abs(level - entry_price), facecolor=color, alpha=0.10, linewidth=0))
        hline(entry_price, BLUE, "entry", "-", start=ex)
        hline(sl, DOWN, "SL (P2)", start=ex)
        hline(tp, UP, "TP", start=ex)
        if not pd.isna(row["be_price"]):
            hline(row["be_price"], AMBER, "BE = 0 point" if zero is not None else "BE trigger",
                  (0, (1, 2)), start=ex)
        if exit_ is not None:
            ax.scatter([end], [row["exit_price"]], marker="X", s=90, color=TEXT, zorder=6,
                       edgecolor="white", linewidth=0.8)
            ax.annotate(row["result"], (end, row["exit_price"]), xytext=(0, -16 if selling else 14),
                        textcoords="offset points", ha="center", fontsize=9, fontweight="bold", color=TEXT)
        bx = loc(frame, row["be_time"])
        if bx is not None and 0 <= bx - off <= right:
            ax.axvline(bx - off, color=AMBER, linewidth=0.9, linestyle=":")
    elif not pd.isna(row["p2_price"]):
        hline(row["p2_price"], BLUE, "P2 / would-be stop", start=max(0, (p2 if p2 is not None else p1) - off))

    ax.set_title(title_for(row, kind), loc="left", fontsize=11, color=TEXT, fontweight="bold")
    ax.set_ylim(y_lo, y_hi)
    ax.set_xlim(-1, right + 8)
    ax.yaxis.tick_right()

    rx.plot(list(xs), view["rsi"].to_numpy(), color=RSI_LINE, linewidth=1.4)
    for level, color in ((70, DOWN), (30, UP), (50, "#9aa3b2")):
        rx.axhline(level, color=color, linewidth=0.9, linestyle=":" if level == 50 else "--")
    rx.set_ylim(0, 100)
    rx.set_yticks([30, 50, 70])
    rx.yaxis.tick_right()
    rx.set_ylabel("RSI 14", color=TEXT, fontsize=8)

    # P1's RSI can come from a candle up to 2 either side of P1 - mark the one that supplied it
    p1_at = p1
    for cand in (p1, p1 - 1, p1 + 1, p1 - 2, p1 + 2):
        if 0 <= cand < len(frame) and abs(frame["rsi"].iloc[cand] - row["p1_rsi"]) < 0.01:
            p1_at = cand
            break
    for idx, name, color, key in ((p1_at, "P1", PURPLE, "p1_rsi"), (m, "M", AMBER, "m_rsi"),
                                  (p2, "P2", BLUE, "p2_rsi")):
        if idx is None or pd.isna(row.get(key)) or not 0 <= idx - off <= right:
            continue
        rx.scatter([idx - off], [row[key]], s=34, color=color, zorder=5, edgecolor="white")
        rx.annotate(f"{name} {row[key]:.1f}", (idx - off, row[key]), xytext=(0, 8),
                    textcoords="offset points", ha="center", fontsize=8, color=color)

    ticks = list(range(0, len(view), max(1, len(view) // 10)))
    rx.set_xticks(ticks)
    rx.set_xticklabels([view.index[t].strftime("%m-%d %H:%M") for t in ticks], fontsize=8, color=TEXT)

    fig.subplots_adjust(left=0.04, right=0.93, top=0.92, bottom=0.07)
    fig.savefig(path, dpi=110, facecolor=BG)
    plt.close(fig)
    return True


def image_path(row, kind, group_sizes):
    """<run>/<kind>/<pair>/<Buy|Sell>/<result or stage>/<tag>_<nn>.png, numbered on from
    whatever is already in the folder so a second run never overwrites the first."""
    tag = row["refused_at"] if kind == "invalid" else row["result"]
    side = "Buy" if row["direction"] == "BUY" else "Sell"
    folder = RUN.images_dir / kind / row["symbol"] / side / tag
    folder.mkdir(parents=True, exist_ok=True)
    taken = [int(m.group(1)) for f in folder.glob(f"{tag}_*.png")
             if (m := re.fullmatch(rf"{re.escape(tag)}_(\d+)\.png", f.name))]
    width = max(2, len(str(group_sizes[(row["symbol"], row["direction"], tag)])))
    return folder / f"{tag}_{max(taken, default=0) + 1:0{width}d}.png"


def main():
    global RUN
    RUN = cfg.get_run()
    valid, invalid = load_setups("valid"), load_setups("invalid")
    pairs = sorted(set(valid["symbol"]) | set(invalid["symbol"]))
    print("Pairs in this run: " + ", ".join(pairs))
    pair = ask("Which pair (name, or Enter for all)?",
               {**{p: {p.lower()} for p in pairs}, "All": {"a", "all", ""}})
    kind = ask("Valid or Invalid?", {"valid": {"v"}, "invalid": {"i"}})
    df = valid if kind == "valid" else invalid
    if pair != "All":
        df = df[df["symbol"] == pair]

    if kind == "valid":
        choice = ask("Win, Loss or Breakeven?", {"Win": {"w"}, "Loss": {"l"}, "Breakeven": {"b", "be"}})
        pool, label, tag_col = df[df["result"] == choice], choice.lower(), "result"
    else:
        counts = df["refused_at"].value_counts()
        for stage, n in counts.items():
            print(f"   {stage:<22}{n:>8}")
        choice = ask("Which stage (name, or Enter for all)?",
                     {**{s: {s.lower()} for s in counts.index}, "All": {"a", "all", ""}})
        pool = df if choice == "All" else df[df["refused_at"] == choice]
        label, tag_col = ("refused" if choice == "All" else choice), "refused_at"

    if pool.empty:
        raise SystemExit(f"no {kind} {label} setups in this run")
    n = ask_count(f"{len(pool)} {label} setups available - how many images?", len(pool))
    picked = pool.sample(n=n, random_state=random.randrange(10**6)) if n < len(pool) else pool
    sizes = df.groupby(["symbol", "direction", tag_col]).size().to_dict()

    done = 0
    for _, row in picked.sort_values("p1_time").iterrows():
        path = image_path(row, kind, sizes)
        if draw(row, kind, path):
            done += 1
            print(f"  [{done}/{n}] {path.relative_to(RUN.images_dir)}")
    print(f"{done} image(s) written under {RUN.images_dir / kind}")


if __name__ == "__main__":
    main()
