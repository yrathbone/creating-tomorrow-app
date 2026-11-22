"""C-46: the validation attempt budget for job_match._call_with_retry (CAREER_AI_ATTEMPT_LIMIT) and its one-way latch.

Design: RP-0009 addendum 02 (C-46_REVISED-DESIGN.md, tests A to H) and addendum 03 (C-46_ARMED-LATCH.md, tests I1 to I8).
The budget is NOT an account-wide Anthropic spending limit: it counts and limits only the career calls that go through
job_match._call_with_retry. The public tools, the career gap interview (elevate), resume upload, skill scan and the AI key
check are outside it; while it is set, the four career routes among those are closed instead.

Everything here is mocked: a fake anthropic.Anthropic records how it was built and every messages.create call. Fictional
data, a fake key value, no network, no live calls.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import contextlib
import io
import os
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx

import abuse_guard
import elevate
from career import job_match, term_pipeline
from tests.test_ownership import OwnershipTestCase

ENV = job_match.ATTEMPT_LIMIT_ENV
LABELS = ("career_job_compare", "career_term_plan", "career_job_build_resume")
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- fakes ---------------------------------------------------------------------------------------------------------------
def tool_reply(data_by_tool=None):
    """A valid forced-tool reply for whichever tool the call asked for."""
    def reply(kwargs):
        name = kwargs["tool_choice"]["name"]
        data = (data_by_tool or {}).get(name, {"ok": True})
        block = SimpleNamespace(type="tool_use", name=name, input=dict(data))
        return SimpleNamespace(content=[block], stop_reason="tool_use", model="fake-model",
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return reply


def malformed_reply(kwargs):
    """A reply with no tool call: _call_with_retry treats it as unusable and makes its one app-level retry."""
    return SimpleNamespace(content=[], stop_reason="end_turn", model="fake-model", usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def provider_error(kwargs):
    raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://example.invalid/v1/messages"))


class FakeAnthropic:
    """Stands in for anthropic.Anthropic. `replies` is a list of callables taking the create() kwargs; the last one repeats."""

    def __init__(self, replies=None, on_create=None):
        self.replies = list(replies or [tool_reply()])
        self.on_create = on_create
        self.constructed = []          # kwargs of every Anthropic(...) construction
        self.calls = []                # kwargs of every messages.create(...)
        self.used_seen_at_create = []  # the budget counter as seen inside create (slot already taken?)
        self.lock = threading.Lock()

    def __call__(self, **kwargs):
        self.constructed.append(kwargs)
        return SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        with self.lock:
            self.calls.append(kwargs)
            self.used_seen_at_create.append(job_match._budget["used"])
            reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if self.on_create:
            self.on_create(len(self.calls))
        return reply(kwargs)


def compare_tool_data():
    return {"submit_job_comparison": {"job_title": "Fictional role", "match_report": {}, "categories": [], "questions": []}}


def call(label="career_job_compare"):
    return job_match._call_with_retry(label, "system", "user", {"name": "submit_job_comparison"},
                                      extract=lambda r: job_match._extract_tool_input(r, "submit_job_comparison", ("job_title",)))


class BudgetCase(unittest.TestCase):
    """Fresh budget per test, a fake key, the limit unset unless a test sets it; afterwards the budget is reset with the
    environment already restored, so no latch leaks into other test files."""

    def setUp(self):
        super().setUp()
        self.addCleanup(job_match._reset_attempt_budget_for_tests)  # registered first, so it runs last
        patcher = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-not-real"})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(ENV, None)
        with contextlib.redirect_stdout(io.StringIO()):
            job_match._reset_attempt_budget_for_tests()

    def set_limit(self, value, restart=True):
        """Set CAREER_AI_ATTEMPT_LIMIT; with restart=True, as a process that starts with it (the deployed case)."""
        if value is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = value
        if restart:
            return self.quiet(job_match._reset_attempt_budget_for_tests)
        return ""

    def fake(self, *replies, on_create=None):
        fake = FakeAnthropic(list(replies) or [tool_reply(compare_tool_data())], on_create)
        patcher = mock.patch.object(job_match.anthropic, "Anthropic", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def quiet(self, fn, *args, **kwargs):
        """Runs fn, returns its printed output (and re-raises after capturing)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fn(*args, **kwargs)
        return out.getvalue()

    def hammer(self, threads):
        barrier = threading.Barrier(threads)
        results = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            try:
                call()
                outcome = "sent"
            except job_match.JobMatchError:
                outcome = "refused"
            with lock:
                results.append(outcome)

        with contextlib.redirect_stdout(io.StringIO()):
            pool = [threading.Thread(target=worker) for _ in range(threads)]
            for t in pool:
                t.start()
            for t in pool:
                t.join(timeout=30)
        return results

    def run_call(self, label="career_job_compare"):
        """(result or the JobMatchError, printed output)"""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                result = call(label)
            except job_match.JobMatchError as e:
                result = e
        return result, out.getvalue()


# --- A: OFF ----------------------------------------------------------------------------------------------------------------
class A_Off(BudgetCase):
    def test_A1_unset_builds_the_default_client_and_counts_nothing(self):
        fake = self.fake()
        result, out = self.run_call()
        self.assertEqual(result["job_title"], "Fictional role")
        self.assertEqual(fake.constructed, [{}], "OFF must build anthropic.Anthropic() exactly as before (SDK retries kept)")
        self.assertNotIn("[ai-attempt]", out)
        self.assertNotIn("[ai-budget]", out)

    def test_A2_empty_or_spaces_is_off(self):
        for value in ("", "   "):
            with self.subTest(value=repr(value)):
                self.set_limit(value)
                fake = self.fake()
                result, out = self.run_call()
                self.assertNotIsInstance(result, Exception)
                self.assertEqual(fake.constructed, [{}])
                self.assertNotIn("[ai-", out)

    def test_A3_off_keeps_the_app_retry_on_a_malformed_reply(self):
        fake = self.fake(malformed_reply, tool_reply(compare_tool_data()))
        result, out = self.run_call()
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.constructed, [{}], "one default client for both attempts, as before")
        self.assertNotIn("[ai-attempt]", out)

    def test_A4_off_has_no_hidden_limit(self):
        fake = self.fake()
        for _ in range(20):
            result, _ = self.run_call()
            self.assertNotIsInstance(result, Exception)
        self.assertEqual(len(fake.calls), 20)
        self.assertEqual(job_match._budget["used"], 0)


# --- B: ARMED --------------------------------------------------------------------------------------------------------------
class B_Armed(BudgetCase):
    def test_B1_armed_disables_sdk_retries_and_logs_the_attempt(self):
        startup = self.set_limit("8")
        self.assertIn(f"[ai-budget] armed boot={job_match._budget['boot']} limit=8", startup)
        fake = self.fake()
        result, out = self.run_call("career_job_compare")
        self.assertNotIsInstance(result, Exception)
        self.assertEqual(fake.constructed, [{"max_retries": 0}])
        self.assertIn(f"[ai-attempt] boot={job_match._budget['boot']} tool=career_job_compare n=1 limit=8", out)

    def test_B1b_log_lines_hold_no_prompt_or_reply_text(self):
        self.set_limit("8")
        self.fake()
        _, out = self.run_call()
        lines = [line for line in out.splitlines() if line.startswith("[ai-")]
        self.assertTrue(lines)
        for line in lines:
            for secret_or_content in ("Fictional role", "test-key-not-real", "system", "user"):
                self.assertNotIn(secret_or_content, line)

    def test_B2_the_slot_is_taken_before_the_request_is_sent(self):
        self.set_limit("8")
        fake = self.fake()
        self.run_call()
        self.assertEqual(fake.used_seen_at_create, [1], "inside create() the counter must already show this attempt")

    def test_B3_an_app_retry_takes_a_second_slot(self):
        self.set_limit("8")
        fake = self.fake(malformed_reply, tool_reply(compare_tool_data()))
        _, out = self.run_call()
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(job_match._budget["used"], 2)
        self.assertIn("n=1 limit=8", out)
        self.assertIn("n=2 limit=8", out)

    def test_B4_a_provider_error_uses_its_slot_and_is_not_retried(self):
        self.set_limit("8")
        fake = self.fake(provider_error)
        result, _ = self.run_call()
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.constructed, [{"max_retries": 0}])
        self.assertEqual(job_match._budget["used"], 1)

    def test_B5_one_counter_is_shared_across_labels(self):
        self.set_limit("8")
        self.fake()
        outs = [self.run_call(label)[1] for label in LABELS]
        for n, (label, out) in enumerate(zip(LABELS, outs), start=1):
            self.assertIn(f"tool={label} n={n} limit=8", out)


# --- C: refusal before sending ---------------------------------------------------------------------------------------------
PROFILE = "EXPERIENCE:\n- Shift Lead at Hearthside Home Goods (2021 - Present)\n  * Logged customer cases in ticketing software\n  * Handled returns"
POSTING = "Customer Success Associate\nResolve cases in ticketing software."
WRITER_RESUME = {"name": "N", "contact": "c@example.com", "headline": "Shift lead", "summary": "Shift lead who handled returns.",
                 "skills": ["Returns handling"], "education": [], "certifications": [],
                 "experience": [{"title": "Shift Lead", "organization": "Hearthside Home Goods", "dates": "2021 - Present",
                                 "bullets": ["Handled returns"]}]}
SAVED_PLAN = [{"term": "Ticketing software", "importance": "required", "kind": "skill", "support": "literal",
               "evidence": "Logged customer cases in ticketing software", "denied": False, "alternatives_group": "",
               "accepts_equivalent_experience": False}]


class C_RefusedBeforeSending(BudgetCase):
    def build(self, saved_terms):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                result = term_pipeline.build_checked_resume(PROFILE, POSTING, [], "N", "c@example.com", saved_terms=saved_terms)
            except job_match.JobMatchError as e:
                result = e
        return result, out.getvalue()

    def writer_fake(self):
        return self.fake(tool_reply({"submit_tailored_resume": {"resume_data": WRITER_RESUME},
                                     "submit_term_plan": {"terms": SAVED_PLAN}}))

    def test_C1_the_attempt_after_the_limit_is_refused_without_being_sent(self):
        self.set_limit("2")
        fake = self.fake()
        self.run_call()
        self.run_call()
        result, out = self.run_call()
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(len(fake.calls), 2, "the third attempt must never reach messages.create")
        self.assertIn("[ai-budget] refused", out)
        self.assertIn("reason=limit_reached used=2 limit=2", out)
        self.assertEqual(job_match._budget["used"], 2)

    def test_C2_limit_zero_refuses_the_first_call(self):
        self.set_limit("0")
        fake = self.fake()
        result, out = self.run_call()
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(fake.calls, [])
        self.assertIn("reason=limit_reached used=0 limit=0", out)

    def test_C3_a_build_at_limit_1_sends_only_the_writer_and_still_returns_a_checked_resume(self):
        self.set_limit("1")
        fake = self.writer_fake()
        result, out = self.build(SAVED_PLAN)
        self.assertNotIsInstance(result, Exception, out)
        self.assertEqual([c["tool_choice"]["name"] for c in fake.calls], ["submit_tailored_resume"])
        self.assertEqual(job_match._budget["used"], 1)
        self.assertIn("tool=career_term_revise reason=limit_reached", out, "the fix-up is refused without a request")
        for key in ("resume_data", "truth_notice", "claims_struck", "skills_removed"):
            self.assertIn(key, result, "the code-only truth checks still run")

    def test_C4_limit_0_refuses_the_writer_and_the_build_fails_cleanly(self):
        self.set_limit("0")
        fake = self.writer_fake()
        result, out = self.build(SAVED_PLAN)
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(fake.calls, [])

    def test_C5_without_a_saved_plan_the_plan_takes_the_only_slot_and_the_writer_is_refused(self):
        self.set_limit("1")
        fake = self.writer_fake()
        result, out = self.build(None)
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual([c["tool_choice"]["name"] for c in fake.calls], ["submit_term_plan"])
        self.assertIn("tool=career_job_build_resume reason=limit_reached", out)


# --- D: invalid configuration fails closed -------------------------------------------------------------------------------
class D_Invalid(BudgetCase):
    def test_D1_invalid_values_refuse_every_call_before_sending(self):
        for value in ("eight", "8.5", "-1", "101", "+8", "8 8", "٨"):
            with self.subTest(value=value):
                startup = self.set_limit(value)
                self.assertIn("limit=invalid_config", startup)
                fake = self.fake()
                result, out = self.run_call()
                self.assertIsInstance(result, job_match.JobMatchError)
                self.assertEqual(fake.calls, [])
                self.assertIn("reason=invalid_config", out)

    def test_D2_the_accepted_range_is_0_to_100(self):
        for value, expected in (("0", ("armed", 0)), ("8", ("armed", 8)), (" 8 ", ("armed", 8)), ("100", ("armed", 100)),
                                ("101", ("invalid", None)), (None, ("off", None))):
            with self.subTest(value=value):
                self.set_limit(value, restart=False)
                self.assertEqual(job_match._read_attempt_mode(), expected)


# --- E: concurrency ------------------------------------------------------------------------------------------------------
class E_Concurrency(BudgetCase):
    def test_E1_32_simultaneous_calls_send_exactly_8(self):
        for _ in range(50):
            self.set_limit("8")
            fake = self.fake()
            results = self.hammer(32)
            self.assertEqual(len(fake.calls), 8)
            self.assertEqual(results.count("sent"), 8)
            self.assertEqual(results.count("refused"), 24)
            self.assertEqual(sorted(fake.used_seen_at_create)[-1], 8)
            self.assertEqual(job_match._budget["used"], 8)

    def test_E2_retrying_calls_never_exceed_the_limit_together(self):
        self.set_limit("8")
        fake = self.fake(malformed_reply)  # every reply unusable: each call wants two slots
        self.hammer(16)
        self.assertLessEqual(len(fake.calls), 8)
        self.assertEqual(len(fake.calls), job_match._budget["used"])


# --- F: routes outside the budget, public tools, key check ---------------------------------------------------------------
JOB_TEXT = "Senior analyst wanted. Requires five years of experience with reporting, budgeting and stakeholder communication."
FILE = {"resume_file": ("resume.txt", b"Fictional person. Cashier at a store for five years.", "text/plain")}
CLOSED_ROUTES = {
    "/job-discover": ({"json": {"resume_data": {"roles": []}}}, "discover"),
    "/resume-discover": ({"json": {"resume_data": {"roles": []}}}, "discover"),
    "/resume-start": ({"files": FILE}, "start_resume_review"),
    "/skill-scan": ({}, "start_skill_scan"),
}


class F_RoutesAndPublicTools(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(job_match._reset_attempt_budget_for_tests)
        for patcher in (mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
                        mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter())):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop(ENV, None)
        with contextlib.redirect_stdout(io.StringIO()):
            job_match._reset_attempt_budget_for_tests()
        abuse_guard.IN_FLIGHT.reset()
        self.onboard(self.a)

    def arm(self, value):
        os.environ[ENV] = value
        with contextlib.redirect_stdout(io.StringIO()):
            job_match._reset_attempt_budget_for_tests()

    def post(self, path, kwargs, ai_function):
        out = io.StringIO()
        with mock.patch(f"career.routes.{ai_function}", return_value={"stage": "questions", "questions": []}) as ai, \
                mock.patch("career.routes.extract_text_async", new=mock.AsyncMock(return_value="Fictional resume text")), \
                mock.patch("anthropic.Anthropic") as client, contextlib.redirect_stdout(out):
            res = self.call("POST", path, self.a, **kwargs)
        return res, ai, client, out.getvalue()

    def test_F0_exactly_the_four_routes_carry_the_closure_check(self):
        from career.routes import router
        closing = {r.path for r in router.routes
                   if any(getattr(d.call, "__qualname__", "").startswith("_closed_while_attempt_guard_active") for d in r.dependant.dependencies)}
        self.assertEqual(closing, set(CLOSED_ROUTES))

    def test_F1_off_the_four_routes_reach_their_ai_function_as_before(self):
        for path, (kwargs, ai_function) in CLOSED_ROUTES.items():
            with self.subTest(route=path):
                res, ai, _, out = self.post(path, kwargs, ai_function)
                self.assertNotEqual(res.status_code, 503, res.text)
                ai.assert_called_once()
                self.assertNotIn("[ai-budget]", out)

    def test_F2_armed_or_invalid_the_four_routes_are_closed_before_any_ai_code(self):
        for value in ("8", "eight"):
            self.arm(value)
            for path, (kwargs, ai_function) in CLOSED_ROUTES.items():
                with self.subTest(value=value, route=path):
                    res, ai, client, out = self.post(path, kwargs, ai_function)
                    self.assertEqual(res.status_code, 503, res.text)
                    self.assertEqual(res.headers.get("X-AI-Status"), "unavailable")
                    ai.assert_not_called()
                    client.assert_not_called()
                    self.assertIn(f"[ai-budget] closed boot={job_match._budget['boot']} route={path}", out)
            self.assertEqual(abuse_guard.IN_FLIGHT.count, 0, "a closed route must give back its AI slot")

    def test_F3_public_modules_do_not_use_the_guard_and_elevate_is_unchanged(self):
        for module in ("upgrade.py", "coach.py", "elevate.py", "prepare.py", "profile_review.py", "resume_ingestion.py", "scratch.py",
                       "ai_health.py", "main.py"):
            with self.subTest(module=module):
                source = open(os.path.join(BACKEND, module), encoding="utf-8").read()
                self.assertNotIn("job_match", source)
                self.assertNotIn(ENV, source)
        self.arm("0")  # even with a zero budget, a public helper is neither counted nor refused
        fake = FakeAnthropic([tool_reply()])
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-not-real"}), \
                mock.patch.object(elevate.anthropic, "Anthropic", fake), contextlib.redirect_stdout(io.StringIO()):
            result = elevate._call_with_retry("elevate_start", "system", "user", [{"name": "t"}], {"type": "tool", "name": "t"},
                                              extract=lambda r: {"ok": True})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(fake.constructed, [{}], "public Elevate keeps the default client")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(job_match._budget["used"], 0)

    def test_I3_after_I1_the_four_routes_stay_closed(self):
        self.arm("8")
        os.environ.pop(ENV, None)  # switched off in the same process
        for path, (kwargs, ai_function) in CLOSED_ROUTES.items():
            with self.subTest(route=path):
                res, ai, client, _ = self.post(path, kwargs, ai_function)
                self.assertEqual(res.status_code, 503, res.text)
                ai.assert_not_called()
                client.assert_not_called()
        self.assertTrue(job_match._budget["run_invalid"])

    def test_F4_the_ai_key_check_is_unchanged(self):
        source = open(os.path.join(BACKEND, "ai_health.py"), encoding="utf-8").read()
        self.assertIn("max_retries=0", source)
        self.assertNotIn("job_match", source)


# --- G: boot id and start-up line ----------------------------------------------------------------------------------------
class G_BootAndStartup(BudgetCase):
    def test_G1_one_boot_per_process_and_a_restart_starts_again_at_1(self):
        self.set_limit("8")
        self.fake()
        boot = job_match._budget["boot"]
        outs = [self.run_call()[1] for _ in range(3)]
        self.assertTrue(all(f"boot={boot}" in o for o in outs))
        self.set_limit("8")  # simulated restart: a new process with the same setting
        self.assertNotEqual(job_match._budget["boot"], boot)
        _, out = self.run_call()
        self.assertIn("n=1 limit=8", out, "the counter restarts; the B7 procedure treats this as STOP (INVALID run)")

    def test_G2_the_startup_line_is_printed_only_when_armed(self):
        self.assertIn("[ai-budget] armed", self.set_limit("8"))
        self.assertEqual(self.set_limit(None), "")


# --- I: the one-way latch (addendum 03) ----------------------------------------------------------------------------------
class I_Latch(BudgetCase):
    def test_I1_armed_then_off_in_the_same_process_is_refused_and_invalidates_the_run(self):
        self.set_limit("8")
        fake = self.fake()
        first, _ = self.run_call()
        self.assertNotIsInstance(first, Exception)
        self.set_limit(None, restart=False)  # the setting disappears while the same process keeps running
        result, out = self.run_call()
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(len(fake.calls), 1, "nothing may be sent after the change")
        self.assertNotIn({}, fake.constructed, "a client with SDK retries must never be built after arming")
        self.assertIn("reason=disarmed_while_armed", out)
        self.assertEqual(out.count("RUN INVALID"), 1)
        self.assertEqual(job_match._budget["used"], 1)

    def test_I2_after_I1_everything_stays_refused_and_run_invalid_is_logged_once(self):
        self.set_limit("8")
        fake = self.fake()
        self.run_call()
        self.set_limit("", restart=False)
        outs = "".join(self.run_call()[1] for _ in range(6))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(outs.count("RUN INVALID"), 1)
        self.assertEqual(outs.count("reason=disarmed_while_armed"), 6)

    def test_I4_raising_the_limit_in_process_is_not_a_new_allowance(self):
        self.set_limit("8")
        fake = self.fake()
        self.run_call()
        self.set_limit("20", restart=False)
        result, out = self.run_call()
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("RUN INVALID", out)

    def test_I5_armed_then_invalid_stays_latched_and_invalid(self):
        self.set_limit("8")
        fake = self.fake()
        self.run_call()
        self.set_limit("eight", restart=False)
        result, out = self.run_call()
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(len(fake.calls), 1)
        self.set_limit("8", restart=False)  # even putting the old value back does not reopen it
        result, _ = self.run_call()
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(len(fake.calls), 1)

    def test_I6_never_armed_means_no_latch_and_todays_behaviour(self):
        fake = self.fake()
        for _ in range(3):
            self.run_call()
        self.assertIsNone(job_match._budget["latched"])
        self.assertEqual(fake.constructed, [{}, {}, {}], "one default client per call, exactly as before")
        self.assertEqual(len(fake.calls), 3)

    def test_I7_switching_off_during_concurrent_calls_sends_nothing_new(self):
        self.set_limit("8")
        flip = {}

        def on_create(n):
            if n == 2 and not flip:
                with job_match._budget_lock:
                    os.environ.pop(ENV, None)
                    flip["used"] = job_match._budget["used"]

        fake = self.fake(tool_reply(compare_tool_data()), on_create=on_create)
        self.hammer(16)
        self.assertTrue(flip, "the setting was switched off mid-run")
        self.assertEqual(job_match._budget["used"], flip["used"], "no slot may be taken after the switch")
        self.assertEqual(len(fake.calls), job_match._budget["used"], "every request that was sent was counted")
        self.assertNotIn({}, fake.constructed)
        sent = len(fake.calls)
        result, out = self.run_call()  # the next attempt after the switch (some threads may all have finished before it)
        self.assertIsInstance(result, job_match.JobMatchError)
        self.assertEqual(len(fake.calls), sent)
        self.assertTrue(job_match._budget["run_invalid"])


class I8_RestartDetection(BudgetCase):
    def test_I8_a_restart_into_off_leaves_usage_lines_without_attempt_lines(self):
        """Documents why the B7 procedure needs its log rule: a new process started OFF prints no armed line and no
        [ai-attempt] lines, but its successful career calls still print [usage] lines with the new boot unannounced."""
        self.set_limit("8")
        self.fake()
        boot = job_match._budget["boot"]
        _, armed_out = self.run_call()
        restart_out = self.set_limit(None)  # simulated restart into OFF
        _, off_out = self.run_call()
        self.assertIn(f"[ai-attempt] boot={boot}", armed_out)
        self.assertEqual(restart_out, "", "no armed line for the new boot")
        self.assertIn("[usage] tool=career_job_compare", off_out)
        self.assertNotIn("[ai-attempt]", off_out)


if __name__ == "__main__":
    unittest.main()
