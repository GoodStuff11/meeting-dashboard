# Meeting dashboard

A board of the project's open questions, the agenda for the next meeting, and
the decisions those agenda items became.

It reads section 7 of `HANDOFF.md` — the group's authoritative ledger of open
and closed items — and reconciles its own database against it. It never edits
`HANDOFF.md`. Anything you do here that §7 has not caught up with is written
out as a list of edits owed to §7, for a person to fold in by hand.

## Requirements

Python 3.12 or newer. Nothing else. No install step, no dependencies, no npm.
Everything is Python standard library, and the whole board is served from a
local HTTP server on your own machine.

## Getting started

A fresh clone of this repository has no data in it. `dashboard-data/` is
gitignored here, so there is no database, no `dashboard.json`, nothing. The
board has to be either generated or adopted. Which of the two depends on
whether anyone in the group has set this up before you.

### If you are the first person setting this up

Tell it where `HANDOFF.md` is, then sync.

```bash
cd meeting-dashboard
./dashboard set-handoff /path/to/HANDOFF.md
./dashboard sync
```

`sync` prints a one-line summary, something like:

```
added 30 · updated 0 · reverted 0 · reopened 0 · stale 0 · flags 7 · agenda proposed 7
```

That is the board generating itself from §7: every item becomes a question,
every unresolved disagreement in §7.1 becomes a flag and a proposed agenda
item. You now have `dashboard-data/dashboard.json`, `dashboard-data/dashboard.db`
and `dashboard-data/pending-changes.md`. Start the board:

```bash
./dashboard serve
```

It prints `Meeting dashboard: http://127.0.0.1:8765`. Open that.

If the group is going to share this board, the usual next step is to move the
data into the repository everyone already pulls — the Overleaf paper repo:

```bash
./dashboard move-data /path/to/the-paper-repo
```

That moves the folder to `the-paper-repo/dashboard-data`, updates your config,
and adds `dashboard-data/dashboard.db` to that repo's `.gitignore`. Then commit
and push the data there as you would any other file in that repo. Everyone
else is now in the second situation, below.

### If the group already keeps the data in the Overleaf repo

Clone both repositories, then point this one at the data that already exists.

```bash
git clone <this-repo> meeting-dashboard
git clone <the-paper-repo> paper
cd meeting-dashboard
./dashboard set-data /path/to/paper/dashboard-data
./dashboard set-handoff /path/to/paper/HANDOFF.md
./dashboard serve
```

`set-data` records the path and moves nothing. The database rebuilds itself
from the committed `dashboard.json` the first time you run anything, so the
board comes up populated.

**Do not run `move-data` here.** `move-data` relocates your data directory to
somewhere new, and it refuses any destination that already has a non-empty
`dashboard-data` — which is exactly what you have. You are not moving data;
you are adopting data that is already in the right place. `set-data` is the
command for that.

Note the asymmetry, because it catches people:

- `move-data` takes **the parent directory** the folder should live in.
  `./dashboard move-data ~/paper` puts it at `~/paper/dashboard-data`.
- `set-data` takes **the folder itself**.
  `./dashboard set-data ~/paper/dashboard-data`.

Check what you ended up with at any time:

```bash
./dashboard where
```

```
data dir: /home/you/paper/dashboard-data
handoff: /home/you/paper/HANDOFF.md
```

## The commands

There are nine. `./dashboard --help` lists them.

| Command | What it does |
|---|---|
| `serve` | Starts the local web server and prints the link. Ctrl-C stops it. |
| `sync` | Reconciles the database against `HANDOFF.md` §7 and rewrites `dashboard.json` and `pending-changes.md`. Does not serve. |
| `update` | `sync`, then `serve`. The usual way to start a session. |
| `export` | Rewrites `dashboard.json` from the database. No syncing, no network, no `HANDOFF.md`. |
| `meeting <date>` | Records that a meeting happened on `<date>` (`YYYY-MM-DD`). |
| `where` | Prints the data directory and `HANDOFF.md` path this checkout resolves to. |
| `set-handoff <path>` | Records a different `HANDOFF.md` in the config. |
| `set-data <directory>` | Records an existing `dashboard-data` directory in the config. Moves nothing. |
| `move-data <directory>` | Relocates the `dashboard-data` folder into `<directory>` and updates the config. |

In more detail:

**`serve`** — `./dashboard serve [--host H] [--port N]`. Serves the board at
`http://127.0.0.1:8765` by default and prints the link. Under VS Code
Remote-SSH the port is forwarded automatically and the link is clickable. Every
change you make in the browser is written to disk immediately; there is no save
button. Reach for it when you just want to look at or edit the board and the
database is already current.

**`sync`** — `./dashboard sync [--handoff P] [--data D] [--clickup]`. Reads §7,
adds items it has not seen, updates the fields the tracker owns, records
disagreements from §7.1 as flags, proposes agenda items, and writes
`pending-changes.md`. Prints one summary line. Reach for it before a meeting,
or from a script, when you want the reconciliation without a server. Running it
twice in a row leaves `dashboard.json` byte-identical — a no-op sync produces no
diff.

**`update`** — `./dashboard update [--handoff P] [--data D] [--clickup] [--host H] [--port N]`.
Exactly `sync` followed by `serve`, in one command. This is what you run at the
start of a working session. If the sync fails it does not serve. It blocks
until you stop it, so it is the wrong verb for a script or an agent — use
`sync`.

**`export`** — `./dashboard export [--data D]`. Rewrites `dashboard.json` from
the SQLite database and prints the path it wrote. Reach for it if you deleted
or corrupted the JSON, or want the JSON refreshed without touching
`HANDOFF.md`. It cannot invent data: whatever is in the database is what you
get.

**`meeting`** — `./dashboard meeting 2026-09-21 [--label "weekly"] [--data D]`.
Records a meeting date. Prints `recorded 2026-09-21 · 1 meeting(s) on record`.
This is what the staleness counter counts: the badge on an open question reads
how many recorded meetings it has survived since it was raised. Dates are
deduplicated and sorted, so re-running it is harmless, and a recorded meeting
survives the next sync. Until at least one meeting is recorded the badge is
hidden rather than showing zero. A date that is not `YYYY-MM-DD` is rejected
with an error.

**`where`** — `./dashboard where [--handoff P] [--data D]`. Prints the two
paths this checkout resolves to. Run it first whenever something looks wrong;
most confusion is a checkout pointing at a data directory you did not expect.
It writes `dashboard-config.json` with the defaults if there is not one yet.

**`set-handoff`** — `./dashboard set-handoff /path/to/HANDOFF.md`. Validates
that the file exists, then records its absolute path in the config. Errors
naming the path if there is no file there, and in that case writes nothing.

**`set-data`** — `./dashboard set-data /path/to/dashboard-data`. Takes the
`dashboard-data` folder **itself**, not its parent — deliberately the opposite
of `move-data`. Validates that the directory exists, then records it in the
config. It moves, copies and creates nothing. This is the command for the
second and third person on a shared data directory. If the config already
points there it says so and does nothing. If the directory has no
`dashboard.json` in it, it still records the path but warns you — that is the
sign you pointed at an empty or wrong folder, and the board would otherwise
come up silently empty.

**`move-data`** — `./dashboard move-data /path/to/parent`. Takes **the parent
directory** the folder should live in, not the new folder's own name:
`./dashboard move-data ~/paper` moves it to `~/paper/dashboard-data`, keeping
the name. It refuses to overwrite a non-empty `dashboard-data` at the
destination. It verifies the files arrived byte-for-byte (copying across
filesystems when a plain rename cannot cross the boundary) before deleting the
source, and only updates the config once the move has actually succeeded — a
failed move never leaves the config pointing somewhere the data is not. If the
destination is inside a git repository, it also makes sure
`dashboard-data/dashboard.db` is gitignored there, so a stray SQLite binary
never gets committed.

## The flags

| Flag | Applies to | Meaning |
|---|---|---|
| `--handoff PATH` | `sync`, `update` | Use this `HANDOFF.md` for this run only. |
| `--data DIR` | `sync`, `update`, `serve`, `export`, `meeting`, `where` | Use this data directory for this run only. |
| `--clickup` | `sync`, `update` | Merge the cached ClickUp snapshot into the items. |
| `--label TEXT` | `meeting` | An optional name for the meeting. |
| `--host HOST` | `serve`, `update` | Address to bind. Default `127.0.0.1`. |
| `--port N` | `serve`, `update` | Port to bind. Default `8765`. |

`--handoff` and `--data` override the config **for that one run and do not
change it**. Nothing is written to `dashboard-config.json` by using them. To
make a change stick, use `set-handoff` or `set-data`.

`--clickup` reads `dashboard-data/clickup-cache.json` and nothing else. This
process never touches the network. If there is no cache file it is a silent
no-op; the snapshot has to be refreshed by an agent that has a ClickUp
connector (see below).

## The workflow around a meeting

**Before.** Sync so the board matches the ledger, then look at what it
proposes.

```bash
./dashboard update
```

Sync proposes an agenda item for every unresolved disagreement in §7.1, and for
every open item that is high priority or past its due date. Go through the
Agenda tab and curate it: keep what is worth the group's time, dismiss the
rest. A dismissed proposal collapses into a Dismissed group with a Restore
button rather than disappearing — sync will never propose it again, so hiding
it would be deleting it.

Record the meeting date, so the staleness counters advance:

```bash
./dashboard meeting 2026-09-21 --label "weekly"
```

**During.** Work the board live. Close questions the group has settled, writing
the closing note as you close them. Resolve agenda items into decisions: each
decision needs grounds, and the board will not record one without them. Add
follow-ups and who owns them.

**After.** Whatever you did in the UI that §7 does not yet know about is now
listed in `dashboard-data/pending-changes.md`. Someone — a person, or an agent
working under one — folds those into `HANDOFF.md` §7 by hand, and commits both
the data directory and `HANDOFF.md`.

## What an agent does

These are the jobs worth handing to an agent, and what to ask for.

**Reconcile the board.** *"Sync the meeting dashboard against HANDOFF.md and
tell me what changed."* The agent runs `./dashboard sync` — not `update`, which
starts a server and blocks — and reports the summary line: what was added,
updated, reverted, reopened, went stale, and what agenda items were proposed.

**Fold pending changes into §7.** *"Read dashboard-data/pending-changes.md and
draft the edits to HANDOFF.md §7."* This is the important one. The dashboard
writes `pending-changes.md` and never writes §7 itself. Item numbers are born
in §7, and an agent rewriting that ledger unreviewed is how it gets corrupted.
So the agent reads the file, works out what each entry means for §7 — a
question to mark CLOSED, one to reopen, a decision to record, an item that has
vanished from §7 and should either be restored or retired — and proposes the
edits for you to review before they land. The dashboard never applies them, and
neither should an agent without your say-so.

**Refresh the ClickUp snapshot.** *"Pull the current ClickUp status for the
tasks in §7 and update the cache."* Nothing in this process touches the
network; `--clickup` only ever reads a cached snapshot from
`dashboard-data/clickup-cache.json`. An agent with a ClickUp connector fetches
the statuses and writes that file:

```json
{
  "pulled_on": "2026-09-21",
  "tasks": {
    "86akhc9zz": {"status": "in progress", "priority": "high", "due": "2026-09-28"}
  }
}
```

The keys are the ClickUp task ids that appear in §7. After that,
`./dashboard sync --clickup` merges the statuses in. The board shows how old
the snapshot is, so a stale pull is visible rather than misleading.

**Commit the data.** *"Commit the dashboard data."* The data directory lives
wherever `./dashboard where` says — usually inside the Overleaf paper repo, not
this one. The agent commits `dashboard.json`, `pending-changes.md` and
`clickup-cache.json` there, and leaves `dashboard.db` alone: it is gitignored
and rebuilt automatically.

## Rules that will otherwise confuse you

- **§7 dictates open and closed.** Close a question in the UI and the next sync
  reopens it unless §7 agrees. The closure is not lost: it is recorded in
  `pending-changes.md` as an edit owed to §7. Close it in §7 to make it stick.
  The mirror case works the same way — reopen something in the UI that §7 has
  closed, and sync closes it again and records the reopening.
- **Item numbers come from §7 and nowhere else.** Closed items keep theirs.
- **The UI owns what the UI creates**: resolutions, decisions, follow-ups, the
  curated agenda, and any difficulty you set by hand. Sync never overwrites
  them. Difficulty is guessed from the item's wording only until you set it
  yourself; after that it is yours.
- **A decision cannot be recorded without grounds.**
- **Flags are listed, never resolved automatically.** §7.1's disagreements
  appear in full at the top of Open questions; resolved ones are dimmed, not
  hidden. An item that disappears from §7 is likewise flagged and kept, not
  deleted.
- **Agenda work is saved as you type.** A resolution, a follow-up list and a
  "resolved by" are written as you type them and again when you leave the
  field, so another click somewhere else on the board cannot wipe them.
- **A question's closing note is the exception.** It has nowhere to be stored
  until you press Close, so it is held in the browser tab: it survives anything
  else you do on the board, but not a reload or a closed laptop. Press Close
  before you shut the lid.
- **Entries in `pending-changes.md` keep reappearing** every time it is
  regenerated, until they are in §7. Nothing here can tell whether you actually
  filed them, and repetition you can skim past is a much cheaper failure than
  silently dropping a decision nobody recorded.

## Where things live

```
meeting-dashboard/
  dashboard                  the command, ./dashboard <verb>
  dashboard-config.json      this machine's paths. Gitignored.
  dashboard-data/            the data directory, by default. Gitignored here.
  project_tracker/           the code
    cli.py                   the commands
    sync.py                  reconciliation against §7
    store.py                 the database and every rule about it
    serve.py                 the HTTP surface
    report.py                pending-changes.md
    export.py                database <-> dashboard.json
    sources/handoff.py       the §7 parser
    sources/clickup.py       the cached ClickUp snapshot
    static/                  the browser UI
  tests/                     python3 -m pytest tests/ -q
```

`dashboard-config.json` holds two things:

```json
{
  "data_dir": "dashboard-data",
  "handoff": "/home/you/paper/HANDOFF.md"
}
```

`data_dir` is relative to the project root, or absolute. The file is gitignored
on purpose: those paths are specific to your machine and your checkout, not
something to share. Every clone gets its own. A fresh clone has none; the first
command you run writes it out with the defaults, so the choice this machine is
making is visible in a file rather than re-guessed silently on every run.
`set-data`, `set-handoff` and `move-data` are how you change it — there is no
need to hand-edit it.

The data directory holds four files, wherever it ends up:

| File | |
|---|---|
| `dashboard.json` | The board. **Commit it** — this is what a clone carries. |
| `pending-changes.md` | What is owed to `HANDOFF.md` §7. **Commit it.** |
| `clickup-cache.json` | The last ClickUp pull. **Commit it.** Absent until someone makes one. |
| `dashboard.db` | Local SQLite cache. **Do not commit it** — it is rebuilt from the JSON automatically whenever the JSON has changed. |

In *this* repository the whole of `dashboard-data/` is gitignored, so none of
it is committed here. Once the folder has been moved into the paper repo, that
is where those files get committed — and `move-data` adds
`dashboard-data/dashboard.db` to that repo's `.gitignore` for you.

## Troubleshooting

**The port is already in use.** `./dashboard serve` ends in
`OSError: [Errno 98] Address already in use`. Either something else has 8765,
or you left a server running in another terminal. Pick another port:

```bash
./dashboard serve --port 8790
```

Use `--host` as well if you need it reachable from somewhere other than
localhost.

**`HANDOFF.md` not found.** `sync` and `update` fail with the path they looked
at and tell you to run `./dashboard set-handoff <path>`. That is the fix, not a
bug report. Run `./dashboard where` to see what the checkout currently thinks.
If the file is there but §7 cannot be parsed, the error says so and names the
file.

**The browser cannot reach the server.** VS Code's port forwarding does
sometimes wedge, and a forwarded port with a dead tunnel behind it looks
exactly like a working one. Forward it yourself from your own machine instead,
then open the same link:

```bash
ssh -L 8765:localhost:8765 you@the-host
```

**The board comes up empty.** Run `./dashboard where` and look at the data
directory. Either it is not the one with the group's data in it — fix that with
`set-data` — or it genuinely has no data yet, in which case `./dashboard sync`
builds it from §7.
