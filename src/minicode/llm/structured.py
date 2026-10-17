"""Structured output: ask for JSON, validate with pydantic, retry with the error.

Both providers offer native "JSON schema" modes, but this helper deliberately uses
the portable approach (schema in the prompt + validation + retry) so it works with
any LLMClient, including FakeLLMClient, and shows the retry loop explicitly.
The validation error is fed back to the model because models are good at fixing
a mistake once they are told exactly what was wrong.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from minicode.llm.base import LLMClient
from minicode.llm.types import Message

STRUCTURED_SYSTEM = (
    "You produce machine-readable output. Reply with a single JSON object that matches "
    "the given JSON Schema. No prose, no Markdown fences."
)


class StructuredOutputError(Exception):
    """The model never produced valid output within the allowed attempts."""

    def __init__(self, message: str, last_text: str) -> None:
        super().__init__(message)
        self.last_text = last_text


def complete_structured[T: BaseModel](
    llm: LLMClient,
    prompt: str,
    model: type[T],
    *,
    max_retries: int = 2,
    max_tokens: int = 1024,
    system: str = STRUCTURED_SYSTEM,
) -> T:
    """Return an instance of `model` parsed from the LLM's reply.

    Makes at most `1 + max_retries` calls. Each retry keeps the conversation so the
    model sees its own bad answer next to the validation error.
    """
    messages = [Message.user(_with_schema(prompt, model))]
    last_text = ""
    last_error = ""
    for _attempt in range(max_retries + 1):
        response = llm.complete(messages, system=system, tools=[], max_tokens=max_tokens)
        last_text = response.text
        try:
            return model.model_validate_json(extract_json(response.text))
        except ValidationError as exc:
            last_error = format_validation_error(exc)
            messages.append(Message.assistant(response))
            messages.append(Message.user(_retry_prompt(last_error)))
    raise StructuredOutputError(
        f"No valid {model.__name__} after {max_retries + 1} attempts. Last error: {last_error}",
        last_text,
    )


def extract_json(text: str) -> str:
    """Pull the JSON object out of a reply, tolerating Markdown fences or chatter around it."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return text.strip()
    return text[start : end + 1]


def format_validation_error(exc: ValidationError) -> str:
    """Compact, model-readable list of problems, e.g. `age: Input should be a valid integer`."""
    lines = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "(root)"
        lines.append(f"{location}: {error['msg']}")
    return "; ".join(lines)


def _with_schema(prompt: str, model: type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(), indent=2)
    return f"{prompt}\n\nRespond with JSON matching this JSON Schema:\n{schema}"


def _retry_prompt(error: str) -> str:
    return (
        f"Your previous reply was not valid: {error}\n"
        "Reply again with only the corrected JSON object."
    )
