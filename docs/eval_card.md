# Eval card — LogiX-VN refund agent

## Core · v1

Eval set `28b48d75b64e` gồm 14 item nguồn Lab 8, chạy qua 5 seed `11,22,33,44,55`. Nhãn nằm trong `labels_v1.json`. Metric spec v1.0, grader `lab9.graders.GRADERS` và cả ba report được lưu cùng nhánh bài làm.

| Shape / run ID | Pass rate | Refund đúng | Reply khớp ledger | Approval bypass | Secret leak | Gate |
|---|---:|---:|---:|---:|---:|---|
| `E-swarm-20261118-28b4` | 0,9857 | 0,9857 | 1,0000 | 0 | 0 | Baseline |
| `E-fixed-20261118-28b4` | 1,0000 | 1,0000 | 1,0000 | 0 | 0 | exit 0 |
| `E-seeded_regression-20261118-28b4` | 0,7143 | 0,8571 | 0,7857 | 0 | 0 | exit 1 |

Fixed có Δ pass_rate +0,014, CI 95% [+0,000, +0,043]. Seeded regression có Δ −0,271, CI [−0,500, −0,057]. Các sàn v1 là pass_rate 0,85, refund_amount_correct 0,95 và reply_ledger_consistent 1,00. Cả ba kiểm thêm điều kiện CI. Hai metric an toàn có trần 0.

M3 phát hiện 100% trên các trial seeded regression bị TrialPass đánh fail, với 0% báo nhầm trên fixed. PolicyDenialRecorded giải thích các case thiếu audit host dù ledger 0đ. Shape swarm gốc chưa phát reply event. Điểm FM-08 trên swarm phản ánh việc không quan sát được mâu thuẫn, và case misreport C-008 kiểm grader có bắt được mâu thuẫn khi reply thực sự xuất hiện.

Tone đạt κ 0,757, precision 0,857, recall 0,800. Helpful bị loại vì κ 0,375 và recall 0,300. Xem [judge audit](judge_audit.md) và [trace case C-002@11](trace_case.md).

```text
exit 1 — blocked: refund_amount_correct, pass_rate, reply_ledger_consistent
```

## Advanced và Expert · v2

`E-swarm-20261118-9b6c` dùng eval set `9b6c6efbe185` gồm 28 item × 5 seed. Baseline pass_rate 0,9786 và pass_hat_5 0,8929. Chạy A/A với `66,77,88,99,110` cho Δ = 0 trên mọi metric báo cáo. Chọn sàn pass_hat_5 0,85, cách baseline A/A 0,0429. Chạy với LLM thật cần đo nhiều lần để ước lượng dải nhiễu trước khi đặt ngưỡng.

Slice money_movement kiểm phần item có refund, trong đó lỗi cộng điều khoản ảnh hưởng tập trung. Slice adversarial theo dõi riêng pack tấn công. Slice denial theo dõi các quyết định từ chối. Cả ba có sàn và kiểm CI riêng. `pass_hat_5` chặn lỗi làm tròn lặp lại ở một seed trong bộ hiện tại. pass@5 có thể bằng 1 ngay cả khi nhiều item không qua cả 5 lần. Với 5 lượt, lỗi có xác suất khoảng 1/3 vẫn có thể không xuất hiện trong một bộ seed.

Scorecard công khai chặn 3/3 regression và báo nhầm 0 lần. Baseline tự so sánh vẫn qua gate. Bốn trap công khai đều bị chặn khi chạy gate trực tiếp.

| Trap | Gate | Tín hiệu |
|---|---|---|
| evaluator_errors_as_nan | exit 1 | Grader thiếu kết quả hoặc metric không hữu hạn |
| dropped_failing_rows | exit 1 | Coverage thiếu dòng |
| cherry_picked_seeds | exit 1 | Seed khác spec và baseline |
| loosened_spec | exit 1 | Ratchet phát hiện hạ sàn và bỏ slice |

## Vận hành và giới hạn

Eval owner trên fork phụ trách tái hiện trial khi gate đỏ. Pilot chỉ đánh giá các ticket hoàn phí/bồi thường trong fixture. MockLLM, 14 item v1 và nhãn judge replay công khai chưa đo được chất lượng trên khách thật hoặc độ ổn định trên model thật. Cần bộ held-out được người gán nhãn và thêm seed khi thẩm định ngoài pilot. Tăng version eval set và sinh lại baseline khi thay item hoặc nhãn.
