"""Simulate the alternative-design scenarios and collect results per replication.

  py run_alt.py --runs 20                 all scenarios
  py run_alt.py --only ACTUATED --runs 1 --out alt_smoke   quick check

Writes <out>_dcm.csv (speeds/accelerations/counts at L1..L12),
<out>_net.csv (vehicle network performance per vehicle class),
<out>_queue.csv (queue counters per 10-min interval). Resumable per scenario.
"""
import argparse
import csv
import shutil
import time
import traceback

import pandas as pd
import win32com.client as com

from common import HERE, RUN_ROOT, log
from scenarios import SCENARIOS, build_scenario, set_actuated

CLASSES = {"All": "All", "Car": "10", "HGV": "20", "Bike": "60", "Ped": "50"}
NET_ATTRS = ["DelayAvg", "SpeedAvg", "StopsAvg", "DelayStopAvg", "TravTmTot", "DistTot",
             "VehAct", "VehArr", "DelayLatent", "DemandLatent"]
Q_ATTRS = ["QLen", "QLenMax", "QStops"]


def att(obj, name):
    try:
        v = obj.AttValue(name)
        return None if v is None else float(v)
    except Exception:  # noqa: BLE001
        return None


def append(path, rows, fields):
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def simulate(vissim, scen, runs, seed, incr):
    folder = RUN_ROOT / scen
    shutil.rmtree(folder, ignore_errors=True)
    inpx = build_scenario(scen, folder / "Vissim_lab.inpx")
    vissim.LoadNet(str(inpx), False)
    if scen == "ACTUATED":
        set_actuated(vissim, log)
    try:
        for sr in list(vissim.Net.SimulationRuns.GetAll()):
            vissim.Net.SimulationRuns.RemoveSimulationRun(sr)
    except Exception:  # noqa: BLE001
        pass
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

    dcm, net, que = [], [], []
    for m in vissim.Net.DataCollectionMeasurements.GetAll():
        loc = int(m.AttValue("No"))
        for i, rn in enumerate(run_nos, 1):
            s = f"({rn},1,All)"
            dcm.append({"scenario": scen, "run": i, "loc": loc, "speed": att(m, "SpeedAvgArith" + s),
                        "acc": att(m, "Acceleration" + s), "vehs": att(m, "Vehs" + s)})
    vnp = vissim.Net.VehicleNetworkPerformanceMeasurement
    for i, rn in enumerate(run_nos, 1):
        for cname, ckey in CLASSES.items():
            r = {"scenario": scen, "run": i, "class": cname}
            for a in NET_ATTRS:
                r[a] = att(vnp, f"{a}({rn},1,{ckey})")
            net.append(r)
    for q in vissim.Net.QueueCounters.GetAll():
        qn, name = int(q.AttValue("No")), q.AttValue("Name")
        for i, rn in enumerate(run_nos, 1):
            for ti in (1, 2, 3):
                r = {"scenario": scen, "run": i, "counter": qn, "name": name, "interval": ti}
                for a in Q_ATTRS:
                    r[a] = att(q, f"{a}({rn},{ti})")
                que.append(r)
    return dcm, net, que, folder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--incr", type=int, default=1)
    ap.add_argument("--out", default="alt")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    scen = a.only or SCENARIOS
    f_dcm, f_net, f_q = (HERE / f"{a.out}_{k}.csv" for k in ("dcm", "net", "queue"))
    done = set(pd.read_csv(f_dcm).scenario) if f_dcm.exists() else set()
    todo = [s for s in scen if s not in done]
    log(f"run_alt: {todo} x {a.runs} runs (seed {a.seed}/{a.incr}) -> {a.out}_*.csv", "alt_log.txt")
    if not todo:
        return
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    vissim = com.Dispatch("Vissim.Vissim")
    for s in todo:
        t0 = time.time()
        try:
            dcm, net, que, folder = simulate(vissim, s, a.runs, a.seed, a.incr)
        except Exception:  # noqa: BLE001
            log(f"  {s} FAILED\n{traceback.format_exc()}", "alt_log.txt")
            raise
        append(f_dcm, dcm, ["scenario", "run", "loc", "speed", "acc", "vehs"])
        append(f_net, net, ["scenario", "run", "class"] + NET_ATTRS)
        append(f_q, que, ["scenario", "run", "counter", "name", "interval"] + Q_ATTRS)
        shutil.rmtree(folder, ignore_errors=True)
        missing = [k for k in NET_ATTRS if all(r[k] is None for r in net)]
        log(f"  {s} done in {time.time() - t0:.0f} s; network attributes not available: {missing}", "alt_log.txt")
    log("run_alt: finished", "alt_log.txt")


if __name__ == "__main__":
    main()
