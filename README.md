# Meeting dashboard

The state-of-project board: open questions, the meeting agenda, and the decisions
those agenda items became. It reads `HANDOFF.md` §7 and writes its own database;
it never edits `HANDOFF.md`.

## Running it

```bash
cd meeting-dashboard
./dashboard serve
```

That serves the current database at <http://127.0.0.1:8765> and prints the link.
Under VS Code Remote-SSH the port is forwarded automatically and the link is
clickable.

If the browser cannot reach it — VS Code's forwarding does sometimes wedge, and
a forwarded port with a dead tunnel behind it looks exactly like a working one —
forward it yourself from your own machine instead, then open the same link:

```bash
ssh -L 8765:localhost:8765 you@the-host
```

Every change you make in the browser is saved as you make it, and there is no save
button. The one thing still held in the tab is the note you type when closing a
question: it has nowhere to be stored until you press Close, so press Close before
you shut the laptop. Everything else — agenda resolutions, follow-ups, who resolved
it — is already on disk.

If port 8765 is already taken, pick another with `--port` (and `--host` if you
need it reachable from somewhere other than localhost), e.g.
`./dashboard serve --port 8790`.

## Refreshing it from HANDOFF.md

```bash
./dashboard update            # reconcile against §7, then serve
./dashboard update --clickup  # also merge the cached ClickUp snapshot
```

`sync` does the reconciliation without serving. `export` rewrites `dashboard.json`
from the database.

## Recording a meeting

```bash
./dashboard meeting 2026-09-21              # after (or before) the meeting
./dashboard meeting 2026-09-21 --label "post-bookkeeping pass"
```

This is what the staleness counter counts: the badge on an open question reads
how many recorded meetings it has survived since it was raised. Dates are
deduplicated and kept in order, so re-running it is harmless. Until at least one
meeting is recorded the badge is hidden rather than showing zero — a counter
frozen at zero reads as "nothing is stale", which is worse than no counter.

## What lives where

This project is standalone: it is not inside the paper repo any more, and the
data directory is relocatable. By default, everything sits under the project root:

| File | |
|---|---|
| `dashboard-data/dashboard.json` | The board. **Committed** — this is what a clone carries. |
| `dashboard-data/dashboard.db` | Local SQLite cache. **Gitignored**, rebuilt from the JSON automatically. |
| `dashboard-data/pending-changes.md` | What the dashboard owes `HANDOFF.md` §7. **Committed.** |
| `dashboard-data/clickup-cache.json` | Last ClickUp pull. **Committed**, refreshed only on request. |

`dashboard-config.json`, at the project root, records where `dashboard-data` and
`HANDOFF.md` actually live on *this* machine. It is gitignored — it is not shared,
and every clone/checkout gets its own. A fresh clone has none; the first command
you run writes it out with the defaults (`dashboard-data` under the project root,
and the group's usual `HANDOFF.md` path).

Three commands manage this instead of hand-editing the config file:

```bash
./dashboard where                  # print the resolved data dir and handoff path
./dashboard move-data <directory>  # permanently relocate dashboard-data
./dashboard set-handoff <path>     # record a different HANDOFF.md
```

`move-data` takes **the directory dashboard-data should live in — the parent, not
the new folder's own name.** `./dashboard move-data ~/research/68f6bef0/` moves
the folder to `~/research/68f6bef0/dashboard-data`, keeping the name
`dashboard-data`; it does not rename it to `68f6bef0`. It refuses to overwrite a
non-empty `dashboard-data` at the destination, verifies the files arrived (copying
across filesystems when a plain rename cannot cross the boundary) before deleting
the source, and only updates the config once the move has actually succeeded — a
failed move never leaves the config pointing somewhere the data isn't. If the
destination is inside a git repository, it also makes sure `dashboard-data/dashboard.db`
is gitignored there, so a stray SQLite binary never gets committed.

The most common reason to move it: relocating `dashboard-data` into the Overleaf
paper repo (`68f6bef0eaaf5c0928a922c6/`) so the whole group shares board state
through the same `git pull`/`git push` that already carries the manuscript,
instead of everyone running their own disconnected copy.

`--handoff` and `--data` on any command override the config for that one run
without changing it; `set-handoff` is for making a change stick.

If `sync` or `update` cannot find `HANDOFF.md` at the configured path, it fails
with the path it looked at and tells you to run `./dashboard set-handoff <path>`
— that's the fix, not a bug report.

## The rules it follows

- **Item numbers come from `HANDOFF.md` §7 and nowhere else.** Closed items keep theirs.
- **§7 dictates open and closed.** If you close a question here and §7 still lists it
  open, the next sync reopens it — and records the closure in `pending-changes.md`, so
  it is owed to §7 rather than lost.
- **The UI owns what the UI creates**: resolutions, decisions, follow-up people, the
  curated agenda, and any difficulty you set by hand. Sync never overwrites them.
- **A decision cannot be recorded without grounds.**
- **Flags are listed, never resolved automatically.** §7.1's disagreements appear in
  full at the top of Open questions; resolved ones are dimmed, not hidden.
- **Agenda work is written as you type.** A resolution, a follow-up list and a
  "resolved by" are saved as you type them and again when you leave the field, so
  another click somewhere else on the board cannot wipe them.
- **A question's closing note is the exception.** It has nowhere to be stored until
  you press Close, so it is held in the tab: it survives anything else you do on the
  board, but not a reload or a closed laptop. Press Close to make it durable.
- **Nothing is destroyed by a click.** A dismissed sync proposal is collapsed into a
  Dismissed group with a Restore button — sync will never propose it again, so hiding
  it would be deleting it.

## Getting a colleague set up

`git pull` (or `git clone`), then `./dashboard serve`. The database rebuilds itself
from the committed JSON, and `dashboard-config.json` is written with the defaults
on first run. Nothing to install: it is Python standard library only.

If your `dashboard-data` (or `HANDOFF.md`) is not where the defaults expect —
for instance because someone already ran `move-data` and you are on a different
machine — run `./dashboard where` to see what this checkout currently thinks,
and `./dashboard move-data` / `set-handoff` to fix it for good.
