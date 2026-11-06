"""Priority 1, PR 6: editable suggestions. A supported posting term that could not be placed on the resume gets the candidate's OWN saved
sentence as a suggested bullet under its role; the candidate edits it and adds it to this resume version only, and can undo it. No AI.
Fictional data.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import copy
import os
import unittest
from unittest import mock

import abuse_guard
from career import suggestions
from models import ResumeVersion
from tests.test_ownership import SUB_A, OwnershipTestCase

EXPERIENCES = [
    {"title": "Shift Lead", "organization": "Hearthside Home Goods",
     "description": "- Handled returns and customer complaints, about 20 a week\n- Trained new hires on the POS system\n- Scheduled 6 associates each week"},
    {"title": "Call Centre Agent", "organization": "Brightline Direct", "description": "- Took inbound customer orders by phone"},
]
RESUME = {
    "name": "Marcus Bell", "contact": "Naperville, IL | m@example.com", "headline": "", "summary": "Shift lead.",
    "skills": ["De-escalation"], "education": [], "certifications": [],
    "experience": [
        {"title": "Shift Lead", "subtitle": "Hearthside Home Goods, Naperville, IL | 2021 - Present", "bullets": ["Scheduled 6 associates each week."]},
    ],
    "term_report": [
        {"term": "Complaint resolution", "kind": "skill", "importance": "required", "support": "related",
         "evidence": "Shift Lead: handled returns and customer complaints", "status": "not_placed"},
        {"term": "Customer onboarding", "kind": "skill", "importance": "required", "support": "transferable",
         "evidence": "Trained new hires", "status": "transferable"},
        {"term": "Salesforce", "kind": "skill", "importance": "required", "support": "none", "evidence": "", "status": "not_in_profile"},
    ],
}
EVIDENCE = "EXPERIENCE:\n- Shift Lead at Hearthside Home Goods\n  * Handled returns and customer complaints, about 20 a week\n  * Scheduled 6 associates each week"


class A_FindingSuggestions(unittest.TestCase):
    def find(self, resume=RESUME, experiences=EXPERIENCES):
        return suggestions.find_suggestions(resume, resume["term_report"], experiences)

    def test_a_supported_unplaced_term_gets_the_candidates_own_sentence_under_its_role(self):
        out = self.find()
        self.assertEqual(len(out), 1)
        s = out[0]
        self.assertEqual((s["term"], s["role"], s["experience_index"]), ("Complaint resolution", "Shift Lead", 0))
        self.assertEqual(s["suggested_text"], "Handled returns and customer complaints, about 20 a week.")
        self.assertEqual(s["before_bullets"], ["Scheduled 6 associates each week."])

    def test_the_suggestion_is_a_sentence_from_the_saved_role_never_invented(self):
        s = self.find()[0]
        self.assertIn(s["source_sentence"].rstrip(".").lower(), EXPERIENCES[0]["description"].lower())

    def test_a_different_activity_unsupported_and_phrase_terms_get_no_suggestion(self):
        out = self.find()
        self.assertNotIn("Customer onboarding", [s["term"] for s in out])  # transferable: a different activity
        self.assertNotIn("Salesforce", [s["term"] for s in out])
        report = [{**RESUME["term_report"][0], "kind": "phrase"}]
        self.assertEqual(suggestions.find_suggestions(RESUME, report, EXPERIENCES), [])

    def test_a_role_the_resume_left_off_is_not_brought_back(self):
        only_other_role = [EXPERIENCES[1]]
        self.assertEqual(self.find(experiences=only_other_role), [])

    def test_a_sentence_already_on_the_resume_is_not_offered(self):
        resume = copy.deepcopy(RESUME)
        resume["experience"][0]["bullets"].append("Handled returns and customer complaints, about 20 a week.")
        self.assertEqual(self.find(resume), [])

    def test_a_related_term_needs_real_overlap_with_its_evidence_note(self):
        resume = copy.deepcopy(RESUME)
        resume["term_report"][0]["evidence"] = "Something about vendors"
        self.assertEqual(self.find(resume), [])

    def test_a_term_literally_in_a_saved_sentence_matches_that_sentence(self):
        resume = copy.deepcopy(RESUME)
        resume["term_report"] = [{"term": "POS system", "kind": "skill", "importance": "preferred", "support": "literal", "evidence": "", "status": "not_placed"}]
        self.assertEqual(self.find(resume)[0]["suggested_text"], "Trained new hires on the POS system.")


class B_ApplyingAndUndoing(unittest.TestCase):
    CHOICE = {"term": "Complaint resolution", "experience_index": 0, "text": "Handled returns and customer complaints, about 20 a week."}

    def test_the_chosen_bullet_is_added_and_the_input_is_not_modified(self):
        before = copy.deepcopy(RESUME)
        out = suggestions.apply_suggestions(RESUME, [self.CHOICE], EVIDENCE)
        self.assertEqual(RESUME, before)
        self.assertEqual(out["experience"][0]["bullets"][-1], self.CHOICE["text"])
        self.assertEqual(out["applied_suggestions"][0]["previous_status"], "not_placed")

    def test_the_term_status_follows_what_is_really_on_the_resume(self):
        out = suggestions.apply_suggestions(RESUME, [{**self.CHOICE, "text": "Handled complaint resolution calls for returns."}], EVIDENCE.replace("Handled", "Handled complaint resolution calls for returns. Handled", 1))
        status = {r["term"]: r["status"] for r in out["term_report"]}
        self.assertEqual(status["Complaint resolution"], "on_resume")
        out2 = suggestions.apply_suggestions(RESUME, [self.CHOICE], EVIDENCE)
        self.assertEqual({r["term"]: r["status"] for r in out2["term_report"]}["Complaint resolution"], "not_placed")  # the words are not in the bullet

    def test_an_edited_bullet_with_an_invented_figure_is_refused(self):
        with self.assertRaisesRegex(ValueError, "number or amount"):
            suggestions.apply_suggestions(RESUME, [{**self.CHOICE, "text": "Handled returns and complaints worth 90 thousand dollars."}], EVIDENCE)

    def test_a_figure_from_the_candidates_own_evidence_is_allowed(self):
        suggestions.apply_suggestions(RESUME, [{**self.CHOICE, "text": "Handled about 20 customer complaints a week."}], EVIDENCE)

    def test_bad_choices_are_refused_with_a_plain_message(self):
        for bad, message in (({**self.CHOICE, "experience_index": 5}, "no longer on this resume"), ({**self.CHOICE, "text": "Handled."}, "between 3"),
                             ({**self.CHOICE, "text": "word " * 41}, "between 3"), ({**self.CHOICE, "text": "Scheduled 6 associates each week"}, "already on")):
            with self.assertRaisesRegex(ValueError, message):
                suggestions.apply_suggestions(RESUME, [bad], EVIDENCE)
        with self.assertRaisesRegex(ValueError, "at least one"):
            suggestions.apply_suggestions(RESUME, [], EVIDENCE)

    def test_undo_restores_the_resume_exactly(self):
        added = suggestions.apply_suggestions(RESUME, [self.CHOICE], EVIDENCE)
        undone = suggestions.undo_suggestions(added)
        self.assertEqual(undone["experience"], RESUME["experience"])
        self.assertEqual(undone["term_report"], RESUME["term_report"])
        self.assertEqual(undone["applied_suggestions"], [])


class C_Routes(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
                        mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter())):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()
        self.onboard(self.a)
        e = EXPERIENCES[0]
        self.call("POST", "/experiences", self.a, json={"title": e["title"], "organization": e["organization"], "description": e["description"]})
        with self.Session() as s:
            v = ResumeVersion(career_profile_id=self.profile_id_for(SUB_A), resume_data=copy.deepcopy(RESUME))
            s.add(v)
            s.commit()
            self.version_id = v.id

    def url(self, tail=""):
        return f"/resume-versions/{self.version_id}/suggestions{tail}"

    def test_list_returns_the_suggestion_and_makes_no_change(self):
        res = self.call("GET", self.url(), self.a)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual([s["term"] for s in res.json()["suggestions"]], ["Complaint resolution"])
        with self.Session() as s:
            self.assertEqual(s.get(ResumeVersion, self.version_id).resume_data, RESUME)

    def test_apply_saves_to_this_version_and_undo_restores_it(self):
        choice = {"term": "Complaint resolution", "experience_index": 0, "text": "Handled returns and customer complaints, about 20 a week."}
        res = self.call("POST", self.url("/apply"), self.a, json={"choices": [choice]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn(choice["text"], res.json()["resume_data"]["experience"][0]["bullets"])
        saved = self.call("GET", "/resume-versions", self.a).json()[0]["resume_data"]
        self.assertIn(choice["text"], saved["experience"][0]["bullets"])
        again = self.call("GET", self.url(), self.a).json()
        self.assertEqual(again["suggestions"], [])  # no longer offered once it is on the resume
        self.assertEqual(len(again["applied"]), 1)
        undone = self.call("POST", self.url("/undo"), self.a)
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["resume_data"]["experience"], RESUME["experience"])

    def test_a_bullet_with_an_invented_figure_is_refused_and_nothing_is_saved(self):
        bad = {"term": "Complaint resolution", "experience_index": 0, "text": "Handled returns and complaints worth 90 thousand dollars."}
        res = self.call("POST", self.url("/apply"), self.a, json={"choices": [bad]})
        self.assertEqual(res.status_code, 400, res.text)
        with self.Session() as s:
            self.assertEqual(s.get(ResumeVersion, self.version_id).resume_data, RESUME)

    def test_another_persons_resume_is_not_found_for_every_route(self):
        self.onboard(self.b)
        choice = {"term": "Complaint resolution", "experience_index": 0, "text": "Handled returns and customer complaints, about 20 a week."}
        self.assertEqual(self.call("GET", self.url(), self.b).status_code, 404)
        self.assertEqual(self.call("POST", self.url("/apply"), self.b, json={"choices": [choice]}).status_code, 404)
        self.assertEqual(self.call("POST", self.url("/undo"), self.b).status_code, 404)

    def test_too_many_choices_are_refused(self):
        choice = {"term": "t", "experience_index": 0, "text": "Handled returns and customer complaints, about 20 a week."}
        res = self.call("POST", self.url("/apply"), self.a, json={"choices": [choice] * 11})
        self.assertEqual(res.status_code, 422, res.text)


if __name__ == "__main__":
    unittest.main()
