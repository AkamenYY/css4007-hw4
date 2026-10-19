"""Print the parts of the logs used in Part C (saved to outputs/inspect.txt)."""
import json, statistics
from pathlib import Path
O = Path("outputs")
out = []
p = out.append

def load(run, st):
    return {r["id"]: r for r in json.loads((O / run / f"{st}.json").read_text())}

def short(x, n=160):
    x = json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x
    return x if len(x) <= n else x[:n] + "..."

for run in ["run1", "run2"]:
    s3 = load(run, "S3")
    p(f"\n=== {run} S3 rounds / tool calls per question")
    p(", ".join(f"{q}:{r['rounds']}r/{r['tool_calls']}c" for q, r in s3.items()))
    p(f"median rounds {statistics.median(r['rounds'] for r in s3.values())}, max {max(r['rounds'] for r in s3.values())}")
    for st in ["S1", "S2", "S3"]:
        d = load(run, st)
        p(f"\n=== {run} {st} wrong answers: got vs expected")
        for q, r in d.items():
            if not r["correct"]:
                p(f"{q}: got {r['parsed']} | expected {r['expected']}" + (f" | votes {r['votes']}" if st == "S2" else ""))

def dump_s3(run, q):
    r = load(run, "S3")[q]
    p(f"\n--- {run} S3 {q} log (expected {r['expected']}, got {r['parsed']})")
    for rnd in r["log"]:
        p(f" round {rnd['round']}: prompt_tokens={rnd['prompt_tokens']} completion_tokens={rnd['completion_tokens']}")
        for c in rnd.get("tool_calls", []):
            p(f"   {c['tool']}({c['arguments']}) -> {short(c['result'])}")
        if "final" in rnd:
            p("   FINAL: " + short(rnd["final"], 600))

for run in ["run1", "run2"]:
    d = load(run, "S3")
    for q, r in d.items():
        if not r["correct"]:
            dump_s3(run, q)
dump_s3("run1", "Q-09")
r1 = load("run1", "S3")
dump_s3("run1", max(r1, key=lambda q: r1[q]["rounds"]))

s2 = load("run1", "S2")
for q in [q for q, r in s2.items() if not r["correct"]][:2]:
    p(f"\n--- run1 S2 {q} votes {s2[q]['votes']} (expected {s2[q]['expected']})")
    p("   sample 1 tail: " + short(s2[q]["texts"][0][-700:], 700))

s1 = load("run1", "S1")
for q in ["Q-09", "Q-17", "Q-01"]:
    p(f"\n--- run1 S1 {q}: {short(s1[q]['texts'][0], 200)} (expected {s1[q]['expected']})")

p("\n=== C1: normal (run1) vs vague description")
vague = load("c1_vague", "S3")
for q in vague:
    a, b = r1[q], vague[q]
    args = lambda r: [c["arguments"] for x in r["log"] for c in x.get("tool_calls", [])]
    p(f"{q}: calls {a['tool_calls']} vs {b['tool_calls']}, rounds {a['rounds']} vs {b['rounds']}, "
      f"answer {a['parsed']} vs {b['parsed']}, tokens {a['in']} vs {b['in']}")
    p("   vague args: " + short(args(b), 400))
text = "\n".join(out)
(O / "inspect.txt").write_text(text, encoding="utf-8")
print(text)
