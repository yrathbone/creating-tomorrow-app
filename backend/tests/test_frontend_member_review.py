"""C-52 frontend round: static and node regression checks for the member résumé review and the stored-version downloads.

Covers: the review screen and its server-text safety, the Edit and sign-off wiring, the download routes (general and job-targeted),
/api/generate kept for the three public tools only, and the node unit tests of the review rules.
Run from the backend folder:  py -3.12 -m unittest tests.test_frontend_member_review -v
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "career")
JS = os.path.join(ROOT, "js")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf8") as f:
        return f.read()


class MemberReviewStaticChecks(unittest.TestCase):
    def test_member_pages_never_call_the_public_generate_endpoint(self):
        for name in ("generalResume.js", "jobMatch.js", "generalResumeReview.js", "resumeTruthModel.js"):
            with self.subTest(name=name):
                self.assertNotIn("/api/generate", read(JS, name))

    def test_public_tools_keep_the_generate_endpoint(self):
        for name in ("app.js", "scratch.js", "elevate.js"):
            with self.subTest(name=name):
                self.assertIn("/api/generate", read(ROOT, "..", name))

    def test_general_download_reads_the_signed_document_or_the_stored_version_only(self):
        src = read(JS, "generalResume.js")
        self.assertIn("downloadSignedGeneralResume(fileName)", src)
        self.assertIn('"/download?ats_mode=false&template="', src)
        self.assertIn("generalReview.isSigned()", src)           # no download before sign-off when the switch is ON
        self.assertIn('"/document"', read(JS, "generalResumeReview.js"))
        self.assertIn("createMemberReview", read(JS, "generalResumeReview.js"))

    def test_job_download_reads_the_stored_version_and_needs_one(self):
        src = read(JS, "jobMatch.js")
        self.assertIn('"/api/career/resume-versions/" + encodeURIComponent(jobState.resumeVersionId) + "/download?ats_mode=false', src)
        self.assertIn("if (!jobState.resumeVersionId)", src)

    def test_review_is_shown_only_when_the_server_says_the_switch_is_on(self):
        src = read(JS, "generalResume.js")
        self.assertIn('generalResumeState.truthGate === "on"', src)
        self.assertIn("data.truth_gate", src)

    def test_review_text_from_the_server_is_written_as_text_not_html(self):
        for name in ("generalResumeReview.js", "resumeTruthModel.js"):
            with self.subTest(name=name):
                self.assertNotIn("innerHTML", read(JS, name))
                self.assertNotIn("insertAdjacentHTML", read(JS, name))

    def test_every_review_control_has_visible_text_or_a_label(self):
        html = read(ROOT, "login.html")
        section = html[html.index('id="general-review"'):html.index('id="general-resume-download-btn"')]
        for control in ("general-review-preview-btn", "general-review-signoff-btn", "general-review-signoff-check"):
            self.assertIn(control, section)
        self.assertIn('<label class="field truth-signoff">', section)
        self.assertIn('aria-live="polite"', section)            # status changes are announced
        self.assertIn('role="status" aria-live="assertive"', section)  # review errors are announced; the page keeps its two role=alert boxes
        review = read(JS, "generalResumeReview.js")
        self.assertIn('span.textContent = "Your wording for this statement"', review)   # the Edit field has a label
        self.assertIn("aria-describedby", review)                 # each action is linked to its statement

    def test_review_sections_are_headed_lists(self):
        html = read(ROOT, "login.html")
        for heading in ("general-review-supported-h", "general-review-derived-h", "general-review-uncertain-h", "general-review-removed-h"):
            self.assertIn(f'id="{heading}"', html)
        self.assertIn('id="general-review-heading" tabindex="-1"', html)

    def test_scripts_load_in_dependency_order(self):
        html = read(ROOT, "login.html")
        self.assertLess(html.index("js/resumeDownload.js"), html.index("js/resumeTruthModel.js"))
        self.assertLess(html.index("js/resumeTruthModel.js"), html.index("js/generalResumeReview.js"))
        self.assertLess(html.index("js/generalResumeReview.js"), html.index("js/jobMatch.js"))
        self.assertLess(html.index("js/generalResumeReview.js"), html.index("js/generalResume.js"))

    def test_the_job_card_reuses_the_same_review_component_with_its_own_ids(self):
        html = read(ROOT, "login.html")
        section = html[html.index('id="job-review"'):html.index('id="job-download-btn"')]
        for control in ("job-review-preview-btn", "job-review-signoff-btn", "job-review-signoff-check", "job-review-recheck-btn", "job-review-status"):
            self.assertIn(control, section)
        job = read(JS, "jobMatch.js")
        self.assertIn('createMemberReview({ prefix: "job-review", downloadId: "job-download-btn", recheck: true })', job)
        self.assertIn("jobReview.download(", job)
        self.assertIn('if (jobState.truthGate === "on")', job)
        self.assertIn("jobState.truthGate = data.truth_gate", job)
        self.assertIn("if (!jobReview.isSigned())", job)            # a job download is refused unless signed when the switch is ON


@unittest.skipUnless(shutil.which("node"), "node is not installed: the review-rule tests are NOT RUN")
class ReviewRuleUnitTests(unittest.TestCase):
    def test_node_unit_tests_pass(self):
        here = os.path.dirname(__file__)
        result = subprocess.run(["node", "--test", os.path.join(here, "frontend", "resumeTruthModel.test.js")], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
