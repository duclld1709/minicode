import pytest

from minicode.chat import ChatSession
from minicode.llm.fake_client import FakeLLMClient, text_response
from minicode.llm.pricing import Price
from minicode.llm.types import Usage

pytestmark = pytest.mark.m0


def test_every_turn_resends_the_whole_history() -> None:
    # The core M0 lesson: the model is stateless, so we must send everything again.
    llm = FakeLLMClient(script=["Hi Duc!", "Your name is Duc."])
    session = ChatSession(llm)

    session.send("My name is Duc.")
    session.send("What is my name?")

    second_call = llm.calls[1]
    assert [(m.role, m.content) for m in second_call.messages] == [
        ("user", "My name is Duc."),
        ("assistant", "Hi Duc!"),
        ("user", "What is my name?"),
    ]


def test_usage_and_cost_accumulate() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=0)
    llm = FakeLLMClient(script=[text_response("a", usage), text_response("b", usage)])
    session = ChatSession(llm, prices={"fake-model": Price(input_per_mtok=1.0, output_per_mtok=0)})

    session.send("one")
    session.send("two")

    assert session.total_usage.input_tokens == 2_000_000
    assert session.total_cost == pytest.approx(2.0)


def test_unknown_price_gives_no_cost() -> None:
    session = ChatSession(FakeLLMClient(script=["a"]))
    session.send("x")
    assert session.total_cost is None


def test_failed_call_does_not_leave_dangling_user_turn() -> None:
    session = ChatSession(FakeLLMClient(script=[]))
    with pytest.raises(RuntimeError):
        session.send("hello")
    assert session.history == []
