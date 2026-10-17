# M0 — Setup & lần gọi LLM đầu tiên

> Mục tiêu: gọi được model, chat nhiều lượt, thấy token và chi phí. Qua đó hiểu một
> điều nền tảng mà mọi phần sau đều dựa vào: **LLM không nhớ gì cả, mình phải gửi lại
> toàn bộ lịch sử ở mỗi lượt.**

Code chính: `src/minicode/llm/types.py`, `llm/base.py`, `llm/fake_client.py`,
`llm/openai_client.py`, `llm/pricing.py`, `config.py`, `chat.py`, `cli.py`.

---

## 1. Khái niệm

### Token
Model không đọc chữ mà đọc **token**, tức các mảnh từ do tokenizer cắt ra. Với tiếng Anh,
1 token ≈ 4 ký tự ≈ ¾ từ. Tiếng Việt có dấu thường tốn token hơn cho cùng một ý.
Giá API và giới hạn của model đều tính bằng token. Ví dụ, `gpt-6.1-sol` có giá
$2 / 1M token input và $10 / 1M token output (giá tại thời điểm viết, xem `pricing.py`).
Token output thường đắt hơn input khoảng 4–5 lần.

Với **reasoning model**, phần "suy nghĩ" ẩn cũng được tính là output token. Khi chạy thử
`minicode chat` với `gpt-6.1-sol`, câu trả lời chỉ 5 chữ vẫn báo `out 133`, vì phần lớn trong
đó là reasoning token (`usage.output_tokens_details.reasoning_tokens`).

### Context window
Đây là số token tối đa model "nhìn thấy" trong một lần gọi, tính chung system prompt,
toàn bộ lịch sử, định nghĩa tool **và** phần output. Chat càng dài thì mỗi lượt càng
tốn input token, vì cả lịch sử bị gửi lại. Bạn sẽ thấy rõ điều này khi chạy `minicode chat`:
số `in` tăng dần theo từng lượt. Đến M5 mình sẽ làm *compaction* để xử lý chuyện này.

### Temperature
Tham số này điều chỉnh độ ngẫu nhiên khi chọn token tiếp theo. Gần 0 thì ổn định, ít sáng tạo;
cao hơn thì đa dạng nhưng dễ "bay" hơn. Agent viết code thường muốn ổn định.
Lưu ý: nhiều reasoning model hiện nay **không cho chỉnh** temperature, nên `LLMClient`
của minicode cố tình không đưa tham số này vào interface.

### Role trong message
- **system**: chỉ dẫn nền (danh tính, quy tắc). Với OpenAI Responses, nó nằm ở `instructions`;
  với Anthropic, nó nằm ở tham số `system`. Hai bên đều không đặt system prompt trong list message.
- **user**: lời người dùng.
- **assistant**: câu trả lời trước đó của model, gửi lại để model "nhớ".
- **tool**: kết quả tool (từ M2). Mỗi provider biểu diễn role này khác nhau, nên minicode có
  format nội bộ riêng.

### Vì sao LLM "stateless"
Mỗi request API là độc lập: server không nhớ lượt trước. "Trí nhớ" của chatbot chỉ là việc
**client tự giữ lịch sử và gửi lại hết**. Test `test_every_turn_resends_the_whole_history`
trong `tests/unit/test_chat.py` chứng minh điều này. Ở lượt 2, model nhận đủ cả 3 message:

```
user: My name is Duc.  →  assistant: Hi Duc!  →  user: What is my name?
```

OpenAI có tùy chọn lưu state phía server (`store=True`, `previous_response_id`), nhưng
minicode cố tình dùng `store=False` để mô hình tư duy luôn rõ ràng: model chỉ biết những gì
có trong request.

### Vì sao LLM hallucinate
Model được huấn luyện để sinh ra token *có xác suất cao*, không phải token *đúng sự thật*.
Khi thiếu thông tin (hàm không tồn tại, file chưa đọc, sự kiện sau thời điểm huấn luyện),
nó vẫn sinh ra câu trả lời nghe rất hợp lý. Với coding agent, cách chống chính là **cho
model công cụ để kiểm chứng**: đọc file thật, chạy test thật (M2, M3), thay vì tin vào
"trí nhớ" của nó.

---

## 2. Vì sao thiết kế như vậy

| Quyết định | Phương án khác | Lý do chọn |
|---|---|---|
| Type nội bộ trung lập (`Message`, `LLMResponse`) | Dùng thẳng object của SDK | Agent loop, tool, test không phụ thuộc provider. Đổi provider chỉ cần đổi adapter |
| `Message` phẳng (`content`, `tool_calls`, `tool_results`) | Danh sách "content block" như Anthropic | Dễ đọc hơn cho người mới. Adapter lo phần chuyển đổi. Trade-off: khó biểu diễn ảnh hay nội dung xen kẽ (không cần cho dự án này) |
| `LLMClient` là `Protocol` | Abstract base class | Fake client và adapter không cần kế thừa gì, chỉ cần "đúng hình dạng" (structural typing) |
| Thêm `on_text` ngay từ M0 | Thêm khi làm streaming ở M1 | Interface là contract với test của người học, đổi giữa chừng sẽ làm vỡ code của họ |
| OpenAI **Responses API** | Chat Completions | Đây là API OpenAI khuyến nghị hiện nay, hỗ trợ reasoning model tốt hơn. Trade-off: provider "OpenAI-compatible" (Ollama, vLLM…) thường chỉ có Chat Completions |
| Config gộp theo thứ tự file < `.env` < env | Thư viện `pydantic-settings` | Không nằm trong danh sách dependency, và tự viết thì thấy rõ giá trị đến từ đâu |
| `environ` truyền vào `load_settings` | Đọc `os.environ` bên trong | Không có global state, test kín (hermetic) |
| Bảng giá là dữ liệu, override được | Gọi API lấy giá | Không có API giá chính thức. Giá đổi thường xuyên, nên coi là "ước tính" |
| Không có model mặc định trong code | Hardcode model mặc định | Model ID lỗi thời rất nhanh. Thiếu `MINICODE_MODEL` thì báo lỗi rõ ràng |

---

## 3. Pitfalls

- **Quên gửi lại lịch sử**: chỉ gửi message mới nhất, và model "quên" ngay lượt trước.
- **Không copy history trong fake client**: list `history` bị sửa sau khi gọi, nên test assert
  sai. `FakeLLMClient` dùng `model_copy(deep=True)` vì lý do này.
- **Để lại user message "treo" khi API lỗi**: lượt sau gửi 2 user message liên tiếp.
  Xem phần rollback trong `ChatSession.send`.
- **Lộ API key**: in `settings` ra log, hoặc commit `.env`. Hãy dùng `SecretStr`, kiểm tra
  `.gitignore` *trước* commit đầu tiên.
- **Nhầm `arguments` của OpenAI là dict**: thực ra nó là **chuỗi JSON**, phải `json.loads`.
  Anthropic thì trả `input` là dict.
- **Viết test gọi API thật mà không có cờ bảo vệ**: chạy `pytest` là mất tiền. Hãy dùng `--run-live`.
- **Dựa vào trí nhớ về SDK**: SDK đổi nhanh (ví dụ `cache_write_tokens` mới thành field bắt buộc
  trong usage của OpenAI 3.x). Hãy đọc source trong `.venv`.

---

## 4. Bài tập tự code lại

Thứ tự nên viết (mỗi bước chạy test tương ứng):

1. `llm/types.py`: `ToolCall`, `ToolResult`, `Usage` (kèm `__add__`), `LLMResponse`, `Message`
   và 3 classmethod `user` / `assistant` / `tool`.
   *Gợi ý:* dùng `Field(default_factory=list)` cho list.
2. `llm/base.py`: `LLMClient` Protocol với `model` và `complete(...)`.
   *Gợi ý:* `@runtime_checkable` để `isinstance` dùng được trong test.
3. `llm/fake_client.py`: `FakeLLMClient` trả lời theo kịch bản, ghi lại `calls`, raise khi hết kịch bản.
   → `uv run pytest -m m0 tests/contract`
4. `config.py`: `Settings` + `load_settings(workspace, environ=..., dotenv_file=...)`.
   *Gợi ý:* `tomllib` có sẵn, `dotenv_values` không đụng vào `os.environ`.
5. `llm/pricing.py`: `estimate_cost`.
6. `llm/openai_client.py`: `to_input_items`, `to_function_tool`, `from_response`, `OpenAIClient.complete`.
   *Gợi ý:* test bằng `Response.model_validate({...})` để có object đúng format SDK mà không cần mạng.
7. `chat.py`: `ChatSession.send`, gồm cộng dồn usage và rollback khi lỗi.
8. `cli.py`: lệnh `chat` + `chat_loop(session, console, read_line)`.
   *Gợi ý:* truyền `read_line` vào để test không cần bàn phím.

Marker cần pass: `uv run pytest -m m0` (contract: `tests/contract/test_m0_*.py`).

---

## 5. Gợi ý cải tiến

Những chỗ reference cố tình làm đơn giản:

- Chưa streaming: text hiện ra một lần ở cuối (sẽ làm ở M1).
- Chưa retry khi gặp lỗi 429/5xx (SDK có retry mặc định; thử tự viết exponential backoff).
- Cost bỏ qua giá cache và giá long-context. Thử đọc `usage.input_tokens_details.cached_tokens`.
- Không lưu lịch sử chat ra file. Thử thêm `/save` và `/load`.
- REPL chưa hỗ trợ nhập nhiều dòng, và chưa có lệnh `/clear` hay `/usage`.
- `max_tokens` cố định. Thử cho chỉnh theo từng lượt.

---

## 6. Câu hỏi tự kiểm tra

1. Nếu ở lượt thứ 10 bạn chỉ gửi message mới nhất, model sẽ trả lời ra sao? Vì sao?
2. Vì sao số input token tăng dần qua mỗi lượt chat, còn output token thì không?
3. System prompt được đặt ở đâu trong request của OpenAI Responses và của Anthropic Messages?
4. Vì sao `FakeLLMClient` quan trọng với một dự án agent? Nó giúp test được những gì mà API thật không làm được?
5. Hallucination là gì, và vì sao "cho model tool để kiểm chứng" là cách giảm hallucination hiệu quả cho coding agent?
