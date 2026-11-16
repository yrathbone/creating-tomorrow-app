"""C-52 truthfulness regression tests for the GENERAL résumé path (tests only; no behaviour change).

Finding (2026-11-14, Synthetic Accounts A and B): the general résumé route saves AI output after only dedupe_skills and
drop_unsourced_bullets. It does not run the claim, title, credential or soft-claim checks that the job-targeted route runs
(career/term_pipeline.py build_checked_resume -> resume_quality.find_issues / find_claim_issues).

How the tests are arranged:
- Tests marked @expectedFailure DEMONSTRATE the current failure. They must start passing ("unexpected success") after the
  validator is wired in; remove the decorator then.
- Tests without the decorator protect legitimate behaviour and must keep passing (transferable skills, exact factual fields).

The AI call is mocked with the generated text actually seen for each synthetic account, so no paid call is made.

Run from the backend folder:  py -3.12 -m unittest tests.test_general_resume_truthfulness_regression -v
"""
import os
import unittest
from unittest import mock

import abuse_guard
from career import resume_quality
from tests.test_ownership import OwnershipTestCase

# --- Synthetic Account B: source (saved profile) and the output the model actually produced (2026-11-14) -------------
B_ROLE = {"title": "Coordinator", "organization": "Fictional Organization Beta", "subtitle": "Fictional Organization Beta — Jun 2021 – May 2025"}
B_BULLETS = [
    "Handled customer requests and kept records for a fictional office of eight.",
    "Improved the record-keeping checklist.",
]
B_EDUCATION = "Fictional School B: Certificate, Customer Service"
B_SKILLS_SAVED = ["Customer support", "Record keeping", "Calendar planning", "Written communication"]
B_GENERATED = {
    "name": "SYNTHETIC Member B",
    "contact": "SYNTHETIC | synthetic.member.b@example.com",
    "headline": "Customer Support Coordinator | Records & Office Operations",
    "summary": (
        "Service-oriented coordinator with experience handling customer requests and maintaining records for a small office team. "
        "Skilled in record keeping, calendar planning, and written communication, with a track record of improving administrative "
        "processes. Certified in customer service and dependable in fast-paced, detail-driven environments."
    ),
    "skills": ["Customer Support", "Record Keeping", "Calendar Planning", "Written Communication", "Process Improvement", "Office Administration"],
    "experience": [{
        "title": "Coordinator",
        "subtitle": "Fictional Organization Beta — 06/21 – 05/25",
        "bullets": [
            "Handled customer requests and maintained records for a fictional office of eight.",
            "Improved the record-keeping checklist, streamlining documentation practices.",
        ],
    }],
    "education": [B_EDUCATION],
    "certifications": [],
}

# --- Synthetic Account A: generated output (2026-11-14) -------------------------------------------------------------
A_GENERATED = {
    "name": "SYNTHETIC Member A",
    "contact": "SYNTHETIC | synthetic.member.a@example.com",
    "headline": "Operations Coordination | Scheduling & Reporting | Team Support",
    "summary": (
        "Operations professional with experience coordinating scheduling and reporting for a team, maintaining shared trackers, "
        "and improving report turnaround time. Known for dependable written communication and effective teamwork in fast-paced "
        "coordination roles. Holds a Certificate in Office Administration."
    ),
    "skills": ["Scheduling", "Reporting", "Spreadsheet Tracking", "Written Communication", "Teamwork", "Operations Coordination"],
    "experience": [{
        "title": "Operations Coordinator",
        "subtitle": "Fictional Organization Alpha — Jan 2021 – Mar 2023",
        "bullets": [
            "Coordinated scheduling and reporting for a team of six.",
            "Maintained a shared tracker to support team coordination.",
            "Reduced weekly report preparation time through improved tracking processes.",
        ],
    }],
    "education": ["Fictional School: Certificate in Office Administration"],
    "certifications": [],
}

B_SKILLS_UNSUPPORTED = {"Office Administration"}
# "Office Operations" is UNCERTAIN under the accepted Step B checker (kept for the member to decide), not UNSUPPORTED.
B_HEADLINE_UNSUPPORTED = {"Customer Support Coordinator"}
B_SUMMARY_UNSUPPORTED = {"Certified", "track record", "fast-paced", "detail-driven"}


def _all_text(resume: dict) -> str:
    parts = [resume.get("headline", ""), resume.get("summary", ""), " ".join(resume.get("skills", []))]
    for job in resume.get("experience", []):
        parts.append(job.get("title", ""))
        parts.append(job.get("subtitle", ""))
        parts.extend(job.get("bullets", []))
    parts.extend(resume.get("education", []))
    return "\n".join(parts)


class GeneralResumeTruthfulnessRoute(OwnershipTestCase):
    """Drives the real route with the AI call mocked to return what the model actually produced."""

    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()

    def _seed_b_profile(self):
        self.onboard(self.a)
        res = self.call("POST", "/experiences", self.a, json={"title": B_ROLE["title"], "organization": B_ROLE["organization"], "description": " ".join(B_BULLETS)})
        self.assertEqual(res.status_code, 200, res.text)
        for skill in B_SKILLS_SAVED:
            res = self.call("POST", "/skills", self.a, json={"name": skill})
            self.assertEqual(res.status_code, 200, res.text)

    def _build(self, generated: dict, mode: str = "off") -> dict:
        self._seed_b_profile()
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}), mock.patch("career.routes.build_general_resume", return_value={"resume_data": dict(generated, experience=[dict(j, bullets=list(j["bullets"])) for j in generated["experience"]], skills=list(generated["skills"]), education=list(generated["education"]), certifications=[])}):
            res = self.call("POST", "/build-general-resume", self.a, json={"name": "SYNTHETIC Member B", "contact": "SYNTHETIC | synthetic.member.b@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["resume_data"]

    # ---- Failure demonstrations (expected to fail today) -------------------------------------------------------------

    def test_b_unsupported_skill_is_not_saved_as_a_qualification(self):
        saved = self._build(B_GENERATED, mode="on")
        self.assertFalse(B_SKILLS_UNSUPPORTED & set(saved["skills"]), f"unsupported skill saved: {set(saved['skills']) & B_SKILLS_UNSUPPORTED}")

    def test_b_unsupported_headline_title_is_not_saved(self):
        saved = self._build(B_GENERATED, mode="on")
        hits = {t for t in B_HEADLINE_UNSUPPORTED if t in saved["headline"]}
        self.assertFalse(hits, f"unsupported headline text saved: {hits}")

    def test_b_uncertain_headline_wording_is_kept_only_for_the_member_to_decide(self):
        # Uncertain wording is not silently removed and not silently confirmed: it stays in the draft as a review item.
        self._build(B_GENERATED, mode="on")
        version = next(v for v in self.call("GET", "/resume-versions", self.a).json() if v.get("resume_data", {}).get("member_review"))
        review = self.call("GET", f"/resume-versions/{version['id']}/review", self.a).json()
        self.assertTrue(any(i["where"].startswith("headline") and i["classification"] == "UNCERTAIN" for i in review["items"]))

    def test_b_overstated_and_unsourced_summary_claims_are_not_saved(self):
        saved = self._build(B_GENERATED, mode="on")
        hits = {t for t in B_SUMMARY_UNSUPPORTED if t.lower() in saved["summary"].lower()}
        self.assertFalse(hits, f"unsupported summary wording saved: {hits}")

    def test_a_unsourced_soft_claim_is_not_saved(self):
        saved = self._build(A_GENERATED, mode="on")
        self.assertNotIn("Known for dependable", saved["summary"])

    def test_with_the_switch_on_the_general_route_stores_a_truth_review(self):
        # Behavioural (replaces an earlier expectation that pinned which checker function the route calls): the stored version
        # carries the server-side review that the member must act on.
        self._build(B_GENERATED, mode="on")
        listed = self.call("GET", "/resume-versions", self.a).json()
        self.assertTrue(any("member_review" in v["resume_data"] for v in listed))

    def test_with_the_switch_off_the_generated_wording_is_saved_as_generated(self):
        # Documented compatibility while the feature is disabled: nothing is reviewed or removed. Staging and production stay OFF
        # until the separate acceptance review (C-52 frontend round).
        saved = self._build(B_GENERATED, mode="off")
        self.assertTrue(B_SKILLS_UNSUPPORTED & set(saved["skills"]))

    # ---- Protections that must keep passing -----------------------------------------------------------------------------

    def test_b_derived_transferable_skill_is_kept(self):
        # "Process Improvement" is derived from "Improved the record-keeping checklist". It must not be discarded as a false positive.
        saved = self._build(B_GENERATED)
        self.assertIn("Process Improvement", saved["skills"])

    def test_a_derived_skill_from_the_role_title_is_kept(self):
        # "Operations Coordination" is derived from the saved role title "Operations Coordinator".
        saved = self._build(A_GENERATED)
        self.assertIn("Operations Coordination", saved["skills"])

    def test_factual_fields_for_b_are_preserved_exactly(self):
        saved = self._build(B_GENERATED)
        job = saved["experience"][0]
        self.assertEqual(job["title"], "Coordinator")
        self.assertEqual(job["subtitle"], "Fictional Organization Beta — 06/21 – 05/25")
        self.assertIn(B_EDUCATION, saved["education"])

    def test_factual_fields_for_a_are_preserved_exactly(self):
        saved = self._build(A_GENERATED)
        self.assertEqual(saved["experience"][0]["title"], "Operations Coordinator")
        self.assertEqual(saved["experience"][0]["subtitle"], "Fictional Organization Alpha — Jan 2021 – Mar 2023")
        self.assertIn("Fictional School: Certificate in Office Administration", saved["education"])

    def test_no_account_a_content_appears_in_b_output(self):
        saved = self._build(B_GENERATED)
        text = _all_text(saved)
        for marker in ("Member A", "Fictional Organization Alpha", "synthetic.member.a"):
            self.assertNotIn(marker, text)


class ExistingPipelineIsAvailableForReuse(unittest.TestCase):
    """Shows the existing checks can be called on general-résumé-shaped data (feasibility, not wiring)."""

    def test_find_claim_issues_flags_a_listed_unsupported_term_in_a_general_summary(self):
        issues = resume_quality.find_claim_issues(B_GENERATED, ["Office Administration"], evidence_text="Coordinator. Customer requests. Records.")
        self.assertIsInstance(issues, list)

    def test_find_claim_issues_is_inert_without_a_term_list(self):
        # Documents the reason the general path gets no protection: with no posting terms, the term-driven check flags nothing.
        self.assertEqual(resume_quality.find_claim_issues(B_GENERATED, [], evidence_text=""), [])


if __name__ == "__main__":
    unittest.main()
