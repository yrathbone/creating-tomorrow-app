"""Job discovery pilot (migration 0012): offline tests. In-memory SQLite, synthetic boards and members, no network.

Covers: feature gating, preferences and the 10-board limit, member isolation, board parsing, the rules that stop bad board
responses closing live postings, central fetch (one read per board), deterministic matching, and the review link.
Run from the backend folder:  python -m unittest discover -s tests -t .
"""
import io
import json
import os
import socket
import unittest
import urllib.error
from datetime import date, timedelta
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import job_discovery_run
from auth.dependencies import get_current_user
from career import discovery
from career.discovery_routes import router as discovery_router
from career.job_boards import (BoardError, apply_board_records, fetch_board_records, fetch_payload, load_registry, parse_ashby,
                               parse_greenhouse, purge_closed, run_sync)
from career.opportunities import normalize_job_url
from career.routes import router as career_router
from db import Base, get_db_session
from models import CareerProfile, Experience, JobPosting, JobPreference, Opportunity, Skill, User

BOARD_A = {"source": "greenhouse", "board_token": "sample-a", "name": "Sample Employer A"}
BOARD_B = {"source": "ashby", "board_token": "sample-b", "name": "Sample Employer B"}
TODAY = date(2026, 11, 12)


def _no_network(*args, **kwargs):
    raise AssertionError("network access attempted during an offline test")


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._buf, self.status = io.BytesIO(body), status

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Stands in for the network: serves canned bodies per board token and counts reads."""
    def __init__(self, bodies: dict):
        self.bodies, self.calls = bodies, []

    def open(self, req, timeout=None):
        token = req.full_url.rstrip("/").rsplit("/", 2)[-2] if "greenhouse" in req.full_url else req.full_url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append(token)
        body = self.bodies[token]
        if isinstance(body, Exception):
            raise body
        return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))


def gh_job(job_id, title="Project Coordinator", location="Chicago, IL", slug="sample-a"):
    return {"id": job_id, "title": title, "location": {"name": location},
            "absolute_url": f"https://jobs.example-employer.com/{slug}/jobs/{job_id}"}


def ash_job(job_id, title="Program Manager", workplace="Hybrid", employment="FullTime", listed=True):
    return {"id": job_id, "title": title, "location": "Chicago, IL", "workplaceType": workplace, "employmentType": employment,
            "isListed": listed, "jobUrl": f"https://jobs.example-employer.com/sample-b/{job_id}"}


class DiscoveryBase(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {
            "CT_JOB_DISCOVERY_ENABLED": "1", "CT_JOB_DISCOVERY_ALLOWED_SUBS": "me,other",
            "CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": "me,other",
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        for name in ("create_connection", "getaddrinfo"):
            p = mock.patch.object(socket, name, side_effect=_no_network)
            p.start()
            self.addCleanup(p.stop)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.engine = engine
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        db = self.Session()
        self.me, self.other = User(cognito_sub="me"), User(cognito_sub="other")
        db.add_all([self.me, self.other])
        db.commit()
        self.my_profile = CareerProfile(user_id=self.me.id)
        self.other_profile = CareerProfile(user_id=self.other.id)
        db.add_all([self.my_profile, self.other_profile])
        db.commit()
        db.add(Experience(career_profile_id=self.my_profile.id, title="Program Coordinator", organization="Sample Org"))
        db.add(Skill(career_profile_id=self.my_profile.id, name="Grant reporting"))
        db.commit()
        self.my_id, self.other_id = self.me.id, self.other.id
        self.my_profile_id, self.other_profile_id = self.my_profile.id, self.other_profile.id
        db.close()

        app = FastAPI()
        app.include_router(career_router, prefix="/api/career")
        app.include_router(discovery_router, prefix="/api/career")
        self.current = self.my_id

        def session():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        def user():
            s = self.Session()
            u = s.get(User, self.current)
            s.close()
            return u

        app.dependency_overrides[get_db_session] = session
        app.dependency_overrides[get_current_user] = user
        self.client = TestClient(app, raise_server_exceptions=False)

    def add_posting(self, db, board=BOARD_A, job_id="1", title="Project Coordinator", location="Chicago, IL", arrangement="on_site",
                    employment="full_time", slug="sample-a", first=TODAY, closed=None):
        url = f"https://jobs.example-employer.com/{slug}/jobs/{job_id}"
        _, url_hash = normalize_job_url(url)
        row = JobPosting(source=board["source"], board_token=board["board_token"], source_job_id=job_id, title=title,
                         company=board["name"], location_text=location, work_arrangement=arrangement, employment_type=employment,
                         job_url=url, url_hash=url_hash, first_seen_on=first, last_seen_on=first, closed_on=closed)
        db.add(row)
        db.commit()
        return row


class Gating(DiscoveryBase):
    def test_switch_off_returns_404(self):
        with mock.patch.dict(os.environ, {"CT_JOB_DISCOVERY_ENABLED": "0"}):
            self.assertEqual(self.client.get("/api/career/job-preferences").status_code, 404)
            self.assertEqual(self.client.get("/api/career/job-matches").status_code, 404)

    def test_not_on_allowlist_returns_404(self):
        self.current = self.my_id
        with mock.patch.dict(os.environ, {"CT_JOB_DISCOVERY_ALLOWED_SUBS": "someone-else"}):
            self.assertEqual(self.client.get("/api/career/job-preferences").status_code, 404)

    def test_runner_refuses_when_switch_off(self):
        with mock.patch.dict(os.environ, {"CT_JOB_DISCOVERY_ENABLED": "0"}):
            self.assertEqual(job_discovery_run.main(), 2)


class Preferences(DiscoveryBase):
    def test_defaults_when_nothing_saved(self):
        body = self.client.get("/api/career/job-preferences").json()
        self.assertEqual(body["target_titles"], [])
        self.assertTrue(body["remote_ok"] and body["onsite_ok"])
        self.assertEqual(body["follow_limit"], 10)

    def test_save_and_read_back(self):
        put = self.client.put("/api/career/job-preferences", json={"target_titles": ["Program Manager"], "locations": ["Chicago"],
                                                                   "remote_ok": False, "employment_types": ["full_time"], "exclude_words": ["sales"]})
        self.assertEqual(put.status_code, 200, put.text)
        got = self.client.get("/api/career/job-preferences").json()
        self.assertEqual(got["target_titles"], ["Program Manager"])
        self.assertFalse(got["remote_ok"])

    def test_unknown_board_refused(self):
        r = self.client.put("/api/career/job-preferences", json={"followed_boards": ["greenhouse:not-approved"]})
        self.assertEqual(r.status_code, 400)

    def test_follow_limit_is_ten_and_enforced_in_code(self):
        from career.discovery_routes import follow_limit
        self.assertEqual(follow_limit(), 10)
        boards = [{"source": "greenhouse", "board_token": f"sample-{i}", "name": f"Sample Employer {i}"} for i in range(11)]
        self._approve(boards)
        eleven = [f"greenhouse:sample-{i}" for i in range(11)]
        self.assertEqual(self.client.put("/api/career/job-preferences", json={"followed_boards": eleven}).status_code, 400)
        ten = eleven[:10]
        self.assertEqual(self.client.put("/api/career/job-preferences", json={"followed_boards": ten}).status_code, 200)

    def test_bad_employment_type_and_negative_pay_refused(self):
        self.assertEqual(self.client.put("/api/career/job-preferences", json={"employment_types": ["freelance"]}).status_code, 400)
        self.assertEqual(self.client.put("/api/career/job-preferences", json={"min_base": -5}).status_code, 422)

    def test_other_member_cannot_see_my_preferences(self):
        self._approve([BOARD_A])
        self.client.put("/api/career/job-preferences", json={"target_titles": ["Secret Role"], "followed_boards": ["greenhouse:sample-a"]})
        self.current = self.other_id
        seen = self.client.get("/api/career/job-preferences").json()
        self.assertEqual(seen["target_titles"], [])
        self.assertEqual(seen["followed_boards"], [])

    def _approve(self, boards):
        import career.job_boards as jb
        self._reg = mock.patch.object(jb, "load_registry", return_value=boards)
        self._reg.start()
        self.addCleanup(self._reg.stop)
        import career.discovery_routes as dr
        self._reg2 = mock.patch.object(dr, "load_registry", return_value=boards)
        self._reg2.start()
        self.addCleanup(self._reg2.stop)


class BoardParsing(unittest.TestCase):
    def test_greenhouse_valid_and_malformed_items_counted(self):
        payload = {"jobs": [gh_job(1), {"id": 2, "title": ""}, "not-a-job", gh_job(3, slug="sample-a")]}
        records, malformed = parse_greenhouse(payload, BOARD_A)
        self.assertEqual([r["source_job_id"] for r in records], ["1", "3"])
        self.assertEqual(malformed, 2)

    def test_ashby_skips_direct_link_only_and_maps_fields(self):
        payload = {"jobs": [ash_job("a1", workplace="Remote", employment="PartTime"), ash_job("a2", listed=False)]}
        records, malformed = parse_ashby(payload, BOARD_B)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["work_arrangement"], "remote")
        self.assertEqual(records[0]["employment_type"], "part_time")
        self.assertEqual(malformed, 0)

    def test_ashby_without_id_uses_the_link(self):
        job = ash_job("x")
        del job["id"]
        records, _ = parse_ashby({"jobs": [job]}, BOARD_B)
        self.assertEqual(records[0]["source_job_id"], job["jobUrl"])

    def test_wrong_shape_is_held(self):
        with self.assertRaises(BoardError):
            parse_greenhouse(["not", "a", "dict"], BOARD_A)
        with self.assertRaises(BoardError):
            parse_ashby({"jobs": "nope"}, BOARD_B)

    def test_unsafe_link_is_skipped_not_repaired(self):
        bad = gh_job(9)
        bad["absolute_url"] = "http://jobs.example-employer.com/x"  # not https
        records, malformed = parse_greenhouse({"jobs": [bad]}, BOARD_A)
        self.assertEqual(records, [])
        self.assertEqual(malformed, 1)


class FetchSafety(unittest.TestCase):
    def test_http_error_is_held(self):
        opener = FakeOpener({"sample-a": urllib.error.HTTPError("u", 503, "down", {}, None)})
        with self.assertRaises(BoardError):
            fetch_payload(BOARD_A, opener)

    def test_network_error_is_held(self):
        opener = FakeOpener({"sample-a": OSError("refused")})
        with self.assertRaises(BoardError):
            fetch_payload(BOARD_A, opener)

    def test_invalid_json_is_held(self):
        opener = FakeOpener({"sample-a": b"{not json"})
        with self.assertRaises(BoardError):
            fetch_payload(BOARD_A, opener)

    def test_oversized_response_is_held(self):
        big = b"{" + b" " * 2_000_001 + b"}"
        opener = FakeOpener({"sample-a": big})
        with self.assertRaises(BoardError):
            fetch_payload(BOARD_A, opener)

    def test_redirect_is_refused_by_the_real_opener(self):
        from career.job_boards import _NoRedirects
        handler = _NoRedirects()
        self.assertIsNone(handler.redirect_request(None, None, 301, "Moved", {}, "https://elsewhere.example.com/"))

    def test_registry_rejects_bad_token_and_duplicates(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "boards.json"
            p.write_text(json.dumps([{"source": "greenhouse", "board_token": "bad token!"}]), encoding="utf-8")
            with self.assertRaises(BoardError):
                load_registry(p)
            p.write_text(json.dumps([{"source": "greenhouse", "board_token": "x"}, {"source": "greenhouse", "board_token": "x"}]), encoding="utf-8")
            with self.assertRaises(BoardError):
                load_registry(p)

    def test_committed_registry_is_empty(self):
        self.assertEqual(load_registry(), [])


class SyncRules(DiscoveryBase):
    def _run(self, bodies, registry=(BOARD_A,), today=TODAY):
        db = self.Session()
        opener = FakeOpener(bodies)
        report = run_sync(db, today, registry=list(registry), opener=opener)
        return db, report, opener

    def test_first_run_adds_then_rerun_updates_without_duplicates(self):
        bodies = {"sample-a": {"jobs": [gh_job(1), gh_job(2)]}}
        db, report, _ = self._run(bodies)
        self.assertEqual(report["boards"][0]["added"], 2)
        db2, report2, _ = self._run(bodies, today=TODAY + timedelta(days=1))
        self.assertEqual(report2["boards"][0]["updated"], 2)
        self.assertEqual(db2.query(JobPosting).count(), 2)

    def test_missing_posting_closes_on_a_complete_run(self):
        self._run({"sample-a": {"jobs": [gh_job(1), gh_job(2)]}})
        db, report, _ = self._run({"sample-a": {"jobs": [gh_job(1)]}}, today=TODAY + timedelta(days=1))
        self.assertEqual(report["boards"][0]["closed"], 1)
        closed = db.query(JobPosting).filter(JobPosting.closed_on.is_not(None)).one()
        self.assertEqual(closed.source_job_id, "2")

    def test_http_error_changes_nothing(self):
        self._run({"sample-a": {"jobs": [gh_job(1), gh_job(2)]}})
        db, report, _ = self._run({"sample-a": urllib.error.HTTPError("u", 500, "x", {}, None)}, today=TODAY + timedelta(days=1))
        self.assertEqual(report["boards"][0]["result"], "held")
        self.assertEqual(db.query(JobPosting).filter(JobPosting.closed_on.is_not(None)).count(), 0)

    def test_empty_list_while_open_is_held(self):
        self._run({"sample-a": {"jobs": [gh_job(1)]}})
        db, report, _ = self._run({"sample-a": {"jobs": []}}, today=TODAY + timedelta(days=1))
        self.assertIn("empty list", report["boards"][0]["close_held"])
        self.assertEqual(db.query(JobPosting).filter(JobPosting.closed_on.is_not(None)).count(), 0)

    def test_sharp_drop_is_held(self):
        self._run({"sample-a": {"jobs": [gh_job(i) for i in range(1, 11)]}})
        db, report, _ = self._run({"sample-a": {"jobs": [gh_job(1)]}}, today=TODAY + timedelta(days=1))
        self.assertIn("sharp drop", report["boards"][0]["close_held"])
        self.assertEqual(db.query(JobPosting).filter(JobPosting.closed_on.is_not(None)).count(), 0)

    def test_too_many_malformed_items_is_held(self):
        self._run({"sample-a": {"jobs": [gh_job(1), gh_job(2), gh_job(3)]}})
        bodies = {"sample-a": {"jobs": [gh_job(1), {"bad": 1}, {"bad": 2}]}}
        db, report, _ = self._run(bodies, today=TODAY + timedelta(days=1))
        self.assertIn("malformed", report["boards"][0]["close_held"])
        self.assertEqual(db.query(JobPosting).filter(JobPosting.closed_on.is_not(None)).count(), 0)

    def test_reappearing_posting_reopens(self):
        self._run({"sample-a": {"jobs": [gh_job(1), gh_job(2)]}})
        self._run({"sample-a": {"jobs": [gh_job(1)]}}, today=TODAY + timedelta(days=1))
        db, _, _ = self._run({"sample-a": {"jobs": [gh_job(1), gh_job(2)]}}, today=TODAY + timedelta(days=2))
        self.assertEqual(db.query(JobPosting).filter(JobPosting.closed_on.is_not(None)).count(), 0)

    def test_same_link_on_two_keys_is_listed_once(self):
        dup = gh_job(5)
        dup["absolute_url"] = "https://jobs.example-employer.com/sample-a/jobs/1?utm_source=x"
        bodies = {"sample-a": {"jobs": [gh_job(1), dup]}}
        db, report, _ = self._run(bodies)
        self.assertEqual(db.query(JobPosting).count(), 1)
        self.assertEqual(report["boards"][0]["duplicate_skipped"], 1)

    def test_closed_postings_are_deleted_after_fourteen_days(self):
        db = self.Session()
        self.add_posting(db, closed=TODAY - timedelta(days=20), job_id="old")
        self.add_posting(db, closed=TODAY - timedelta(days=3), job_id="recent")
        removed = purge_closed(db, TODAY)
        db.commit()
        self.assertEqual(removed, 1)
        self.assertEqual([p.source_job_id for p in db.query(JobPosting).all()], ["recent"])

    def test_central_fetch_reads_each_board_once_for_many_members(self):
        db = self.Session()
        for uid in (self.my_profile_id, self.other_profile_id):
            db.add(JobPreference(career_profile_id=uid, target_titles=[], locations=[], remote_ok=True, onsite_ok=True,
                                 employment_types=[], exclude_words=[], followed_boards=["greenhouse:sample-a"]))
        db.commit()
        db.close()
        _, _, opener = self._run({"sample-a": {"jobs": [gh_job(1)]}})
        self.assertEqual(opener.calls, ["sample-a"])

    def test_failed_board_does_not_stop_the_others(self):
        bodies = {"sample-a": urllib.error.HTTPError("u", 500, "x", {}, None), "sample-b": {"jobs": [ash_job("b1")]}}
        db, report, _ = self._run(bodies, registry=(BOARD_A, BOARD_B))
        results = {b["board"]: b["result"] for b in report["boards"]}
        self.assertEqual(results, {"greenhouse:sample-a": "held", "ashby:sample-b": "ok"})


class Matching(DiscoveryBase):
    def setUp(self):
        super().setUp()
        self.db = self.Session()
        self.prefs = {"target_titles": ["Program Manager"], "locations": ["Chicago"], "remote_ok": True, "onsite_ok": True,
                      "employment_types": ["full_time"], "min_base": None, "exclude_words": ["sales"], "followed_boards": []}
        self.terms = discovery.profile_terms(["Program Coordinator"], ["Grant reporting"])

    def test_remote_and_onsite_rules(self):
        remote = self.add_posting(self.db, job_id="r", title="Program Manager", arrangement="remote", location="Anywhere")
        self.prefs["remote_ok"] = False
        self.assertIsNone(discovery.match_posting(remote, self.prefs, self.terms))

    def test_location_and_excluded_words(self):
        far = self.add_posting(self.db, job_id="f", title="Program Manager", location="Denver, CO")
        self.assertIsNone(discovery.match_posting(far, self.prefs, self.terms))
        sales = self.add_posting(self.db, job_id="s", title="Program Manager, Sales", location="Chicago")
        self.assertIsNone(discovery.match_posting(sales, self.prefs, self.terms))

    def test_reasons_are_given(self):
        row = self.add_posting(self.db, job_id="g", title="Program Manager", location="Chicago, IL")
        result = discovery.match_posting(row, self.prefs, self.terms)
        self.assertIsNotNone(result)
        self.assertTrue(any("target role" in r for r in result["reasons"]))
        self.assertTrue(any("Location" in r for r in result["reasons"]))

    def test_ranking_is_deterministic_and_limited_to_ten(self):
        for i in range(12):
            self.add_posting(self.db, job_id=f"p{i}", title="Program Manager", location="Chicago")
        self.add_posting(self.db, job_id="closed", title="Program Manager", location="Chicago", closed=TODAY)
        postings = self.db.query(JobPosting).all()
        first = [p.id for p, _ in discovery.rank(postings, self.prefs, self.terms)]
        second = [p.id for p, _ in discovery.rank(list(reversed(postings)), self.prefs, self.terms)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 10)

    def test_no_follows_means_no_matches(self):
        self.add_posting(self.db, job_id="x", title="Program Manager", location="Chicago")
        self.assertEqual(self.client.get("/api/career/job-matches").json()["matches"], [])


class MatchesRoute(DiscoveryBase):
    def test_matches_only_from_followed_boards_and_flag_saved_links(self):
        import career.job_boards as jb
        import career.discovery_routes as dr
        boards = [BOARD_A, BOARD_B]
        with mock.patch.object(jb, "load_registry", return_value=boards), mock.patch.object(dr, "load_registry", return_value=boards):
            db = self.Session()
            followed = self.add_posting(db, job_id="1", title="Program Manager", location="Chicago")
            self.add_posting(db, board=BOARD_B, job_id="b1", title="Program Manager", location="Chicago", slug="sample-b")
            _, url_hash = normalize_job_url(followed.job_url)
            db.add(Opportunity(career_profile_id=self.my_profile_id, title="x", job_url=followed.job_url, dedupe_key=url_hash,
                               state="saved"))
            db.commit()
            followed_id = followed.id
            db.close()
            self.client.put("/api/career/job-preferences", json={"target_titles": ["Program Manager"], "locations": ["Chicago"],
                                                                 "followed_boards": ["greenhouse:sample-a"]})
            body = self.client.get("/api/career/job-matches").json()
            self.assertEqual([m["id"] for m in body["matches"]], [followed_id])
            self.assertTrue(body["matches"][0]["already_saved"])
            self.assertTrue(any("target role" in r for r in body["matches"][0]["reasons"]))

    def test_other_member_sees_only_their_own_matches(self):
        import career.job_boards as jb
        import career.discovery_routes as dr
        with mock.patch.object(jb, "load_registry", return_value=[BOARD_A]), mock.patch.object(dr, "load_registry", return_value=[BOARD_A]):
            self.client.put("/api/career/job-preferences", json={"target_titles": ["Program Manager"], "followed_boards": ["greenhouse:sample-a"]})
            self.current = self.other_id
            self.assertEqual(self.client.get("/api/career/job-matches").json()["matches"], [])


class MigrationOffline(unittest.TestCase):
    """Runs the 0012 upgrade and downgrade on a scratch SQLite database (structure only; the disposable PostgreSQL run is separate)."""
    def test_upgrade_creates_and_downgrade_removes_both_tables(self):
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import inspect
        spec = importlib.util.spec_from_file_location("m0012", os.path.join(os.path.dirname(__file__), "..", "alembic", "versions", "0012_add_job_discovery.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine, tables=[Base.metadata.tables["users"], Base.metadata.tables["career_profiles"]])
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mod.upgrade()
        names = set(inspect(engine).get_table_names())
        self.assertIn("job_postings", names)
        self.assertIn("job_preferences", names)
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mod.downgrade()
        names = set(inspect(engine).get_table_names())
        self.assertNotIn("job_postings", names)
        self.assertNotIn("job_preferences", names)


class AshbyResponseLimits(DiscoveryBase):
    """Ashby responses carry descriptions, so they have their own, larger, byte limit (5 MB). Greenhouse stays at 2 MB."""

    @staticmethod
    def _big_ashby(count: int, pad_chars: int):
        jobs = []
        for i in range(count):
            job = ash_job(f"big-{i}")
            job["descriptionHtml"] = "<p>" + "x" * pad_chars + "</p>"
            job["descriptionPlain"] = "x" * pad_chars
            jobs.append(job)
        return {"jobs": jobs}

    def test_valid_larger_ashby_response_is_accepted(self):
        body = json.dumps(self._big_ashby(143, 8_000)).encode("utf-8")  # about 2.3 MB: over the old 2 MB cap
        self.assertGreater(len(body), 2_000_000)
        records, malformed = fetch_board_records(BOARD_B, FakeOpener({"sample-b": body}))
        self.assertEqual(len(records), 143)
        self.assertEqual(malformed, 0)

    def test_oversized_ashby_response_is_held(self):
        body = json.dumps(self._big_ashby(40, 150_000)).encode("utf-8")  # about 6 MB: over the 5 MB Ashby cap
        self.assertGreater(len(body), 5_000_000)
        with self.assertRaises(BoardError) as ctx:
            fetch_board_records(BOARD_B, FakeOpener({"sample-b": body}))
        self.assertIn("too large", str(ctx.exception))

    def test_greenhouse_still_refuses_two_megabytes(self):
        body = json.dumps({"jobs": [gh_job(i) for i in range(10)], "pad": "y" * 2_200_000}).encode("utf-8")
        with self.assertRaises(BoardError):
            fetch_board_records(BOARD_A, FakeOpener({"sample-a": body}))

    def test_declared_length_over_the_limit_is_refused_before_reading(self):
        class Declared:
            status = 200
            headers = {"Content-Length": "9000000"}
            def read(self, n=-1):
                raise AssertionError("body must not be read when the declared length is over the limit")
            def __enter__(self): return self
            def __exit__(self, *exc): return False
        class Opener:
            def open(self, req, timeout=None): return Declared()
        with self.assertRaises(BoardError):
            fetch_board_records(BOARD_B, Opener())

    def test_truncated_ashby_response_is_held(self):
        full = json.dumps(self._big_ashby(20, 1_000)).encode("utf-8")
        with self.assertRaises(BoardError):
            fetch_board_records(BOARD_B, FakeOpener({"sample-b": full[: len(full) // 2]}))

    def test_failed_ashby_request_is_held(self):
        with self.assertRaises(BoardError):
            fetch_board_records(BOARD_B, FakeOpener({"sample-b": urllib.error.HTTPError("u", 500, "x", {}, None)}))
        with self.assertRaises(BoardError):
            fetch_board_records(BOARD_B, FakeOpener({"sample-b": OSError("refused")}))

    def test_unlisted_ashby_postings_are_excluded(self):
        jobs = [ash_job("listed-1"), ash_job("hidden-1", listed=False), ash_job("listed-2")]
        records, malformed = parse_ashby({"jobs": jobs}, BOARD_B)
        self.assertEqual(sorted(r["source_job_id"] for r in records), ["listed-1", "listed-2"])
        self.assertEqual(malformed, 0)

    def test_oversized_response_changes_no_posting_state(self):
        db, report, _ = self._run_ashby({"sample-b": {"jobs": [ash_job("keep-1"), ash_job("keep-2")]}})
        self.assertEqual(report["boards"][0]["result"], "ok")
        body = json.dumps(self._big_ashby(40, 150_000)).encode("utf-8")
        db2, report2, _ = self._run_ashby({"sample-b": body}, today=TODAY + timedelta(days=1))
        self.assertEqual(report2["boards"][0]["result"], "held")
        self.assertEqual(db2.query(JobPosting).filter(JobPosting.closed_on.is_not(None)).count(), 0)
        self.assertEqual(db2.query(JobPosting).count(), 2)

    def _run_ashby(self, bodies, today=TODAY):
        db = self.Session()
        report = run_sync(db, today, registry=[BOARD_B], opener=FakeOpener(bodies))
        return db, report, None


if __name__ == "__main__":
    unittest.main()
