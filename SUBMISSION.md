# HW4 — submission

**AI assistance:** I used Claude (Anthropic) to plan and draft Part A, to write the code (`tools.py`, `strategies.py`, `run.py`, tests), and to help draft the written answers in Parts B and C from my own logs and outputs. I ran all the code myself; every number in this file comes from those runs and is saved in `outputs/`.

---

## Part A — Plan on paper (Easy)

> Commit this whole part before any `.py` file exists.

### A1 — The steps

Example question: *"Which district is denser, Brightwater or Millbrook, and by how much?"*

| # | Step | What goes in (types) | What comes out (types) | When it goes wrong | Tool, loop, or model? |
|---|---|---|---|---|---|
| 1 | **Read the question** | `question: str` | `districts: list[str]` (2 or 3 names), `metric: str` (e.g. "density"), `kind: str` ("compare two", "best of three", "yes/no threshold") | A name is misspelled → found out in step 3 (lookup suggests the right name). Metric unclear → the model has to choose; it cannot ask. | model |
| 2 | **Choose the raw facts needed** | `metric: str`, `districts: list[str]` | `needed: list[tuple[str, str]]` = (district, field), e.g. density → `population_2025`, `area_km2` for each district | The metric needs a field that does not exist → lookup returns the list of valid fields and the model chooses again. | model |
| 3 | **Fetch one fact** — `lookup(district, field)` | `district: str`, `field: str` (one of 10 fixed names) | `{"district": str, "field": str, "value": float, "unit": str, "source": str, "note": str (optional)}` | Nothing found → `{"error": "no district named X; did you mean A or B?"}`. Two similar names (Ossbridge/Ossford) → only an exact match is accepted, never a guess. Number missing → `{"error": "<field> is not given in the <district> profile (NR-xx)"}`. Unknown field → error with the valid list. | tool |
| 4 | **Clean the fact** (inside `lookup`, before step 3 returns) | the raw profile text, archived profiles, correction notices | the one valid number in a standard unit, plus a `note` saying what was done | Only an archived profile exists → error, the 2019 number is never returned. A correction exists → the corrected number is returned and the note names both documents (NR-05 + NR-16). Unit is cubic metres → converted to megalitres (÷ 1,000). Any other unit → error, not a guess. | tool (inside lookup) |
| 5 | **Calculate** — `calculate(expression)` | `expression: str`, e.g. `"37203 / 758.6 - 44675 / 921.4"` | `{"expression": str, "result": float}` (not rounded) | Division by zero → `{"error": "division by zero"}`. Not arithmetic (names, calls, attributes) → refused without running. Huge powers (`9**9**9`) → refused. Bad syntax → error asking for the form `44675 / 921.4`. | tool |
| 6 | **Decide** | per-district `float` values from step 5 | `winner: str` (district or `yes`/`no`), `difference: float` | Equal values → report either name with 0. If a step-3 error was never fixed, the model must not invent the number; the question stays unanswered. | model |
| 7 | **Round and write the answer** | `winner: str`, `difference: float` | one line `ANSWER: <name or yes/no> \| <number>` with ≥ 4 significant figures | No ANSWER line → counted as unanswered. Rounding too early (e.g. 0.03 instead of 0.0348) → wrong. | model |
| 8 | **Run the loop** | the model's message with `tool_calls` | one `tool` message per `tool_call_id`, sent back to the model; a log entry per call | `arguments` is not valid JSON or has wrong keys → an error result is sent back instead of running anything. Unknown tool → error result. Round limit reached → question marked unanswered. | loop |
| 9 | **Score** (outside the model) | the final reply `str`, the answer key | `correct: bool`, `unanswered: bool` | No ANSWER line → unanswered. | my code |

Steps 1–2 and 6–7 are the model's thinking; 3–5 are the only places a number can enter the answer; 8–9 never touch facts. No two steps produce the same thing, so the split is exclusive. Every number in the final answer must come from step 3 (a fact) or step 5 (arithmetic on facts), so together the steps cover the whole task.

**How the steps connect:**

```text
question ──► 1 read ──► 2 choose facts ──► (district, field) pairs
                                                  │
                         ┌────────────────────────┘
                         ▼
        8 loop ──► 3 lookup ──► 4 clean (archived / correction / unit) ──► value + source
                                                  │
                         ┌────────────────────────┘
                         ▼
        8 loop ──► 5 calculate (per district, then the difference) ──► float
                                                  │
                                                  ▼
                              6 decide ──► 7 ANSWER line ──► 9 score
```

The loop (8) sits between the model and the tools in steps 3 and 5: the model only *asks*, the loop runs the tool and sends the result back.

**What I am assuming:**

- Population means the **2025 census**; budgets are the **2025 fiscal year**; water is household use in **calendar 2025**; pupils and schools are **2025/26** (NR-00 says so).
- **Archived profiles (NR-13 Tarnvale, NR-14 Kelmarsh) are never used.** They are from 2019 and superseded.
- **Corrections win over profiles**: Brightwater's area is 921.4 km², not 912.4 (NR-16).
- **1 megalitre = 1,000 m³** (NR-15). Lindenmoor's water (2,151,400 m³) becomes 2,151.4 ML.
- Water tariff for 2025 is **142.35 tenge per m³** in every district; the 2024 price is not used.
- "Per resident per day" uses **365 days** (2025 is not a leap year); litres = ML × 1,000,000.
- "By how much" is reported as a **positive** difference.
- **Round only once, at the very end** (step 7). Intermediate results stay unrounded inside `calculate`.
- Growth projection (Q-18): the same *percentage* growth, i.e. multiply by 37,203 / 34,590 once more.

**The assumption the answers are most sensitive to:** that step 3/4 returns the number from the *right* document. If lookup picked the archived Tarnvale profile, the uncorrected Brightwater area, Ossford instead of Ossbridge, or Lindenmoor's water in m³, every later step would still run perfectly and give a confident wrong answer — `calculate` cannot notice a wrong input. That is why document choice is handled inside the tool by fixed rules, not left to the model.

### A2 — The two tools

#### `lookup`

One district + one field → one number with its source. I chose this over "search phrase → matching sentences" because sentences would put the traps (archived text, the typo, cubic metres) back in front of the model; a single checked number keeps them inside my code.

```json
{
  "type": "function",
  "function": {
    "name": "lookup",
    "description": "Get ONE number about ONE district of the Nine Rivers Region from the official documents. Call it once per district and field you need. It always uses the 2025 profile, ignores archived 2019 profiles, applies correction notices, and returns water in megalitres. The result says which document the number came from. For the regional water tariff use field 'water_tariff_2025' (district can be empty). If the district name is wrong you get an error with suggestions.",
    "parameters": {
      "type": "object",
      "properties": {
        "district": {
          "type": "string",
          "description": "District name, e.g. 'Ossbridge'. Exact spelling matters."
        },
        "field": {
          "type": "string",
          "enum": [
            "population_2025",
            "population_2020",
            "area_km2",
            "budget_2025",
            "water_2025",
            "schools",
            "pupils_2025_26",
            "road_km",
            "founded",
            "water_tariff_2025"
          ],
          "description": "Which number to return."
        }
      },
      "required": [
        "district",
        "field"
      ],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"district": "Ossbridge", "field": "population_2025", "value": 52904.0, "unit": "residents", "source": "NR-01"}` |
| success with correction | `{"district": "Brightwater", "field": "area_km2", "value": 921.4, "unit": "km2", "source": "NR-05 + NR-16", "note": "profile says 912.4, corrected by NR-16"}` |
| success with archived profile present | `{"district": "Tarnvale", "field": "water_2025", "value": 5207.0, ..., "source": "NR-03", "note": "archived profile NR-13 (2019) ignored"}` |
| success with unit conversion | `{"district": "Lindenmoor", "field": "water_2025", "value": 2151.4, "unit": "megalitres", "note": "profile gives 2,151,400 cubic metres; converted to megalitres"}` |
| misspelled / unknown district | `{"error": "no district named 'Ossbrige'; did you mean Ossbridge or Ossford? Districts: ..."}` |
| unknown field | `{"error": "unknown field 'rainfall'. Valid fields: population_2025, ..."}` |
| field not in that profile | `{"error": "founded is not given in the Ossbridge profile (NR-01)"}` |
| any unexpected failure | `{"error": "lookup failed: <ErrorType>"}` — never an exception |

**Worst thing it could do with strange or dangerous input:** it only reads one fixed file and compares the input with a fixed list of 12 names and 10 fields, so strange input can only produce an error message. The real risk is a **wrong but plausible number**: e.g. fuzzy matching "Ossbrige" to Ossford. So it never auto-corrects a name; it only suggests. Output is one number, so it cannot flood the context with whole documents.

#### `calculate`

```json
{
  "type": "function",
  "function": {
    "name": "calculate",
    "description": "Work out an arithmetic expression exactly, e.g. '44675 / 921.4 - 37203 / 758.6'. Only numbers, + - * / ** and brackets. Use it for every calculation instead of doing arithmetic yourself. Returns the unrounded result.",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {
          "type": "string",
          "description": "The arithmetic expression."
        }
      },
      "required": [
        "expression"
      ],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"expression": "44675 / 921.4", "result": 48.4859995659}` |
| division by zero | `{"error": "division by zero"}` |
| not arithmetic: `__import__('os').system('echo hi')`, `(1).__class__` | `{"error": "'Call' is not allowed; use numbers, + - * / ** and brackets only"}` (refused before anything runs) |
| huge power `9**9**9` | `{"error": "exponent larger than 100 is not allowed"}` (checked before computing) |
| result too big (> 10^15) | `{"error": "result is too large or not a real number"}` |
| cannot be read (`two plus two`) | `{"error": "could not read the expression; write it like 44675 / 921.4"}` |
| longer than 300 characters | `{"error": "expression longer than 300 characters"}` |

**Worst thing it could do with strange or dangerous input:** with `eval` it could run any Python the model wrote (delete files, read `.env`). It will use `ast.parse` and walk the tree, allowing only number constants, `+ - * / **` and unary minus. Nothing is ever executed as code. The remaining risk is **using a lot of CPU or memory** (`9**9**9`), which is why exponents and result size are limited.

### A3 — Q-09 by hand

Q-09: *"Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?"*

```json
[
  {"role": "system", "content": "You answer questions about the Nine Rivers Region. You do NOT have the documents. Get every number with the lookup tool and do every calculation with the calculate tool ... ANSWER: <district name or yes/no> | <number>"},
  {"role": "user", "content": "Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"population_2025\"}"}},
    {"id": "call_2", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"area_km2\"}"}},
    {"id": "call_3", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"population_2025\"}"}},
    {"id": "call_4", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"area_km2\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_1", "content": "{\"district\": \"Brightwater\", \"field\": \"population_2025\", \"value\": 44675.0, \"unit\": \"residents\", \"source\": \"NR-05\"}"},
  {"role": "tool", "tool_call_id": "call_2", "content": "{\"district\": \"Brightwater\", \"field\": \"area_km2\", \"value\": 921.4, \"unit\": \"km2\", \"source\": \"NR-05 + NR-16\", \"note\": \"profile says 912.4, corrected by NR-16\"}"},
  {"role": "tool", "tool_call_id": "call_3", "content": "{\"district\": \"Millbrook\", \"field\": \"population_2025\", \"value\": 37203.0, \"unit\": \"residents\", \"source\": \"NR-11\"}"},
  {"role": "tool", "tool_call_id": "call_4", "content": "{\"district\": \"Millbrook\", \"field\": \"area_km2\", \"value\": 758.6, \"unit\": \"km2\", \"source\": \"NR-11\"}"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_5", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"37203 / 758.6 - 44675 / 921.4\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_5", "content": "{\"expression\": \"37203 / 758.6 - 44675 / 921.4\", \"result\": 0.5556561156}"},

  {"role": "assistant", "content": "Millbrook: 37,203 / 758.6 = 49.04 per km2. Brightwater: 44,675 / 921.4 = 48.49 per km2 (corrected area, NR-16). Millbrook is denser by 0.56.\nANSWER: Millbrook | 0.5557"}
]
```

That is 3 model calls (rounds): 4 lookups in parallel, 1 calculation, then the answer.

**My arithmetic:**

- Brightwater: 44,675 ÷ **921.4** (corrected by NR-16) = 48.4860 residents/km²
- Millbrook: 37,203 ÷ 758.6 = 49.0417 residents/km²
- Difference: 49.0417 − 48.4860 = **0.5557 → 0.6** (1 decimal). **Millbrook** is denser. ✓ matches the key (Millbrook, 0.6).
- With the typo area 912.4: 44,675 ÷ 912.4 = 48.9643, difference 0.0774 → **0.1**. The name is still right, but the number is wrong. This is exactly the trap: the correction notice changes the answer.

### A4 — Why I split it this way

**Rejected alternative: one search-style lookup** (`lookup(query: str)` → the matching sentences), and the model reads the numbers itself.

I did not choose it because:

1. The four traps (similar names, archived profiles, the corrected typo, cubic metres) are all about **which number is the right one**. With sentence search, both the archived and the 2025 Tarnvale sentences, or both "912.4" and the correction, would come back, and the model would have to resolve them every time — the same weakness S1 has. With my split, these rules are written once, in code, and tested (B2).
2. Returning sentences costs many more tokens per call, and each extra round repeats them.
3. My version gives one number with a `source`, so every number in the log can be checked against a document.

Its advantage would be flexibility: it works for questions about any fact, not only my 10 fields. That is the cost of my choice: a question about something outside the 10 fields cannot be answered. For these 20 questions all needed facts are in the 10 fields, so I accept that.

I also rejected **one tool per calculation** (`density(a, b)`, `growth(a, b)` …): it would need many tools, each a new place for bugs, while one safe `calculate` covers all of them.

---

## Part B — Build it and run it (Medium)

Code: `tools.py` (the two tools and their definitions), `strategies.py` (S1, S2, S3, the loop, the scoring rule), `run.py` (runs everything, writes `outputs/`), `tests/test_tools.py`, `inspect_logs.py` (prints the log extracts quoted in Part C into `outputs/inspect.txt`).

### What I changed from Part A while coding

1. **`reasoning_effort="none"` for every call.** My first S3 test failed with `400 - Function tools with reasoning_effort are not supported for gpt-5.6-luna in /v1/chat/completions ... set reasoning_effort to 'none'` (`outputs/test/` before the fix). To keep the comparison like for like I set it for **all three** strategies, not only S3. Side effect: S1 now gets no hidden reasoning at all (see C2/C4).
2. **The loop needed more rounds than I planned.** In A3 I expected 3 rounds for Q-09; the model took 4 because it split the arithmetic into several `calculate` calls (see B3).
3. Questions are run 5 at a time in parallel threads to save wall-clock time. Each question's seconds are still measured on its own.

Nothing else changed: the tool definitions, fields, error messages and the Q-09 plan are the ones in Part A.

### B2 — Tests

`python -m pytest tests -v` (also saved in `outputs/pytest.txt`). No API key needed.

```text
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
collected 15 items

tests/test_tools.py::test_lookup_finds_2025_population PASSED            [  6%]
tests/test_tools.py::test_lookup_misspelled_name_suggests PASSED         [ 13%]
tests/test_tools.py::test_lookup_similar_names_are_kept_apart PASSED     [ 20%]
tests/test_tools.py::test_lookup_ignores_archived_profile PASSED         [ 26%]
tests/test_tools.py::test_lookup_applies_correction PASSED               [ 33%]
tests/test_tools.py::test_lookup_converts_cubic_metres PASSED            [ 40%]
tests/test_tools.py::test_lookup_unknown_field PASSED                    [ 46%]
tests/test_tools.py::test_lookup_tariff PASSED                           [ 53%]
tests/test_tools.py::test_calculate_multiplication PASSED                [ 60%]
tests/test_tools.py::test_calculate_density PASSED                       [ 66%]
tests/test_tools.py::test_calculate_refuses_import PASSED                [ 73%]
tests/test_tools.py::test_calculate_refuses_attribute PASSED             [ 80%]
tests/test_tools.py::test_calculate_refuses_huge_power_quickly PASSED    [ 86%]
tests/test_tools.py::test_calculate_division_by_zero PASSED              [ 93%]
tests/test_tools.py::test_calculate_garbage PASSED                       [100%]

============================== 15 passed in 0.03s ==============================
```

### B3 — The loop

- **Round limit, and why:** `MAX_ROUNDS = 12`. The hardest questions need 6 lookups (3 districts × 2 fields) and a few calculations; even done one call per round that is about 10 rounds, so 12 never cuts off a reasonable plan but stops a model that loops on errors. In practice S3 used a median of 3 rounds and at most 5 (Q-01 in run 2); no question hit the limit (0 unanswered in both runs).
- **What the loop checks:** `arguments` arrives as a JSON string; `run_tool()` parses it, rejects non-objects, unknown keys and non-string values, and returns `{"error": ...}` instead of running anything. The assistant message is appended unchanged (`msg.model_dump(exclude_none=True)`), then one `tool` message is sent back for **every** `tool_call_id`.
- **Where the logs are:** `outputs/run1/S3_logs/Q-XX.json` and `outputs/run2/S3_logs/Q-XX.json`: every round's `prompt_tokens`/`completion_tokens`, every tool call with its id, arguments string, result and seconds, and the final reply. S1/S2 replies are in `outputs/runN/S1.json` and `S2.json` (all 5 samples and the votes).
- **Real Q-09 conversation compared with my A3 version** (`outputs/run1/S3_logs/Q-09.json`):

| | My A3 plan | Real run 1 |
|---|---|---|
| Round 1 | 4 lookups in parallel | the same 4 lookups in parallel; Brightwater area came back as 921.4 with the note "profile says 912.4, corrected by NR-16" |
| Round 2 | one `calculate("37203 / 758.6 - 44675 / 921.4")` | **two** calls: `44675 / 921.4` → 48.486, `37203 / 758.6` → 49.0417 |
| Round 3 | final answer | `calculate("37203 / 758.6 - 44675 / 921.4")` → 0.5557 |
| Round 4 | — | `ANSWER: Millbrook \| 0.5557` |
| Total | 3 rounds, 5 calls | **4 rounds, 7 calls**, 3,302 input tokens |

Same facts, same sources, same answer (0.5557 → 0.6 ✓). The difference is that the model computes each district's density first and only then the difference, so it pays one extra round. Prompt tokens grew every round: 526 → 823 → 940 → 1,013.

### B4 — Three strategies

**What I kept the same:**

- model `gpt-5.6-luna`, Chat Completions API, `temperature = 1.0` (accepted by the model, logged in each `summary.md`), `reasoning_effort = "none"`, no max-token limit;
- the same 20 question strings, sent unchanged as the user message;
- the same answer-format block in every system prompt (`ANSWER: <name or yes/no> | <number>`, at least 4 significant figures), the same parser and the same scoring rule;
- S1 and S2 get the identical documents block (all 17 documents); S3 gets no documents, only the two tools;
- S2: k = 5 separate calls per question, plurality vote over `(name, number rounded to the question's decimals)`;
- S3: `MAX_ROUNDS = 12`; same tool definitions in both runs;
- prices for the cost column: $0.20 per 1M input and $1.20 per 1M output tokens (`run.py`, published gpt-5.6-luna price). Tokens are summed from `usage` of **every** call (all 5 S2 samples, every S3 round).

**My rule for a correct answer** (written before the first full run; it is `is_correct()` in `strategies.py`, committed in the code commit *before* `outputs/run1` existed): the name (or yes/no) must match the key exactly, ignoring case; and the number, taken as an absolute value and rounded to the question's `decimals`, must be within one unit of the last digit of `value`. No ANSWER line = unanswered.

*Why this rule:* the question asks for a name and a size, so both must be right; rounding at the key's precision with ±1 in the last digit forgives rounding differences but not real arithmetic errors (e.g. 14,346 vs 14,235 fails). *Why 20 questions:* that is the fixed set; I ran it twice to see how much the counts move by chance (C4).

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | 5 | 0 | 44,400 | 256 | 1.3 | 30.6 | 0.0092 |
| 1 | S2 think and vote (k = 5) | 16 | 0 | 223,700 | 12,002 | 9.2 | 191.5 | 0.0591 |
| 1 | S3 tools | 18 | 0 | 52,800 | 4,229 | 5.2 | 108.8 | 0.0156 |
| 2 | S1 direct | 3 | 0 | 44,400 | 260 | 1.4 | 33.2 | 0.0092 |
| 2 | S2 think and vote (k = 5) | 17 | 0 | 223,700 | 11,859 | 8.7 | 182.0 | 0.0590 |
| 2 | S3 tools | 19 | 0 | 54,198 | 4,086 | 4.9 | 107.1 | 0.0157 |

Total seconds = sum of the per-question times. **Full-run cost:** $0.0839 per run of all three strategies, $0.168 for both runs, about $0.18 with the C1 run and the test runs (at the prices above).

**Per question (run 1):** (run 2 is in `outputs/run2/summary.md`)

| Question | S1 | S2 | S3 |
|---|:---:|:---:|:---:|
| Q-01 | ✗ | ✓ | ✓ |
| Q-02 | ✗ | ✓ | ✓ |
| Q-03 | ✗ | ✓ | ✓ |
| Q-04 | ✗ | ✓ | ✓ |
| Q-05 | ✗ | ✗ | ✓ |
| Q-06 | ✓ | ✓ | ✓ |
| Q-07 | ✗ | ✓ | ✓ |
| Q-08 | ✗ | ✓ | ✓ |
| Q-09 | ✗ | ✓ | ✓ |
| Q-10 | ✓ | ✓ | ✓ |
| Q-11 | ✗ | ✓ | ✓ |
| Q-12 | ✗ | ✓ | ✓ |
| Q-13 | ✓ | ✓ | ✓ |
| Q-14 | ✗ | ✗ | ✓ |
| Q-15 | ✗ | ✓ | ✓ |
| Q-16 | ✓ | ✓ | ✓ |
| Q-17 | ✗ | ✗ | ✗ |
| Q-18 | ✓ | ✓ | ✗ |
| Q-19 | ✗ | ✓ | ✓ |
| Q-20 | ✗ | ✗ | ✓ |

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

I replaced the `lookup` description with `"Looks things up."` and kept everything else, including the parameter schema (`outputs/c1_vague/`). Compared with S3 run 1 on the same five questions:

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| Q-01 | 5 | 7 | Ossbridge 4.570 ✓ | Ossbridge 4.570 ✓ |
| Q-03 | 7 | 5 | Lindenmoor 5.340 ✓ | Lindenmoor 5.340 ✓ |
| Q-08 | 6 | 7 | Brightwater 72.456 ✓ | Brightwater 72.456 ✓ |
| Q-09 | 7 | 7 | Millbrook 0.5557 ✓ | Millbrook 0.5557 ✓ |
| Q-18 | 3 | 3 | Millbrook 40013.39 ✗ | yes 40013.39 ✓ |

**What changed:** almost nothing in the answers, a little in the calls. The clearest effect is in Q-08: with the vague description the model did not know the tariff is regional, so it called `lookup` for `water_tariff_2025` **twice**, once with `"Brightwater"` and once with `"Millbrook"`. My description says "for the regional water tariff use field 'water_tariff_2025' (district can be empty)", and with it the model called it once with an empty district. Call counts went both up and down (5→7, 7→5), so they mostly reflect how the model chooses to split arithmetic, not the description. Q-18 changed from ✗ to ✓ only in the answer *format* (name vs `yes`); that is run-to-run noise in the final line, since the tool calls and the number were identical.

**Why so little changed:** most of what the model needs is in the **schema**, not in the description: the `field` parameter is an enum with self-explaining names (`population_2025`, `area_km2`, `water_2025` …), and the tool result itself returns the unit, the source and notes such as "corrected by NR-16". The description only adds information the schema cannot express (that the tariff is regional, that archived profiles are already handled), and that is exactly where the vague run behaved worse. With a search-style lookup (`query: str`) and no enum, I would expect the description to matter much more. 5 questions are too few to say more.

### C2 — Three mistakes explained

**S1 — Q-09 (run 1): `ANSWER: Brightwater | 12.01`, expected Millbrook | 0.6.**
S1 must answer with the final line only, and with `reasoning_effort="none"` the model has no hidden reasoning tokens either: its whole output was 12 tokens. So it must do a two-division comparison and the correction notice "in one step", which it cannot do. It picked the wrong district and an invented difference. The same thing happened across S1 (5/20 and 3/20): the names were often right (Q-01, Q-03, Q-07, Q-08 all chose the right district), but the numbers were guesses, e.g. Q-17 `Harrowfield | 4.247` instead of 884 (a value off by a factor of ~200, i.e. the unit conversion was never done). A language model produces the next token; without written intermediate steps there is nowhere to hold 44,675 / 921.4. The earlier test run (before I set `reasoning_effort="none"`) got Q-09 right with S1 while using 217 output tokens instead of 12, which supports this: the error comes from having no room to compute, not from missing facts.

**S2 — Q-14 (run 1): votes `[4.6, 4.7, 0.0, 5.0, 0.0]` → winner 0.0, expected Ashgrove | 4.9.**
Sample 1 worked correctly in principle: "Tarnvale: 5,207 × 1,000,000 ÷ 71,388 ÷ 365 = 199.92; Ashgrove: … = 204.54; difference 4.623". But the true values are 199.83 and 204.69 (difference 4.85). The model's mental division is off in the second decimal, so each sample lands on a slightly different number. Voting over *exact* rounded numbers then breaks: three samples were close to the truth but all different (4.6, 4.7, 5.0), and the two broken samples both rounded to 0.0, so the plurality was **0.0 with only 2/5 votes**.

This shows both sides of self-consistency. Voting reduces **variance**: it removes a single wild sample, as in Q-05 run 1, where one sample said 13 and the vote was 14,346. It cannot remove **bias**: in Q-20 run 1 all five votes were 2,998–3,005 and none was 2,993, because every sample makes the same kind of rounding drift in long divisions (Q-05: "2,884.6 million ÷ 14,926 = 193,168.2", true value 193,260.1). If every sample is wrong in the same direction, the majority is wrong too. And when the answer is a continuous number, k = 5 samples rarely agree exactly, so the vote is decided by ties.

**S3 — Q-17 (run 1): `ANSWER: Ossbridge | 884.4572`, expected Harrowfield | 884.**
The log is perfect up to the last step: 5 correct lookups in round 1 (tariff 142.35, Harrowfield 7,146 ML and 90,212 residents, Ossbridge 3,862 ML and 52,904), then `calculate("(7146*1000*142.35/90212)-(3862*1000*142.35/52904)")` → 884.457. The expression is Harrowfield **minus** Ossbridge and the result is positive, so Harrowfield paid more. In round 3 the model still wrote "Ossbridge households paid more". The calculator removed the arithmetic error completely (884.457 is exact), but **reading** the sign of a result and naming the winner is still done by the model, and it slipped. The other two S3 errors are the same kind: in Q-18 (run 1) the number 40,013.39 was exact but the model wrote `Millbrook` instead of `yes`; in Q-08 (run 2) the model **planned** wrongly and never looked up `water_2025`; it computed (population difference) × tariff, "assuming equal household water consumption per resident". Tools fix arithmetic and fact retrieval; they do not fix planning or the final reading of the result.

**Rounds and tokens in S3:** each round re-sends the whole conversation (system prompt, tool definitions, every previous tool call and result), so prompt size grows every round: Q-17 538 → 894 → 987, Q-09 526 → 823 → 940 → 1,013. Total input is therefore roughly rounds × an average prompt that keeps growing. The model needs at least 3 rounds (facts, then arithmetic that depends on the facts, then the answer) because a call that needs a result cannot be made in the same round as the call that produces it.

### C3 — Which strategy I would use, and what would change it

**I would use S3 (tools).**

| | S1 | S2 (k = 5) | S3 |
|---|---:|---:|---:|
| Correct, run 1 + run 2 | 8/40 (20%) | 33/40 (82.5%) | **37/40 (92.5%)** |
| Input tokens per run | 44,400 | 223,700 | 52,800–54,198 |
| Cost per run | $0.0092 | $0.0591 | $0.0156 |
| Median seconds per question | 1.3–1.4 | 8.7–9.2 | 4.9–5.2 |

- **Against S2:** S3 was more accurate in both runs (18 vs 16, 19 vs 17) at **about a quarter of the cost** and a little over half the latency. S2 pays 5× the input because it sends all documents five times, and its remaining errors (Q-05, Q-17, Q-20) are arithmetic bias that more samples will not remove. S3's calculator removes exactly that class of error. S3 errors were planning and naming slips, which S2 does not avoid either (they would need checks on the final line).
- **Against S1:** S1 is the cheapest and fastest, but 20% accuracy makes it useless here: almost every question needs two or more divisions, which S1 has no room to do.

**What would change my choice:**

- **Questions with no arithmetic** (e.g. "When was Stonecairn founded?", or Q-10-style simple lookups): S1 is good enough. All strategies got Q-10, Q-13 and Q-16 in both runs, and S1 is 4× faster and cheaper than S3.
- **1,000× more documents:** S1 and S2 become impossible, because ~2.3 million tokens do not fit in a prompt and would cost far too much ×5. S3 still works because only the tool results enter the prompt. I would keep S3 and change `lookup` (final question 6).
- **A strict latency limit (≈ 1–2 s):** S1 is the only one that fits; S3's 3+ sequential round trips cannot. I would use S1 with reasoning switched on, or precompute the answers.
- **A very small budget:** S3 is already cheapest among the accurate ones. If tools were not possible (an API that does not support function calling with reasoning, as here), S2 with k = 3 and a *median* instead of a plurality vote would be my second choice.

### C4 — How sure I can be

- **How different were the two runs?** S1 5 vs 3, S2 16 vs 17, S3 18 vs 19. Per question, S3 changed result on 3 questions (Q-08, Q-17, Q-18) and S2 on 3 (Q-12, Q-14, Q-20); S1 changed on 2 (Q-06 and Q-18). So about **±1–2 correct answers per strategy** come from sampling alone.
- **Is the S3–S2 gap bigger?** The gap was 2 questions in each run, about the same size as the run-to-run noise. Over the 40 paired answers, S3 was right where S2 was wrong 6 times (Q-05, Q-14, Q-20 in run 1; Q-05, Q-12, Q-17 in run 2), and the reverse happened 2 times (Q-18 run 1, Q-08 run 2). A sign test on 6 vs 2 gives p ≈ 0.29, so **S3 > S2 is not proven by accuracy alone**. S1 being far worse (8/40) is certain. The cost and latency differences are large and stable across both runs (5× tokens, ~2× time), and they are not noisy, so they decide my choice more than accuracy does.
- **How many questions would I need?** With accuracy near 90%, the 95% interval on 20 questions is about ±13 points (√(0.9·0.1/20) ≈ 0.067). To detect a 10-point paired difference with ~20% of questions disagreeing between the two strategies, McNemar's test needs about (1.96 + 0.84)² × 0.20 / 0.10² ≈ **160 questions**. With 20 I can trust "S1 is much worse" but not the order of S2 and S3.
- **What this comparison cannot settle:** it is one model, `reasoning_effort="none"` for all strategies (forced by the API for tools; with reasoning on, S1/S2 would probably do much better, as the S1 test run suggested), one temperature, one prompt wording and one fictional corpus with no ambiguity in the facts.

### Final questions

1. **When the model sends a `tool_calls` message, what has actually run so far?** Nothing. The model has only produced text in a structured format: a tool name and an `arguments` string. My loop decides whether to run it. In Q-09 round 1 the model "asked" for 4 lookups; they ran on my laptop only when `run_tool()` called `lookup()` (each call's run time is logged as `seconds`).

2. **Why does `arguments` arrive as a string, and what goes wrong if you pass it straight in?** The model generates tokens, so its output is text that only *looks like* JSON. It can be invalid, contain extra keys, or wrong types. Passing the string to `lookup(arguments)` would put the whole JSON text into `district`, and `**json.loads(...)` without checks could crash on bad JSON or unexpected keys. My loop parses it, checks it is an object with only the allowed string keys, and otherwise sends an `{"error": ...}` back to the model.

3. **How many tokens do the two tool definitions add to every S3 request?** **376 tokens**, measured with the API (`python run.py --measure-tools` → `outputs/tool_tokens.txt`: "prompt_tokens with tools = 385, without = 9"). With ~3–4 rounds per question that is ~1,100–1,500 tokens per question, about a quarter of S3's input.

4. **How much more did S2 cost than S1?** $0.0591 vs $0.0092 in run 1: **6.4× more** (+$0.0499). Input was 5.04× (223,700 vs 44,400) because each of the 5 samples re-sends the full ~2,200-token documents prompt; output was 47× (12,002 vs 256) because S2 writes its reasoning and S1 writes one line. Latency per question was ~7× higher because the 5 samples ran one after another.

5. **Which question needed the most rounds in S3, and why?** In run 1 the maximum was 4 rounds (Q-03, Q-05, Q-08, Q-09, Q-11, Q-20); in run 2 it was 5 rounds for Q-01. The 4-round pattern in the logs is always the same (Q-03, Q-09): round 1 all lookups in parallel, round 2 one calculation per district, round 3 the difference, round 4 the answer. The extra round comes from the model's habit of computing intermediate values before the final expression, not from the question being hard. Q-11 and Q-20 also needed the most *calls* (10) because they have three districts.

6. **What would I change in `lookup` with 100,000 documents?** Today it regex-parses the text on every call. I would parse every profile **once** into a table (SQLite: district, field, value, unit, source, valid_from, archived, corrected_by) and make `lookup` a keyed query, with the archived/correction rules applied when the table is built. For facts outside fixed fields I would add a second, search-style tool (BM25 or embeddings, as in HW3) that returns at most a few short snippets with their document ids.

7. **What stops `calculate` from running dangerous code? Could the model still make it misbehave?** It never executes the text: `ast.parse` turns it into a tree and my `_eval` walks it, accepting only number constants, `+ - * / **` and unary minus. Names, calls, attributes and subscripts raise an error before anything runs (the `__import__('os')…` and `(1).__class__` tests). Resource abuse is bounded: exponents above 100, results above 10^15 and expressions over 300 characters are refused, so `9**9**9` returns an error in under a second. The model *can* still make it give a wrong answer by sending a valid but wrong expression, as in Q-08 run 2 (`(44675-37203)*142.35/1000000`): the calculator is exact, but only about what it is given.

8. **For which kind of question did tools help most, and for which not at all?** Most: questions with long divisions on large numbers, where the model's own arithmetic drifts. Q-05 (budget per resident) and Q-17 (water cost per resident) were wrong in S2 in both runs, and Q-20 in run 1, off by 6–116 units; S3 got Q-05 and Q-20 right in both runs and Q-17 in run 2. Also traps that are rules: Q-09 (correction notice) was wrong in S1 in both runs and right in S3 in both. Not at all: simple questions like Q-10 (8-year difference between founding years), Q-13 and Q-16 were right in every strategy. And tools did not help with planning or wording mistakes (Q-08 run 2, Q-17 and Q-18 run 1).
