# Phase 2: automated calibration of the Kungsgatan-Slottsgatan Vissim model

Run on the Vissim PC, from this folder (PowerShell):

```
py -m pip install pywin32 numpy pandas scipy scikit-learn openpyxl matplotlib
py run_pipeline.py smoke      # 2 configs x 1 run: checks the COM link and timing
py run_pipeline.py all        # screen -> refine -> validate (several hours)
```

| Step | What happens | Output |
|---|---|---|
| `screen` | 160-point Latin hypercube over 14 parameters + original model, 3 replications each (seed 42, common random numbers) | `results_screen.csv` |
| `analyse.py train` | summary per configuration, GP surrogate per output (5-fold CV), Sobol sensitivity indices, constrained optimum | `report_training.txt`, `sensitivity_heatmap.png`, `surrogate_candidates.csv`, `design_validate.csv` |
| `refine` | 40-point LHS in a box around the surrogate optimum, retrain | `results_refine.csv` |
| `validate` | 3 surrogate optima + best simulated + original, 10 replications with new seeds (1001, +7) | `report_validation.txt`, `report_validation.tex` |

Model facts: fixed-time controller 1, program 1 (90 s), demand and routes unchanged.
Every variant gets a 600 s warm-up and 1800 s data collection. The original
`II-sim Vissim lab (2025)/Vissim_lab.inpx` is never modified; variants are written to
`C:/Temp/vissim_calibration_runs/` and deleted after reading.

Objective: J = RMSE(speed, L1..L12)/s_v + RMSE(acceleration, L1..L8)/s_a, where s_v, s_a are the median
day-to-day field standard deviations, so speeds and accelerations weigh equally.
Phase-1 finding: fitting speeds alone drives the deceleration parameters to their bounds and breaks
the accelerations; phase 2 also adds direction-specific desired speeds.
Constraints: GEH <= 5 at L1..L8 and served demand at L4 >= 95 %.
Independent validation: new random seeds and odd/even field days.
