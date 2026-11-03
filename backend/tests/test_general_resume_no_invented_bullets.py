"""The general resume must not carry bullets for a role the candidate gave no description (or skills) for.

Found in the Checkpoint B run (2026-11-03): a fictional "Summer Camp Counselor" role with no description came back with two
duty bullets the profile never contained. Plain code now empties such roles; the prompt also says so.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import io
import os
import unittest
from unittest import mock

from docx import Document

import abuse_guard
import resume_builder as rb
from career.job_match import GENERAL_RESUME_SYSTEM_PROMPT
from career.resume_quality import drop_unsourced_bullets
from tests.test_ownership import OwnershipTestCase

SOURCES = [
    {"title": "Science Teacher", "organization": "Fox Valley Middle School", "has_source": True},
    {"title": "Summer Camp Counselor", "organization": "Riverbend Outdoor Camp", "has_source": False},
]
RESUME = {
    "name": "N", "contact": "c", "summary": "", "skills": [], "education": [],
    "experience": [
        {"title": "Science Teacher", "subtitle": "Fox Valley Middle School — 2014 – 2025", "bullets": ["Taught five sections a day."]},
        {"title": "Summer Camp Counselor", "subtitle": "Riverbend Outdoor Camp — 2010 – 2013", "bullets": ["Supervised campers.", "Kept camp safe."]},
    ],
}


class DropUnsourcedBullets(unittest.TestCase):
    def test_a_role_with_no_source_text_loses_its_bullets_and_keeps_its_heading(self):
        out, emptied = drop_unsourced_bullets(RESUME, SOURCES)
        camp = out["experience"][1]
        self.assertEqual(camp["bullets"], [])
        self.assertEqual((camp["title"], camp["subtitle"]), ("Summer Camp Counselor", "Riverbend Outdoor Camp — 2010 – 2013"))
        self.assertEqual(emptied, ["Summer Camp Counselor"])

    def test_a_role_with_source_text_keeps_its_bullets(self):
        out, _ = drop_unsourced_bullets(RESUME, SOURCES)
        self.assertEqual(out["experience"][0]["bullets"], ["Taught five sections a day."])

    def test_the_input_resume_is_not_changed(self):
        drop_unsourced_bullets(RESUME, SOURCES)
        self.assertEqual(len(RESUME["experience"][1]["bullets"]), 2)

    def test_a_role_that_matches_no_profile_role_is_left_alone(self):
        out, emptied = drop_unsourced_bullets(RESUME, [])
        self.assertEqual(out, RESUME)
        self.assertEqual(emptied, [])

    def test_matching_ignores_case_and_needs_the_organization_in_the_subtitle(self):
        sources = [{"title": "SUMMER CAMP COUNSELOR", "organization": "riverbend outdoor camp", "has_source": False}]
        self.assertEqual(drop_unsourced_bullets(RESUME, sources)[1], ["Summer Camp Counselor"])
        other_org = [{"title": "Summer Camp Counselor", "organization": "Some Other Camp", "has_source": False}]
        self.assertEqual(drop_unsourced_bullets(RESUME, other_org)[1], [])

    def test_two_roles_with_one_title_keep_bullets_if_either_has_source(self):
        sources = [dict(SOURCES[1], has_source=True), dict(SOURCES[1], has_source=False)]
        self.assertEqual(drop_unsourced_bullets(RESUME, sources)[1], [])

    def test_the_prompt_tells_the_ai_not_to_write_bullets_for_such_a_role(self):
        self.assertIn("EMPTY bullets list", GENERAL_RESUME_SYSTEM_PROMPT)

    def test_a_role_with_no_bullets_still_builds_a_document_in_every_layout(self):
        out, _ = drop_unsourced_bullets(RESUME, SOURCES)
        for template in ("classic", "modern", "traditional"):
            with self.subTest(template=template):
                text = "\n".join(p.text for p in Document(io.BytesIO(rb.build_resume_bytes(out, ats_mode=False, template=template))).paragraphs)
                self.assertIn("Summer Camp Counselor", text)
                self.assertNotIn("Supervised campers", text)


class GeneralResumeRoute(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()

    def add_role(self, title, org, description=""):
        res = self.call("POST", "/experiences", self.a, json={"title": title, "organization": org, "description": description})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def build(self):
        with mock.patch("career.routes.build_general_resume", return_value={"resume_data": {k: (list(v) if isinstance(v, list) else v) for k, v in RESUME.items()}}):
            res = self.call("POST", "/build-general-resume", self.a, json={"name": "N", "contact": "c@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["resume_data"]["experience"]

    def test_the_saved_resume_has_no_bullets_for_a_role_without_a_description(self):
        self.onboard(self.a)
        self.add_role("Science Teacher", "Fox Valley Middle School", "Taught five sections a day.")
        self.add_role("Summer Camp Counselor", "Riverbend Outdoor Camp")
        jobs = {j["title"]: j["bullets"] for j in self.build()}
        self.assertEqual(jobs["Summer Camp Counselor"], [])
        self.assertEqual(jobs["Science Teacher"], ["Taught five sections a day."])

    def test_a_skill_tied_to_the_role_counts_as_source_text(self):
        self.onboard(self.a)
        self.add_role("Science Teacher", "Fox Valley Middle School", "Taught five sections a day.")
        camp = self.add_role("Summer Camp Counselor", "Riverbend Outdoor Camp")
        res = self.call("POST", "/skills", self.a, json={"name": "Group leadership", "experience_id": camp["id"]})
        self.assertEqual(res.status_code, 200, res.text)
        jobs = {j["title"]: j["bullets"] for j in self.build()}
        self.assertEqual(len(jobs["Summer Camp Counselor"]), 2)  # the candidate gave something to write from


if __name__ == "__main__":
    unittest.main()
