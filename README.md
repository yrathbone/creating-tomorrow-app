# Creating Tomorrow

The public web app: upload your old resume + paste a job posting, get an
honest A-F match report, answer a few reflective yes/no questions about
experience you might have forgotten to write down, and download a new
ATS-friendly resume with only the things you actually confirmed.

Built on top of the same logic as the local `resume-tool` scripts, wrapped
in a FastAPI backend and a plain HTML/JS frontend (no build step, no
framework — kept deliberately simple to stay manageable).

## How it works

1. `POST /api/analyze` — takes the uploaded resume file + job posting
   text, calls the Claude API once to restructure the resume into a clean
   JSON shape, produce the match report, and generate a handful of
   reflective questions.
2. The browser shows the report and questions. Nothing is saved
   server-side — the resume data lives in the browser tab only, for that
   session.
3. `POST /api/generate` — takes the (possibly updated, based on confirmed
   answers) resume JSON and returns a `.docx` file, built with
   `python-docx` exactly like the local tool.

## Running it locally

```
cd backend
pip install -r requirements.txt
set ANTHROPIC_API_KEY=sk-ant-...        (or setx, to persist it)
uvicorn main:app --reload --port 8000
```

Then open http://127.0.0.1:8000 — the backend also serves the frontend
directly, so there's nothing separate to run.

## Deploying to Render

### One-time setup (only if you haven't already)

1. **GitHub account**: [github.com/signup](https://github.com/signup)
2. **Render account**: [dashboard.render.com/register](https://dashboard.render.com/register)
   — sign up with your GitHub account so the two are linked.

### Push this folder to GitHub

From this folder (`creating-tomorrow-app`):

```
git init
git add .
git commit -m "Initial Creating Tomorrow web app"
```

Then on GitHub: create a new repository (no README/license — this folder
already has one), and follow the "push an existing repository" instructions
it shows you, e.g.:

```
git remote add origin https://github.com/YOUR-USERNAME/creating-tomorrow-app.git
git branch -M main
git push -u origin main
```

### Connect Render

1. In the Render dashboard: **New > Blueprint**.
2. Pick the `creating-tomorrow-app` GitHub repo. Render reads `render.yaml`
   automatically and configures the service.
3. It will ask you to set `ANTHROPIC_API_KEY` — paste your key directly
   into the Render dashboard field (never into a chat, a commit, or this
   README). Get a key at
   [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
   if you don't have one yet.
4. Deploy. Render gives you a `*.onrender.com` URL immediately.

### Point wrenpath.org at it

In Render: service **Settings > Custom Domains**, add `wrenpath.org` (and
`www.wrenpath.org` if you want both). Render shows you the exact DNS
records to add. Go to wherever you bought the domain, open its DNS
settings, and add those records. DNS changes can take up to a few hours to
take effect.

## Cost

- Render free tier works for testing, but the service goes to sleep after
  15 minutes of no traffic and takes ~30-60 seconds to wake back up on the
  next request. Fine for early testing, not great for real users — the
  Starter plan ($7/month) keeps it always-on.
- Every `/api/analyze` call is one Claude API request — this is the
  recurring, usage-based cost to budget for as traffic grows. Check
  current pricing at [anthropic.com/pricing](https://www.anthropic.com/pricing).
- `/api/generate` is free (pure Python, no API call).

## Privacy note

No resume or job posting text is written to disk or a database anywhere
in this app — everything happens in-memory per request, and the only
thing that leaves the server is what's sent back to the browser that made
the request. Worth stating explicitly on the site itself once it's live.
