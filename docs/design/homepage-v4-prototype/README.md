# Homepage Version 4: approved design reference (not deployed)

This folder holds the approved Creating Tomorrow Version 4 homepage prototype. It lives under `docs/`
on purpose: Render serves only `frontend/`, so none of this is publicly reachable. The live homepage
(`frontend/index.html`) is unchanged.

Status: design approved on 2026-10-09; waiting for final photography and mascot assets.

## What is here
- `home-v4.html` / `home-v4.css`: the prototype in the dashboard's look (raised cards, glossy colored icons, gradient buttons):
  hero, six compact tool cards, then ONE bottom row: How It Works on the left, the Chicago 2150 picture with the promise on the right.
  Close to one screen at desktop width. The dashboard preview box was removed on purpose.
- `img/hero-placeholder.jpg`: PLACEHOLDER portrait (a crop from the approved mockup).
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
