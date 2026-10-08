"""Self-serve "Delete my data and account": POST /api/career/account/delete.

Uses the same real-token harness as the ownership tests. The rules under test: the word DELETE is required;
only the signed-in person's own data goes (never anyone else's); every kind of saved record goes; it works
before every migration is applied; and it is all-or-nothing.
Run from backend/:  py -3.12 -m unittest discover -s tests -t .
"""
import unittest
from unittest import mock

from sqlalchemy import text

import career.routes as routes
from models import Application, CareerProfile, Certification, Education, Experience, Language, ResumeIngestionDraft, ResumeVersion, ScanHistory, Skill, User
from tests.test_ownership import OwnershipTestCase, SUB_A, SUB_B, bearer, make_token

KINDS = (Application, ResumeVersion, ScanHistory, Skill, Experience, Education, Certification, Language, ResumeIngestionDraft, CareerProfile)


class DeleteAccount(OwnershipTestCase):
    def delete(self, who, confirm="DELETE"):
        return self.call("POST", "/account/delete", who, json={"confirm": confirm})

    def rows_for(self, label, sub):
        """How many rows of every kind belong to this person (profile id looked up before any deletion)."""
        with self.Session() as s:
            profile = s.query(CareerProfile).join(User).filter(User.cognito_sub == sub).one_or_none()
            if profile is None:
                return {m.__tablename__: 0 for m in KINDS}
            out = {}
            for m in KINDS:
                col = m.id if m is CareerProfile else m.career_profile_id
                out[m.__tablename__] = s.query(m).filter(col == (profile.id)).count()
            return out

    def world(self):
        ids = self.build_world()
        # a language and an unfinished resume draft for A as well
        self.assertEqual(self.call("POST", "/languages", self.a, json={"name": "Spanish", "proficiency": "native"}).status_code, 200)
        pid = self.profile_id_for(SUB_A)
        with self.Session() as s:
            s.add(ResumeIngestionDraft(career_profile_id=pid, analysis_summary="private draft"))
            s.commit()
        return ids

    def user_count(self, sub):
        with self.Session() as s:
            return s.query(User).filter(User.cognito_sub == sub).count()

    def test_the_word_delete_is_required_and_nothing_goes_without_it(self):
        self.world()
        before = self.rows_for("A", SUB_A)
        for wrong in ("", "delete", "Delete", "yes", "DELETE ME", "please"):
            with self.subTest(wrong):
                res = self.delete(self.a, wrong)
                self.assertEqual(res.status_code, 400, wrong)
        self.assertEqual(self.rows_for("A", SUB_A), before)
        self.assertEqual(self.user_count(SUB_A), 1)
        # no body at all is refused too
        self.assertEqual(self.call("POST", "/account/delete", self.a, json={}).status_code, 422)

    def test_it_requires_a_real_signed_in_person(self):
        self.assertEqual(self.client.post("/api/career/account/delete", json={"confirm": "DELETE"}).status_code, 401)
        self.assertEqual(self.delete(bearer("not.a.token")).status_code, 401)

    def test_everything_of_the_signed_in_person_is_erased_and_nothing_of_anyone_else(self):
        self.world()
        before_a, before_b = self.rows_for("A", SUB_A), self.rows_for("B", SUB_B)
        self.assertTrue(all(n >= 1 for n in before_a.values()), before_a)  # the test really covers every kind of record
        res = self.delete(self.a)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["deleted"])
        for key in ("applications", "resume_versions", "scan_history", "skills", "experiences", "education", "certifications", "languages", "drafts"):
            self.assertGreaterEqual(body["counts"][key], 1, key)
        self.assertEqual(self.user_count(SUB_A), 0)
        with self.Session() as s:
            for m in KINDS:
                self.assertEqual(s.query(m).count(), before_b[m.__tablename__], f"{m.__tablename__}: only B's rows may remain")
        self.assertEqual(self.rows_for("B", SUB_B), before_b)
        # B still signs in and sees exactly their own things
        self.assertEqual(len(self.call("GET", "/experiences", self.b).json()), 1)
        self.assertEqual(self.call("GET", "/experiences", self.b).json()[0]["title"], "Role B")

    def test_an_old_token_after_deletion_finds_an_empty_account_not_the_old_data(self):
        self.world()
        self.assertEqual(self.delete(self.a).status_code, 200)
        res = self.call("GET", "/experiences", self.a)
        self.assertEqual(res.status_code, 404)  # a fresh person with no Career Profile: consent is needed first
        with self.Session() as s:
            self.assertEqual(s.query(Experience).filter(Experience.title == "Role A").count(), 0)

    def test_a_person_who_never_created_a_profile_can_still_delete(self):
        self.assertEqual(self.call("GET", "/me", self.a).status_code, 200)  # signs the account row into existence
        self.assertEqual(self.user_count(SUB_A), 1)
        res = self.delete(self.a)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.user_count(SUB_A), 0)

    def test_calling_it_twice_is_harmless(self):
        self.world()
        self.assertEqual(self.delete(self.a).status_code, 200)
        self.assertEqual(self.delete(self.a).status_code, 200)
        self.assertEqual(self.rows_for("B", SUB_B)["experiences"], 1)

    def test_it_works_before_every_migration_is_applied(self):
        self.world()
        with self.Session() as s:  # simulate a database where the languages table does not exist yet
            s.execute(text("DROP TABLE languages"))
            s.commit()
        res = self.delete(self.a)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["counts"]["languages"], 0)
        self.assertEqual(self.user_count(SUB_A), 0)

    def test_it_is_all_or_nothing(self):
        self.world()
        before = self.rows_for("A", SUB_A)
        real = routes._delete_rows
        calls = {"n": 0}

        def flaky(db, model, **filters):
            calls["n"] += 1
            if calls["n"] == 5:
                raise RuntimeError("the database went away half-way")
            return real(db, model, **filters)

        with mock.patch.object(routes, "_delete_rows", flaky):
            with self.assertRaises(RuntimeError):
                self.delete(self.a)
        self.assertGreaterEqual(calls["n"], 5)
        self.assertEqual(self.rows_for("A", SUB_A), before, "a half-finished deletion must roll back")
        self.assertEqual(self.user_count(SUB_A), 1)

    def test_the_log_line_never_contains_personal_details(self):
        self.world()
        with self.assertLogs("career.routes", level="INFO") as logs:
            self.delete(self.a)
        line = " ".join(logs.output)
        self.assertIn("deleted by their owner", line)
        for private in ("Role A", "Org A", "private-A", "Spanish", SUB_A, "Secret job"):
            self.assertNotIn(private, line)


if __name__ == "__main__":
    unittest.main()
