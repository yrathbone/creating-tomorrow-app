# Button colour scheme

One colour per job, so a visitor learns what a button does from its colour. Approved 2026-10-13.

| Role | Colour | Used for | Examples |
|---|---|---|---|
| **Blue** (solid) | royal blue `#003395` (dashboard `--v4-blue`) | the everyday main action on a screen | Upload my resume, + Add a job, Continue, Save, Add role, Download resume |
| **Gold** (solid, dark text) | `#FFB000` (the dashboard's own gold is `#FFBC00`) | start here, get going | Learn (hero button), Get started today, Build a general resume, I applied for this job, Check the posting's keywords |
| **Green** (solid) | `#1F7A3F`, hover `#16602F` | explore and compare | Career Tools (hero button, opens the Guide popup), Compare to my Career Profile, Explore these with me, Scan for missing skills, Analyze my resume, Review my profile, Prepare me |
| **Crimson** (solid) | `#C8102E`, hover `#8F0B22` | the one action that builds your document | Build my resume, Generate my resume, Build my elevated resume |
| **Outline** (blue border, white fill) | cobalt border | secondary or neutral | Cancel, Skip this job, Compare a different job, Make this my default |
| **Delete** (outline, red text) | `#B93030` | permanent or destructive | Permanently delete everything, the Remove and Delete buttons on cards |

Rules:
- Crimson is reserved for building the document. Because Delete is outlined, a solid red always means Build.
- Use at most one crimson button on a screen.
- Text on every solid colour is white, except gold, which uses dark text. All pairs meet 4.5:1 contrast.
- Crimson is also the colour of "Privacy & Terms" in the footer; that is a link, not a button.
- Button labels are sentence case ("Build my resume", "Add a job"). Only the names of pages and tools keep their capitals: Career Tools, Learn, Right Fit, Elevate, Spotlight, Prepare, Beginning, Refine, plus proper names such as LinkedIn, Career Profile and ATS. Decided 2026-11-03.

How it is built:
- `.btn-green` and `.btn-crimson` are defined in `frontend/style.css` (every page), `frontend/pages-v4.css` (free tools) and `frontend/career/dashboard-v4.css` (signed-in dashboard). The homepage uses `.h5-btn-green` in `frontend/home-v5.css`.
- Put the class on the button in the HTML. Do not add colour rules by id.
- `backend/tests/frontend/button_scheme.test.js` lists exactly which buttons are green and crimson. To add one, add it to that table and to this page.
