# Automated calibration of the Kungsgatan-Slottsgatan Vissim model

Run on the Vissim PC, from this folder (PowerShell):

```
py -m pip install pywin32 numpy pandas scipy scikit-learn openpyxl matplotlib
py run_pipeline.py smoke      # 2 configs x 1 run: checks the COM link and timing
py run_pipeline.py all        # screen -> refine -> validate (several hours)
```

| Step | What happens | Output |
|---|---|---|
| `screen` | 160-point Latin hypercube over 15 parameters + original model, 3 replications each (seed 42, common random numbers) | `results_screen.csv` |
| `analyse.py train` | summary per configuration, GP surrogate per output (5-fold CV), Sobol sensitivity indices, constrained optimum | `report_training.txt`, `sensitivity_heatmap.png`, `surrogate_candidates.csv`, `design_validate.csv` |
| `refine` | 40-point LHS in a box around the surrogate optimum, retrain | `results_refine.csv` |
| `validate` | 3 surrogate optima + best simulated + original, 10 replications with new seeds (1001, +7) | `report_validation.txt`, `report_validation.tex` |

Model facts: fixed-time controller 1, program 1 (90 s), demand and routes unchanged.
Every variant gets a 600 s warm-up and 1800 s data collection. The original
`II-sim Vissim lab (2025)/Vissim_lab.inpx` is never modified; variants are written to
`C:/Temp/vissim_calibration_runs/` and deleted after reading.

Objective: RMSE of mean speed over L1..L12 vs the 10 field mornings.
Constraints: GEH <= 5 at L1..L8 and served demand at L4 >= 95 %.
Accelerations are only used for validation.
