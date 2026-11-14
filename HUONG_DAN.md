# Hướng dẫn EnergyWatch

## 1. Cài đặt và kiểm thử

Mở PowerShell:

```powershell
cd "C:\Users\LOQ\Documents\Codex\2026-11-06\cj\outputs\EnergyWatch"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 evaluate.py --output reports/my-evaluation-v1.json
```

Kỳ vọng: Ran 37 tests và OK. Báo cáo là các metric thực tế, không phải số case cần đạt 100%.

```powershell
Get-Content reports/my-evaluation-v1.json -Encoding utf8
```

Trên demo hiện tại: selected_model=ridge_0.1; test MAE Ridge khoảng 1.2273 kWh, lag_168h khoảng 1.8816, lag_24h khoảng 3.9454. Có 35 giờ vượt ngưỡng, nhóm thành 20 sự kiện. Đối chiếu nhãn giả lập: tp=24, fp=11, fn=0, tn=2125. Sai số số thực có thể chênh rất nhỏ giữa môi trường.

Không gọi đây là 100% accuracy: recall=100% chỉ trên 24 giờ bất thường được chèn, còn precision khoảng 68.57% vì 11 cảnh báo giả.

## 2. Mở ứng dụng

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8515
```

Mở http://127.0.0.1:8515, giữ PowerShell đang chạy. Nếu cổng bận, đổi 8516 và mở đúng cổng mới. Không cần API key.

## 3. Chạy demo và xem baseline

Giữ Demo giả lập, bấm Huấn luyện và đánh giá theo thời gian. Ứng dụng hiển thị 3 công tơ, 4320 giờ mỗi công tơ, 35 giờ cảnh báo và 20 sự kiện (trước khi ghi nhận xét: reviewed=0, pending=20).

Tab Dự báo và baseline: so sánh MAE/WAPE của Ridge với lag_24h và lag_168h. Đây là cùng 2160 điểm test; MAE thấp hơn tốt hơn nhưng chỉ trên demo này.

Chọn METER_A và tăng Số giờ cuối để xem lên 720 để thấy toàn bộ test. Đường actual_kwh là quan sát, forecast_kwh là dự báo một giờ trước; lower/upper là dải sai số thực nghiệm. Dải không bảo đảm bao phủ tương lai.

Bảng Ước lượng cho một giờ sau cuối dữ liệu chưa có actual để đánh giá. Không phải dự báo cả tháng tới.

## 4. Đọc metric cảnh báo

Phần đối chiếu nhãn demo:

- tp: giờ bất thường chèn vào và được báo đúng.
- fp: giờ được gắn nhãn bình thường nhưng bị cảnh báo.
- fn: giờ bất thường chèn vào bị bỏ sót.
- tn: giờ bình thường không bị cảnh báo.

Precision = 24/35 ≈ 68.57%; recall = 24/24 = 100%. Normal false-alarm rate = 11/2136 ≈ 0.515%. Các tỷ lệ đo theo giờ, không phải theo sự kiện hay thiết bị. Nhãn nằm trong tệp riêng, không dùng để huấn luyện hoặc đặt ngưỡng.

## 5. Duyệt một sự kiện

Tab Duyệt cảnh báo, chọn sự kiện có độ lệch lớn, đọc các giờ và residual. Chọn trạng thái:

- investigate: cần kiểm tra thêm.
- expected_variation: người duyệt cho rằng có thể là biến động dự kiến.
- data_issue: người duyệt nghi có vấn đề dữ liệu.

Ghi ví dụ: `Độ lệch cao trong dữ liệu demo. Cần đối chiếu dữ liệu nguồn và lịch hoạt động trước khi kết luận.` Tích đã đọc dữ liệu rồi lưu. Reviewed tăng lên 1, pending giảm còn 19. Nhãn nhận xét không tự thay đổi mô hình hay kết quả TP/FP.

## 6. Xuất báo cáo

Tab Phương pháp và xuất báo cáo: xem mốc train/validation/calibration/test và ngưỡng từng công tơ. Tích hiểu báo cáo có thể còn pending rồi tải ZIP.

ZIP chứa run-and-review.json, all-alert-events.csv và test-predictions.csv. Không cần duyệt hết 20 sự kiện mới được xuất, nhưng mọi sự kiện chưa duyệt vẫn xuất với pending và báo cáo ghi rõ số lượng. Đây là báo cáo duyệt từng phần, không phải xác nhận đã xử lý hết.

## 7. Thử dữ liệu CSV khác

Chọn Tải CSV và tải dữ liệu giả lập/được phép dùng, đúng ba cột theo thứ tự timestamp,meter_id,kwh. Tối thiểu 84 ngày tròn liên tục, tối đa 365 ngày; tối đa 10 công tơ, cùng giờ bắt đầu/kết thúc. Giờ phải YYYY-MM-DDTHH:00, UTC+07:00. Mã công tơ chỉ chữ/số/_; kWh là tiêu thụ từng giờ, không phải chỉ số điện kế cộng dồn.

CSV thiếu giờ, trùng giờ, sai thứ tự, NaN/âm hoặc lệch lưới giữa công tơ sẽ bị từ chối. Demo không tự nội suy. Với dữ liệu tải lên không có nhãn chuẩn, không hiển thị precision/recall. Đổi dữ liệu rồi chạy tạo run mới; ghi chú cũ không được tự kế thừa.

Có thể thử tải chính data/hourly_demo.csv. Với cùng byte dữ liệu và kết quả mô hình, run cũ được dùng lại; đây là hành vi giữ lịch sử có chủ đích.

## 8. Hiểu phạm vi

Test là đánh giá cuốn chiếu một giờ: dự báo giờ t dùng quan sát trước t, bao gồm các giờ test đã xảy ra. Không dùng kWh của chính t hay tương lai để làm đặc trưng. Train fit mô hình; validation chọn alpha; calibration đặt ngưỡng; test để đo kết quả cuối.

Cảnh báo là sai lệch thống kê, chưa phải chẩn đoán hỏng thiết bị. Không tự điều khiển thiết bị hay tính tiền điện. Dữ liệu và ghi chú được lưu không mã hóa trong private/energywatch.sqlite3; app chưa có đăng nhập/phân quyền.
