"""Compare a LinkedIn review (the public Spotlight tool's result) with the
skills saved in a signed-in person's Career Profile. Plain code, no AI call.

Two lists come back:
- on_review_not_in_profile: skills the review says are demonstrated or worth
  considering that are NOT yet in the Career Profile (add them to the profile).
- in_profile_not_on_linkedin: Career Profile skills never mentioned anywhere in
  the LinkedIn review text (consider adding them on LinkedIn).
"""
import re

from career.term_pipeline import normalize, term_in_text

MAX_RESULTS = 40
MAX_LABEL_WORDS = 4
_SPLIT_LABEL = re.compile(r"\s+[-–—]\s+|:\s+")
_PAREN = re.compile(r"\([^)]*\)")
_PART_SPLIT = re.compile(r"\s*/\s*")


def _all_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _all_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]
    return []


def _labels(entry: str) -> list[str]:
    """'Pre-sales / Solutions Consulting - supported by the CashPro role' ->
    ['Pre-sales', 'Solutions Consulting']. Anything sentence-like is dropped."""
    head = _SPLIT_LABEL.split(entry.strip(), maxsplit=1)[0]
    head = _PAREN.sub(" ", head)
    out = []
    for part in _PART_SPLIT.split(head):
        label = " ".join(part.split()).strip(" .;,-")
        if label and len(label.split()) <= MAX_LABEL_WORDS and len(label) <= 60:
            out.append(label)
    return out


def _already_in_profile(label: str, profile_skills: list[str]) -> bool:
    return any(
        normalize(label) == normalize(s) or term_in_text(label, s) or term_in_text(s, label)
        for s in profile_skills
    )


def compare_skills(review: dict, profile_skills: list[str]) -> dict:
    skills = (review or {}).get("skills") if isinstance(review, dict) else None
    skills = skills if isinstance(skills, dict) else {}

    candidates: list[str] = []
    seen: set[str] = set()
    for key in ("clearly_demonstrated", "possible_to_consider"):
        for entry in skills.get(key) or []:
            if not isinstance(entry, str):
                continue
            for label in _labels(entry):
                k = normalize(label)
                if k and k not in seen and not _already_in_profile(label, profile_skills):
                    seen.add(k)
                    candidates.append(label)

    corpus = "\n".join(_all_strings(review))
    missing_on_linkedin = [s for s in profile_skills if s and not term_in_text(s, corpus)]

    return {
        "on_review_not_in_profile": candidates[:MAX_RESULTS],
        "in_profile_not_on_linkedin": missing_on_linkedin[:MAX_RESULTS],
    }
