"""Train-only ridge fits, chronological selection/calibration, one-step backtest."""
import hashlib
import json
import math
from datetime import timedelta
import numpy as np
from data_model import load_data

VERSION = 'hourly-ridge-review-v1'
ALPHAS = (.1, 10.0, 100.0)
ALPHA_ERROR = .005


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def features(values, start, indices):
    result = []
    for i in indices:
        if not 168 <= i <= len(values):
            raise ValueError('Features require 168 observed past hours')
        dt = start + timedelta(hours=int(i))
        result.append([math.sin(2 * math.pi * dt.hour / 24), math.cos(2 * math.pi * dt.hour / 24),
                       math.sin(4 * math.pi * dt.hour / 24), math.cos(4 * math.pi * dt.hour / 24),
                       *[float(dt.weekday() == day) for day in range(6)],
                       i / 24, values[i - 24], values[i - 168], float(np.mean(values[i - 24:i]))])
    return np.asarray(result, dtype=float)


def fit_ridge(x, y, alpha):
    if alpha <= 0 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Invalid training input')
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-10] = 1
    z = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    penalty = np.eye(z.shape[1]) * alpha
    penalty[0, 0] = 0
    weights = np.linalg.solve(z.T @ z + penalty, z.T @ y)
    return {'mean': mean, 'scale': scale, 'weights': weights}


def predict(fit, x):
    z = np.column_stack([np.ones(len(x)), (x - fit['mean']) / fit['scale']])
    return np.maximum(z @ fit['weights'], 0)


def metrics(actual, forecast):
    actual, forecast = np.asarray(actual), np.asarray(forecast)
    if len(actual) == 0:
        return {'points': 0, 'mae': None, 'wape': None, 'bias': None}
    denominator = float(np.abs(actual).sum())
    return {'points': len(actual), 'mae': float(np.abs(actual - forecast).mean()),
            'wape': float(np.abs(actual - forecast).sum() / denominator) if denominator else None,
            'bias': float((forecast - actual).mean())}


def threshold(errors, alpha=ALPHA_ERROR):
    errors = np.asarray(errors)
    if not len(errors) or not 0 < alpha < 1 or not np.isfinite(errors).all() or (errors < 0).any():
        raise ValueError('Invalid calibration errors')
    rank = min(len(errors), math.ceil((len(errors) + 1) * (1 - alpha)))
    return float(np.sort(errors)[rank - 1])


def pipeline(raw):
    data = load_data(raw)
    times = data['times']
    n = len(times)
    train_end, valid_end, calib_end = n // 2, n * 2 // 3, n * 5 // 6
    candidate_fits = {}
    validation = {f'ridge_{alpha:g}': [] for alpha in ALPHAS}
    matrices = {}
    for meter, values in data['values'].items():
        x = features(values, times[0], range(168, n))
        matrices[meter] = x
        train, valid = slice(0, train_end - 168), slice(train_end - 168, valid_end - 168)
        for alpha in ALPHAS:
            fit = fit_ridge(x[train], values[168:train_end], alpha)
            candidate_fits[(meter, alpha)] = fit
            validation[f'ridge_{alpha:g}'].extend(np.abs(values[train_end:valid_end] - predict(fit, x[valid])).tolist())
    val_mae = {name: float(np.mean(values)) for name, values in validation.items()}
    selected = min(ALPHAS, key=lambda a: (val_mae[f'ridge_{a:g}'], a))
    rows, next_hour, fitted, thresholds = [], [], {}, {}
    baseline_actual, baseline_day, baseline_week, ridge_all = [], [], [], []
    for meter, values in data['values'].items():
        fit = candidate_fits[(meter, selected)]
        x = matrices[meter]
        calibration_pred = predict(fit, x[valid_end - 168:calib_end - 168])
        cutoff = threshold(np.abs(values[valid_end:calib_end] - calibration_pred))
        thresholds[meter] = cutoff
        fitted[meter] = {k: v.tolist() for k, v in fit.items()}
        predictions = predict(fit, x[calib_end - 168:])
        for i, prediction in zip(range(calib_end, n), predictions):
            actual = float(values[i])
            estimate = float(prediction)
            rows.append({'meter_id': meter, 'timestamp': times[i].strftime('%Y-%m-%dT%H:00'),
                         'actual_kwh': actual, 'forecast_kwh': estimate,
                         'lower_kwh': max(0, estimate - cutoff), 'upper_kwh': estimate + cutoff,
                         'residual_kwh': actual - estimate, 'threshold_kwh': cutoff,
                         'flagged': abs(actual - estimate) > cutoff})
            baseline_actual.append(actual)
            baseline_day.append(float(values[i - 24]))
            baseline_week.append(float(values[i - 168]))
            ridge_all.append(estimate)
        future = float(predict(fit, features(values, times[0], [n]))[0])
        next_hour.append({'meter_id': meter, 'timestamp': (times[-1] + timedelta(hours=1)).strftime('%Y-%m-%dT%H:00'),
                          'forecast_kwh': future, 'lower_kwh': max(0, future - cutoff), 'upper_kwh': future + cutoff})
    split = {'train': [times[0].isoformat(timespec='minutes'), times[train_end - 1].isoformat(timespec='minutes')],
             'validation': [times[train_end].isoformat(timespec='minutes'), times[valid_end - 1].isoformat(timespec='minutes')],
             'calibration': [times[valid_end].isoformat(timespec='minutes'), times[calib_end - 1].isoformat(timespec='minutes')],
             'test': [times[calib_end].isoformat(timespec='minutes'), times[-1].isoformat(timespec='minutes')]}
    result = {'algorithm': VERSION, 'dataset_sha256': data['sha256'], 'timezone': 'UTC+07:00',
              'meters': list(data['values']), 'hours_per_meter': n, 'split': split,
              'usable_train_points_per_meter': train_end - 168, 'validation_mae': val_mae,
              'selected_model': f'ridge_{selected:g}', 'thresholds_kwh': thresholds,
              'calibration_alpha': ALPHA_ERROR, 'fitted_parameters': fitted,
              'test_metrics_all_observed': {'lag_24h': metrics(baseline_actual, baseline_day),
                    'lag_168h': metrics(baseline_actual, baseline_week), 'ridge': metrics(baseline_actual, ridge_all)},
              'test_band_coverage': float(np.mean([not r['flagged'] for r in rows])),
              'test_rows': rows, 'next_hour': next_hour,
              'scope': 'Rolling one-hour-ahead backtest with observed prior lags; no multi-hour recursive forecast. Bands are empirical, not guaranteed coverage.'}
    result['id'] = fingerprint(result)
    result['events'] = group_events(rows, result['id'])
    return result


def group_events(rows, run_id):
    from datetime import datetime
    events = []
    current = None
    for row in sorted(rows, key=lambda r: (r['meter_id'], r['timestamp'])):
        if not row['flagged']:
            current = None
            continue
        contiguous = current and current['meter_id'] == row['meter_id'] and datetime.fromisoformat(row['timestamp']) - datetime.fromisoformat(current['end']) == timedelta(hours=1)
        if not contiguous:
            current = {'meter_id': row['meter_id'], 'start': row['timestamp'], 'end': row['timestamp'], 'hours': 0, 'peak_abs_residual_kwh': 0.0}
            events.append(current)
        current['end'] = row['timestamp']
        current['hours'] += 1
        current['peak_abs_residual_kwh'] = max(current['peak_abs_residual_kwh'], abs(row['residual_kwh']))
    for event in events:
        event['id'] = fingerprint({'run': run_id, **event})[:24]
    return events


def score_truth(result, truth):
    if truth.get('dataset_sha256') != result['dataset_sha256']:
        raise ValueError('Truth labels do not belong to this exact CSV')
    labels = truth.get('positive_keys')
    if not isinstance(labels, list) or not all(isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) for x in v) for v in labels):
        raise ValueError('Invalid truth labels')
    positives = {tuple(v) for v in labels}
    observed = {(r['meter_id'], r['timestamp']) for r in result['test_rows']}
    if len(positives) != len(labels) or not positives <= observed:
        raise ValueError('Truth labels must be unique test-hour keys')
    tp = fp = fn = tn = 0
    normal_actual, normal_forecast = [], []
    for row in result['test_rows']:
        positive = (row['meter_id'], row['timestamp']) in positives
        flag = row['flagged']
        tp += int(positive and flag)
        fp += int(not positive and flag)
        fn += int(positive and not flag)
        tn += int(not positive and not flag)
        if not positive:
            normal_actual.append(row['actual_kwh'])
            normal_forecast.append(row['forecast_kwh'])
    return {'hour_level': {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': tp / (tp + fp) if tp + fp else None, 'recall': tp / (tp + fn) if tp + fn else None,
            'normal_false_alarm_rate': fp / (fp + tn) if fp + tn else None},
            'ridge_normal_hours_only': metrics(normal_actual, normal_forecast),
            'scope': 'Known injected synthetic hours only. Not real fault diagnosis or event-level recall.'}
