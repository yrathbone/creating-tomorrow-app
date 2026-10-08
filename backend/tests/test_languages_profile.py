"""Phase 2B: Language entity, Career Profile basics (display name / contact line), and the
behavior of those features before database migration 0008 has been applied.

Uses the same real-token test harness as the Phase 2A ownership suite.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
from sqlalchemy import text

from models import CareerProfile, Language, User
from tests.test_ownership import OwnershipTestCase, SUB_A, SUB_B, bearer, make_token


class LanguageRoutes(OwnershipTestCase):
    def test_crud_and_response_shape(self):
        self.onboard(self.a)
        made = self.call("POST", "/languages", self.a, json={"name": "Spanish", "proficiency": "Professional working proficiency"})
        self.assertEqual(made.status_code, 200, made.text)
        body = made.json()
        self.assertEqual(sorted(body), ["created_at", "id", "name", "proficiency", "source"])
        self.assertEqual((body["name"], body["proficiency"], body["source"]), ("Spanish", "Professional working proficiency", "manual"))

        self.call("POST", "/languages", self.a, json={"name": "English", "proficiency": "Native"})
        listing = self.call("GET", "/languages", self.a).json()
        self.assertEqual([l["name"] for l in listing], ["Spanish", "English"])  # oldest first

        upd = self.call("PUT", f"/languages/{body['id']}", self.a, json={"name": "Spanish (Mexico)", "proficiency": "Native"})
        self.assertEqual((upd.status_code, upd.json()["name"], upd.json()["proficiency"]), (200, "Spanish (Mexico)", "Native"))
        self.assertEqual(self.call("GET", "/languages", self.a).json()[0]["name"], "Spanish (Mexico)")

        self.assertEqual(self.call("DELETE", f"/languages/{body['id']}", self.a).json(), {"deleted": True})
        self.assertEqual([l["name"] for l in self.call("GET", "/languages", self.a).json()], ["English"])
        self.assertEqual(self.call("DELETE", f"/languages/{body['id']}", self.a).status_code, 404)

    def test_name_is_required_and_trimmed(self):
        self.onboard(self.a)
        self.assertEqual(self.call("POST", "/languages", self.a, json={"name": "   "}).status_code, 400)
        self.assertEqual(self.call("POST", "/languages", self.a, json={"name": ""}).status_code, 400)
        self.assertEqual(self.call("POST", "/languages", self.a, json={"proficiency": "Native"}).status_code, 422)
        made = self.call("POST", "/languages", self.a, json={"name": "  French  "}).json()
        self.assertEqual(made["name"], "French")
        self.assertEqual(self.call("PUT", f"/languages/{made['id']}", self.a, json={"name": " "}).status_code, 400)
        self.assertEqual(self.call("GET", "/languages", self.a).json()[0]["name"], "French")  # failed update changed nothing

    def test_proficiency_is_optional_and_blank_becomes_none(self):
        self.onboard(self.a)
        none_given = self.call("POST", "/languages", self.a, json={"name": "German"}).json()
        self.assertIsNone(none_given["proficiency"])
        blank = self.call("POST", "/languages", self.a, json={"name": "Italian", "proficiency": "   "}).json()
        self.assertIsNone(blank["proficiency"])
        trimmed = self.call("POST", "/languages", self.a, json={"name": "Hindi", "proficiency": "  Limited  "}).json()
        self.assertEqual(trimmed["proficiency"], "Limited")
        cleared = self.call("PUT", f"/languages/{trimmed['id']}", self.a, json={"name": "Hindi"}).json()
        self.assertIsNone(cleared["proficiency"])

    def test_requires_a_career_profile(self):
        self.assertEqual(self.call("GET", "/languages", self.a).status_code, 404)  # no consent yet
        self.assertEqual(self.call("POST", "/languages", self.a, json={"name": "Spanish"}).status_code, 404)

    def test_languages_are_isolated_between_users(self):
        self.onboard(self.a)
        self.onboard(self.b)
        a_lang = self.call("POST", "/languages", self.a, json={"name": "Secret-A", "proficiency": "Native"}).json()["id"]
        b_lang = self.call("POST", "/languages", self.b, json={"name": "Mine-B"}).json()["id"]
        self.assertEqual([l["name"] for l in self.call("GET", "/languages", self.a).json()], ["Secret-A"])
        self.assertEqual([l["name"] for l in self.call("GET", "/languages", self.b).json()], ["Mine-B"])
        # B knows A's database id and tries anyway
        self.assertEqual(self.call("PUT", f"/languages/{a_lang}", self.b, json={"name": "Hacked"}).status_code, 404)
        self.assertEqual(self.call("DELETE", f"/languages/{a_lang}", self.b).status_code, 404)
        with self.Session() as s:
            self.assertEqual(s.get(Language, a_lang).name, "Secret-A")
            self.assertEqual(s.get(Language, b_lang).career_profile_id, self.profile_id_for(SUB_B))

    def test_identity_in_the_body_is_ignored(self):
        self.onboard(self.a)
        self.onboard(self.b)
        res = self.call("POST", "/languages", self.a, json={
            "name": "Injected", "user_id": 99, "cognito_sub": SUB_B, "career_profile_id": self.profile_id_for(SUB_B), "source": "hacker",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["source"], "manual")
        self.assertEqual(self.call("GET", "/languages", self.b).json(), [])
        self.assertEqual(len(self.call("GET", "/languages", self.a).json()), 1)

    def test_languages_are_in_the_export_and_only_the_owners(self):
        self.onboard(self.a)
        self.onboard(self.b)
        self.call("POST", "/languages", self.a, json={"name": "Quechua-A", "proficiency": "Native"})
        self.call("POST", "/languages", self.b, json={"name": "Basque-B"})
        export_a = self.call("GET", "/export", self.a).json()
        self.assertEqual([(l["name"], l["proficiency"]) for l in export_a["languages"]], [("Quechua-A", "Native")])
        self.assertNotIn("languages_unavailable", export_a)
        text_b = self.call("GET", "/export", self.b).text
        self.assertIn("Basque-B", text_b)
        self.assertNotIn("Quechua-A", text_b)


class ProfileBasicsRoutes(OwnershipTestCase):
    def test_get_requires_a_profile_then_starts_empty(self):
        self.assertEqual(self.call("GET", "/profile", self.a).status_code, 404)
        self.onboard(self.a)
        res = self.call("GET", "/profile", self.a)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"display_name": None, "contact_line": None})

    def test_save_and_reload_with_trimming_and_blank_clearing(self):
        self.onboard(self.a)
        saved = self.call("PUT", "/profile", self.a, json={"display_name": "  Ada Lovelace ", "contact_line": " London | ada@example.com "})
        self.assertEqual((saved.status_code, saved.json()), (200, {"display_name": "Ada Lovelace", "contact_line": "London | ada@example.com"}))
        self.assertEqual(self.call("GET", "/profile", self.a).json(), {"display_name": "Ada Lovelace", "contact_line": "London | ada@example.com"})
        # blank means "none"; omitted means "none" too (the PUT replaces both fields)
        self.call("PUT", "/profile", self.a, json={"display_name": "   ", "contact_line": "only contact"})
        self.assertEqual(self.call("GET", "/profile", self.a).json(), {"display_name": None, "contact_line": "only contact"})
        self.call("PUT", "/profile", self.a, json={})
        self.assertEqual(self.call("GET", "/profile", self.a).json(), {"display_name": None, "contact_line": None})

    def test_length_limits(self):
        self.onboard(self.a)
        self.assertEqual(self.call("PUT", "/profile", self.a, json={"display_name": "x" * 201}).status_code, 400)
        self.assertEqual(self.call("PUT", "/profile", self.a, json={"contact_line": "x" * 401}).status_code, 400)
        self.assertEqual(self.call("PUT", "/profile", self.a, json={"display_name": "x" * 200, "contact_line": "y" * 400}).status_code, 200)

    def test_profiles_are_isolated_and_the_browser_cannot_pick_one(self):
        self.onboard(self.a)
        self.onboard(self.b)
        self.call("PUT", "/profile", self.a, json={"display_name": "Name A", "contact_line": "Contact A"})
        # B sees its own (empty) profile, never A's
        self.assertEqual(self.call("GET", "/profile", self.b).json(), {"display_name": None, "contact_line": None})
        # B tries to point the write at A's profile / user through the body
        a_profile = self.profile_id_for(SUB_A)
        res = self.call("PUT", "/profile", self.b, json={
            "display_name": "Written by B", "contact_line": "B contact",
            "id": a_profile, "career_profile_id": a_profile, "profile_id": a_profile, "user_id": 1, "cognito_sub": SUB_A,
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.call("GET", "/profile", self.a).json(), {"display_name": "Name A", "contact_line": "Contact A"})
        self.assertEqual(self.call("GET", "/profile", self.b).json(), {"display_name": "Written by B", "contact_line": "B contact"})
        # there is no route that takes a profile id at all
        for method in ("GET", "PUT"):
            self.assertIn(self.call(method, f"/profile/{a_profile}", self.b, json={}).status_code, (404, 405))
        # and the same query-string attempt does nothing
        self.assertEqual(self.call("GET", f"/profile?profile_id={a_profile}&user_id=1", self.b).json()["display_name"], "Written by B")

    def test_requires_a_valid_token(self):
        self.assertEqual(self.client.get("/api/career/profile").status_code, 401)
        self.assertEqual(self.client.put("/api/career/profile", json={}).status_code, 401)
        self.assertEqual(self.client.get("/api/career/languages").status_code, 401)
        self.assertEqual(self.client.post("/api/career/languages", json={"name": "x"}).status_code, 401)
        self.assertEqual(self.call("GET", "/profile", bearer(make_token(SUB_A, client_id="other-client"))).status_code, 401)

    def test_existing_profile_rows_stay_valid_with_new_fields_empty(self):
        self.onboard(self.a)
        with self.Session() as s:
            row = s.query(CareerProfile).join(User).filter(User.cognito_sub == SUB_A).one()
            self.assertIsNone(row.display_name)
            self.assertIsNone(row.contact_line)
        # every pre-existing dashboard read still works with those fields empty
        for path in ("/experiences", "/education", "/certifications", "/skills", "/scan-history", "/resume-versions", "/applications", "/export"):
            self.assertEqual(self.call("GET", path, self.a).status_code, 200, path)


class BeforeMigration0008(OwnershipTestCase):
    """Production starts on the old schema until `alembic upgrade head` is run. Everything that
    existed before must keep working, and the new features must say plainly why they cannot."""

    def setUp(self):
        super().setUp()
        self.onboard(self.a)  # a profile created on the NEW schema, then roll the schema back to 0007
        with self.Session() as s:
            s.execute(text("DROP TABLE languages"))
            s.execute(text("ALTER TABLE career_profiles DROP COLUMN display_name"))
            s.execute(text("ALTER TABLE career_profiles DROP COLUMN contact_line"))
            s.commit()

    def test_language_routes_report_the_missing_upgrade_instead_of_pretending(self):
        for method, path, body in (("GET", "/languages", None), ("POST", "/languages", {"name": "Spanish"}),
                                   ("PUT", "/languages/1", {"name": "Spanish"}), ("DELETE", "/languages/1", None)):
            with self.subTest(f"{method} {path}"):
                kw = {"json": body} if body is not None else {}
                res = self.call(method, path, self.a, **kw)
                self.assertEqual(res.status_code, 503, res.text)
                self.assertIn("migration 0008", res.json()["detail"])

    def test_profile_routes_report_the_missing_upgrade(self):
        for method, kw in (("GET", {}), ("PUT", {"json": {"display_name": "Ada"}})):
            res = self.call(method, "/profile", self.a, **kw)
            self.assertEqual(res.status_code, 503, res.text)
            self.assertIn("migration 0008", res.json()["detail"])

    def test_export_still_works_and_says_languages_are_missing(self):
        res = self.call("GET", "/export", self.a)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["languages"], [])
        self.assertIn("migration 0008", body["languages_unavailable"])

    def test_everything_that_existed_before_keeps_working(self):
        self.assertEqual(self.call("GET", "/me", self.a).status_code, 200)
        made = self.call("POST", "/experiences", self.a, json={"title": "T", "organization": "O"})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(len(self.call("GET", "/experiences", self.a).json()), 1)
        # and a brand-new person can still consent (a new profile row is created on the old schema)
        self.assertEqual(self.call("POST", "/consent", self.b).status_code, 200)
        self.assertEqual(self.call("GET", "/skills", self.b).status_code, 200)
        # a failed new-feature request must not poison the next request
        self.assertEqual(self.call("GET", "/languages", self.b).status_code, 503)
        self.assertEqual(self.call("GET", "/education", self.b).status_code, 200)
