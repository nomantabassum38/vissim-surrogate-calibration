"""Alternative designs evaluated with the calibrated model (phase 2, OPT1).

  BASE      calibrated model, fixed-time controller (program 1), constant demand
  ACTUATED  same, signal controller switched to the provided VisVAP logic
            (Control_logic.vap + Signal_data.pua), lab section 5.2
  INCIDENT  same as BASE, but vehicle inputs A, C, E, G vary every 10 min (Table 1)
  BIKE800   same as BASE, bicycle demand 800 per direction (constant)

All scenarios: 600 s warm-up with the base demand + 1800 s evaluation (the three
10-minute intervals of Table 1), identical random seeds (common random numbers).
"""
import xml.etree.ElementTree as ET
from pathlib import Path

from build_net import build_inpx
from common import MODEL_DIR, WARMUP

# calibrated parameters (Calibration_phase2, validated configuration OPT1)
CALIBRATED = {
    "ax": 1.4859741261467647, "bx_add": 0.8191111883140614, "bx_mult": 1.3849912733672918,
    "sdf_sig": 0.31331974178646843, "v_kn": 51.728823400594955, "v_ks": 51.314985289702754,
    "v_se": 43.912240701123494, "v_sw": 52.406171587799406, "acc_scale": 1.0432438229629262,
    "dec_scale": 0.8944682022127057, "v_right": 10.127224983182654, "dec_right": 1.0905839276183946,
    "v_left": 29.940891326722387, "v_bike": 17.325688474144396,
}

# Table 1 of the lab instructions [veh/h] per 10-minute interval.
# A = Kungsgatan north (input 1), C = Slottsgatan east (input 4),
# E = Kungsgatan south (input 3), G = Slottsgatan west (input 11, named in the lab text).
INCIDENT = {"1": (670, 640, 670), "4": (160, 370, 190), "3": (1100, 920, 1100), "11": (100, 380, 150)}
BIKE_INPUTS = ("14", "15")
SCENARIOS = ["BASE", "ACTUATED", "INCIDENT", "BIKE800"]
VAP_FILE = MODEL_DIR / "Control_logic.vap"
PUA_FILE = MODEL_DIR / "Signal_data.pua"


def _evaluation(root):
    ev = root.find("evaluation")
    t0, t1 = str(WARMUP), str(WARMUP + 1800)
    for tag, interval in (("dataColl", "1800"), ("vehNetPerf", "1800"), ("queues", "600")):
        e = ev.find(tag)
        e.set("collectData", "true")
        e.set("fromTime", t0)
        e.set("toTime", t1)
        e.set("interval", interval)
    ev.find("nodeResults").set("collectData", "false")
    ev.find("nodeRawData").set("writeFile", "false")


def _incident(root):
    """Time intervals 0 / 600 / 1200 / 1800 s: warm-up at the base demand, then Table 1."""
    tis = [t for t in root.iter("timeIntervalSet") if t.get("no") == "VEHICLEINPUT"][0]
    box = tis.find("timeInts") if tis.find("timeInts") is not None else tis
    for t in list(box.iter("timeInterval")):
        box.remove(t)
    for s in (0, 600, 1200, 1800):
        ET.SubElement(box, "timeInterval", {"start": str(s)})
    for vi in root.iter("vehicleInput"):
        vols = list(vi.iter("timeIntervalVehVolume"))
        parent = [p for p in vi.iter() if vols[0] in list(p)][0]
        proto = dict(vols[0].attrib)
        base = proto["volume"]
        for v in vols:
            parent.remove(v)
        seq = (base,) + tuple(str(x) for x in INCIDENT[vi.get("no")]) if vi.get("no") in INCIDENT else None
        for k, s in enumerate((0, 600, 1200, 1800)):
            a = dict(proto)
            a["timeInt"] = f"1 {s * 1000}"
            if seq:
                a["cont"], a["volume"] = "false", seq[k]
            else:
                a["cont"] = "false" if k == 0 else "true"
            ET.SubElement(parent, "timeIntervalVehVolume", a)


def build_scenario(name, out_path):
    out_path = Path(out_path)
    build_inpx(CALIBRATED, out_path)
    tree = ET.parse(out_path)
    root = tree.getroot()
    _evaluation(root)
    if name == "INCIDENT":
        _incident(root)
    if name == "BIKE800":
        for vi in root.iter("vehicleInput"):
            if vi.get("no") in BIKE_INPUTS:
                for tv in vi.iter("timeIntervalVehVolume"):
                    tv.set("volume", "800")
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    return out_path


def set_actuated(vissim, log):
    """Switch controller 1 to the VisVAP logic through COM (as in lab section 5.2)."""
    sc = vissim.Net.SignalControllers.ItemByKey(1)
    log(f"    controller before: type={sc.AttValue('Type')} prog={sc.AttValue('ProgFile')}")
    for val in ("VAP", "Vap", 3):
        try:
            sc.SetAttValue("Type", val)
            break
        except Exception as e:  # noqa: BLE001
            log(f"    Type={val!r} rejected: {e}")
    sc.SetAttValue("SupplyFile1", str(VAP_FILE))
    sc.SetAttValue("SupplyFile2", str(PUA_FILE))
    try:
        sc.SetAttValue("Name", "Actuated controller")
    except Exception:  # noqa: BLE001
        pass
    log(f"    controller after:  type={sc.AttValue('Type')} prog={sc.AttValue('ProgFile')} "
        f"supply1={sc.AttValue('SupplyFile1')} supply2={sc.AttValue('SupplyFile2')}")
