"""The four Learn guides (rich templates inside frontend/article.html).

Guards the content rules agreed with Yovana: nothing is stated as fact unless it was checked against its source,
sources are real links, the page structure the site's CSS expects is intact, and the reading times are honest.
Run from backend/:  py -3.12 -m unittest discover -s tests -t .
"""
import html
import os
import re
import unittest

FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
with open(os.path.join(FRONTEND, "article.html"), encoding="utf-8") as f:
    PAGE = f.read()
with open(os.path.join(FRONTEND, "learn-data.js"), encoding="utf-8") as f:
    LEARN = f.read()

ARTICLES = {
    "ats-article-main": ("what-is-ats", "What Is an ATS, Really?", "ATS Basics"),
    "calling-card-article-main": ("resume-calling-card", "Your Resume Is Your Calling Card", "Resume Basics"),
    "linkedin-article-main": ("honest-self-marketing", "Your LinkedIn Profile Is Your Professional Story", "LinkedIn Basics"),
    "interview-article-main": ("how-we-grade", "Prepare Stories, Not Perfect Answers", "Interview Basics"),
}


def block(main_id):
    start = PAGE.index(f'<main id="{main_id}"')
    return PAGE[start:PAGE.index("</main>", start)]


def reading_text(main_id):
    b = block(main_id)
    b = b[: b.index('<details class="ats-sources"')]
    return html.unescape(re.sub(r"<[^>]+>", " ", b))


class GuideStructure(unittest.TestCase):
    def test_each_guide_has_its_header_title_and_category(self):
        for main_id, (slug, title, category) in ARTICLES.items():
            b = block(main_id)
            with self.subTest(slug):
                self.assertIn(f'<p class="ats-category">{category}</p>', b)
                self.assertIn(f"<h1>{title}</h1>", b)
                self.assertRegex(b, r'<p class="ats-readtime">\d+&ndash;\d+ minute read</p>')
                self.assertIn(f'slug: "{slug}"', LEARN)
                self.assertIn("ats-takeaway", b)
                self.assertIn("final-cta", b)

    def test_reading_times_match_the_word_count(self):
        for main_id, (slug, _, _) in ARTICLES.items():
            words = len(reading_text(main_id).split())
            low, high = map(int, re.search(r"(\d+)&ndash;(\d+) minute read", block(main_id)).groups())
            with self.subTest(slug):
                self.assertGreaterEqual(words / 200, low - 0.6, f"{slug}: {words} words is longer than the label says")
                self.assertLessEqual(words / 230, high + 0.6, f"{slug}: {words} words is shorter than the label says")

    def test_guides_are_shorter_than_the_versions_they_replace(self):
        limits = {"ats-article-main": 1177, "calling-card-article-main": 1918, "linkedin-article-main": 2079, "interview-article-main": 2157}
        for main_id, old in limits.items():
            self.assertLess(len(reading_text(main_id).split()), old, main_id)

    def test_tag_names_balance_and_there_are_no_glued_words(self):
        for main_id in ARTICLES:
            b = block(main_id)
            for tag in ("div", "ul", "p", "section", "details", "h2", "h3"):
                self.assertEqual(len(re.findall(rf"<{tag}\b", b)), len(re.findall(rf"</{tag}>", b)), f"{main_id}: unbalanced <{tag}>")
            text = reading_text(main_id)
            self.assertNotRegex(text, r"[a-z][A-Z][a-z]+[A-Z][a-z]+[A-Z]", f"{main_id}: words glued together")
            self.assertNotIn("  .", text)


class ClaimsWeCouldNotVerifyStayOut(unittest.TestCase):
    BANNED = [
        "Sallach", "Chollet", "SN, 2026", "Complete Guide", "While Maintaining Privacy", "Cal Poly",
        "Bornemann", "Wedelstedt", "Schinkel",            # a wrong author list this page used to carry
        "especially larger", "98%", "Fortune 500",
        "guaranteed", "always works", "secret formula that",
    ]

    def test_none_of_the_removed_or_unverified_claims_are_on_the_page(self):
        for main_id in ARTICLES:
            b = block(main_id)
            for bad in self.BANNED:
                self.assertNotIn(bad, b, f"{main_id} still contains {bad!r}")

    def test_the_2025_linkedin_study_has_its_verified_author_list(self):
        b = block("linkedin-article-main")
        for name in ("Steinbrecher", "Heinemann", "Pr&uuml;&szlig;meier", "Sch&auml;pers"):
            self.assertIn(name, b)

    def test_star_is_attributed_only_to_what_opm_actually_says(self):
        b = block("interview-article-main")
        self.assertIn("recommends it for writing structured interview questions", b)
        self.assertNotIn("federal hiring guidance itself", b)


class SourcesAreRealLinks(unittest.TestCase):
    def test_every_link_is_https_and_opens_safely(self):
        for main_id in ARTICLES:
            for m in re.finditer(r'<a href="(https?://[^"]+)"([^>]*)>', block(main_id)):
                with self.subTest(m.group(1)):
                    self.assertTrue(m.group(1).startswith("https://"))
                    self.assertIn('rel="noopener"', m.group(2))
                    self.assertIn('target="_blank"', m.group(2))

    def test_each_guide_with_research_has_a_sources_section(self):
        for main_id in ARTICLES:
            b = block(main_id)
            self.assertIn("Sources &amp; Further Reading", b)
            self.assertGreaterEqual(len(re.findall(r"<li>", b[b.index('class="ats-sources-body"'):])), 3, main_id)

    def test_inline_source_notes_name_their_sources(self):
        # every "(Source: ...)" in the text names something, and the research claims that need a citation have one
        ats = block("ats-article-main")
        for needle in ("Source: <a", "Samadi", "ADA.gov"):
            self.assertIn(needle, ats)
        resume = block("calling-card-article-main")
        for needle in ("Sekeres et al., 2016", "Di Stefano, Gino, Pisano", "Rudolph, Lavigne", "UIUC Career Center", "NACE"):
            self.assertIn(needle, resume)


class LearnPageCards(unittest.TestCase):
    def test_summaries_match_the_guide_subtitles(self):
        subtitles = {
            "what-is-ats": "What you need to know about the software behind online job applications, without the myths.",
            "resume-calling-card": "Keep it ready before you need it.",
            "how-we-grade": "How to prepare for an interview without memorizing a script.",
        }
        for slug, text in subtitles.items():
            self.assertIn(text, LEARN, slug)


if __name__ == "__main__":
    unittest.main()
