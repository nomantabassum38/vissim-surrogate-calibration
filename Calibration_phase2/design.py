"""Experimental designs (CSV files read by run_vissim.py).

  py design.py screen  [--n 160] [--seed 2026]    -> design_screen.csv
  py design.py refine  [--n 40]  [--seed 7]       -> design_refine.csv  (box around analysis optimum)

A design row with original=1 is the untouched course model (only warm-up added).
"""
import argparse
import json

import numpy as np
import pandas as pd
from scipy.stats import qmc

from common import BASE, HERE, HI, LO, PARAM_NAMES


def lhs(n, lo, hi, seed):
    u = qmc.LatinHypercube(d=len(lo), seed=seed, optimization="random-cd").random(n)
    return qmc.scale(u, lo, hi)


def write(rows, name):
    df = pd.DataFrame(rows)
    df.to_csv(HERE / name, index=False)
    print(f"wrote {len(df)} configurations to {name}")


def screen(n, seed):
    rows = [{"config": "REF_ORIGINAL", "original": 1, **BASE},
            {"config": "REF_BASEPARAMS", "original": 0, **BASE}]
    for i, x in enumerate(lhs(n, LO, HI, seed)):
        rows.append({"config": f"LHS_{i + 1:03d}", "original": 0, **dict(zip(PARAM_NAMES, x))})
    write(rows, "design_screen.csv")


def refine(n, seed, frac=0.25):
    """LHS in a box of +-frac*range around the current surrogate optimum."""
    opt = json.loads((HERE / "surrogate_optimum.json").read_text())
    centre = np.array([opt[k] for k in PARAM_NAMES])
    half = frac * (HI - LO)
    lo, hi = np.maximum(LO, centre - half), np.minimum(HI, centre + half)
    rows = [{"config": "REF_OPT_PREV", "original": 0, **dict(zip(PARAM_NAMES, centre))}]
    for i, x in enumerate(lhs(n, lo, hi, seed)):
        rows.append({"config": f"REF_{i + 1:03d}", "original": 0, **dict(zip(PARAM_NAMES, x))})
    write(rows, "design_refine.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["screen", "refine"])
    ap.add_argument("--n", type=int)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    if a.kind == "screen":
        screen(a.n or 160, a.seed or 2026)
    else:
        refine(a.n or 40, a.seed or 7)
