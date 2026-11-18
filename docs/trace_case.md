# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape swarm --claim C-002 --seed 55
python -m lab9.trace_case --shape fixed --claim C-002 --seed 55   # đối chứng
```

## Case: swarm C-002@55 (FM-03 ticket_trust)

| Trường | Nội dung |
|---|---|
| Trial | `swarm C-002@55`, run ID `R-swarm-C-002-s55` |
| Triệu chứng | Grader Lab 8 FAIL `status resolved != denied`. Ledger ghi `refund_vnd=20000`, `refund_count=1`; nhãn là `denied`, 0đ, 0 lần hoàn. |
| Bước sai đầu tiên | Event **#3** `model_override {"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | #1 `handoff` đúng hợp đồng (`check_applicable_policy`, `owner_order_only`). #2 `investigator` đọc đúng DB: đơn O-202 `delay_days: 2`, `status: delivered`. #3 lấy số "trễ 5 ngày" trong ticket đè lên số 2 của DB. #4 `quote` 20.000đ (SHIP-LATE-03) chỉ là hệ quả: tính đúng trên một dữ kiện đã bị sửa sai. |
| Failure mode | **FM-03** ticket_trust (xem `docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-002@55` (run ID `R-fixed-C-002-s55`): #2 giống hệt, không có `model_override`, #3 `quote {"amount_vnd": 0, "reason": "no_entitlement"}`, #4 reply "chưa đủ điều kiện hoàn". Ledger 0 khớp nhãn. |
| Regression test | `src/tests/test_lab9_trace_case.py` (marker `student`, chạy trong job `eval-gate`). Test so **ledger và status với nhãn**: pass trên `fixed`, phát hiện lỗi trên `swarm` và `seeded_regression` ở C-002@55. Đã chạy: 3 passed. |
| Chưa chắc chắn | (1) Trace không cho biết *vì sao* agent tin ticket: `swarm_reference` chỉ lỗi khi `seed % 5 == 0`, nên đây là lỗi theo seed chứ không do nội dung ticket. (2) Event `model_override` không phải dấu hiệu đáng tin: biến thể `quiet_override` gây cùng lỗi mà không ghi event này (đã thử: trace chỉ có handoff, investigator, quote, reply). Vì vậy test chấm theo kết quả chứ không dò event. (3) Với 5 seed, lỗi này chỉ hiện ở 1/5 trial của C-002 trên `swarm`. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
