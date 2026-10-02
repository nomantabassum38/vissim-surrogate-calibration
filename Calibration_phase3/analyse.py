"""Analysis of the batch simulations.

  py analyse.py train      summarise all calibration runs (screen + refine), sensitivity
                           analysis, GP surrogates, constrained optimisation,
                           writes design_validate.csv and surrogate_optimum.json
  py analyse.py validate   final validation with independent seeds: t-tests (speeds and
                           accelerations), GEH, served demand, replications needed,
                           odd/even-day hold-out; writes report_validation.txt/.tex

Objective : RMSE between simulated and field mean speed over L1..L12
Constraints: GEH <= 5 at L1..L8 and served demand at L4 >= 95 % (a margin is used
             on the surrogate); accelerations are never used in the objective.
"""
import json
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import qmc
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.model_selection import KFold

from common import (BASE, BIKE, EXPECTED_FLOW, GEH_MAX, HERE, HI, LO, LOC_NAMES, LOCS, MOTOR,
                    PARAM_NAMES, PARAMS, SERVED_MIN, SERVED_REL, W_ACC, EVAL_LEN, geh, load_field, log)

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
EPS_REPL = 0.05
SERVED_THR = SERVED_MIN     # served-demand threshold at L4 (fraction of expected flow)
_fs, _fa = load_field()
SD_V = _fs.std(0, ddof=1)                    # field day-to-day s.d. per location (speeds)
SD_A = _fa.std(0, ddof=1)                    # ... and accelerations
SV, SA = float(np.median(SD_V)), float(np.median(SD_A))
Z0 = 0.75     # |standardized error| below which the course t-test (10 runs vs 10 days) passes


def zloss(z):
    """Hinge-squared loss: ~free inside the t-test acceptance band, quadratic outside."""
    z = np.abs(z)
    return np.maximum(0.0, z - Z0) ** 2 + 0.05 * z ** 2
SPEEDS = [f"v{i}" for i in LOCS]
FLOWS = [f"q{i}" for i in MOTOR]
ACCS = [f"a{i}" for i in MOTOR]


# ---------------------------------------------------------------------------
def summarise(df):
    fs, fa = load_field()
    ybar, sy, ny = fs.mean(0), fs.std(0, ddof=1), fs.shape[0]
    abar, sa = fa.mean(0), fa.std(0, ddof=1)
    rows = []
    for cfg, g in df.groupby("config"):
        sp = g.pivot(index="run", columns="loc", values="speed_arith")[LOCS].astype(float)
        ac = g.pivot(index="run", columns="loc", values="acc")[MOTOR].astype(float)
        vh = g.pivot(index="run", columns="loc", values="vehs")[MOTOR].astype(float)
        nx = len(sp)
        xbar, sx = sp.mean().values, sp.std(ddof=1).values if nx > 1 else np.zeros(12)
        d = xbar - ybar
        tcrit = stats.t.ppf(0.975, ny + nx - 2)
        sp2 = ((ny - 1) * sy ** 2 + (nx - 1) * sx ** 2) / (ny + nx - 2)
        t_speed = d / np.sqrt(sp2 * (1 / ny + 1 / nx))
        axbar = ac.mean().values
        asx = ac.std(ddof=1).values if nx > 1 else np.zeros(8)
        sp2a = ((ny - 1) * sa ** 2 + (nx - 1) * asx ** 2) / (ny + nx - 2)
        t_acc = (axbar - abar) / np.sqrt(sp2a * (1 / ny + 1 / nx))
        flow = vh.mean().values * 3600 / EVAL_LEN
        g_eh = geh(flow, [EXPECTED_FLOW[i] for i in MOTOR])
        n_req = (stats.t.ppf(0.975, max(nx - 1, 1)) * sx / (EPS_REPL * xbar)) ** 2
        r = {"config": cfg, "n_runs": nx,
             "RMSE_all": np.sqrt(np.mean(d ** 2)),
             "RMSE_motor": np.sqrt(np.mean(d[:8] ** 2)),
             "RMSE_bike": np.sqrt(np.mean(d[8:] ** 2)),
             "speed_tests_passed": int(np.sum(np.abs(t_speed) < tcrit)),
             "acc_tests_passed": int(np.sum(np.abs(t_acc) < tcrit)),
             "RMSE_acc": np.sqrt(np.mean((axbar - abar) ** 2)),
             "J": np.mean(zloss(d / SD_V)) + W_ACC * np.mean(zloss((axbar - abar) / SD_A)),
             "GEH_max": g_eh.max(), "served_L4_%": 100 * flow[3] / EXPECTED_FLOW[4],
             "n_repl_needed": float(np.nanmax(n_req)),
             "feasible": bool(g_eh.max() <= GEH_MAX and flow[3] >= SERVED_MIN * EXPECTED_FLOW[4])}
        for j, i in enumerate(LOCS):
            r[f"v{i}"], r[f"e{i}"], r[f"s{i}"], r[f"t{i}"] = xbar[j], d[j], sx[j], t_speed[j]
        for j, i in enumerate(MOTOR):
            r[f"a{i}"], r[f"ta{i}"], r[f"q{i}"] = axbar[j], t_acc[j], flow[j]
        rows.append(r)
    out = pd.DataFrame(rows)
    return out.sort_values(["feasible", "J"], ascending=[False, True]).reset_index(drop=True)


def set_threshold(summ):
    """Served-demand threshold relative to the original model (its L4 count is below the
    theoretical demand even without congestion: detector position, Poisson arrivals)."""
    global SERVED_THR
    ref = summ[summ.config == "REF_ORIGINAL"]
    if len(ref):
        SERVED_THR = SERVED_REL * float(ref["served_L4_%"].iloc[0]) / 100
    summ["feasible"] = (summ.GEH_max <= GEH_MAX) & (summ["served_L4_%"] / 100 >= SERVED_THR)
    log(f"  served-demand threshold at L4: {100 * SERVED_THR:.1f} % of expected flow")
    return summ.sort_values(["feasible", "J"], ascending=[False, True]).reset_index(drop=True)


def attach_unfinished(summ, results_path):
    from pathlib import Path
    results_path = Path(results_path) if Path(results_path).is_absolute() else HERE / results_path
    p = results_path.with_name(results_path.stem + "_unfinished.csv")
    summ["unfinished_vehs"] = 0
    if p.exists():
        u = pd.read_csv(p)
        if len(u):
            summ["unfinished_vehs"] = summ.config.map(u.groupby("config").remain.sum()).fillna(0).astype(int)
    return summ


def _map_phase1(d):
    d = d.copy()
    d["v_kn"] = d["v_ks"] = d["v_kungs"]
    d["v_se"] = d["v_sw"] = d["v_slott"]
    d["acc_lo"] = d["acc_hi"] = d["acc_scale"]
    d["v_rk"] = d["v_rs"] = d["v_right"]
    d["v_bike"] = d["v_bike"] + 0.2 * (d["dv_ebike"] - 4.0)     # same mean bike desired speed
    return d


def _map_phase2(d):
    d = d.copy()
    d["acc_lo"] = d["acc_hi"] = d["acc_scale"]
    d["v_rk"] = d["v_rs"] = d["v_right"]
    return d


SOURCES = [  # (folder, tag, mapping into the phase-3 parameter space)
    (HERE.parent / "Calibration", "P1", _map_phase1),
    (HERE.parent / "Calibration_phase2", "P2", _map_phase2),
    (HERE, "P3", lambda d: d),
]


def load_training():
    parts = []
    for folder, tag, fmap in SOURCES:
        for res, des in [("results_screen.csv", "design_screen.csv"), ("results_refine.csv", "design_refine.csv")]:
            if not (folder / res).exists() or not (folder / des).exists():
                continue
            summ = attach_unfinished(summarise(pd.read_csv(folder / res)), folder / res)
            design = fmap(pd.read_csv(folder / des)).drop_duplicates("config")
            dd = design[["config", "original"] + PARAM_NAMES].merge(summ, on="config")
            dd["source"] = tag
            dd["config"] = tag + "_" + dd.config.astype(str)
            parts.append(dd)
    data = pd.concat(parts, ignore_index=True)
    data["config"] = data.config.str.replace(r"^P\d_REF_ORIGINAL$", "REF_ORIGINAL", regex=True)
    data = data.drop_duplicates("config", keep="last").reset_index(drop=True)
    return set_threshold(data)


# ---------------------------------------------------------------------------
def scale(X):
    return (np.asarray(X, float) - LO) / (HI - LO)


def _lbfgs(obj_func, initial_theta, bounds):
    from scipy.optimize import minimize
    r = minimize(obj_func, initial_theta, method="L-BFGS-B", jac=True, bounds=bounds,
                 options={"maxiter": 300})
    return r.x, r.fun


def gp(restarts=0):
    k = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(length_scale=np.ones(len(LO)), length_scale_bounds=(0.05, 50), nu=2.5) \
        + WhiteKernel(1e-2, (1e-6, 1e1))
    return GaussianProcessRegressor(kernel=k, normalize_y=True, n_restarts_optimizer=restarts,
                                    optimizer=_lbfgs, random_state=0)


def fit_surrogates(data, targets):
    tr = data[data.original == 0]
    X, models, cv = scale(tr[PARAM_NAMES].values), {}, {}
    for t in targets:
        y = tr[t].values.astype(float)
        models[t] = gp().fit(X, y)
        pred = np.zeros_like(y)     # 5-fold CV with the fitted kernel hyper-parameters kept fixed
        for a, b in KFold(5, shuffle=True, random_state=0).split(X):
            m = GaussianProcessRegressor(kernel=models[t].kernel_, optimizer=None, normalize_y=True)
            pred[b] = m.fit(X[a], y[a]).predict(X[b])
        cv[t] = {"cv_rmse": float(np.sqrt(np.mean((pred - y) ** 2))),
                 "cv_r2": float(1 - np.sum((pred - y) ** 2) / np.sum((y - y.mean()) ** 2)),
                 "range": float(y.max() - y.min())}
        log(f"  surrogate {t}: CV R2 {cv[t]['cv_r2']:.3f}")
    return models, pd.DataFrame(cv).T


def predict(models, U, targets):
    return np.column_stack([models[t].predict(U) for t in targets])


def sobol_indices(models, targets, n=2048, seed=1):
    """Saltelli/Jansen first-order and total Sobol indices on the GP mean."""
    d = len(LO)
    rng = np.random.default_rng(seed)
    A, B = rng.random((n, d)), rng.random((n, d))
    fA, fB = predict(models, A, targets), predict(models, B, targets)
    var = np.var(np.vstack([fA, fB]), axis=0) + 1e-12
    S1, ST = np.zeros((d, len(targets))), np.zeros((d, len(targets)))
    for i in range(d):
        ABi = A.copy()
        ABi[:, i] = B[:, i]
        fABi = predict(models, ABi, targets)
        S1[i] = np.mean(fB * (fABi - fA), axis=0) / var
        ST[i] = 0.5 * np.mean((fA - fABi) ** 2, axis=0) / var
    return (pd.DataFrame(S1, index=PARAM_NAMES, columns=targets),
            pd.DataFrame(ST, index=PARAM_NAMES, columns=targets))


def objective_factory(models, field_mean, field_acc):
    tg = SPEEDS + FLOWS + ACCS
    u_base = scale([BASE[k] for k in PARAM_NAMES])
    q_exp = np.array([EXPECTED_FLOW[i] for i in MOTOR])

    def evaluate(U):
        U = np.atleast_2d(U)
        P = predict(models, U, tg)
        v, q, acc = P[:, :12], P[:, 12:20], P[:, 20:]
        rmse = np.sqrt(np.mean((v - field_mean) ** 2, axis=1))
        rmse_a = np.sqrt(np.mean((acc - field_acc) ** 2, axis=1))
        g = geh(q, q_exp).max(axis=1)
        served = q[:, 3] / EXPECTED_FLOW[4]
        pen = 10 * np.maximum(0, g - (GEH_MAX - 1.0)) + 100 * np.maximum(0, (SERVED_THR + 0.01) - served)
        reg = 0.05 * np.mean((U - u_base) ** 2, axis=1)       # parsimony: stay close to original
        zv, za = (v - field_mean) / SD_V, (acc - field_acc) / SD_A
        J = np.mean(zloss(zv), axis=1) + W_ACC * np.mean(zloss(za), axis=1)
        return J + pen + reg, rmse, g, served, v, rmse_a, acc
    return evaluate


def optimise(models, n_cand=3, n_global=2 ** 15):
    """Global Sobol screening of the surrogate, then vectorised local search
    (shrinking Gaussian perturbations around the best points)."""
    fs, fa = load_field()
    ev = objective_factory(models, fs.mean(0), fa.mean(0))

    def batch(U):
        return np.concatenate([ev(U[i:i + 8192])[0] for i in range(0, len(U), 8192)])

    rng = np.random.default_rng(0)
    U = qmc.Sobol(len(LO), seed=0).random(n_global)
    J = batch(U)
    for sigma in (0.08, 0.04, 0.02, 0.01, 0.005):
        elite = U[np.argsort(J)[:32]]
        cand = np.clip(np.repeat(elite, 256, 0) + rng.normal(0, sigma, (32 * 256, len(LO))), 0, 1)
        U = np.vstack([elite, cand])
        J = batch(U)
    order = np.argsort(J)
    chosen = []
    for k in order:
        if all(np.max(np.abs(U[k] - o["u"])) > 0.05 for o in chosen):
            Jk, rmse, g, served, v, ra, acc = ev(U[k])
            chosen.append({"u": U[k], "J": Jk[0], "pred_RMSE_all": rmse[0], "pred_RMSE_acc": ra[0],
                           "pred_GEH_max": g[0], "pred_served_L4_%": 100 * served[0], "v": v[0], "acc": acc[0]})
        if len(chosen) == n_cand:
            break
    return chosen


# ---------------------------------------------------------------------------
def train():
    data = load_training()
    data.to_csv(HERE / "summary_calibration_runs.csv", index=False)
    fs, fa = load_field()
    log(f"analyse train: {len(data)} configurations, {int(data.n_runs.sum())} simulation runs")
    show = ["config", "J", "RMSE_all", "RMSE_motor", "RMSE_bike", "RMSE_acc", "speed_tests_passed", "acc_tests_passed",
            "GEH_max", "served_L4_%", "unfinished_vehs", "feasible"]
    lines = [f"Objective J = mean_i L(z_i) over 12 speeds + mean over 8 accelerations, z_i = (sim_i - field_i)/sd_i "
             f"(sd_i = field day-to-day s.d.), L(z) = max(0,|z|-{Z0})^2 + 0.05 z^2: maximises passed t-tests",
             f"Training data: {data.groupby('source').size().to_dict()} configurations",
             "Best simulated configurations (feasible first):",
             data.sort_values(["feasible", "J"], ascending=[False, True])[show].head(15).round(3).to_string(), ""]
    ref = data[data.config == "REF_ORIGINAL"]
    if len(ref):
        lines += ["Original model (with warm-up):", ref[show + SPEEDS].round(2).to_string(), ""]

    targets = SPEEDS + FLOWS + ACCS
    models, cv = fit_surrogates(data, targets)
    lines += ["GP surrogate 5-fold cross-validation:", cv.round(3).to_string(), ""]
    S1, ST = sobol_indices(models, SPEEDS + ["q4"] + ACCS)
    ST.round(3).to_csv(HERE / "sensitivity_total_sobol.csv")
    S1.round(3).to_csv(HERE / "sensitivity_first_sobol.csv")
    lines += ["Total Sobol indices (share of output variance caused by each parameter, incl. interactions):",
              ST.round(2).to_string(), ""]
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(12, 6))
        im = ax.imshow(ST.values, cmap="viridis", vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(ST.shape[1]), [c.replace("v", "L").replace("a", "acc L") for c in ST.columns], rotation=60)
        ax.set_yticks(range(ST.shape[0]), ST.index)
        for i in range(ST.shape[0]):
            for j in range(ST.shape[1]):
                ax.text(j, i, f"{ST.values[i, j]:.2f}", ha="center", va="center", fontsize=6,
                        color="w" if ST.values[i, j] < 0.5 else "k")
        fig.colorbar(im, label="total Sobol index")
        ax.set_title("Parameter sensitivity (GP surrogate, total Sobol indices)")
        fig.tight_layout()
        fig.savefig(HERE / "sensitivity_heatmap.png", dpi=150)
    except Exception as e:  # noqa: BLE001
        lines.append(f"(plot skipped: {e})")

    cands = optimise(models)
    best = cands[0]
    x_best = LO + best["u"] * (HI - LO)
    json.dump(dict(zip(PARAM_NAMES, map(float, x_best))), open(HERE / "surrogate_optimum.json", "w"), indent=1)
    crow = []
    for k, c in enumerate(cands, 1):
        x = LO + c["u"] * (HI - LO)
        crow.append({"config": f"OPT{k}", "original": 0, **dict(zip(PARAM_NAMES, x)),
                     "pred_J": c["J"], "pred_RMSE_all": c["pred_RMSE_all"], "pred_RMSE_acc": c["pred_RMSE_acc"],
                     "pred_GEH_max": c["pred_GEH_max"],
                     "pred_served_L4_%": c["pred_served_L4_%"],
                     "at_bound": ",".join(n for n, u in zip(PARAM_NAMES, c["u"]) if u < 0.02 or u > 0.98)})
    cdf = pd.DataFrame(crow)
    cdf.to_csv(HERE / "surrogate_candidates.csv", index=False)
    lines += ["Surrogate optimum candidates:", cdf.round(3).T.to_string(), "",
              "Predicted speeds of OPT1 vs field:",
              pd.DataFrame({"field": fs.mean(0), "pred_OPT1": best["v"]}, index=[f"L{i}" for i in LOCS]).round(2).to_string(), "",
              f"Predicted standardized speed errors z: {np.round((best['v'] - fs.mean(0)) / SD_V, 2)}",
              f"Predicted standardized acc. errors z:   {np.round((best['acc'] - fa.mean(0)) / SD_A, 2)}", "",
              "Predicted accelerations of OPT1 vs field:",
              pd.DataFrame({"field": fa.mean(0), "pred_OPT1": best["acc"]}, index=[f"L{i}" for i in MOTOR]).round(3).to_string(), ""]

    # validation design: candidates, best simulated feasible config, original model
    val = cdf[["config", "original"] + PARAM_NAMES].copy()
    feas = data[(data.original == 0) & data.feasible].sort_values("J")
    if len(feas):
        b = feas.iloc[0]
        val = pd.concat([val, pd.DataFrame([{"config": "BEST_SIM", "original": 0, **{k: b[k] for k in PARAM_NAMES}}])])
        lines.append(f"BEST_SIM = {b.config} (J {b.J:.3f}, RMSE_all {b.RMSE_all:.3f}, RMSE_acc {b.RMSE_acc:.3f})")
    val = pd.concat([val, pd.DataFrame([{"config": "REF_ORIGINAL", "original": 1, **BASE}])])
    val.to_csv(HERE / "design_validate.csv", index=False)
    txt = "\n".join(lines)
    (HERE / "report_training.txt").write_text(txt, encoding="utf-8")
    print(txt)


# ---------------------------------------------------------------------------
def validate():
    df = pd.read_csv(HERE / "results_validate.csv")
    summ = set_threshold(attach_unfinished(summarise(df), "results_validate.csv"))
    fs, fa = load_field()
    odd, even = fs[0::2].mean(0), fs[1::2].mean(0)
    for c in ("odd", "even"):
        ref = odd if c == "odd" else even
        summ[f"RMSE_all_{c}_days"] = [np.sqrt(np.mean((summ.loc[i, SPEEDS].values.astype(float) - ref) ** 2))
                                      for i in summ.index]
    summ.to_csv(HERE / "summary_validation.csv", index=False)
    design = pd.read_csv(HERE / "design_validate.csv").set_index("config")
    show = ["config", "n_runs", "J", "RMSE_all", "RMSE_motor", "RMSE_bike", "speed_tests_passed", "acc_tests_passed",
            "RMSE_acc", "GEH_max", "served_L4_%", "unfinished_vehs", "n_repl_needed",
            "RMSE_all_odd_days", "RMSE_all_even_days", "feasible"]
    lines = ["VALIDATION (independent seeds)", summ[show].round(3).to_string(), ""]
    best = summ[summ.config != "REF_ORIGINAL"].iloc[0]
    lines.append(f"Selected calibrated configuration: {best.config}")
    lines.append(design.loc[best.config, PARAM_NAMES].astype(float).round(3).to_string())
    ny, nx = fs.shape[0], int(best.n_runs)
    tcrit = stats.t.ppf(0.975, ny + nx - 2)
    rows = []
    for i in LOCS:
        rows.append({"loc": f"L{i}", "name": LOC_NAMES[i], "field": fs[:, i - 1].mean(), "field_sd": fs[:, i - 1].std(ddof=1),
                     "sim": best[f"v{i}"], "sim_sd": best[f"s{i}"], "diff": best[f"e{i}"], "t": best[f"t{i}"],
                     "pass": abs(best[f"t{i}"]) < tcrit})
    loc = pd.DataFrame(rows)
    acc = pd.DataFrame([{"loc": f"L{i}", "field": fa[:, i - 1].mean(), "sim": best[f"a{i}"], "t": best[f"ta{i}"],
                         "pass": abs(best[f"ta{i}"]) < tcrit} for i in MOTOR])
    lines += ["", f"Speeds [km/h], t_crit = {tcrit:.3f}", loc.round(3).to_string(index=False),
              "", "Accelerations [m/s2] (part of the calibration objective)", acc.round(3).to_string(index=False)]
    txt = "\n".join(lines)
    (HERE / "report_validation.txt").write_text(txt, encoding="utf-8")
    print(txt)
    write_latex(best, design.loc[best.config], loc, acc, summ, tcrit)


def write_latex(best, params, loc, acc, summ, tcrit):
    L = [r"\begin{table}[H]", r"\centering",
         r"\caption{Calibrated parameter values (configuration " + best.config.replace("_", r"\_") + r").}",
         r"\begin{tabular}{llrr}", r"\toprule", r"\textbf{Parameter} & \textbf{Description} & \textbf{Original} & \textbf{Calibrated}\\", r"\midrule"]
    for k in PARAM_NAMES:
        L.append(f"{k.replace('_', chr(92) + '_')} & {PARAMS[k][3].replace('%', chr(92) + '%')} & {PARAMS[k][2]:.2f} & {float(params[k]):.2f}\\\\")
    L += [r"\bottomrule", r"\end{tabular}", r"\end{table}", "",
          r"\begin{table}[H]", r"\centering",
          r"\caption{Validation of mean speeds with independent random seeds ($n_x=" + str(int(best.n_runs)) +
          r"$ replications, $n_y=10$ field days, $t_{crit}=" + f"{tcrit:.3f}" + r"$).}",
          r"\begin{tabular}{llrrrrrc}", r"\toprule",
          r"\textbf{Loc.} & \textbf{Name} & \textbf{Field} & \textbf{s.d.} & \textbf{Sim.} & \textbf{s.d.} & $T$ & \textbf{H$_0$ kept}\\", r"\midrule"]
    for _, r in loc.iterrows():
        L.append(f"{r['loc']} & {r['name']} & {r.field:.2f} & {r.field_sd:.2f} & {r.sim:.2f} & {r.sim_sd:.2f} & {r.t:.2f} & {'yes' if r['pass'] else 'no'}\\\\")
    L += [r"\bottomrule", r"\end{tabular}", r"\end{table}", "",
          r"\begin{table}[H]", r"\centering", r"\caption{Mean accelerations [m/s$^2$] with independent random seeds.}",
          r"\begin{tabular}{lrrrc}", r"\toprule", r"\textbf{Loc.} & \textbf{Field} & \textbf{Sim.} & $T$ & \textbf{H$_0$ kept}\\", r"\midrule"]
    for _, r in acc.iterrows():
        L.append(f"{r['loc']} & {r.field:.3f} & {r.sim:.3f} & {r.t:.2f} & {'yes' if r['pass'] else 'no'}\\\\")
    L += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    (HERE / "report_validation.tex").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    {"train": train, "validate": validate}[sys.argv[1]]()
