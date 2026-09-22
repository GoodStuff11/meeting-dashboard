"""Source adapters.

Each adapter turns some external record into `Item`s the sync layer can
reconcile. The contract is one function, `fetch()`, returning a list of `Item`.
Which source feeds the dashboard is still an open question, so keep adapters
free of anything specific to the store.
"""

from dataclasses import dataclass


@dataclass
class Item:
    id: str
    title: str
    why: str = ""
    owner: str = ""
    state: str = "open"
    raised: str = ""
    clickup_id: str | None = None
    priority: str = ""
    clickup_status: str | None = None
    due: str | None = None


@dataclass
class Flag:
    """A §7.1 disagreement.

    `key` is a stable hash of the disagreement's headline, not its position in
    the hand-numbered list: inserting an entry renumbers everything below it,
    and a positional key would quietly rewrite each later flag's text under an
    older flag's key (keeping its `first_seen`, so it would look old) while the
    genuinely new one was never proposed. `ordinal` keeps the §7.1 number for
    display only.
    """

    key: str
    text: str
    resolved: bool = False
    ordinal: str = ""


__all__ = ["Item", "Flag"]
