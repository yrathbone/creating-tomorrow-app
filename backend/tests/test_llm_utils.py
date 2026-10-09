"""The server log line written when a call to the AI service fails: says what kind of failure it was, never what was sent."""
import glob
import os
import re
import unittest

import anthropic
try:  # the pinned AI library uses httpx2; older setups still have httpx
    import httpx2 as httpx
except ImportError:
    import httpx

from llm_utils import describe_provider_error

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _status_error(cls, status, body):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                              headers={"request-id": "req_test123"})
    return cls("provider text", response=response, body=body)


class DescribeProviderErrorTests(unittest.TestCase):
    def test_credit_problem_is_recognisable(self):
        e = _status_error(anthropic.BadRequestError, 400,
                          {"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low to access the API."}})
        line = describe_provider_error(e)
        self.assertIn("class=BadRequestError", line)
        self.assertIn("status=400", line)
        self.assertIn("type=invalid_request_error", line)
        self.assertIn("credit balance is too low", line)
        self.assertIn("request_id=req_test123", line)

    def test_unknown_model_and_rate_limit_are_distinguishable(self):
        nf = describe_provider_error(_status_error(anthropic.NotFoundError, 404, {"error": {"type": "not_found_error", "message": "model: x"}}))
        rl = describe_provider_error(_status_error(anthropic.RateLimitError, 429, {"error": {"type": "rate_limit_error", "message": "slow down"}}))
        self.assertIn("status=404", nf)
        self.assertIn("type=not_found_error", nf)
        self.assertIn("status=429", rl)
        self.assertIn("type=rate_limit_error", rl)

    def test_a_connection_failure_has_no_status_and_does_not_crash(self):
        e = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
        line = describe_provider_error(e)
        self.assertIn("class=APIConnectionError", line)
        self.assertIn("status=?", line)

    def test_long_messages_are_cut_and_newlines_removed(self):
        e = _status_error(anthropic.BadRequestError, 400, {"error": {"type": "invalid_request_error", "message": "line one\nline two " + "x" * 500}})
        line = describe_provider_error(e)
        self.assertNotIn("\n", line)
        self.assertLess(len(line), 400)


class EveryToolLogsTheErrorTests(unittest.TestCase):
    def test_every_provider_failure_log_carries_the_details(self):
        files = glob.glob(os.path.join(BACKEND, "*.py")) + glob.glob(os.path.join(BACKEND, "career", "*.py"))
        seen = 0
        for path in files:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            if "describe_provider_error" in src and os.path.basename(path) == "llm_utils.py":
                continue
            for m in re.finditer(r'_diagnose\("provider_error[^\n]*', src):
                seen += 1
                self.assertIn("describe_provider_error(e)", m.group(0), f"{path}: provider failure logged without its details")
                before = src[: m.start()].rsplit("except", 1)[-1]
                self.assertIn("as e", before.split(":", 1)[0] + ":", f"{path}: the failure log must be inside 'except ... as e'")
        self.assertGreaterEqual(seen, 10, "every tool module keeps its provider-failure log")


if __name__ == "__main__":
    unittest.main()
