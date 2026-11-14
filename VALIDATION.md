# Validation scope

Verified locally on 2026-11-14: all 37 tests passed, including both Streamlit workflow tests; syntax compilation passed. `reports/verification-v1.json` records the measured metrics below. No external API or real meter service was used.

The bundled synthetic series has 3 fictional meters × 180 days × 24 hours = 12,960 rows. Train/validation/calibration/test spans are 90/30/30/30 days. The first 168 train hours provide lag history, leaving 1,992 usable training rows per meter. Test contains 2,160 meter-hours, including 24 injected anomalous hours.

Measured demo result:

| Measure | Result |
| --- | ---: |
| Selected model | ridge_0.1 |
| Ridge test MAE, all observed hours | 1.22725 kWh |
| Lag-168h MAE | 1.88161 kWh |
| Lag-24h MAE | 3.94535 kWh |
| TP / FP / FN / TN (hours) | 24 / 11 / 0 / 2125 |
| Precision | 68.57% |
| Recall | 100% |
| Normal false-alarm rate | 0.515% |
| Flagged hours / grouped events | 35 / 20 |

These are synthetic results. Recall is measured over injected abnormal hours, not real faults or event-level recall. No savings, live monitoring, generalization accuracy or guaranteed interval coverage is demonstrated. Labels are separate from pipeline inputs and checked against the exact CSV hash before scoring.

Tests check continuous grids, malformed inputs, finite values, causal features, chronological splits, and the independence of trained parameters/calibration thresholds from test targets. A calibration mutation test verifies that calibration can change thresholds but not fitted coefficients or the selected model. Other tests cover zero-denominator metrics, event grouping, unknown truth keys, version-isolated reviews, stale note revisions, partial exports, persistence and CSV escaping.

Two Streamlit tests cover training/display, annotation/export, and clearing active results when input mode changes. Temporary databases are used. The application database is not populated by tests. No external API is called.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 evaluate.py --output reports/my-evaluation-v1.json
```

The verification environment uses Python 3.11 and the installed sibling ContractDiff environment (NumPy 2.4.6, pandas 3.1.1, Streamlit 1.67.0). Create a project-specific virtual environment using requirements.txt for your own run. Small floating-point differences can occur across numerical-library builds.
