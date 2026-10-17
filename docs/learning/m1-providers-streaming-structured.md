# M1: Provider abstraction, streaming, structured output

> Mục tiêu:
> - đổi provider chỉ bằng biến môi trường;
> - thấy text hiện ra dần khi model đang sinh;
> - ép model trả về dữ liệu có cấu trúc và tự sửa khi sai.

Code chính: `src/minicode/llm/anthropic_client.py`, `llm/openai_client.py`, `llm/structured.py`,
`llm/factory.py`, `cli.py` (`_stream_printer`).

---

## 1. Khái niệm

### So sánh format của 2 provider

| | OpenAI Responses API | Anthropic Messages API |
|---|---|---|
| Gọi | `client.responses.create(...)` | `client.messages.create(...)` |
| System prompt | `instructions="..."` | `system="..."` |
| Lịch sử | `input=[items...]`: list phẳng gồm message và "item" | `messages=[...]`: user và assistant xen kẽ, `content` là list block |
| Định nghĩa tool | `{"type": "function", "name", "description", "parameters"}` | `{"name", "description", "input_schema"}` |
| Model gọi tool | item `{"type": "function_call", "call_id", "name", "arguments": "<chuỗi JSON>"}` | block `{"type": "tool_use", "id", "name", "input": {dict}}` |
| Trả kết quả tool | item `{"type": "function_call_output", "call_id", "output"}` | block `tool_result` **nằm trong message role `user`** |
| Báo lỗi tool | Không có cờ, phải ghi trong text | `is_error: true` |
| Lý do dừng | Không có, phải suy ra từ `status` và output | `stop_reason`: `end_turn`, `tool_use`, `max_tokens`… |
| `max_tokens` | Tùy chọn (`max_output_tokens`) | **Bắt buộc** |

Kết luận: hai provider cùng một ý tưởng nhưng khác format ở mọi chỗ. Vì vậy minicode có
**type nội bộ** (`Message`, `ToolCall`, `LLMResponse`), mỗi adapter chỉ lo phần dịch
qua lại. Agent loop ở M3 sẽ không biết mình đang nói chuyện với provider nào.

### Streaming
Không streaming thì phải chờ model sinh xong cả câu trả lời (có thể vài chục giây) rồi mới thấy gì.
Có streaming thì server gửi về từng **event** nhỏ ngay khi có token mới:
- OpenAI: `response.output_text.delta`;
- Anthropic: SDK gom sẵn thành `stream.text_stream`.

Streaming **không làm model nhanh hơn**. Tổng thời gian vẫn vậy, nhưng *thời gian đến token
đầu tiên* (time-to-first-token) ngắn hơn nhiều, nên người dùng cảm thấy nhanh hơn.

Trong minicode, callback `on_text` nhận từng đoạn text, còn kết quả cuối (`LLMResponse`) vẫn
được dựng từ message hoàn chỉnh. Nhờ vậy code phía sau không cần quan tâm có stream hay không.

### Structured output
Nhiều tác vụ cần **dữ liệu** chứ không cần văn xuôi. Ví dụ ở M6, router phải phân loại một task
là `question` hay `edit`. Cách làm trong `complete_structured`:
1. đưa JSON Schema (sinh từ pydantic model) vào prompt;
2. lấy phần `{...}` trong câu trả lời, rồi validate bằng `Model.model_validate_json`;
3. nếu fail, gửi lại cho model **chính câu trả lời sai của nó kèm lỗi cụ thể** (ví dụ
   `confidence: Input should be a valid number`), rồi yêu cầu sửa;
4. thử tối đa `1 + max_retries` lần, sau đó raise `StructuredOutputError`.

### Reasoning model và standard model
- **Standard model** sinh câu trả lời ngay: rẻ, nhanh, hợp với tác vụ đơn giản (tóm tắt, phân loại).
- **Reasoning model** "suy nghĩ" trước khi trả lời. Phần suy nghĩ ẩn vẫn tính tiền như output token.
  Bạn đã thấy ở M0: câu trả lời 5 chữ vẫn báo `out 133`. Loại này tốt hơn hẳn cho tác vụ nhiều bước như
  debug hay lập kế hoạch sửa code, nhưng chậm và đắt hơn. Nhiều reasoning model không cho chỉnh `temperature`.

### Chọn size model: `main` và `small`
- `MINICODE_MODEL` (main) dùng cho agent loop: cần suy luận tốt, gọi tool chính xác.
- `MINICODE_SMALL_MODEL` (small) dùng cho việc phụ, gọi nhiều lần: tóm tắt khi compaction (M5),
  routing (M6). Ví dụ `gpt-6-luna` rẻ hơn `gpt-6.1-sol` khoảng 20 lần.

Nguyên tắc: bắt đầu với model mạnh để có baseline đúng, rồi đo bằng eval (M7) xem
chỗ nào hạ xuống model nhỏ mà không giảm chất lượng.

---

## 2. Vì sao thiết kế như vậy

| Quyết định | Phương án khác | Lý do chọn |
|---|---|---|
| Inject `sdk=` vào constructor của adapter | Mock bằng `unittest.mock.patch` | Rõ ràng, không "ma thuật". Stub chỉ cần đúng các method mà adapter gọi |
| Stub trả object **đúng format SDK** (`Response.model_validate`, `Message.model_validate`) | Stub trả `SimpleNamespace` tùy ý | Test phát hiện được khi SDK đổi field (như `cache_write_tokens` ở M0) |
| Chỉ stream khi có `on_text` | Luôn stream | Đường không stream đơn giản hơn để debug, và được dùng cho các call phụ (structured, summary) |
| Dùng chung `from_response` / `from_message` cho cả hai đường | Viết riêng cho stream | Một nơi duy nhất để chuẩn hóa nên không lệch nhau. Message cuối của stream cũng là `Response`/`Message` |
| Structured output qua prompt + validate + retry | JSON mode hay structured outputs native của provider | Chạy được với mọi `LLMClient` (kể cả fake), và lộ rõ vòng retry để học. Đánh đổi: native mode chắc chắn hơn |
| Gửi lỗi validate cho model sửa | Chỉ gọi lại y nguyên | Model sửa rất tốt khi biết *chính xác* sai ở đâu. Gọi lại y nguyên thường lặp lại đúng lỗi cũ |
| Stream ra text thô, không render Markdown | Render Markdown sau khi stream xong | Markdown chỉ render được khi đã có toàn bộ text. Ưu tiên thấy token chạy |
| `extract_json` lấy từ `{` đầu đến `}` cuối | Regex hoặc parser phức tạp | Đủ cho hầu hết trường hợp (có code fence, có câu dẫn). Nếu vẫn sai thì vòng retry sẽ xử lý |

---

## 3. Pitfalls

- **Quên rằng Anthropic không có role `tool`**: gửi `{"role": "tool"}` sẽ bị API báo lỗi.
  Tool result phải nằm trong message `user`, và các kết quả của cùng một lượt phải chung một message.
- **Nhầm `arguments` (chuỗi JSON) với `input` (dict)** giữa hai provider.
- **Gửi assistant message rỗng cho Anthropic** cũng bị từ chối. Xem placeholder `(no content)`.
- **Không gọi `get_final_message()` / `get_final_response()`** sau khi stream thì mất usage và tool call,
  vì delta text không chứa những thứ đó.
- **Retry structured output mà không giữ lịch sử**: model không thấy câu sai của nó, nên sửa kém.
- **Không giới hạn số lần retry**: vòng lặp vô hạn tốn tiền. Luôn có `max_retries`.
- **Tin JSON trả về mà không validate**: model có thể trả đúng cú pháp JSON nhưng sai kiểu hoặc thiếu field.

---

## 4. Bài tập tự code lại

1. `llm/anthropic_client.py`:
   - `to_messages`: user, assistant (text block + tool_use blocks), tool (user + tool_result blocks);
   - `to_tool`;
   - `from_message`: nối text block, gom tool_use, map `stop_reason`.

   *Gợi ý:* bắt đầu bằng unit test cho `to_messages` trước khi gọi API.
2. `AnthropicClient.complete`: đường `create` trước, sau đó đến đường `stream` với `text_stream`.
3. Nhánh streaming của `OpenAIClient.complete`: lọc event `response.output_text.delta`.
   → `uv run pytest -m m1 tests/contract/test_m1_adapters.py`
4. `llm/structured.py`: `extract_json`, `format_validation_error`, rồi `complete_structured`.
   *Gợi ý:* `exc.errors(include_url=False)` cho list lỗi có `loc` và `msg`.
   → `uv run pytest -m m1 tests/contract/test_m1_structured.py`
5. `factory.create_client`: thêm nhánh `anthropic`.
6. `cli.py`: truyền `on_text` in từng chunk (`console.print(chunk, end="", markup=False)`).

Marker cần pass: `uv run pytest -m m1`.

---

## 5. Gợi ý cải tiến

- Dùng **structured outputs native** (OpenAI: `text={"format": {"type": "json_schema", ...}}`;
  Anthropic: `output_config`), giữ vòng retry làm lưới an toàn. So sánh tỉ lệ lỗi.
- Stream cả **tool call** (argument được gửi dần) để hiển thị "đang gọi tool X…" sớm hơn.
- Render Markdown sau khi stream xong (xóa text thô, in bản đẹp) bằng `rich.live.Live`.
- Thêm retry/backoff cho lỗi tạm thời (429, 529 overloaded) ở tầng adapter.
- Tận dụng **prompt caching** của Anthropic (`cache_control`) cho system prompt dài ở các milestone sau.
- Đọc `reasoning_tokens` và hiển thị riêng trong dòng usage.
- `extract_json` chưa xử lý được trường hợp có nhiều object JSON trong một câu trả lời.

---

## 6. Câu hỏi tự kiểm tra

1. Vì sao Anthropic yêu cầu tool result nằm trong message `user`? Nếu một lượt có 3 tool call,
   bạn gửi lại bao nhiêu message?
2. Streaming cải thiện chỉ số nào: tổng thời gian hay time-to-first-token? Vì sao?
3. Khi stream, tại sao vẫn cần `get_final_message()` / `get_final_response()`?
4. Trong `complete_structured`, vì sao gửi lại cả câu trả lời sai của model chứ không chỉ gửi lỗi?
5. Task "tóm tắt 20 lượt hội thoại cũ" nên dùng main hay small model? Còn "sửa bug khó trong 3 file"?
