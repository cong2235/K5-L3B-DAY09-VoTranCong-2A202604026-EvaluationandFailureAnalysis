# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (judge replay, nhãn lưu sẵn trong CSV, không cần API key). Lớp dương là `FAIL`, vì việc của judge là tìm lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt (exit 0) | **dùng**, non-blocking |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không đạt κ và R (exit 1) | **loại** khỏi gate |

Ma trận nhầm lẫn (FAIL là dương):

| Tiêu chí | TP | FP | FN | TN | Tỉ lệ FAIL quan sát | Sau Rogan-Gladen |
|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 | 0.30 |
| helpful | 9 | 0 | 21 | 70 | 0.09 | 0.30 |

Với helpful, judge báo 9% reply có lỗi trong khi tỉ lệ thật là 30%. Judge này đếm thiếu hơn 3 lần.

## Case audit thủ công: tone_ok (cả 10 bất đồng)

| # | Case | Judge nói | Người nói | Ai đúng? | Hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha" | PASS | FAIL | Người | Thêm luật xưng hô: CS xưng "LogiX", gọi khách "anh/chị"; "em… nha" là FAIL. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn…" | PASS | FAIL | Người | Cùng luật xưng hô: gọi khách là "bạn" là FAIL. |
| 3 | H-029 "vui lòng chờ… không cần nhắn thêm" | PASS | FAIL | Người | Judge bị đánh lừa bởi "Dạ, vui lòng". Thêm luật: câu ra lệnh hoặc chặn khách liên hệ là FAIL dù có từ lịch sự. Thêm H-029 làm ví dụ FAIL. |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Ghi rõ: lời xin lỗi không bắt buộc; ngắn mà đủ ý là PASS. |
| 5 | H-051 "LogiX đã refund 90.000đ" | FAIL | PASS | Người | Thêm danh sách từ tiếng Anh được phép theo quy định CS LogiX ("refund"). |
| 6 | H-063 "đã hoàn 20.000đ và sẽ hoàn thêm" | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống là lỗi **nội dung**, không phải giọng điệu. Không đưa vào rubric tone; chuyển cho grader code so reply với ledger (metric FM-08). |
| 7 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Thêm luật: emoji trong ngữ cảnh khiếu nại là FAIL. |
| 8 | H-081 "chưa đủ điều kiện hoàn theo chính sách hiện hành ạ" | FAIL | PASS | **Judge** | Không sửa rubric. Sửa **nhãn người** (note: "đọc nhầm ticket"). Sau khi sửa: P 0.893, R 0.806, κ 0.784. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | Người (chấp nhận được) | Thêm luật: lỗi gõ nhỏ không đổi nghĩa thì không FAIL tone. |
| 10 | H-094 "Da, LogiX da hoan… xin loi vi su bat tien" | PASS | FAIL | Người | Thêm luật: tiếng Việt mất dấu hoặc dịch máy là FAIL. |

Tóm tắt tone: 9/10 bất đồng là judge sai, 1/10 là nhãn người sai. Judge lỏng với xưng hô và với từ lịch sự bề mặt (FN 6), và quá chặt với câu ngắn hoặc từ tiếng Anh được phép (FP 3).

## Case audit thủ công: helpful (21 bất đồng, đều là FN)

| # | Case | Judge nói | Người nói | Ai đúng? | Hành động sửa rubric |
|---|---|---|---|---|---|
| 11 | HL-015 "đã hoàn 55.000đ cho đơn O-112" (ledger 40.000đ) | PASS | FAIL | Người | Judge chỉ thấy reply, không thấy ledger, nên **không thể** chấm số tiền. Bỏ tiêu chí "đúng tiền" khỏi rubric judge; chấm bằng code (metric FM-08). |
| 12 | HL-016 reply dài, xin lỗi 2 lần, nói 55.000đ (ledger 35.000đ) | PASS | FAIL | Người | Ngoài sai tiền còn có verbosity bias: cả 13 reply dài trên 150 ký tự đều được judge PASS, người FAIL cả 13. Thêm luật: xin lỗi lặp lại không cộng điểm helpful. |
| 13 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả (hoàn bao nhiêu, hay từ chối) nên không helpful. Thêm luật: phải nêu rõ kết quả xử lý. Xưng hô thuộc rubric tone. |
| 14 | HL-091 "Ok bạn, đơn O-233 xử lý rồi nhé." | PASS | FAIL | Người | Như #13. |
| 15 | HL-020 "đã hoàn 90.000đ cho đơn O-303" (ledger 120.000đ) | PASS | FAIL | Người | Như #11. Reply ngắn, lịch sự, nên judge không có cơ sở nào để phát hiện. |

Phân loại 21 FN theo `human_failure`: **18 "sai tiền"**, 3 "sai xưng hô". Judge bắt được hết 9 lỗi còn lại (giọng cụt, không hỏi lại mã đơn, lạc đề).

## Kết luận
- **helpful bị loại khỏi gate.** κ = 0.375 < 0.6 và R = 0.30 < 0.7, dù P = 1.0. P cao chỉ nghĩa là khi judge nói FAIL thì đúng. Nó vẫn bỏ sót 21/30 reply lỗi (FN 21), và gate dùng judge này sẽ cho qua phần lớn regression. Nguyên nhân chính: 18/21 FN là sai số tiền, thứ judge chỉ đọc reply không thể biết. Đúng với quy tắc "tiền và approval luôn chấm bằng code".
- **Phạm vi dùng được của helpful.** Nếu bỏ các reply "sai tiền", judge đạt P = 1.0, R = 0.75, κ = 0.837 trên 82 reply còn lại. Có thể dùng lại helpful sau khi rút gọn rubric (chỉ chấm nêu kết quả, hỏi lại thông tin, đúng chủ đề) và **calibrate lại trên nhãn người mới**. Con số 0.837 được tính trên chính dữ liệu đã dùng để chọn phạm vi, nên chưa phải bằng chứng.
- **tone_ok dùng được nhưng để non-blocking.** Nó chạm sàn nhưng biên mỏng (P 0.857, R 0.800). Hướng sửa rubric: luật xưng hô, luật câu ra lệnh, luật emoji, luật mất dấu, danh sách từ được phép.
- **Rogan-Gladen** cho thấy tỉ lệ lỗi thật của cả hai tiêu chí khoảng 30%. Khi báo cáo tỉ lệ lỗi tone, dùng số đã hiệu chỉnh (0.30) thay vì số thô (0.28).
- **Rủi ro còn lại.** Judge chỉ được kiểm trên dữ liệu replay đã công khai, và các luật sửa rubric ở trên được rút ra từ chính dữ liệu này. Cần một tập nhãn người mới để có held-out thật. n = 100 nên khoảng tin cậy của κ còn rộng.
