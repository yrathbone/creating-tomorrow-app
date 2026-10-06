"""Compare a LinkedIn review (the public Spotlight tool's result) with the
skills saved in a signed-in person's Career Profile. Plain code, no AI call.

Three lists come back:
- roles_not_in_profile: roles in the review's sample profile (title, organization,
  bullets) that match none of the saved roles, so they can be added with a tick.
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


def _squash(text: str) -> str:
    """Letters and digits only, so "V.P., Treasury" and "VP Treasury" compare equal."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _is_note(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("[") and t.endswith("]")


def _same_role(title: str, org: str, existing: list[dict]) -> bool:
    t, o = _squash(title), _squash(org)
    for e in existing:
        et, eo = _squash(e.get("title")), _squash(e.get("organization"))
        same_org = bool(o) and bool(eo) and (o == eo or o in eo or eo in o)
        same_title = bool(t) and bool(et) and (t == et or t in et or et in t)
        if same_org and same_title:
            return True
    return False


def compare_roles(review: dict, existing_roles: list[dict]) -> list[dict]:
    """Roles from the review's sample updated profile that are not already saved.
    Bracketed [notes] are dropped from the bullets. No dates come with these roles,
    so the person adds them after (the site says so)."""
    sample = (review or {}).get("suggested_full_profile") if isinstance(review, dict) else None
    roles = sample.get("experience") if isinstance(sample, dict) else None
    out = []
    for role in roles if isinstance(roles, list) else []:
        if not isinstance(role, dict):
            continue
        title = " ".join(str(role.get("title") or "").split())
        org = " ".join(str(role.get("organization") or "").split())
        if not title or _same_role(title, org, existing_roles):
            continue
        bullets = [b.strip() for b in (role.get("bullets") or []) if isinstance(b, str) and b.strip() and not _is_note(b)]
        out.append({"title": title, "organization": org, "description": "\n".join(bullets)})
    return out[:MAX_RESULTS]


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
