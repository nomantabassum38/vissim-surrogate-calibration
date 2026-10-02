"""Run a design in Vissim through COM and collect per-replication results.

  py run_vissim.py --design design_screen.csv --runs 3 --out results_screen.csv
  py run_vissim.py --design design_validate.csv --runs 10 --seed 1001 --incr 7 --out results_validate.csv

Each configuration is written to C:/Temp/vissim_calibration_runs/<config>/Vissim_lab.inpx,
simulated, read and deleted. Results are appended per configuration, so an
interrupted batch resumes where it stopped. Unfinished vehicle inputs (Vissim .err)
go to <out>_unfinished.csv.
"""
import argparse
import csv
import re
import shutil
import time
import traceback
from pathlib import Path

import pandas as pd
import win32com.client as com

from build_net import build_inpx
from common import HERE, PARAM_NAMES, RUN_ROOT, log

FIELDS = ["config", "run", "loc", "speed_arith", "speed_harm", "acc", "vehs"]


def done_configs(out):
    if not out.exists():
        return set()
    return set(pd.read_csv(out, usecols=["config"]).config.astype(str))


def start_vissim():
    v = com.Dispatch("Vissim.Vissim")
    log(f"  Vissim started: {v.AttValue('Version')}")
    return v


def clear_runs(vissim):
    try:
        runs = vissim.Net.SimulationRuns
        for sr in list(runs.GetAll()):
            runs.RemoveSimulationRun(sr)
    except Exception:  # noqa: BLE001
        pass


def unfinished(config, folder):
    rows = []
    for err in folder.rglob("*.err"):
        txt = err.read_text(encoding="utf-8-sig", errors="ignore")
        for m in re.finditer(r"Vehicle input (\d+) could not be finished completely \(remain: (\d+)", txt):
            rows.append({"config": config, "file": err.name, "input": int(m.group(1)),
                         "remain": int(m.group(2))})
    return rows


def simulate(vissim, row, runs, seed, incr):
    cfg = row["config"]
    folder = RUN_ROOT / cfg
    shutil.rmtree(folder, ignore_errors=True)
    p = None if int(row.get("original", 0)) == 1 else {k: float(row[k]) for k in PARAM_NAMES}
    inpx = build_inpx(p, folder / "Vissim_lab.inpx")
    vissim.LoadNet(str(inpx), False)
    clear_runs(vissim)
    sim = vissim.Simulation
    sim.SetAttValue("NumRuns", runs)
    sim.SetAttValue("RandSeed", seed)
    sim.SetAttValue("RandSeedIncr", incr)
    sim.SetAttValue("UseMaxSimSpeed", True)
    try:
        vissim.Graphics.CurrentNetworkWindow.SetAttValue("QuickMode", 1)
    except Exception:  # noqa: BLE001
        pass
    vissim.SuspendUpdateGUI()
    try:
        sim.RunContinuous()
    finally:
        vissim.ResumeUpdateGUI()
    run_nos = sorted(int(sr.AttValue("No")) for sr in vissim.Net.SimulationRuns.GetAll())[-runs:]
    rows = []
    for dcm in vissim.Net.DataCollectionMeasurements.GetAll():
        loc = int(dcm.AttValue("No"))
        for i, rn in enumerate(run_nos, 1):
            sub = f"({rn},1,All)"
            rows.append({"config": cfg, "run": i, "loc": loc,
                         "speed_arith": dcm.AttValue("SpeedAvgArith" + sub),
                         "speed_harm": dcm.AttValue("SpeedAvgHarm" + sub),
                         "acc": dcm.AttValue("Acceleration" + sub),
                         "vehs": dcm.AttValue("Vehs" + sub)})
    return rows, unfinished(cfg, folder), folder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--incr", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int, help="run at most this many new configs")
    a = ap.parse_args()

    design = pd.read_csv(HERE / a.design)
    if a.only:
        design = design[design.config.isin(a.only)]
    out = HERE / a.out
    unf_out = out.with_name(out.stem + "_unfinished.csv")
    skip = done_configs(out)
    todo = [r for _, r in design.iterrows() if str(r["config"]) not in skip]
    if a.limit:
        todo = todo[:a.limit]
    log(f"run_vissim: {a.design}: {len(todo)} to run ({len(skip)} done), runs={a.runs}, "
        f"seed={a.seed}/{a.incr} -> {a.out}")
    if not todo:
        return
    RUN_ROOT.mkdir(parents=True, exist_ok=True)

    vissim = start_vissim()
    t_start, n_done = time.time(), 0
    for k, row in enumerate(todo, 1):
        t0 = time.time()
        for attempt in (1, 2):
            try:
                rows, unf, folder = simulate(vissim, row, a.runs, a.seed, a.incr)
                break
            except Exception:  # noqa: BLE001
                log(f"  {row['config']}: attempt {attempt} failed\n{traceback.format_exc()}")
                if attempt == 2:
                    raise
                try:
                    vissim = None
                    time.sleep(5)
                    vissim = start_vissim()
                except Exception:  # noqa: BLE001
                    log(traceback.format_exc())
                    raise
        new = not out.exists()
        with open(out, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)
        if unf or not unf_out.exists():
            with open(unf_out, "a", newline="") as fu:
                wu = csv.DictWriter(fu, fieldnames=["config", "file", "input", "remain"])
                if fu.tell() == 0:
                    wu.writeheader()
                wu.writerows(unf)
        shutil.rmtree(folder, ignore_errors=True)
        n_done += 1
        per = (time.time() - t_start) / n_done
        log(f"  [{k}/{len(todo)}] {row['config']} done in {time.time() - t0:.0f} s, "
            f"unfinished vehicles {sum(u['remain'] for u in unf)}, "
            f"ETA {per * (len(todo) - k) / 60:.0f} min")
    log("run_vissim: finished")


if __name__ == "__main__":
    main()
