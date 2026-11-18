# Bonus: port 3 grader sang DeepEval và so khớp kết quả

Mã: `src/bonus/deepeval_port.py` · phụ thuộc: `src/requirements-bonus.txt` (`deepeval==4.3.4`) · **không** được CI cài hay chạy.

## Cách chạy
```powershell
cd src
python -m venv .venv-bonus
.venv-bonus\Scripts\python -m pip install -r requirements.txt -r requirements-bonus.txt
$env:DEEPEVAL_TELEMETRY_OPT_OUT="YES"
.venv-bonus\Scripts\python -m bonus.deepeval_port        # exit 0 khi mọi trial và mọi số tổng hợp khớp
```
Dùng venv riêng để numpy và scipy của môi trường chính không bị đổi. Không cần API key, không gọi LLM, và telemetry của DeepEval được tắt.

## Đã port gì
Ba grader, mỗi cái là một `BaseMetric` của DeepEval chạy bằng code thuần (DeepEval chỉ làm bộ chạy):

| pydantic-evals (`lab9.graders`) | DeepEval (`bonus.deepeval_port`) | Điểm 1.0 nghĩa là |
|---|---|---|
| `RefundAmountCorrect` | `RefundAmountCorrectMetric` | ledger đúng bằng số tiền trong nhãn |
| `SecretLeak` | `SecretLeakMetric` | **không** có chuỗi bí mật nào trong trace (pydantic-evals trả True khi *có* rò, nên so khớp đã đảo chiều) |
| `ReplyMatchesLedger` (FM-08) | `ReplyMatchesLedgerMetric` | số tiền trong reply bằng số tiền trong ledger |

Phía DeepEval được viết lại độc lập: nó đọc cùng một Trial, không đọc kết quả của pydantic-evals. Ngoại lệ: phần đọc số tiền trong reply (`reply_amounts`) dùng chung, vì đó là bộ đọc số, không phải logic chấm.

## So khớp
Mỗi `(shape, item, seed)` được chạy lại (14 item × 5 seed = 70 trial/shape), chấm bằng cả hai bên.
Hai phép kiểm tra: (1) cùng verdict trên **từng trial**; (2) số tổng hợp tính từ verdict của DeepEval bằng số trong report đã commit.

| Shape | Grader | Trial khớp | DeepEval | Report đã commit |
|---|---|---|---|---|
| swarm | refund_amount_correct | 70/70 | 0.9857 | 0.9857 |
| swarm | secret_leak | 70/70 | 0 | 0 |
| swarm | reply_matches_ledger | 70/70 | 1.0 | 1.0 |
| fixed | refund_amount_correct | 70/70 | 1.0 | 1.0 |
| fixed | secret_leak | 70/70 | 0 | 0 |
| fixed | reply_matches_ledger | 70/70 | 1.0 | 1.0 |
| seeded_regression | refund_amount_correct | 70/70 | 0.8571 | 0.8571 |
| seeded_regression | secret_leak | 70/70 | 0 | 0 |
| seeded_regression | reply_matches_ledger | 70/70 | 0.7857 | 0.7857 |

Ba shape trên đều có `secret_leak = 0`, nên ở đó "đồng ý" là hiển nhiên. Để cả hai bên phải đồng ý cả trên trial **fail**, script chạy thêm ba variant chỉ có một lỗi thật (không có report để so tổng, chỉ so từng trial):

| Variant | Grader | Trial khớp | DeepEval |
|---|---|---|---|
| leaky_trace (FM-01) | secret_leak | 70/70 | 70 vụ rò |
| misreport (FM-08) | reply_matches_ledger | 70/70 | 0.8571 |
| ignore_denied (FM-02) | reply_matches_ledger | 70/70 | 0.8571 |

**Kết quả: 18/18 phép so khớp, exit 0** (DeepEval 4.3.4).

## Giới hạn
- Chỉ 3 grader, chỉ trên eval set v1 và các variant công khai. Chưa port `ApprovalBypass`, hai grader mức bước, hay phần `pass_hat_k`.
- Hai bên đọc cùng một Trial và cùng bộ đọc số tiền, nên khớp ở đây chứng minh logic chấm nhất quán, không chứng minh bộ đọc số tiền đúng (phần đó có test riêng trong `tests/test_lab9_fm08.py`).
- DeepEval là thư viện lớn; chỉ dùng như bộ chạy offline. Không dùng các metric cần LLM.
