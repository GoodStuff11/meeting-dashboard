"""Parse `HANDOFF.md` section 7 — the ledger where item numbers are born.

Section 7 is hand-written prose and its shape will drift. Every failure mode
here is loud on purpose: a parser that silently drops an item produces a
dashboard that is quietly wrong, which is worse than one that will not build.

To catch a malformed item header (missing period, stray space after the
opening `**`, etc.) that would otherwise merge silently into the previous
item's body, each subsection is scanned twice: once with the strict item
regex and once with a looser "item-like line" candidate regex. A mismatch
between the two counts raises `HandoffParseError` naming the offending
line(s), rather than quietly dropping an item.

Known limitations of this guard, which no line-anchored regex can close:
- A header that has lost its `**` bold markers entirely is indistinguishable
  from ordinary numbered prose and will not be flagged.
- A header not at a true line start (e.g. embedded mid-paragraph rather than
  beginning its own line) is invisible to both the strict and candidate
  regexes and will not be flagged.
These are accepted gaps, not bugs to chase with a heavier regex; anything
further would risk false positives on dated progress notes and similar
prose that legitimately starts with `**<digits>`.
"""

import hashlib
import re
from pathlib import Path

from . import Flag, Item


class HandoffParseError(ValueError):
    """Raised when section 7 cannot be parsed into items."""


_SECTION_7 = re.compile(r"^##\s+7\.\s", re.M)
_SECTION_71 = re.compile(r"^###\s+7\.1\s", re.M)
_NEXT_H2 = re.compile(r"^##\s+(?!7\.)", re.M)
_OWNER_HEADING = re.compile(r"^###\s+Open\s+[—-]\s*(?P<owner>.+?)\s*$", re.M)
_CLOSED_HEADING = re.compile(r"^###\s+Closed\s*$", re.M)
_ITEM = re.compile(r"^\*\*(?P<num>\d+[a-z]?)\.\s+(?P<title>.+?)\*\*", re.M)
# Looser "this line looks like it wants to be an item header" detector, used
# only as a count guard against _ITEM so a malformed header (missing period,
# stray space, ...) is caught rather than silently merged into the previous
# item's body. Constrained to 1-3 digits so it does not fire on dated
# progress notes like "**2026-09-21:** ..." (a 4-digit year), which are
# legitimate prose inside section 7.
_ITEM_CANDIDATE = re.compile(r"^\*\*\s*\d{1,3}[a-z]?[.\s)]", re.M)
_CLICKUP = re.compile(r"[Tt]ask\s+`(?P<id>[0-9a-z]{6,})`")
_RAISED = re.compile(r"(?:raised|Asked|asked)\s+(?P<date>\d{4}-\d{2}-\d{2})")
_FLAG_ENTRY = re.compile(r"^(?P<key>\d+)\.\s+(?P<body>.*?)(?=^\d+\.\s|\Z)", re.M | re.S)
# An explicit priority marker in an item's body. Only an explicit one: §7 is
# prose, and inferring urgency from wording would put words in the group's
# mouth. Item 14 says "*Task `86akhca0p`, high priority.*" and item 14 decides
# the paper's venue — without this it sorted to the bottom of the board.
_PRIORITY = re.compile(r"\b(?:high|top)\s+priority\b", re.I)


_BULLET = re.compile(r"^[-*]\s+(?=\S)")


def _blocks(text):
    """Collapse hard-wrapped prose while keeping its block structure.

    Markdown's own rules, cut down to what the ledger uses: a blank line ends
    a paragraph, a line opening with `- ` (or `* `) starts a bullet, and any
    other line — indented or not — continues whatever block it follows. Inside
    a block all whitespace collapses to single spaces, exactly as before, so
    one-paragraph prose comes out byte-identical to the old flattening.

    The result joins paragraphs with a blank line and puts consecutive bullets
    on consecutive `- ` lines, which is the form `renderRich` in app.js reads.
    `*` must be followed by whitespace to count, so `**bold**` never does.
    """
    blocks = []  # [kind, [line fragments]] with kind "p" or "li"
    open_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            open_block = False
            continue
        bullet = _BULLET.match(line)
        if bullet:
            blocks.append(["li", [line[bullet.end():]]])
        elif open_block:
            blocks[-1][1].append(line)
        else:
            blocks.append(["p", [line]])
        open_block = True
    out = []
    for index, (kind, parts) in enumerate(blocks):
        body = " ".join(" ".join(parts).split())
        if index:
            # Consecutive bullets share a list; anything else is a new block.
            out.append("\n" if kind == "li" and blocks[index - 1][0] == "li" else "\n\n")
        out.append(f"- {body}" if kind == "li" else body)
    return "".join(out)


def _section_7(text):
    start = _SECTION_7.search(text)
    if start is None:
        raise HandoffParseError("no '## 7.' heading found in HANDOFF.md")
    rest = text[start.end():]
    end = _NEXT_H2.search(rest)
    body = rest if end is None else rest[:end.start()]
    return body


def _split_subsections(body):
    """Yield (owner, state, text) for each ### block inside section 7."""
    marks = []
    for m in _OWNER_HEADING.finditer(body):
        marks.append((m.start(), m.end(), m.group("owner").strip(), "open"))
    for m in _CLOSED_HEADING.finditer(body):
        marks.append((m.start(), m.end(), "", "closed"))
    marks.sort()
    if not marks:
        raise HandoffParseError(
            "section 7 has no '### Open — <name>' or '### Closed' subsections")
    flags_start = _SECTION_71.search(body)
    limit = flags_start.start() if flags_start else len(body)
    out = []
    for index, (start, content_start, owner, state) in enumerate(marks):
        if start >= limit:
            continue
        end = marks[index + 1][0] if index + 1 < len(marks) else limit
        out.append((owner, state, body[content_start:min(end, limit)]))
    return out


def _parse_items(body):
    items = []
    for owner, state, text in _split_subsections(body):
        matches = list(_ITEM.finditer(text))
        candidates = list(_ITEM_CANDIDATE.finditer(text))
        if len(candidates) != len(matches):
            match_starts = {m.start() for m in matches}
            bad_lines = []
            for candidate in candidates:
                if candidate.start() in match_starts:
                    continue
                line_end = text.find("\n", candidate.start())
                line = text[candidate.start():line_end if line_end != -1 else len(text)]
                bad_lines.append(line.strip())
            raise HandoffParseError(
                f"subsection for owner {owner!r} (state {state}): found "
                f"{len(candidates)} item-like line(s) but only parsed "
                f"{len(matches)} as valid item headers; a header is likely "
                f"malformed (missing period, stray space, ...). Offending "
                f"line(s): {bad_lines!r}")
        if not matches:
            raise HandoffParseError(
                f"subsection for owner {owner!r} (state {state}) contains no items; "
                "section 7's format has changed")
        for index, match in enumerate(matches):
            stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            chunk = text[match.end():stop]
            why = chunk.strip()
            if why.startswith("—") or why.startswith("--"):
                why = why.lstrip("—-").strip()
            clickup = _CLICKUP.search(chunk)
            raised = _RAISED.search(chunk)
            items.append(Item(
                id=match.group("num"),
                title=match.group("title").strip(),
                why=_blocks(why),
                owner=owner,
                state=state,
                raised=raised.group("date") if raised else "",
                clickup_id=clickup.group("id") if clickup else None,
                priority="high" if _PRIORITY.search(chunk) else "",
            ))
    seen = {}
    for item in items:
        if item.id in seen:
            raise HandoffParseError(
                f"item number {item.id!r} appears twice in section 7; "
                "numbers are unique identifiers and must not be reused")
        seen[item.id] = item
    return items


def flag_title(text):
    """A flag's headline: its first bolded phrase, else its opening words.

    This is the part of a §7.1 entry that stays put. Resolving one strikes the
    headline through with `~~` and appends prose after it, and neither touches
    what this returns — which is why it, and not the whole body, is what
    `flag_key` hashes.
    """
    stripped = (text or "").strip().lstrip("~").strip()
    bold = re.match(r"\*\*(?P<t>.+?)\*\*", stripped)
    if bold:
        return bold.group("t").strip()
    return " ".join(stripped.split()[:12])


def flag_key(text):
    """A short stable identifier for a §7.1 disagreement, from its headline.

    Not the §7.1 ordinal: those renumber whenever somebody inserts an entry.
    See the `Flag` docstring. Rewording a headline does mint a new key — that
    is the deliberate trade, since a reworded disagreement cannot be told from
    a new one, and a new one being listed is the safe direction to fail.
    """
    identity = " ".join(flag_title(text).casefold().split())
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]


def _parse_flags(body):
    match = _SECTION_71.search(body)
    if match is None:
        return []
    text = body[match.end():]
    flags = []
    for entry in _FLAG_ENTRY.finditer(text):
        raw = _blocks(entry.group("body"))
        flags.append(Flag(key=flag_key(raw), text=raw, resolved=raw.startswith("~~"),
                          ordinal=entry.group("key")))
    return flags


def parse_handoff(text):
    """Return (items, flags) parsed from section 7 of a HANDOFF.md document."""
    body = _section_7(text)
    return _parse_items(body), _parse_flags(body)


def read_handoff(path):
    return parse_handoff(Path(path).read_text())


def fetch(path):
    """Adapter entry point: items only, for callers that do not want flags."""
    return read_handoff(path)[0]
