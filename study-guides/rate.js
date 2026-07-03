/* Post-read rating widget for explainer pages.
   Rate a paper AFTER reading it (separate from the digest's pre-read triage): how worth-it it was,
   and whether the abstract over/undersold it. Saved to localStorage['paperRatings'][slug] (shared
   origin, so the digest can read + export it). Feeds the interest ranker so it learns what you
   actually valued, not just what you clicked. Self-contained; guides load it with
   <script src="../rate.js"></script>. */
(function () {
  var slug = (location.pathname.split("/").pop() || "").replace(/\.html$/, "");
  if (!slug) return;
  var KEY = "paperRatings";
  var R = {};
  try { R = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
  function save() { localStorage.setItem(KEY, JSON.stringify(R)); }
  function cur() { return R[slug] || {}; }
  function set(patch) { R[slug] = Object.assign({}, R[slug], patch, { ts: new Date().toISOString() }); save(); }

  var box = document.createElement("div");
  box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:99999;font-family:'Mulish',system-ui,sans-serif";
  var open = !!cur().score;
  function render() {
    var c = cur();
    box.innerHTML = open ? panel(c) : pill(c);
  }
  function pill(c) {
    var label = c.score ? "★".repeat(c.score) + "☆".repeat(5 - c.score) : "★ Rate this paper";
    return '<button id="rt-open" style="background:#FFFDF8;border:1.5px solid #D8C8AC;border-radius:999px;'
      + 'padding:9px 14px;box-shadow:0 4px 14px rgba(90,66,28,.16);cursor:pointer;font-weight:800;font-size:.82rem;'
      + 'color:' + (c.score ? "#C27D14" : "#6E6456") + '">' + label + '</button>';
  }
  function panel(c) {
    var stars = [1, 2, 3, 4, 5].map(function (i) {
      return '<span data-s="' + i + '" style="cursor:pointer;color:' + (i <= (c.score || 0) ? "#E8A33D" : "#E7DBC6") + '">★</span>';
    }).join("");
    var deltas = [["under", "undersold ▲"], ["match", "matched ="], ["over", "oversold ▼"]].map(function (o) {
      var on = c.delta === o[0];
      return '<button data-d="' + o[0] + '" style="font-size:.68rem;border:1px solid ' + (on ? "#2C8C7C" : "#E7DBC6")
        + ';background:' + (on ? "#DCEFE9" : "#fff") + ';color:#332C24;border-radius:7px;padding:3px 6px;cursor:pointer">' + o[1] + "</button>";
    }).join("");
    return '<div style="background:#FFFDF8;border:1.5px solid #D8C8AC;border-radius:14px;padding:13px 15px;'
      + 'box-shadow:0 8px 22px rgba(90,66,28,.18);max-width:236px">'
      + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
      + '<span style="font-weight:800;font-size:.82rem;color:#332C24">Was this paper worth it?</span>'
      + '<span id="rt-close" style="cursor:pointer;color:#9A8E7C;font-size:1rem;line-height:1">×</span></div>'
      + '<div id="rt-stars" style="font-size:1.6rem;letter-spacing:3px">' + stars + "</div>"
      + '<div style="font-size:.72rem;color:#6E6456;margin:8px 0 3px">vs. what the abstract promised:</div>'
      + '<div style="display:flex;gap:4px">' + deltas + "</div>"
      + '<div id="rt-msg" style="font-size:.68rem;color:#2C8C7C;margin-top:8px;font-family:\'JetBrains Mono\',monospace">'
      + (c.score ? "saved ✓ feeds your recommender" : "tap a star — feeds your recommender") + "</div></div>";
  }
  box.addEventListener("click", function (e) {
    if (e.target.id === "rt-open") { open = true; return render(); }
    if (e.target.id === "rt-close") { open = false; return render(); }
    var s = e.target.closest("[data-s]"), d = e.target.closest("[data-d]");
    if (s) { set({ score: +s.getAttribute("data-s") }); render(); }
    if (d) { set({ delta: d.getAttribute("data-d") }); render(); }
  });
  render();
  document.body.appendChild(box);
})();
