"""Version-bound alert annotations, no automatic fault/root-cause decisions."""
import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

STATES = ('investigate', 'expected_variation', 'data_issue')


class ReviewStore:
    def __init__(self, path='private/energywatch.sqlite3'):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notes(run TEXT, event TEXT, revision INTEGER, status TEXT, reviewer TEXT, note TEXT, created TEXT, PRIMARY KEY(run,event));
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, run TEXT, event TEXT, payload TEXT);
        ''')

    def close(self):
        self.db.close()

    def save(self, result):
        payload = json.dumps(result, sort_keys=True, ensure_ascii=False)
        with self.db:
            row = self.db.execute('SELECT payload FROM runs WHERE id=?', (result['id'],)).fetchone()
            if row and row['payload'] != payload:
                raise ValueError('Run identifier mismatch')
            self.db.execute('INSERT OR IGNORE INTO runs VALUES(?,?)', (result['id'], payload))
        return result['id']

    def run(self, run_id):
        row = self.db.execute('SELECT payload FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise ValueError('Run not found')
        return json.loads(row[0])

    def notes(self, run_id):
        return {row['event']: dict(row) for row in self.db.execute('SELECT * FROM notes WHERE run=?', (run_id,))}

    def review(self, run_id, event_id, revision, status, reviewer, note):
        if status not in STATES or not reviewer.strip() or not note.strip() or len(note) > 5000 or len(reviewer) > 100:
            raise ValueError('Cần trạng thái, tên người duyệt và ghi chú tối đa 5.000 ký tự.')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            result = self.run(run_id)
            if not any(e['id'] == event_id for e in result['events']):
                raise ValueError('Sự kiện không thuộc lượt đánh giá này.')
            old = self.db.execute('SELECT * FROM notes WHERE run=? AND event=?', (run_id, event_id)).fetchone()
            if revision != (old['revision'] if old else 0):
                raise ValueError('Ghi chú đã đổi. Hãy tải lại trước khi lưu.')
            created = datetime.now(timezone.utc).isoformat()
            self.db.execute('INSERT INTO notes VALUES(?,?,?,?,?,?,?) ON CONFLICT(run,event) DO UPDATE SET revision=excluded.revision,status=excluded.status,reviewer=excluded.reviewer,note=excluded.note,created=excluded.created',
                (run_id, event_id, revision + 1, status, reviewer.strip(), note.strip(), created))
            self.db.execute('INSERT INTO history(run,event,payload) VALUES(?,?,?)', (run_id, event_id,
                json.dumps({'before': dict(old) if old else None, 'after': {'revision': revision + 1, 'status': status, 'reviewer': reviewer.strip(), 'note': note.strip(), 'created': created}}, ensure_ascii=False)))

    def export(self, run_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            result = self.run(run_id)
            notes = self.notes(run_id)
            report = {'result': result, 'event_notes': notes,
                      'reviewed_events': len(notes), 'pending_events': len(result['events']) - len(notes),
                      'scope': 'Partial alert annotations. Pending events remain visible. Labels are reviewer opinions, not verified fault causes.'}
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('run-and-review.json', json.dumps(report, ensure_ascii=False, indent=2))
                stream = io.StringIO(newline='')
                writer = csv.writer(stream)
                writer.writerow(['event_id', 'meter', 'start', 'end', 'hours', 'review_status', 'reviewer', 'note'])
                def safe(value):
                    text = str(value)
                    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text
                for event in result['events']:
                    n = notes.get(event['id'], {})
                    writer.writerow([safe(v) for v in (event['id'], event['meter_id'], event['start'], event['end'], event['hours'], n.get('status', 'pending'), n.get('reviewer', ''), n.get('note', ''))])
                archive.writestr('all-alert-events.csv', '\ufeff' + stream.getvalue())
                stream = io.StringIO(newline='')
                fields = ['meter_id', 'timestamp', 'actual_kwh', 'forecast_kwh', 'lower_kwh', 'upper_kwh', 'residual_kwh', 'threshold_kwh', 'flagged']
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(result['test_rows'])
                archive.writestr('test-predictions.csv', '\ufeff' + stream.getvalue())
            return output.getvalue()
