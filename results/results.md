# Relaypack results (live: Claude API + Meko MCP, 10 runs per cell)

Cells with fewer runs: meko x 12 tasks = 3 runs (the Meko free tier caps `conversation_add_message` at 1,000 lifetime calls).

| tasks | mode | total tokens | tokens/task | latency (s) | cost (USD) | pass rate | retries |
|---|---|---|---|---|---|---|---|
| 4 | baseline | 29,468 | 7,367 | 31.2 | 0.1521 | 100% | 0.0 |
| 4 | meko | 6,235 | 1,559 | 28.3 | 0.0586 | 100% | 0.0 |
| 8 | baseline | 59,021 | 7,378 | 61.3 | 0.3053 | 100% | 0.0 |
| 8 | meko | 13,380 | 1,672 | 59.2 | 0.1218 | 100% | 0.2 |
| 12 | baseline | 88,744 | 7,395 | 94.4 | 0.4614 | 100% | 0.0 |
| 12 | meko | 25,737 | 2,145 | 89.0 | 0.2119 | 100% | 0.0 |

| tasks | token reduction | retry reduction |
|---|---|---|
| 4 | 79% | 0.0 → 0.0 |
| 8 | 77% | 0.0 → 0.2 |
| 12 | 71% | 0.0 → 0.0 |
