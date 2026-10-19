"""The two tools the model can call: lookup and calculate.

Neither tool ever raises. Every failure comes back as {"error": "..."} so the
model can read it and try again.
"""
import ast
import difflib
import json
import math
import operator
import re
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "data" / "corpus.jsonl"

# ---------------------------------------------------------------- lookup ----

# field -> (unit, regex patterns tried in order; group 1 is the number)
FIELDS = {
    "population_2025": ("residents", [
        r"2025 census (?:recorded|counted) ([\d,]+)",
        r"Census population: [\d,]+ in 2020 and ([\d,]+) in 2025",
    ]),
    "population_2020": ("residents", [
        r"2020 census had recorded ([\d,]+)",
        r"([\d,]+) at the 2020 census",
        r"Census population: ([\d,]+) in 2020",
    ]),
    "area_km2": ("km2", [r"([\d,.]+) square kilometres"]),
    "budget_2025": ("million tenge", [r"([\d,.]+) million tenge"]),
    "water_2025": ("megalitres", [r"([\d,.]+) megalitres",
                                  r"([\d,.]+) cubic metres of water"]),
    "schools": ("schools", [r"(\d+) schools"]),
    "pupils_2025_26": ("pupils", [r"([\d,]+) pupils"]),
    "road_km": ("km", [r"([\d,.]+) km"]),
    "founded": ("year", [r"(?i)founded in (\d{4})"]),
}
REGION_FIELDS = {"water_tariff_2025": ("tenge per cubic metre",
                                       r"From 1 January 2025 .*? ([\d.]+) tenge per cubic metre")}


def _load_corpus():
    docs = [json.loads(line) for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    profiles, archived, corrections, region = {}, {}, {}, {}
    names = re.search(r"twelve districts: (.*?)\.", docs[0]["text"]).group(1).split(", ")
    for d in docs:
        title = d["title"]
        if "district profile" not in title.lower():
            if title.startswith("Correction notice"):
                corrections[title.split(" - ")[-1].strip()] = d
            else:
                region[d["id"]] = d
            continue
        name = title.split(" district")[0]
        (archived if "ARCHIVED" in title else profiles)[name] = d
    return names, profiles, archived, corrections, region


DISTRICTS, PROFILES, ARCHIVED, CORRECTIONS, REGION = _load_corpus()


def _num(s):
    return float(s.replace(",", ""))


def lookup(district: str = "", field: str = "") -> dict:
    """Return one 2025 fact about one district, with the document it came from."""
    try:
        field = (field or "").strip()
        if field in REGION_FIELDS:
            unit, pat = REGION_FIELDS[field]
            for doc in REGION.values():
                m = re.search(pat, doc["text"])
                if m:
                    return {"field": field, "value": _num(m.group(1)), "unit": unit,
                            "source": doc["id"], "note": "same in every district"}
            return {"error": f"{field} not found in the documents"}
        if field not in FIELDS:
            return {"error": f"unknown field '{field}'. Valid fields: "
                             f"{', '.join(list(FIELDS) + list(REGION_FIELDS))}"}

        typed = (district or "").strip()
        match = next((n for n in DISTRICTS if n.lower() == typed.lower()), None)
        if match is None:
            close = difflib.get_close_matches(typed.title(), DISTRICTS, n=2, cutoff=0.6)
            hint = f"; did you mean {' or '.join(close)}?" if close else ""
            return {"error": f"no district named '{typed}'{hint} "
                             f"Districts: {', '.join(DISTRICTS)}"}

        doc = PROFILES[match]
        unit, patterns = FIELDS[field]
        for pat in patterns:
            m = re.search(pat, doc["text"])
            if m:
                break
        else:
            return {"error": f"{field} is not given in the {match} profile ({doc['id']})"}

        result = {"district": match, "field": field, "value": _num(m.group(1)),
                  "unit": unit, "source": doc["id"]}
        notes = []
        if "cubic metres" in m.group(0):  # Lindenmoor gives water in m3
            result["value"] = round(result["value"] / 1000, 4)
            notes.append(f"profile gives {m.group(1)} cubic metres; converted to megalitres (1 ML = 1,000 m3)")
        corr = CORRECTIONS.get(match)
        if corr and field == "area_km2":
            fixed = re.search(r"correct area is ([\d,.]+) square kilometres", corr["text"])
            if fixed:
                notes.append(f"profile says {m.group(1)}, corrected by {corr['id']}")
                result["value"] = _num(fixed.group(1))
                result["source"] = f"{doc['id']} + {corr['id']}"
        if match in ARCHIVED:
            notes.append(f"archived profile {ARCHIVED[match]['id']} (2019) ignored")
        if notes:
            result["note"] = "; ".join(notes)
        return result
    except Exception as e:  # never crash the loop
        return {"error": f"lookup failed: {type(e).__name__}"}


# ------------------------------------------------------------- calculate ----

_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
MAX_LEN = 300          # characters in the expression
MAX_EXPONENT = 100     # largest power allowed
MAX_ABS = 1e15         # largest result allowed (any intermediate value)


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError(f"exponent larger than {MAX_EXPONENT} is not allowed")
        if isinstance(node.op, ast.Div) and right == 0:
            raise ZeroDivisionError("division by zero")
        value = _BINOPS[type(node.op)](left, right)
        if isinstance(value, complex) or abs(value) > MAX_ABS:
            raise ValueError("result is too large or not a real number")
        return value
    raise ValueError(f"'{type(node).__name__}' is not allowed; use numbers, + - * / ** and brackets only")


def calculate(expression: str = "") -> dict:
    """Safely work out an arithmetic expression. No eval, no exec."""
    expr = (expression or "").replace(",", "").strip()
    if not expr:
        return {"error": "empty expression"}
    if len(expr) > MAX_LEN:
        return {"error": f"expression longer than {MAX_LEN} characters"}
    try:
        tree = ast.parse(expr, mode="eval")
        value = _eval(tree)
        return {"expression": expr, "result": round(float(value), 10)}
    except ZeroDivisionError:
        return {"error": "division by zero"}
    except SyntaxError:
        return {"error": "could not read the expression; write it like 44675 / 921.4"}
    except (ValueError, OverflowError, TypeError) as e:
        return {"error": str(e) or "not allowed"}
    except Exception as e:
        return {"error": f"calculate failed: {type(e).__name__}"}


# ------------------------------------------------- definitions for the model

LOOKUP_DESCRIPTION = (
    "Get ONE number about ONE district of the Nine Rivers Region from the official "
    "documents. Call it once per district and field you need. It always uses the 2025 "
    "profile, ignores archived 2019 profiles, applies correction notices, and returns "
    "water in megalitres. The result says which document the number came from. "
    "For the regional water tariff use field 'water_tariff_2025' (district can be empty). "
    "If the district name is wrong you get an error with suggestions."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "lookup",
        "description": LOOKUP_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "district": {"type": "string", "description": "District name, e.g. 'Ossbridge'. Exact spelling matters."},
                "field": {"type": "string", "enum": list(FIELDS) + list(REGION_FIELDS),
                          "description": "Which number to return."},
            },
            "required": ["district", "field"],
            "additionalProperties": False,
        },
    }},
    {"type": "function", "function": {
        "name": "calculate",
        "description": ("Work out an arithmetic expression exactly, e.g. '44675 / 921.4 - 37203 / 758.6'. "
                        "Only numbers, + - * / ** and brackets. Use it for every calculation instead of "
                        "doing arithmetic yourself. Returns the unrounded result."),
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "The arithmetic expression."}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    }},
]

TOOL_FUNCTIONS = {"lookup": lookup, "calculate": calculate}
