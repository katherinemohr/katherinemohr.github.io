# Adding a guide

1. Write the guide as a single self-contained HTML file (own `<html>`, inline CSS/JS — no build step) and drop it in this folder, e.g. `guides/my-topic.html`.
   - Optional: add `<script src="../rate.js"></script>` near the end of `<body>` to get the floating post-read star-rating widget (saved to `localStorage`, keyed by filename).
2. Add an entry to the `#papers-data` JSON array in `../index.html` (between the `GUIDES_START` / `GUIDES_END` markers):

   ```json
   {
     "slug": "my-topic",
     "file": "guides/my-topic.html",
     "cat": "note",
     "title": "My Topic",
     "desc": "One-line description shown on the card.",
     "venue": "Guide",
     "year": 2026,
     "topics": ["tag-one", "tag-two"],
     "added": "2026-07-02"
   }
   ```

   - `cat` is one of `note` / `paper` / `other` — controls which folder tab it shows under.
   - `venue`/`year` are shown as a tag; use whatever's meaningful (`"Guide"`, `"Course"`, a conference name, etc).
   - `added` (ISO date) controls sort order in the "Recent" section.
3. Delete the placeholder `example-guide` entry once you've added your own.

That's it — no rebuild step, just commit and push.
