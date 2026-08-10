# LAN conversion service

Date: 2026-08-10
Status: approved, not yet implemented

## Problem

The KML/KMZ point extractor is a desktop app shipped as an `.exe` and a `.dmg`.
Colleagues who want a workbook currently have to install it. The owner wants to
run one instance on their own laptop and let colleagues use it from a browser
instead.

## Decisions

Settled before design, and the design depends on all five:

| Question | Decision |
|---|---|
| How colleagues reach it | A web page they open in a browser |
| Network reach | Office LAN only. No tunnel, no public exposure |
| What is retained | Nothing. Convert and forget |
| Access control | One shared password for the team |
| How it starts | Started by hand by the owner, not on login |

Rejected, with reasons, so they are not silently revisited:

- **Colleagues install the desktop app.** Already possible and needs no new
  code, but defeats the point: the owner wants zero install on their side.
- **Remote access via a tunnel.** Would require real authentication and TLS.
  Not needed while everyone is on one network.
- **Keeping a history of conversions.** Needs storage, a cleanup job, and a
  rule stopping one person seeing another's files. Retaining nothing removes
  all three problems.
- **Per-user accounts.** Only worth building to know who did what, which
  contradicts keeping nothing.

## Approach

Flask, chosen over a `http.server` implementation and over FastAPI.

The security- and correctness-sensitive part of this feature is multipart
upload parsing. Flask delegates that to Werkzeug, which is well tested. A
standard-library version would mean hand-rolling it, and the `cgi` module that
used to help was removed in Python 3.13. FastAPI was rejected as the wrong
shape: the work is CPU-bound KML parsing and openpyxl writing for a handful of
users, so async buys nothing and costs a much larger dependency tree.

The service stays **out of the packaged `.exe`/`.dmg`**. Only the owner runs the
server; colleagues just open a browser. Bundling Flask would add hidden imports
and Jinja2 template data to `build.spec` for no benefit to anyone using it.

## Architecture

A third shell over the existing core, alongside the two that already exist:

```
        gui.py          cli.py          server.py   <- new
      (tkinter)      (argparse)          (Flask)
           \             |                 /
            \            |                /
             ------ pipeline.py ----------
              load_file . export_to_*
                        |
        archive . kml_parser . table . excel
```

### New files

**`kmz_points/server.py`** — `create_app(password, max_upload_bytes)` returns a
configured Flask app. A factory rather than a module-level global, so each test
builds its own instance.

Three routes:

- `GET /` — password form when unauthenticated, upload page otherwise
- `POST /login` — checks the shared password, establishes a session
- `POST /convert` — accepts files, returns one `.xlsx`

**`serve.py`** — repo-root launcher mirroring the existing `run.py`. Reads the
password, binds the LAN address, prints the URL to share.

**`tests/test_server.py`** — Flask test-client coverage.

### Changed files

**`kmz_points/excel.py`** — `write_workbook`'s second parameter widens from
`path: str | Path` to `target: str | Path | BinaryIO`, and the return type from
`Path` to `Path | None`, returning `None` when handed a stream. `openpyxl`'s
`save()` already accepts both; the only behavioural change is skipping
`target.parent.mkdir(...)` when the target is not a path. Renaming the
parameter is safe: both existing call sites pass it positionally, so no keyword
caller can break. The return value is currently unused by every caller.

It also gains an optional `issues: list[str] | None = None`, which appends the
`Issues` sheet described under "Reporting partial failures". Both existing call
sites omit it, so the desktop app's workbook is unchanged.

**`kmz_points/pipeline.py`** — `export_to_excel` currently does two jobs:
aggregating points and warnings into a `BatchSummary`, and writing a file. The
aggregation moves into `_collect(loaded) -> (points, summary)`, used by both
`export_to_excel` (unchanged signature and behaviour) and a new
`export_to_stream(loaded, stream) -> BatchSummary`. Without this split the
summary logic would be duplicated and the two paths would drift.

There is deliberately no `when` parameter, unlike `export_to_excel`: it would be
unused, because a stream has no filename to stamp. The download name is chosen
by the server, which calls `output_filename()` itself.

`export_to_stream` matches `export_to_excel`'s existing early-return contract:
when the batch yields no points it writes nothing to the stream, appends the
same "No points found" warning, and returns. It leaves `summary.output_path` as
`None` in all cases, because a stream has no path — so the server must decide
whether a workbook exists from `summary.points_extracted`, not from
`output_path`. `as_text()` therefore omits its "Saved to" line for stream
exports, which is right: on the success path the summary is not rendered at all,
and the failures it would have carried travel on the workbook's `Issues` sheet.

**`requirements.txt`** — adds `flask` under a marked web section, so it is clear
it is not needed for the desktop app.

**`build.spec`** — `flask` added to the existing `excludes` list, so it can
never accidentally enter the desktop bundle.

## Data flow

One conversion, start to finish:

1. Colleague opens `http://<laptop-lan-ip>:8000/`, enters the shared password.
2. `POST /login` compares it with `hmac.compare_digest` and sets a session
   cookie. Failure re-renders the form with an error; no lockout, no logging.
3. They select one or more KML/KMZ files and submit to `POST /convert`.
4. The handler creates a per-request temporary directory.
5. Each upload is written into it under `secure_filename(...)` only — the
   client-supplied path is never used.
6. Each file goes through the existing `load_file`, which never raises and
   reports unreadable files as errors on the returned object.
7. `export_to_stream` writes one workbook into a `BytesIO`, or writes nothing if
   the batch yielded no points. Any warnings are written into the workbook
   itself, on a second sheet named `Issues` — see "Reporting partial failures".
8. If `summary.points_extracted` is greater than zero, the response is that
   buffer as
   `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, named
   by the existing `output_filename(when)` helper. Otherwise the upload page
   re-renders with the summary and no download.
9. The temporary directory is removed as the request ends, whatever the outcome.

Nothing is written outside that temporary directory at any point.

## Error handling

The pipeline's existing contract is that a batch containing a corrupt file, a
KMZ with no KML inside, or a document with zero points still exports everything
it could read and reports the rest as warnings. The service preserves this
rather than converting partial success into an error:

| Condition | Response |
|---|---|
| Not authenticated | Redirect to `/`, nothing converted |
| Wrong password | Form re-rendered with an error |
| No files selected | Upload page with a message |
| Some files unreadable | Workbook returned, with the failures on its `Issues` sheet |
| No points in any file | Upload page with the summary, no download |
| Upload over the size cap | HTTP 413 |

## Reporting partial failures

A batch where some files are unreadable still exports every point it could
read. On the desktop that partial failure is reported in the window; in a
browser there is nowhere to put it, because the response body **is** the
workbook. An earlier draft of this spec required the failures to reach the user
and separately prescribed returning the raw file, which cannot both be true. A
prototype confirmed the consequence: three good files plus a corrupt one
returned a workbook, `files_failed=1`, and no mention of the corrupt file
anywhere in the response.

Resolved by putting the failures inside the artifact. When a batch produces any
warnings, the workbook gains a second sheet named `Issues` listing them, after
the `Points` sheet so that opening the file still lands on the data. The
information then survives being emailed on, which a web page would not.

This applies to the web path only. `export_to_excel` passes no issues, so the
desktop app's output is unchanged.

Rejected alternatives: a results page carrying a one-shot download link, which
would mean holding the workbook in memory between two requests and so
contradict retaining nothing; and reporting the failures in a response header,
which no colleague would ever see.

## Security

Scaled to a trusted office LAN, not to the public internet.

- Password compared with `hmac.compare_digest` (constant time)
- Supplied via the `KMZ_PASSWORD` environment variable, or prompted at startup
  with `getpass`. Never hardcoded, never committed
- Session secret generated randomly at startup and not persisted. Restarting
  signs everyone out, which suits a service that retains nothing
- Session cookie set `HttpOnly` and `SameSite=Lax`
- `MAX_CONTENT_LENGTH` caps uploads at 50 MB by default
- Uploads written under `secure_filename` inside a per-request temp directory

### Accepted limitations

**No TLS.** This is plain HTTP. The shared password and the uploaded files
travel the LAN in clear text, and anyone able to sniff that network can read
both. This is an accepted trade-off for internal data on a trusted office
network; TLS would require certificates every colleague's browser trusts, which
is disproportionate here. Revisit this decision if the data stops being
internal, or if the service is ever exposed beyond the LAN.

**No rate limiting.** Unnecessary for a known, small group of colleagues.

**Flask's development server**, run with `threaded=True` so one large
conversion does not block other users. Adequate at this scale. `waitress` is
the drop-in upgrade if it stops being adequate.

**Availability is bounded by the laptop.** The service is reachable only while
the laptop is awake, running the server, and on the office network. Colleagues
cannot distinguish "the service is down" from "you went home". This is inherent
to the chosen deployment, not a defect.

**The LAN address can change.** DHCP may hand the laptop a different IP between
sessions, changing the URL colleagues need.

## Launcher

`serve.py` reads the password, binds `0.0.0.0`, determines the LAN IP, and
prints what to paste into chat:

```
  Share this:  http://192.168.1.42:8000
  Stop with Ctrl-C
```

## Testing

Flask's test client, so no network and no display are needed and the tests run
unchanged on all four CI platforms.

`tests/test_server.py`:

- unauthenticated `POST /convert` converts nothing
- wrong password rejected; correct password establishes a session
- the three generated samples return 200, the xlsx content type, and a workbook
  that reopens with 7 data rows
- one corrupt file among good ones still returns a workbook, and its `Issues`
  sheet names the failure. Asserted by loading the returned workbook, not by
  searching the response bytes: an xlsx is a zip, so the text is compressed and
  a substring check fails even when the sheet is there
- a batch yielding zero points returns the summary and no download
- an upload over the cap returns 413
- a `../../evil.kml` filename stays inside the temp directory

Guarding the `pipeline.py` refactor specifically, so the split cannot drift
unnoticed:

- `write_workbook` into a `BytesIO` produces a workbook that reopens correctly
- `export_to_stream` and `export_to_excel` produce identical summaries for
  identical input

Existing tests must continue to pass unchanged. Sample inputs come from the
existing `write_samples` helper, matching the fixture style already used
throughout the suite.

## Out of scope

- Any change to `gui.py` or `cli.py` behaviour
- Packaging the server into the `.exe` or `.dmg`
- Remote or internet access, tunnels, TLS
- Stored history, user accounts, audit logging
- Auto-start on login
