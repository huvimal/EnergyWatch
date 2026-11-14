"""Hourly energy CSV validation and reproducible synthetic fixtures."""
import csv
import hashlib
import io
import json
import math
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np


def load_data(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > 8 * 1024 * 1024:
        raise ValueError('CSV phải khác rỗng và tối đa 8 MB.')
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        if reader.fieldnames != ['timestamp', 'meter_id', 'kwh']:
            raise ValueError('CSV cần đúng ba cột theo thứ tự: timestamp,meter_id,kwh. Không đưa nhãn bất thường vào đầu vào mô hình.')
        values, times = {}, {}
        for row in reader:
            if set(row) != {'timestamp', 'meter_id', 'kwh'} or any(value is None for value in row.values()):
                raise ValueError('Hàng CSV thiếu hoặc thừa trường.')
            meter = row['meter_id']
            if not isinstance(meter, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', meter):
                raise ValueError('Mã công tơ chỉ gồm chữ/số/_, tối đa 32 ký tự.')
            text = row['timestamp']
            if not isinstance(text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:00', text):
                raise ValueError('Thời gian phải là YYYY-MM-DDTHH:00, giờ cố định UTC+07:00.')
            dt = datetime.strptime(text, '%Y-%m-%dT%H:%M')
            value = float(row['kwh'])
            if not math.isfinite(value) or not 0 <= value <= 1000000:
                raise ValueError('kWh phải hữu hạn, không âm và không vượt 1.000.000 mỗi giờ.')
            values.setdefault(meter, []).append(value)
            times.setdefault(meter, []).append(dt)
            if len(values) > 10 or len(values[meter]) > 365 * 24:
                raise ValueError('Tối đa 10 công tơ và 365 ngày mỗi công tơ.')
    except (UnicodeDecodeError, KeyError, TypeError, OverflowError):
        raise ValueError('Không đọc được CSV UTF-8 hoặc có trường rỗng/sai kiểu.') from None
    except ValueError as exc:
        raise ValueError(str(exc)) from None
    if not values:
        raise ValueError('CSV không có dữ liệu.')
    reference = next(iter(times.values()))
    if len(reference) < 84 * 24 or len(reference) % 24:
        raise ValueError('Cần 84–365 ngày tròn dữ liệu theo giờ.')
    for meter, timeline in times.items():
        if any(b - a != timedelta(hours=1) for a, b in zip(timeline, timeline[1:])):
            raise ValueError('Có giờ thiếu, trùng hoặc sai thứ tự. Demo không tự nội suy/điền khoảng trống.')
        if timeline != reference:
            raise ValueError('Các công tơ phải có cùng lưới giờ bắt đầu/kết thúc.')
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'times': reference,
            'values': {m: np.array(v, dtype=float) for m, v in sorted(values.items())}}


def make_demo(days=180, seed=27):
    if days < 84:
        raise ValueError('Demo needs at least 84 days')
    rng = random.Random(seed)
    start = datetime(2025, 1, 1)
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['timestamp', 'meter_id', 'kwh'])
    positives = []
    test_start = days * 24 * 5 // 6
    event_hours = {test_start + 3 * 24 + j: 18 for j in (10, 11, 12)}
    event_hours.update({test_start + 11 * 24 + j: -15 for j in (15, 16, 17, 18)})
    event_hours[test_start + 18 * 24 + 8] = 25
    # For the minimum-length demo, drop events beyond its observed horizon.
    for i in range(days * 24):
        dt = start + timedelta(hours=i)
        for meter, scale in [('METER_A', 1.0), ('METER_B', 1.5), ('METER_C', .7)]:
            normal = 45 + 10 * math.sin(2 * math.pi * (dt.hour - 7) / 24) + 3 * math.cos(4 * math.pi * dt.hour / 24)
            normal += -8 if dt.weekday() >= 5 else 0
            normal += i / 24 * .025
            value = scale * (normal + rng.gauss(0, 1.2) + event_hours.get(i, 0))
            timestamp = dt.strftime('%Y-%m-%dT%H:00')
            writer.writerow([timestamp, meter, f'{max(value, 0):.4f}'])
            if i in event_hours:
                positives.append([meter, timestamp])
    raw = out.getvalue().encode('utf-8')
    truth = {'dataset_sha256': hashlib.sha256(raw).hexdigest(), 'scope': 'synthetic_injected_test_hours_only', 'positive_keys': positives}
    return raw, truth


if __name__ == '__main__':
    root = Path(__file__).resolve().parent / 'data'
    root.mkdir(exist_ok=True)
    raw, truth = make_demo()
    (root / 'hourly_demo.csv').write_bytes(raw)
    (root / 'truth.json').write_text(json.dumps(truth, indent=2), encoding='utf-8')
    print('Created synthetic CSV and separate truth labels.')
