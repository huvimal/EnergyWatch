import hashlib
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from model import pipeline, score_truth
from store import ReviewStore, STATES

ROOT = Path(__file__).resolve().parent


@st.cache_data(show_spinner=False)
def analyze(raw):
    return pipeline(raw)


def main():
    st.set_page_config(page_title='EnergyWatch', layout='wide')
    st.title('EnergyWatch')
    st.caption('Hourly forecast → Calibrated residual alerts → Human review')
    st.info('Bản demo cục bộ. Cảnh báo chỉ là sai lệch dự báo, không xác định nguyên nhân hoặc tự điều khiển thiết bị. Không cần API key.')
    mode = st.radio('Nguồn dữ liệu', ['Demo giả lập', 'Tải CSV'], horizontal=True)
    raw = None
    if mode == 'Demo giả lập':
        raw = (ROOT / 'data/hourly_demo.csv').read_bytes()
    else:
        uploaded = st.file_uploader('CSV theo giờ: timestamp,meter_id,kwh', type=['csv'])
        if uploaded is not None:
            raw = uploaded.getvalue()
    signature = (mode, hashlib.sha256(raw).hexdigest()) if raw else None
    if st.session_state.get('signature') != signature:
        st.session_state['signature'] = signature
        st.session_state.pop('run_id', None)
    store = ReviewStore(ROOT / 'private/energywatch.sqlite3')
    try:
        if st.button('Huấn luyện và đánh giá theo thời gian', disabled=not raw):
            try:
                with st.spinner('Đang so sánh mô hình, hiệu chỉnh và đánh giá...'):
                    result = analyze(raw)
                    st.session_state['run_id'] = store.save(result)
            except (ValueError, ArithmeticError) as exc:
                st.session_state.pop('run_id', None)
                st.error(str(exc))
        run_id = st.session_state.get('run_id')
        if not run_id:
            st.write('Cần CSV liên tục 84–365 ngày, tối đa 10 công tơ, cùng lưới giờ. Không tự điền giờ thiếu. Giờ cố định UTC+07:00; kWh là năng lượng trong từng giờ, không phải số điện kế tích lũy.')
            return
        result = store.run(run_id)
        notes = store.notes(run_id)
        st.write({'selected_model': result['selected_model'], 'meters': len(result['meters']),
                  'hours_per_meter': result['hours_per_meter'], 'flagged_hours': sum(r['flagged'] for r in result['test_rows']),
                  'alert_events': len(result['events']), 'reviewed_events': len(notes), 'pending_events': len(result['events']) - len(notes)})
        tabs = st.tabs(['1. Dự báo và baseline', '2. Duyệt cảnh báo', '3. Phương pháp và xuất báo cáo'])
        with tabs[0]:
            table = [{'model': name, 'MAE (kWh)': v['mae'], 'WAPE (%)': v['wape'] * 100 if v['wape'] is not None else None,
                      'bias (kWh)': v['bias'], 'test_points': v['points']} for name, v in result['test_metrics_all_observed'].items()]
            st.dataframe(table, hide_index=True)
            st.caption('Cùng 30 ngày test với demo 180 ngày. Đánh giá cuốn chiếu trước một giờ: chỉ dùng dữ liệu đã quan sát trước giờ đích, kể cả các giờ test trước đó. Không phải dự báo toàn bộ test từ một thời điểm duy nhất.')
            meter = st.selectbox('Công tơ', result['meters'])
            hours = st.select_slider('Số giờ cuối để xem', options=[24, 72, 168, 336, 720], value=168)
            rows = [r for r in result['test_rows'] if r['meter_id'] == meter]
            chart = pd.DataFrame(rows[-hours:])
            chart.index = pd.to_datetime(chart['timestamp'])
            st.line_chart(chart[['actual_kwh', 'forecast_kwh', 'lower_kwh', 'upper_kwh']])
            st.caption('Trục thời gian theo CSV, UTC+07:00. Dải sai số lấy từ calibration, không bảo đảm độ phủ tương lai.')
            flagged = [r for r in rows if r['flagged']]
            st.dataframe(flagged, hide_index=True)
            st.subheader('Ước lượng cho một giờ sau cuối dữ liệu')
            st.dataframe(result['next_hour'], hide_index=True)
            st.caption('Chưa có quan sát ở giờ này để kiểm chứng; mô hình giữ nguyên sau train, không cập nhật tự động.')
            if mode == 'Demo giả lập':
                truth = json.loads((ROOT / 'data/truth.json').read_text(encoding='utf-8'))
                try:
                    scores = score_truth(result, truth)
                    st.subheader('Đối chiếu nhãn giờ bất thường được chèn trong demo')
                    st.json(scores)
                    st.caption('Nhãn được đọc sau khi chạy pipeline và không dùng để huấn luyện/chọn ngưỡng. Đây không phải độ chính xác phát hiện hỏng hóc thực tế.')
                except ValueError as exc:
                    st.warning(str(exc))

        with tabs[1]:
            if not result['events']:
                st.write('Không có chuỗi giờ vượt ngưỡng trong lượt này.')
            else:
                events = sorted(result['events'], key=lambda e: (-e['peak_abs_residual_kwh'], e['id']))
                selected = st.selectbox('Chọn sự kiện cảnh báo', [e['id'] for e in events],
                    format_func=lambda value: next(f"{e['meter_id']} · {e['start']} → {e['end']} · {e['hours']} giờ" for e in events if e['id'] == value), key=f'event_{run_id}')
                event = next(e for e in events if e['id'] == selected)
                st.json(event)
                st.dataframe([r for r in result['test_rows'] if r['meter_id'] == event['meter_id'] and event['start'] <= r['timestamp'] <= event['end']], hide_index=True)
                st.caption('Các giờ vượt ngưỡng liền nhau được nhóm thành sự kiện. Nhãn duyệt là nhận xét của người dùng, chưa phải nguyên nhân đã xác minh.')
                old = notes.get(selected)
                revision = old['revision'] if old else 0
                with st.form(f'review_{run_id}_{selected}_{revision}'):
                    reviewer = st.text_input('Người duyệt', old['reviewer'] if old else 'huni-demo')
                    status = st.selectbox('Trạng thái', STATES, index=STATES.index(old['status']) if old else 0)
                    note = st.text_area('Ghi chú kiểm tra', old['note'] if old else '', max_chars=5000)
                    checked = st.checkbox('Tôi đã đọc dữ liệu và hiểu cảnh báo chưa xác định nguyên nhân')
                    if st.form_submit_button('Lưu nhận xét'):
                        try:
                            if not checked:
                                raise ValueError('Cần đối chiếu dữ liệu trước khi lưu.')
                            store.review(run_id, selected, revision, status, reviewer, note)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

        with tabs[2]:
            st.json({'run_id': run_id, 'dataset_sha256': result['dataset_sha256'], 'algorithm': result['algorithm'],
                     'split': result['split'], 'validation_mae': result['validation_mae'], 'thresholds_kwh': result['thresholds_kwh'],
                     'calibration_alpha': result['calibration_alpha'], 'test_band_coverage': result['test_band_coverage']})
            st.write('Ridge và chuẩn hóa đặc trưng chỉ fit trên train. Validation chọn alpha; calibration đặt ngưỡng sai số riêng từng công tơ. Không dùng test hoặc nhãn sự cố để chỉnh ngưỡng.')
            st.caption('Các đoạn thời gian có phụ thuộc. Dải sai số thực nghiệm không có cam kết độ phủ. Cảnh báo giả, drift và ảnh hưởng của bất thường lên lag vẫn có thể xảy ra.')
            ack = st.checkbox('Tôi hiểu báo cáo có thể còn sự kiện pending và không xác nhận lỗi thiết bị', key=f'export_{run_id}')
            if ack:
                st.download_button('Tải ZIP kết quả và nhận xét', store.export(run_id), 'energywatch-report.zip', 'application/zip')
                st.caption('ZIP chứa run-and-review.json, all-alert-events.csv và test-predictions.csv. Sự kiện chưa duyệt vẫn được giữ với trạng thái pending; không bị ẩn khỏi báo cáo.')
    finally:
        store.close()


if __name__ == '__main__':
    main()
