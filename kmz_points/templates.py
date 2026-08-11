"""The web service's two pages.

Kept apart from server.py so that file stays about routing and uploads rather
than markup. They are strings rather than files under templates/ because the
service is a single-file affair started by hand -- no template directory to
locate, and nothing for the desktop bundle to have to exclude.

Shared style lives in _SHELL so the two pages cannot drift apart. Every page
declares its own background: without one the browser supplies the canvas, and
in dark mode that means near-black behind #1f2933 text.
"""

from __future__ import annotations

_SHELL = """<!doctype html>
<title>KML / KMZ Point Extractor</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: %(width)s; margin: 4rem auto;
         padding: 0 1rem; color: #1f2933; background: #f2f4f7; }
  h1 { margin-bottom: .5rem; }
  .note { color: #6b7785; font-size: .9rem; }
  .error { color: #b42318; }
  .warning { color: #b54708; }
  input, button { font: inherit; padding: .5rem; }
  button[disabled] { opacity: .6; cursor: progress; }
</style>
"""

LOGIN_PAGE = (
    _SHELL % {"width": "34rem"}
    + """
<h1>KML / KMZ Point Extractor</h1>
<p>Enter the team password to continue.</p>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post" action="{{ url_for('login') }}">
  <input type="password" name="password" autofocus>
  <button type="submit">Continue</button>
</form>
"""
)

UPLOAD_PAGE = (
    _SHELL % {"width": "40rem"}
    + """
<style>
  .summary { background: #f2f4f7; padding: 1rem; border-radius: .4rem;
             border: 1px solid #d5dce5; white-space: pre-line; }
  #drop-zone { border: 1px dashed #a9c6e8; background: #eaf2fd;
               border-radius: .4rem; padding: 2rem 1rem; text-align: center;
               color: #6b7785; margin: 1rem 0; }
  #drop-zone.over { border-color: #2563eb; background: #dbeafe; color: #1f2933; }
  #chosen { margin: .5rem 0; }
  #working { color: #6b7785; margin-left: .5rem; }
</style>
<h1>KML / KMZ Point Extractor</h1>
<p>Choose one or more .kml or .kmz files. You will get one Excel workbook back.</p>
<p class="note">
  Points become one row each. Areas get their own sheet, with their size in
  m², hectares and km², the distance round their outline, and their corners
  listed beneath. Routes and tracks are counted but not extracted.
</p>
<p class="note">Total upload size must be under {{ upload_limit }}.</p>

<form method="post" action="{{ url_for('convert') }}" enctype="multipart/form-data"
      id="convert-form">
  <div id="drop-zone" hidden>Drop .kml or .kmz files here</div>
  <input type="file" name="files" accept=".kml,.kmz" multiple required id="files">
  <p id="chosen" class="note"></p>
  <button type="submit" id="convert-button">Convert</button>
  <span id="working" hidden>Converting…</span>
  <input type="hidden" name="download_token" id="download-token">
</form>

{% if summary %}<div class="summary">{{ summary }}</div>{% endif %}
{% for warning in warnings %}<p class="warning">{{ warning }}</p>{% endfor %}

<script>
// Drag-and-drop. The zone stays hidden until this runs, so a browser without
// JavaScript never shows an invitation it cannot honour -- the file input
// beneath it is the real control either way.
(function () {
  var zone = document.getElementById("drop-zone");
  var input = document.getElementById("files");
  var chosen = document.getElementById("chosen");
  if (!zone || !input || typeof DataTransfer === "undefined") return;

  zone.hidden = false;

  function describe() {
    var files = Array.prototype.slice.call(input.files || []);
    chosen.textContent = files.length
      ? files.length + " file(s): " + files.map(function (f) { return f.name; }).join(", ")
      : "";
  }

  function accepted(files) {
    return Array.prototype.filter.call(files, function (file) {
      return /\\.(kml|kmz)$/i.test(file.name);
    });
  }

  ["dragenter", "dragover"].forEach(function (name) {
    zone.addEventListener(name, function (event) {
      event.preventDefault();
      zone.classList.add("over");
    });
  });

  ["dragleave", "drop"].forEach(function (name) {
    zone.addEventListener(name, function () { zone.classList.remove("over"); });
  });

  zone.addEventListener("drop", function (event) {
    event.preventDefault();
    var files = accepted(event.dataTransfer.files);
    if (!files.length) {
      chosen.textContent = "Those are not .kml or .kmz files.";
      return;
    }
    // The file input cannot be assigned a plain list; a DataTransfer is the
    // only way to hand dropped files to a form that still posts normally.
    var carrier = new DataTransfer();
    files.forEach(function (file) { carrier.items.add(file); });
    input.files = carrier.files;
    describe();
  });

  zone.addEventListener("click", function () { input.click(); });
  input.addEventListener("change", describe);
  describe();
})();

// A successful conversion is a file download, so the page never navigates and
// no load event ever fires -- without this the button would look idle while a
// large batch was still being read, and people would submit it twice. The
// server echoes the token back as a cookie once the response is on its way,
// which is the only signal a download gives us.
(function () {
  var form = document.getElementById("convert-form");
  var button = document.getElementById("convert-button");
  var working = document.getElementById("working");
  var field = document.getElementById("download-token");
  if (!form || !button) return;

  form.addEventListener("submit", function () {
    var token = String(Date.now()) + String(Math.random()).slice(2);
    field.value = token;
    button.disabled = true;
    working.hidden = false;

    var waited = 0;
    var poll = setInterval(function () {
      waited += 250;
      var arrived = document.cookie.indexOf("download_token=" + token) !== -1;
      // The time limit matters: a batch that fails before the response is
      // written sets no cookie, and a permanently dead button is worse than
      // an early one.
      if (arrived || waited > 120000) {
        clearInterval(poll);
        button.disabled = false;
        working.hidden = true;
        document.cookie = "download_token=; Max-Age=0; Path=/";
      }
    }, 250);
  });
})();
</script>
"""
)
