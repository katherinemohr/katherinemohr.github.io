# Study Guides

A self-contained study library section of this site, served at `/study-guides/`. Plain
HTML/CSS/JS — no build step, no dependency on the rest of the Jekyll site. This folder is a
generic scaffold (landing page, guide-card schema, offline PWA support, post-read rating
widget, an empty paper-triage inbox) — see `guides/README.md` for how to add a guide.

```
study-guides/
  index.html            # library landing page — cards, filters, "save offline" button
  digest.html            # empty paper-triage inbox template (needs its own feed of papers)
  rate.js                 # optional post-read star-rating widget, included by individual guides
  sw.js / manifest.webmanifest / icon*.svg   # PWA offline support
  guides/
    README.md            # schema for adding a new guide
```

## Adding a new guide

See [`guides/README.md`](guides/README.md).

## Notes

- Everything here is public, like the rest of the site.
- `digest.html` is a shell with no data wired up — it expects a feed of paper metadata (see the
  comment above `#data` in that file for the shape). Nothing currently populates it.
