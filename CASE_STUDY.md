# EnergyWatch — Case Study

## Problem
An energy-monitoring prototype should demonstrate whether its forecasts outperform simple baselines and show the false alarms produced by its detector. Evaluation must avoid using future targets or anomaly labels to fit the model or tune thresholds.

## Implementation
EnergyWatch is a personal Python/Streamlit prototype for hourly kWh forecasting and alert review. A strict CSV validator requires continuous, aligned hourly series. Per-meter ridge models use calendar features and observed historical lags, with train-only feature scaling and coefficient fitting.

The chronological workflow separates training, model selection, threshold calibration and final testing. Validation selects the regularization parameter; calibration establishes per-meter absolute-error cutoffs. The test is a rolling one-hour-ahead backtest, so earlier observed test values can enter later lag features. It is not a multi-hour forecast from a single origin.

Consecutive flagged hours are grouped into alert events. Reviewers annotate events in SQLite with revision checks and input/model-output fingerprints. A new run does not inherit previous notes. Partial ZIP reports retain unreviewed events explicitly as pending, alongside predictions and review counts.

## Measured synthetic result
The bundled dataset contains 3 fictional meters over 180 days. The split is 90/30/30/30 days for train/validation/calibration/test, with 2,160 meter-hours in the test period. Separate synthetic labels identify 24 injected abnormal hours and are checked against the exact CSV hash after the model pipeline runs.

The local verification report `reports/verification-v1.json` selected `ridge_0.1`:

| Test measure | Result |
| --- | ---: |
| Ridge MAE | 1.2273 kWh |
| Lag-168h baseline MAE | 1.8816 kWh |
| Lag-24h baseline MAE | 3.9454 kWh |
| TP / FP / FN / TN, measured by hour | 24 / 11 / 0 / 2125 |
| Precision / recall | 68.57% / 100% |
| Normal false-alarm rate | 0.515% |
| Flagged hours / grouped events | 35 / 20 |

The 37 automated tests include causal-feature checks, test-target mutation checks, calibration isolation, malformed input validation, review-version isolation, partial exports and two Streamlit workflow tests. See [VALIDATION.md](VALIDATION.md).

## What this does and does not establish
The results show behavior on one self-authored synthetic dataset. Recall applies to injected abnormal hours, not real faults or event-level recall. Eleven false alarms remain visible. Empirical error bands do not guarantee future coverage under temporal dependence or drift.

The project does not diagnose fault causes, control devices, stream live meter data or demonstrate cost/energy savings. The SQLite database is unencrypted, reviewer labels are not authentication, and history is editable. Only synthetic or authorized data should be processed.

## Reproduce
Install requirements, run `python -m unittest discover -s tests -v`, then `python evaluate.py --output reports/my-evaluation-v1.json`. Follow [HUONG_DAN.md](HUONG_DAN.md) to inspect forecasts, annotate alerts and export a partial review report.
