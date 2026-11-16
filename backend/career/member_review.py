"""C-52 round 7: the common member-review keys, and how a saved résumé's kind is read.

Two different things are stored in a résumé version's JSON, and they must never be confused:
- `truth_review` written by the JOB-TARGETED pipeline (answer conflicts, claims struck, claim and verb review, held lines,
  provenance). Its meaning and contents are preserved exactly. It is never read as a member review.
- `member_review` / `member_signoff`: the common member review and sign-off, used by both résumé kinds from this round on.

Legacy general résumés stored their review under `truth_review` (identified by the checker version it carries) and their sign-off
under `final_signoff`. Those are still read (fallback), and are moved to the common keys the next time they are written. No migration.
"""

MEMBER_REVIEW = "member_review"
MEMBER_SIGNOFF = "member_signoff"
LEGACY_GENERAL_REVIEW = "truth_review"     # only when it is a general review (carries a checker version)
LEGACY_SIGNOFF = "final_signoff"
JOB_MARKERS = ("term_report", "role_selection", "ats_match")   # written only by the job-targeted build


def is_general_shaped(value) -> bool:
    return isinstance(value, dict) and "checker_version" in value and "content_hash" in value


def review_of(data):
    """The member review of a saved résumé, or None when it has never been checked. A job-specific truth_review is never returned."""
    data = data or {}
    if isinstance(data.get(MEMBER_REVIEW), dict):
        return data[MEMBER_REVIEW]
    if is_general_shaped(data.get(LEGACY_GENERAL_REVIEW)):
        return data[LEGACY_GENERAL_REVIEW]
    return None


def signoff_of(data):
    data = data or {}
    value = data.get(MEMBER_SIGNOFF)
    if value is None:
        value = data.get(LEGACY_SIGNOFF)
    return value or None


def kind_of(data) -> str:
    """'job' for a job-targeted résumé (it carries the job build's own records); 'general_review' for a general résumé with a member
    review; 'general_legacy' for any other saved résumé (a general résumé saved before the truth check)."""
    data = data or {}
    if any(k in data for k in JOB_MARKERS):
        return "job"
    if review_of(data) is not None:
        return "general_review"
    return "general_legacy"


def with_review(data, review) -> dict:
    """The résumé content with the member review stored under the common key. A legacy general review is moved out, not kept beside it."""
    out = {k: v for k, v in (data or {}).items() if not (k == LEGACY_GENERAL_REVIEW and is_general_shaped(v))}
    out[MEMBER_REVIEW] = review
    return out


def with_signoff(data, signoff) -> dict:
    """The résumé content with the sign-off stored under the common key (None removes it). A legacy sign-off is moved out."""
    out = {k: v for k, v in (data or {}).items() if k != LEGACY_SIGNOFF}
    if signoff is None:
        out.pop(MEMBER_SIGNOFF, None)
    else:
        out[MEMBER_SIGNOFF] = signoff
    return out


def is_job_kind(data) -> bool:
    return kind_of(data) == "job"
