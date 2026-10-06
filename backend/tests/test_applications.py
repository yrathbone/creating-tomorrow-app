"""Application tracker routes, run against a throwaway in-memory SQLite database
with the login dependency replaced - no real database, token or AI call.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth.dependencies import get_current_user
from career.routes import router
from db import Base, get_db_session
from models import CareerProfile, ResumeVersion, ScanHistory, User


class ApplicationRoutes(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        db = self.Session()
        self.me = User(cognito_sub="me")
        self.other = User(cognito_sub="other")
        db.add_all([self.me, self.other])
        db.commit()
        self.my_profile = CareerProfile(user_id=self.me.id)
        self.other_profile = CareerProfile(user_id=self.other.id)
        db.add_all([self.my_profile, self.other_profile])
        db.commit()
        self.other_scan = ScanHistory(career_profile_id=self.other_profile.id, scan_type="job_comparison", summary_text="s", result_data={})
        self.my_resume = ResumeVersion(career_profile_id=self.my_profile.id, resume_data={})
        db.add_all([self.other_scan, self.my_resume])
        db.commit()
        self.other_scan_id, self.my_resume_id = self.other_scan.id, self.my_resume.id
        self.me_id, self.other_id = self.me.id, self.other.id
        self.current_id = self.me_id
        db.close()

        app = FastAPI()
        app.include_router(router, prefix="/api/career")

        def session():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        def user():
            s = self.Session()
            u = s.get(User, self.current_id)
            s.close()
            return u

        app.dependency_overrides[get_db_session] = session
        app.dependency_overrides[get_current_user] = user
        self.client = TestClient(app)

    def test_create_list_update_delete(self):
        made = self.client.post("/api/career/applications", json={"job_title": "CSM, Enterprise", "company": "Stripe", "applied_on": "2026-10-06", "resume_version_id": self.my_resume_id})
        self.assertEqual(made.status_code, 200, made.text)
        app_id = made.json()["id"]
        self.assertEqual(made.json()["status"], "applied")

        listing = self.client.get("/api/career/applications").json()
        self.assertEqual([a["job_title"] for a in listing], ["CSM, Enterprise"])

        upd = self.client.put(f"/api/career/applications/{app_id}", json={"job_title": "CSM, Enterprise", "company": "Stripe", "applied_on": "2026-10-06", "status": "interview", "notes": "Phone screen Tue"})
        self.assertEqual((upd.status_code, upd.json()["status"], upd.json()["notes"]), (200, "interview", "Phone screen Tue"))

        self.assertEqual(self.client.delete(f"/api/career/applications/{app_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/career/applications").json(), [])

    def test_date_defaults_to_today_and_bad_input_is_rejected(self):
        ok = self.client.post("/api/career/applications", json={"job_title": "X"})
        self.assertEqual(ok.status_code, 200)
        self.assertRegex(ok.json()["applied_on"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(self.client.post("/api/career/applications", json={"job_title": "X", "applied_on": "10/06/2026"}).status_code, 400)
        self.assertEqual(self.client.post("/api/career/applications", json={"job_title": "  "}).status_code, 400)
        self.assertEqual(self.client.post("/api/career/applications", json={"job_title": "X", "status": "ghosted"}).status_code, 400)

    def test_cannot_link_someone_elses_scan_or_touch_their_rows(self):
        stolen = self.client.post("/api/career/applications", json={"job_title": "X", "scan_history_id": self.other_scan_id})
        self.assertEqual(stolen.status_code, 400)

        # a row belonging to the other user is invisible and untouchable
        self.current_id = self.other_id
        theirs = self.client.post("/api/career/applications", json={"job_title": "Theirs"}).json()["id"]
        self.current_id = self.me_id
        self.assertEqual(self.client.get("/api/career/applications").json(), [])
        self.assertEqual(self.client.put(f"/api/career/applications/{theirs}", json={"job_title": "Mine now"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/career/applications/{theirs}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
