"""Job Fit is computed in code from the comparison's requirement lists.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import unittest

from career.job_fit import compute_job_fit


def req(name, importance="required"):
    return {"requirement": name, "importance": importance}


def gap(name, importance="required", status="missing", how=""):
    return {"requirement": name, "importance": importance, "status": status, "explanation": "x", "how_to_close": how}


class JobFit(unittest.TestCase):
    def report(self, met, gaps):
        return {"requirements_met": met, "required_qualification_gaps": gaps}

    def test_none_when_the_met_list_is_missing(self):
        self.assertIsNone(compute_job_fit({"required_qualification_gaps": [gap("CTP")]}))

    def test_all_met_is_an_A(self):
        fit = compute_job_fit(self.report([req("a"), req("b"), req("c", "preferred")], []))
        self.assertEqual((fit["pct"], fit["letter"]), (100, "A"))

    def test_weights_required_over_preferred(self):
        # required met (3), preferred missing (2): 3/5 = 60%
        fit = compute_job_fit(self.report([req("a")], [gap("b", "preferred")]))
        self.assertEqual((fit["pct"], fit["letter"]), (60, "D"))
        # required missing (3), preferred met (2): 2/5 = 40%
        fit = compute_job_fit(self.report([req("b", "preferred")], [gap("a")]))
        self.assertEqual(fit["pct"], 40)

    def test_partial_gap_earns_half_credit(self):
        fit = compute_job_fit(self.report([req("a")], [gap("b", status="partial")]))
        self.assertEqual(fit["pct"], 75)  # (3 + 1.5) / 6
        self.assertEqual(fit["letter"], "C")

    def test_band_edges(self):
        def letter(met, missing):
            return compute_job_fit(self.report([req(f"m{i}") for i in range(met)], [gap(f"g{i}") for i in range(missing)]))["letter"]
        self.assertEqual(letter(9, 1), "A")   # 27/30 = 90%
        self.assertEqual(letter(4, 1), "B")   # 12/15 = 80%
        self.assertEqual(letter(7, 3), "C")   # 21/30 = 70%
        self.assertEqual(letter(2, 1), "D")   # 6/9 = 67%

    def test_interview_answer_closes_a_gap(self):
        report = self.report([req("a")], [gap("Franchise compliance auditing (required)")])
        before = compute_job_fit(report)
        after = compute_job_fit(report, [{"category": "Franchise compliance auditing", "bullet_text": "Audited franchises."}])
        self.assertEqual(before["pct"], 50)
        self.assertEqual(after["pct"], 100)
        self.assertEqual(after["closed_by_interview"], 1)
        self.assertEqual(after["open_gaps"], [])

    def test_unrelated_fact_does_not_close_a_gap(self):
        report = self.report([req("a")], [gap("Franchise compliance auditing")])
        after = compute_job_fit(report, [{"category": "Pricing strategies", "bullet_text": "x"}])
        self.assertEqual(after["pct"], 50)

    def test_open_gaps_list_required_first_and_carries_how_to_close(self):
        fit = compute_job_fit(self.report([req("a")], [
            gap("nice to have", "preferred", how="a course"),
            gap("CTP", "required", how="Complete the CTP certification"),
        ]))
        self.assertEqual([g["requirement"] for g in fit["open_gaps"]], ["CTP", "nice to have"])
        self.assertEqual(fit["open_gaps"][0]["how_to_close"], "Complete the CTP certification")

    def test_malformed_entries_are_ignored_not_fatal(self):
        fit = compute_job_fit({"requirements_met": ["text", req("a")], "required_qualification_gaps": ["text"]})
        self.assertEqual(fit["pct"], 100)


if __name__ == "__main__":
    unittest.main()
