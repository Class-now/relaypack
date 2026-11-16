# Relaypack trace — run `202611160113-meko-12-9` (12 tasks, Meko mode)

## Which lessons were learned, and where (SQL on the datapack's `relay_attempts` table)

```sql
SELECT lesson, COUNT(*) AS failures, MIN(task) AS first_seen
FROM relay_attempts WHERE run_id = '202611160113-meko-12-9' AND NOT passed AND lesson <> ''
GROUP BY lesson ORDER BY first_seen;
```

| lesson | failures | first_seen |
|---|---|---|
| Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence). | 1 | t01 |
| Normalize letter case (str.lower()) before comparing or counting text. | 1 | t02 |
| Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign. | 1 | t03 |

## Attempts per task

```sql
SELECT task, MAX(attempt) AS attempts, MAX(lessons_seen) AS lessons_in_prompt,
MAX(input_tokens + output_tokens) AS tokens
FROM relay_attempts WHERE run_id = '202611160113-meko-12-9' GROUP BY task ORDER BY task;
```

| task | attempts | lessons_in_prompt | tokens |
|---|---|---|---|
| t01 | 2 | 1 | 1317 |
| t02 | 2 | 2 | 1301 |
| t03 | 2 | 3 | 1631 |
| t04 | 1 | 3 | 875 |
| t05 | 1 | 3 | 750 |
| t06 | 1 | 3 | 880 |
| t07 | 1 | 3 | 869 |
| t08 | 1 | 3 | 734 |
| t09 | 1 | 3 | 718 |
| t10 | 1 | 3 | 669 |
| t11 | 1 | 3 | 961 |
| t12 | 1 | 3 | 848 |

## Decision trace (the `reasoning` stored with each Coder turn)

- `meko-t01` coder acted on: 4 guide passages; 2 earlier turns
- `meko-t01` coder acted on: 4 guide passages; 3 earlier turns; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).
- `meko-t02` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).
- `meko-t02` coder acted on: 4 guide passages; 3 earlier turns; lesson: Normalize letter case (str.lower()) before comparing or counting text.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).
- `meko-t03` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).; lesson: Normalize letter case (str.lower()) before comparing or counting text.
- `meko-t03` coder acted on: 4 guide passages; 3 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).; lesson: Normalize letter case (str.lower()) before comparing or counting text.
- `meko-t04` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).; lesson: Normalize letter case (str.lower()) before comparing or counting text.
- `meko-t05` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Normalize letter case (str.lower()) before comparing or counting text.
- `meko-t06` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Normalize letter case (str.lower()) before comparing or counting text.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).
- `meko-t07` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Normalize letter case (str.lower()) before comparing or counting text.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).
- `meko-t08` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Normalize letter case (str.lower()) before comparing or counting text.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).
- `meko-t09` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Normalize letter case (str.lower()) before comparing or counting text.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).
- `meko-t10` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Normalize letter case (str.lower()) before comparing or counting text.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).
- `meko-t11` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).; lesson: Normalize letter case (str.lower()) before comparing or counting text.
- `meko-t12` coder acted on: 4 guide passages; 2 earlier turns; lesson: Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.; lesson: Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).; lesson: Normalize letter case (str.lower()) before comparing or counting text.
