"""Job Fit score: "does this JOB match YOU", computed in plain code from the
comparison's requirement lists (not an AI opinion).

Inputs are the match_report's `requirements_met` and `required_qualification_gaps`
(each with an importance), so the denominator is the whole posting. Required
requirements weigh more than preferred ones. A "partial" gap earns half credit,
a gap the candidate confirmed in the interview counts as met, and a missing one
earns nothing.

The result is deliberately a letter and a band, never a 0-100 number to chase:
a strong honest fit is the goal, not a perfect score. It is separate from the
resume's Keyword Match grade (does the RESUME reflect the posting).
"""
import re

WEIGHT = {"required": 3, "preferred": 2}
CREDIT = {"partial": 0.5, "missing": 0.0}

# (minimum percent, letter, band label, title, verdict)
BANDS = [
    (90, "A", "90%+", "Strong fit", "Strong fit. This job lines up with what you have already done. Apply."),
    (80, "B", "80–89%", "Good fit", "Good fit. Apply, and be ready to speak to the gaps below."),
    (70, "C", "70–79%", "Stretch", "A stretch. Apply if you can speak to the required gaps below."),
    (0, "D", "under 70%", "Not yet a fit", "Not a strong fit yet. Look at what would close the gaps below before spending time on this one."),
]

_PAREN = re.compile(r"\([^)]{0,300}\)")  # bounded, so a pile of unclosed brackets cannot make matching slow
_WORD = re.compile(r"[a-z0-9]+")


def _norm(text: str) -> str:
    return " ".join(_WORD.findall(_PAREN.sub(" ", (text or "").lower())))


def _confirmed(requirement: str, confirmed_facts: list[dict]) -> bool:
    """A gap the candidate confirmed in the interview: the fact's category is the
    gap's requirement (the interview is built from those categories)."""
    need = _norm(requirement)
    if not need:
        return False
    for fact in confirmed_facts or []:
        cat = _norm(fact.get("category", ""))
        if cat and (cat == need or cat in need or need in cat):
            return True
    return False


def _weight(importance: str) -> int:
    return WEIGHT.get(importance, WEIGHT["preferred"])


def compute_job_fit(match_report: dict, confirmed_facts: list[dict] | None = None) -> dict | None:
    """Returns the fit, or None when the comparison did not include the list of
    requirements already met (nothing honest to divide by)."""
    if not isinstance(match_report, dict) or "requirements_met" not in match_report:
        return None
    met = [m for m in (match_report.get("requirements_met") or []) if isinstance(m, dict)]
    gaps = [g for g in (match_report.get("required_qualification_gaps") or []) if isinstance(g, dict)]
    if not met and not gaps:
        return None

    earned = 0.0
    total = 0
    closed = 0
    counts = {"met": len(met), "partial": 0, "missing": 0}
    open_gaps = []
    for m in met:
        w = _weight(m.get("importance"))
        total += w
        earned += w
    for g in gaps:
        w = _weight(g.get("importance"))
        total += w
        if _confirmed(g.get("requirement", ""), confirmed_facts or []):
            earned += w
            counts["met"] += 1
            closed += 1
            continue
        status = g.get("status") if g.get("status") in CREDIT else "missing"
        earned += w * CREDIT[status]
        counts[status] += 1
        open_gaps.append(g)

    pct = round(earned / total * 100) if total else 0
    _, letter, band, title, verdict = next(b for b in BANDS if pct >= b[0])

    open_gaps.sort(key=lambda g: (g.get("importance") != "required", g.get("status") != "missing"))
    return {
        "pct": pct,
        "letter": letter,
        "band": band,
        "title": title,
        "verdict": verdict,
        "counts": counts,
        "closed_by_interview": closed,
        "open_gaps": [
            {
                "requirement": g.get("requirement", ""),
                "importance": g.get("importance", "preferred"),
                "status": g.get("status", "missing"),
                "how_to_close": g.get("how_to_close", ""),
            }
            for g in open_gaps[:6]
        ],
    }
