"""One-command driver (run on the Vissim PC from the Calibration folder).

  py run_pipeline.py smoke     original model, 1 run: checks COM + timing (~1 min)
  py run_pipeline.py screen    160-point LHS x 3 runs + 2 references, then analyse train
  py run_pipeline.py refine    40-point LHS around the surrogate optimum x 3 runs, retrain
  py run_pipeline.py validate  candidates x 10 runs with new seeds, final report
  py run_pipeline.py all       screen -> refine -> validate

Every step resumes where it stopped. Progress: pipeline_log.txt, pipeline_status.txt.
"""
import subprocess
import sys
import time

from common import HERE, log

PY = sys.executable


def status(msg):
    (HERE / "pipeline_status.txt").write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n", encoding="utf-8")
    log(msg)


def run(*args):
    status("RUNNING " + " ".join(map(str, args)))
    p = subprocess.run([PY, *map(str, args)], cwd=HERE)
    if p.returncode:
        status(f"FAILED ({p.returncode}) " + " ".join(map(str, args)))
        sys.exit(p.returncode)


def smoke():
    if not (HERE / "design_screen.csv").exists():
        run("design.py", "screen")
    run("run_vissim.py", "--design", "design_screen.csv", "--only", "REF_ORIGINAL", "LHS_001",
        "--runs", "1", "--out", "results_smoke.csv")
    import pandas as pd
    print(pd.read_csv(HERE / "results_smoke.csv").pivot_table(index="loc", columns="config",
                                                                 values=["speed_arith", "vehs"]).round(2))
    status("DONE smoke")


def screen():
    if not (HERE / "design_screen.csv").exists():
        run("design.py", "screen")
    run("run_vissim.py", "--design", "design_screen.csv", "--runs", "3", "--out", "results_screen.csv")
    run("analyse.py", "train")
    status("DONE screen")


def refine():
    if not (HERE / "design_refine.csv").exists():
        run("design.py", "refine")
    run("run_vissim.py", "--design", "design_refine.csv", "--runs", "3", "--out", "results_refine.csv")
    run("analyse.py", "train")
    status("DONE refine")


def validate():
    run("run_vissim.py", "--design", "design_validate.csv", "--runs", "10", "--seed", "1001",
        "--incr", "7", "--out", "results_validate.csv")
    run("analyse.py", "validate")
    status("DONE validate")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    for f in {"smoke": [smoke], "screen": [screen], "refine": [refine], "validate": [validate],
              "all": [screen, refine, validate]}[stage]:
        f()
    status(f"ALL DONE ({stage})")
