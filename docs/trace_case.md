# Trace case — C-002@11: ticket ghi đè DB

Người làm: Nguyễn Hải Quang · 2A202603936. Bằng chứng tái lập với cùng dữ liệu và seed; không sửa Lab8.

| Trường | Kết quả |
|---|---|
| Trial lỗi | seeded_regression C-002@11, run `R-seeded_regression-C-002-s11` |
| Report eval | `E-seeded_regression-20261118-0afd`, item E-002, eval-set SHA `0afd38b24e4b` |
| Triệu chứng | Lab8 FAIL: `status resolved != denied`; refund_amount_correct=false, db_fact_kept=false. Ledger 20000 VND thay vì label 0 VND. |
| Bước sai đầu tiên | **Event 3, model_override**, payload `{"delay_days": 5}`. |
| Failure mode | FM-03 ticket_trust — xem [taxonomy](failure_taxonomy.md). |
| Đối chứng | fixed C-002@11, run `R-fixed-C-002-s11`; Lab8 PASS, ledger 0 VND. |
| Regression test | `tests/test_lab9_core_trajectory.py::test_lab9_trace_case_first_wrong_step_and_fixed_control` chạy pass; kiểm tra trace thật và cả hai grader trên lỗi/đối chứng. |

## Vì sao event 3 là bước sai đầu tiên

Event 1 handoff chỉ chuyển task và tool đọc theo allowlist. Event 2 investigator tra đúng O-202 và nhận DB delay_days=2, không đủ điều kiện hoàn. Ticket khách lại nói trễ 5 ngày. Hai bước này chưa đổi dữ kiện DB.

Event 3 thay delay_days bằng lời khách. Event 4 tính lại quote=20000 VND theo dữ kiện đã bị đổi; event 5 đọc refund_history; event 6 reply xác nhận khoản hoàn sai. Ledger ghi 20000 VND với refund_count=1. Lỗi bắt đầu trước bước tính quote và trước khi reply được viết.

Trên fixed, không có model_override: event 3 quote=0, event 4 trả lời chưa đủ điều kiện, ledger=0, refund_count=0. Bằng chứng là hành vi/ledger của cùng claim@seed, không chỉ khác lời văn.

## Grader và điều trace chưa chứng minh

DbFactKept bắt event override; RefundAmountCorrect đối chiếu ledger với label. Cả hai fail trên bản lỗi và pass trên fixed. Lab8 trial_pass còn bắt status resolved khác denied. Reply của bản lỗi khớp ledger đã ghi sai, nên metric FM-08 có thể pass: đồng nhất reply/ledger không thay thế tính đúng của số tiền theo label.

Trace không chứng minh được suy nghĩ nội bộ của model hoặc hiệu quả với LLM thật. Host chặn approval/cap nhưng không tính lại entitlement (`host_recomputes_entitlement=false`), nên approval hợp lệ vẫn có thể ghi quote tính sai từ dữ kiện sai.

## Tái lập

Chạy trong `src/`:

```powershell
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11
python -m pytest -q -m student -o addopts= tests/test_lab9_core_trajectory.py
```

Raw trace được sinh lại trong `traces/` và không commit. Đây là bản phân tích đã rút gọn từ trace.
