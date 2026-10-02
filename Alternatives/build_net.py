"""Write a calibration variant of the course model as a stand-alone .inpx.

build_inpx(p, out)      applies parameter vector p (dict, see common.PARAMS)
build_inpx(None, out)   original model, only the evaluation settings changed

Always applied: 600 s warm-up + 1800 s data collection, fixed-time program 1,
standalone network (no scenario management). Demand and routes are untouched.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import copy

from common import BASE_INPX, EVAL_LEN, FIXED, WARMUP

RIGHT_RSA = ["1", "4", "5", "9"]          # connectors 10000, 10004, 10007, 10008
LEFT_RSA = ["6", "7", "8", "10"]          # connectors 10005, 10006, 10009, 10012
# vehicle input -> (composition, distribution, parameter)
INPUT_SPEED = {"3": ("1", 901, "v_kn"),     # Kungsgatan northbound (link 2)
               "1": ("4", 907, "v_ks"),     # Kungsgatan southbound (link 4)
               "4": ("5", 902, "v_se"),     # Slottsgatan east, westbound (link 5)
               "11": ("6", 908, "v_sw")}    # Slottsgatan west, eastbound (link 11)
VRU_LINKS = {"9", "10", "13", "14", "15", "16", "17", "18",      # footpaths
             "19", "20", "21", "22", "10014", "10015"}          # cycle tracks


def _find(root, tag, no):
    for e in root.iter(tag):
        if e.get("no") == str(no):
            return e
    raise KeyError(f"{tag} {no} not found")


def _set_distribution(root, no, name, lo, hi):
    parent = root.find("desSpeedDistributions")
    for d in parent.findall("desSpeedDistribution"):
        if d.get("no") == str(no):
            parent.remove(d)
    d = ET.SubElement(parent, "desSpeedDistribution", {"name": name, "no": str(no)})
    pts = ET.SubElement(d, "speedDistrDatPts")
    ET.SubElement(pts, "speedDistributionDataPoint", {"fx": "0", "x": f"{lo:.2f}"})
    ET.SubElement(pts, "speedDistributionDataPoint", {"fx": "1", "x": f"{hi:.2f}"})


def _scale_function(root, tag, no, s):
    fn = _find(root, tag, no)
    for pt in fn.iter():
        if pt.get("x") is None or pt is fn:
            continue
        for k in ("y", "yMin", "yMax"):
            if pt.get(k) is not None:
                pt.set(k, f"{float(pt.get(k)) * s:.4f}")


def _set_rsa(root, no, distr, decel):
    rsa = _find(root, "reducedSpeedArea", no)
    box = rsa.find("vehClassSpeedRed")
    if box is None:
        box = ET.SubElement(rsa, "vehClassSpeedRed")
    for c in list(box):
        box.remove(c)
    for vc in ("10", "20"):                     # cars and HGV
        ET.SubElement(box, "vehClassSpeedReduction",
                      {"decel": f"{decel:.3f}", "desSpeedDistr": str(distr), "vehClass": vc})


def build_inpx(p, out_path, warmup=WARMUP, eval_len=EVAL_LEN):
    tree = ET.parse(BASE_INPX)
    root = tree.getroot()
    root.find("netPara").set("underScenMngm", "false")

    if p is not None:
        db = _find(root, "drivingBehavior", 1)
        db.set("w74ax", f"{p['ax']:.3f}")
        db.set("w74bxAdd", f"{p['bx_add']:.3f}")
        db.set("w74bxMult", f"{p['bx_mult']:.3f}")
        db.set("safDistFactSig", f"{p['sdf_sig']:.3f}")

        # desired speeds per approach: one car/HGV composition per vehicle input
        comps = root.find("vehicleCompositions")
        if not any(c.get("no") == "6" for c in comps.findall("vehicleComposition")):
            c6 = copy.deepcopy(_find(root, "vehicleComposition", 5))
            c6.set("no", "6")
            c6.set("name", "CarSlottsgatanWest")
            comps.append(c6)
        for inp, (comp, dno, key) in INPUT_SPEED.items():
            _set_distribution(root, dno, f"Cal {key}", p[key] - 5, p[key] + 5)
            for rf in _find(root, "vehicleComposition", comp).iter("vehicleCompositionRelativeFlow"):
                rf.set("desSpeedDistr", str(dno))
            for tv in _find(root, "vehicleInput", inp).iter("timeIntervalVehVolume"):
                tv.set("vehComp", comp)

        for fn in ("1", "2"):                      # Car, HGV
            _scale_function(root, "desAccelerationFunction", fn, p["acc_scale"])
            _scale_function(root, "desDecelerationFunction", fn, p["dec_scale"])

        _set_distribution(root, 903, "Cal right turn", max(p["v_right"] - 2.5, 3.0), p["v_right"] + 2.5)
        for no in RIGHT_RSA:
            _set_rsa(root, no, 903, p["dec_right"])
        _set_distribution(root, 904, "Cal left turn", max(p["v_left"] - 2.5, 3.0), p["v_left"] + 2.5)
        for no in LEFT_RSA:
            _set_rsa(root, no, 904, 2.0)

        _set_distribution(root, 905, "Cal bike", p["v_bike"] - 1.5, p["v_bike"] + 1.5)
        v_e = p["v_bike"] + p.get("dv_ebike", FIXED["dv_ebike"])
        _set_distribution(root, 906, "Cal e-bike", v_e - 2.5, v_e + 2.5)
        for rf in _find(root, "vehicleComposition", 3).iter("vehicleCompositionRelativeFlow"):
            rf.set("desSpeedDistr", "905" if rf.get("vehType") == "610" else "906")

    sim = root.find("simulation")
    sim.set("simPeriod", str(warmup + eval_len))
    dc = root.find("evaluation").find("dataColl")
    dc.set("collectData", "true")
    dc.set("fromTime", str(warmup))
    dc.set("toTime", str(warmup + eval_len))
    dc.set("interval", str(eval_len))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    return out_path
