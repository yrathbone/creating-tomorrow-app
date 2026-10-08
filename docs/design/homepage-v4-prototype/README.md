# Homepage Version 4: approved design reference (not deployed)

This folder holds the approved Creating Tomorrow Version 4 homepage prototype. It lives under `docs/`
on purpose: Render serves only `frontend/`, so none of this is publicly reachable. The live homepage
(`frontend/index.html`) is unchanged.

Status: design approved on 2026-10-09; waiting for final photography and mascot assets.

## What is here
- `home-v4.html` / `home-v4.css`: the prototype exactly as approved (hero, six compact tool cards, How It Works,
  twilight Chicago closing band). The dashboard preview section was removed on purpose.
- `img/hero-placeholder.jpg`: PLACEHOLDER portrait (a crop from the approved mockup).
- `img/chicago-twilight-placeholder.jpg`: PLACEHOLDER twilight Chicago image (a darkened, blue-toned grade of a reference photo).

## To preview it locally
The page uses paths relative to a folder inside `frontend/` (`../logo-icon.png`, `../mascot-icon.png`, `../auth-nav.js`, `../tool.html`...).
To view it, temporarily copy this folder to `frontend/prototype/`, run the site, open `/prototype/home-v4.html`,
and delete the copy afterwards (never commit it under `frontend/`).

## Asset replacements still to do
1. Replace the hero portrait with commissioned or licensed photography.
2. Replace the twilight Chicago image with commissioned or licensed Chicago photography (Grant Park / Museum Campus views).
3. Replace the low-resolution mascot crops (`frontend/mascot-welcome.png`, `frontend/mascot-icon.png`) with final production assets.

## When converting the real homepage
Re-create this design in `frontend/index.html` using the existing homepage content and tools (Guide Me must open the existing Guide),
keep the same copy, and do not ship the placeholder images.
