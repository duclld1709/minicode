# M6: Workflow patterns

> Mục tiêu: biết **5 pattern** ghép các lần gọi LLM. Với mỗi pattern, hiểu nó giải quyết vấn đề gì,
> tốn gì, và **khi nào không nên dùng**. Mỗi pattern có một chỗ dùng thật trong minicode.

Code chính: `src/minicode/workflows/commit_msg.py`, `agent/router.py`, `agent/loop.py`
(`_execute_all`), `workflows/subagent.py`, `workflows/verifier.py`, `tools/todo.py`.

---

## 1. Khái niệm

Phân biệt hai loại: **workflow** là các bước *do code quyết định* (cố định, dễ đoán), còn **agent** là
các bước *do model quyết định* (vòng lặp M3). Năm pattern dưới đây nằm giữa hai cực đó.

### 1. Prompt chaining: `minicode commit-msg`
```
diff ──► [LLM 1: tóm tắt thay đổi] ──summary──► [LLM 2: viết commit message] ──► message
```
Chia một việc thành các bước cố định; output của bước trước là input của bước sau.
- **Lợi:** mỗi bước có một nhiệm vụ hẹp nên dễ làm tốt và dễ kiểm tra riêng. Bước 2 không phải đọc
  code, chỉ lo câu chữ. Có thể chèn kiểm tra giữa các bước.
- **Chi phí:** 2 call thay vì 1, nên độ trễ cộng dồn.
- **Khi nào:** task có các bước rõ ràng, lần nào cũng giống nhau.

### 2. Routing: `agent/router.py`
```
task ──► [small model: question | edit] ──► question: agent với tool read-only
                                       └──► edit:     agent với toàn bộ tool
```
Một call rẻ phân loại đầu vào, rồi chọn đường xử lý phù hợp. minicode dùng routing cho **an toàn**:
câu hỏi thì không thể sửa file. Routing cũng có thể dùng cho **chi phí**, ví dụ câu dễ thì dùng
model nhỏ, câu khó thì dùng model lớn.
- **Chi phí:** thêm một call small model, khoảng 300 token, gần như không đáng kể.
- **Rủi ro:** phân loại sai. Lỗi thì fallback sang `edit`, vì toàn bộ tool vẫn được permission bảo vệ,
  còn từ chối làm việc thì vô ích.

### 3. Parallelization: tool `read` chạy song song
Model thường gọi nhiều tool một lượt: "đọc 5 file này". Các tool `read` không có side effect và không
cần hỏi permission, nên **chạy cùng lúc** được. Kết quả vẫn **giữ đúng thứ tự** của call.

```
[read a][read b][read c] [edit x] [read d]
 └──── song song ─────┘   một mình  một mình
```

Một call không phải `read` là "rào chắn". Nó chạy một mình, theo thứ tự, vì có thể hỏi người dùng
hoặc phụ thuộc call trước (sửa file rồi mới chạy test).
- **Lợi:** độ trễ bằng call *chậm nhất* thay vì *tổng* các call. Với `delegate`, mỗi call là cả một
  subagent, nên lợi rất lớn.
- **Chi phí:** không tốn thêm token. Đổi lại code phức tạp hơn (thread, thứ tự, Ctrl+C).
- Biến thể khác của parallelization là *voting*: gọi N lần cùng một câu hỏi rồi lấy đa số.

### 4. Orchestrator-workers: tool `delegate`
Agent chính (orchestrator) giao một việc **độc lập, chỉ đọc** cho subagent (worker):
"tìm mọi nơi gọi `parse_config` và cho biết lỗi được xử lý thế nào". Worker có **context riêng**,
có thể đọc 30 file, và chỉ trả về bản báo cáo.
- **Lợi:** context của orchestrator chỉ tăng thêm một đoạn báo cáo, không phải 30 file. Nhiều worker
  chạy song song (pattern 3).
- **Chi phí:** worker phải tự khám phá lại từ đầu vì không thấy context của cha. Tổng token *tăng*.
  Trong lần chạy thật, câu hỏi dùng 2 delegate tốn $0.046, so với khoảng $0.02 nếu agent tự đọc 2 file.
- **Khi nào:** việc tìm kiếm rộng, hoặc nhiều nhánh độc lập. **Không** nên dùng cho việc nhỏ.

### 5. Evaluator-optimizer: `--verify "pytest -q"`
```
agent làm ──► "xong" ──► [chạy lệnh verify] ──exit 0──► thật sự xong
                ▲                 │
                └──output lỗi─────┘ (tối đa K lần kiểm tra)
```
Một bên tạo ra kết quả (optimizer), một bên đánh giá (evaluator) và trả phản hồi. Ở minicode,
evaluator là **một lệnh**, không phải LLM: exit code thì khách quan và miễn phí. Pattern này giải quyết
thẳng failure mode "agent nói đã sửa nhưng chưa chạy test" của M3.
- Evaluator cũng có thể là LLM (một "reviewer" chấm theo tiêu chí), dùng cho việc không có lệnh kiểm
  tra tự động, như văn bản hay thiết kế. Khi đó lại cần quan tâm độ tin cậy của người chấm.

### Thêm: `todo_write` / `todo_read`
Với task nhiều bước, model tự viết kế hoạch rồi cập nhật trạng thái. Lần chạy thật: model gọi
`todo_write` 4 lần (lập plan, rồi đánh dấu xong từng bước). Plan giúp model không lạc hướng sau
nhiều step, và giúp người dùng thấy agent đang ở đâu.

### Khi nào cần orchestration, khi nào một call là đủ
Hãy bắt đầu từ cách **đơn giản nhất**, và chỉ thêm độ phức tạp khi đo được lợi ích:
1. **Một call** (kèm context tốt) giải quyết được rất nhiều việc.
2. **Workflow cố định** (chaining, routing) khi các bước luôn giống nhau.
3. **Agent** (vòng lặp + tool) khi không biết trước cần bao nhiêu bước.
4. **Orchestrator-workers / evaluator** khi agent đơn lẻ bị tràn context hoặc hay "xong" sai.

| Pattern | Số call LLM | Độ trễ | Rủi ro chính |
|---|---|---|---|
| Một call | 1 | thấp | thiếu thông tin |
| Chaining | n (cố định) | cộng dồn | lỗi bước đầu lan ra sau |
| Routing | +1 (nhỏ) | +1 call nhỏ | phân loại sai |
| Parallel tools | không đổi | giảm | race condition, thứ tự |
| Orchestrator-workers | nhiều hơn hẳn | song song nên vừa phải | worker thiếu ngữ cảnh, tốn token |
| Evaluator-optimizer | ×(số vòng) | ×(số vòng) | evaluator yếu nên "pass" sai |

---

## 2. Vì sao thiết kế như vậy

| Quyết định | Phương án khác | Lý do chọn |
|---|---|---|
| Commit message dùng small model | Model chính | Việc hẹp, rõ ràng. Rẻ hơn khoảng 20 lần |
| Router dùng `complete_structured` (M1) | Parse chuỗi "question"/"edit" | Có schema, có retry, có `reason` để debug |
| `MeteredLLM` bọc client để đếm usage | Đổi `complete_structured` để trả usage | Không đổi API của M1. Dùng lại được cho mọi tác vụ phụ |
| Chỉ chạy song song các call `read` **liên tiếp** | Chạy song song mọi call | Thao tác ghi và lệnh có thể phụ thuộc nhau, và cần hỏi permission tuần tự |
| Thu kết quả theo từng future, đúng thứ tự | `list(pool.map(...))` | Khi Ctrl+C, các kết quả đã xong không bị mất (đây là bug mình đã gặp, xem MILESTONES) |
| Subagent không có `delegate` | Cho phép đệ quy | Tránh cây subagent nổ chi phí. Một tầng là đủ |
| Usage của subagent cộng vào cha (`add_usage`) | Bỏ qua | Budget `--max-cost` phải tính *mọi* token mà task tiêu |
| Evaluator là lệnh shell | LLM chấm điểm | Khách quan, miễn phí, không bị "thuyết phục" |
| Không verify khi agent dừng vì guard hoặc Ctrl+C | Verify luôn | Tôn trọng giới hạn người dùng đặt. Không tự kéo dài thêm vòng |
| `todo_write` thay cả danh sách | Thêm, sửa, xóa từng item | Không có logic cập nhật từng phần để sai. Model luôn gửi trạng thái đầy đủ |

---

## 3. Pitfalls

- **Dùng pattern phức tạp khi không cần**: orchestrator-workers cho câu hỏi về một file thì tốn gấp
  đôi mà không tốt hơn.
- **Chaining mà bước 2 vẫn nhận nguyên input gốc**: mất lợi ích tách bước. Bước sau chỉ nên thấy
  đúng thứ nó cần.
- **Router không có fallback**: một JSON hỏng làm hỏng cả task.
- **Chạy song song cả thao tác ghi**: hai `edit_file` cùng một file thì kết quả phụ thuộc thời điểm chạy.
- **Mất thứ tự kết quả**: model ghép nhầm kết quả của call A vào call B.
- **`pool.map` và exception**: một worker lỗi làm mất cả lô kết quả đã xong.
- **Assertion bằng chuỗi con quá yếu**: `"ran" in content` khớp luôn với câu
  "Interrupted … ran.". Hãy kiểm tra thêm `is_error` hoặc so sánh chính xác hơn.
- **Subagent có quyền ghi**: một worker "tự ý" sửa code mà orchestrator không biết.
- **Quên tính token của subagent**: budget hiển thị thấp hơn chi phí thật.
- **Evaluator-optimizer không giới hạn vòng**: test hỏng vĩnh viễn kéo theo vòng lặp vô hạn.
- **Agent "sửa" test để verify pass**: prompt feedback có câu "Do not … weaken the tests".
  Phòng thủ thật là người dùng review diff, hoặc chạy test bằng một bản kiểm tra không cho agent sửa.

---

## 4. Bài tập tự code lại

1. `llm/metered.py`: `MeteredLLM` (có lock).
2. `workflows/commit_msg.py`: `read_diff` (staged trước, rồi unstaged, rồi `NoChangesError`) và
   `write_commit_message` (2 call). Thêm lệnh `minicode commit-msg`.
3. `agent/router.py`: `TaskRoute`, `Router.route` (fallback `edit`). Trong `Agent`: `_choose_tools`
   và `ToolRegistry.subset`.
4. `Agent._execute_all` và `_execute_parallel`.
   *Gợi ý:* viết `test_independent_reads_really_run_concurrently` với `threading.Barrier` trước.
   Barrier chỉ mở khi mọi call cùng chạy, nên test không phụ thuộc thời gian.
5. `workflows/subagent.py`: `DelegateTool`, rồi `Agent.add_usage` (có lock).
6. `workflows/verifier.py`: `run_with_verification` với `run_check` được inject; `ShellTool.run`;
   option `--verify`.
7. `tools/todo.py`: `TodoList`.

Marker cần pass: `uv run pytest -m m6`.

---

## 5. Gợi ý cải tiến

- Router 3 nhánh: `question`, `small-edit` (dùng model nhỏ), `big-edit` (dùng model lớn). Đo bằng eval (M7).
- Evaluator bằng LLM cho task không có test: "reviewer" chấm diff theo checklist rồi trả góp ý.
- Chạy evaluator **trong** vòng lặp (sau mỗi lần edit) thay vì chỉ khi agent báo xong.
- `delegate` có thêm tham số `tools` để orchestrator chọn bộ tool cho worker.
- Hiển thị tiến trình của subagent (đang ở step mấy) trong UI.
- Giới hạn tổng số subagent trong một task.
- `commit-msg --commit` để commit luôn sau khi người dùng xác nhận.
- Chạy song song cả các call `exec` khi người dùng đã đánh dấu "always", ví dụ nhiều lệnh `pytest -k`.

---

## 6. Câu hỏi tự kiểm tra

1. Workflow và agent khác nhau ở điểm nào? Mỗi pattern trong 5 pattern ở trên gần với bên nào hơn?
2. Vì sao chỉ các tool `read` liên tiếp mới chạy song song? Cho ví dụ hai call mà chạy song song sẽ sai.
3. Orchestrator-workers *tăng* tổng token nhưng vẫn có thể là lựa chọn tốt. Khi nào? Khi nào không?
4. Với `--verify "pytest -q"`, agent có thể "gian lận" thế nào để verify pass? Bạn phòng thủ ra sao?
5. Router của minicode phân loại sai một task "edit" thành "question". Điều gì xảy ra với agent?
   Còn chiều ngược lại?
