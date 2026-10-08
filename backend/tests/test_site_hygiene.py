"""Site hygiene: security headers, robots/sitemap, share cards, favicons, the branded 404, no stray fonts.

These are the invisible things that make a site feel professionally built, so they are checked
automatically: a future edit that drops one fails here.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import json
import os
import re
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from PIL import Image

import main

FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
SITE = "https://creatingtomorrow.net"
PUBLIC_PAGES = ["index.html", "about.html", "learn.html", "videos.html", "tool.html", "scratch.html", "elevate.html", "spotlight.html", "prepare.html", "article.html",
                "privacy.html", "terms.html", "accessibility.html", "contact.html"]
TRUST_PAGES = ["privacy.html", "terms.html", "accessibility.html", "contact.html"]
CONTACT_EMAIL = "yovanarathbone@creatingtomorrow.net"


def read(*parts):
    with open(os.path.join(FRONTEND, *parts), encoding="utf-8") as f:
        return f.read()


def image_size(*parts):
    with Image.open(os.path.join(FRONTEND, *parts)) as img:
        return img.size


def all_html():
    for root, _, files in os.walk(FRONTEND):
        for name in files:
            if name.endswith(".html"):
                yield os.path.relpath(os.path.join(root, name), FRONTEND), read(os.path.relpath(os.path.join(root, name), FRONTEND))


class SecurityHeaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_every_response_carries_the_headers(self):
        for path, accept in (("/", "text/html"), ("/api/health", "application/json"), ("/nope-xyz", "text/html"), ("/api/nope", "application/json"), ("/robots.txt", "*/*")):
            h = self.client.get(path, headers={"accept": accept}).headers
            with self.subTest(path):
                self.assertEqual(h["x-content-type-options"], "nosniff")
                self.assertEqual(h["x-frame-options"], "DENY")
                self.assertEqual(h["referrer-policy"], "strict-origin-when-cross-origin")
                self.assertIn("max-age=", h["strict-transport-security"])
                self.assertIn("camera=()", h["permissions-policy"])
                self.assertIn("content-security-policy", h)

    def test_csp_is_enforced_and_never_allows_plugins_or_framing(self):
        h = self.client.get("/").headers
        self.assertNotIn("content-security-policy-report-only", h, "the policy is enforced now (see main.py for how to roll back)")
        csp = h["content-security-policy"]
        for must in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'"):
            self.assertIn(must, csp)

    def test_the_csp_lists_every_outside_address_the_pages_really_use(self):
        csp = self.client.get("/").headers["content-security-policy"]
        hosts = set()
        for name, page in all_html():
            for url in re.findall(r'(?:<script[^>]+src|<iframe[^>]+src|<link rel="stylesheet"[^>]+href)="(https://[^"]+)"', page):
                hosts.add(urlparse(url).netloc)
        for js in ("learn-data.js", "videos-data.js", "article.html", "videos.html"):
            for url in re.findall(r'src="(https://[^"$]+)', read(js)):
                hosts.add(urlparse(url).netloc)
        for host in hosts:
            self.assertIn(host, csp, f"{host} is loaded by a page but missing from the CSP")
        self.assertIn("cognito-idp.us-east-2.amazonaws.com", csp)  # the sign-in service (called from the browser)


class BrandedNotFound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_missing_pages_get_the_branded_page_with_a_real_404(self):
        for path in ("/nope-xyz", "/missing.png", "/old/page.html"):
            res = self.client.get(path)
            with self.subTest(path):
                self.assertEqual(res.status_code, 404)
                self.assertIn("text/html", res.headers["content-type"])
                self.assertIn("That page isn’t here.", res.text)

    def test_the_api_still_answers_in_json(self):
        for accept in ("text/html", "*/*", "application/json"):
            res = self.client.get("/api/does-not-exist", headers={"accept": accept})
            self.assertEqual(res.status_code, 404)
            self.assertEqual(res.json(), {"detail": "Not Found"})

    def test_the_page_is_not_called_404_html_and_works_from_any_depth(self):
        self.assertFalse(os.path.exists(os.path.join(FRONTEND, "404.html")), "StaticFiles would use a file called 404.html for /api/ paths too")
        page = read("not-found.html")
        self.assertIn('<meta name="robots" content="noindex" />', page)
        for ref in re.findall(r'(?:href|src)="([^"#]+)"', page):
            self.assertTrue(ref.startswith("/") or ref.startswith("https://"), f"relative link on the 404 page: {ref}")
            if ref.startswith("/"):
                self.assertTrue(os.path.exists(os.path.join(FRONTEND, ref.lstrip("/"))), f"missing file {ref}")


class SearchAndSharing(unittest.TestCase):
    def test_robots_txt(self):
        robots = read("robots.txt")
        self.assertIn("User-agent: *", robots)
        self.assertIn("Disallow: /api/", robots)
        self.assertIn("Disallow: /career/", robots)
        self.assertIn(f"Sitemap: {SITE}/sitemap.xml", robots)

    def test_sitemap_lists_only_real_public_pages(self):
        root = ET.fromstring(read("sitemap.xml"))
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [u.find("s:loc", ns).text for u in root.findall("s:url", ns)]
        self.assertIn(SITE + "/", locs)
        slugs = set(re.findall(r'slug:\s*"([a-z0-9-]+)"', read("learn-data.js")))
        seen_slugs = set()
        for loc in locs:
            self.assertTrue(loc.startswith(SITE + "/"), loc)
            self.assertNotIn("/career/", loc)
            parsed = urlparse(loc)
            name = parsed.path.lstrip("/") or "index.html"
            self.assertTrue(os.path.exists(os.path.join(FRONTEND, name)), f"{loc} has no file")
            if parsed.query:
                slug = parsed.query.split("=", 1)[1]
                self.assertIn(slug, slugs)
                seen_slugs.add(slug)
        self.assertEqual(seen_slugs, slugs, "every guide should be in the sitemap")

    def test_every_public_page_has_the_share_card_and_favicon_set(self):
        for page in PUBLIC_PAGES:
            h = read(page)
            with self.subTest(page):
                self.assertIn(f'<meta property="og:image" content="{SITE}/og-image.png" />', h)
                self.assertIn('<meta name="twitter:card" content="summary_large_image" />', h)
                self.assertIn('<meta property="og:title"', h)
                self.assertIn('<meta property="og:description"', h)
                self.assertIn('<meta name="description"', h)
                self.assertIn('<link rel="apple-touch-icon" href="apple-touch-icon.png" />', h)
                self.assertIn('<link rel="manifest" href="site.webmanifest" />', h)
                self.assertEqual(h.count('<meta property="og:title"'), 1, "duplicate share tags")
                if page != "article.html":  # one page serves many articles, so it has no single canonical address
                    path = "" if page == "index.html" else page
                    self.assertIn(f'<link rel="canonical" href="{SITE}/{path}" />', h)

    def test_the_signed_in_area_is_kept_out_of_search_results(self):
        for page in ("career/login.html", "career/register.html"):
            self.assertIn('<meta name="robots" content="noindex" />', read(page))
            self.assertIn('href="../favicon.ico"', read(page))

    def test_share_image_favicons_and_manifest_are_real_files(self):
        self.assertEqual(image_size("og-image.png"), (1200, 630))
        self.assertEqual(image_size("apple-touch-icon.png"), (180, 180))
        with Image.open(os.path.join(FRONTEND, "favicon.ico")) as ico:
            self.assertEqual(sorted(ico.info["sizes"]), [(16, 16), (32, 32), (48, 48)])
        manifest = json.loads(read("site.webmanifest"))
        self.assertEqual(manifest["name"], "Creating Tomorrow")
        for icon in manifest["icons"]:
            w, h = image_size(icon["src"].lstrip("/"))
            self.assertEqual(f"{w}x{h}", icon["sizes"])

    def test_the_logo_is_a_light_file(self):
        self.assertLess(os.path.getsize(os.path.join(FRONTEND, "logo-icon.png")), 40 * 1024)


class TrustPages(unittest.TestCase):
    """Privacy, Terms, Accessibility, Contact: what funders, schools and partners look for first."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_pages_exist_and_short_addresses_redirect_permanently(self):
        for page in TRUST_PAGES:
            name = page[:-5]
            res = self.client.get("/" + name, follow_redirects=False)
            with self.subTest(name):
                self.assertEqual(res.status_code, 301)
                self.assertEqual(res.headers["location"], "/" + page)
                self.assertEqual(self.client.get("/" + page).status_code, 200)

    def test_every_page_footer_links_to_all_four(self):
        pages = PUBLIC_PAGES + ["career/login.html", "career/register.html", "not-found.html"]
        for page in pages:
            h = read(page)
            prefix = "../" if page.startswith("career/") else ("/" if page == "not-found.html" else "")
            with self.subTest(page):
                for t in TRUST_PAGES:
                    self.assertIn(f'href="{prefix}{t}"', h)
                self.assertIn('class="footer-links"', h)

    def test_the_contact_address_is_the_one_she_gave_and_everything_points_at_it(self):
        self.assertIn(f'href="mailto:{CONTACT_EMAIL}"', read("contact.html"))
        for page in ("privacy.html", "terms.html", "accessibility.html"):
            self.assertIn(CONTACT_EMAIL, read(page), page)
        for name, page in all_html():
            for found in re.findall(r"mailto:([^\"?]+)", page):
                self.assertEqual(found, CONTACT_EMAIL, name)

    def test_privacy_names_every_outside_service_the_site_really_uses(self):
        text = read("privacy.html")
        for service in ("Anthropic", "Amazon Cognito", "Render", "Cloudflare", "jsDelivr", "YouTube"):
            self.assertIn(service, text)
        self.assertIn("We don’t sell your information", text)

    def test_no_claims_we_cannot_back_up_yet(self):
        blob = " ".join(read(p) for p in TRUST_PAGES).lower()
        for banned in ("501(c)", "tax-deductible", "tax deductible", "ein ", "hipaa", "gdpr", "soc 2", "wcag 2.2 level aa compliant",
                       "fully accessible", "fully compliant", "governing law", "lorem", "todo", "placeholder"):
            self.assertNotIn(banned, blob, banned)

    def test_the_consent_screen_links_instead_of_saying_coming_soon(self):
        login = read("career/login.html")
        self.assertNotIn("Privacy · Terms · Delete My Data (coming soon", login)
        self.assertIn('href="../privacy.html"', login)

    def test_trust_pages_are_in_the_sitemap_and_not_hidden_from_search(self):
        sitemap = read("sitemap.xml")
        for page in TRUST_PAGES:
            self.assertIn(f"{SITE}/{page}</loc>", sitemap)
            self.assertNotIn("noindex", read(page))


class NoStrayFonts(unittest.TestCase):
    def test_no_page_asks_google_fonts_for_anything(self):
        for name, page in all_html():
            self.assertNotIn("fonts.googleapis.com", page, name)
            self.assertNotIn("fonts.gstatic.com", page, name)
        for css in ("style.css", "home-v4.css", os.path.join("career", "dashboard-v4.css")):
            self.assertNotIn("googleapis", read(css), css)


class TypeSystem(unittest.TestCase):
    """One headline face (self-hosted Source Serif 4) + one size scale, defined once in style.css."""

    def test_font_files_are_real_and_licensed(self):
        for w in ("600", "700"):
            path = os.path.join(FRONTEND, "fonts", f"source-serif-4-latin-{w}-normal.woff2")
            with open(path, "rb") as f:
                self.assertEqual(f.read(4), b"wOF2", path)
            self.assertLess(os.path.getsize(path), 40 * 1024)
        self.assertIn("SIL Open Font License", read("fonts", "SourceSerif4-OFL.txt"))

    def test_font_face_points_at_files_that_exist(self):
        css = read("style.css")
        urls = re.findall(r'url\("(fonts/[^"]+\.woff2)"\)', css)
        self.assertEqual(len(urls), 2)
        for u in urls:
            self.assertTrue(os.path.exists(os.path.join(FRONTEND, u)), u)
        self.assertIn("font-display: swap", css)

    def test_woff2_is_served_with_the_right_type(self):
        res = TestClient(main.app).get("/fonts/source-serif-4-latin-700-normal.woff2")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "font/woff2")

    def test_scale_tokens_exist_and_pages_use_them(self):
        css = read("style.css")
        for token in ("--font-sans", "--font-serif", "--fs-sm", "--fs-base", "--fs-lg", "--fs-xl", "--fs-h2", "--fs-h1"):
            self.assertRegex(css, re.escape(token) + r":")
        for name, selector in (
            ("style.css", ".ats-header h1"), ("style.css", ".about-hero h1"), ("style.css", ".learn-hub-hero h1"),
            ("home-v4.css", ".hv-hero h1"), ("home-v4.css", ".hv-h2"),
            (os.path.join("career", "dashboard-v4.css"), ".dashboard-hero h1"),
        ):
            m = re.search(re.escape(selector) + r" \{([^}]*)\}", read(name))
            self.assertTrue(m, selector)
            self.assertIn("var(--font-serif)", m.group(1), f"{selector} should use the headline face")
            self.assertRegex(m.group(1), r"font-size:\s*var\(--fs-", f"{selector} should use a scale step")

    def test_every_stylesheet_uses_the_tokens_not_a_second_font_stack(self):
        for name in ("home-v4.css", os.path.join("career", "dashboard-v4.css")):
            self.assertNotIn("Source Serif", read(name), name)
            self.assertNotIn('"Segoe UI"', read(name), name)


if __name__ == "__main__":
    unittest.main()
