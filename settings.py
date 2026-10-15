"""Backtest settings - edit here between runs. The live config.py is never touched.

Run options can also be given on the command line, e.g.:
    python pattern_recognition.py --tf M5 --period 3M --pairs EURUSD GBPUSD
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

BT_DIR = Path(__file__).resolve().parent
ROOT = BT_DIR.parent                       # project root: config/ and strategy/ live here
if str(ROOT) not in sys.path:
    sys.path.append(ROOT.as_posix())

import config  # noqa: E402

# What to run -> data/<TIMEFRAME>/<PAIR>_<TIMEFRAME>_<PERIOD>.csv
PAIRS = ["EURUSD"]
TIMEFRAME = "M15"
PERIOD = "3M"
RUN_TAG = ""            # optional suffix for the report / images name

# Rules that differ from the live config
RR = 3.0
BLACKOUT_START = "23:00"
BLACKOUT_END = "01:30"
MIN_BARS_P1_TO_M = 4
P1_RSI_LANE = True
P1_RSI_PEAK = True
P1_RSI_REACH = 2
ZERO_SWING = True
ZERO_LOOKBACK_BARS = 60
BE_TRIGGER_R = 1.5      # breakeven distance in R, used only when ZERO_SWING is off

DATA_DIR = BT_DIR / "data"
OUT_DIR = BT_DIR / "output"
PIP_SNAPSHOT = OUT_DIR / "pip_values.json"


def rule_settings():
    """config.RULES plus the backtest overrides above."""
    return {**config.RULES,
            "reward_ratio": RR, "min_bars_p1_to_m": MIN_BARS_P1_TO_M,
            "p1_rsi_lane": P1_RSI_LANE, "p1_rsi_peak": P1_RSI_PEAK,
            "p1_rsi_reach": P1_RSI_REACH, "zero_swing": ZERO_SWING,
            "zero_lookback_bars": ZERO_LOOKBACK_BARS}


@dataclass
class Run:
    pairs: list
    timeframe: str
    period: str

    @property
    def label(self):
        """EURUSD_M15_3M, or MULTI_PAIRS_M15_3M for several pairs."""
        who = self.pairs[0] if len(self.pairs) == 1 else "MULTI_PAIRS"
        return "_".join(filter(None, [who, self.timeframe, self.period, RUN_TAG]))

    @property
    def setups_dir(self):
        return OUT_DIR / "setups" / self.label

    @property
    def report_path(self):
        return OUT_DIR / "reports" / f"{self.label}.xlsx"

    @property
    def images_dir(self):
        return OUT_DIR / "images" / self.label

    def data_path(self, pair):
        return DATA_DIR / self.timeframe / f"{pair}_{self.timeframe}_{self.period}.csv"


def get_run():
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", nargs="+", default=PAIRS)
    p.add_argument("--tf", default=TIMEFRAME)
    p.add_argument("--period", default=PERIOD)
    a = p.parse_args()
    return Run([x.upper() for x in a.pairs], a.tf.upper(), a.period.upper())
