"""Driver for the alternative-design study (run from this folder on the Vissim PC).

  py run_alternatives.py smoke   BASE and ACTUATED, 1 run each: checks COM, VAP switch, attributes
  py run_alternatives.py all     4 scenarios x 20 runs, then analysis (about 10-15 minutes)
"""
import subprocess
import sys

from common import HERE, log

PY = sys.executable


def run(*args):
    log("RUNNING " + " ".join(args), "alt_log.txt")
    p = subprocess.run([PY, *args], cwd=HERE)
    if p.returncode:
        log(f"FAILED ({p.returncode}) " + " ".join(args), "alt_log.txt")
        sys.exit(p.returncode)


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage == "smoke":
        run("run_alt.py", "--only", "BASE", "ACTUATED", "INCIDENT", "BIKE800", "--runs", "1", "--out", "alt_smoke")
        run("analyse_alt.py", "--out", "alt_smoke")
    else:
        run("run_alt.py", "--runs", "20", "--out", "alt")
        run("analyse_alt.py", "--out", "alt")
    log(f"ALL DONE ({stage})", "alt_log.txt")
