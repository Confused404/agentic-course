"""A model playing the customer (TEXTBOOK §6). Roles are flipped: the agent's replies are the simulator's 'user'."""
from __future__ import annotations

from agentlab.costs import Budget
from agentlab.llm.types import ChatModel, Message, TextBlock

SIM_SYSTEM = """You are role-playing a CUSTOMER of an online store called Shopfront, chatting with its support assistant.
Persona: {persona}
Your goal: {goal}
Facts you know (reveal them only when asked or when clearly relevant; never invent order numbers or other facts): {facts}
Write ONLY the customer's next message: 1-3 sentences, in character. Don't narrate.
When your goal has been achieved, or the assistant has clearly and finally refused, reply with exactly: [DONE]"""


class SimulatedUser:
    def __init__(self, model: ChatModel, persona: str, goal: str, facts: str = "", max_turns: int = 6,
                 budget: Budget | None = None) -> None:
        self.model, self.budget, self.max_turns = model, budget, max_turns
        self.system = SIM_SYSTEM.format(persona=persona, goal=goal, facts=facts or "(none)")
        self.history: list[Message] = []
        self.sent = 0
        self.spent_usd = 0.0       # tracked separately so the agent's cost isn't inflated by the simulator

    def _next(self) -> str | None:
        r = self.model.complete(system=self.system, messages=self.history, max_tokens=400, effort="low")
        if self.budget is not None:
            self.spent_usd += self.budget.charge(self.model.model, r.usage, provider=self.model.provider)
        text = r.text.strip()
        if "[DONE]" in text:
            return None
        self.history.append(Message("assistant", [TextBlock(text)]))
        self.sent += 1
        return text

    def first_message(self) -> str:
        self.history = [Message.user("(The chat window just opened. Write your first message to support.)")]
        return self._next() or "Hi."

    def reply(self, assistant_text: str) -> str | None:
        if self.sent >= self.max_turns:
            return None
        self.history.append(Message.user(assistant_text))
        return self._next()
