# Relaypack — design notes

ContextCon: Remember Everything · Challenge 08 *Token efficiency* · also entered for *Best use of shared memory*

## 1. The problem

A coding relay of several agents is cheap to build and expensive to run. The common way to give each agent context is to pass everything along: the house coding guide is pasted into every prompt, and every agent receives the full transcript of the agents before it. Two costs follow.

1. **Tokens grow with every hand-off.** The fourth agent in the chain reads the guide for the fourth time and three transcripts it mostly does not need. Add an agent, or a retry, and the bill grows again.
2. **The team never learns.** When the Reviewer finds that the Coder forgot the empty-input case, that lesson lives in one task's transcript and disappears when the task ends. On the next task the same class of bug is written, tested, failed and fixed again, and each round trip costs a full set of prompts.

Relaypack measures both costs on the same tasks, with and without Meko, and keeps quality fixed.

## 2. The relay

```
          ┌──────────┐   plan    ┌────────┐  code   ┌────────┐ report ┌──────────┐
 spec ──▶ │ Planner  │ ───────▶ │ Coder  │ ──────▶ │ Tester │ ─────▶ │ Reviewer │ ──▶ APPROVED
          └──────────┘          └────────┘         └────────┘        └──────────┘
                                     ▲                                     │
                                     └──────── LESSON (max 2 retries) ─────┘
```

- **Planner** writes a five-bullet plan.
- **Coder** returns one Python code block.
- **Tester** is not a model: it runs the task's hidden unit tests in an isolated subprocess (`python -I`, 10 s timeout). Quality is the hidden-test pass rate, so a mode cannot look cheaper by writing worse code.
- **Reviewer** approves, or states one general rule that would have prevented the failure (`LESSON: …`). The Coder gets up to two retries.

Twelve small tasks (`relaypack/tasks.py`) cover lists, strings and numbers. Nine of them contain one of three classic traps — empty input, letter case, negative numbers — so whether a lesson reaches the Coder in time is visible in the retry count.

## 3. Where Meko sits

| Context the agents need | Baseline (pass everything) | Meko mode | Meko feature |
|---|---|---|---|
| House coding guide | full text in every prompt | uploaded once; each agent gets the 4 passages that match its step | knowledge base: `knowledgebase_upload_document`, `knowledgebase_search` |
| What earlier agents said | full transcript | each turn stored; each agent gets the 3 most relevant turns | conversations: `conversation_create`, `conversation_add_message`, `context_search` |
| What the team has learned | lost when the task ends | Reviewer's lesson saved, then promoted to shared memory; the Coder searches it on every later task | collective memory: `memory_add`, `memory_promote`, `memory_search` |
| Why an agent did what it did | — | every turn is stored with `reasoning`: the guide passages, turns and lessons it was given | decision trace on `conversation_add_message` |
| What happened, as data | — | one row per test attempt in `relay_attempts` (task, attempt, passed, report, lesson, lessons in prompt, tokens) | SQL table (`db_run_write_query` / `db_run_read_only_query` when the endpoint offers them; the hosted MCP endpoint does not, so a local SQLite mirror is used and the table is stored in the datapack with `artifact_put` as `relay_attempts.csv`) |
| What it cost | — | each model call recorded against its conversation | `track_token_usage` (per-turn costs in the Traces view) |
| What it produced | — | each passing solution stored whole | `artifact_put` |

The Meko client (`relaypack/meko.py`) talks to the Meko MCP server directly over streamable HTTP JSON-RPC with the standard library, so the benchmark has no framework between the agents and Meko. Every tool name and argument follows the Meko MCP Server reference; `tests/test_meko_mcp.py` runs the whole relay against a fake server that rejects any argument the reference does not list.

### Why shared memory is the part that matters

Retrieval alone (knowledge base + `context_search`) cuts tokens per call. Shared memory cuts the number of calls. In the baseline a trap costs one retry *per task that contains it*; with promoted lessons it costs one retry *per kind of trap*, once for the whole team. Over twelve tasks that is 10 retries against 3, and each avoided retry is a Coder, Tester and Reviewer round that never runs.

### Answering "why did the agent do that?" in one query

Because each attempt is a row in an SQL table, the story of a run is SQL, not log scraping:

```sql
SELECT lesson, COUNT(*) AS failures, MIN(task) AS first_seen
FROM relay_attempts
WHERE run_id = :run AND NOT passed AND lesson <> ''
GROUP BY lesson ORDER BY first_seen;
```

The answer for a 12-task run is three rows — one lesson each from t01, t02 and t03 — and from t04 on every Coder turn's `reasoning` lists all three lessons and every task passes first time. `results/trace.md` is produced by the benchmark from these queries.

## 4. How it is measured

Challenge 08 asks for a baseline and a Meko run on the same input, at least ten times each, with tokens, latency, cost and quality.

- **Same input.** Both modes run the same tasks in the same order with the same system prompts. Only the context block differs.
- **Ten runs per cell**, at 4, 8 and 12 tasks, so the effect of a longer run is visible.
- **Clean start.** Each Meko run begins with `memory_delete_all` for the relay's agent namespace and uses a fresh `run_id`, so run 2 does not inherit run 1's lessons.
- **Tokens.** Live: the `usage` field of every Claude response. Offline: characters / 4 on the real prompts the pipeline builds.
- **Latency.** Live: wall clock of each model call. Offline: modelled (prefill 4k tok/s, decode 60 tok/s).
- **Cost.** List prices per million tokens for the chosen model.
- **Quality.** Hidden-test pass rate, plus retries.

The offline mode replaces the model with a deterministic stand-in: it returns the reference solution unless a task's trap is in play and the matching lesson is absent from the Coder's prompt, in which case it returns the typical first-attempt bug. That isolates the one thing the benchmark is about — whether the right context reached the agent — and makes the token counts exactly reproducible on any machine with Python. The live mode (`--live`) swaps in Claude and the Meko MCP server without changing the pipeline.

## 5. Results (offline, 10 runs per cell)

| tasks | mode | total tokens | tokens/task | latency (s) | cost (USD) | pass rate | retries |
|---|---|---|---|---|---|---|---|
| 4 | baseline | 28,947 | 7,237 | 14.0 | 0.1224 | 100% | 3.0 |
| 4 | meko | 5,124 | 1,281 | 6.8 | 0.0258 | 100% | 3.0 |
| 8 | baseline | 61,512 | 7,689 | 30.8 | 0.2610 | 100% | 7.0 |
| 8 | meko | 8,357 | 1,045 | 11.0 | 0.0421 | 100% | 3.0 |
| 12 | baseline | 90,587 | 7,549 | 45.1 | 0.3842 | 100% | 10.0 |
| 12 | meko | 11,553 | 963 | 15.1 | 0.0581 | 100% | 3.0 |

- **87% fewer tokens at 12 tasks, the same 100% pass rate.**
- **The saving grows with the run.** Baseline tokens per task stay flat (about 7,500); with Meko they fall from 1,281 to 963, because the guide is never re-sent and lessons stop retries early.
- **Retries stop growing.** 10 → 3 at 12 tasks: one per kind of trap.
- **Latency falls by two thirds**, mostly from shorter prompts.

## 6. Limits and next steps

- The task set is small and synthetic by design, so that a full benchmark costs cents. The same relay runs on any task list with a spec and tests.
- Retrieval sizes (4 guide passages, 3 turns, 3 lessons) are fixed. Sweeping them would show where quality starts to drop — the point where "send less" becomes "send too little".
- Meko's self-learning tools (`selflearning_status`, `selflearning_shortfalls`) report which searches matched weakly; feeding those back into the guide is the natural next step.

## 7. Files

| Path | What |
|---|---|
| `relaypack/tasks.py` | 12 tasks, hidden tests, the house guide, the three lessons |
| `relaypack/pipeline.py` | the relay, both context modes, the decision trace and the SQL attempt log |
| `relaypack/meko.py` | Meko MCP client (standard library) and the offline stand-in with the same calls |
| `relaypack/llm.py` | Claude backend, offline stand-in, prices |
| `relaypack/bench.py` | the benchmark, `results.md`, `runs.csv`, `trace.md` |
| `tests/test_meko_mcp.py` | the relay against a fake MCP server that checks every argument |
