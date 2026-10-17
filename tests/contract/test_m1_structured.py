"""Contract tests for `complete_structured` (M1)."""

import pytest
from pydantic import BaseModel

from minicode.llm.fake_client import FakeLLMClient
from minicode.llm.structured import StructuredOutputError, complete_structured

pytestmark = pytest.mark.m1


class Verdict(BaseModel):
    kind: str
    confidence: float


def test_parses_valid_json() -> None:
    llm = FakeLLMClient(script=['{"kind": "question", "confidence": 0.9}'])
    result = complete_structured(llm, "Classify: what does foo() do?", Verdict)
    assert result == Verdict(kind="question", confidence=0.9)


def test_tolerates_markdown_fences() -> None:
    llm = FakeLLMClient(script=['```json\n{"kind": "edit", "confidence": 1}\n```'])
    assert complete_structured(llm, "x", Verdict).kind == "edit"


def test_prompt_contains_the_schema() -> None:
    llm = FakeLLMClient(script=['{"kind": "edit", "confidence": 1}'])
    complete_structured(llm, "Classify this", Verdict)
    prompt = llm.calls[0].messages[0].content
    assert "Classify this" in prompt
    assert '"confidence"' in prompt


def test_retries_with_the_validation_error() -> None:
    llm = FakeLLMClient(
        script=[
            '{"kind": "edit", "confidence": "very"}',  # wrong type
            '{"kind": "edit", "confidence": 0.5}',
        ]
    )
    result = complete_structured(llm, "x", Verdict)

    assert result.confidence == 0.5
    retry_messages = llm.calls[1].messages
    assert [m.role for m in retry_messages] == ["user", "assistant", "user"]
    assert "confidence" in retry_messages[-1].content  # the error names the bad field


def test_gives_up_after_max_retries() -> None:
    llm = FakeLLMClient(script=["not json", "still not", "nope"])
    with pytest.raises(StructuredOutputError) as info:
        complete_structured(llm, "x", Verdict, max_retries=2)
    assert len(llm.calls) == 3
    assert info.value.last_text == "nope"
