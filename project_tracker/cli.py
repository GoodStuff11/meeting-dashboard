"""Command line entry point.

Two verbs matter day to day: `serve` for a person and `update` for an agent.
`where`, `move-data` and `set-handoff` are the plumbing for relocating the
data directory or pointing at a different HANDOFF.md; everything else is
plumbing too.
"""

import argparse
import errno
import hashlib
import shutil
import sys
from pathlib import Path

from . import config
from . import serve as serve_module
from . import store
from .export import ensure_db, export_json
from .report import write_pending
from .sources.handoff import HandoffParseError
from .sync import sync as run_sync


def _paths(data_dir):
    return {
        "db": data_dir / "dashboard.db",
        "json": data_dir / "dashboard.json",
        "pending": data_dir / "pending-changes.md",
        "clickup": data_dir / "clickup-cache.json",
    }


def _handoff_path(args, cfg):
    return Path(args.handoff) if args.handoff else config.resolve_handoff(cfg)


def _do_sync(conn, args, paths, cfg):
    handoff = _handoff_path(args, cfg)
    if not handoff.exists():
        print(f"error: no HANDOFF.md at {handoff} — "
              f"run `./dashboard set-handoff <path>` to point at the right file",
              file=sys.stderr)
        return None
    try:
        result = run_sync(
            conn, handoff_path=handoff,
            clickup_cache_path=paths["clickup"] if args.clickup else None,
            json_path=paths["json"])
    except HandoffParseError as exc:
        print(f"error: could not parse section 7 of {handoff}: {exc}", file=sys.stderr)
        return None
    write_pending(conn, result, paths["pending"])
    print(f"added {len(result.added)} · updated {len(result.updated)} · "
          f"reverted {len(result.reverted)} · reopened {len(result.reopened)} · "
          f"stale {len(result.stale)} · flags {len(result.flags)} · "
          f"agenda proposed {len(result.agenda_proposed)}")
    if result.reverted:
        print(f"  {len(result.reverted)} UI closure(s) owed to HANDOFF §7 — "
              f"see {paths['pending']}")
    if result.reopened:
        print(f"  {len(result.reopened)} UI reopening(s) owed to HANDOFF §7 — "
              f"see {paths['pending']}")
    return result


def _checksum_tree(root):
    """Map each file under `root` (relative path -> sha256) for verifying a move."""
    sums = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            sums[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sums


def _find_git_root(path):
    path = Path(path).resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _ensure_gitignored(repo_root, relative_db_path):
    gitignore = repo_root / ".gitignore"
    pattern = relative_db_path.as_posix()
    existing = gitignore.read_text() if gitignore.exists() else ""
    lines = existing.splitlines()
    if pattern in lines:
        return False
    prefix = "" if (not existing or existing.endswith("\n")) else "\n"
    with gitignore.open("a") as fh:
        fh.write(prefix + pattern + "\n")
    return True


def _cmd_where(args):
    cfg = config.load()
    data_dir = Path(args.data) if args.data else config.resolve_data_dir(cfg)
    handoff = _handoff_path(args, cfg)
    print(f"data dir: {data_dir.resolve() if data_dir.exists() else data_dir}")
    print(f"handoff: {handoff}")
    return 0


def _cmd_move_data(args):
    if not args.target:
        print("error: ./dashboard move-data needs the directory the "
              "dashboard-data folder should live in, e.g. "
              "./dashboard move-data /path/to/parent", file=sys.stderr)
        return 1
    cfg = config.load()
    source = config.resolve_data_dir(cfg)
    dest_parent = Path(args.target).resolve()
    dest = dest_parent / "dashboard-data"

    if not source.exists():
        print(f"error: no dashboard-data directory at {source} to move", file=sys.stderr)
        return 1

    if dest.resolve() == source.resolve():
        print(f"dashboard-data is already at {dest} — nothing to do")
        return 0

    if dest.exists():
        if any(dest.iterdir()):
            print(f"error: {dest} already exists and is not empty — refusing to "
                  f"overwrite it", file=sys.stderr)
            return 1
        dest.rmdir()

    dest_parent.mkdir(parents=True, exist_ok=True)

    before = _checksum_tree(source)
    try:
        source.rename(dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # Cross-filesystem: copy, verify, then remove the source.
        shutil.copytree(source, dest)
        after = _checksum_tree(dest)
        if after != before:
            print(f"error: copy to {dest} did not verify byte-for-byte against "
                  f"{source} — leaving the source in place", file=sys.stderr)
            shutil.rmtree(dest, ignore_errors=True)
            return 1
        shutil.rmtree(source)
    else:
        after = _checksum_tree(dest)
        if after != before:
            print(f"error: move to {dest} did not verify — the config has not "
                  f"been updated; the data is at {dest} but please check it by hand",
                  file=sys.stderr)
            return 1

    repo_root = _find_git_root(dest)
    if repo_root is not None:
        relative_db = (dest / "dashboard.db").relative_to(repo_root)
        if _ensure_gitignored(repo_root, relative_db):
            print(f"added {relative_db.as_posix()} to {repo_root / '.gitignore'}")

    try:
        cfg["data_dir"] = str(dest.relative_to(config.PROJECT_ROOT))
    except ValueError:
        cfg["data_dir"] = str(dest)
    config.save(cfg)

    print(f"moved dashboard-data to {dest}")
    return 0


def _cmd_set_handoff(args):
    if not args.target:
        print("error: ./dashboard set-handoff needs a path to HANDOFF.md",
              file=sys.stderr)
        return 1
    path = Path(args.target).resolve()
    if not path.exists():
        print(f"error: no file at {path}", file=sys.stderr)
        return 1
    cfg = config.load()
    cfg["handoff"] = str(path)
    config.save(cfg)
    print(f"handoff set to {path}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dashboard",
                                     description="The Kim group meeting dashboard.")
    parser.add_argument("command",
                        choices=["sync", "serve", "update", "export", "meeting",
                                 "where", "move-data", "set-handoff"])
    parser.add_argument("target", nargs="?",
                        help="for `meeting`: the meeting's date, YYYY-MM-DD. "
                             "for `move-data`: the directory dashboard-data should "
                             "live in (the parent, not the folder itself). "
                             "for `set-handoff`: the new HANDOFF.md path.")
    parser.add_argument("--handoff", help="path to HANDOFF.md, overriding the config")
    parser.add_argument("--data", help="data directory, overriding the config")
    parser.add_argument("--clickup", action="store_true",
                        help="merge the cached ClickUp snapshot")
    parser.add_argument("--label", default="",
                        help="for `meeting`: an optional name for the meeting")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    args.date = args.target  # back-compat alias used below for `meeting`

    if args.command == "where":
        return _cmd_where(args)
    if args.command == "move-data":
        return _cmd_move_data(args)
    if args.command == "set-handoff":
        return _cmd_set_handoff(args)

    # Only touch dashboard-config.json (and write it on first use) when this
    # invocation actually needs it — a run that fully overrides both --data
    # and --handoff has no business creating or reading it.
    needs_handoff_cfg = args.command in ("sync", "update") and not args.handoff
    cfg = None
    if args.data is None or needs_handoff_cfg:
        cfg = config.load()
    data_dir = Path(args.data) if args.data else config.resolve_data_dir(cfg)
    paths = _paths(data_dir)
    conn = ensure_db(paths["db"], paths["json"])

    if args.command in ("sync", "update"):
        if _do_sync(conn, args, paths, cfg) is None:
            return 1
        if args.command == "sync":
            return 0

    if args.command == "meeting":
        if not args.date:
            print("error: ./dashboard meeting needs a date, e.g. "
                  "./dashboard meeting 2026-09-21", file=sys.stderr)
            return 1
        try:
            meetings = store.record_meeting(conn, args.date, label=args.label or "")
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        export_json(conn, paths["json"])
        print(f"recorded {args.date} · {len(meetings)} meeting(s) on record")
        return 0

    if args.command == "export":
        export_json(conn, paths["json"])
        print(f"wrote {paths['json']}")
        return 0

    serve_module.run(conn, paths["json"], host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
