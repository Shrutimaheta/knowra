"""Conservative, local checks for incompatible quantities and explicit permissions."""

import hashlib
import itertools
import json
import re
from collections import defaultdict
from decimal import Decimal

from app.comparison import units
from fastapi import HTTPException

METRICS = [
    (
        "annual_leave",
        "Annual leave",
        r"annual\s+leave|paid\s+leave|leave\s+(?:allowance|entitlement)|vacation",
        {"days"},
    ),
    ("remote_work", "Remote work", r"remote(?:ly)?|work\s+from\s+home", {"days"}),
    (
        "expense_deadline",
        "Expense claim deadline",
        r"expense\s+(?:deadline|claims?)|reimbursement\s+(?:deadline|claims?)",
        {"days", "hours"},
    ),
    (
        "carryover",
        "Leave carryover",
        r"carryover|carry\s+(?:over|into)|unused\s+leave",
        {"days"},
    ),
    (
        "equipment",
        "Equipment allowance",
        r"equipment\s+(?:allowance|budget)|equipment",
        {"INR", "USD"},
    ),
    (
        "retention",
        "Data retention",
        r"(?:data|record|log)\s+retention|retain\s+(?:data|records|logs)",
        {"days", "months", "years"},
    ),
    (
        "response_time",
        "Response time",
        r"response\s+(?:time|deadline)|respond\s+within",
        {"minutes", "hours", "days"},
    ),
]
SMALL = dict(
    zip(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
        range(20),
        strict=True,
    )
)
TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
NUMBER = (
    r"(?:\d+(?:,\d{3})*(?:\.\d+)?|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|"
    + "|".join(SMALL)
    + ")"
)
QUANTITY = re.compile(
    rf"\b(?P<value>{NUMBER})\s+(?P<unit>business days?|working days?|days?|weeks?|hours?|minutes?|months?|years?|percent)(?=\W|$)|\b(?P<percent>{NUMBER})\s*%",
    re.I,
)
CURRENCY = re.compile(
    rf"(?P<currency>\bINR\b|\bUSD\b|\$|₹)\s*(?P<value>{NUMBER})(?=\W|$)", re.I
)
NEGATIVE = re.compile(
    r"\b(?:not\s+(?:allowed|permitted|eligible|authorized)|prohibited|forbidden|must\s+not|cannot|may\s+not|can\s+not)\b",
    re.I,
)
PERMISSION = re.compile(
    r"\b(?:allowed|permitted|eligible|authorized|can|may|prohibited|forbidden|cannot)\b",
    re.I,
)
SCOPES = re.compile(
    r"\b(?:engineering|sales|finance|marketing|operations|contractors?|interns?|full[- ]time|part[- ]time|permanent|temporary|probation)\b",
    re.I,
)
FILLER = set(
    "a an the is are be to for of and in on not can cannot may must allowed permitted eligible authorized prohibited forbidden employees employee members member team all".split()
)


def number(value):
    value = value.lower().replace(",", "")
    if value[0].isdigit():
        return (
            format(Decimal(value).normalize(), "f") if "." in value else str(int(value))
        )
    return str(
        sum(SMALL.get(word, TENS.get(word, 0)) for word in re.split(r"[ -]", value))
    )


def quantities(text):
    result = []
    for match in QUANTITY.finditer(text):
        unit = (match["unit"] or "percent").lower()
        unit = (
            "business_days"
            if unit.startswith(("working", "business"))
            else unit.rstrip("s") + "s"
            if unit != "percent"
            else "percent"
        )
        basis = re.search(
            r"\b(?:per|each|every|a|an)\s+(day|week|month|year)\b",
            text[match.end() : match.end() + 40],
            re.I,
        )
        result.append(
            {
                "value": number(match["value"] or match["percent"]),
                "unit": unit,
                "basis": basis[1].lower() if basis else "",
                "position": match.start(),
            }
        )
    for match in CURRENCY.finditer(text):
        result.append(
            {
                "value": number(match["value"]),
                "unit": "INR" if match["currency"].upper() in {"INR", "₹"} else "USD",
                "basis": "",
                "position": match.start(),
            }
        )
    return result


def facts(source):
    found = []
    for passage in units(source["pages"]):
        text = passage["text"]
        if len(text) > 1800:
            continue
        metric_matches = [
            (key, label, re.search(pattern, text, re.I), allowed)
            for key, label, pattern, allowed in METRICS
        ]
        metric_matches = [row for row in metric_matches if row[2]]
        values = quantities(text)
        for key, label, _match, allowed in metric_matches:
            candidates = [
                v
                for v in values
                if v["unit"] in allowed
                or (v["unit"] == "business_days" and "days" in allowed)
            ]
            if not candidates:
                continue
            # A sentence containing several policy topics is too ambiguous to
            # assign quantities safely. Review those passages manually.
            if len(metric_matches) != 1:
                continue
            if len(candidates) != 1:
                continue
            value = candidates[0]
            basis = value["basis"] or (
                "year" if key in {"annual_leave", "equipment"} else ""
            )
            found.append(
                dict(
                    passage,
                    metric=key,
                    label=label,
                    kind="quantity",
                    value=value["value"],
                    dimension=value["unit"] + ("/" + basis if basis else ""),
                )
            )
        if (PERMISSION.search(text) or NEGATIVE.search(text)) and not values:
            if len(metric_matches) == 1:
                key, label, _, _ = metric_matches[0]
            elif not metric_matches:
                topic = sorted(set(re.findall(r"[a-z]+", text.lower())) - FILLER)
                if not 2 <= len(topic) <= 12:
                    continue
                key, label = (
                    "permission:" + ":".join(topic),
                    "Permission: " + " ".join(topic),
                )
            else:
                continue
            found.append(
                dict(
                    passage,
                    metric=key,
                    label=label,
                    kind="permission",
                    value="not permitted" if NEGATIVE.search(text) else "permitted",
                    dimension="permission",
                )
            )
    return found


def detect(sources, target=None):
    total_chars = sum(sum(map(len, source["pages"])) for source in sources)
    if total_chars > 400_000:
        raise HTTPException(
            413, "Select documents with at most 400,000 combined extracted characters."
        )
    groups, count = defaultdict(list), 0
    for source in sorted(sources, key=lambda item: item["document"]):
        for fact in facts(source):
            count += 1
            if count > 400:
                raise HTTPException(
                    413, "Too many checkable claims. Select fewer or smaller documents."
                )
            groups[(fact["metric"], fact["kind"], fact["dimension"])].append(
                (source, fact)
            )
    results, tested, possible = [], 0, 0
    for group in groups.values():
        for (left, a), (right, b) in itertools.combinations(group, 2):
            if left["document"] == right["document"]:
                continue
            tested += 1
            if tested > 20_000:
                raise HTTPException(
                    413, "Too many candidate pairs. Select fewer documents."
                )
            if a["value"] == b["value"]:
                continue
            possible += 1
            if len(results) >= 100 and target is None:
                continue
            evidence = []
            for source, fact in ((left, a), (right, b)):
                evidence.append(
                    {k: v for k, v in source.items() if k != "pages"}
                    | {k: fact[k] for k in ("page", "text", "start", "end", "value")}
                )
            fingerprint = hashlib.sha256(
                json.dumps(
                    [
                        a["metric"],
                        a["kind"],
                        a["dimension"],
                        [(s["version_id"], s["page"], s["text"]) for s in evidence],
                    ],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            if target is not None and fingerprint != target:
                continue
            warnings = [
                "Dates, departments and eligibility rules can explain this difference. Review both sources before choosing one."
            ]
            years = [
                sorted(
                    set(
                        re.findall(
                            r"\b20\d{2}\b",
                            source["title"] + " " + " ".join(source["pages"])[:2000],
                        )
                    )
                )
                for source in (left, right)
            ]
            if years[0] != years[1] and any(years):
                warnings.append(
                    "The sources mention different years: "
                    + " / ".join(", ".join(items) or "not specified" for items in years)
                    + ". This may be a policy update."
                )
            scopes = [
                sorted({m.group().lower() for m in SCOPES.finditer(fact["text"])})
                for fact in (a, b)
            ]
            if scopes[0] != scopes[1] and any(scopes):
                warnings.append(
                    "Different eligibility or department wording: "
                    + " / ".join(
                        ", ".join(items) or "not specified" for items in scopes
                    )
                    + "."
                )
            results.append(
                {
                    "id": fingerprint,
                    "topic": a["label"],
                    "kind": a["kind"],
                    "unit": a["dimension"],
                    "sources": evidence,
                    "warnings": warnings,
                }
            )
    return {
        "findings": results,
        "total": possible,
        "truncated": possible > len(results),
        "claims_checked": count,
        "pairs_checked": tested,
        "method": "local-policy-rules",
        "notice": "Possible conflicts, not verified contradictions. Checks cover supported policy quantities and explicit permissions; no findings does not prove the documents agree. OCR errors can affect results.",
    }
