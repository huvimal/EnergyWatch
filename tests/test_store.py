import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from data_model import make_demo
from model import pipeline
from store import ReviewStore


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = pipeline(make_demo(days=84)[0])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite3'
        self.store = ReviewStore(self.path)
        self.run = self.store.save(self.result)
        self.event = self.result['events'][0]['id']

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def review(self, **kwargs):
        options = dict(run_id=self.run, event_id=self.event, revision=0, status='investigate', reviewer='demo', note='Check source data.')
        options.update(kwargs)
        self.store.review(**options)

    def test_review_saved(self):
        self.review()
        self.assertEqual(self.store.notes(self.run)[self.event]['revision'], 1)

    def test_stale_review_rejected(self):
        self.review()
        with self.assertRaises(ValueError):
            self.review()

    def test_unknown_event_rejected(self):
        with self.assertRaises(ValueError):
            self.review(event_id='unknown')

    def test_blank_note_rejected(self):
        with self.assertRaises(ValueError):
            self.review(note=' ')

    def test_invalid_label_rejected(self):
        with self.assertRaises(ValueError):
            self.review(status='confirmed_equipment_failure')

    def test_partial_export_keeps_pending(self):
        self.review()
        with zipfile.ZipFile(io.BytesIO(self.store.export(self.run))) as archive:
            report = json.loads(archive.read('run-and-review.json'))
            self.assertEqual(report['reviewed_events'], 1)
            self.assertEqual(report['pending_events'], len(self.result['events']) - 1)
            self.assertIn('pending', archive.read('all-alert-events.csv').decode('utf-8'))
            self.assertIn('test-predictions.csv', archive.namelist())

    def test_csv_formula_escape(self):
        self.review(note='=IMPORT()', reviewer='@demo')
        with zipfile.ZipFile(io.BytesIO(self.store.export(self.run))) as archive:
            text = archive.read('all-alert-events.csv').decode('utf-8-sig')
            self.assertIn("'=IMPORT()", text)
            self.assertIn("'@demo", text)

    def test_same_run_retains_notes(self):
        self.review()
        self.store.save(self.result)
        self.assertEqual(len(self.store.notes(self.run)), 1)

    def test_different_run_no_inherited_notes(self):
        self.review()
        other = pipeline(make_demo(days=84, seed=28)[0])
        run = self.store.save(other)
        self.assertEqual(self.store.notes(run), {})

    def test_history_and_persistence(self):
        self.review()
        self.review(revision=1, status='data_issue', note='Need independent verification.')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM history').fetchone()[0], 2)
        self.store.close()
        self.store = ReviewStore(self.path)
        self.assertEqual(self.store.notes(self.run)[self.event]['status'], 'data_issue')
