"""Planner -> Coder -> Tester -> Reviewer relay, in two context modes.

baseline: every agent receives the full house guide and the full transcript of
          the agents before it (the common "pass everything along" pattern).
meko:     the guide lives in the Meko knowledge base and each agent pulls only
          the passages relevant to its step; earlier turns are retrieved with
          context_search; Reviewer lessons are promoted to shared memory and
          reach the Coder on later tasks. Every turn carries a decision trace
          (which guide passages, turns and lessons it was given), and every test
          attempt is a row in the datapack's Postgres table relay_attempts, so
          "which lesson stopped which retry" is one SQL query.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field

from .llm import Reply
from .meko import LocalMeko
from .tasks import STYLE_GUIDE, Task

SYSTEMS = {
    "planner": "You are the Planner in a four-agent coding relay. Write a short plan (max 5 bullets) for the function in the spec.",
    "coder": "You are the Coder. Return only one Python code block that implements the spec. Follow the guide and any team lessons.",
    "reviewer": "You are the Reviewer. If the test report says FAILED, reply with one line 'LESSON: <general rule that prevents this class of bug>'. Otherwise reply APPROVED.",
}
MAX_RETRIES = 2
ATTEMPTS_DDL = ("CREATE TABLE IF NOT EXISTS relay_attempts (run_id TEXT, task TEXT, attempt INTEGER, "
                "passed BOOLEAN, report TEXT, lesson TEXT, lessons_seen INTEGER, input_tokens INTEGER, "
                "output_tokens INTEGER);")


def sql_str(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


@dataclass
class TaskResult:
    task: str
    passed: bool
    attempts: int
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    calls: list[dict] = field(default_factory=list)


def run_tests(code: str, task: Task) -> tuple[bool, str]:
    src = code + "\n" + "\n".join(task.tests) + "\nprint('OK')\n"
    try:
        p = subprocess.run([sys.executable, "-I", "-c", src], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return False, "FAILED: timeout"
    if p.returncode == 0 and "OK" in p.stdout:
        return True, "PASSED"
    last = (p.stderr.strip().splitlines() or ["unknown error"])[-1]
    return False, f"FAILED: {last}"


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text


class Relay:
    def __init__(self, llm, mode: str, meko: LocalMeko | None = None, run_id: str = "run") -> None:
        assert mode in ("baseline", "meko")
        self.llm, self.mode, self.run_id = llm, mode, run_id
        self.meko = meko if meko is not None else LocalMeko()
        self.seen: dict[str, list[str]] = {}
        if mode == "meko":
            self.meko.reset_memory()
            self.meko.knowledgebase_add(STYLE_GUIDE, source="house-guide")
            self.meko.db_write(ATTEMPTS_DDL)

    def _context(self, conv: str, transcript: list[str], query: str, agent: str) -> str:
        if self.mode == "baseline":
            return "HOUSE GUIDE:\n" + STYLE_GUIDE + "\n\nTRANSCRIPT SO FAR:\n" + "\n".join(transcript)
        guide = self.meko.knowledgebase_search(query, k=4)
        turns = self.meko.context_search(conv, query, k=3)
        parts = ["GUIDE (relevant passages):", *guide, "RELEVANT EARLIER TURNS:", *turns]
        lessons = []
        if agent == "coder":
            lessons = self.meko.memory_search(query + " empty case negative edge", k=3)
            parts += ["TEAM LESSONS (shared memory):", *lessons]
        self.seen[agent] = [f"{len(guide)} guide passages", f"{len(turns)} earlier turns",
                            *[f"lesson: {l}" for l in lessons]]
        return "\n".join(parts)

    def _ask(self, res: TaskResult, agent: str, conv: str, transcript: list[str], task: Task, query: str, extra: str = "") -> Reply:
        prompt = self._context(conv, transcript, query, agent) + f"\n\nSPEC: {task.spec}\n{extra}"
        r = self.llm.complete(agent, SYSTEMS[agent], prompt, task)
        res.input_tokens += r.input_tokens
        res.output_tokens += r.output_tokens
        res.seconds += r.seconds
        res.calls.append({"agent": agent, "in": r.input_tokens, "out": r.output_tokens})
        line = f"[{agent}] {r.text}"
        transcript.append(line)
        if self.mode == "meko":
            why = f"{agent} acted on: " + "; ".join(self.seen.get(agent, []))
            self.meko.conversation_add_message(conv, agent, r.text, reasoning=why)
            self.meko.track_token_usage(agent, r.input_tokens, r.output_tokens)
        return r

    def run_task(self, task: Task) -> TaskResult:
        conv = f"{self.mode}-{task.id}"
        res = TaskResult(task.id, False, 0)
        transcript = [f"[user] SPEC: {task.spec}"]
        if self.mode == "meko":
            self.meko.conversation_add_message(conv, "user", task.spec)
        self._ask(res, "planner", conv, transcript, task, f"plan {task.func} {task.spec}")
        report = ""
        for attempt in range(1 + MAX_RETRIES):
            res.attempts = attempt + 1
            r = self._ask(res, "coder", conv, transcript, task, f"implement {task.func} edge cases {task.spec} {report}")
            code = extract_code(r.text)
            ok, report = run_tests(code, task)
            transcript.append(f"[tester] {report}")
            if self.mode == "meko":
                self.meko.conversation_add_message(conv, "tester", report)
            rv = self._ask(res, "reviewer", conv, transcript, task, f"review {task.func} {report}", extra=f"TEST REPORT: {report}")
            lesson = "" if ok else rv.text.split("LESSON:", 1)[-1].strip()
            if self.mode == "meko":
                n_lessons = sum(1 for x in self.seen.get("coder", []) if x.startswith("lesson:"))
                self.meko.db_write(
                    "INSERT INTO relay_attempts VALUES (" + ", ".join([
                        sql_str(self.run_id), sql_str(task.id), str(attempt + 1), "TRUE" if ok else "FALSE",
                        sql_str(report), sql_str(lesson), str(n_lessons),
                        str(res.input_tokens), str(res.output_tokens)]) + ");")
            if ok:
                res.passed = True
                if self.mode == "meko":
                    self.meko.artifact_put(f"{task.func}.py", code)
                break
            if lesson:
                if self.mode == "meko":
                    self.meko.memory_add(lesson, scope="agent")
                    self.meko.memory_promote(lesson)
                else:
                    transcript.append(f"[reviewer->coder] {lesson}")
        return res
