"""C-52 Data round 3: saved certifications are server-side evidence.

Genuine saved certifications are SUPPORTED. Fabricated names, credential types, issuers or dates are UNSUPPORTED (never UNCERTAIN, so no
decision can confirm them). Certification changes change the facts hash, so earlier reviews and sign-offs go stale. Employment,
education and skill behaviour is unchanged (the Step A checker tests still pass).

Run from the backend folder:  py -3.12 -m unittest tests.test_general_certifications -v
"""
import copy
import os
import unittest
from unittest import mock

import abuse_guard
from career import opportunities as opp
from career import review_gate as rg
from career.resume_quality import SUPPORTED, UNSUPPORTED, general_truth_findings
from tests.test_ownership import OwnershipTestCase, SUB_A, SUB_B

CERT = {"id": 1, "name": "Certified Customer Service Specialist", "issuer": "Acme Institute", "date": "06/23"}
FACTS = {"roles": [], "education": [], "skills": [], "certifications": [CERT]}
NO_FACTS = {"roles": [], "education": [], "skills": []}


def _res(certs=None, summary=""):
    return {"headline": "", "summary": summary, "skills": [], "experience": [], "education": [], "certifications": list(certs or [])}


def _cert_findings(certs, facts=FACTS):
    return [f for f in general_truth_findings(_res(certs), facts) if f["where"].startswith("certifications")]


class GenuineAndFabricatedCertifications(unittest.TestCase):
    def test_a_genuine_saved_certification_is_supported(self):
        f = _cert_findings(["Certified Customer Service Specialist, Acme Institute, 2023"])
        self.assertEqual([x["classification"] for x in f], [SUPPORTED])
        self.assertEqual(f[0]["source"], 'certification "Certified Customer Service Specialist"')

    def test_the_complete_saved_name_with_no_other_details_is_supported(self):
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Customer Service Specialist"])], [SUPPORTED])

    def test_formatting_differences_do_not_change_a_complete_match(self):
        for line in ("certified customer service specialist", "CERTIFIED  CUSTOMER SERVICE SPECIALIST.",
                     "Certified Customer Service Specialist (Acme Institute, 2023)", "Acme Institute, Certified Customer Service Specialist"):
            with self.subTest(line=line):
                self.assertEqual([x["classification"] for x in _cert_findings([line])], [SUPPORTED])

    def test_a_shortened_name_is_not_supported_reproduced_from_data(self):
        # Data reproduced both of these as SUPPORTED before the correction.
        self.assertEqual([x["classification"] for x in _cert_findings(["Customer Service"])], [UNSUPPORTED])
        self.assertEqual([x["classification"] for x in _cert_findings(["Specialist"])], [UNSUPPORTED])

    def test_any_strict_part_of_the_saved_name_is_unsupported(self):
        for line in ("Certified Customer Service", "Customer Service Specialist", "Certified Specialist", "Service Specialist"):
            with self.subTest(line=line):
                self.assertEqual([x["classification"] for x in _cert_findings([line])], [UNSUPPORTED])

    def test_an_added_word_after_the_saved_name_is_unsupported(self):
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Customer Service Specialist Certificate"])],
                         [UNSUPPORTED])

    def test_a_year_on_a_certification_with_no_saved_date_is_unsupported(self):
        facts = {"roles": [], "education": [], "skills": [],
                 "certifications": [{"id": 2, "name": "Certified Data Analyst", "issuer": "", "date": ""}]}
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Data Analyst, 2023"], facts)], [UNSUPPORTED])

    def test_the_saved_issuer_stated_alone_is_supported_and_another_issuer_is_not(self):
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Customer Service Specialist, Acme Institute"])],
                         [SUPPORTED])
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Customer Service Specialist, Acme Institute Plus"])],
                         [UNSUPPORTED])

    def test_a_certification_never_saved_is_unsupported(self):
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Data Analyst"])], [UNSUPPORTED])

    def test_a_different_issuer_on_a_saved_certification_is_unsupported(self):
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Customer Service Specialist, Beta Institute"])],
                         [UNSUPPORTED])

    def test_a_different_credential_type_is_unsupported(self):
        self.assertEqual([x["classification"] for x in _cert_findings(["Certificate Customer Service Specialist"])], [UNSUPPORTED])

    def test_a_different_date_is_unsupported(self):
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Customer Service Specialist, 2021"])], [UNSUPPORTED])

    def test_a_certification_claimed_without_any_saved_certifications_is_unsupported(self):
        self.assertEqual([x["classification"] for x in _cert_findings(["Certified Customer Service Specialist"], NO_FACTS)], [UNSUPPORTED])

    def test_a_summary_credential_word_is_supported_by_a_saved_certification(self):
        s = general_truth_findings(_res(summary="Certified customer service professional."), FACTS)
        self.assertFalse(any(f["where"] == "summary[0]" and f["classification"] == UNSUPPORTED and "certified" in f["explanation"]
                             for f in s))

    def test_the_same_summary_credential_word_is_unsupported_without_a_saved_certification(self):
        s = general_truth_findings(_res(summary="Certified customer service professional."), NO_FACTS)
        self.assertTrue(any(f["where"] == "summary[0]" and f["classification"] == UNSUPPORTED for f in s))

    def test_a_fabricated_certification_is_removed_in_on_mode_and_a_genuine_one_is_kept(self):
        resume = _res(["Certified Customer Service Specialist, Acme Institute, 2023", "Certificate in Data Science, Beta Institute"])
        draft, review = rg.review_at_save(resume, FACTS, "on")
        self.assertEqual(draft["certifications"], ["Certified Customer Service Specialist, Acme Institute, 2023"])
        self.assertEqual([r["where"] for r in review["removed"]], ["certifications[1]"])

    def test_a_fabricated_certification_is_recorded_but_not_removed_in_shadow_mode(self):
        resume = _res(["Certificate in Data Science, Beta Institute"])
        draft, review = rg.review_at_save(resume, FACTS, "shadow")
        self.assertEqual(len(draft["certifications"]), 1)           # SHADOW never changes the stored content
        self.assertEqual([r["where"] for r in review["removed"]], ["certifications[0]"])   # recorded as a finding only
        self.assertTrue(any(i["where"] == "certifications[0]" and i["classification"] == UNSUPPORTED for i in review["items"]))


class FactsHashCoversCertifications(unittest.TestCase):
    def test_a_profile_without_certifications_keeps_its_previous_hash(self):
        self.assertEqual(rg.facts_hash(NO_FACTS), rg.facts_hash(dict(NO_FACTS, certifications=[])))

    def test_adding_a_certification_changes_the_hash(self):
        self.assertNotEqual(rg.facts_hash(NO_FACTS), rg.facts_hash(FACTS))

    def test_changing_a_certification_name_issuer_or_date_changes_the_hash(self):
        base = rg.facts_hash(FACTS)
        for field, value in (("name", "Certified Customer Service Lead"), ("issuer", "Beta Institute"), ("date", "06/24")):
            with self.subTest(field=field):
                changed = copy.deepcopy(FACTS)
                changed["certifications"][0][field] = value
                self.assertNotEqual(rg.facts_hash(changed), base)


class CertificationRoutes(OwnershipTestCase):
    """Route level: genuine and fabricated certifications, and sign-offs that go stale when a certification changes."""

    CONTENT = {"name": "SYNTHETIC Member B", "contact": "SYNTHETIC | synthetic.member.b@example.com", "headline": "", "summary": "",
               "skills": [], "experience": [], "education": [],
               "certifications": ["Certified Customer Service Specialist, Acme Institute, 2023",
                                  "Certificate in Data Science, Beta Institute"],
               "skills_style": "grouped"}

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
        self.onboard(self.a)
        res = self.call("POST", "/certifications", self.a, json={"name": "Certified Customer Service Specialist",
                                                                  "issuer": "Acme Institute", "date": "06/23"})
        self.assertEqual(res.status_code, 200, res.text)
        self.cert_id = res.json()["id"]

    def _build_on(self):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}), \
                mock.patch("career.routes.build_general_resume", return_value={"resume_data": copy.deepcopy(self.CONTENT)}):
            res = self.call("POST", "/build-general-resume", self.a, json={"name": "SYNTHETIC Member B",
                                                                           "contact": "SYNTHETIC | synthetic.member.b@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["resume_version_id"]

    def _sign(self, vid):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            preview = self.call("GET", f"/resume-versions/{vid}/preview", self.a)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.a,
                                       json={"finalized_hash": preview.json()["finalized_hash"]}).status_code, 200)
        return preview.json()

    def test_on_build_removes_the_fabricated_certification_and_keeps_the_genuine_one(self):
        vid = self._build_on()
        listed = next(v for v in self.call("GET", "/resume-versions", self.a).json() if v.get("id") == vid)
        self.assertEqual(listed["resume_data"]["certifications"], ["Certified Customer Service Specialist, Acme Institute, 2023"])

    def test_a_genuine_signed_version_downloads_and_approves(self):
        vid = self._build_on()
        self._sign(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 200)
            oid = self.call("POST", "/opportunities", self.a, json={"title": "Analyst", "employer": "Sample Employer",
                                                                     "job_url": "https://jobs.example-employer.com/cert/1",
                                                                     "location_text": "Chicago, IL", "work_arrangement": "hybrid",
                                                                     "employment_type": "full_time"}).json()["id"]
            self.assertEqual(self.call("PUT", f"/opportunities/{oid}/approval", self.a,
                                       json={"approved_resume_version_id": vid}).status_code, 200)

    def test_changing_a_saved_certification_makes_the_signed_version_stale_for_download_and_approval(self):
        vid = self._build_on()
        self._sign(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            oid = self.call("POST", "/opportunities", self.a, json={"title": "Analyst", "employer": "Sample Employer",
                                                                     "job_url": "https://jobs.example-employer.com/cert/2",
                                                                     "location_text": "Chicago, IL", "work_arrangement": "hybrid",
                                                                     "employment_type": "full_time"}).json()["id"]
            self.assertEqual(self.call("PUT", f"/certifications/{self.cert_id}", self.a,
                                       json={"name": "Certified Customer Service Specialist", "issuer": "Beta Institute",
                                             "date": "06/23"}).status_code, 200)
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 409)
            self.assertEqual(self.call("PUT", f"/opportunities/{oid}/approval", self.a,
                                       json={"approved_resume_version_id": vid}).status_code, 409)

    def test_a_certification_changed_after_a_preview_refuses_the_sign_off(self):
        vid = self._build_on()
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            preview = self.call("GET", f"/resume-versions/{vid}/preview", self.a).json()
            self.assertEqual(self.call("PUT", f"/certifications/{self.cert_id}", self.a,
                                       json={"name": "Certified Customer Service Specialist", "issuer": "Acme Institute",
                                             "date": "06/24"}).status_code, 200)
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.a,
                                       json={"finalized_hash": preview["finalized_hash"]}).status_code, 409)

    def test_another_member_cannot_read_my_certification_through_the_review(self):
        vid = self._build_on()
        self.onboard(self.b)
        self.assertEqual(self.call("GET", f"/resume-versions/{vid}/review", self.b).status_code, 404)


if __name__ == "__main__":
    unittest.main()
