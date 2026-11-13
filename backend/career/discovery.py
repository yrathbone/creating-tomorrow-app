"""Job discovery pilot: deterministic, explainable matching of open postings to a member's confirmed preferences and career profile.

No AI call, no network call, no third-party data sent anywhere. Every match carries the reasons it was made, and every
exclusion is a plain rule the member can read in their own preferences.
"""
import re
from models import JobPosting

WORD = re.compile(r"[a-z0-9]{3,}")
STOPWORDS = frozenset({"and", "the", "for", "with", "from", "into", "our", "you", "your", "will", "job", "role", "work", "team"})
MAX_RECOMMENDATIONS = 10


def tokens(text: str | None) -> set[str]:
    return {w for w in WORD.findall((text or "").lower()) if w not in STOPWORDS}


def profile_terms(experience_titles: list[str], skill_names: list[str]) -> set[str]:
    terms: set[str] = set()
    for text in list(experience_titles) + list(skill_names):
        terms |= tokens(text)
    return terms


def _in_location(posting_location: str | None, locations: list[str]) -> bool:
    loc = (posting_location or "").lower()
    return any(item.lower() in loc for item in locations if item)


def match_posting(posting: JobPosting, prefs: dict, terms: set[str]) -> dict | None:
    """Returns {"score": int, "reasons": [str]} or None when a hard rule excludes the posting."""
    title = (posting.title or "").lower()
    arrangement = posting.work_arrangement

    if arrangement == "remote" and not prefs["remote_ok"]:
        return None
    if arrangement in ("on_site", "hybrid") and not prefs["onsite_ok"]:
        return None
    if prefs["employment_types"] and posting.employment_type and posting.employment_type not in prefs["employment_types"]:
        return None
    if any(word and word.lower() in title for word in prefs["exclude_words"]):
        return None

    reasons: list[str] = []
    location_ok = not prefs["locations"]
    if prefs["locations"]:
        if _in_location(posting.location_text, prefs["locations"]):
            location_ok = True
            reasons.append(f"Location: {posting.location_text}")
        elif arrangement == "remote" and prefs["remote_ok"]:
            location_ok = True
            reasons.append("Remote role")
    if not location_ok:
        return None

    score = 0
    targets = [t.lower() for t in prefs["target_titles"] if t]
    if any(t in title for t in targets):
        score += 3
        reasons.append("Title matches a target role")
    else:
        overlap = tokens(posting.title) & tokens(" ".join(targets))
        if overlap:
            score += min(len(overlap), 3)
            reasons.append("Title words: " + ", ".join(sorted(overlap)[:4]))

    profile_overlap = tokens(posting.title) & terms
    if profile_overlap:
        score += min(len(profile_overlap), 3)
        reasons.append("Matches your profile: " + ", ".join(sorted(profile_overlap)[:4]))

    if score == 0:
        return None
    return {"score": score, "reasons": reasons}


def rank(postings: list[JobPosting], prefs: dict, terms: set[str], limit: int = MAX_RECOMMENDATIONS) -> list[tuple[JobPosting, dict]]:
    scored = []
    for posting in postings:
        if posting.closed_on is not None:
            continue
        result = match_posting(posting, prefs, terms)
        if result is not None:
            scored.append((posting, result))
    scored.sort(key=lambda pair: (-pair[1]["score"], -pair[0].first_seen_on.toordinal(), pair[0].id))
    return scored[:limit]
