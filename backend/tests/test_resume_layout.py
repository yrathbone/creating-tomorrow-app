"""The preferred resume layout (migration 0009): pick it once and it is remembered on the Career Profile.

Same real-token harness as the ownership suite. Covers: defaults, saving and clearing, validation,
isolation between people, the download route using the saved layout, and the behavior before the
database upgrade has been applied (everything else must keep working; only this feature waits).

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import io
import unittest

from docx import Document
from docx.shared import Pt
from sqlalchemy import text

from models import CareerProfile
from tests.test_ownership import OwnershipTestCase, SUB_A

NAME_SIZE = {"classic": Pt(11), "modern": Pt(22), "traditional": Pt(18)}


def name_size_of(res):
    return Document(io.BytesIO(res.content)).paragraphs[0].runs[0].font.size


class ResumeLayoutRoutes(OwnershipTestCase):
    def test_starts_as_classic(self):
        self.onboard(self.a)
        res = self.call("GET", "/resume-layout", self.a)
        self.assertEqual((res.status_code, res.json()), (200, {"layout": "classic"}))

    def test_save_reload_and_change_it(self):
        self.onboard(self.a)
        for layout in ("modern", "traditional", "classic", "modern"):
            put = self.call("PUT", "/resume-layout", self.a, json={"layout": layout})
            self.assertEqual((put.status_code, put.json()), (200, {"layout": layout}), put.text)
            self.assertEqual(self.call("GET", "/resume-layout", self.a).json(), {"layout": layout})

    def test_classic_and_blank_both_clear_the_saved_choice(self):
        self.onboard(self.a)
        self.call("PUT", "/resume-layout", self.a, json={"layout": "modern"})
        self.assertEqual(self.call("PUT", "/resume-layout", self.a, json={"layout": ""}).json(), {"layout": "classic"})
        with self.Session() as s:  # nothing is stored for the default
            self.assertIsNone(s.query(CareerProfile).one().preferred_resume_layout)
        self.call("PUT", "/resume-layout", self.a, json={"layout": "traditional"})
        self.assertEqual(self.call("PUT", "/resume-layout", self.a, json={}).json(), {"layout": "classic"})

    def test_the_name_is_trimmed_and_case_does_not_matter_but_other_names_are_refused(self):
        self.onboard(self.a)
        self.assertEqual(self.call("PUT", "/resume-layout", self.a, json={"layout": "  Modern "}).json(), {"layout": "modern"})
        for bad in ("fancy", "modern;", "../classic", "x" * 500):
            res = self.call("PUT", "/resume-layout", self.a, json={"layout": bad})
            self.assertEqual(res.status_code, 400, bad)
        self.assertEqual(self.call("GET", "/resume-layout", self.a).json(), {"layout": "modern"})  # unchanged by the bad tries

    def test_requires_a_career_profile_first(self):
        self.assertEqual(self.call("GET", "/resume-layout", self.a).status_code, 404)
        self.assertEqual(self.call("PUT", "/resume-layout", self.a, json={"layout": "modern"}).status_code, 404)

    def test_people_cannot_see_or_change_each_others_layout(self):
        self.onboard(self.a)
        self.onboard(self.b)
        self.call("PUT", "/resume-layout", self.a, json={"layout": "modern"})
        self.assertEqual(self.call("GET", "/resume-layout", self.b).json(), {"layout": "classic"})
        self.call("PUT", "/resume-layout", self.b, json={"layout": "traditional"})
        self.assertEqual(self.call("GET", "/resume-layout", self.a).json(), {"layout": "modern"})

    def test_identity_in_the_body_is_ignored(self):
        self.onboard(self.a)
        self.onboard(self.b)
        self.call("PUT", "/resume-layout", self.a, json={"layout": "modern", "user_id": 2, "career_profile_id": 2, "cognito_sub": "someone-else"})
        self.assertEqual(self.call("GET", "/resume-layout", self.b).json(), {"layout": "classic"})
        self.assertEqual(self.call("GET", "/resume-layout", self.a).json(), {"layout": "modern"})

    def test_requires_a_valid_token(self):
        for method in ("GET", "PUT"):
            res = self.client.request(method, "/api/career/resume-layout", json={"layout": "modern"})
            self.assertEqual(res.status_code, 401, method)


class DownloadUsesTheSavedLayout(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        self.onboard(self.a)
        _, self.resume = self.seed_history_rows(SUB_A)

    def download(self, query=""):
        res = self.call("GET", f"/resume-versions/{self.resume}/download{query}", self.a)
        self.assertEqual(res.status_code, 200, res.text)
        return name_size_of(res)

    def test_with_no_choice_it_uses_the_saved_layout(self):
        self.assertEqual(self.download(), NAME_SIZE["classic"])
        self.call("PUT", "/resume-layout", self.a, json={"layout": "modern"})
        self.assertEqual(self.download(), NAME_SIZE["modern"])
        self.call("PUT", "/resume-layout", self.a, json={"layout": "traditional"})
        self.assertEqual(self.download(), NAME_SIZE["traditional"])

    def test_an_explicit_choice_wins_over_the_saved_one(self):
        self.call("PUT", "/resume-layout", self.a, json={"layout": "modern"})
        self.assertEqual(self.download("?template=traditional"), NAME_SIZE["traditional"])
        self.assertEqual(self.download("?template=classic"), NAME_SIZE["classic"])

    def test_a_wrong_choice_gives_classic_not_an_error(self):
        self.assertEqual(self.download("?template=nonsense"), NAME_SIZE["classic"])


class BeforeMigration0009(OwnershipTestCase):
    """Production stays on the old schema until `alembic upgrade head` is run."""

    def setUp(self):
        super().setUp()
        self.onboard(self.a)
        _, self.resume = self.seed_history_rows(SUB_A)
        with self.Session() as s:
            s.execute(text("ALTER TABLE career_profiles DROP COLUMN preferred_resume_layout"))
            s.commit()

    def test_the_layout_routes_say_plainly_that_the_upgrade_is_missing(self):
        for method, kw in (("GET", {}), ("PUT", {"json": {"layout": "modern"}})):
            res = self.call(method, "/resume-layout", self.a, **kw)
            self.assertEqual(res.status_code, 503, res.text)
            self.assertIn("migration 0009", res.json()["detail"])

    def test_downloads_still_work_and_use_classic(self):
        res = self.call("GET", f"/resume-versions/{self.resume}/download", self.a)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(name_size_of(res), NAME_SIZE["classic"])
        res = self.call("GET", f"/resume-versions/{self.resume}/download?template=modern", self.a)
        self.assertEqual(name_size_of(res), NAME_SIZE["modern"])  # an explicit choice still works

    def test_the_name_and_contact_fields_and_everything_else_keep_working(self):
        # the saved name/contact line live on the same table: they must not be disturbed
        put = self.call("PUT", "/profile", self.a, json={"display_name": "Ada Lovelace", "contact_line": "London"})
        self.assertEqual(put.status_code, 200, put.text)
        self.assertEqual(self.call("GET", "/profile", self.a).json(), {"display_name": "Ada Lovelace", "contact_line": "London"})
        self.assertEqual(self.call("GET", "/me", self.a).status_code, 200)
        self.assertEqual(self.call("POST", "/experiences", self.a, json={"title": "T", "organization": "O"}).status_code, 200)
        self.assertEqual(self.call("GET", "/export", self.a).status_code, 200)
        # a brand-new person can still consent, and a failed layout request poisons nothing
        self.assertEqual(self.call("POST", "/consent", self.b).status_code, 200)
        self.assertEqual(self.call("GET", "/resume-layout", self.b).status_code, 503)
        self.assertEqual(self.call("GET", "/education", self.b).status_code, 200)


if __name__ == "__main__":
    unittest.main()
