# Asset slots: what to replace, where, and the specs

Everything visual on the Version 4 homepage that is a placeholder is listed here. Replace the files (keep the names, or change the one
reference named in the "Where" column) and nothing else about the design changes.

| Slot | Today (placeholder) | Where it is wired | Final asset to supply |
|---|---|---|---|
| Hero portrait | `img/hero-placeholder.jpg` (a 560 x 336 crop from a mockup) | `<img>` in the `.hv-hero-photo` block of `home-v4.html` (marked `ASSET SLOT`), plus its `alt` text | One licensed or commissioned photo of a real person, warm natural light, Chicago visible behind. At least 1800 x 1080, JPG or WebP, subject right of centre (the left 20% fades to white), eyes toward the text. Write new alt text describing the real photo. |
| Chicago picture (bottom-right card) | `img/chicago-2150.jpg` (concept image, 1800 x 576, caption cropped off) | One CSS variable: `--hv-closing-image` at the top of `home-v4.css` | The final Chicago artwork, about 1800 x 576 (3.1:1), JPG or WebP, no text baked in. Sky on top (it fades into white behind the words), skyline across the lower two thirds. |
| Mascot accent | `../mascot-icon.png` (128 px crop from a concept sheet) | `<img class="hv-sprout">` in `home-v4.html` (marked `ASSET SLOT`) | Final sunflower mascot, transparent PNG at 600 px or SVG, small-size friendly "icon" pose. |
| Dashboard mascot (separate, already live) | `frontend/mascot-welcome.png`, `frontend/mascot-icon.png` | `frontend/career/login.html` | Same final mascot set (welcome pose and icon pose). |
| Dashboard skyline (separate, already live) | An illustration generated into `frontend/career/dashboard-v4.css` | One CSS variable: `--v4-hero-art` | Optional: a designer-made transparent skyline PNG/SVG (change only that variable). |

Licence note: keep the licence or commission paperwork for each photograph with the project records before launch.
