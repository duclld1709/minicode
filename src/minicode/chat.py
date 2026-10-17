"""A multi-turn chat session without tools (M0).

LLM APIs are stateless: each call sees only what we send. "Memory" in a chat is
just us keeping the history and resending all of it every turn. `ChatSession`
makes that explicit so it can be tested and later reused by the agent loop.
"""

from __future__ import annotations

from minicode.llm.base import LLMClient, TextCallback
from minicode.llm.pricing import Price, estimate_cost
from minicode.llm.types import LLMResponse, Message, Usage

DEFAULT_CHAT_SYSTEM = "You are a helpful, concise assistant for software engineers."


class ChatSession:
    def __init__(
        self,
        llm: LLMClient,
        *,
        system: str = DEFAULT_CHAT_SYSTEM,
        max_tokens: int = 4096,
        prices: dict[str, Price] | None = None,
    ) -> None:
        self.llm = llm
        self.system = system
        self.max_tokens = max_tokens
        self.prices = prices or {}
        self.history: list[Message] = []
        self.total_usage = Usage()

    def send(self, text: str, on_text: TextCallback | None = None) -> LLMResponse:
        """Append the user turn, call the model with the *whole* history, store the reply."""
        self.history.append(Message.user(text))
        try:
            response = self.llm.complete(
                self.history,
                system=self.system,
                tools=[],
                max_tokens=self.max_tokens,
                on_text=on_text,
            )
        except Exception:
            # Roll back so a failed call (network, auth) does not leave a dangling user turn.
            self.history.pop()
            raise
        self.history.append(Message.assistant(response))
        self.total_usage = self.total_usage + response.usage
        return response

    def cost_of(self, usage: Usage) -> float | None:
        return estimate_cost(self.llm.model, usage, self.prices)

    @property
    def total_cost(self) -> float | None:
        return self.cost_of(self.total_usage)
