"""
Creating Tomorrow - architecture learning program.

WHAT THIS IS
This is NOT part of the production application. Nothing in this file is
imported by, or affects, backend/main.py or anything in frontend/. It is a
plain-Python description of the REAL system, built by reading every file in
the repository (see docs/CURRENT_INFRASTRUCTURE.md for the full audit this
was built from).

WHY IT EXISTS
To make the architecture something you can run, read top to bottom, and
question - rather than a document you skim once. Every value below traces
back to an actual file/line in the repo. Nothing here is invented.

HOW TO RUN IT
    cd architecture
    python creating_tomorrow_architecture.py

That prints a readable architecture summary to the terminal (see main() at
the bottom - it calls each show_*() function in turn).
"""

from dataclasses import dataclass, field


# ============================================================================
# SECTION 1: THE SITE, TOP LEVEL
# ----------------------------------------------------------------------------
# WHAT THIS IS: the highest-level shape of the whole application - one
# frontend, one backend, one AI provider.
# WHY IT EXISTS: before drilling into any one piece, this is the 30-second
# version - what talks to what.
# HOW IT CONNECTS: "frontend" and "backend" are actually the SAME process in
# production (FastAPI serves both) - see backend["serves_frontend"] below.
# ============================================================================

site = {
    "frontend": {
        "type": "plain HTML/CSS/JavaScript",
        "framework": None,  # VERIFIED: no package.json, no build step anywhere
        "page_count": 10,
        "served_by": "the same FastAPI process as the API (StaticFiles mount)",
    },
    "backend": {
        "framework": "FastAPI",
        "server": "Uvicorn",
        "language": "Python",
        "entry_point": "backend/main.py",
        "serves_frontend": True,  # main.py's app.mount("/", StaticFiles(...))
        "database": None,  # VERIFIED: no db driver in requirements.txt, no db import anywhere
    },
    "ai": {
        "provider": "Anthropic",
        "sdk": "anthropic (official Python SDK)",
        "model_env_var": "CT_MODEL",
        "model_default": "claude-sonnet-5",
        "api_key_env_var": "ANTHROPIC_API_KEY",  # set in Render dashboard, never in repo
    },
}


# ============================================================================
# SECTION 2: THE SIX TOOLS
# ----------------------------------------------------------------------------
# WHAT THIS IS: one entry per career tool, naming its real frontend page,
# real JS file, real backend module, and real Python function(s) - not
# generic placeholders.
# WHY IT EXISTS: this is the part of the app that actually does something.
# Everything else (nav, styling, hosting) exists to support these six flows.
# HOW IT CONNECTS: each tool's "backend_module" is a file in backend/, each
# calling into Anthropic (see external_services["anthropic"] in Section 4).
# ============================================================================

@dataclass
class Tool:
    name: str
    page: str                  # the frontend HTML file
    js_file: str                # the frontend JS file driving it
    backend_module: str         # the Python file with the tool's AI logic
    functions: list             # real function names in that module
    endpoints: list             # real /api/... routes this tool calls
    response_style: str         # "tool_choice" (reliable) or "free_text_json" (older pattern)
    uses_web_search: bool
    max_tokens: int
    has_retry: bool
    produces_docx: bool


tools = {
    "Beginning": Tool(
        name="Beginning",
        page="frontend/scratch.html",
        js_file="frontend/scratch.js",
        backend_module="backend/scratch.py",
        functions=["draft_entry", "finalize"],
        endpoints=["/api/scratch-entry", "/api/scratch-finalize", "/api/generate"],
        response_style="free_text_json",
        uses_web_search=True,   # only tool that does - see draft_entry()
        max_tokens=6000,
        has_retry=False,
        produces_docx=True,
    ),
    "Refine": Tool(
        name="Refine",
        page="frontend/tool.html (mode=refine)",
        js_file="frontend/app.js",
        backend_module="backend/upgrade.py",
        functions=["upgrade"],
        endpoints=["/api/refine", "/api/generate"],
        response_style="tool_choice",
        uses_web_search=False,
        max_tokens=16000,
        has_retry=True,
        produces_docx=True,
    ),
    "Right Fit": Tool(
        name="Right Fit",
        page="frontend/tool.html (mode=analyze)",
        js_file="frontend/app.js",
        backend_module="backend/coach.py",
        functions=["analyze"],
        endpoints=["/api/analyze", "/api/recap", "/api/generate"],
        response_style="tool_choice",
        uses_web_search=False,
        max_tokens=16000,
        has_retry=True,
        produces_docx=True,
    ),
    "Elevate": Tool(
        name="Elevate",
        page="frontend/elevate.html",
        js_file="frontend/elevate.js",
        backend_module="backend/elevate.py",
        functions=["analyze_for_discovery", "discover", "finalize_elevate"],
        endpoints=["/api/elevate-start", "/api/elevate-discover", "/api/elevate-finalize", "/api/generate"],
        response_style="free_text_json",
        uses_web_search=False,
        max_tokens=8000,
        has_retry=False,
        produces_docx=True,
    ),
    "Spotlight": Tool(
        name="Spotlight",
        page="frontend/spotlight.html",
        js_file="frontend/spotlight.js",
        backend_module="backend/profile_review.py",
        functions=["review_profile"],
        endpoints=["/api/profile-review", "/api/spotlight-recap"],
        response_style="tool_choice",
        uses_web_search=False,
        max_tokens=16000,
        has_retry=True,
        produces_docx=True,
    ),
    "Prepare": Tool(
        name="Prepare",
        page="frontend/prepare.html",
        js_file="frontend/prepare.js",
        backend_module="backend/prepare.py",
        functions=["prepare"],
        endpoints=["/api/prepare"],
        response_style="free_text_json",
        uses_web_search=False,
        max_tokens=8000,
        has_retry=False,
        produces_docx=False,  # NEEDS VERIFICATION: no download feature exists for Prepare today
    ),
}


# ============================================================================
# SECTION 3: DATA FLOW (ONE GENERIC REQUEST, START TO FINISH)
# ----------------------------------------------------------------------------
# WHAT THIS IS: the same 8 hops every single tool request takes, in order.
# WHY IT EXISTS: once you understand this one flow, you understand all six
# tools - they only differ in step 5 (which Python function, which prompt).
# HOW IT CONNECTS: step 2 is site["backend"], step 5 is a Tool from
# Section 2, step 6 is external_services["anthropic"] from Section 4.
# ============================================================================

data_flow = [
    "1. Browser JS builds a request (FormData or JSON) and calls fetch('/api/...')",
    "2. Cloudflare -> Render -> Uvicorn -> FastAPI (backend/main.py) receives it",
    "3. main.py's route handler validates input (size limits, required fields)",
    "4. If a file was uploaded, extractor.extract_text() converts it to plain text in memory",
    "5. main.py calls the matching tool module's function (see tools dict above)",
    "6. That function calls anthropic.Anthropic().messages.create(...) - the ONLY AI step",
    "7. The tool module validates/parses the response, retries once if applicable, and returns a dict",
    "8. main.py returns JSON (or resume_builder.py builds a .docx) back through the same path to the browser",
]


# ============================================================================
# SECTION 4: EXTERNAL SERVICES
# ----------------------------------------------------------------------------
# WHAT THIS IS: every third party this application actually talks to today -
# VERIFIED by reading requirements.txt, every backend import, every frontend
# <script>/<link> tag, and the live site's own DNS/HTTP response headers.
# WHY IT EXISTS: this is exactly the list an AWS migration has to account
# for - some of these move with you (Anthropic, GitHub, GoDaddy), some get
# replaced (Render), one's status is genuinely unclear (Cloudflare).
# HOW IT CONNECTS: "required_today" = False means the app would still work
# without it (e.g. Google Fonts); it does NOT mean "unused."
# ============================================================================

external_services = {
    "anthropic": {
        "purpose": "every AI feature in all six tools",
        "called_from": "every backend/*.py tool module",
        "required_today": True,
        "moves_to_aws_unchanged": True,  # it's an external API call either way
    },
    "github": {
        "purpose": "source control; Render watches this repo for deploys",
        "repo": "yrathbone/creating-tomorrow-app",  # VERIFIED via git remote -v
        "required_today": True,
        "moves_to_aws_unchanged": "yes, if AWS's CI/CD also reads from GitHub (recommended)",
    },
    "render": {
        "purpose": "current production host (compute) - runs render.yaml's uvicorn command",
        "required_today": True,
        "moves_to_aws_unchanged": False,  # this is exactly what a migration replaces
    },
    "cloudflare": {
        "purpose": "fronts the custom domain - VERIFIED via live response headers (Server: cloudflare, CF-RAY)",
        "required_today": "NEEDS VERIFICATION",  # could be Render's own edge network, not a separate account
        "moves_to_aws_unchanged": "NEEDS VERIFICATION",
    },
    "godaddy": {
        "purpose": "DNS for creatingtomorrow.net",
        "nameservers": ["ns63.domaincontrol.com", "ns64.domaincontrol.com"],  # VERIFIED via nslookup
        "required_today": True,
        "moves_to_aws_unchanged": True,  # DNS and hosting are independent - can stay on GoDaddy indefinitely
    },
    "google_fonts": {
        "purpose": "one font ('Caveat') loaded on the homepage only",
        "called_from": "frontend/index.html <link> tag",
        "required_today": False,  # cosmetic only
        "moves_to_aws_unchanged": True,  # unaffected by backend hosting choice
    },
}

# Checked for and confirmed NOT present anywhere in the codebase:
services_not_used = [
    "any database (PostgreSQL, MySQL, SQLite, MongoDB, Redis)",
    "any analytics/tracking script (Google Analytics, Plausible, Segment, Hotjar, Mixpanel)",
    "any error-monitoring SDK (Sentry or similar)",
    "any email or SMS service",
    "any payment processor",
    "any authentication/login provider",
    "any AI or search API besides Anthropic (Beginning's 'web search' is Anthropic's own server-side tool)",
]


# ============================================================================
# SECTION 5: DATA STORAGE
# ----------------------------------------------------------------------------
# WHAT THIS IS: a direct answer to "does this app save anything, anywhere?"
# WHY IT EXISTS: privacy is a stated design goal of this app - this section
# is the verified evidence behind that claim, not a restatement of the goal.
# HOW IT CONNECTS: this is WHY the AWS recommendation (Section 7) can
# seriously consider "no database at all."
# ============================================================================

data_storage = {
    "database": "NOT USED - no driver in requirements.txt, no db import anywhere in backend/",
    "server_filesystem_writes": "NOT USED - extractor.py and resume_builder.py both work entirely in io.BytesIO",
    "browser_localStorage": "NOT USED - verified via repo-wide search",
    "browser_sessionStorage": "NOT USED - verified via repo-wide search",
    "cookies": "NOT USED - verified via repo-wide search",
    "browser_tab_memory": "USED - each tool keeps its own plain JS variables (e.g. resumeData) for one session only",
    "url_query_params": "USED, UI-routing only - e.g. tool.html?mode=refine, article.html?slug=... (never resume/job content)",
    "render_disk": "NOT USED - no persistent disk attached, none needed",
    "cloudflare_logging": "NEEDS VERIFICATION - depends on the Cloudflare open question in Section 4",
    "verbose_ai_failure_logging": "NOT PRESENT in coach.py/upgrade.py/profile_review.py (category-only diagnostics); scratch.py/elevate.py/prepare.py log no diagnostics at all today",
}


# ============================================================================
# SECTION 6: OPEN QUESTIONS
# ----------------------------------------------------------------------------
# WHAT THIS IS: things this audit could NOT settle by reading the repo -
# they require checking a provider dashboard, or a decision only you can make.
# WHY IT EXISTS: an honest architecture doc says what it doesn't know.
# HOW IT CONNECTS: these map directly to the "OPEN QUESTIONS" list in the
# chat summary and in docs/CURRENT_INFRASTRUCTURE.md.
# ============================================================================

open_questions = [
    "Is Cloudflare a separate account you manage, or just Render's own edge network in front of custom domains? (check Render's custom-domain docs/dashboard)",
    "What does Anthropic's CURRENT published data-retention policy say (re-check at migration time - it was verified once, policies can change)",
    "Does Render's own platform-level request logging capture full request bodies (i.e. resume/job-posting text) at the infrastructure layer, outside this app's own code?",
    "Was a downloadable report ever planned for Prepare, or is 'no .docx download' intentional?",
    "Should the three tools still on the free-text-JSON pattern (Beginning, Elevate, Prepare) be migrated to the tool_choice pattern - and is that in scope before or after the AWS migration?",
    "Should the unescaped innerHTML pattern in app.js/scratch.js/elevate.js be standardized to match prepare.js's escapeHtml() approach?",
]


# ============================================================================
# SECTION 7: AWS MIGRATION TARGET (PROPOSED - NOT BUILT, NOT DEPLOYED)
# ----------------------------------------------------------------------------
# WHAT THIS IS: the simplest AWS shape that could run this exact application,
# given everything verified above (no database, no auth, no persistence).
# WHY IT EXISTS: a concrete target makes the migration roadmap (Phase 5,
# docs/AWS_MIGRATION_PLAN.md) about moving TOWARD something specific.
# HOW IT CONNECTS: every "replaces" value below points back at
# external_services["render"] above - this section proposes what fills that
# one gap. See docs/AWS_MIGRATION_PLAN.md for the full reasoning.
# ============================================================================

aws_future = {
    "frontend_hosting": {
        "candidates": ["AWS Amplify Hosting", "S3 + CloudFront"],
        "replaces": "Render's StaticFiles serving of frontend/",
        "status": "PROPOSED - not built",
    },
    "backend_hosting": {
        # UPDATED 2026-09-22: App Runner stopped accepting new customers
        # 2026-04-30 (verified live, not from stale docs). ECS Express Mode
        # was actually built, deployed, verified via /api/health, and
        # deleted the same night - real Fargate + ALB cost turned out to
        # be ~$50+/month if left running, confirmed live, not estimated.
        # Lambda's free tier is verified PERMANENT (1M requests + 400,000
        # GB-seconds/month, forever) - now the primary recommendation.
        "candidates": ["Lambda + API Gateway", "Amazon ECS Express Mode", "ECS/Fargate (manual)"],
        "primary_recommendation": "Lambda + API Gateway",
        "app_runner_status": "NOT AVAILABLE - closed to new customers as of 2026-04-30",
        "ecs_express_mode_status": "tested and torn down 2026-09-22 - real, cost prohibits leaving it running; kept as an occasional practice target, not the persistent architecture",
        "replaces": "Render's uvicorn process",
        "status": "PROPOSED - not built (Lambda); ECS Express Mode already tested once, then deleted",
    },
    "secrets": {
        "candidate": "AWS Secrets Manager (or Parameter Store for a simpler start)",
        "replaces": "Render's dashboard-set ANTHROPIC_API_KEY env var",
        "status": "PROPOSED - not built",
    },
    "monitoring": {
        "candidate": "CloudWatch",
        "replaces": "Render's built-in logs (no direct equivalent exists today)",
        "status": "PROPOSED - not built",
    },
    "database": {
        "candidate": None,
        "reasoning": "Section 5 above VERIFIES no database is used today - don't add one without a real, current reason",
        "status": "NOT PLANNED unless a real need emerges",
    },
    "authentication": {
        "candidate": "Cognito, ONLY if user accounts ever become a real feature",
        "status": "NOT PLANNED - no auth exists today",
    },
    "dns": {
        "candidate": "stays on GoDaddy initially; Route 53 only if a specific, real benefit shows up later",
        "status": "NO CHANGE PROPOSED for Stage 1",
    },
}


# ============================================================================
# DISPLAY FUNCTIONS
# ----------------------------------------------------------------------------
# Small, boring, on purpose - each one just prints a section of the
# structures above in a readable way. No cleverness needed here.
# ============================================================================

def _header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def show_site_summary() -> None:
    _header("SITE SUMMARY")
    for part, details in site.items():
        print(f"\n[{part.upper()}]")
        for key, value in details.items():
            print(f"  {key}: {value}")


def show_tool_flow(tool_name: str) -> None:
    _header(f"TOOL FLOW: {tool_name}")
    tool = tools.get(tool_name)
    if not tool:
        print(f"  Unknown tool '{tool_name}'. Known tools: {', '.join(tools)}")
        return
    print(f"  Page:            {tool.page}")
    print(f"  JS file:         {tool.js_file}")
    print(f"  Backend module:  {tool.backend_module}")
    print(f"  Functions:       {', '.join(tool.functions)}")
    print(f"  Endpoints:       {', '.join(tool.endpoints)}")
    print(f"  Response style:  {tool.response_style}")
    print(f"  Uses web search: {tool.uses_web_search}")
    print(f"  max_tokens:      {tool.max_tokens}")
    print(f"  Has retry logic: {tool.has_retry}")
    print(f"  Produces .docx:  {tool.produces_docx}")


def show_all_tool_flows() -> None:
    for name in tools:
        show_tool_flow(name)


def show_data_flow() -> None:
    _header("DATA FLOW (every tool follows this same 8-step path)")
    for step in data_flow:
        print(f"  {step}")


def show_external_services() -> None:
    _header("EXTERNAL SERVICES")
    for name, details in external_services.items():
        print(f"\n[{name.upper()}]")
        for key, value in details.items():
            print(f"  {key}: {value}")
    print("\n[CONFIRMED NOT USED]")
    for item in services_not_used:
        print(f"  - {item}")


def show_data_storage() -> None:
    _header("DATA STORAGE")
    for key, value in data_storage.items():
        print(f"  {key}: {value}")


def show_open_questions() -> None:
    _header("OPEN QUESTIONS (need your input or a provider-dashboard check)")
    for i, question in enumerate(open_questions, start=1):
        print(f"  {i}. {question}")


def show_aws_target() -> None:
    _header("AWS MIGRATION TARGET (PROPOSED - see docs/AWS_MIGRATION_PLAN.md)")
    for part, details in aws_future.items():
        print(f"\n[{part.upper()}]")
        for key, value in details.items():
            print(f"  {key}: {value}")


def main() -> None:
    show_site_summary()
    show_data_flow()
    show_all_tool_flows()
    show_external_services()
    show_data_storage()
    show_aws_target()
    show_open_questions()
    print("\n" + "=" * 78)
    print("End of architecture summary. See docs/ for the full write-ups.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
