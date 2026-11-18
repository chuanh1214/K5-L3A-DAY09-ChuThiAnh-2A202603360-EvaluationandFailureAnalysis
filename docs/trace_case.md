# Trace case · C-002@11

Từ `src/`, chạy lại đúng claim và seed trên hai phiên bản.

```powershell
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11
```

| Trường | Kết quả |
|---|---|
| Trial | `seeded_regression C-002@11`, report `E-seeded_regression-20261118-28b4`. |
| Triệu chứng | Lab 8 grader báo `status resolved != denied`. Reply nói đã hoàn 20.000đ và ledger ghi 20.000đ qua 1 lượt. Nhãn yêu cầu 0đ, 0 lượt. |
| Bước sai đầu tiên | Event 3 `model_override` với payload `{"delay_days": 5}`. |
| Các bước trước đó | Event 1 giao nhiệm vụ kiểm tra chính sách đúng claim. Event 2 tra DB thấy đơn O-202 với `delay_days: 2`. Ticket nói 5 ngày. Event 4 tính 20.000đ bằng `SHIP-LATE-03` sau khi độ trễ bị ghi đè. |
| Failure mode | FM-03 · ticket_trust. |
| Đối chứng | `fixed C-002@11` giữ dữ kiện DB, event 3 báo `no_entitlement`, ledger 0đ, trạng thái `denied`, grader PASS. |
| Regression test | `test_c002_uses_database_delay` chạy hai shape trên cùng fixture và seed. Assertion DbFactKept cho kết quả False với variant lỗi, True với fixed. Test kiểm tra thêm ledger và trạng thái. |
| Giới hạn | Trace xác định bước ghi đè trong case này. Một hồi quy không phát event `model_override` cần grader outcome hoặc kiểm chứng trực tiếp dữ kiện nguồn. |

Chạy test với `python -m pytest -q tests/test_lab9_trace_regression.py`.
