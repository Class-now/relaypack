"""Live smoke test: run the first N tasks in Meko mode against Claude + the Meko MCP server.

    python -m relaypack.smoke 2
"""
import sys
import time

from .llm import ClaudeLLM
from .meko import MekoMCP
from .pipeline import Relay
from .tasks import TASKS

n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
relay = Relay(ClaudeLLM(), "meko", MekoMCP(), run_id=time.strftime("smoke-%Y%m%d%H%M%S"))
for t in TASKS[:n]:
    r = relay.run_task(t)
    print(t.func, "passed" if r.passed else "FAILED", r.attempts, r.input_tokens + r.output_tokens, f"{r.seconds:.1f}s",
          flush=True)
