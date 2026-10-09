"""Size limits on data in requests (risk-audit finding F-03): real use passes, absurd sizes are refused with a normal 422."""
import unittest

from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

import main
from career.routes import ApplicationIn, CertificationIn, EducationIn, ExperienceIn, JobBuildResumeRequest, LanguageIn, SkillIn
from limits import MAX_ITEMS, MAX_STRUCTURE_CHARS, BoundedDict, BoundedDictList, BoundedList, Long, Short, Tiny
from tests.test_resume_templates import SAMPLE


class Holder(BaseModel):
    d: BoundedDict = {}
    l: BoundedList = []
    dl: BoundedDictList = []
    short: Short = ""
    tiny: Tiny = ""
    long: Long = ""


class BoundedTypesTests(unittest.TestCase):
    def test_normal_data_passes(self):
        Holder(d={"name": "Ada", "experience": [{"title": "x" * 500}] * 20}, l=["q"] * 200, dl=[{"a": 1}] * 100)

    def test_a_structure_over_the_size_cap_is_refused(self):
        with self.assertRaises(ValidationError):
            Holder(d={"big": "x" * (MAX_STRUCTURE_CHARS + 1)})
        with self.assertRaises(ValidationError):
            Holder(dl=[{"big": "x" * 1000}] * 500 + [{"big": "x" * MAX_STRUCTURE_CHARS}])

    def test_a_list_with_too_many_items_is_refused(self):
        Holder(l=[1] * MAX_ITEMS)
        with self.assertRaises(ValidationError):
            Holder(l=[1] * (MAX_ITEMS + 1))

    def test_text_caps(self):
        Holder(short="x" * 300, tiny="x" * 100, long="x" * 20000)
        for field, size in (("short", 301), ("tiny", 101), ("long", 20001)):
            with self.assertRaises(ValidationError, msg=field):
                Holder(**{field: "x" * size})


class ProfileFormsTests(unittest.TestCase):
    def test_real_entries_still_fit(self):
        ExperienceIn(title="Treasury Management Officer", organization="JPMorgan Chase", location="Chicago, IL", start_date="06/26", end_date="Present", description="Lead executive sessions.\n" * 400)
        EducationIn(institution="Illinois Institute of Technology", degree="M.S.", field_of_study="Applied Information Technology", graduation_date="In Progress, 2028")
        CertificationIn(name="Certified Treasury Professional (CTP)", issuer="AFP", date="In Progress")
        SkillIn(name="Treasury management", source_text="Used daily in my role.")
        ApplicationIn(job_title="Product Lead", company="Contoso", applied_on="2026-10-01", status="applied", notes="Referred by a friend.")
        LanguageIn(name="Spanish", proficiency="Fluent")
        JobBuildResumeRequest(job_description="x", name="Yovana", contact="Chicago, IL | 555-0100", confirmed_facts=[{"a": 1}], qa_history=[{"q": "a"}])

    def test_absurd_entries_are_refused(self):
        with self.assertRaises(ValidationError):
            ExperienceIn(title="x" * 301, organization="Acme")
        with self.assertRaises(ValidationError):
            ExperienceIn(title="Role", organization="Acme", description="x" * 20001)
        with self.assertRaises(ValidationError):
            SkillIn(name="x" * 301)
        with self.assertRaises(ValidationError):
            ApplicationIn(job_title="Role", notes="x" * 20001)


class RealRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_a_normal_resume_still_builds(self):
        res = self.client.post("/api/generate", json={"resume_data": SAMPLE})
        self.assertEqual(res.status_code, 200)

    def test_an_oversized_structure_is_a_422_that_names_the_field(self):
        res = self.client.post("/api/generate", json={"resume_data": dict(SAMPLE, notes="x" * (MAX_STRUCTURE_CHARS + 10))})
        self.assertEqual(res.status_code, 422)
        self.assertIn("resume_data", str(res.json()))

    def test_a_scratch_entry_with_an_enormous_description_is_refused_before_any_ai_call(self):
        res = self.client.post("/api/scratch-entry", json={"entry_type": "work", "title": "t", "organization": "o", "dates": "d", "description": "x" * 20001})
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
