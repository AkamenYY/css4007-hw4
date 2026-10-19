"""Run the strategies on the questions and save everything to outputs/.

python run.py --run 1                         # S1, S2, S3 on all 20 questions
python run.py --run 1 --questions Q-09 --strategies S3
python run.py --run c1_vague --strategies S3 --vague --questions Q-01,Q-03,Q-08,Q-09,Q-18
python run.py --measure-tools                 # tokens added by the tool definitions
"""
import argparse
import copy
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import strategies as S
from tools import TOOLS

# Price per million tokens for gpt-5.6-luna (OpenAI price after the July 2026 cut;
# check platform.openai.com/usage for what was actually billed).
PRICE_IN, PRICE_OUT = 0.20, 1.20
WORKERS = 5  # questions run in parallel to save wall-clock time; timing is per question

QUESTIONS = json.loads((Path(__file__).parent / "data" / "questions.json").read_text(encoding="utf-8"))


def run_one(strategy, q, tools):
    t0 = time.perf_counter()
    try:
        res = S.s3_tools(q, tools) if strategy == "S3" else S.STRATEGIES[strategy](q)
    except Exception as e:  # keep going, count it as unanswered
        res = {"texts": [], "parsed": None, "in": 0, "out": 0, "calls": 0, "error": repr(e)}
    res["seconds"] = round(time.perf_counter() - t0, 2)
    res["id"] = q["id"]
    res["correct"] = S.is_correct(res["parsed"], q)
    res["unanswered"] = res["parsed"] is None
    res["expected"] = f"{q['answer']} | {q['value']}"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="1")
    ap.add_argument("--strategies", default="S1,S2,S3")
    ap.add_argument("--questions", default="")
    ap.add_argument("--vague", action="store_true", help="S3 with a one-line lookup description")
    ap.add_argument("--measure-tools", action="store_true")
    a = ap.parse_args()

    if a.measure_tools:
        measure_tools()
        return

    tools = TOOLS
    if a.vague:
        tools = copy.deepcopy(TOOLS)
        tools[0]["function"]["description"] = "Looks things up."

    qs = [q for q in QUESTIONS if not a.questions or q["id"] in a.questions.split(",")]
    out = Path("outputs") / f"run{a.run}" if a.run[0].isdigit() else Path("outputs") / a.run
    out.mkdir(parents=True, exist_ok=True)
    summary, per_q = [], {}

    for st in a.strategies.split(","):
        wall = time.perf_counter()
        with ThreadPoolExecutor(WORKERS) as ex:
            results = list(ex.map(lambda q: run_one(st, q, tools), qs))
        wall = round(time.perf_counter() - wall, 1)

        (out / f"{st}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        if st == "S3":  # one log file per question
            (out / "S3_logs").mkdir(exist_ok=True)
            for r in results:
                (out / "S3_logs" / f"{r['id']}.json").write_text(
                    json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

        tin, tout = sum(r["in"] for r in results), sum(r["out"] for r in results)
        secs = [r["seconds"] for r in results]
        cost = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
        name = {"S1": "S1 direct", "S2": f"S2 think and vote (k = {S.K})", "S3": "S3 tools"}[st]
        summary.append(f"| {a.run} | {name} | {sum(r['correct'] for r in results)} | "
                       f"{sum(r['unanswered'] for r in results)} | {tin} | {tout} | "
                       f"{statistics.median(secs):.1f} | {sum(secs):.1f} | {cost:.4f} |")
        for r in results:
            per_q.setdefault(r["id"], {})[st] = "✓" if r["correct"] else ("–" if r["unanswered"] else "✗")
        print(summary[-1], f"(wall clock {wall}s)")

    sts = a.strategies.split(",")
    lines = ["| Run | Strategy | Correct | Unanswered | Input tokens | Output tokens | "
             "Median seconds per question | Total seconds | Cost ($) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|", *summary, "",
             "| Question | " + " | ".join(sts) + " |", "|---|" + ":---:|" * len(sts)]
    lines += [f"| {qid} | " + " | ".join(per_q[qid].get(s, "") for s in sts) + " |" for qid in per_q]
    lines += ["", f"temperature accepted by the model: {S._temperature_ok}"]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSaved to {out}/")


def measure_tools():
    """Same message with and without tools; the difference is what the definitions cost."""
    msgs = [{"role": "user", "content": "Say OK."}]
    with_t = S.chat(messages=msgs, tools=TOOLS).usage.prompt_tokens
    without = S.chat(messages=msgs).usage.prompt_tokens
    text = f"prompt_tokens with tools = {with_t}, without = {without}, tools add {with_t - without}"
    print(text)
    Path("outputs").mkdir(exist_ok=True)
    (Path("outputs") / "tool_tokens.txt").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
