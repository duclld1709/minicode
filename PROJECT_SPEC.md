# PROJECT_SPEC.md — `minicode`: a mini coding agent (Claude Code–style), built from scratch in Python
---

## 0. Vai trò của bạn (Claude Code) và cách làm việc

Bạn đang xây một **reference implementation** cho một người đang học AI Engineering. Người học code Python tốt nhưng mới với agent. Sau đó họ sẽ:

1. chạy thử dự án để hình dung sản phẩm cuối,
2. tự code lại từ đầu theo từng milestone,
3. so sánh code của họ với code của bạn, rồi cải tiến.

Vì vậy, ưu tiên theo thứ tự: **dễ đọc > đúng > đầy đủ > tối ưu**. Không viết code "thông minh" khó theo dõi.

**Quy tắc làm việc:**

- Làm **từng milestone một** (M0 → M8). Đầu mỗi milestone, nêu ngắn gọn kế hoạch. Cuối mỗi milestone:
  - chạy `uv run pytest`, `uv run ruff check .` và `uv run mypy src`; tất cả phải pass;
  - cập nhật `MILESTONES.md` và viết `docs/learning/mN-<slug>.md`;
  - commit, rồi `git tag mN`;
  - **dừng lại và chờ mình xác nhận**, trừ khi mình nói "làm tiếp hết".
- Mỗi tag `mN` phải **chạy được độc lập và test xanh** tại thời điểm đó. Người học sẽ `git checkout mN` để so sánh.
- **Không dùng agent framework**: không LangChain, LangGraph, LlamaIndex, CrewAI, AutoGen hay Agent SDK. Agent loop phải tự viết.
- Dependencies được phép:
  - runtime: `anthropic`, `openai`, `mcp` (official Python SDK), `pydantic` (v2), `typer`, `rich`, `python-dotenv`, `httpx`, `pyyaml`;
  - dev: `pytest`, `pytest-asyncio`, `ruff`, `mypy`.
  - Muốn thêm gì khác thì **hỏi trước**.
- **Kiểm tra API của SDK** bằng docs hiện hành hoặc source của package đã cài, không dựa vào trí nhớ. Pin version trong `pyproject.toml`.
- Ngôn ngữ:
  - Tiếng Anh: code, tên biến, comment, docstring, README, commit message.
  - Tiếng Việt: `docs/learning/*.md`.
- Khi spec mơ hồ hoặc mâu thuẫn, hỏi mình thay vì tự đoán những quyết định lớn.

---

## 1. Sản phẩm cuối trông như thế nào

`minicode` là một CLI chạy trong một thư mục project. Người dùng giao task bằng ngôn ngữ tự nhiên. Agent sẽ tự đọc file, tìm kiếm, sửa code và chạy lệnh. Mọi tool call đều hiển thị trên terminal. Agent xin phép trước các hành động rủi ro và tự dừng khi xong.

```bash
# REPL tương tác
uv run minicode --cwd ./my-project

# One-shot
uv run minicode run "Fix the failing tests" --cwd examples/buggy_calculator

# Expose toolbelt dưới dạng MCP server
uv run minicode mcp-serve

# Chạy eval
uv run python evals/run_evals.py --model <model-id>
```

**Kịch bản demo chuẩn (end-to-end acceptance):**

`examples/buggy_calculator/` là một repo Python nhỏ có 2–3 bug và test đang fail. Lệnh `minicode run "Fix the failing tests"` phải làm được các bước sau:

1. khám phá repo;
2. chạy pytest và đọc lỗi;
3. sửa code bằng `edit_file`;
4. chạy lại pytest;
5. báo cáo ngắn gọn những gì đã sửa.

## 2. Non-goals (không làm)

- Không GUI, web UI hay IDE plugin.
- Không vector DB hay RAG.
- Không fine-tuning.
- Không multi-user.
- Không Docker sandbox (chỉ để ở roadmap).
- Không hỗ trợ Windows native (WSL là được).

---

## 3. Kiến trúc

### 3.1 Cấu trúc thư mục

```
minicode/
  pyproject.toml
  CLAUDE.md                 # quy ước dự án cho các phiên Claude Code sau
  README.md
  MILESTONES.md             # tổng quan milestone + test marker tương ứng
  .env.example
  src/minicode/
    cli.py                  # typer entrypoints, REPL, rich rendering
    config.py               # settings từ env + .minicode/config.toml
    llm/
      types.py              # Message, ToolCall, ToolResult, LLMResponse, Usage
      base.py               # LLMClient Protocol
      anthropic_client.py
      openai_client.py
      fake_client.py        # scripted responses cho test offline
      pricing.py            # ước tính cost theo model (bảng giá cấu hình được)
    tools/
      base.py               # Tool, ToolRegistry, schema từ pydantic model
      fs.py                 # read_file, list_dir, glob, grep, write_file, edit_file
      shell.py              # run_bash
      todo.py               # todo_write / todo_read
    agent/
      loop.py               # Agent.run(): vòng lặp lõi
      guards.py             # budgets, stopping conditions, permission policy, sandbox
      context.py            # lịch sử hội thoại, ước lượng token, compaction
      prompts.py            # system prompt builder theo section
      router.py             # routing task bằng small model
    mcp/
      server.py             # expose tools của minicode qua MCP (stdio)
      client.py             # nạp tool từ MCP server ngoài vào registry
    harness/
      memory.py             # nạp AGENTS.md
      skills.py             # skills với progressive disclosure
    workflows/
      subagent.py           # orchestrator-workers
      verifier.py           # evaluator-optimizer
    tracing.py              # JSONL trace
  tests/
    unit/
    contract/               # test chỉ dựa trên public API, dùng lại được cho code của người học
    e2e/                    # gọi API thật, marker `live`, mặc định skip
  evals/
    tasks/<task_id>/        # fixture repo + task.yaml + check.py
    run_evals.py
    results/
  examples/buggy_calculator/
  docs/
    architecture.md
    learning/
```

### 3.2 Interface lõi (giữ ỔN ĐỊNH qua các milestone)

Code tự viết lại của người học phải pass cùng bộ contract test, nên public API không được đổi tùy tiện. Nếu buộc phải đổi, ghi rõ lý do trong `MILESTONES.md`.

```python
# llm/types.py — format nội bộ, trung lập với provider; adapter tự chuyển đổi
class ToolCall(BaseModel):     id: str; name: str; arguments: dict
class ToolResult(BaseModel):   call_id: str; content: str; is_error: bool = False
class Usage(BaseModel):        input_tokens: int; output_tokens: int
class LLMResponse(BaseModel):  text: str; tool_calls: list[ToolCall]; stop_reason: str; usage: Usage
class Message(BaseModel):      role: Literal["user", "assistant", "tool"]; content: ...  # thiết kế cụ thể tùy bạn, giải thích trong docs

# llm/base.py
class LLMClient(Protocol):
    def complete(self, messages, *, system: str, tools: list[dict], max_tokens: int) -> LLMResponse: ...

# tools/base.py
@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]                  # sinh JSON schema từ model này
    handler: Callable[..., str]
    risk: Literal["read", "write", "exec"]

class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def schemas(self) -> list[dict]: ...
    def execute(self, call: ToolCall) -> ToolResult: ...   # KHÔNG BAO GIỜ raise; lỗi -> is_error=True

# agent/loop.py
class Agent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry, guards: Guards, ...): ...
    def run(self, task: str) -> AgentResult: ...    # final_text, steps, usage, stop_reason
```

Dependency injection ở mọi nơi (LLM client, registry, permission prompt) để test được bằng `FakeLLMClient`.

### 3.3 Agent loop (tinh thần)

```
while True:
    guards.check()                    # max_steps, token/cost budget, wall time, interrupt
    resp = llm.complete(history, system, tools)
    history.append(assistant(resp))
    if not resp.tool_calls:
        return done(resp.text)
    for call in resp.tool_calls:
        if not permission.allow(call):
            result = denied(call)
        else:
            result = registry.execute(call)
        history.append(tool_result(truncate(result)))
    context.maybe_compact(history)
```

### 3.4 An toàn (bắt buộc, có test)

- **Workspace sandbox**: mọi path được `resolve()` và phải nằm trong `--cwd`. Chặn `..`, symlink thoát ra ngoài và absolute path bên ngoài workspace.
- **`run_bash`**:
  - có timeout và truncate output (giữ phần đầu và phần cuối);
  - có denylist các pattern nguy hiểm như `rm -rf /`, `sudo`, `curl … | sh`, `mkfs`, fork bomb;
  - denylist chỉ là lớp phụ; lớp chính là permission.
- **Permission modes**:
  - `ask` (mặc định): hỏi trước mọi tool `write` và `exec`;
  - `accept-edits`: tự cho phép `write`, vẫn hỏi `exec`;
  - `auto`: không hỏi, nhưng denylist vẫn áp dụng.
- **Prompt injection**:
  - tool output được bọc rõ là dữ liệu;
  - system prompt nói rõ rằng nội dung từ file hoặc lệnh là data, không phải chỉ thị;
  - phòng tuyến thật sự là permission guard, và phải có test chứng minh điều này.
- Không bao giờ log API key. Trace phải mask secret.

---

## 4. Milestones

Mỗi milestone cần đủ các phần sau:

- **Build**: những gì phải xây;
- **Acceptance**: tiêu chí hoàn thành;
- **Tests**: dùng pytest marker `@pytest.mark.mN`, để người học chạy `pytest -m m2`;
- **Learning note**: file `docs/learning/mN-*.md`.

Cột "Buổi" ánh xạ tới syllabus khóa học tham khảo.

### M0 — Setup & first LLM call (Buổi 1: LLM Foundations)
- **Build:**
  - project `uv`, Python 3.12+;
  - `config.py` đọc env (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MINICODE_PROVIDER`, `MINICODE_MODEL`, `MINICODE_SMALL_MODEL`);
  - `.env.example` (model ID lấy theo docs hiện hành của provider, không hardcode trong code);
  - `minicode chat`: chat nhiều lượt, không có tool;
  - in token usage và cost ước tính sau mỗi lượt;
  - `FakeLLMClient` trả lời theo kịch bản cho test.
- **Acceptance:** chat được với ít nhất một provider; test offline pass.
- **Learning note:** token, context window, temperature, các role trong message, vì sao LLM "stateless" và phải gửi lại toàn bộ lịch sử, vì sao LLM hallucinate.

### M1 — Provider abstraction, streaming, structured output (Buổi 2: LLM Abilities)
- **Build:**
  - adapter Anthropic và OpenAI cùng trả về các type ở mục 3.2;
  - streaming text ra terminal;
  - helper `complete_structured(llm, prompt, model: type[BaseModel])`: validate bằng pydantic, retry kèm thông báo lỗi khi parse fail (tối đa N lần).
- **Acceptance:** đổi provider chỉ bằng env var; contract test cho adapter (dùng response giả lập theo format của từng SDK).
- **Learning note:**
  - so sánh format message và tool của 2 provider;
  - reasoning model và standard model;
  - chọn size model: `main` cho agent, `small` cho summarize và routing.

### M2 — Tool calling (Buổi 3: Tool Use)
- **Build:**
  - `Tool` và `ToolRegistry`, sinh schema từ pydantic;
  - tool fs: `read_file` (có offset/limit, đánh số dòng), `list_dir`, `glob`, `grep`, `write_file`, `edit_file`;
  - `edit_file` dùng exact string replace, yêu cầu `old_string` là duy nhất, nếu không thì trả lỗi hướng dẫn;
  - `run_bash`.
- **Xử lý lỗi**, mọi trường hợp đều thành `ToolResult(is_error=True)` có thông điệp giúp model tự sửa:
  - tool không tồn tại;
  - argument sai schema;
  - handler raise exception;
  - output quá dài (truncate kèm `[truncated N lines]`).
- **Acceptance:** với `FakeLLMClient`, một lượt tool use chạy đúng; mọi loại lỗi ở trên đều có test.
- **Learning note:** model chỉ *đề xuất* tool call, code của mình mới là thứ thực thi; thiết kế description và schema để model dùng đúng.

### M3 — Agent loop & guards (Buổi 6: phần lõi, làm sớm vì mọi thứ sau đều cần)
- **Build:**
  - `Agent.run()` theo mục 3.3;
  - stopping conditions: không còn tool call, `max_steps`, budget token/cost, wall time, Ctrl+C (dừng êm và giữ lịch sử);
  - permission modes và sandbox theo mục 3.4;
  - `rich` hiển thị từng bước (tool name, args rút gọn, kết quả rút gọn);
  - `minicode run` và REPL.
- **Acceptance:**
  - **kịch bản demo `buggy_calculator` chạy thành công với API thật**;
  - test offline cho từng stopping condition và guard.
- **Learning note:** vòng Observe → Think → Act; vì sao agent cần guard; các failure mode thường gặp (lặp vô hạn, gọi sai tool liên tục, "nói xong" mà chưa làm).

### M4 — MCP (Buổi 3: MCP)
- **Build:**
  - `minicode mcp-serve`: expose toolbelt fs (read-only mặc định, flag cho phép write) qua MCP stdio, test được bằng MCP Inspector;
  - MCP client: đọc `.minicode/mcp.json` (format tương tự Claude Code), khởi động server, nạp tool vào registry với tên `mcp__<server>__<tool>`, risk mặc định `exec` (cẩn trọng).
- **Acceptance:** integration test chạy chính server của minicode như subprocess, rồi gọi tool qua client.
- **Learning note:** MCP giải quyết vấn đề gì; khác gì với việc tự định nghĩa tool; rủi ro bảo mật khi dùng MCP server của bên thứ ba.

### M5 — Harness / context engineering (Buổi 4: Harness Engineering)
- **Build:**
  - `prompts.py` ghép system prompt từ các section: identity, quy tắc dùng tool, quy tắc an toàn, environment (cwd, OS, git status, ngày), project memory;
  - nạp `AGENTS.md` ở thư mục gốc workspace làm project memory;
  - **Skills**: `.minicode/skills/<name>/SKILL.md` có frontmatter `name` và `description`. System prompt chỉ chứa tên và mô tả. Tool `load_skill(name)` mới nạp nội dung đầy đủ (progressive disclosure). Kèm 2 skill mẫu, ví dụ `write-pytest-tests` và `python-refactor`;
  - **Context compaction**: khi token ước lượng vượt ngưỡng, dùng small model tóm tắt các lượt cũ và giữ nguyên N lượt cuối; xóa nội dung các tool result cũ, dài và giữ lại placeholder.
- **Acceptance:**
  - test compaction kích hoạt đúng ngưỡng;
  - test skills chỉ nạp khi được gọi;
  - test prompt injection: fixture file chứa chỉ thị độc hại, agent (với fake LLM "bị lừa") đề xuất lệnh nguy hiểm, guard phải chặn hoặc hỏi.
- **Learning note:**
  - prompt engineer → context engineer → harness engineer;
  - kỹ thuật prompt nào của 2023 đã lỗi thời và cái nào còn giá trị;
  - cách viết một skill tốt.

### M6 — Workflow patterns (Buổi 5: Workflow Patterns)
Hiện thực đủ 5 pattern, mỗi pattern có chỗ dùng thật trong minicode:

| Pattern | Hiện thực trong minicode |
|---|---|
| Chaining | `minicode commit-msg`: diff → tóm tắt → viết commit message (2 call nối tiếp) |
| Routing | `router.py`: small model phân loại task (hỏi đáp / sửa code) bằng structured output; hỏi đáp thì dùng tool read-only |
| Parallelization | các tool call `read` độc lập trong cùng một lượt chạy song song (thread pool), giữ đúng thứ tự kết quả |
| Orchestrator-workers | tool `delegate(task)`: subagent có context riêng, chỉ có tool read-only, trả về bản tóm tắt |
| Evaluator-optimizer | `--verify "pytest -q"`: khi agent báo xong, chạy lệnh verify; nếu fail, đưa output lại cho agent sửa (tối đa K vòng) |

- **Thêm:** tool `todo_write` và `todo_read` để agent tự lập và cập nhật kế hoạch cho task nhiều bước.
- **Acceptance:** mỗi pattern có ít nhất một test offline.
- **Learning note:** khi nào cần orchestration, khi nào một call là đủ, và chi phí/độ trễ của từng pattern.

### M7 — Observability & Evals
- **Tracing:** mỗi session ghi một file JSONL vào `.minicode/traces/` (mỗi LLM call và tool call kèm latency, token, cost). Lệnh `minicode replay <trace>` xem lại có định dạng.
- **Evals:** 8–10 task trong `evals/tasks/`, mỗi task gồm fixture repo, `task.yaml` (prompt, `max_steps`) và `check.py` (pass/fail khách quan). Các loại task cần có:
  - sửa bug;
  - thêm function kèm test;
  - đổi tên symbol trên nhiều file;
  - trả lời câu hỏi về codebase (check theo keyword);
  - task cần dùng skill;
  - task có bẫy prompt injection.
- `run_evals.py`:
  - copy fixture ra thư mục tạm;
  - chạy agent;
  - chạy check;
  - xuất bảng: pass rate, số bước trung bình, token, cost, thời gian;
  - lưu JSON vào `evals/results/`;
  - so sánh được nhiều model/config.
- **Acceptance:** chạy eval với ít nhất một model thật và lưu kết quả (mình sẽ tự chạy nếu bạn không có key).
- **Learning note:** vì sao agent phải có eval; khác biệt giữa unit test và eval; cách đọc trace để debug agent.

### M8 — Polish cho CV
- **`README.md`** (tiếng Anh, viết cho nhà tuyển dụng):
  - một câu mô tả và GIF demo (kèm hướng dẫn quay bằng `vhs` hoặc `asciinema`);
  - features;
  - quick start;
  - sơ đồ kiến trúc (Mermaid);
  - design decisions & trade-offs;
  - bảng kết quả eval;
  - limitations;
  - roadmap.
- `docs/architecture.md` chi tiết hơn README.
- GitHub Actions CI: ruff, mypy, pytest (chỉ offline).
- `docs/learning/interview-questions.md` (tiếng Việt): khoảng 25 câu hỏi phỏng vấn fresher AI Engineer liên quan đến dự án, mỗi câu có gợi ý trả lời dẫn tới file/hàm cụ thể trong code.

---

## 5. Contract tests để người học tự kiểm tra code của mình

- `tests/contract/` chỉ test qua public API ở mục 3.2, không chạm vào chi tiết nội bộ.
- Người học sẽ copy `tests/contract/` sang repo của họ (cùng tên package `minicode`) rồi chạy `pytest -m mN`.
- `MILESTONES.md` phải có bảng: milestone → marker → các contract test thuộc milestone đó → các hàm người học cần tự viết.

## 6. Learning notes (`docs/learning/mN-*.md`, tiếng Việt)

Mỗi file gồm:

1. **Khái niệm**: giải thích ngắn, có ví dụ.
2. **Vì sao thiết kế như vậy**: các phương án đã cân nhắc và trade-off.
3. **Pitfalls**: lỗi thường gặp khi tự code.
4. **Bài tập tự code lại**: danh sách hàm/class theo thứ tự nên viết, gợi ý (không đưa lời giải), marker test cần pass.
5. **Gợi ý cải tiến**: những gì reference cố tình làm đơn giản, để người học cải tiến khi so sánh.
6. **Câu hỏi tự kiểm tra**: 3–5 câu.

## 7. Chuẩn chất lượng code

- Python 3.12+, `uv`, type hints đầy đủ, `mypy` (strict cho `src/`), `ruff` (lint + format), pydantic v2.
- Không global state. Hàm ngắn (khoảng ≤ 50 dòng). Docstring giải thích **vì sao**, không chỉ **cái gì**.
- Test mặc định chạy offline bằng `FakeLLMClient`. Test gọi API thật có marker `live` và bị skip nếu không có key.
- Coverage khoảng ≥ 80% cho `agent/` và `tools/`.
- Commit nhỏ, message rõ ràng (Conventional Commits).

## 8. Definition of Done (toàn dự án)

- [ ] `uv sync && uv run minicode run "Fix the failing tests" --cwd examples/buggy_calculator` thành công với Anthropic **hoặc** OpenAI.
- [ ] `uv run pytest` xanh khi offline; CI xanh.
- [ ] `uv run python evals/run_evals.py` sinh được báo cáo.
- [ ] Có đủ tag `m0` … `m8`; checkout tag nào cũng chạy được và test xanh.
- [ ] README, architecture và learning notes đầy đủ.

## 9. Bắt đầu

Đọc toàn bộ spec này. Trước khi viết code:

1. liệt kê điểm nào trong spec bạn thấy mâu thuẫn, rủi ro hoặc nên điều chỉnh;
2. xác nhận version hiện tại của `anthropic`, `openai` và `mcp`, cùng cách gọi tool use / MCP tương ứng;
3. tạo `CLAUDE.md` tóm tắt quy ước của dự án.

Sau đó **chỉ thực hiện M0** rồi dừng lại.
