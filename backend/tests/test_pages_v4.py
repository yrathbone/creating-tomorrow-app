"""The new look on every page except the homepage and the dashboard (frontend/pages-v4.css).

Guards three things: every inner page actually loads it, it can never leak onto the homepage or the dashboard,
and the Career Tools hub keeps the hooks app.js needs. Run from backend/:  py -3.12 -m unittest discover -s tests -t .
"""
import os
import re
import unittest

FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
INNER = ["about.html", "learn.html", "videos.html", "tool.html", "scratch.html", "elevate.html", "spotlight.html", "prepare.html",
         "article.html", "privacy.html", "terms.html", "accessibility.html", "contact.html"]
SEPARATE = ["index.html", os.path.join("career", "login.html"), os.path.join("career", "register.html"), "not-found.html"]


def read(*parts):
    with open(os.path.join(FRONTEND, *parts), encoding="utf-8") as f:
        return f.read()


class InnerPagesUseTheNewLook(unittest.TestCase):
    def test_every_inner_page_has_the_body_class_and_loads_the_stylesheets_in_order(self):
        for page in INNER:
            h = read(page)
            with self.subTest(page):
                self.assertRegex(h, r'<body class="pages-v4[ "]')
                style, home, pages = (h.find(f'href="{n}.css"') for n in ("style", "home-v4", "pages-v4"))
                self.assertTrue(0 < style < home < pages, "style.css, then home-v4.css, then pages-v4.css")

    def test_the_homepage_dashboard_and_sign_in_pages_do_not_load_it(self):
        for page in SEPARATE:
            self.assertNotIn("pages-v4", read(page), page)

    def test_the_stylesheet_is_scoped_so_it_cannot_leak(self):
        css = re.sub(r"/\*.*?\*/", "", read("pages-v4.css"), flags=re.S)
        depth, selector_start, bad = 0, 0, []
        for i, ch in enumerate(css):
            if ch == "{":
                if depth == 0:
                    selector = css[selector_start:i].strip()
                    if not selector.startswith("@"):
                        for part in selector.split(","):
                            part = part.strip()
                            if not (part.startswith("body.pages-v4") or part.startswith("body:where(.pages-v4)")):
                                bad.append(part)
                elif depth == 1 and css[:i].rstrip().rsplit("{", 1)[0].strip().rsplit("}", 1)[-1].strip().startswith("@"):
                    pass
                depth += 1
                selector_start = i + 1
            elif ch == "}":
                depth -= 1
                selector_start = i + 1
        # rules inside @media blocks are checked too
        for m in re.finditer(r"@media[^{]*\{(.*?)\n\}", css, re.S):
            for sel in re.findall(r"(?:^|\})\s*([^{}@]+)\{", m.group(1)):
                for part in sel.split(","):
                    part = part.strip()
                    if part and not (part.startswith("body.pages-v4") or part.startswith("body:where(.pages-v4)")):
                        bad.append(part)
        self.assertEqual(bad, [], "every rule must start with body.pages-v4 so the homepage and dashboard stay untouched")

    def test_no_new_fonts_or_outside_requests(self):
        css = read("pages-v4.css")
        self.assertNotIn("http", css.replace("http://www.w3.org/2000/svg", ""))
        self.assertNotIn("@import", css)
        self.assertNotIn("font-face", css)


class CareerToolsHub(unittest.TestCase):
    def test_hub_keeps_the_hooks_app_js_needs(self):
        h = read("tool.html")
        self.assertEqual(len(re.findall(r'class="mode-btn hv-tool', h)), 6)
        for mode in ("refine", "analyze"):
            self.assertRegex(h, rf'<button type="button" class="mode-btn hv-tool [^"]+" id="mode-{mode}" data-mode="{mode}">')
        for link in ("scratch.html", "elevate.html", "spotlight.html", "prepare.html"):
            self.assertRegex(h, rf'<a class="mode-btn hv-tool [^"]+" href="{link}">')
        self.assertIn('id="step-mode"', h)
        self.assertIn('.mode-btn[data-mode]', read("app.js"))

    def test_hub_tiles_have_an_icon_a_name_a_description_and_a_start_line(self):
        h = read("tool.html")
        block = h[h.index('id="step-mode"'):h.index('id="step-upload"')]
        for part in ("hv-vicon", "hv-vtype", "<b>", "hv-vdesc", "hv-vfoot"):
            self.assertEqual(block.count(part), 6, part)


class LearnPage(unittest.TestCase):
    def test_learn_lists_every_guide_with_a_real_link(self):
        h = read("learn.html")
        slugs = set(re.findall(r'slug:\s*"([a-z0-9-]+)"', read("learn-data.js")))
        linked = set(re.findall(r'href="article\.html\?slug=([a-z0-9-]+)"', h))
        self.assertEqual(linked, slugs)
        self.assertIn('class="pv-panel"', h)


class SmallFixes(unittest.TestCase):
    def test_sign_in_and_register_fields_say_what_they_are_for_password_managers(self):
        login, register = read("career", "login.html"), read("career", "register.html")
        self.assertIn('id="login-password" name="password" autocomplete="current-password"', login)
        self.assertIn('id="login-email" name="email" autocomplete="username"', login)
        self.assertIn('autocomplete="new-password"', register)
        self.assertIn('autocomplete="email"', register)

    def test_dynamic_dropdowns_carry_a_name(self):
        self.assertIn('layout.name = "resume-layout"', read("career", "js", "history.js"))
        apps = read("career", "js", "applications.js")
        self.assertIn('statusSelect.name = "application-status"', apps)
        self.assertIn('move.name = "application-move"', apps)

    def test_the_guide_call_to_action_buttons_wrap_instead_of_overflowing(self):
        css = read("style.css")
        m = re.search(r"\.final-cta \.hero-ctas \{([^}]*)\}", css)
        self.assertTrue(m)
        self.assertIn("max-width: 100%", m.group(1))
        self.assertIn("flex: 0 1 auto", m.group(1))


if __name__ == "__main__":
    unittest.main()
