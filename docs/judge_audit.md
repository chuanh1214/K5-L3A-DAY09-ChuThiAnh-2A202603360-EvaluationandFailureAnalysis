# Judge audit

| Tiêu chí | n | κ | Precision | Recall | Quan sát FAIL → Rogan–Gladen | Quyết định |
|---|---:|---:|---:|---:|---:|---|
| tone_ok | 100 | 0,757 | 0,857 | 0,800 | 0,28 → 0,30 | Đạt ngưỡng cho tone |
| helpful | 100 | 0,375 | 1,000 | 0,300 | 0,09 → 0,30 | Loại khỏi gate |

Ngưỡng áp dụng là κ ≥ 0,6, precision ≥ 0,8, recall ≥ 0,7. Lớp dương là FAIL. Ma trận tone có TP 24, FP 4, FN 6, TN 66. Ma trận helpful có TP 9, FP 0, FN 21, TN 70. Helpful bỏ sót 21 trong 30 lỗi, và hiệu chỉnh tỉ lệ lỗi toàn tập vẫn không khắc phục được quyết định trên từng case.

| Case | Judge | Người | Ai đúng | Sửa rubric |
|---|---|---|---|---|
| H-008 | PASS | FAIL | Người | Yêu cầu xưng hô chuyên nghiệp với khách. Thêm ví dụ về cụm “rồi nha, anh check giúp em” quá suồng sã. |
| H-017 | PASS | FAIL | Người | Khi không có cách xưng hô đã được thiết lập, dùng “anh/chị”. Đánh giá cả lời gọi “bạn ơi” và tiểu từ “nha”. |
| H-029 | PASS | FAIL | Người | Đánh giá toàn bộ câu. Phạt mệnh lệnh làm khách ngại hỏi tiếp như “không cần nhắn thêm”. |
| H-042 | FAIL | PASS | Người | Cho qua phản hồi ngắn, lịch sự, có số tiền và thời hạn. Chỉ yêu cầu xin lỗi khi tình huống có căn cứ. |
| H-051 | FAIL | PASS | Người | Cho phép thuật ngữ nghiệp vụ “refund” theo quy ước LogiX nếu cả câu vẫn rõ ràng và lịch sự. |

Tone được dùng cho tiêu chí văn phong trên replay. Các quyết định về tiền và approval dùng grader code. Cần dữ liệu gán nhãn độc lập để kiểm tra rubric đã sửa ngoài tập công khai.
