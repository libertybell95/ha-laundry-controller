# Branding brief

Laundry Controller works without any images; Home Assistant shows a generic
placeholder until brand images exist. This brief lists the assets worth making
and contains a prompt to paste into ChatGPT (or another image generator).

## Assets and where they go

### Used by Home Assistant directly

Since Home Assistant 2026.3, custom integrations ship brand images in a
`brand/` folder inside the integration
([developer blog](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api)).
They appear in Settings → Devices & services, the integration page and the
"Add integration" dialog. Requirements follow the
[home-assistant/brands](https://github.com/home-assistant/brands) spec: PNG,
transparent background, trimmed (no empty margin), losslessly compressed.

| File (in `custom_components/laundry_controller/brand/`) | Size | Use |
| --- | --- | --- |
| `icon.png` | 256 × 256 | Square icon, light UI |
| `icon@2x.png` | 512 × 512 | Same, high-DPI |
| `dark_icon.png` | 256 × 256 | Square icon, dark UI |
| `dark_icon@2x.png` | 512 × 512 | Same, high-DPI |
| `logo.png` | landscape, height 128–256 (use 256 high) | Icon + "Laundry Controller" wordmark, light UI |
| `logo@2x.png` | landscape, height 256–512 (use 512 high) | Same, high-DPI |
| `dark_logo.png` | as `logo.png` | Dark UI |
| `dark_logo@2x.png` | as `logo@2x.png` | Dark UI |

Home Assistant 2025.3–2026.2 cannot read the `brand/` folder; on those versions
the images only appear if they are also submitted to the
`custom_integrations/laundry_controller/` folder of the home-assistant/brands
repository (a separate pull request with the same files). This is optional.

HACS uses the same brand images for its listing; no separate HACS asset is
needed.

### Separate distribution (GitHub only)

| File | Size | Use |
| --- | --- | --- |
| `docs/images/banner.png` | 1280 × 400 | Top of the README |
| `docs/images/social-preview.png` | 1280 × 640 | GitHub → Settings → Social preview (upload manually; under 1 MB) |

Not needed: favicons, app-store icons, animated assets, Lovelace card art.

## Prompt for ChatGPT

Copy everything inside the box.

````text
Create a small, consistent brand kit for an open-source Home Assistant
integration called "Laundry Controller". It monitors a washing machine and a
tumble dryer, reminds people when laundry is waiting, and announces when the
dryer is done.

VISUAL CONCEPT
- One simple, friendly symbol: a front-loading washing machine seen straight
  on, whose round door contains a small circular arrow or a check mark,
  suggesting "cycle tracked / laundry done".
- Optional tiny accent: a single small notification dot on the top-right of the
  machine body (like an app badge). Keep it subtle.
- Flat vector style, rounded corners, consistent 2-level stroke weights, no
  gradients or only a very soft one, no drop shadows, no text inside the icon,
  no photo-realism, no 3D. Must stay recognizable at 32 × 32 px.
- It must look at home next to Home Assistant's own icons (clean, modern,
  geometric, slightly rounded), but must NOT use the Home Assistant house logo
  or claim to be an official Home Assistant product.

COLOR PALETTE
- Primary blue: #0050FF (taken from the integration's default LED colour
  0,80,255)
- Light blue accent: #41BDF5
- Ink (outlines on light backgrounds): #1F2933
- White: #FFFFFF
- Badge/accent (sparingly): #FFB020
- Dark-mode variants: replace ink outlines with #E6EDF3 and lighten the blue to
  #4D86FF so the symbol stays visible on #111418 backgrounds.

FILES TO PRODUCE (all PNG, fully transparent background, trimmed so the artwork
touches the edges with no empty margin, sRGB)
1. icon.png          256 x 256   symbol only, for light backgrounds
2. icon@2x.png       512 x 512   same, double resolution
3. dark_icon.png     256 x 256   symbol only, for dark backgrounds
4. dark_icon@2x.png  512 x 512   same, double resolution
5. logo.png          landscape, exactly 256 px tall: the symbol on the left,
                     wordmark "Laundry Controller" on the right in a clean
                     geometric sans-serif (similar to Figtree, Inter or Nunito),
                     ink colour; for light backgrounds
6. logo@2x.png       same, exactly 512 px tall
7. dark_logo.png     like logo.png, light wordmark (#E6EDF3), for dark
                     backgrounds
8. dark_logo@2x.png  same, exactly 512 px tall
9. banner.png        1280 x 400, NOT transparent: soft light background
                     (#F5F8FF to white), logo on the left half, short tagline
                     on the right: "Washer and dryer tracking for Home
                     Assistant". Leave generous padding.
10. social-preview.png 1280 x 640, NOT transparent: same style as the banner,
                     logo centered, tagline below it, safe area of 80 px on
                     all sides.

CONSISTENCY
- The symbol must be identical (same geometry) across all files; only colours
  change for dark variants.
- Icons 1–4 must be perfectly square.
- Logos 5–8 must have the same proportions as each other.

Deliver each file separately with exactly the filename above.
````

## After generating

1. Check transparency and trimming (no margin) for files 1–8; check sizes.
2. Optimise losslessly (e.g. `oxipng -o max *.png`).
3. Put files 1–8 in `custom_components/laundry_controller/brand/` and files 9–10
   in `docs/images/`.
4. Add `![Laundry Controller](docs/images/banner.png)` to the top of the README.
5. Upload `social-preview.png` in the GitHub repository settings.
