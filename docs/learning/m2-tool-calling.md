# M2: Tool calling

> Mục tiêu: cho model "tay chân", gồm đọc file, tìm kiếm, sửa code và chạy lệnh, theo cách **an toàn
> và tự sửa được khi sai**.

Code chính: `src/minicode/tools/base.py`, `tools/fs.py`, `tools/shell.py`, `tools/toolbelt.py`.

---

## 1. Khái niệm

### Model chỉ *đề xuất*, code của mình mới *thực thi*
Đây là ý quan trọng nhất của M2. Khi bạn gửi danh sách tool kèm schema, model **không chạy gì cả**.
Nó chỉ trả về một yêu cầu kiểu:

```json
{"type": "function_call", "name": "read_file", "arguments": "{\"path\": \"src/calc.py\"}"}
```

Từ đó, mọi thứ do code của mình quyết định: có chạy không, chạy thế nào, trả về gì.
Đây chính là chỗ đặt hàng rào an toàn: sandbox (M2), permission và denylist (M3).

Một lượt tool use đầy đủ (xem `test_one_tool_use_turn_with_fake_llm`):

```
user: "Echo hi 3 lần"
  → LLM: tool_call(echo, {text: "hi", times: 3})        # đề xuất
  → registry.execute(call) → ToolResult("hihihi")       # mình thực thi
  → gửi lại LLM: [user, assistant(tool_call), tool(result)]
  → LLM: "The tool said hihihi."                         # trả lời cuối
```

### Schema sinh từ pydantic
Mỗi tool có một `input_model` (pydantic). Từ model đó ta có hai thứ:
1. `model_json_schema()` là JSON Schema gửi cho model, để nó biết tham số là gì;
2. `model_validate(arguments)` để kiểm tra argument model gửi về **trước khi** chạy handler.

Một nguồn sự thật cho cả hai, nên schema không bao giờ lệch với code.

### Description là "prompt" của tool
Model chỉ biết về tool qua `name`, `description` và `Field(description=...)`. Description tốt cần nói:
- **khi nào** dùng tool. Ví dụ "For changing part of an existing file, prefer edit_file";
- **output trông thế nào**. Ví dụ "lines prefixed with their line number (the number and a tab are not
  part of the file)". Câu này giúp model không copy cả số dòng vào `old_string`;
- **ràng buộc**. Ví dụ "old_string must be unique".

### Lỗi là thông tin, không phải exception
`ToolRegistry.execute` **không bao giờ raise**. Mọi lỗi đều thành `ToolResult(is_error=True)` với
thông điệp hướng dẫn cách sửa:

| Tình huống | Thông điệp gửi cho model |
|---|---|
| Tool không tồn tại | `Unknown tool 'read'. Available tools: read_file, list_dir, ...` |
| JSON hỏng | `Arguments for 'x' were not valid JSON: ... Send a single JSON object.` |
| Sai schema | `Invalid arguments for 'echo': text: Field required; times: Input should be a valid integer. Expected JSON schema: {...}` |
| Lỗi dự kiến (`ToolError`) | `old_string appears 2 times... Include more surrounding lines...` |
| Bug trong handler | `Tool 'x' crashed: RuntimeError: ...` |
| Output quá dài | giữ đầu và cuối, kèm `... [truncated 90 lines] ...` |

Model rất giỏi tự sửa khi được biết *chính xác* sai ở đâu. Nếu agent crash vì model gõ nhầm tên tool,
nó sẽ không bao giờ đi xa được.

### Vì sao `edit_file` dùng exact string replace
Có ba cách phổ biến để model sửa file:
- **viết lại cả file**: dễ, nhưng tốn token và dễ làm mất code;
- **diff hoặc patch**: model hay sai số dòng, sai format;
- **exact replace**: model copy đúng đoạn cần sửa và đưa đoạn thay thế.

Exact replace là cách các coding agent hiện nay hay dùng. Yêu cầu `old_string` **duy nhất** để
không bao giờ sửa nhầm chỗ. Khi không duy nhất, mình trả lỗi để model thêm ngữ cảnh.

---

## 2. Vì sao thiết kế như vậy

| Quyết định | Phương án khác | Lý do chọn |
|---|---|---|
| Handler nhận **một** object pydantic đã validate | `handler(**kwargs)` | Có type đầy đủ, handler không phải tự kiểm tra input |
| Lỗi dự kiến dùng `ToolError`, lỗi bất ngờ thì bắt `Exception` | Trả chuỗi lỗi từ handler | Handler viết tự nhiên (raise). Registry phân biệt được "lỗi có hướng dẫn" với "bug" |
| Truncate giữ **đầu và cuối** | Chỉ giữ phần đầu | pytest và compiler in tóm tắt hoặc lỗi ở *cuối* output |
| Sandbox nằm trong `resolve_in_workspace`, gọi ở mọi tool fs | Kiểm tra một lần ở agent loop | Kiểm tra ngay tại chỗ dùng path, nên không tool nào "quên". `resolve()` xử lý luôn `..` và symlink |
| Exit code khác 0 của `run_bash` **không** phải tool error | Coi là lỗi | Test fail là *thông tin* agent cần đọc, không phải lỗi của tool |
| Bỏ biến `*API_KEY*`, `*TOKEN*`... khỏi env của subprocess | Truyền nguyên env | Một lệnh `env` hay `printenv` (có thể do prompt injection) sẽ làm lộ key |
| Chuẩn hóa CRLF khi edit rồi khôi phục | Bỏ qua | Model luôn viết `\n`. Không chuẩn hóa thì mọi edit trên file Windows đều "not found" |
| `find_bash` ưu tiên Git Bash trên Windows | `shutil.which("bash")` | `bash` trên PATH của Windows thường là launcher WSL, chạy ở filesystem khác |
| `read_file` có `limit ≤ 500` và registry cắt ở 600 dòng | Đọc cả file | Không làm tràn context. Ngưỡng của registry cao hơn `limit` nên một trang đọc bình thường không bị cắt. Footer `use offset to read more` chỉ cho model cách đọc tiếp |

---

## 3. Pitfalls

- **Raise exception từ `execute`**: một lỗi nhỏ làm sập cả agent loop.
- **Thông điệp lỗi chung chung** kiểu "Error" hay "Invalid input": model không biết sửa gì và sẽ lặp lại lỗi.
- **Kiểm tra sandbox bằng chuỗi** (`".." in path`): bỏ sót symlink, absolute path và `a/../../x`.
  Hãy dùng `resolve()` rồi `is_relative_to(root)`.
- **`glob` với pattern chứa `..`**: `Path.glob("../*")` thoát được ra ngoài. Phải kiểm tra lại *kết quả*.
- **Đánh số dòng nhưng không nói rõ** trong description: model copy cả `"     2\t"` vào `old_string`.
- **Đọc và ghi bằng `read_text()` / `write_text()` trên Windows**: newline bị chuyển đổi ngầm.
  Hãy dùng bytes.
- **Quên timeout cho `run_bash`**: `pytest --pdb` hay `python` (REPL) treo vĩnh viễn. Hãy đặt
  `stdin=DEVNULL` để lệnh tương tác thoát ngay.
- **Tách stdout và stderr**: model mất thứ tự giữa log và lỗi. Gộp vào một luồng thì dễ đọc hơn.
- **Trả quá nhiều output**: một lệnh `grep` trên cả repo có thể tốn hàng chục nghìn token.

---

## 4. Bài tập tự code lại

1. `tools/base.py`:
   - `Tool` (dataclass), `ToolError`;
   - `ToolRegistry.register` (kiểm tra tên trùng hoặc không hợp lệ), `schemas`;
   - `ToolRegistry.execute`: lần lượt xử lý tool lạ, JSON hỏng, validate, gọi handler, bắt lỗi, truncate;
   - `truncate_output` (đầu + cuối).

   → `uv run pytest -m m2 tests/contract/test_m2_registry.py`
2. `tools/fs.py`:
   - `resolve_in_workspace` (*gợi ý:* `Path.resolve()` + `Path.is_relative_to()`);
   - `read_text` (phát hiện binary bằng byte `\0`) và `write_text` (bytes);
   - `read_file`, rồi `list_dir`, `glob`, `grep`, `write_file`;
   - `edit_file`: đếm số lần xuất hiện, xử lý CRLF.

   → `uv run pytest -m m2 tests/contract/test_m2_fs_tools.py`
3. `tools/shell.py`:
   - `find_bash`, `scrubbed_env`;
   - `run_bash`: `subprocess.run([bash, "-c", cmd], cwd=..., env=..., stdin=DEVNULL, stdout=PIPE,
     stderr=STDOUT, timeout=...)`.

   → `tests/contract/test_m2_shell.py`
4. `tools/toolbelt.py`: `build_registry(root, environ=...)`.

Marker cần pass: `uv run pytest -m m2`.

---

## 5. Gợi ý cải tiến

- `edit_file` có thêm `replace_all` (đổi tên biến trong một file), hoặc `multi_edit` (nhiều chỗ một lần).
- Ghi nhớ "đã đọc file chưa": từ chối `edit_file` nếu file chưa được `read_file` hoặc đã bị đổi từ
  lần đọc cuối. Claude Code làm vậy để tránh sửa mù.
- `grep` dùng `ripgrep` nếu có (nhanh hơn nhiều), và tôn trọng `.gitignore`.
- Timeout hiện chỉ kill tiến trình `bash`, chưa kill tiến trình con. Thử dùng process group
  (`start_new_session=True` + `os.killpg`).
- Cho `run_bash` chạy nền các lệnh lâu (dev server) kèm tool đọc log.
- Rút gọn JSON schema gửi cho model (bỏ `title`) để tiết kiệm token.
- Trả về diff ngắn sau `edit_file` để model tự kiểm tra.

---

## 6. Câu hỏi tự kiểm tra

1. Khi model "gọi" `run_bash("rm -rf /")`, tại thời điểm nào lệnh thật sự chạy? Ai quyết định?
2. Vì sao `execute` trả `ToolResult(is_error=True)` thay vì raise? Điều gì xảy ra với agent nếu raise?
3. Path `src/../../etc/passwd` và một symlink `link -> /etc` bị chặn ở dòng code nào? Vì sao kiểm tra
   chuỗi `".."` là chưa đủ?
4. Vì sao `pytest` fail (exit code 1) không bị coi là tool error?
5. Bạn sẽ viết description cho tool `edit_file` thế nào để model không copy số dòng vào `old_string`?
