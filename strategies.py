"""The three strategies. Everything is identical except the strategy itself:
same model, same temperature, same question text, same answer-format line."""
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from openai import BadRequestError, OpenAI

from tools import TOOL_FUNCTIONS, TOOLS

load_dotenv()
MODEL = "gpt-5.6-luna"
TEMPERATURE = 1.0       # same for every strategy; S2 needs it > 0 so samples vary
K = 5                   # S2 samples per question
MAX_ROUNDS = 12         # S3 loop limit
_temperature_ok = True  # set to False if the model rejects the parameter

# The Accept-Encoding header avoids a brotli decoding bug we hit in HW3.
client = OpenAI(default_headers={"Accept-Encoding": "gzip, deflate"})

DOCS = [json.loads(l) for l in (Path(__file__).parent / "data" / "corpus.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
DOCS_TEXT = "\n\n".join(f"[{d['id']}] {d['title']}\n{d['text']}" for d in DOCS)

ANSWER_FORMAT = (
    "End your reply with exactly one final line in this format:\n"
    "ANSWER: <district name or yes/no> | <number>\n"
    "The number has no units and no thousands separators. Do not round it to fewer than "
    "4 significant figures (for example 0.03484, 4.570, 14235.31); whole counts and years stay whole."
)

S1_SYSTEM = ("You answer questions about the Nine Rivers Region using only the documents below.\n"
             "Reply with the final line only, no explanation.\n" + ANSWER_FORMAT +
             "\n\nDOCUMENTS:\n" + DOCS_TEXT)
S2_SYSTEM = ("You answer questions about the Nine Rivers Region using only the documents below.\n"
             "Think step by step: find every number you need, say which document it comes from, "
             "and show each calculation before the final line.\n" + ANSWER_FORMAT +
             "\n\nDOCUMENTS:\n" + DOCS_TEXT)
S3_SYSTEM = ("You answer questions about the Nine Rivers Region. You do NOT have the documents. "
             "Get every number with the lookup tool and do every calculation with the calculate "
             "tool; do not do arithmetic in your head.\n" + ANSWER_FORMAT)


def chat(**kwargs):
    """One API call. Uses TEMPERATURE unless the model has rejected it once."""
    global _temperature_ok
    if _temperature_ok:
        try:
            return client.chat.completions.create(model=MODEL, reasoning_effort="none", temperature=TEMPERATURE, **kwargs)
        except BadRequestError as e:
            if "temperature" not in str(e).lower():
                raise
            _temperature_ok = False
            print("NOTE: model rejected 'temperature'; using the default from now on")
    return client.chat.completions.create(model=MODEL, reasoning_effort="none", **kwargs)


def parse_answer(text):
    """Return (name, number) from the last ANSWER line, or None."""
    hits = re.findall(r"ANSWER:\s*\**\s*([A-Za-z][A-Za-z ]*?)\s*\|\s*\**\s*(-?[\d,]*\.?\d+)", text or "")
    if not hits:
        return None
    name, num = hits[-1]
    return name.strip(), float(num.replace(",", ""))


def is_correct(parsed, q):
    """Rule fixed before the first full run: name matches exactly (ignoring case),
    and |number| rounded to q['decimals'] is within one unit of the last digit of q['value']."""
    if parsed is None:
        return False
    name, num = parsed
    step = 10 ** -q["decimals"]
    return (name.lower() == q["answer"].lower()
            and abs(round(abs(num), q["decimals"]) - q["value"]) <= step + 1e-9)


def _usage(r):
    return r.usage.prompt_tokens, r.usage.completion_tokens


# ------------------------------------------------------------- strategies

def s1_direct(q):
    r = chat(messages=[{"role": "system", "content": S1_SYSTEM},
                       {"role": "user", "content": q["question"]}])
    text = r.choices[0].message.content
    tin, tout = _usage(r)
    return {"texts": [text], "parsed": parse_answer(text), "in": tin, "out": tout, "calls": 1}


def s2_vote(q):
    texts, votes, tin, tout = [], [], 0, 0
    for _ in range(K):
        r = chat(messages=[{"role": "system", "content": S2_SYSTEM},
                           {"role": "user", "content": q["question"]}])
        text = r.choices[0].message.content
        texts.append(text)
        a, b = _usage(r)
        tin, tout = tin + a, tout + b
        p = parse_answer(text)
        if p:
            votes.append((p[0].lower(), round(abs(p[1]), q["decimals"])))
    parsed = None
    if votes:
        (name, num), _ = Counter(votes).most_common(1)[0]
        parsed = (name, num)
    return {"texts": texts, "votes": [list(v) for v in votes], "parsed": parsed,
            "in": tin, "out": tout, "calls": K}


def run_tool(name, raw_args):
    """Check the model's request before running anything."""
    if name not in TOOL_FUNCTIONS:
        return {"error": f"unknown tool '{name}'"}
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {"error": "arguments were not valid JSON"}
    if not isinstance(args, dict):
        return {"error": "arguments must be a JSON object"}
    allowed = TOOLS[0 if name == "lookup" else 1]["function"]["parameters"]["properties"]
    extra = set(args) - set(allowed)
    if extra or not all(isinstance(v, str) for v in args.values()):
        return {"error": f"allowed arguments: {', '.join(allowed)} (all strings)"}
    return TOOL_FUNCTIONS[name](**args)


def s3_tools(q, tools=TOOLS):
    messages = [{"role": "system", "content": S3_SYSTEM},
                {"role": "user", "content": q["question"]}]
    log, tin, tout, text = [], 0, 0, None
    for rnd in range(1, MAX_ROUNDS + 1):
        r = chat(messages=messages, tools=tools)
        a, b = _usage(r)
        tin, tout = tin + a, tout + b
        msg = r.choices[0].message
        if not msg.tool_calls:
            text = msg.content
            log.append({"round": rnd, "prompt_tokens": a, "completion_tokens": b, "final": text})
            break
        messages.append(msg.model_dump(exclude_none=True))  # unchanged, with its tool_calls
        calls = []
        for tc in msg.tool_calls:                            # answer EVERY tool_call_id
            t0 = time.perf_counter()
            result = run_tool(tc.function.name, tc.function.arguments)
            calls.append({"id": tc.id, "tool": tc.function.name, "arguments": tc.function.arguments,
                          "result": result, "seconds": round(time.perf_counter() - t0, 5)})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
        log.append({"round": rnd, "prompt_tokens": a, "completion_tokens": b, "tool_calls": calls})
    return {"texts": [text], "parsed": parse_answer(text), "in": tin, "out": tout,
            "calls": len(log), "rounds": len(log), "hit_limit": text is None,
            "tool_calls": sum(len(x.get("tool_calls", [])) for x in log), "log": log}


STRATEGIES = {"S1": s1_direct, "S2": s2_vote, "S3": s3_tools}
