"""LLM backends: Claude through the Anthropic SDK, and a deterministic offline simulator.

The simulator never calls a model. It returns the reference solution unless the
task's pitfall lesson is absent from the Coder's prompt, in which case it
returns the typical first-attempt bug. That models the one behaviour the
benchmark is about (does the right context reach the agent?) and lets token
counts be measured exactly on the real prompts the pipeline builds.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass

from .tasks import LESSONS, Task

PRICES = {  # USD per million tokens (input, output)
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass
class Reply:
    text: str
    input_tokens: int
    output_tokens: int
    seconds: float


def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


class SimLLM:
    model = os.environ.get("RELAYPACK_PRICE_MODEL", "claude-opus-5-5")

    def complete(self, agent: str, system: str, prompt: str, task: Task) -> Reply:
        if agent == "coder":
            lesson = LESSONS.get(task.pitfall, "")
            knows = not task.buggy or (lesson and lesson in prompt)
            text = "```python\n" + (task.solution if knows else task.buggy) + "```"
        elif agent == "planner":
            text = f"Plan for {task.func}: read the spec, list edge cases, implement, keep under 15 lines."
        elif agent == "reviewer":
            text = f"LESSON: {LESSONS[task.pitfall]}" if "FAILED" in prompt and task.pitfall else "APPROVED"
        else:
            text = ""
        i, o = approx_tokens(system + prompt), approx_tokens(text)
        # modelled latency: prefill ~4k tok/s, decode ~60 tok/s
        return Reply(text, i, o, i / 4000 + o / 60)


class ClaudeLLM:
    def __init__(self, model: str | None = None, effort: str = "low") -> None:
        import anthropic

        self.client = anthropic.Anthropic(max_retries=6)
        self.model = model or os.environ.get("RELAYPACK_MODEL", "claude-opus-5-5")
        self.effort = effort

    def complete(self, agent: str, system: str, prompt: str, task: Task) -> Reply:
        t0 = time.perf_counter()
        r = self.client.messages.create(
            model=self.model, max_tokens=4000, system=system,
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in r.content if b.type == "text")
        return Reply(text, r.usage.input_tokens, r.usage.output_tokens, time.perf_counter() - t0)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (input_tokens * pin + output_tokens * pout) / 1e6
