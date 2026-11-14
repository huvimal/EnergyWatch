import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from store import ReviewStore

ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    @staticmethod
    def button(app, label):
        return next(b for b in app.button if b.label == label)

    def test_demo_review_and_partial_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ui.sqlite3'
            with patch('store.ReviewStore', side_effect=lambda *_: ReviewStore(path)):
                app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
                self.button(app, 'Huấn luyện và đánh giá theo thời gian').click().run()
                self.assertEqual(len(app.exception), 0)
                next(t for t in app.text_area if t.label == 'Ghi chú kiểm tra').set_value('Đối chiếu demo; cần kiểm tra dữ liệu gốc trước khi xác định nguyên nhân.')
                next(c for c in app.checkbox if c.label.startswith('Tôi đã đọc dữ liệu')).check()
                self.button(app, 'Lưu nhận xét').click().run()
                self.assertEqual(len(app.exception), 0)
                next(c for c in app.checkbox if c.label.startswith('Tôi hiểu báo cáo')).check().run()
                self.assertEqual(len(app.exception), 0)
                store = ReviewStore(path)
                result = store.run(app.session_state['run_id'])
                self.assertEqual(len(store.notes(result['id'])), 1)
                self.assertTrue(store.export(result['id']))
                self.assertGreater(len(result['events']), 1)
                store.close()

    def test_input_mode_change_clears_active_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ui.sqlite3'
            with patch('store.ReviewStore', side_effect=lambda *_: ReviewStore(path)):
                app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
                self.button(app, 'Huấn luyện và đánh giá theo thời gian').click().run()
                self.assertTrue(app.session_state['run_id'])
                app.radio[0].set_value('Tải CSV').run()
                self.assertEqual(len(app.exception), 0)
                self.assertNotIn('run_id', app.session_state)
                self.assertFalse(any(b.label == 'Lưu nhận xét' for b in app.button))
