# Relaypack — a four-agent coding relay that stops paying for the same context twice

ContextCon: Remember Everything — Challenge 08 *Token efficiency* (and *Best use of shared memory*).

Multi-agent coding pipelines usually pass everything along: every agent gets the full house guide and the full transcript of the agents before it. Tokens grow with every hand-off, and the team never learns — the same class of bug is fixed again on every task.

Relaypack runs **Planner → Coder → Tester → Reviewer** on twelve small Python tasks and puts **Meko** in the middle as the context layer:

| What | Baseline | With Meko |
|---|---|---|
| House coding guide | pasted in full into every prompt | stored once in the **knowledge base**; each agent gets the 4 passages relevant to its step (`knowledgebase_search`) |
| Earlier turns | full transcript | stored with `conversation_add_message`; each agent gets the 3 most relevant turns (`context_search`) |
| What the team learned | lost at the end of each task | Reviewer's lesson → `memory_add` → `memory_promote` to **shared memory**; the Coder reads it on later tasks (`memory_search`) |
| Why an agent did that | — | each turn is stored with its `reasoning` (which guide passages, turns and lessons it was given): the **decision trace** |
| What happened, as data | — | every test attempt is a row in the SQL table `relay_attempts` (the hosted Meko MCP endpoint exposes no SQL tools, so the table is kept in a local SQLite mirror and stored in the datapack as the artifact `relay_attempts.csv`); "which lesson stopped which retry" is one query (see `results/trace.md`) |
| Usage and outputs | — | every call logged with `track_token_usage`; passing code saved with `artifact_put` |

The Tester really runs hidden unit tests in a subprocess; quality is the hidden-test pass rate.

## Results

### Live run — Claude (Anthropic API) + hosted Meko MCP

Same 12 tasks, same inputs, 10 runs per cell (Challenge 08 asks for ≥10), measured on 2026-11-16/17. The 12-task Meko cell has 3 runs: the Meko free tier caps `conversation_add_message` at 1,000 lifetime calls and the benchmark hit it. Raw rows: `results/runs.csv`. Cost uses Claude Opus 5.5 list prices ($4 / $20 per million tokens).

| tasks | mode | total tokens | tokens/task | latency (s) | cost (USD) | pass rate | retries |
|---|---|---|---|---|---|---|---|
| 4 | baseline | 29,468 | 7,367 | 31.2 | 0.1521 | 100% | 0.0 |
| 4 | meko | 6,235 | 1,559 | 28.3 | 0.0586 | 100% | 0.0 |
| 8 | baseline | 59,021 | 7,378 | 61.3 | 0.3053 | 100% | 0.0 |
| 8 | meko | 13,380 | 1,672 | 59.2 | 0.1218 | 100% | 0.2 |
| 12 | baseline | 88,744 | 7,395 | 94.4 | 0.4614 | 100% | 0.0 |
| 12 | meko | 25,737 | 2,145 | 89.0 | 0.2119 | 100% | 0.0 |

**71–79% fewer tokens and 54–61% lower cost, same 100% pass rate.** Claude passed the hidden tests on the first try in both modes, so the live saving is pure context: the guide and the transcript are never re-sent. Latency is about the same, because the Meko round-trips cost roughly what the shorter prompts save.

### Offline run — reproducible without keys

A deterministic LLM stand-in that makes the typical first-attempt bug unless the matching lesson is in the Coder's prompt shows the second effect, shared memory cutting retries:

| tasks | mode | total tokens | tokens/task | latency (s) | cost (USD) | pass rate | retries |
|---|---|---|---|---|---|---|---|
| 4 | baseline | 28,947 | 7,237 | 14.0 | 0.1224 | 100% | 3.0 |
| 4 | meko | 5,124 | 1,281 | 6.8 | 0.0258 | 100% | 3.0 |
| 8 | baseline | 61,512 | 7,689 | 30.8 | 0.2610 | 100% | 7.0 |
| 8 | meko | 8,357 | 1,045 | 11.0 | 0.0421 | 100% | 3.0 |
| 12 | baseline | 90,587 | 7,549 | 45.1 | 0.3842 | 100% | 10.0 |
| 12 | meko | 11,553 | 963 | 15.1 | 0.0581 | 100% | 3.0 |

Here the baseline pays one retry for every task with an edge-case trap (10 over 12 tasks); with shared memory the team pays once per *kind* of trap (empty input, letter case, negative numbers — 3 in total).

## How it was measured

- Both modes build their real prompts from the same tasks; tokens are counted on those prompts and replies.
- The offline table uses a deterministic stand-in for the LLM (returns the typical first-attempt bug unless the matching lesson is in the Coder's prompt) and an in-memory stand-in for Meko with the same calls. Token counts are characters / 4; latency is modelled (prefill 4k tok/s, decode 60 tok/s).
- `--live` swaps in Claude through the Anthropic SDK (real `usage` tokens, wall-clock latency) and the Meko MCP server (`https://mcp.mekodata.ai/mcp`).

## Run it

```bash
python -m relaypack.bench --runs 10            # offline, no keys
python -m unittest tests.test_meko_mcp         # every Meko call checked against the documented tool arguments
pip install anthropic
export ANTHROPIC_API_KEY=... MEKO_API_KEY=...
python -m relaypack.meko                       # live: finds/creates the datapack, checks the tool catalogue
python -m relaypack.bench --runs 10 --live     # Claude + Meko (resumes from results/runs.jsonl)
python -m relaypack.bench --live --aggregate-only   # rebuild the tables from finished runs only
```

Results go to `results/results.md` and `results/runs.csv`; `results/trace.md` holds the SQL attempt log and the decision trace of one 12-task Meko run. Each Meko run starts with `memory_delete_all`, so run 2 does not inherit run 1's lessons. Design notes: [`docs/DESIGN.md`](docs/DESIGN.md).

## Layout

- `relaypack/tasks.py` — the 12 tasks, hidden tests, the house guide
- `relaypack/meko.py` — Meko MCP client (standard library only; tools and arguments as in the Meko MCP Server reference) and the offline stand-in (same interface)
- `tests/test_meko_mcp.py` — runs the relay against a fake MCP server that rejects undocumented arguments
- `relaypack/llm.py` — Claude backend, offline simulator, prices
- `relaypack/pipeline.py` — the relay and the two context modes
- `relaypack/bench.py` — the benchmark and the tables
