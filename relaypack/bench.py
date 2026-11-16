"""Benchmark: the same 12 tasks, baseline vs Meko, N runs each.

    python -m relaypack.bench --runs 10            # offline simulator + local Meko stand-in
    python -m relaypack.bench --runs 10 --live     # Claude API + Meko MCP (needs keys)

Writes results/results.md, results/runs.csv and results/trace.md (the Postgres
attempt log and the decision trace of one 12-task Meko run).
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import time
from pathlib import Path

from .llm import ClaudeLLM, SimLLM, cost_usd
from .meko import LocalMeko, MekoMCP
from .pipeline import Relay
from .tasks import TASKS


LAST: dict = {}
STAMP = time.strftime("%Y%m%d%H%M")  # run ids stay unique across repeated live benchmarks on one datapack

LESSON_SQL = """SELECT lesson, COUNT(*) AS failures, MIN(task) AS first_seen
FROM relay_attempts WHERE run_id = {run} AND NOT passed AND lesson <> ''
GROUP BY lesson ORDER BY first_seen;"""
TASK_SQL = """SELECT task, MAX(attempt) AS attempts, MAX(lessons_seen) AS lessons_in_prompt,
MAX(input_tokens + output_tokens) AS tokens
FROM relay_attempts WHERE run_id = {run} GROUP BY task ORDER BY task;"""


def run_once(llm, mode: str, live: bool, n_tasks: int, k: int = 0) -> dict:
    meko = (MekoMCP() if live else LocalMeko()) if mode == "meko" else None
    run_id = f"{STAMP}-{mode}-{n_tasks}-{k}"
    relay = Relay(llm, mode, meko, run_id=run_id)
    results = [relay.run_task(t) for t in TASKS[:n_tasks]]
    if mode == "meko" and n_tasks == 12:
        LAST.update(meko=relay.meko, run_id=run_id)
    i = sum(r.input_tokens for r in results)
    o = sum(r.output_tokens for r in results)
    return {
        "mode": mode, "tasks": n_tasks,
        "input_tokens": i, "output_tokens": o, "total_tokens": i + o,
        "tokens_per_task": (i + o) / n_tasks,
        "seconds": sum(r.seconds for r in results),
        "cost_usd": cost_usd(llm.model, i, o),
        "pass_rate": sum(r.passed for r in results) / n_tasks,
        "retries": sum(r.attempts - 1 for r in results),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--out", default="results")
    ap.add_argument("--aggregate-only", action="store_true",
                    help="live: build results.md from runs.jsonl without starting new runs")
    a = ap.parse_args()
    llm = ClaudeLLM() if a.live else SimLLM()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    # Live runs take about an hour, so each finished run is appended to a checkpoint and a
    # re-run resumes where the last one stopped (delete runs.jsonl to start over).
    ckpt = out / "runs.jsonl"
    done = [json.loads(l) for l in ckpt.read_text().splitlines() if l.strip()] if a.live and ckpt.exists() else []
    if not a.live and ckpt.exists():
        ckpt.unlink()
    rows = []
    for n in (4, 8, 12):
        for m in ("baseline", "meko"):
            for k in range(a.runs):
                hit = next((r for r in done if (r["mode"], r["tasks"], r.get("k")) == (m, n, k)), None)
                if hit is None and a.aggregate_only:
                    continue
                if hit is None:
                    hit = dict(run_once(llm, m, a.live, n, k), k=k)
                    if a.live:
                        with open(ckpt, "a") as f:
                            f.write(json.dumps(hit) + chr(10))
                    print(f"done {m} tasks={n} run={k} tokens={hit['total_tokens']} pass={hit['pass_rate']:.0%}", flush=True)
                rows.append(hit)
    with open(out / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def agg(mode, n, key):
        return st.mean(r[key] for r in rows if r["mode"] == mode and r["tasks"] == n)

    def count(mode, n):
        return sum(1 for r in rows if r["mode"] == mode and r["tasks"] == n)

    short = [(m, n, count(m, n)) for n in (4, 8, 12) for m in ("baseline", "meko") if count(m, n) < a.runs]
    lines = [f"# Relaypack results ({'live: Claude API + Meko MCP' if a.live else 'offline: simulated LLM + local Meko stand-in'}, {a.runs} runs per cell)", ""]
    if short:
        lines += ["Cells with fewer runs: " + ", ".join(f"{m} x {n} tasks = {c} runs" for m, n, c in short)
                  + " (the Meko free tier caps `conversation_add_message` at 1,000 lifetime calls).", ""]
    lines += ["| tasks | mode | total tokens | tokens/task | latency (s) | cost (USD) | pass rate | retries |",
              "|---|---|---|---|---|---|---|---|"]
    for n in (4, 8, 12):
        for m in ("baseline", "meko"):
            lines.append(f"| {n} | {m} | {agg(m, n, 'total_tokens'):,.0f} | {agg(m, n, 'tokens_per_task'):,.0f} | "
                         f"{agg(m, n, 'seconds'):.1f} | {agg(m, n, 'cost_usd'):.4f} | {agg(m, n, 'pass_rate'):.0%} | {agg(m, n, 'retries'):.1f} |")
    lines += ["", "| tasks | token reduction | retry reduction |", "|---|---|---|"]
    for n in (4, 8, 12):
        b, k = agg("baseline", n, "total_tokens"), agg("meko", n, "total_tokens")
        rb, rk = agg("baseline", n, "retries"), agg("meko", n, "retries")
        lines.append(f"| {n} | {1 - k / b:.0%} | {rb:.1f} → {rk:.1f} |")
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if LAST:
        (out / "trace.md").write_text(trace_report(LAST["meko"], LAST["run_id"]), encoding="utf-8")


def _upload_attempts(meko, run: str) -> None:
    import io
    rows = meko.db_read(f"SELECT * FROM relay_attempts WHERE run_id = {run} ORDER BY task, attempt;")
    if not rows:
        return
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    meko.artifact_put("relay_attempts.csv", buf.getvalue(), "text/csv")


def _table(rows: list[dict]) -> list[str]:
    if not rows:
        return ["(no rows)"]
    cols = list(rows[0])
    return ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols),
            *["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]]


def trace_report(meko, run_id: str) -> str:
    run = "'" + run_id + "'"
    hosted = "db_run_read_only_query" in getattr(meko, "catalogue", ())
    where = ("the datapack's Postgres table `relay_attempts`" if hosted or not hasattr(meko, "catalogue") else
             "the `relay_attempts` attempt log (SQLite mirror; this MCP endpoint exposes no SQL tools, "
             "so the rows are also stored in the datapack as the artifact `relay_attempts.csv`)")
    if hasattr(meko, "catalogue") and not hosted:
        _upload_attempts(meko, run)
    lines = [f"# Relaypack trace — run `{run_id}` (12 tasks, Meko mode)", "",
             f"## Which lessons were learned, and where (SQL on {where})", "",
             "```sql", LESSON_SQL.format(run=run), "```", "", *_table(meko.db_read(LESSON_SQL.format(run=run))), "",
             "## Attempts per task", "", "```sql", TASK_SQL.format(run=run), "```", "",
             *_table(meko.db_read(TASK_SQL.format(run=run)))]
    if getattr(meko, "decisions", None):
        lines += ["", "## Decision trace (the `reasoning` stored with each Coder turn)", ""]
        lines += [f"- `{d['conv']}` {d['reasoning']}" for d in meko.decisions if d["agent"] == "coder"][:16]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
