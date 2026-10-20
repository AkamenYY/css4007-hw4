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

Files: `tools.py` (the two tools), `strategies.py` (S1, S2, S3, the loop, the scoring rule), `run.py` (runs everything, saves to `outputs/`), `tests/test_tools.py`, `inspect_logs.py` (prints the log parts used in Part C to `outputs/inspect.txt`).

### What I changed from Part A while coding

1. **`reasoning_effort="none"` for all three strategies.** The API refused tools otherwise (`400 - Function tools with reasoning_effort are not supported ... set reasoning_effort to 'none'`). I set it for S1 and S2 too, so the comparison stays fair.
2. **More rounds than planned.** I expected 3 rounds for Q-09; the model used 4 (see B3).
3. Questions run 5 at a time in parallel to save time. Each question is still timed on its own.

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

- **Round limit:** 12. The hardest question needs about 6 lookups + a few calculations, so 12 is enough but still stops an endless loop. Real use: median 3 rounds, max 5. No question hit the limit.
- **Checks:** `arguments` is a JSON *string*, so the loop parses it and checks the keys and types before running anything. Bad input → an `{"error": ...}` goes back to the model. Every `tool_call_id` gets an answer.
- **Logs:** `outputs/run1/S3_logs/Q-XX.json` and `outputs/run2/S3_logs/` (every call, its inputs, result, time, tokens per round).
- **Real Q-09 vs my A3 plan:**

| | My plan (A3) | Real run 1 |
|---|---|---|
| Round 1 | 4 lookups | same 4 lookups (area came back corrected: 921.4, "corrected by NR-16") |
| Round 2 | 1 calculation | 2 calculations (each density separately) |
| Round 3 | answer | the difference: 0.5557 |
| Round 4 | — | answer: `Millbrook \| 0.5557` |

Same facts, same answer (0.6 ✓). The model just split the maths into smaller steps, so it needed 1 extra round. Prompt size grew every round: 526 → 823 → 940 → 1,013 tokens.

### B4 — Three strategies

**What I kept the same:** model `gpt-5.6-luna`, `temperature = 1.0`, `reasoning_effort = "none"`, the same 20 questions, the same answer line (`ANSWER: <name or yes/no> | <number>`), the same scoring code. S1 and S2 get the same documents; S3 gets only the tools. S2 uses k = 5. Cost uses $0.20 / 1M input and $1.20 / 1M output tokens; tokens are counted from every call.

**My rule for a correct answer** (in `is_correct()`, committed before run 1): the name must match exactly (case ignored), and the number, rounded to the key's decimals, may differ by at most 1 in the last digit. No ANSWER line = unanswered.
*Why:* both parts of the answer matter, and ±1 in the last digit forgives rounding but not real mistakes. I ran everything twice to see how much results move by chance.

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

I changed the `lookup` description to `"Looks things up."` (`outputs/c1_vague/`).

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| Q-01 | 5 | 7 | Ossbridge 4.570 ✓ | Ossbridge 4.570 ✓ |
| Q-03 | 7 | 5 | Lindenmoor 5.340 ✓ | Lindenmoor 5.340 ✓ |
| Q-08 | 6 | 7 | Brightwater 72.456 ✓ | Brightwater 72.456 ✓ |
| Q-09 | 7 | 7 | Millbrook 0.5557 ✓ | Millbrook 0.5557 ✓ |
| Q-18 | 3 | 3 | Millbrook 40013.39 ✗ | yes 40013.39 ✓ |

**Result:** almost nothing changed.
**Why:** the model learns most from the **schema**: the field names (`population_2025`, `area_km2` …) explain themselves, and every result shows its unit and source. The only real difference: in Q-08 the vague model did not know the water price is the same everywhere, so it asked for it twice. The Q-18 change is only the answer wording, not the tool use.

### C2 — Three mistakes explained

**S1, Q-09 (run 1): `Brightwater | 12.01`, correct is Millbrook | 0.6.**
S1 must answer in one line with no reasoning (only 12 output tokens). It has nowhere to do 44,675 ÷ 921.4, so it guesses. It often picked the right district but almost never the right number.

**S2, Q-14 (run 1): votes `[4.6, 4.7, 0.0, 5.0, 0.0]` → 0.0, correct is 4.9.**
Three answers were close to the truth but all a bit different, so the two wrong 0.0 answers won the vote.
- Voting fixes **random** mistakes (Q-05: one sample said 13, the vote ignored it).
- Voting does **not** fix mistakes that every sample makes (Q-20: all 5 votes were 2,998–3,005, correct is 2,993). The model's mental division is always slightly off, so the majority is also off.

**S3, Q-17 (run 1): `Ossbridge | 884.4572`, correct is Harrowfield | 884.**
All lookups were right, and the calculator gave the exact number: `Harrowfield − Ossbridge = +884.457`. But in the last step the model wrote the wrong name.
- A calculator removes **arithmetic** mistakes completely.
- It cannot fix **reading** or **planning** mistakes: Q-18 wrote `Millbrook` instead of `yes`; Q-08 (run 2) forgot to look up the water use.

**Why S3 needs several rounds, each more expensive:** the model must first get the numbers, then calculate, then answer, so at least 3 rounds. Each round sends the whole conversation again, so it grows: Q-17 538 → 894 → 987 tokens.

### C3 — Which strategy I would use, and what would change it

**I choose S3 (tools).**

| | S1 | S2 | S3 |
|---|---:|---:|---:|
| Correct (both runs) | 8/40 | 33/40 | **37/40** |
| Cost per run | $0.009 | $0.059 | **$0.016** |
| Seconds per question | 1.3 | 9 | 5 |

- **Not S2:** less accurate, about **4× more expensive** and slower (it sends all documents 5 times). Its errors are arithmetic, which voting cannot fix.
- **Not S1:** cheapest and fastest, but only 20% correct.

**When I would choose differently:**
- **Questions with no maths** (like Q-10) → **S1**: all strategies get them right, and S1 is cheapest and fastest.
- **1,000× more documents** → **S3** only: the documents no longer fit in a prompt.
- **Answer needed in 1–2 seconds** → **S1**: S3 needs several rounds one after another.
- **Tools not allowed** → **S2**, but with a median instead of a vote.

### C4 — How sure I can be

- **Two runs:** S1 5 vs 3, S2 16 vs 17, S3 18 vs 19. Each strategy changed on 2–3 questions, so chance alone moves results by about **1–2 questions**.
- **S3 vs S2:** the gap is 2 questions in both runs, the same size as the noise. Over 40 answers, S3 won 6 times and S2 won 2 times (sign test p ≈ 0.29). So **"S3 is more accurate" is not proven**. "S1 is worst" is clear. The cost and time differences are large and stable, and they are my main reason for S3.
- **How many questions I would need:** with 20 questions the margin is about ±13 points. To prove a 10-point difference I would need about **160 questions**.
- **What this cannot tell me:** results for one model only, with reasoning switched off (with reasoning on, S1 and S2 would likely do better), one prompt and one made-up dataset.

### Final questions

1. **What has run when the model sends `tool_calls`?** Nothing. The model only wrote a request. My code decides whether to run it.

2. **Why is `arguments` a string?** The model produces text, which only looks like JSON and can be broken. If I passed it straight in, the whole string would become the district name, or the code would crash. So I parse and check it first.

3. **How many tokens do the tool definitions add?** **376 tokens** per request (measured: 385 with tools, 9 without; `outputs/tool_tokens.txt`).

4. **How much more did S2 cost than S1?** **6.4×** ($0.0591 vs $0.0092). It sends the documents 5 times (5× input) and writes long reasoning (47× output).

5. **Which question needed the most rounds in S3?** Q-01 in run 2 (5 rounds); in run 1 several questions needed 4 (Q-03, Q-05, Q-08, Q-09, Q-11, Q-20). The extra rounds come from the model calculating each district separately before the difference, not from the question being hard.

6. **What would change with 100,000 documents?** Read all documents once into a table (district, field, value, source, archived, corrected) and make `lookup` a quick search in that table. For other facts, add a search tool that returns a few short pieces of text.

7. **What stops `calculate` from running dangerous code?** It never runs the text as code. `ast` breaks it into parts and allows only numbers and `+ - * / **`. Huge powers, huge results and very long inputs are refused. The model can still send a correct-looking but wrong formula (Q-08 run 2), and the calculator will compute it exactly.

8. **Where did tools help most, and where not at all?** Most: long divisions with big numbers (Q-05, Q-17, Q-20, where S2 was off by 6–116) and the correction trap (Q-09). Not at all: easy questions like Q-10 (all strategies right), and planning or wording mistakes (Q-08, Q-17, Q-18 in S3).
