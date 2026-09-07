# hashpass / hashengine split + task pool — design

**Status:** draft for review
**Date:** 2026-09-08
**Supersedes/extends:** builds on the current single-`hashpass` CLI (`src/hashpass/`), the
registry (`src/hashpass/registry/`), the two-tier key/evidence system (`key.py`,
`evidence.py`, `server/verify.py`, `sync.py`), and the image/task stores.

## 1. Overview

Split the single `hashpass` tool into two user-facing commands sharing one core, and turn the
dev-only local registry into a real network **pool** that hosts a numbered curriculum of tasks,
authenticates users, records per-student pass/fail progress, and exposes a web dashboard for
teachers.

- **`hashpass`** — the **student** command. Installed on student machines by a one-line installer
  **served by the pool site** (so the pool URL is implicit). First run forces registration/login
  against the pool. Running with no arguments
  pulls new task images (in parallel), lists tasks by number with pass status, and runs one.
- **`hashengine`** — the **author/teacher** command. Adds image authoring (`build`), publishing
  (`push --task N`), the pool server (`serve`, with the web UI), and author login. **Not present
  on a student machine**: it is a separate distribution whose clean install requires web
  authorization (author role) against the pool.
- **pool server** (`hashengine serve`) — a network HTTP service: registry (image/task blobs) +
  auth with roles + registration toggle + numbered catalog + per-student progress + grade
  submission + a server-rendered web dashboard.

Both commands self-update from GitHub releases of the same repo.

## 2. Goals / non-goals

**Goals**
- Clean student/author separation at the packaging level (student machine never carries authoring
  or server code).
- Server-hosted curriculum: tasks carry a **number**; `push --task N` places a task at position N.
- Mandatory identity: a real login on the pool, capturing **ФИО (full name)**, **group**, and a
  free **comment**; `student_id` becomes the real login (today it is hardcoded `"local"`).
- Persistent, server-side pass/fail progress per student, viewable by teachers in a web UI.
- Fast task delivery: parallel (multi-threaded) pull of new/changed images at launch (foreground,
  not a background daemon).
- **Basic** task-integrity: the pool refuses to sign a completion for a task whose content hash
  does not match what was published.
- One-command install served by the pool site (`curl https://<pool>/install.sh | bash`) and
  in-place auto-update from GitHub. No installer lives in the repo; `make install` stays for authors.
- Author-tool install gated by web authorization (author role).

**Non-goals**
- Not a hardened, internet-scale auth system. PBKDF2 + HMAC bearer tokens (already present) are the
  ceiling; TLS is delegated to a reverse proxy the operator runs.
- Not tamper-proof against a student with local root (they run the container). Integrity is
  "casual-cheating-resistant", per the user's "базовую защиту, не прямо какую-то там".
- No change to the DSL, the nspawn/overlay runtime, or the live-console grading mechanics.
- No deploy to the legacy server `185.212.148.108:8000` (see constraints).

## 3. Global constraints

Copied verbatim into the implementation plan; every task inherits these.

- **No deploy to `185.212.148.108:8000`** (the legacy Flask app). The new pool is a fresh,
  self-hosted component; it is **built and tested locally only**. Actually standing it up on a
  real host is the operator's action, not this work's.
- **Local build/test only** for containers (tier3 needs scoped sudo: mount/umount, systemd-nspawn,
  rsync, tar, machinectl). Pure logic is tier1; HTTP round-trips are tier1/tier2 against a
  loopback server.
- **Push to `origin/main` is allowed** (user lifted the no-remote-push rule on 2026-09-08).
- **Network calls to GitHub** (auto-update) and to the pool must be **mockable** in tests and must
  **fail open/quietly** (a down pool or offline GitHub never bricks the tool).
- Python **3.13**; standard library only for the server and web UI (no Flask/Jinja);
  no new runtime dependencies without calling it out.
- Server binaries carry a security note; the pool binds a configurable host (default still
  loopback) and **requires auth** for every mutating or credit-granting request.

## 4. Architecture

### 4.1 Packaging (two distributions, shared core)

```
src/
  hashcore/     # shared library (renamed from most of today's hashpass.*)
                #   recipe, canon, compare, render, imagestore, registry (client + blob + refs +
                #   auth primitives), runner, taskrun, taskstore, key, evidence, sync, grade
  hashpass/     # STUDENT cli only: register/login, pull (parallel), run, list-by-number, submit
  hashengine/   # AUTHOR/SERVER cli: build, push --task N, serve (+web), login, images
packaging/
  hashpass/     # distribution "hashpass": ships hashcore + hashpass; entry point `hashpass`
  hashengine/   # distribution "hashengine": depends on "hashpass"; adds hashengine; entry `hashengine`
```

- Two installable **distributions**: `hashpass` (student — includes `hashcore`, exposes only the
  `hashpass` script) and `hashengine` (depends on `hashpass`, adds the `hashengine` script).
  Installing `hashpass` never places the `hashengine` command on the machine.
- `make install` → installs `hashengine` (editable) for authors, which pulls `hashpass`/`hashcore`.
- Student install path → installs the `hashpass` distribution only (see §8).
- **DECISION (default):** two distributions, `hashengine` depends on `hashpass`, no separate
  `hashcore` distribution (core lives inside the `hashpass` dist). Lighter than three dists; a
  student needs core to run tasks anyway. *(Alternative, if preferred: three dists with a standalone
  `hashcore`. More separation, more packaging surface.)*
- The big mechanical cost is the import rename `hashpass.* → hashcore.*` across the tree; this is
  Phase 1 and lands before any behavior change.

### 4.2 Homes on disk

- Student: `~/.hashpass/` — `images/` (pulled), `creds.json`, `pool.json` (pool URL + cached
  identity), `update.json` (last update-check stamp).
- Engine/server: `~/.hashengine/` — `registry/{store/, users.json, catalog.json,
  progress/<user>.json, config.json, secret}`.
- `hashcore.Home` is parameterized by app name so both reuse the same path logic.

### 4.3 Component diagram (data flow)

```
author:  hashengine build ─► local image/task store ─► push --task N ─► POOL /image,/task,/catalog
teacher: browser ─► POOL /web (login, dashboard, users, registration toggle)
student: hashpass (first run) ─► POOL /register|/login ─► token
         hashpass ─► POOL /catalog ─(parallel)─► /image/<ref> … ─► local store ─► run
         run passes ─► hashpass ─► POOL /submit(evidence,digest) ─► verify+progress+global key
both:    launch ─► GitHub /releases/latest ─► (newer?) self-update ─► re-exec
```

## 5. Pool server (`hashengine serve`)

Extend `registry/server.py` (`RegistryServer`, `ThreadingHTTPServer`). Remove the dev-only
loopback assertion; add a `--host/--port` and a security banner. All existing routes stay
(`/login`, `/closure/…`, `/image/…` GET/HEAD/PUT). New routes:

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/register` | POST | none (gated by toggle) | signup: user, password, full_name, group, comment → creates a **student** user |
| `/me` | GET | bearer | returns `{user, role, full_name, group}` — used by the engine-install gate |
| `/catalog` | GET | bearer | ordered `[{number, name, version, title, digest}]` |
| `/task/<name…>/<version>` | GET/PUT | GET bearer / PUT author | task **bundle** transfer (checks + hp + task-meta); PUT also updates the catalog when `?number=N` |
| `/submit` | POST | bearer | `{evidence, task_digest}` → verify + record progress + return `{status, global_key?}` |
| `/progress` | GET | bearer (author sees all; student sees self) | JSON progress for the dashboard |
| `/install.sh` | GET | none | student bootstrap installer, templated with **this pool's** URL |
| `/install-engine.sh` | GET | session cookie (author/admin) | author-gated engine bootstrap installer |
| `/web/*` | GET/POST | session cookie (author/admin) | web dashboard (§6) |
| `/admin/registration` | POST | admin | open/close signup |
| `/admin/role` | POST | admin | grant/revoke author role |

### 5.1 Users & roles

`UserStore` record grows from a bare PBKDF2 string to:
```
{ "pw": "<pbkdf2 record>", "role": "student|author|admin",
  "full_name": "...", "group": "...", "comment": "...", "created_at": <ts> }
```
- `/register` always creates `role="student"`; `full_name` and `group` are **required**
  (server rejects blank), `comment` optional.
- Author role is granted by an admin (web or `/admin/role`). The **first** user created (or a
  seeded admin from `config.json`) is `admin`.
- Registration toggle in `config.json` (`registration_open: bool`); `/register` returns 403 when
  closed. Default open.
- Tokens stay as today (HMAC bearer, 7-day TTL, `token.py`); the server looks up the **current**
  role from `users.json` per request (revocable without waiting for token expiry).

### 5.2 Catalog & numbering

- `catalog.json`: map `number -> {name, version, title, digest}` (number is a positive int).
- `push --task N` (author) uploads the image closure (existing) **and** the task bundle (new
  `/task` PUT with `?number=N`), then the server writes/overwrites catalog position N.
- Free order (per decision): the number is display/recommended order; nothing is locked. A student
  may run any catalog task. Progress is the **set** of passed tasks.

### 5.3 Progress

- `progress/<user>.json`: map `task-number (or ref) -> {status: "passed"|"failed", ts,
  global_key?, digest}`.
- Written by `/submit`. `status="passed"` iff the server re-verified evidence AND the digest
  matched; otherwise `"failed"` (attempt recorded). Teachers read it via `/progress` / web.

### 5.4 Task transfer (new)

Today `pack_image` moves only `layer/`; the task lives in the sibling `task/` dir and is never
transported. Add a task blob (tar of `task/{bundle,hp,task-meta.json}`) with its own
pack/unpack, moved by a `/task` PUT/GET. The server keeps each task's **reference checks**
(`bundle/checks.json`) so `/submit` can re-verify (`server/verify.py` already does
`matches(canonical, candidate, …)`), and its **digest** (§7).

## 6. Web UI (`hashengine serve`, server-rendered)

**DECISION (default):** pure `http.server` + hand-written HTML/CSS, zero runtime deps.
*(Alternative: Flask — more familiar, adds a dependency; rejected by default to honor "не прямо
какую-то там".)*

- **Login** (`/web/login`): author/admin credentials → signed session cookie (reuse `token.py`
  HMAC; cookie is a bearer token). Students have no web access by default.
- **Dashboard** (`/web`): table of students (ФИО, group, comment) × task numbers, each cell
  passed/not-passed (+ timestamp). Filter by group. Read from `progress/` + `users.json` +
  `catalog.json`.
- **Users** (`/web/users`): list users; create a user (with full_name/group/comment); grant/revoke
  author role (admin only); open/close registration (admin only).
- **Front page**: shows the one-line install command (`curl -fsSL https://<pool>/install.sh | bash`)
  and a link to register. Authors, once logged in, additionally get the engine install command
  (`/install-engine.sh`). This is the "через сайтик" entry point.
- Theme-agnostic, minimal CSS; tables scroll horizontally; no external assets.

## 7. Task integrity (basic)

- **Digest:** `task_digest = sha256(canonical-serialization of the task's grading content)` —
  the sorted concatenation of `bundle/checks.json`, every file under `hp/` (path + bytes, sorted),
  and `task-meta.json`. Computed by `hashengine` at push, stored in the catalog, transported with
  the task, and recomputed identically by `hashpass` before `/submit`.
- **Enforcement:** `/submit` compares the client-reported digest to the stored one; on mismatch it
  refuses the global key and records a `failed` attempt with reason `digest-mismatch`.
- **Belt-and-suspenders:** the server also re-verifies derived-check evidence with its own
  reference checks and signs the global key with its secret (`issue_global_key`), and binds the
  key to the **authenticated principal** (fixing today's `student_id != principal` gap that
  `sync.py` only models in-process).
- **Honest boundary (documented in the spec and code):** derived checks (observe / observe output)
  are fully server-re-verified; handler stages (`check exec`) run client-side and are covered only
  by the digest + HMAC signature. A student with local root can still cheat those; the goal is to
  stop casual tampering and copy-paste key sharing, not a determined attacker.

## 8. Install (served by the pool site, not the repo)

There is **no** installer in the repo and **no** raw-GitHub one-liner. The pool serves its own
bootstrap script, so the pool URL is implicit — it is whatever host the student downloaded from.

- **Student** — the pool web serves a script at `GET /install.sh`, templated with that pool's own
  base URL. One-liner (printed on the site front page):
  ```
  curl -fsSL https://<pool-host>/install.sh | bash
  ```
  The script: checks Python 3.13 + pip; `pip install --user` the **`hashpass`** distribution from
  the latest **GitHub release** tag; writes the serving pool's URL into `~/.hashpass/pool.json`
  (so the student never types a URL); prints next steps. `HASHPASS_POOL` remains only as an
  optional override.
- **Engine/author** — two paths:
  - `make install` from a clone — the canonical dev/author path (installs `hashengine` editable).
  - The pool web serves an **author-gated** script at `GET /install-engine.sh`, reachable only
    after an author/admin logs in on the site (the "запросит авторизацию на сайте" gate). It
    installs the `hashengine` distribution and pre-seeds the pool URL. Non-authors are instead
    shown how to request author access.
- The package always installs from the **GitHub release** (one source of truth, consistent with
  auto-update §9); the site serves only the thin bootstrap script, never the packages.
- `make install-student` stays as a local-testing convenience (installs the `hashpass` dist).

## 9. Auto-update (both tools)

- On launch, at most once per `UPDATE_CHECK_INTERVAL` (default 24h, stamped in
  `update.json`/`~/.hashengine`), GET `https://api.github.com/repos/Bunnyton/hashpass/releases/latest`,
  read `tag_name`, compare to the installed `__version__` (a real version in `pyproject`, bumped and
  git-tagged per release).
- **DECISION (default):** if a newer version exists, **auto-update** in place (re-run the same
  `pip install --user` from the new tag) and **re-exec** the original command, printing a one-line
  notice. Escape hatches: `--no-update` flag and `HASHPASS_NO_UPDATE=1`.
  *(Alternative: notify-only, let the user run an update command. Say if you prefer this — it is
  safer but less "auto".)*
- All network/tooling failures are swallowed with a debug note; the tool continues on the current
  version. Never blocks the student behind a GitHub outage.
- Version comparison is a pure, unit-tested function (PEP 440-ish: numeric dotted compare).

## 10. Student `hashpass`

- **First-run gate:** no valid cached pool token → interactive `register` (default, if signup
  open) or `login`. Pool URL comes from `~/.hashpass/pool.json` (written by the site installer),
  with `HASHPASS_POOL` as an optional override. Nothing else runs until identity is established.
- **`hashpass` (no args):** update check → parallel pull of catalog images that are new or whose
  version changed (thread pool over `RemoteRegistry.pull`, bounded workers) → print the numbered
  task list with pass status (from `/progress`) → interactive picker.
- **`hashpass run <number|ref>`:** resolve number→ref via catalog, run as today; on a live pass,
  build evidence and POST `/submit`; reflect the returned status.
- **`student_id`** = the authenticated pool login (replaces `_DEFAULT_STUDENT="local"`).
- Commands: `register`, `login`, `pull` (manual refresh), `run`, `list`/no-arg, `whoami`.

## 11. Author `hashengine`

- `build` (as today), `login`, `images`, `serve` (+ `--web`, `--host`, `--port`).
- `push <ref> [--task N] [--title "…"]`: push image closure (existing) + task bundle; with
  `--task N`, register/overwrite catalog position N and store the digest. Without `--task`, push
  the image only (no catalog slot).
- `serve` seeds an admin on first run (from `config.json` or a printed generated password).

## 12. Data-model summary (new/changed)

- `UserRecord` (§5.1): +role, +full_name, +group, +comment, +created_at.
- `CatalogEntry`: {number, name, version, title, digest}.
- `ProgressEntry`: {status, ts, global_key?, digest}.
- `pack_task`/`unpack_task` blob (mirror of `pack_image`).
- `task_digest(task_dir) -> str` in hashcore (used by both engine push and student submit).
- `__version__` in hashcore + version-compare helper.

## 13. Testing strategy

- **tier1 (pure):** version compare; `task_digest` determinism + mismatch; role gating logic;
  registration-toggle logic; catalog add/overwrite/order; progress record transitions; token/role
  lookup; evidence re-verify + principal binding; digest enforcement in `/submit`.
- **tier2 (loopback HTTP):** full `/register → /login → push(image+task,--task N) → /catalog →
  parallel pull → /submit → /progress` round-trip against a `make_server` on 127.0.0.1; web login
  + dashboard render (assert HTML contains the expected rows); registration-closed 403.
- **tier3 (nspawn):** one end-to-end `hashpass run` of a pulled task that passes and submits.
- **installer:** `shellcheck` + a dry-run mode (`HASHPASS_INSTALL_DRYRUN=1`) that prints the pip
  command instead of running it; the `--engine` gate tested against a loopback pool.
- **auto-update:** GitHub response mocked; assert update triggers only on a strictly newer tag and
  that failures are swallowed. No real network in tests.

## 14. Phased plan (detailed in the implementation plan)

1. **Core split** — introduce `hashcore`; rename `hashpass.* → hashcore.*`; two thin CLIs
   (`hashpass`, `hashengine`) wired to the existing commands; packaging for two distributions;
   `make install` / `make install-student`. Behavior unchanged. (Largest, mechanical.)
2. **Users & roles & registration** — `UserRecord` fields, `/register` (+required ФИО/group),
   roles, `/me`, registration toggle, admin seeding.
3. **Task transfer & digest** — `pack_task`/`unpack_task`, `/task` GET/PUT, `task_digest`, store
   reference checks server-side.
4. **Catalog & numbering** — `catalog.json`, `push --task N`, `/catalog`.
5. **Student client** — first-run gate, parallel pull, list-by-number, `run`, real `student_id`.
6. **Submit & progress** — `/submit` (verify + digest + principal binding), `progress/`, wire the
   run→submit path.
7. **Web UI** — login, dashboard, users, registration toggle, front page.
8. **Installer (pool-served)** — the pool serves `/install.sh` (student, self-templated URL) and an
   author-gated `/install-engine.sh`; scripts pip-install the right dist from the GitHub release and
   seed `pool.json`; dry-run + shellcheck. No repo-level installer.
9. **Auto-update** — `__version__`, version compare, launch-time check + re-exec, escape hatches.

Phases 1–6 are the functional spine; 7–9 layer on top and can ship incrementally.

## 15. Open decisions (defaults chosen — override on review)

1. **Packaging:** two distributions, `hashengine` depends on `hashpass` (core inside `hashpass`).
   Alt: three dists with standalone `hashcore`.
2. **Web stack:** stdlib `http.server` + hand-written HTML. Alt: Flask.
3. **Auto-update:** automatic in-place update + re-exec. Alt: notify-only.
4. **Registration:** self-signup, ФИО+group **required**, comment free; admin can open/close signup
   and grant author role (per your answers).
5. **Order:** free order; number = display/recommended path; progress = set of passed (per your
   answer).
6. **Install gate:** identity enforced at **first run** of `hashpass`; `hashengine` install gated by
   web author-role authorization (per your answers).
7. **Install & pool URL:** no repo installer — the pool **site** serves the installer, so the pool
   URL is implicit and written to `pool.json` (`HASHPASS_POOL` optional override). `make install`
   stays for authors; the engine is also installable via an author-gated site installer.
