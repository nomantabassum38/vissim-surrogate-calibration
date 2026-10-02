"""Compare the alternative designs with the calibrated baseline.

  py analyse_alt.py [--out alt]

Paired comparison with common random numbers: run k of every scenario uses the same
seed as run k of BASE, so differences are tested with a paired t-test.
Writes alt_report.txt, alt_tables.tex and figures fig_alt_*.png.
"""
import argparse

import numpy as np
import pandas as pd
from scipy import stats

from common import HERE, LOC_NAMES

SC = ["BASE", "ACTUATED", "INCIDENT", "BIKE800"]
LABEL = {"BASE": "Baseline (fixed time)", "ACTUATED": "Actuated control", "INCIDENT": "Incident demand",
         "BIKE800": "800 bicycles/h"}
COL = {"BASE": "#8a8984", "ACTUATED": "#2a78d6", "INCIDENT": "#eb6834", "BIKE800": "#1baf7a"}
APPROACH = {1: "Kungsg. S left", 2: "Kungsg. S main", 3: "Kungsg. N left", 4: "Kungsg. N main",
            5: "Slottsg. E left", 6: "Slottsg. E main", 7: "Slottsg. W left", 8: "Slottsg. W main",
            9: "Bike N-bound", 10: "Bike S-bound"}


def ci(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return np.nan, np.nan, np.nan
    return x.mean(), x.std(ddof=1), stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))


def paired(df, key, metric, scen):
    a = df[df.scenario == "BASE"].set_index(key)[metric]
    b = df[df.scenario == scen].set_index(key)[metric]
    j = a.index.intersection(b.index)
    d = (b[j] - a[j]).astype(float).dropna()
    if len(d) < 2 or d.std(ddof=1) == 0:
        return np.nan, np.nan
    return d.mean(), stats.ttest_1samp(d, 0).pvalue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="alt")
    a = ap.parse_args()
    dcm = pd.read_csv(HERE / f"{a.out}_dcm.csv")
    net = pd.read_csv(HERE / f"{a.out}_net.csv")
    que = pd.read_csv(HERE / f"{a.out}_queue.csv")
    sc = [s for s in SC if s in set(net.scenario)]
    L = []

    # ---------------- network performance per class
    rows = []
    for s in sc:
        for c in ["All", "Car", "HGV", "Bike"]:
            g = net[(net.scenario == s) & (net["class"] == c)]
            r = {"scenario": s, "class": c, "runs": len(g)}
            for m in ["DelayAvg", "StopsAvg", "SpeedAvg", "DelayStopAvg", "VehArr", "DelayLatent", "DemandLatent"]:
                if m in g and g[m].notna().any():
                    mean, sd, hw = ci(g[m])
                    r[m], r[m + "_ci"] = mean, hw
                    if s != "BASE":
                        sub = net[net["class"] == c]
                        r[m + "_diff"], r[m + "_p"] = paired(sub, "run", m, s)
            rows.append(r)
    perf = pd.DataFrame(rows)
    perf.to_csv(HERE / "alt_network_performance.csv", index=False)
    L += ["NETWORK PERFORMANCE (mean, 95% CI half-width, paired difference to BASE and p-value)",
          perf.round(3).to_string(index=False), ""]

    # replications needed for the average delay (all vehicles), epsilon 5 %
    for s in sc:
        g = net[(net.scenario == s) & (net["class"] == "All")].DelayAvg.astype(float)
        n = (stats.t.ppf(0.975, len(g) - 1) * g.std(ddof=1) / (0.05 * g.mean())) ** 2
        L.append(f"replications needed for average delay ({s}, eps 5%): {n:.1f} (used {len(g)})")
    L.append("")

    # ---------------- queues
    qm = que.groupby(["scenario", "counter", "name", "run"])[["QLen", "QLenMax"]].agg(
        {"QLen": "mean", "QLenMax": "max"}).reset_index()
    qrows = []
    for s in sc:
        for k in sorted(qm.counter.unique()):
            g = qm[(qm.scenario == s) & (qm.counter == k)]
            m1, _, h1 = ci(g.QLen)
            m2, _, h2 = ci(g.QLenMax)
            r = {"scenario": s, "counter": k, "approach": APPROACH.get(k, k), "QLen": m1, "QLen_ci": h1,
                 "QLenMax": m2, "QLenMax_ci": h2}
            if s != "BASE":
                r["QLen_diff"], r["QLen_p"] = paired(qm[qm.counter == k], "run", "QLen", s)
            qrows.append(r)
    qt = pd.DataFrame(qrows)
    qt.to_csv(HERE / "alt_queues.csv", index=False)
    L += ["QUEUES [m] (mean queue over 1800 s, maximum queue)", qt.round(2).to_string(index=False), ""]
    prof = que.groupby(["scenario", "counter", "interval"]).QLen.mean().unstack()
    L += ["QUEUE PROFILE per 10-min interval [m]", prof.round(1).to_string(), ""]

    # ---------------- speeds at L1..L12
    sp = dcm.groupby(["scenario", "loc"]).agg(speed=("speed", "mean"), acc=("acc", "mean"),
                                               flow=("vehs", lambda v: v.mean() * 2)).reset_index()
    spw = sp.pivot(index="loc", columns="scenario", values="speed")[sc]
    L += ["MEAN SPEEDS [km/h] at the measurement locations", spw.round(2).to_string(), ""]
    fw = sp.pivot(index="loc", columns="scenario", values="flow")[sc]
    L += ["HOURLY FLOWS [veh/h] at the measurement locations", fw.round(0).to_string(), ""]
    txt = "\n".join(L)
    (HERE / "alt_report.txt").write_text(txt, encoding="utf-8")
    print(txt)

    # ---------------- LaTeX tables
    def f(x, d=1):
        return "" if pd.isna(x) else f"{x:.{d}f}"

    T = [r"\begin{table}[H]", r"\centering",
         r"\caption{Vehicle network performance (mean $\pm$ 95\,\% confidence half-width, " + str(int(perf.runs.max())) +
         r" replications with common random numbers). $\Delta$: paired difference to the baseline, $p$: paired $t$-test.}",
         r"\label{tab:altperf}", r"\small", r"\begin{tabular}{llrrrrr}", r"\toprule",
         r"\textbf{Scenario} & \textbf{Class} & \textbf{Delay [s/veh]} & $\Delta$ & $p$ & \textbf{Stops [1/veh]} & \textbf{Arrived}\\",
         r"\midrule"]
    for _, r in perf.iterrows():
        T.append(f"{LABEL[r.scenario]} & {r['class']} & {f(r.get('DelayAvg'))} $\\pm$ {f(r.get('DelayAvg_ci'))} & "
                 f"{f(r.get('DelayAvg_diff'))} & {f(r.get('DelayAvg_p'), 3)} & {f(r.get('StopsAvg'), 2)} & {f(r.get('VehArr'), 0)}\\\\")
    T += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    T += [r"\begin{table}[H]", r"\centering", r"\caption{Mean and maximum queue length [m] per queue counter.}",
          r"\label{tab:altqueue}", r"\small", r"\begin{tabular}{l" + "rr" * len(sc) + "}", r"\toprule",
          r"\textbf{Queue counter} & " + " & ".join(r"\multicolumn{2}{c}{\textbf{" + LABEL[s] + "}}" for s in sc) + r"\\",
          " & " + " & ".join(["mean & max"] * len(sc)) + r"\\", r"\midrule"]
    for k in sorted(qt.counter.unique()):
        cells = []
        for s in sc:
            r = qt[(qt.scenario == s) & (qt.counter == k)].iloc[0]
            cells += [f(r.QLen), f(r.QLenMax)]
        T.append(f"{APPROACH.get(k, k)} & " + " & ".join(cells) + r"\\")
    T += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    T += [r"\begin{table}[H]", r"\centering", r"\caption{Mean speed [km/h] at the measurement locations.}",
          r"\label{tab:altspeed}", r"\small", r"\begin{tabular}{ll" + "r" * len(sc) + "}", r"\toprule",
          r"\textbf{Loc.} & \textbf{Name} & " + " & ".join(r"\textbf{" + LABEL[s] + "}" for s in sc) + r"\\", r"\midrule"]
    for loc in spw.index:
        T.append(f"L{loc} & {LOC_NAMES[loc]} & " + " & ".join(f(spw.loc[loc, s], 2) for s in sc) + r"\\")
    T += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    (HERE / "alt_tables.tex").write_text("\n".join(T), encoding="utf-8")

    # ---------------- figures
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                             "axes.edgecolor": "#8a8984", "xtick.color": "#52514e", "ytick.color": "#52514e"})
        # delay per class
        fig, ax = plt.subplots(figsize=(7, 3.6))
        cls = ["All", "Car", "HGV", "Bike"]
        w = 0.8 / len(sc)
        for k, s in enumerate(sc):
            g = perf[perf.scenario == s].set_index("class")
            x = np.arange(len(cls)) + (k - (len(sc) - 1) / 2) * w
            ax.bar(x, [g.loc[c, "DelayAvg"] for c in cls], w * 0.92, yerr=[g.loc[c, "DelayAvg_ci"] for c in cls],
                   color=COL[s], label=LABEL[s], capsize=2, error_kw={"lw": 0.8, "ecolor": "#52514e"})
        ax.set_xticks(range(len(cls)), ["All vehicles", "Cars", "HGV", "Bicycles"])
        ax.set_ylabel("Average delay [s/veh]")
        ax.grid(axis="y", color="#efeee9", lw=0.6)
        ax.legend(frameon=False, fontsize=7.5, ncol=2)
        fig.tight_layout()
        fig.savefig(HERE / "fig_alt_delay.png", dpi=200)
        # mean queue per counter
        fig, ax = plt.subplots(figsize=(7.4, 3.6))
        ks = sorted(qt.counter.unique())
        for k, s in enumerate(sc):
            g = qt[qt.scenario == s].set_index("counter")
            x = np.arange(len(ks)) + (k - (len(sc) - 1) / 2) * w
            ax.bar(x, [g.loc[c, "QLen"] for c in ks], w * 0.92, yerr=[g.loc[c, "QLen_ci"] for c in ks],
                   color=COL[s], label=LABEL[s], capsize=2, error_kw={"lw": 0.8, "ecolor": "#52514e"})
        ax.set_xticks(range(len(ks)), [APPROACH.get(c, c) for c in ks], rotation=35, ha="right")
        ax.set_ylabel("Mean queue length [m]")
        ax.grid(axis="y", color="#efeee9", lw=0.6)
        ax.legend(frameon=False, fontsize=7.5, ncol=2)
        fig.tight_layout()
        fig.savefig(HERE / "fig_alt_queue.png", dpi=200)
        # incident profile
        if "INCIDENT" in sc:
            fig, axs = plt.subplots(1, 4, figsize=(8.4, 2.8), sharey=False)
            for ax, k in zip(axs, (2, 4, 6, 8)):
                for s in ("BASE", "INCIDENT"):
                    v = prof.loc[(s, k)].values
                    ax.plot([5, 15, 25], v, "o-", color=COL[s], lw=2, ms=5, label=LABEL[s])
                ax.set_title(APPROACH[k], fontsize=8.5)
                ax.set_xticks([5, 15, 25], ["0-10", "10-20", "20-30"])
                ax.set_xlabel("minutes", fontsize=8)
                ax.grid(color="#efeee9", lw=0.6)
            axs[0].set_ylabel("Mean queue [m]")
            axs[0].legend(frameon=False, fontsize=7)
            fig.tight_layout()
            fig.savefig(HERE / "fig_alt_incident.png", dpi=200)
    except Exception as e:  # noqa: BLE001
        print("figures skipped:", e)


if __name__ == "__main__":
    main()
