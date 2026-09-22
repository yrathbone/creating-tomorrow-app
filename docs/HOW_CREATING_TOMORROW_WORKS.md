# How Creating Tomorrow Works

This is written for you, not for a senior engineer — it assumes you know
Python basics (functions, dicts, lists, loops, JSON, what an API is) and are
learning cloud architecture. Every technical term is defined the first time
it shows up, using this format:

> **TERM**
> **Plain-English definition:** ...
> **Why Creating Tomorrow uses it:** ...
> **Where I can find it in the code:** ...

---

## Someone visits creatingtomorrow.net. What happens next?

Here's the full path, step by step, before we zoom into any one piece.

1. Their browser looks up `creatingtomorrow.net` in **DNS** and gets back an
   IP address.

   > **DNS (Domain Name System)**
   > **Plain-English definition:** The internet's phone book — turns a name
   > like `creatingtomorrow.net` into the numeric address (an IP address)
   > computers actually use to find each other.
   > **Why Creating Tomorrow uses it:** So people can type a memorable name
   > instead of an IP address.
   > **Where I can find it in the code:** Nowhere in the repo — DNS lives in
   > GoDaddy's dashboard, outside this codebase entirely.

2. The request first passes through **Cloudflare** (confirmed by checking
   the live site's response headers), which sits in front of Render.

3. Cloudflare forwards the request to **Render**, which is running our
   Python web server (**Uvicorn**, running our **FastAPI** app).

   > **Uvicorn**
   > **Plain-English definition:** A program that actually listens for
   > incoming web requests and hands them to your Python code. FastAPI
   > describes *what* to do with a request; Uvicorn is the thing that
   > *receives* the request in the first place.
   > **Why Creating Tomorrow uses it:** FastAPI needs something like Uvicorn
   > to actually run — they're almost always used together.
   > **Where I can find it in the code:** `render.yaml`'s `startCommand`:
   > `uvicorn main:app --host 0.0.0.0 --port $PORT`

   > **FASTAPI**
   > **Plain-English definition:** A Python framework that creates the
   > server endpoints ("routes") the website's JavaScript talks to — you
   > write a Python function, decorate it with something like
   > `@app.post("/api/analyze")`, and FastAPI wires up everything needed to
   > receive that kind of request and send back a response.
   > **Why Creating Tomorrow uses it:** It receives requests from the
   > career tools' JavaScript and sends structured responses back — it's
   > the entire backend.
   > **Where I can find it in the code:** `backend/main.py`

4. **The very same FastAPI app also serves the frontend.** There's no
   separate frontend server. One line in `main.py`,
   `app.mount("/", StaticFiles(directory=frontend_dir, html=True), ...)`,
   tells FastAPI "for anything that isn't `/api/...`, just serve files out
   of the `frontend/` folder." So when someone first loads
   `creatingtomorrow.net`, they're getting `frontend/index.html` handed to
   them by the exact same Python process that will later handle their
   `/api/analyze` call.

5. The browser now has plain HTML, CSS, and JavaScript. It renders the page.
   No React, no build step — what you see in `frontend/index.html` is
   (almost) exactly what's rendered.

6. When the person actually *uses* a tool — say, uploads a resume — their
   browser's JavaScript makes an **HTTP request** to one of our `/api/...`
   endpoints.

   > **HTTP request**
   > **Plain-English definition:** A message a browser (or any program)
   > sends to a server asking it to do something — "POST this data to this
   > address" or "GET whatever's at this address." Has a method (GET, POST,
   > etc.), a URL, optional headers, and an optional body.
   > **Why Creating Tomorrow uses it:** It's how the browser and the FastAPI
   > server talk to each other — every tool submission is one HTTP POST
   > request.
   > **Where I can find it in the code:** every `fetch(...)` call in the
   > frontend `.js` files, e.g. `spotlight.js` line 179:
   > `fetch("/api/profile-review", { method: "POST", body: formData })`

7. FastAPI receives that request, runs the matching Python function in
   `main.py`, which calls into a tool-specific file (like `coach.py` for
   Right Fit).

8. That tool file builds a prompt and calls **Anthropic's API** — this is
   the one and only place any "thinking" happens. FastAPI itself is not
   smart; it's plumbing. The actual resume analysis, question-writing, etc.
   is entirely done by the Claude model on Anthropic's servers.

   > **JSON (JavaScript Object Notation)**
   > **Plain-English definition:** A text format for structured data — looks
   > almost exactly like a Python dict/list, e.g.
   > `{"match_level": "Average", "strengths": ["...", "..."]}`. It's the
   > universal language APIs use to send data back and forth.
   > **Why Creating Tomorrow uses it:** Every request body and response body
   > between the browser and FastAPI, and between FastAPI and Anthropic, is
   > JSON (or, for `tool_choice`-based calls, a Python dict shaped by a JSON
   > Schema — same idea).
   > **Where I can find it in the code:** everywhere — e.g. `coach.py`'s
   > `ANALYSIS_TOOL["input_schema"]` defines exactly what shape of JSON the
   > model must return.

9. Anthropic sends back a JSON-shaped answer. The Python tool file validates
   it, and (for the three tools fixed this year) retries once if the answer
   came back cut off or malformed.

10. `main.py` returns that answer to the browser as an HTTP response —
    either JSON (for on-screen results) or a `.docx` file (for downloads).

11. The browser's JavaScript takes that response and updates the page —
    no reload, no navigation, just DOM updates (adding text, showing/hiding
    sections).

That's the entire loop, every single time: **browser → FastAPI → Python tool
file → Anthropic → Python tool file → FastAPI → browser.** Nothing is saved
anywhere in the middle.

---

## Walking through one real tool end to end: Right Fit

Let's trace an actual click.

**1. You're on `tool.html`, click "Right Fit."**
`app.js`'s `selectMode("analyze")` runs. It looks up `MODE_CONFIG["analyze"]`
(a plain JS object listing the endpoint, page copy, and loading messages for
this mode) and shows the upload form.

**2. You upload a resume and paste a job posting, click "Analyze my resume."**
`app.js`'s submit handler builds a `FormData` object (the JS way of building
a multipart file-upload request) with your file and the posting text, then:

```js
const res = await fetch("/api/analyze", { method: "POST", body: formData });
```

> **API endpoint**
> **Plain-English definition:** One specific URL + method combination a
> server understands, e.g. "POST to `/api/analyze`." Each endpoint usually
> does one job.
> **Why Creating Tomorrow uses it:** Each of the six tools' steps maps to
> exactly one endpoint — 13 endpoints total, all defined in `main.py`.
> **Where I can find it in the code:** every `@app.post(...)` /
> `@app.get(...)` line in `backend/main.py`.

**3. FastAPI receives it.** `main.py`'s `api_analyze()` function runs:
- Reads the uploaded file's bytes.
- Checks it's under 5 MB.
- Calls `extractor.extract_text()` to turn the `.docx`/`.pdf`/`.txt` file
  into plain text.
- Checks the job posting isn't empty and isn't absurdly long.
- Calls `coach.analyze(resume_text, job_posting)`.

**4. `coach.py` does the actual AI work.** Inside `analyze()`:
- It builds one big text prompt combining a fixed `SYSTEM_PROMPT` (Nova's
  instructions — how to compare a resume to a posting honestly) with your
  specific resume text and job posting.
- It calls:

```python
client.messages.create(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    system=SYSTEM_PROMPT,
    tools=[ANALYSIS_TOOL],
    tool_choice={"type": "tool", "name": "submit_analysis"},
    messages=[{"role": "user", "content": prompt}],
)
```

> **Anthropic API / Claude**
> **Plain-English definition:** The AI service this whole product is built
> on. You send text (a prompt), it sends back generated text (or, here,
> structured data matching a schema you provided).
> **Why Creating Tomorrow uses it:** It's the only "intelligence" in the
> entire application — every piece of analysis, every drafted bullet, every
> question is Claude's output, never hand-coded logic.
> **Where I can find it in the code:** every tool file in `backend/`
> imports `anthropic` and calls `client.messages.create(...)`.

  - The `tool_choice` part is a trick worth understanding: instead of asking
    Claude to "please respond in this JSON shape" (which can go wrong —
    extra text, a broken bracket), we force it to call a specific "tool"
    (`submit_analysis`) whose parameters are defined by a strict schema.
    Anthropic's own systems then make sure what comes back actually matches
    that schema. Three tools (Right Fit, Refine, Spotlight) use this; the
    other three still use the older, more fragile approach of asking for
    plain JSON text and parsing it by hand (`llm_utils.extract_json_object`).
  - If the response got cut off before finishing (Claude ran out of its
    token budget), `coach.py` notices (`response.stop_reason == "max_tokens"`)
    and tries **once** more before giving up with a friendly error.

**5. The validated result flows back up:** `coach.py` returns a Python dict
→ `main.py`'s `api_analyze()` returns it (FastAPI automatically turns a
Python dict into a JSON HTTP response) → the browser's `fetch()` call
receives that JSON.

**6. `app.js` renders it.** `renderMatchReport()` reads fields like
`report.match_level`, `report.strengths`, builds list items, and injects
them into the page.

**7. If you download a recap**, `app.js` makes a *second*, separate request
— `POST /api/recap` — which does **not** call Anthropic at all. It just
takes the match report you already have and formats it as a `.docx` using
`python-docx` in `resume_builder.py`. This is a good example of "not every
button press is an AI call" — worth remembering, since it affects cost.

---

## The other five tools, briefly

Now that you've seen the full pattern once, here's what's actually different
about each of the others (see `CURRENT_INFRASTRUCTURE.md` Section C for the
complete arrow-by-arrow flow of each):

- **Beginning (`scratch.py`)** — instead of one big call, it's many small
  calls: one Claude call *per experience entry* you add (`draft_entry()`),
  then one more at the end (`finalize()`). `draft_entry()` is also the only
  place in the whole app that uses Claude's built-in **web search** tool —
  it looks up what a role like yours typically involves, to write better
  reflective questions.

  > **Server-side tool use (web search)**
  > **Plain-English definition:** Some AI APIs let the model itself decide
  > to search the web mid-response, read results, and use them, all inside
  > one API call — you don't run the search yourself.
  > **Why Creating Tomorrow uses it:** So Beginning's reflective questions
  > (aimed at first-time resume writers) are grounded in what a real job
  > posting for that role actually tends to ask for, not just the model's
  > memorized guess.
  > **Where I can find it in the code:** `scratch.py`, the
  > `tools=[{"type": "web_search_20250305", ...}]` line inside `_call()`.

- **Refine (`upgrade.py`)** — one call, no job posting involved at all. Just
  "make this resume read more professionally, using only what's already
  true." Same `tool_choice` pattern as Right Fit.

- **Elevate (`elevate.py`)** — the most conversational tool: three *different*
  endpoints (`start`, `discover`, `finalize`) representing three stages of
  an interview. Each `discover()` call gets the *entire* question-and-answer
  history so far as input (sent fresh every time — there's no server-side
  memory of the conversation between calls) and decides whether to ask more
  questions or wrap up.

- **Spotlight (`profile_review.py`)** — the only tool that sends **images**
  to Claude, not just text. Screenshots get base64-encoded and sent as
  image content blocks alongside any pasted text. It's also the only tool
  whose input is explicitly optional-plus-optional (any combination of
  screenshots/pasted text/PDF, plus an optional resume for extra context).

  > **Multimodal**
  > **Plain-English definition:** An AI model that can accept more than one
  > type of input in the same request — here, text *and* images together.
  > **Why Creating Tomorrow uses it:** So Spotlight can read a LinkedIn
  > profile straight from a screenshot instead of requiring you to
  > painstakingly retype everything.
  > **Where I can find it in the code:** `profile_review.py`'s
  > `review_profile()`, the `content.append({"type": "image", ...})` line.

- **Prepare (`prepare.py`)** — takes a job description (and optionally a
  resume) and produces interview questions with plain-language reasons —
  no resume *rewriting* happens here at all, it's the only tool that
  doesn't touch `resume_builder.py`.

---

## Where privacy comes from (it's an architecture property, not a promise)

The footer says "we don't save your resume." That's not just a policy — it's
verifiably true from the code: every tool file processes your file's bytes
in memory (`io.BytesIO`), calls Anthropic, gets an answer, and returns it.
There is no `open("file.txt", "w")` anywhere, no database import anywhere,
no `localStorage`/cookie anywhere in the frontend. See
`CURRENT_INFRASTRUCTURE.md` Section E for the full verification.

> **Environment variable**
> **Plain-English definition:** A named value set outside your code (in the
> hosting dashboard, not in a file) that your program reads at runtime —
> the standard way to hand a program a secret (like an API key) without
> ever writing that secret into a file that gets committed to Git.
> **Why Creating Tomorrow uses it:** The Anthropic API key
> (`ANTHROPIC_API_KEY`) is never in the repository — it's set directly in
> Render's dashboard and read at runtime with `os.environ.get(...)`.
> **Where I can find it in the code:** `render.yaml` declares the variable
> name (`sync: false` means "I'm not telling you the value here — set it in
> the dashboard"); every tool file reads it with
> `os.environ.get("ANTHROPIC_API_KEY")`.
