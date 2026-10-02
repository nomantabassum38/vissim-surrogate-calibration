"""Shared definitions for the automated calibration of the Kungsgatan-Slottsgatan
Vissim model (Infra informatics PhD course, Vissim lab).

Folder layout (everything stays inside "II-sim Vissim lab (2026)"):
  II-sim Vissim lab (2026)/
    II-sim Vissim lab (2025)/Vissim_lab.inpx   original course model (never modified)
    Calibration/                                this code, designs, results, reports
Locations L1..L12 are Vissim data-collection measurements 1..12, in the same
order as the columns of traffic_measurements.xlsx.
"""
from pathlib import Path

import numpy as np
import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODEL_DIR = ROOT / "II-sim Vissim lab (2025)"
BASE_INPX = MODEL_DIR / "Vissim_lab.inpx"
FIELD_XLSX = MODEL_DIR / "traffic_measurements.xlsx"
RUN_ROOT = Path("C:/Temp/vissim_calibration_phase3")     # staging area on the Vissim PC

LOC_NAMES = {
    1: "Slottsgatan East in", 2: "Slottsgatan West out", 3: "Kungsgatan South out",
    4: "Kungsgatan South in", 5: "Slottsgatan East out", 6: "Kungsgatan North out",
    7: "Kungsgatan North in", 8: "Slottsgatan West in",
    9: "Kungsgatan South in (bike)", 10: "Kungsgatan North out (bike)",
    11: "Kungsgatan North in (bike)", 12: "Kungsgatan South out (bike)",
}
MOTOR = list(range(1, 9))
BIKE = list(range(9, 13))
LOCS = MOTOR + BIKE
# hourly flow past each DCP = vehicle input x static route share
EXPECTED_FLOW = {1: 120, 2: 142, 3: 702, 4: 957, 5: 305, 6: 1001, 7: 561, 8: 90,
                 9: 100, 10: 100, 11: 100, 12: 100}

WARMUP, EVAL_LEN = 600, 1800          # s; data collection 600..2400 s
GEH_MAX = 5.0
SERVED_MIN = 0.95                     # simulated / expected flow at L4 (near capacity)
SERVED_REL = 0.97
# objective weights: errors are expressed in units of the typical (median) day-to-day
# field standard deviation, so speeds and accelerations count equally
W_ACC = 1.0                     # ... or, when available: >= 97 % of the original model's L4 flow

# ---------------------------------------------------------------------------
# Calibration parameters: (low, high, original-model value, description)
# Every speed parameter is the centre c of a uniform desired-speed distribution
# U(c - w, c + w) written into the network as a real Vissim distribution.
# ---------------------------------------------------------------------------
PARAMS = {
    "ax":        (0.8, 3.0, 2.0,  "W74 average standstill distance [m] (driving behaviour 1)"),
    "bx_add":    (0.3, 4.0, 2.0,  "W74 additive part of safety distance"),
    "bx_mult":   (0.8, 5.0, 3.0,  "W74 multiplicative part of safety distance"),
    "sdf_sig":   (0.2, 1.0, 0.6,  "Safety-distance reduction factor near stop lines"),
    "v_kn":      (44.0, 62.0, 53.0, "Desired speed Kungsgatan northbound input (comp. 1), U(c-5,c+5) [km/h]"),
    "v_ks":      (44.0, 62.0, 53.0, "Desired speed Kungsgatan southbound input (comp. 4), U(c-5,c+5) [km/h]"),
    "v_se":      (25.0, 60.0, 53.0, "Desired speed Slottsgatan east input (comp. 5), U(c-5,c+5) [km/h]"),
    "v_sw":      (25.0, 60.0, 53.0, "Desired speed Slottsgatan west input (comp. 6), U(c-5,c+5) [km/h]"),
    "acc_lo":    (0.6, 1.6, 1.0,  "Scale on desired acceleration (Car/HGV) at speeds <= 20 km/h"),
    "acc_hi":    (0.4, 1.4, 1.0,  "Scale on desired acceleration (Car/HGV) at speeds >= 50 km/h (linear blend between)"),
    "dec_scale": (0.3, 1.6, 1.0,  "Scale on desired-deceleration functions Car/HGV"),
    "v_rk":      (6.0, 30.0, 22.5, "Right-turn speed from Kungsgatan (RSA 1, 5), U(c-2.5,c+2.5) [km/h]"),
    "v_rs":      (6.0, 30.0, 22.5, "Right-turn speed from Slottsgatan (RSA 4, 9), U(c-2.5,c+2.5) [km/h]"),
    "dec_right": (0.3, 3.5, 2.0,  "Deceleration towards right-turn reduced-speed areas [m/s2]"),
    "v_left":    (10.0, 36.0, 27.5, "Left-turn reduced-speed areas 6,7,8,10, U(c-2.5,c+2.5) [km/h]"),
    "v_bike":    (12.0, 20.0, 13.5, "Conventional bike desired speed, U(c-1.5,c+1.5) [km/h]"),
}
FIXED = {"dv_ebike": 4.0}       # e-bike = bike + 4 km/h (not identifiable from mean speeds)
PARAM_NAMES = list(PARAMS)
LO = np.array([PARAMS[k][0] for k in PARAM_NAMES])
HI = np.array([PARAMS[k][1] for k in PARAM_NAMES])
BASE = {k: PARAMS[k][2] for k in PARAM_NAMES}


def load_field():
    """Per-day field values: speeds (10 x 12) and motorized accelerations (10 x 8)."""
    ws = openpyxl.load_workbook(FIELD_XLSX, data_only=True)["Calibration"]
    rows = [r for r in ws.iter_rows(values_only=True)]
    days = [r for r in rows if isinstance(r[0], (int, float)) and not isinstance(r[0], bool)
            and 1 <= r[0] <= 10 and all(isinstance(x, (int, float)) for x in r[1:21])][:10]
    arr = np.array([[float(x) for x in r[1:21]] for r in days])
    speed = np.hstack([arr[:, 0:8], arr[:, 16:20]])
    acc = arr[:, 8:16]
    return speed, acc


def geh(model_hourly, count_hourly):
    m, c = np.asarray(model_hourly, float), np.asarray(count_hourly, float)
    return np.sqrt(2 * (m - c) ** 2 / np.maximum(m + c, 1e-9))


def log(msg, name="pipeline_log.txt"):
    import time
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    with open(HERE / name, "a", encoding="utf-8") as f:
        f.write(line + "\n")
