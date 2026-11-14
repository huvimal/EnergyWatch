import csv
import io
import unittest
from datetime import timedelta
import numpy as np
from data_model import make_demo, load_data
from model import pipeline, features, threshold, metrics, score_truth, group_events


def rewrite(raw, mutate):
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))
    mutate(rows)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['timestamp', 'meter_id', 'kwh'])
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.truth = make_demo(days=84)

    def test_demo_shape(self):
        data = load_data(self.raw)
        self.assertEqual(len(data['times']), 84 * 24)
        self.assertEqual(len(data['values']), 3)

    def test_deterministic_generator(self):
        self.assertEqual(make_demo(days=84)[0], self.raw)

    def test_bom(self):
        self.assertEqual(len(load_data(b'\xef\xbb\xbf' + self.raw)['values']), 3)

    def test_missing_hour_rejected(self):
        with self.assertRaises(ValueError):
            load_data(rewrite(self.raw, lambda rows: rows.pop(3)))

    def test_duplicate_hour_rejected(self):
        with self.assertRaises(ValueError):
            load_data(rewrite(self.raw, lambda rows: rows.insert(0, rows[0].copy())))

    def test_unsorted_rejected(self):
        def swap(rows):
            rows[0], rows[3] = rows[3], rows[0]
        with self.assertRaises(ValueError):
            load_data(rewrite(self.raw, swap))

    def test_nonfinite_negative_rejected(self):
        for value in ('NaN', 'inf', '-1', '1000001'):
            with self.assertRaises(ValueError):
                load_data(rewrite(self.raw, lambda rows: rows[0].update(kwh=value)))

    def test_bad_meter_rejected(self):
        with self.assertRaises(ValueError):
            load_data(rewrite(self.raw, lambda rows: rows[0].update(meter_id='=FORMULA')))

    def test_wrong_time_format(self):
        with self.assertRaises(ValueError):
            load_data(rewrite(self.raw, lambda rows: rows[0].update(timestamp='2025-01-01T00:30')))

    def test_truth_not_input_column(self):
        with self.assertRaises(ValueError):
            load_data(self.raw.replace(b'timestamp,meter_id,kwh', b'timestamp,meter_id,kwh,is_anomaly', 1))

    def test_too_short(self):
        with self.assertRaises(ValueError):
            load_data(b'timestamp,meter_id,kwh\r\n2025-01-01T00:00,A,1\r\n')

    def test_different_grids(self):
        def shift(rows):
            for row in rows:
                if row['meter_id'] == 'METER_C':
                    from datetime import datetime
                    dt = datetime.fromisoformat(row['timestamp']) + timedelta(hours=1)
                    row['timestamp'] = dt.strftime('%Y-%m-%dT%H:00')
        with self.assertRaises(ValueError):
            load_data(rewrite(self.raw, shift))


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.truth = make_demo(days=84)
        cls.result = pipeline(cls.raw)

    def test_chronological_splits(self):
        split = self.result['split']
        self.assertLess(split['train'][1], split['validation'][0])
        self.assertLess(split['validation'][1], split['calibration'][0])
        self.assertLess(split['calibration'][1], split['test'][0])

    def test_features_do_not_read_target_or_future(self):
        data = load_data(self.raw)
        y = data['values']['METER_A']
        before = features(y, data['times'][0], [500])
        changed = y.copy()
        changed[500:] = 99999
        np.testing.assert_array_equal(features(changed, data['times'][0], [500]), before)

    def test_test_changes_do_not_fit_or_calibrate(self):
        boundary = self.result['split']['test'][0]
        def change(rows):
            for row in rows:
                if row['timestamp'] >= boundary:
                    row['kwh'] = str(float(row['kwh']) + 50)
        changed = pipeline(rewrite(self.raw, change))
        self.assertEqual(changed['selected_model'], self.result['selected_model'])
        self.assertEqual(changed['thresholds_kwh'], self.result['thresholds_kwh'])
        self.assertEqual(changed['fitted_parameters'], self.result['fitted_parameters'])
        self.assertEqual(changed['test_rows'][0]['forecast_kwh'], self.result['test_rows'][0]['forecast_kwh'])
        self.assertNotEqual(changed['id'], self.result['id'])

    def test_calibration_changes_do_not_fit(self):
        begin, end = self.result['split']['calibration']
        def change(rows):
            for row in rows:
                if begin <= row['timestamp'] <= end:
                    row['kwh'] = str(float(row['kwh']) + 20)
        changed = pipeline(rewrite(self.raw, change))
        self.assertEqual(changed['selected_model'], self.result['selected_model'])
        self.assertEqual(changed['fitted_parameters'], self.result['fitted_parameters'])
        self.assertNotEqual(changed['thresholds_kwh'], self.result['thresholds_kwh'])

    def test_truth_hash_mismatch(self):
        with self.assertRaises(ValueError):
            score_truth(self.result, {**self.truth, 'dataset_sha256': 'wrong'})

    def test_truth_unknown_test_key(self):
        with self.assertRaises(ValueError):
            score_truth(self.result, {**self.truth, 'positive_keys': [['UNKNOWN', '2025-01-01T00:00']]})

    def test_truth_confusion_counts(self):
        scores = score_truth(self.result, self.truth)['hour_level']
        self.assertEqual(scores['tp'] + scores['fn'], len(self.truth['positive_keys']))
        self.assertEqual(sum(scores[k] for k in ('tp', 'fp', 'fn', 'tn')), len(self.result['test_rows']))

    def test_no_negative_bands(self):
        self.assertTrue(all(0 <= r['lower_kwh'] <= r['forecast_kwh'] <= r['upper_kwh'] for r in self.result['test_rows']))

    def test_zero_denominator_metric(self):
        self.assertIsNone(metrics([0, 0], [0, 1])['wape'])

    def test_threshold_rank_and_validation(self):
        self.assertEqual(threshold([1, 2, 3, 4], alpha=.5), 3)
        with self.assertRaises(ValueError):
            threshold([float('nan')])

    def test_event_grouping_by_meter_and_contiguity(self):
        rows = [{'meter_id': m, 'timestamp': t, 'flagged': f, 'residual_kwh': 10} for m, t, f in [
            ('A', '2025-01-01T00:00', True), ('A', '2025-01-01T01:00', True),
            ('A', '2025-01-01T02:00', False), ('A', '2025-01-01T03:00', True),
            ('B', '2025-01-01T03:00', True)]]
        self.assertEqual([e['hours'] for e in group_events(rows, 'demo')], [2, 1, 1])

    def test_next_hour_has_no_observed_actual(self):
        self.assertNotIn('actual_kwh', self.result['next_hour'][0])
        self.assertGreater(self.result['next_hour'][0]['timestamp'], self.result['split']['test'][1])

    def test_baselines_same_points(self):
        counts = {v['points'] for v in self.result['test_metrics_all_observed'].values()}
        self.assertEqual(len(counts), 1)
