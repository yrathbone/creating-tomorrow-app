"""C-52 Step B continuation: focused regression tests (written before the implementation changes, 2026-11-14).

Priority 1: headline and summary claims are never SUPPORTED on word overlap alone. Known Synthetic A/B examples.
Priority 2: approval, preview and sign-off do not hold database row locks while rendering; approval commits atomically and
refuses a stale snapshot; application records and approvals are serialised. Concurrency is exercised by deterministic
interleavings (test hooks between the snapshot and the commit phase), because the SQLite test database serialises writes.
Real concurrent PostgreSQL behaviour is NOT exercised here; it is reported as environment-blocked (see the report).

Run from the backend folder:  py -3.12 -m unittest tests.test_step_b_corrections -v
"""
import copy
import io
import os
import unittest
from unittest import mock

from docx import Document

import abuse_guard
from career import opportunities as opp
from career import review_gate as rg
from career import routes as career_routes
from career.resume_quality import SUPPORTED, UNCERTAIN, UNSUPPORTED, general_truth_findings
from tests.test_ownership import OwnershipTestCase, SUB_A, SUB_B

B_FACTS = {
    "roles": [{"id": 1, "title": "Coordinator", "organization": "Fictional Organization Beta", "years": [2021, 2025],
               "start": (2021, 6), "end": (2025, 5),
               "text": "Handled customer requests and kept records for a fictional office of eight. Improved the record-keeping checklist."}],
    "education": [{"id": 1, "school": "Fictional School B", "degree": "Certificate Customer Service", "text": ""}],
    "skills": ["Customer support", "Record keeping", "Calendar planning", "Written communication"],
}
A_FACTS = {
    "roles": [{"id": 1, "title": "Operations Coordinator", "organization": "Fictional Organization Alpha", "years": [2021, 2023],
               "start": (2021, 1), "end": (2023, 3),
               "text": "Coordinated scheduling and reporting for a fictional team of six. Maintained a shared tracker and reduced weekly report preparation time."}],
    "education": [{"id": 2, "school": "Fictional School", "degree": "Certificate in Office Administration", "text": ""}],
    "skills": ["Scheduling", "Reporting", "Spreadsheet tracking", "Written communication", "Teamwork"],
}


def _res(headline="", summary="", skills=None):
    return {"headline": headline, "summary": summary, "skills": skills or [], "experience": [], "education": []}


def _by(findings, where):
    return [f["classification"] for f in findings if f["where"] == where]


def _once_before(target, name, nth, fn):
    """Deterministic interleaving without any production hook: runs fn once, immediately before the nth call of
    target.name, then lets the real call proceed. Scoped to the with-block; nothing is registered in production code."""
    real = getattr(target, name)
    count = {"n": 0}

    def wrapper(*args, **kwargs):
        count["n"] += 1
        if count["n"] == nth:
            fn()
        return real(*args, **kwargs)
    return mock.patch.object(target, name, side_effect=wrapper)


class HeadlineAndSummaryNeverSupportedOnOverlap(unittest.TestCase):
    def test_a_headline_built_from_saved_words_is_uncertain_not_supported(self):
        for seg in ("Operations Coordination", "Scheduling & Reporting"):
            with self.subTest(seg=seg):
                f = general_truth_findings(_res(headline=seg), A_FACTS)
                self.assertEqual(_by(f, "headline[0]"), [UNCERTAIN])

    def test_a_partly_supported_headline_is_uncertain(self):
        self.assertEqual(_by(general_truth_findings(_res(headline="Team Support"), A_FACTS), "headline[0]"), [UNCERTAIN])

    def test_a_headline_naming_a_title_not_held_is_unsupported(self):
        self.assertEqual(_by(general_truth_findings(_res(headline="Customer Support Coordinator"), B_FACTS), "headline[0]"), [UNSUPPORTED])

    def test_b_records_and_office_operations_is_uncertain(self):
        self.assertEqual(_by(general_truth_findings(_res(headline="Records & Office Operations"), B_FACTS), "headline[0]"), [UNCERTAIN])

    def test_an_exact_held_title_is_supported(self):
        self.assertEqual(_by(general_truth_findings(_res(headline="Coordinator"), B_FACTS), "headline[0]"), [SUPPORTED])

    def test_an_exact_saved_skill_is_not_enough_for_a_headline(self):
        # F3 (Data 2026-11-15): a supported skill does not justify the same words as a headline; the member confirms it.
        f = general_truth_findings(_res(headline="Record keeping"), B_FACTS)
        self.assertEqual(_by(f, "headline[0]"), [UNCERTAIN])
        self.assertIn("headline states a professional title", next(x for x in f if x["where"] == "headline[0]")["explanation"])

    def test_a_summary_built_from_overlap_is_uncertain_never_supported(self):
        s = "Operations professional with experience coordinating scheduling and reporting for a team."
        f = general_truth_findings(_res(summary=s), A_FACTS)
        self.assertEqual(_by(f, "summary[0]"), [UNCERTAIN])

    def test_b_plausible_summary_sentence_is_uncertain(self):
        s = "Service-oriented coordinator with experience handling customer requests and maintaining records for a small office team."
        self.assertEqual(_by(general_truth_findings(_res(summary=s), B_FACTS), "summary[0]"), [UNCERTAIN])

    def test_an_exact_saved_sentence_in_a_summary_is_supported(self):
        s = "Handled customer requests and kept records for a fictional office of eight."
        self.assertEqual(_by(general_truth_findings(_res(summary=s), B_FACTS), "summary[0]"), [SUPPORTED])

    def test_an_exact_saved_credential_statement_is_supported(self):
        s = "Holds a Certificate in Office Administration."
        self.assertEqual(_by(general_truth_findings(_res(summary=s), A_FACTS), "summary[0]"), [SUPPORTED])

    def test_a_soft_claim_in_a_summary_stays_unsupported(self):
        s = "Known for dependable written communication."
        self.assertEqual(_by(general_truth_findings(_res(summary=s), A_FACTS), "summary[0]"), [UNSUPPORTED])

    def test_no_headline_or_summary_finding_carries_the_old_overlap_label(self):
        for res, facts in ((_res(headline="Operations Coordination | Scheduling & Reporting | Team Support",
                                summary="Coordinated scheduling and reporting for a team. Known for dependable teamwork."), A_FACTS),
                           (_res(headline="Records & Office Operations", summary="Handled customer requests and maintained records."), B_FACTS)):
            for f in general_truth_findings(res, facts):
                if f["where"].startswith(("headline", "summary")) and f["classification"] == SUPPORTED:
                    self.assertNotEqual(f["source"], "saved career data")

    def test_skills_and_bullets_keep_their_step_a_behaviour(self):
        facts = copy.deepcopy(B_FACTS)
        facts["roles"][0]["text"] += " Improved the record-keeping checklist."
        res = {"headline": "", "summary": "", "skills": ["Process Improvement"], "experience": [], "education": []}
        self.assertEqual(_by(general_truth_findings(res, facts), "skills[0]"), ["DERIVED"])


class RouteRegressions(OwnershipTestCase):
    """Priority 2 scenarios, driven through the real routes with deterministic interleavings."""

    def setUp(self):
        super().setUp()
        from career.opportunities import router as opportunities_router
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
            mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": f"{SUB_A},{SUB_B}"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.app.include_router(opportunities_router, prefix="/api/career")
        abuse_guard.IN_FLIGHT.reset()

    CONTENT = {"name": "SYNTHETIC Member B", "contact": "SYNTHETIC | synthetic.member.b@example.com",
               "headline": "Coordinator", "summary": "Handled customer requests and kept records for a fictional office of eight.",
               "skills": ["Record Keeping"], "experience": [{"title": "Coordinator", "subtitle": "Fictional Organization Beta — 06/21 – 05/25",
                                                             "bullets": ["Improved the record-keeping checklist."]}],
               "education": ["Fictional School B: Certificate, Customer Service"], "certifications": [], "skills_style": "grouped"}

    def _seed(self):
        self.onboard(self.a)
        self.assertEqual(self.call("POST", "/experiences", self.a, json={"title": "Coordinator", "organization": "Fictional Organization Beta",
                                                                          "description": "Handled customer requests and kept records for a fictional office of eight. Improved the record-keeping checklist.",
                                                                          "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        self.assertEqual(self.call("POST", "/skills", self.a, json={"name": "Record keeping"}).status_code, 200)
        self.assertEqual(self.call("POST", "/education", self.a, json={"institution": "Fictional School B", "degree": "Certificate",
                                                                        "field_of_study": "Customer Service"}).status_code, 200)

    def _version(self, mode="off", content=None):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}), \
                mock.patch("career.routes.build_general_resume", return_value={"resume_data": copy.deepcopy(content or self.CONTENT)}):
            res = self.call("POST", "/build-general-resume", self.a, json={"name": "SYNTHETIC Member B",
                                                                           "contact": "SYNTHETIC | synthetic.member.b@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["resume_version_id"]

    def _link(self, url="https://jobs.example-employer.com/postings/1001"):
        res = self.call("POST", "/opportunities", self.a, json={"title": "Analyst", "employer": "Sample Employer", "job_url": url,
                                                                "location_text": "Chicago, IL", "work_arrangement": "hybrid", "employment_type": "full_time"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["id"]

    def _approve(self, oid, vid, mode="off"):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}):
            return self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid})

    def _doc_bytes(self, oid):
        res = self.call("GET", f"/opportunities/{oid}/approved-document", self.a)
        return res.content if res.status_code == 200 else None

    def _state(self, oid):
        rows = self.call("GET", "/opportunities", self.a).json()
        row = next(r for r in rows if r["id"] == oid)
        approval = row.get("approval") or {}
        return {"approved_resume_version_id": approval.get("version_id"), "status": approval.get("status"), "raw": row}

    # ---- Priority 2: approval snapshot, stale rejection, atomic commit ------------------------------------------------------
    def test_a_saved_fact_change_between_snapshot_and_commit_refuses_the_approval(self):
        self._seed()
        vid = self._version("on")
        oid = self._link()
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            preview = self.call("GET", f"/resume-versions/{vid}/preview", self.a).json()
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.a,
                                       json={"finalized_hash": preview["finalized_hash"]}).status_code, 200)
        exp = self.call("GET", "/experiences", self.a).json()[0]

        def change_fact():
            self.assertEqual(self.call("PUT", f"/experiences/{exp['id']}", self.a, json={
                "title": "Coordinator", "organization": "Fictional Organization Beta", "description": "Changed after the snapshot.",
                "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}), _once_before(opp, "_commit_approval", 1, change_fact):
            res = self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid})
        self.assertEqual(res.status_code, 409, res.text)
        self.assertIn("changed", res.text.lower())
        self.assertIsNone(self._state(oid).get("approved_resume_version_id"))
        self.assertIsNone(self._doc_bytes(oid))

    def test_an_application_recorded_between_snapshot_and_commit_refuses_an_approval_change(self):
        self._seed()
        v1 = self._version("off")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        v2 = self._version("off", content=dict(self.CONTENT, headline="Coordinator (updated)"))
        before = self._doc_bytes(oid)

        def record():
            res = self.call("POST", f"/opportunities/{oid}/record-application", self.a, json={})
            self.assertEqual(res.status_code, 200, res.text)
        with _once_before(opp, "_commit_approval", 1, record):
            res = self._approve(oid, v2)
        self.assertEqual(res.status_code, 409, res.text)
        self.assertEqual(self._state(oid).get("approved_resume_version_id"), v1)
        self.assertEqual(self._doc_bytes(oid), before)                       # the recorded application's document is unchanged

    def test_a_failed_commit_leaves_the_previous_approval_and_document_untouched(self):
        self._seed()
        v1 = self._version("off")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        v2 = self._version("off", content=dict(self.CONTENT, headline="Coordinator (second)"))
        before = self._doc_bytes(oid)

        def fail():
            raise RuntimeError("simulated failure before commit")
        with _once_before(opp, "_approval_token", 2, fail), self.assertRaises(RuntimeError):   # 2nd call = inside the commit phase
            self._approve(oid, v2)
        self.assertEqual(self._state(oid).get("approved_resume_version_id"), v1)
        self.assertEqual(self._doc_bytes(oid), before)

    def test_rendering_happens_before_the_commit_phase_and_not_inside_it(self):
        self._seed()
        vid = self._version("off")
        oid = self._link()
        events = []
        real = opp.build_resume_bytes

        def recording_render(*a, **k):
            events.append("render")
            return real(*a, **k)
        with mock.patch.object(opp, "build_resume_bytes", side_effect=recording_render), \
                _once_before(opp, "_commit_approval", 1, lambda: events.append("between")), \
                _once_before(opp, "_approval_token", 2, lambda: events.append("commit")):
            self.assertEqual(self._approve(oid, vid).status_code, 200)
        self.assertEqual(events, ["render", "between", "commit"])

    def test_a_repeated_approval_of_the_same_version_changes_nothing(self):
        self._seed()
        vid = self._version("off")
        oid = self._link()
        self.assertEqual(self._approve(oid, vid).status_code, 200)
        before = self._doc_bytes(oid)
        self.assertEqual(self._approve(oid, vid).status_code, 200)
        self.assertEqual(self._doc_bytes(oid), before)

    def test_a_claim_decision_changed_between_snapshot_and_commit_refuses_the_gated_approval(self):
        self._seed()
        vid = self._version("on", content=dict(self.CONTENT, headline="Coordinator | Record keeping plus Calendar planning"))
        oid = self._link()
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            review = self.call("GET", f"/resume-versions/{vid}/review", self.a).json()
            uncertain = [i for i in review["items"] if i["classification"] == UNCERTAIN]
            for item in uncertain:
                self.assertEqual(self.call("POST", f"/resume-versions/{vid}/decisions", self.a,
                                           json={"item_id": item["id"], "decision": "keep", "acknowledge": True}).status_code, 200)
            preview = self.call("GET", f"/resume-versions/{vid}/preview", self.a).json()
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.a,
                                       json={"finalized_hash": preview["finalized_hash"]}).status_code, 200)
            target = uncertain[0]

            def change_decision():
                self.assertEqual(self.call("POST", f"/resume-versions/{vid}/decisions", self.a,
                                           json={"item_id": target["id"], "decision": "remove"}).status_code, 200)
            with _once_before(opp, "_commit_approval", 1, change_decision):
                res = self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid})
        self.assertEqual(res.status_code, 409, res.text)
        self.assertIsNone(self._state(oid).get("approved_resume_version_id"))

    def test_a_preview_refuses_when_saved_facts_change_before_it_is_recorded(self):
        self._seed()
        vid = self._version("on", content=dict(self.CONTENT, headline="Coordinator | Record keeping plus Calendar planning"))
        exp = self.call("GET", "/experiences", self.a).json()[0]

        def change_fact():
            self.assertEqual(self.call("PUT", f"/experiences/{exp['id']}", self.a, json={
                "title": "Coordinator", "organization": "Fictional Organization Beta", "description": "Changed before the receipt.",
                "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}), _once_before(career_routes, "_review_state", 2, change_fact):
            res = self.call("GET", f"/resume-versions/{vid}/preview", self.a)   # 2nd call = the locked phase
        self.assertEqual(res.status_code, 409, res.text)

    # ---- Data REVISE: approval races for clear and no-op requests, and the switch -------------------------------------------
    def test_a_clear_never_erases_an_approval_made_after_it_was_prepared(self):
        self._seed()
        v1 = self._version("off")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        v2 = self._version("off", content=dict(self.CONTENT, headline="Coordinator (newer)"))
        captured = {}

        def concurrent_approval():
            self.assertEqual(self._approve(oid, v2).status_code, 200)
            captured["doc"] = self._doc_bytes(oid)
        with _once_before(opp, "_commit_approval", 1, concurrent_approval):
            res = self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": None})
        self.assertEqual(res.status_code, 409, res.text)
        self.assertEqual(self._state(oid).get("approved_resume_version_id"), v2)
        self.assertEqual(self._doc_bytes(oid), captured["doc"])

    def test_a_no_op_never_reports_an_approval_that_changed_after_it_was_decided(self):
        self._seed()
        v1 = self._version("off")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        v2 = self._version("off", content=dict(self.CONTENT, headline="Coordinator (newer)"))

        def concurrent_approval():
            self.assertEqual(self._approve(oid, v2).status_code, 200)
        with _once_before(opp, "_commit_approval", 1, concurrent_approval):
            res = self._approve(oid, v1)                 # decided as a no-op against v1
        self.assertEqual(res.status_code, 409, res.text)
        self.assertEqual(self._state(oid).get("approved_resume_version_id"), v2)

    def test_a_clear_without_a_concurrent_change_still_clears(self):
        self._seed()
        v1 = self._version("off")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        res = self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": None})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(self._state(oid).get("approved_resume_version_id"))
        self.assertIsNone(self._doc_bytes(oid))

    def test_off_and_shadow_approvals_snapshot_the_content_without_review_keys(self):
        self._seed()
        vid = self._version("shadow")
        oid = self._link()
        seen = []
        real = opp.build_resume_bytes

        def capture(data, *a, **k):
            seen.append(dict(data))
            return real(data, *a, **k)
        with mock.patch.object(opp, "build_resume_bytes", side_effect=capture):
            self.assertEqual(self._approve(oid, vid, mode="shadow").status_code, 200)
        self.assertTrue(seen)
        self.assertNotIn("truth_review", seen[0])
        self.assertNotIn("final_signoff", seen[0])

    def test_switch_off_and_shadow_refuse_the_member_review_steps_and_never_gate_them(self):
        self._seed()
        vid = self._version("shadow")
        for mode in ("shadow", "off"):
            with self.subTest(mode=mode), mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}):
                self.assertEqual(self.call("POST", f"/resume-versions/{vid}/decisions", self.a,
                                           json={"item_id": "x", "decision": "keep", "acknowledge": True}).status_code, 409)
                self.assertEqual(self.call("GET", f"/resume-versions/{vid}/preview", self.a).status_code, 409)
                self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.a,
                                           json={"finalized_hash": "f" * 64}).status_code, 409)
                self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 409)

    def test_ownership_is_enforced_before_the_switch_in_every_mode(self):
        self._seed()
        vid = self._version("shadow")
        self.onboard(self.b)
        for mode in ("off", "shadow", "on"):
            with self.subTest(mode=mode), mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}):
                self.assertEqual(self.call("GET", f"/resume-versions/{vid}/review", self.b).status_code, 404)
                self.assertEqual(self.call("GET", f"/resume-versions/{vid}/preview", self.b).status_code, 404)
                self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.b,
                                           json={"finalized_hash": "f" * 64}).status_code, 404)
                self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.b).status_code, 404)


if __name__ == "__main__":
    unittest.main()
