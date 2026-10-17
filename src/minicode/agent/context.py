"""Context management: estimate history size and compact it when it grows too large.

Every step resends the whole history, so long tasks grow the context (and the
bill) step by step until they hit the model's context window. Compaction trades
detail for room, in two stages, cheapest first:

1. Clear old, long tool results (the bulk of most histories: file dumps, test
   logs) and leave a short placeholder. The model can re-run the tool if needed.
2. If that is not enough, summarize everything before the last N steps with the
   small model, keeping the user's requests verbatim.

The cut always happens right before an assistant message, so a tool call and
its results are never separated (both providers reject that).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from minicode.llm.base import LLMClient
from minicode.llm.types import Message, ToolResult, Usage
from minicode.tools.base import truncate_output

CHARS_PER_TOKEN = 4  # rough average for English text and code; good enough for a threshold

CLEARED_RESULT = "[tool result cleared to save context ({chars} chars); re-run the tool if needed]"

SUMMARY_SYSTEM = (
    "You summarize the earlier part of a coding agent's session so the agent can continue the "
    "task. Be concise and concrete."
)
SUMMARY_PROMPT = """\
Summarize this transcript for the agent that produced it. Include:
- what has been done so far (files read or changed, commands run, their results);
- important facts discovered (file paths, function names, error messages, test status);
- what was still left to do.
Do not invent anything that is not in the transcript.

<transcript>
{transcript}
</transcript>"""


def estimate_tokens(messages: list[Message], system: str = "") -> int:
    """Approximate token count of a request (chars / 4). Cheap, offline, provider-neutral."""
    chars = len(system)
    for message in messages:
        chars += len(message.content)
        chars += sum(len(c.name) + len(json.dumps(c.arguments)) for c in message.tool_calls)
        chars += sum(len(r.content) for r in message.tool_results)
    return chars // CHARS_PER_TOKEN


@dataclass
class Compaction:
    """Outcome of one `maybe_compact` call."""

    messages: list[Message]
    usage: Usage = field(default_factory=Usage)  # cost of the summary call, if any
    cleared_results: int = 0
    summarized_messages: int = 0

    @property
    def changed(self) -> bool:
        return self.cleared_results > 0 or self.summarized_messages > 0


@dataclass
class Compactor:
    llm: LLMClient  # the *small* model: summarizing does not need the expensive one
    threshold_tokens: int = 100_000
    keep_last_steps: int = 6
    clear_results_over_chars: int = 2_000
    summary_max_tokens: int = 1_500

    def maybe_compact(self, messages: list[Message], system: str = "") -> Compaction:
        if estimate_tokens(messages, system) < self.threshold_tokens:
            return Compaction(messages)
        split = self.split_index(messages)
        if split is None:
            return Compaction(messages)  # everything is recent; nothing we may touch
        cleared, count = clear_old_tool_results(messages, split, self.clear_results_over_chars)
        if estimate_tokens(cleared, system) < self.threshold_tokens:
            return Compaction(cleared, cleared_results=count)
        return self._summarize(cleared, split, count)

    def split_index(self, messages: list[Message]) -> int | None:
        """Index of the first message to keep verbatim: the start of the last N steps."""
        assistant_indices = [i for i, m in enumerate(messages) if m.role == "assistant"]
        if len(assistant_indices) <= self.keep_last_steps:
            return None
        return assistant_indices[-self.keep_last_steps]

    def _summarize(self, messages: list[Message], split: int, cleared: int) -> Compaction:
        old, recent = messages[:split], messages[split:]
        try:
            response = self.llm.complete(
                [Message.user(SUMMARY_PROMPT.format(transcript=render_transcript(old)))],
                system=SUMMARY_SYSTEM,
                tools=[],
                max_tokens=self.summary_max_tokens,
            )
        except Exception:
            # A failed summary should not kill the task; stage 1 already saved some room.
            return Compaction(messages, cleared_results=cleared)
        summary = summary_message(response.text, old)
        return Compaction(
            [summary, *recent],
            usage=response.usage,
            cleared_results=cleared,
            summarized_messages=len(old),
        )


def clear_old_tool_results(
    messages: list[Message], before: int, over_chars: int
) -> tuple[list[Message], int]:
    """Copy of `messages` where long tool results before index `before` are placeholders."""
    result: list[Message] = []
    count = 0
    for index, message in enumerate(messages):
        if index >= before or message.role != "tool":
            result.append(message)
            continue
        long_ids = {r.call_id for r in message.tool_results if len(r.content) > over_chars}
        count += len(long_ids)
        result.append(
            Message.tool(
                [_placeholder(r) if r.call_id in long_ids else r for r in message.tool_results]
            )
        )
    return result, count


def _placeholder(result: ToolResult) -> ToolResult:
    content = CLEARED_RESULT.format(chars=len(result.content))
    return ToolResult(call_id=result.call_id, content=content, is_error=result.is_error)


def summary_message(summary: str, old: list[Message]) -> Message:
    """The user turn that replaces the summarized part. User requests are kept verbatim,
    because losing the actual task is the worst thing compaction can do."""
    requests = "\n".join(f"- {m.content}" for m in old if m.role == "user" and m.content)
    return Message.user(
        "[Context was compacted. Summary of the earlier conversation:]\n"
        f"{summary.strip()}\n\n"
        f"[The user's requests so far, verbatim:]\n{requests}\n\n"
        "[Continue from here.]"
    )


def render_transcript(messages: list[Message], max_chars: int = 200_000) -> str:
    """Plain-text transcript for the summarizer. Tool results are shortened."""
    lines: list[str] = []
    for message in messages:
        if message.role == "user" and message.content:
            lines.append(f"USER: {message.content}")
        elif message.role == "assistant":
            if message.content:
                lines.append(f"ASSISTANT: {message.content}")
            for call in message.tool_calls:
                lines.append(f"TOOL CALL {call.name}({json.dumps(call.arguments)[:300]})")
        else:
            for r in message.tool_results:
                status = "ERROR" if r.is_error else "RESULT"
                lines.append(f"TOOL {status}: {r.content[:500]}")
    return truncate_output("\n".join(lines), max_lines=10_000, max_chars=max_chars)
