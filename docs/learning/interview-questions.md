# Câu hỏi phỏng vấn fresher AI Engineer, xoay quanh minicode

Mỗi câu có **gợi ý trả lời**: các ý chính, kèm file hoặc hàm trong minicode để bạn mở ra minh họa.
Hãy tập trả lời bằng lời của mình, rồi dẫn chứng bằng code ("trong project của em, chỗ này nằm ở…").

---

## A. LLM cơ bản

**1. Vì sao gọi LLM là "stateless"? Chatbot nhớ hội thoại bằng cách nào?**
Mỗi request là độc lập. Client giữ lịch sử và gửi lại toàn bộ ở mỗi lượt. Hệ quả: chi phí và độ trễ
tăng theo độ dài hội thoại.
→ `chat.ChatSession.send`, test `test_every_turn_resends_the_whole_history`, `store=False` trong
`llm/openai_client.py`.

**2. Token là gì? Vì sao input token tăng dần qua mỗi bước của agent?**
Token là đơn vị model đọc và tính tiền. Mỗi step gửi lại lịch sử đã dài thêm (tool call cộng kết quả).
→ Trace thật trong `docs/learning/m7-observability-evals.md` (input tăng từ 1.391 lên 2.757); `llm/pricing.estimate_cost`.

**3. Vì sao LLM hallucinate? Coding agent giảm hallucination thế nào?**
Model sinh token có xác suất cao chứ không kiểm chứng sự thật. Cách giảm: cho model tool để kiểm chứng
(đọc file thật, chạy test thật), và yêu cầu "do not claim it works unless you checked".
→ `agent/prompts.TOOL_RULES`, `--verify` (`workflows/verifier.py`).

**4. Reasoning model khác standard model thế nào? Khi nào dùng loại nào?**
Reasoning model "nghĩ" trước khi trả lời: tốt cho việc nhiều bước, nhưng chậm và đắt, và phần suy nghĩ
cũng tính là output token. Việc đơn giản (routing, tóm tắt) thì dùng model nhỏ.
→ `out 133` cho câu trả lời 5 chữ ở M0; `MINICODE_SMALL_MODEL`, `agent/router.py`.

**5. Structured output: làm sao bảo đảm model trả về JSON đúng schema?**
Đưa schema vào prompt, validate bằng pydantic, và khi sai thì gửi lại lỗi cụ thể để model sửa (có giới
hạn số lần). Ngoài ra provider có chế độ structured output native.
→ `llm/structured.complete_structured`, `format_validation_error`.

## B. Tool use & agent loop

**6. Khi model "gọi tool", ai thực sự chạy tool đó?**
Model chỉ *đề xuất* một tool call (tên và argument dạng JSON). Code của mình quyết định có chạy hay
không, và đây là điểm đặt mọi hàng rào an toàn.
→ `agent/loop.Agent._execute`, `PermissionPolicy.decide`.

**7. Mô tả vòng lặp của một agent. Khi nào nó dừng?**
Lặp: guard, gọi LLM, không có tool call thì dừng, có thì chạy tool rồi append kết quả, sau đó compact.
Các lý do dừng: `completed`, `max_steps`, `token_budget`, `cost_budget`, `wall_time`, `interrupted`,
`output_truncated`.
→ `Agent._loop`, `Guards.check`.

**8. Vì sao `ToolRegistry.execute` không bao giờ raise exception?**
Lỗi là thông tin cho model: thông điệp rõ ràng giúp model tự sửa ở lượt sau, còn raise thì agent sập.
Các loại lỗi: tool không tồn tại, JSON hỏng, sai schema, handler lỗi, output quá dài.
→ `tools/base.ToolRegistry.execute`, `ToolError`, `tests/contract/test_m2_registry.py`.

**9. Vì sao `edit_file` dùng "exact string replace, old_string phải duy nhất"?**
Diff và số dòng dễ sai với LLM; viết lại cả file thì tốn token và dễ mất code. Yêu cầu duy nhất để
không sửa nhầm chỗ. Thêm xử lý CRLF.
→ `tools/fs.FileTools.edit_file`.

**10. Người dùng bấm Ctrl+C giữa chừng. Điều gì phải được bảo đảm?**
Dừng êm, giữ lịch sử, và mọi tool call đều phải có result (provider từ chối lịch sử có tool call mồ côi).
Các kết quả đã xong (kể cả khi chạy song song) không được mất.
→ `Agent._close_dangling_tool_calls`, `_execute_parallel` (thu từng future), MILESTONES M6 (bug đã sửa).

**11. Thiết kế description cho tool thế nào để model dùng đúng?**
Nói khi nào dùng, output trông thế nào, và các ràng buộc. Ví dụ: số dòng không phải là một phần của
file, nên đừng copy vào `old_string`. Description chính là prompt của tool.
→ `READ_FILE_DOC`, `EDIT_FILE_DOC` trong `tools/fs.py`; `Field(description=...)`.

## C. An toàn

**12. Prompt injection là gì? Minicode phòng thủ ra sao?**
Nội dung bên ngoài (file, output lệnh, MCP) chứa chỉ thị độc hại. Phòng thủ nhiều lớp: đánh dấu dữ liệu
bằng `<tool_output>`, sandbox, denylist, và permission. Phòng tuyến thật là guard, không phải prompt.
→ `prompts.wrap_tool_output`, `tests/contract/test_m5_prompt_injection.py`, eval `injection_*`.

**13. Vì sao denylist không đủ? Lớp chính là gì?**
Luôn có cách viết khác để lách (`python -c "shutil.rmtree(...)"`). Lớp chính là con người duyệt ở mode
`ask`. Denylist chỉ chặn thảm họa hiển nhiên, ở mọi mode.
→ `agent/guards.DANGEROUS_COMMANDS`, `_needs_prompt`; giới hạn của `auto` được ghi trong test.

**14. Sandbox đường dẫn hoạt động thế nào? Vì sao không kiểm tra chuỗi `".."`?**
`Path.resolve()` (xử lý cả `..` và symlink) rồi `is_relative_to(root)`. Kiểm tra chuỗi bỏ sót symlink,
absolute path và các dạng biến thể. Kết quả của `glob` phải được kiểm tra lại.
→ `tools/fs.resolve_in_workspace`, `FileTools.glob`, `_is_searchable`.

**15. Làm sao bảo đảm API key không bị lộ?**
`SecretStr` trong settings; xóa biến `*_API_KEY` khỏi môi trường của `run_bash`; MCP chỉ nhận whitelist
biến môi trường; trace mask mọi dòng trước khi ghi.
→ `config.Settings`, `tools/shell.scrubbed_env`, `tracing.mask_secrets`, test đọc `.env` trong `test_m7_tracing.py`.

## D. Context & harness engineering

**16. Context engineering khác prompt engineering ở điểm nào?**
Prompt engineering lo *câu chữ*; context engineering quyết định *đưa thông tin gì* vào context ở mỗi
bước: memory, skill, kết quả tool, compaction.
→ `agent/prompts.build_system_prompt` (các section), `harness/`.

**17. Skills với progressive disclosure là gì? Vì sao không nhét hết vào system prompt?**
System prompt chỉ có tên và mô tả; nội dung chỉ được nạp qua `load_skill` khi cần. Cách này tiết kiệm
token ở mọi request và không làm loãng sự chú ý của model.
→ `harness/skills.py`, `test_skill_body_is_loaded_only_when_called`, trace thật trong ghi chú M5.

**18. Context compaction hoạt động thế nào? Có những rủi ro gì?**
Hai giai đoạn: xóa tool result cũ và dài, rồi tóm tắt bằng model nhỏ. Rủi ro: cắt giữa tool call và
result (lỗi 400), làm mất task gốc (vì vậy giữ nguyên văn yêu cầu), hoặc compact liên tục.
→ `agent/context.Compactor`, `split_index`, `summary_message`.

## E. Workflow patterns

**19. Kể 5 workflow pattern. Mỗi pattern dùng ở đâu trong project?**
Chaining (`commit-msg`), routing (`Router`), parallelization (tool `read` song song), orchestrator-workers
(`delegate`), evaluator-optimizer (`--verify`).
→ `workflows/`, `agent/router.py`, `Agent._execute_all`.

**20. Khi nào **không** nên dùng multi-agent (orchestrator-workers)?**
Việc nhỏ hoặc cần chung ngữ cảnh: worker phải khám phá lại từ đầu, tổng token tăng lên. Hợp với tìm kiếm
rộng hoặc các nhánh độc lập. Con số thật: 2 delegate tốn khoảng $0.046.
→ `workflows/subagent.DelegateTool`, ghi chú M6.

**21. Chạy tool song song: cần lưu ý gì?**
Chỉ chạy song song các call không có side effect và không cần hỏi permission. Giữ đúng thứ tự kết quả.
Xử lý exception và Ctrl+C mà không làm mất kết quả đã xong.
→ `Agent._execute_all`, `test_m6_parallel.py` (dùng `threading.Barrier`).

## F. MCP

**22. MCP giải quyết vấn đề gì? Khác gì tự định nghĩa tool?**
Một giao thức chung giảm số tích hợp từ N×M xuống N+M. Server tự mô tả tool và tự validate. Rủi ro:
code của bên thứ ba và tool poisoning, nên minicode gán risk `exec`.
→ `mcp/server.py` (bọc `ToolRegistry`), `mcp/client.py`, `tests/contract/test_m4_mcp.py`.

**23. MCP SDK là async, agent loop là sync. Bạn nối hai bên thế nào?**
Mỗi kết nối có một event loop riêng trong thread nền, giữ `Client` mở; handler gọi
`run_coroutine_threadsafe(...).result(timeout)`.
→ `mcp/client.McpConnection`.

## G. Observability, eval, kỹ thuật phần mềm

**24. Unit test khác eval thế nào? Làm sao viết check cho eval mà không bị "gian lận"?**
Unit test thì tất định và kiểm tra một hàm; eval thì đo hành vi của cả hệ thống bằng pass rate.
Check phải chấm hành vi: chạy bộ test gốc trên code của agent, dùng hidden checks, xem các tool call
đã thử. Check cũng cần test riêng (check quá chặt từng làm fail một agent tốt).
→ `evals.original_tests_pass`, `test_untouched_fixture_and_empty_answer_fail`, mục "Chuyện có thật" trong ghi chú M7.

**25. Làm sao test một hệ thống dùng LLM mà không tốn tiền và không flaky?**
Dependency injection ở mọi nơi; `FakeLLMClient` trả lời theo kịch bản; stub SDK trả object đúng format
thật; fake clock cho test wall time; live test chỉ chạy khi có cờ `--run-live`.
→ `llm/fake_client.py`, `tests/contract/test_m1_adapters.py`, `tests/conftest.py`.

**26. Đọc trace thế nào để debug một agent chạy kém?**
Tìm tool call lặp lại cùng một lỗi, input token tăng vọt, `end_turn` mà không có lần edit nào, hay
latency cao. Từ đó sửa thông điệp lỗi, giới hạn output, prompt hoặc model.
→ `tracing.py`, `minicode replay`, bảng triệu chứng trong ghi chú M7.

**27. Vì sao chọn chi phí theo model nhỏ hay lớn? Dữ liệu nào hỗ trợ quyết định?**
Đo bằng eval. Kết quả thật: cả `gpt-6.1-sol` và `gpt-6-luna` đều đạt 9/9, nhưng chi phí chênh 13 lần.
Kết luận đúng là bộ eval đã bão hòa và cần task khó hơn.
→ `evals/results/`, `python evals/run_evals.py --compare ...`.

---

## Mẹo trình bày project trong phỏng vấn
- Mở đầu bằng **một câu**: "Coding agent kiểu Claude Code tự viết từ đầu, không dùng framework; có
  guard, MCP và eval".
- Chuẩn bị **một sơ đồ** (README) và **một trace thật** (`minicode replay`).
- Kể **một bug thật** mình đã tìm ra: kết quả của tool chạy song song bị mất khi Ctrl+C, hoặc check
  eval quá chặt. Kể bằng trình tự: triệu chứng, cách điều tra, nguyên nhân gốc, cách sửa, test chống tái phát.
- Nói rõ **giới hạn**: chưa có sandbox thật, bộ eval còn nhỏ. Người phỏng vấn đánh giá cao sự trung thực.
