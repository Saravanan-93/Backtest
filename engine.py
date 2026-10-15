"""Bar-by-bar simulation of the live W/M rules over MT5 CSV exports.

Pattern, RSI, fib and entry rules come straight from strategy/rules.py. Position
bookkeeping and exits are re-implemented here because bot/ imports MetaTrader5.
MT5 exports OHLC only, so inside one bar price is assumed to run open -> low -> high ->
close for a bullish bar and open -> high -> low -> close for a bearish one.
"""

import pandas as pd

import settings as cfg
from settings import config
from strategy import rules

SETUP_FIELDS = ["p1_time", "p1_price", "p1_rsi", "m_time", "m_price", "m_rsi",
                "p2_time", "p2_price", "p2_rsi", "fib_level", "risk_pips"]


def load_bars(path):
    """MT5 export (tab-separated <DATE> <TIME> <OPEN> ...) -> OHLC + spread by timestamp."""
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]
    df.index = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    if "spread" not in df:
        df["spread"] = 0.0
    cols = ["open", "high", "low", "close", "spread"]
    return df[cols].apply(pd.to_numeric, errors="coerce").dropna().sort_index()


def bar_path(o, h, l, c):
    return [o, l, h, c] if c >= o else [o, h, l, c]


def minutes(text):
    h, _, m = text.partition(":")
    return int(h) * 60 + int(m or 0)


def lot_for(risk_pips, pip_value):
    if risk_pips <= 0:
        return 0.01
    cash = config.RISK_CAPITAL * config.RISK_PERCENT
    return round(max(round(cash / (risk_pips * pip_value) / 0.01) * 0.01, 0.01), 2)


def same_pattern_at_risk(open_trades, pattern):
    kind = pattern.split("_")[0]
    for t in open_trades:
        if t["pattern"].split("_")[0] == kind and not t["be_hit"]:
            return f"a {kind} is already open ({t['id']}) and has not reached breakeven yet"
    return None


def duplicate_stop(open_trades, direction, sl, point):
    for t in open_trades:
        if t["direction"] == direction and abs(t["sl"] - sl) <= point:
            return f"{direction} already open ({t['id']}) with the same stop {t['sl']:.5f}"
    return None


def position_cap(open_trades):
    if config.MAX_POSITIONS_PER_PAIR and len(open_trades) >= config.MAX_POSITIONS_PER_PAIR:
        return f"at the {config.MAX_POSITIONS_PER_PAIR} per-pair cap"
    if config.MAX_TOTAL_POSITIONS and len(open_trades) >= config.MAX_TOTAL_POSITIONS:
        return f"at the {config.MAX_TOTAL_POSITIONS} total-position cap"
    at_risk = sum(not t["be_hit"] for t in open_trades)
    if config.MAX_RISK_SLOTS and at_risk >= config.MAX_RISK_SLOTS:
        return f"at the {config.MAX_RISK_SLOTS} risk-slot cap"
    return None


def simulate(frame, symbol, settings, pip_value):
    """Returns (trades, refused) for one pair."""
    pip = rules.pip_size(symbol)
    point = pip / 10.0
    b_start, b_end = minutes(cfg.BLACKOUT_START), minutes(cfg.BLACKOUT_END)

    times = frame.index
    opens, highs, lows, closes = (frame[c].to_numpy() for c in ("open", "high", "low", "close"))
    spreads = frame["spread"].to_numpy()

    open_trades, trades, refused = [], [], []
    logged, traded = set(), set()

    def refuse(src, stage, reason):
        row = {"symbol": symbol, "pattern": src["pattern"], "direction": src["direction"],
               "refused_at": stage, "reason": reason}
        row.update({k: src.get(k) for k in SETUP_FIELDS})
        refused.append(row)

    def open_trade(s, entry, when):
        is_buy = s["direction"] == "BUY"
        reward = s["reward_pips"] * pip
        if settings.get("zero_swing"):
            be = s["zero_price"]
        else:
            trigger = max(s["risk_pips"] * pip * cfg.BE_TRIGGER_R,
                          config.MIN_BE_TRIGGER_PIPS * pip)
            be = entry + trigger if is_buy else entry - trigger
        cash = config.RISK_CAPITAL * config.RISK_PERCENT
        t = {"id": f"{symbol[:3]}-{len(trades) + 1:03d}", "symbol": symbol,
             "pattern": s["pattern"], "direction": s["direction"],
             "p1_time": s["p1_time"], "p1_price": s["p1_price"], "p1_rsi": s["p1_rsi"],
             "m_time": s["m_time"], "m_price": s["m_price"], "m_rsi": s["m_rsi"],
             "p2_time": s["p2_time"], "p2_price": s["p2_price"], "p2_rsi": s["p2_rsi"],
             "fib": s["fib_level"],
             "zero_time": s.get("zero_time"), "zero_price": s.get("zero_price"),
             "zero_swing_pips": s.get("zero_swing_pips"),
             "zero_start_time": s.get("zero_start_time"),
             "zero_start_price": s.get("zero_start_price"),
             "rsi_away": s.get("rsi_away"), "rsi_time": s.get("rsi_time"),
             "p1_to_m_pips": s.get("p1_to_m_pips"),
             "entry_time": when, "entry_price": entry, "sl": s["stop"],
             "tp": entry + reward if is_buy else entry - reward,
             "be_price": be, "be_hit": False, "be_time": None,
             "risk_pips": s["risk_pips"], "reward_pips": s["reward_pips"],
             "lot": lot_for(s["risk_pips"], pip_value), "risk_cash": cash,
             "exit_time": None, "exit_price": None, "result": "Open",
             "pnl_pips": None, "pnl_cash": None, "r": None}
        open_trades.append(t)
        trades.append(t)
        return t

    def close_trade(t, price, result, when):
        move = price - t["entry_price"] if t["direction"] == "BUY" else t["entry_price"] - price
        pips = move / pip
        t.update(exit_time=when, exit_price=price, result=result, pnl_pips=round(pips, 2),
                 pnl_cash=round(pips * t["lot"] * pip_value, 2))
        t["r"] = round(t["pnl_cash"] / t["risk_cash"], 3) if t["risk_cash"] else None
        open_trades.remove(t)

    def resolve_segment(t, start, end, when):
        """One straight price move, checked against the trade's levels in the order
        price crosses them. True once the trade has closed."""
        if start == end:
            return False
        up = end > start
        lo, hi = sorted((start, end))
        levels = [("TP", t["tp"]), ("SL", t["sl"])]
        if not t["be_hit"]:
            levels.append(("BE", t["be_price"]))
        hits = sorted((lv for lv in levels if lo <= lv[1] <= hi),
                      key=lambda lv: lv[1], reverse=not up)
        for name, level in hits:
            if name == "BE":
                t.update(be_hit=True, sl=t["entry_price"], be_time=when)
            elif name == "TP":
                close_trade(t, level, "Win", when)
                return True
            else:
                be = abs(t["sl"] - t["entry_price"]) <= point
                close_trade(t, level, "Breakeven" if be else "Loss", when)
                return True
        return False

    def crossed(direction, trigger, start, end):
        if direction == "SELL":
            return end < start and end <= trigger <= start
        return end > start and start <= trigger <= end

    for t in range(settings["rsi_period"] + 5, len(frame) - 1):
        found, refusals = rules.find_setups(frame.iloc[:t + 1], symbol, settings)

        for row in refusals:
            key = (row["direction"], row["p1_time"], row["refused_at"])
            if key not in logged:
                logged.add(key)
                refuse(row, row["refused_at"], row["reason"])

        candidates = [s for s in found if (s["direction"], s["p1_time"]) not in traded]
        when = times[t + 1]
        o, h, l, c = opens[t + 1], highs[t + 1], lows[t + 1], closes[t + 1]
        spread = spreads[t + 1] * point

        for trade in list(open_trades):
            path = bar_path(o, h, l, c)
            for a, b in zip(path, path[1:]):
                if resolve_segment(trade, a, b, when):
                    break

        dead = set()
        path = bar_path(o, h, l, c)
        for a, b in zip(path, path[1:]):
            for s in candidates:
                key = (s["direction"], s["p1_time"])
                if key in dead or key in traded:
                    continue

                killed = rules.deepen(s, b, pip, settings)
                if killed:
                    dead.add(key)
                    refuse(s, *killed[:2])
                    continue
                if not crossed(s["direction"], s["trigger"], a, b):
                    continue

                dead.add(key)
                too_tight = rules.entry_refusal(s, pip, settings)
                if too_tight:
                    refuse(s, *too_tight[:2])
                    continue
                if rules.blackout_covers(when, b_start, b_end):
                    refuse(s, "BLACKOUT", "trigger crossed inside the blackout window")
                    continue
                cap = position_cap(open_trades)
                if cap:
                    refuse(s, "ALREADY_TRADED", cap)
                    continue
                clash = same_pattern_at_risk(open_trades, s["pattern"])
                if clash:
                    refuse(s, "SAME_PATTERN_AT_RISK", clash)
                    continue
                clash = duplicate_stop(open_trades, s["direction"], s["stop"], point)
                if clash:
                    refuse(s, "SAME_STOP", clash)
                    continue

                traded.add(key)
                entry = s["trigger"] + spread if s["direction"] == "BUY" else s["trigger"]
                resolve_segment(open_trade(s, entry, when), entry, b, when)

    tag_rsi_source(refused, frame, settings)
    return trades, refused


def tag_rsi_source(rows, frame, settings):
    """rsi_away: 0 if P1's RSI is its own candle's, 1-2 if it came from a candle before P1."""
    series = rules.rsi(frame["close"], settings["rsi_period"]).round(2).to_numpy()
    for row in rows:
        row["rsi_away"], row["rsi_time"] = 0, None
        if row.get("p1_time") is None or row.get("p1_rsi") is None:
            continue
        at = frame.index.get_indexer([pd.Timestamp(row["p1_time"])])[0]
        for away in (0, 1, 2):
            if at >= away and abs(series[at - away] - row["p1_rsi"]) < 0.005:
                row["rsi_away"] = away
                row["rsi_time"] = None if away == 0 else str(frame.index[at - away])
                break


def summarise(rows):
    closed = [r for r in rows if r["result"] != "Open"]
    count = lambda name: sum(r["result"] == name for r in closed)
    return {"trades": len(rows), "wins": count("Win"), "losses": count("Loss"),
            "breakeven": count("Breakeven"),
            "net_cash": sum(r["pnl_cash"] for r in closed),
            "net_pips": sum(r["pnl_pips"] for r in closed)}
