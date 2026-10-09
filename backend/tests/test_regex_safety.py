"""CodeQL flagged four patterns that could be made slow by a long crafted input (run 2026-10-09). They are now bounded;
these tests keep the same answers on normal text and a tight time limit on hostile text."""
import time
import unittest

from career import job_fit, linkedin_compare


class SameAnswersOnNormalText(unittest.TestCase):
    def test_labels_split_the_same_way(self):
        self.assertEqual(linkedin_compare._labels("Pre-sales / Solutions Consulting - supported by the CashPro role"),
                         ["Pre-sales", "Solutions Consulting"])
        self.assertEqual(linkedin_compare._labels("Project Management (PMP)"), ["Project Management"])
        self.assertEqual(linkedin_compare._labels("  Data   Analysis\t/\nReporting  "), ["Data Analysis", "Reporting"])
        self.assertEqual(linkedin_compare._labels("Leadership: led a team of eight people across three regions"), ["Leadership"])

    def test_norm_drops_bracketed_notes(self):
        self.assertEqual(job_fit._norm("Python (3+ years) and SQL"), "python and sql")
        self.assertEqual(job_fit._norm(None), "")


class HostileTextStaysFast(unittest.TestCase):
    LIMIT = 0.5  # seconds; the unbounded patterns took far longer on inputs this size

    def timed(self, fn, arg):
        start = time.perf_counter()
        fn(arg)
        return time.perf_counter() - start

    def test_long_whitespace_and_dash_runs(self):
        self.assertLess(self.timed(linkedin_compare._labels, "a" + " " * 40000 + "x"), self.LIMIT)
        self.assertLess(self.timed(linkedin_compare._labels, "a" + " -" * 20000), self.LIMIT)
        self.assertLess(self.timed(linkedin_compare._labels, "a" + " / " * 20000), self.LIMIT)

    def test_piles_of_unclosed_brackets(self):
        self.assertLess(self.timed(linkedin_compare._labels, "(" * 40000), self.LIMIT)
        self.assertLess(self.timed(job_fit._norm, "(" * 40000), self.LIMIT)
        self.assertLess(self.timed(job_fit._norm, "(a" * 20000), self.LIMIT)


if __name__ == "__main__":
    unittest.main()
