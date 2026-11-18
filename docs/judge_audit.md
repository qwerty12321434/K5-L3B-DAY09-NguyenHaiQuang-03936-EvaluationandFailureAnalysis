# Judge audit — Nguyễn Hải Quang · 2A202603936

Backend replay, không gọi model/API. `FAIL` là lớp dương: TP là judge phát hiện đúng lỗi, FN là lỗi bị bỏ sót. Floors: κ ≥ 0,6; precision ≥ 0,8; recall ≥ 0,7. κ không xác định phải loại judge.

| Tiêu chí | n | TP / FP / FN / TN | κ | Precision | Recall | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 24 / 4 / 6 / 66 | 0,757 | 0,857 | 0,800 | Đạt floors; đủ điều kiện đánh giá tone trong phạm vi replay |
| helpful | 100 | 9 / 0 / 21 / 70 | 0,375 | 1,000 | 0,300 | Loại; không dùng làm release gate |

Tỉ lệ lỗi quan sát tone=0,28; sensitivity=0,8; specificity=66/70. Rogan–Gladen hiệu chỉnh về 0,30. Helpful có observed=0,09, sensitivity=0,3, specificity=1,0, corrected=0,30. Hiệu chỉnh tỉ lệ không cứu được khả năng tìm lỗi từng case: helpful bỏ sót 21/30 lỗi. Không thay precision cao cho recall thấp.

## Audit các bất đồng

Đây là phân tích do Codex hỗ trợ dựa trên reply và nhãn/ghi chú có sẵn trong CSV, chưa phải một vòng gán nhãn độc lập bởi người mới. Cột “nhãn nên giữ” là đề xuất để người làm bài rà soát.

| Case | Judge / human | Nhãn nên giữ và căn cứ | Sửa rubric đề xuất |
|---|---|---|---|
| H-008 | PASS / FAIL | FAIL: “em”, “nha”, “anh check” quá suồng sã theo chuẩn CS của bộ dữ liệu. | Thêm ví dụ âm cho giọng quá thân mật; lịch sự không chỉ là thân thiện. |
| H-017 | PASS / FAIL | FAIL theo context tuổi khách trong note; chỉ reply đứng riêng chưa chứng minh được tuổi. | Cấp context xưng hô cho judge; thiếu context thì chuyển review, không suy đoán tuổi. |
| H-029 | PASS / FAIL | FAIL: “không cần nhắn thêm” mang giọng ra lệnh dù có “Dạ, vui lòng”. | Ưu tiên kiểm câu áp đặt trước khi cộng điểm lời chào lịch sự. |
| H-042 | FAIL / PASS | PASS cho tone: câu ngắn nhưng lịch sự; không có quy định luôn phải xin lỗi. | Không trừ điểm chỉ vì thiếu câu xin lỗi; tách tone khỏi xác thực số tiền. |
| H-051 | FAIL / PASS | PASS: “refund” là từ CS được phép theo note. | Thêm allowlist thuật ngữ và ví dụ dùng từ tiếng Anh hợp lệ. |
| HL-015 | PASS / FAIL | FAIL về tính đúng: reply 55.000đ, note ledger 40.000đ. | Bắt buộc so tiền bằng code; không cho tone tốt bù lỗi tiền. |
| HL-016 | PASS / FAIL | FAIL: reply 55.000đ, ledger 35.000đ; lời xin lỗi dài không sửa được lỗi. | Chia helpfulness thành đúng dữ kiện và hành động hữu ích; tiền vẫn do code chấm. |
| HL-020 | PASS / FAIL | FAIL: reply 90.000đ, ledger 120.000đ. | Thêm ví dụ âm cho báo thiếu tiền, không chỉ báo thừa. |
| HL-028 | PASS / FAIL | FAIL: reply 50.000đ, ledger 35.000đ; lặp lời xin lỗi. | Không chấm theo độ dài/lịch sự; yêu cầu bằng chứng ledger trước khi xác nhận hoàn. |
| HL-035 | PASS / FAIL | FAIL: reply 50.000đ, ledger 35.000đ, câu chữ trôi chảy vẫn sai. | Thêm ca diễn đạt lại để kiểm rubric giữ nguyên quyết định khi nội dung tiền không đổi. |

## Kết luận và hành động

Giữ tone judge ở mức đã calibration; Core gate hiện chỉ dùng code graders, không tự thêm tone làm blocking metric. Loại helpful judge khỏi quyết định merge. M3 bổ sung `reply_ledger_consistent` để bắt khoảng trống số tiền mà Lab8 trial_pass và helpful judge có thể bỏ sót.

Các sửa rubric trên là đề xuất; dữ liệu judge replay giữ nguyên, không sửa verdict để làm đẹp calibration. Muốn tuyên bố rubric mới tốt hơn phải chạy lại trên nhãn người mới và tập held-out. CSV chỉ có note về ledger, không có DB gốc cho từng reply; audit helpful dựa trên evidence được cung cấp, không khẳng định đã truy vấn ledger thật của các case HL.

## Tái lập

Chạy trong `src/`:

```powershell
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
```

Lệnh tone phải exit 0; helpful phải exit 1. Đây là kết quả mong đợi, không phải lỗi môi trường.
