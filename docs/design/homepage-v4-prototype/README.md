# Homepage Version 4: approved design reference (not deployed)

This folder holds the approved Creating Tomorrow Version 4 homepage prototype. It lives under `docs/`
on purpose: Render serves only `frontend/`, so none of this is publicly reachable. The live homepage
(`frontend/index.html`) is unchanged.

Status: design approved on 2026-10-09; waiting for final photography and mascot assets.

## What is here
- `home-v4.html` / `home-v4.css`: the prototype in the dashboard's look (raised cards, glossy colored icons, gradient buttons):
  hero, six compact tool cards, a short 'what we stand for' strip, the six tools with the Alan Kay quote in one box, then How It Works (number + icon + arrow flow, each step clickable), and a full-width Chicago 2150 band with the promise at the bottom.
  Close to one screen at desktop width. The dashboard preview box was removed on purpose.
- `img/hero-man.jpg`: hero portrait (concept image, a man looking up with the Chicago skyline behind him). `img/hero-placeholder.jpg` is the older woman placeholder, no longer used. Licence check needed before launch.
- `img/chicago-2150.jpg`: concept image of a future Chicago from Grant Park (caption cropped off). Needs a licence check or a commissioned replacement before launch.

## To preview it locally
The page uses paths relative to a folder inside `frontend/` (`../logo-icon.png`, `../mascot-icon.png`, `../auth-nav.js`, `../tool.html`...).
To view it, temporarily copy this folder to `frontend/prototype/`, run the site, open `/prototype/home-v4.html`,
and delete the copy afterwards (never commit it under `frontend/`).

## Asset replacements still to do
(Full specs, file names and exactly where each one is wired: see `ASSETS.md`.)
1. Replace the hero portrait with commissioned or licensed photography.
2. Confirm the licence of the Chicago 2150 concept image (or replace it with commissioned artwork).
3. Replace the low-resolution mascot crops (`frontend/mascot-welcome.png`, `frontend/mascot-icon.png`) with final production assets.

## When converting the real homepage
Re-create this design in `frontend/index.html` using the existing homepage content and tools (Guide Me must open the existing Guide),
keep the same copy, and do not ship the placeholder images.

## Status update (2026-10-07)
The live homepage (`frontend/index.html` + `frontend/home-v4.css`, pictures in `frontend/img/home/`) is now built from this design.
Differences from this prototype: Career Basics replaces the "what we stand for" strip; the header is the shared site header (same as the dashboard);
"Guide Me" opens the existing Guide modal (guide.js, data-guide-open buttons). This folder stays as the design reference.
