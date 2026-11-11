"""Deterministic stand-in for the Anthropic messages.create call, for the LOCAL SYNTHETIC test harness only (C-52 round 7).

What it is
- A replacement for `anthropic.Anthropic` that answers each tool call the app makes with a fixed, schema-shaped result.
- The results are written for ONE synthetic member profile and ONE synthetic job posting (see SYNTHETIC_PROFILE below).
- Everything around the call stays REAL: prompt building, schema checks on the tool result, the truthfulness and provenance
  checks, the evidence checks, the feature switch, and every authorization check. Only the model's answer is fixed.

What it is not
- It is not a model and makes no network call.
- It is not enabled unless the local harness runs (CT_LOCAL_HARNESS=1, localhost only, no hosting-platform markers).
  The harness guard in local_signed_in.py refuses everything else before this module is installed.
- Any tool it does not know raises an error, so an unexpected AI call fails loudly instead of passing silently.
"""
from types import SimpleNamespace

SYNTHETIC_PROFILE = {
    "experience": {
        "title": "Customer Service Lead",
        "organization": "Sample Company",
        "start_date": "2022",
        "end_date": "2025",
        "description": "Led a team of 6 agents handling customer escalations\n"
                       "Reduced average response time by 25% through a new triage process",
    },
    "skills": ["Team leadership", "Zendesk", "Excel", "Customer escalations"],
    "name": "Synthetic Member A",
    "contact": "member.a@example.invalid | 555-0100",
}

POSTING_TITLE = "Customer Service Lead at Sample Employer"


def _comparison(_prompt):
    return {
        "job_title": POSTING_TITLE,
        "match_report": {
            "match_level": "High",
            "match_rationale": "The profile shows team leadership and customer escalation work. Salesforce is not in the profile.",
            "strengths": ["Team leadership of 6 agents", "Customer escalations on Zendesk"],
            "required_qualification_gaps": [
                {"requirement": "Salesforce", "importance": "required", "status": "missing",
                 "explanation": "The profile does not mention Salesforce.",
                 "how_to_close": "A short course or hands-on role using Salesforce."},
            ],
            "requirements_met": [
                {"requirement": "Team leadership", "importance": "required"},
                {"requirement": "Zendesk", "importance": "required"},
            ],
        },
        "categories": ["Leadership", "Tools"],
        "questions": [
            {"id": "q1", "category": "Tools", "question": "Have you used Salesforce in any role, even briefly?"},
            {"id": "q2", "category": "Leadership", "question": "How did you train new agents on escalations?"},
            {"id": "q3", "category": "Results", "question": "What measures did you track for response time?"},
        ],
    }


def _term_plan(_prompt):
    return {
        "terms": [
            {"term": "Team leadership", "importance": "required", "kind": "skill", "support": "literal",
             "evidence": "Customer Service Lead: led a team of 6 agents"},
            {"term": "Zendesk", "importance": "required", "kind": "skill", "support": "literal",
             "evidence": "Customer Service Lead: customer escalations on Zendesk"},
            {"term": "customer escalations", "importance": "preferred", "kind": "phrase", "support": "literal",
             "evidence": "Customer Service Lead: handling customer escalations"},
            {"term": "Salesforce", "importance": "required", "kind": "skill", "support": "none", "evidence": ""},
        ]
    }


def _resume(_prompt):
    exp = SYNTHETIC_PROFILE["experience"]
    return {
        "resume_data": {
            "name": SYNTHETIC_PROFILE["name"],
            "contact": SYNTHETIC_PROFILE["contact"],
            "headline": "Customer Service Leadership | Team Leadership | Zendesk",
            "summary": "Customer Service Lead who led a team of 6 agents and handled customer escalations on Zendesk.",
            "skills": ["Team leadership", "Zendesk", "Customer escalations", "Excel"],
            "experience": [{
                "title": exp["title"],
                "subtitle": f"{exp['organization']} · {exp['start_date']} – {exp['end_date']}",
                "bullets": exp["description"].split("\n"),
            }],
            "education": [],
            "certifications": [],
        },
        "role_selection": [{"title": exp["title"], "organization": exp["organization"], "treatment": "full",
                            "reason": "The only role in the synthetic profile, and it matches the posting."}],
    }


def _revised(prompt):
    return _resume(prompt)


def _skill_keywords(_prompt):
    return {"skills": []}


def _general(prompt):
    return _resume(prompt)


FIXTURES = {
    "submit_job_comparison": _comparison,
    "submit_term_plan": _term_plan,
    "submit_tailored_resume": _resume,
    "submit_revised_resume": _revised,
    "submit_skill_keywords": _skill_keywords,
    "submit_general_resume": _general,
}


class _Messages:
    def __init__(self):
        self.calls = []

    def create(self, *, model, max_tokens, system, tools, tool_choice, messages, **_kw):
        name = tool_choice.get("name") if isinstance(tool_choice, dict) else None
        self.calls.append(name)
        handler = FIXTURES.get(name)
        if handler is None:
            raise RuntimeError(f"stub: no fixture for tool {name!r}; the harness refuses unknown AI calls")
        prompt = messages[-1]["content"] if messages else ""
        data = handler(prompt)
        block = SimpleNamespace(type="tool_use", name=name, input=data, id="stub-" + name)
        return SimpleNamespace(stop_reason="tool_use", content=[block],
                               usage=SimpleNamespace(input_tokens=0, output_tokens=0,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0))


class StubAnthropic:
    """Replaces anthropic.Anthropic inside the harness process only."""

    def __init__(self, *_a, **_kw):
        self.messages = _Messages()


STUB_CLIENT = None


def install() -> None:
    """Installs the stub into the anthropic module (harness process only). Idempotent."""
    global STUB_CLIENT
    import anthropic
    STUB_CLIENT = StubAnthropic()
    anthropic.Anthropic = lambda *a, **k: STUB_CLIENT
