"""Loads the plain `decks/<name>.yaml` config (SPEC.md §4: commander,
bracket, threshold, gameplan) -- distinct from `<name>.derived.yaml`
(effect_classes/success_condition, LLM- or skill-derived).

Found this session, via a fresh subagent's report, not by inspection: this
file previously existed for four decks but was never actually read by any
command -- `audit --threshold N` required the value be typed by hand every
time, and nothing cross-checked the config's stated `bracket:` against
`combos`' live Commander Spellbook estimate. That gap is exactly how a
stale bracket claim (Ugluk's `ugluk.yaml` said 3; the deck is actually
Ruthless/4, a real two-card combo) went unnoticed until a full manual run.
This module and its call sites close that gap: config values become real
defaults, and a bracket mismatch is now flagged automatically rather than
only visible if someone reads both outputs side by side.

**`feedback:` -- the iteration log (user-requested directly: "the agent
and skill should be able to pick up and add to that, instead of starting
over").** A running, append-only list in the SAME yaml file (the user's
call: "we have a yaml, why not log it there" rather than a separate file)
of every swap suggestion's outcome and every "never touch this card" pin,
each with a `reason`. `upgrades.py` reads this to MECHANICALLY skip
re-suggesting a pair already marked `rejected`, and to never suggest
touching a `pin`ned card -- not "the agent should remember not to," but a
real filter over real logged data, the same "verify, don't trust" stance
as the rest of this project. Entries are appended via `deckdoctor feedback
<deck> pin|swap|note ...` (see cli.py) rather than a full yaml re-dump, so
existing hand-written comments elsewhere in the file (e.g. the `threshold:
4  # REQUIRED: ...` line) survive -- `append_feedback` only ever adds
text after the `feedback:` block, never rewrites the rest of the file.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime
from pathlib import Path

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None


class DeckConfigError(ValueError):
    """Raised when a `decks/<name>.yaml` document can't be trusted enough
    to read or safely append to -- a non-mapping top level, a `feedback:`
    value that isn't a list, or an entry with missing/wrong-typed owned fields, or
    (via the subclass below) a duplicate key. Deliberately NOT silently
    repaired -- see `_StrictSafeLoader` for why duplicates in particular
    must fail loudly rather than pick a "winning" value."""


class DuplicateKeyError(DeckConfigError):
    """A YAML mapping (top-level or nested, e.g. inside one feedback
    entry) repeats a key. PyYAML's default loader silently keeps the
    LAST value for a repeated key, which for `feedback:` could silently
    discard a real pin/rejection someone already logged -- worse than
    refusing outright."""


class _StrictSafeLoader(yaml.SafeLoader):
    """yaml.SafeLoader, except every mapping (at any nesting depth) is
    checked for duplicate keys and rejected instead of last-write-wins.
    Subclassing (rather than patching yaml.SafeLoader itself) keeps this
    scoped to deck_config's own loads -- `load_playgroup_config` and
    anything else in the codebase still gets ordinary, permissive
    yaml.safe_load semantics."""


def _construct_mapping_strict(loader: yaml.SafeLoader, node: yaml.Node, deep: bool = False):
    if not isinstance(node, yaml.MappingNode):
        raise yaml.constructor.ConstructorError(
            None, None, f"expected a mapping node, got {node.id}", node.start_mark
        )
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise DeckConfigError("YAML mapping keys must be hashable") from exc
        if duplicate:
            raise DuplicateKeyError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
        try:
            mapping[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as exc:
            raise DeckConfigError("YAML mapping keys must be hashable") from exc
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_strict
)


def _safe_load_strict(text: str):
    try:
        return yaml.load(text, Loader=_StrictSafeLoader)
    except DeckConfigError:
        raise
    except yaml.YAMLError as exc:
        raise DeckConfigError(f"malformed YAML: {exc}") from exc


def _parse_document(text: str) -> dict:
    doc = _safe_load_strict(text)
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise DeckConfigError(f"top-level YAML must be a mapping, got {type(doc).__name__}")
    return doc


@dataclass
class FeedbackEntry:
    date: str
    kind: str  # "pin" | "swap" | "note"
    status: str | None = None  # swap only: "accepted" | "rejected" | "deferred"
    card: str | None = None  # pin only
    current: str | None = None  # swap only
    suggested: str | None = None  # swap only
    text: str | None = None  # note only
    reason: str | None = None


@dataclass
class DeckConfig:
    commander: str
    bracket: int | None = None
    threshold: float | None = None
    gameplan: str | None = None
    feedback: list[FeedbackEntry] = field(default_factory=list)
    # EDHREC theme slug (`deckdoctor themes` lists them), e.g. "tokens".
    # Selects which EDHREC page ranks candidates -- the commander's base page
    # mixes every way it gets built.
    edhrec_theme: str | None = None


_FEEDBACK_FIELDS = {f.name for f in fields(FeedbackEntry)}
_FEEDBACK_STRING_FIELDS = {
    "date", "kind", "status", "card", "current", "suggested", "text", "reason"
}


def _validated_feedback_items(raw: object) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DeckConfigError(f"'feedback' must be a list, got {type(raw).__name__}")
    items = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise DeckConfigError(f"feedback[{i}] must be a mapping, got {type(item).__name__}")
        known = {key: value for key, value in item.items() if key in _FEEDBACK_FIELDS}
        try:
            FeedbackEntry(**known)
        except TypeError as exc:
            raise DeckConfigError(f"feedback[{i}] is invalid: {exc}") from exc
        for key in _FEEDBACK_STRING_FIELDS & known.keys():
            value = known[key]
            if key == "date" and isinstance(value, date) and not isinstance(value, datetime):
                # SafeLoader decodes an unquoted ISO date as a date object.
                # Existing user histories use this valid YAML representation.
                continue
            if value is not None and not isinstance(value, str):
                raise DeckConfigError(
                    f"feedback[{i}].{key} must be a string or null, got {type(value).__name__}"
                )
        items.append(dict(item))
    return items


def _validate_feedback_field(raw: object) -> list[FeedbackEntry]:
    return [
        FeedbackEntry(**{key: value.isoformat() if key == "date" and isinstance(value, date) else value
                         for key, value in item.items() if key in _FEEDBACK_FIELDS})
        for item in _validated_feedback_items(raw)
    ]


def config_path_for(deck_path: str) -> Path:
    return Path(deck_path).with_suffix(".yaml")


def load_deck_config(deck_path: str) -> DeckConfig | None:
    path = config_path_for(deck_path)
    if not path.exists():
        return None
    doc = _parse_document(path.read_text(encoding="utf-8"))
    feedback = _validate_feedback_field(doc.get("feedback"))
    return DeckConfig(
        commander=doc.get("commander", ""),
        bracket=doc.get("bracket"),
        threshold=doc.get("threshold"),
        gameplan=doc.get("gameplan"),
        feedback=feedback,
        edhrec_theme=doc.get("edhrec_theme"),
    )


def pinned_cards(config: DeckConfig | None) -> dict[str, str | None]:
    """card name -> reason, for every `pin` entry -- these must never be
    suggested for a cut/swap again."""
    if config is None:
        return {}
    return {e.card: e.reason for e in config.feedback if e.kind == "pin" and e.card}


def legality_exceptions(config: DeckConfig | None) -> dict[str, str | None]:
    """card name -> reason, for every `legality_exception` entry -- an
    explicit, user-authored override for a card the local mirror marks
    Commander-illegal (`commander_legal: 0`), logged the same append-only
    way as a `pin` (`deckdoctor feedback <deck> legality-exception --card
    ... --reason ...`).

    Real gap this closes: a `pin` alone ("never suggest touching this
    card") does not affect `validate_deck`'s legality check -- the deck
    still fails validation, and per docs/workflow.md ("Do not run numeric
    assessments on an invalid deck") that blocks every downstream
    command. Without this, the only way forward was substituting a
    different, actually-legal card into the analysis copy -- which
    silently evaluates a deck the user isn't playing. `validate_deck`
    reads this mapping and downgrades `card_not_legal` for a listed name
    from a blocking error to a visible, non-blocking accepted-exception
    note instead, so the REAL card stays in every report.

    Deliberately narrow: this overrides `commander_legal` only, not
    colour identity or commander eligibility -- a playgroup table ruling
    ("we allow this card") is the concrete, common case (e.g. a
    recently-printed card the local mirror hasn't synced Commander
    legality for yet); those other checks stay hard errors."""
    if config is None:
        return {}
    return {e.card: e.reason for e in config.feedback if e.kind == "legality_exception" and e.card}


def rejected_swaps(config: DeckConfig | None) -> dict[tuple[str, str], str | None]:
    """(current, suggested) -> reason, for every `swap` entry logged
    `rejected` -- that SPECIFIC pair must not be re-suggested, though a
    DIFFERENT candidate for the same current card still can be."""
    if config is None:
        return {}
    return {
        (e.current, e.suggested): e.reason
        for e in config.feedback
        if e.kind == "swap" and e.status == "rejected" and e.current and e.suggested
    }


def accepted_swaps(config: DeckConfig | None) -> set[tuple[str, str]]:
    """(current, suggested) pairs logged `accepted` -- used to note when a
    swap was agreed to but the current decklist shows it hasn't actually
    been made yet."""
    if config is None:
        return set()
    return {
        (e.current, e.suggested)
        for e in config.feedback
        if e.kind == "swap" and e.status == "accepted" and e.current and e.suggested
    }


def _render_feedback_item(data: dict, newline: str = "\n") -> str:
    data = {k: v for k, v in data.items() if v is not None}
    dumped = yaml.safe_dump([data], default_flow_style=False, sort_keys=False, allow_unicode=True)
    rendered = "\n".join(("  " + line if line else line) for line in dumped.splitlines()) + "\n"
    return rendered.replace("\n", newline)


def _render_feedback_entry(entry: FeedbackEntry, newline: str = "\n") -> str:
    return _render_feedback_item(asdict(entry), newline=newline)


def _render_feedback_block(entries: list[FeedbackEntry], newline: str = "\n") -> str:
    return "".join(_render_feedback_entry(e, newline=newline) for e in entries)


def _render_feedback_items(items: list[dict], newline: str = "\n") -> str:
    return "".join(_render_feedback_item(item, newline=newline) for item in items)


def _reject_yaml_aliases(text: str) -> None:
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None):
                raise DeckConfigError("YAML anchors and aliases are unsupported for feedback append")
    except DeckConfigError:
        raise
    except yaml.YAMLError as exc:
        raise DeckConfigError(f"malformed YAML: {exc}") from exc


def _validate_candidate(text: str, new_entry: FeedbackEntry, expected_count: int) -> str:
    candidate = _parse_document(text)
    entries = _validate_feedback_field(candidate.get("feedback"))
    if len(entries) != expected_count or not entries or asdict(entries[-1]) != asdict(new_entry):
        raise DeckConfigError("generated feedback document failed validation")
    return text


def _compute_appended_text(text: str, new_entry: FeedbackEntry) -> str:
    """Validate `text` (rejecting duplicate keys, a non-mapping top level,
    or a `feedback:` value that isn't a list of valid entries) and return
    the new file contents with `new_entry` appended -- or raise
    `DeckConfigError`/`yaml.YAMLError` without producing any output at all.
    Callers must not write anything if this raises.

    YAML-aware, not a regex/text scan: `yaml.compose` gives the real parse
    tree with character offsets (`Mark.index`) for the `feedback:` key and its
    value, so the *value* span is replaced precisely regardless of whether
    it's a bare `feedback:`, an inline `feedback: []`/`feedback: [ {...} ]`
    (must handle a populated inline list, not just empty), or a multi-line
    block sequence followed by a later top-level key. Everything outside
    that span -- other keys, their comments, their formatting -- is passed
    through byte-for-byte untouched.

    Formatting normalization (disclosed per T01): the *existing* feedback
    entries are re-rendered in block style alongside the new one, so an
    inline/flow list becomes a block list, and any comments written
    *inside* the feedback list itself (not elsewhere in the file) are not
    preserved. A bare `feedback:` (or `feedback: # comment`) with zero
    entries is special-cased to leave that exact line untouched (comment
    included) and insert the new block immediately after it.
    """
    if not isinstance(new_entry, FeedbackEntry):
        raise DeckConfigError("new feedback entry must be a FeedbackEntry")
    _validated_feedback_items([asdict(new_entry)])
    _reject_yaml_aliases(text)
    doc = _parse_document(text)
    old_items = _validated_feedback_items(doc.get("feedback"))
    expected_count = len(old_items) + 1

    root = yaml.compose(text, Loader=yaml.SafeLoader)
    key_node = value_node = None
    if root is not None:
        if not isinstance(root, yaml.MappingNode):
            raise DeckConfigError("top-level YAML must be a mapping")
        for k, v in root.value:
            if isinstance(k, yaml.ScalarNode) and k.value == "feedback":
                key_node, value_node = k, v
                break

    if key_node is None:
        newline = "\r\n" if "\r\n" in text else "\n"
        if text and not text.endswith(("\n", "\r")):
            text += newline
        result = text + (newline if text and not text.endswith(newline) else "") + f"feedback:{newline}" + _render_feedback_block([new_entry], newline=newline)
        return _validate_candidate(result, new_entry, expected_count)

    if isinstance(value_node, yaml.ScalarNode) and value_node.tag == "tag:yaml.org,2002:null":
        # Bare `feedback:` (optionally with a same-line comment) and no
        # entries -- leave that whole line untouched, insert right after.
        newline = "\r\n" if "\r\n" in text else "\n"
        rendered = _render_feedback_block([new_entry], newline=newline)
        newline_idx = text.find("\n", key_node.start_mark.index)
        if newline_idx == -1:
            sep = "" if text.endswith("\n") else "\n"
            return _validate_candidate(text + sep + rendered, new_entry, expected_count)
        insert_at = newline_idx + 1
        return _validate_candidate(text[:insert_at] + rendered + text[insert_at:], new_entry, expected_count)

    if not isinstance(value_node, yaml.SequenceNode):
        raise DeckConfigError(
            f"cannot safely append to 'feedback' (node type {value_node.id}); "
            "expected a plain list, not an alias/anchor or other construct"
        )

    newline = "\r\n" if "\r\n" in text else "\n"
    rendered_all = _render_feedback_items(old_items + [asdict(new_entry)], newline=newline)
    value_start, value_end = value_node.start_mark.index, value_node.end_mark.index
    if value_node.start_mark.line == key_node.start_mark.line:
        # Inline/flow value (e.g. `feedback: []` or `feedback: [ {...} ]`)
        # sharing the key's line -- drop it and start the block on a new line.
        head = text[:value_start].rstrip(" \t") + newline
    else:
        # Block-style value: start_mark.index points at the `-` token
        # itself, not the start of its (indented) line -- replace from the
        # line's true start so the old line's leading spaces aren't left
        # dangling in front of the freshly rendered block (which supplies
        # its own "  - " indent), producing inconsistent indentation.
        line_start = text.rfind("\n", 0, value_start) + 1
        head = text[:line_start]
    return _validate_candidate(head + rendered_all + text[value_end:], new_entry, expected_count)


def _default_new_file_mode() -> int:
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


@contextlib.contextmanager
def _locked(lock_path: Path):
    """Exclusive advisory lock (POSIX `fcntl.flock`) on a sidecar
    `<name>.yaml.lock`, held for the whole read-modify-write critical
    section below so two callers -- two threads, two processes, this CLI
    invoked twice -- can't interleave a read and a write and silently lose
    one's update. Platform semantics, spelled out because "local lock" can
    mean several incompatible things:

    - Advisory, not mandatory: it only excludes OTHER code that also
      flocks this same lock path. It does not stop something from writing
      to the `.yaml` file directly without going through `append_feedback`.
    - POSIX only. This module already hard-depends on `fcntl` (imported
      unconditionally above), which does not exist on Windows -- this
      function will raise `AttributeError`/`ImportError` there. No attempt
      is made to fall back to `msvcrt`; that's out of scope for T01.
    - Unreliable over NFS (a well-known `flock` limitation) -- fine for
      this repo's local decks/ directory, not a guarantee for a network
      mount.
    - The lock file is intentionally never unlinked after use. Deleting it
      would race: another process could still hold the now-unlinked inode
      open while a third process creates a fresh lock file of the same
      name, and the two would no longer exclude each other. A persistent
      empty sidecar file is the standard, safe tradeoff.
    """
    if fcntl is None:
        raise DeckConfigError("feedback append requires POSIX fcntl locking")
    lock_file = open(lock_path, "a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _atomic_write(path: Path, data: bytes, mode: int | None) -> None:
    """Write `data` to a temp file in `path`'s own directory (so the final
    `os.replace` is on one filesystem and therefore atomic on POSIX),
    fsync it for durability, restore `mode` (the original file's
    permissions) or a umask-appropriate default for a brand-new file, then
    replace. On any failure -- including one injected after the temp file
    is written, e.g. a failing `os.replace` -- the temp file is removed
    and `path` is left exactly as it was; nothing here ever writes to
    `path` directly."""
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, stat.S_IMODE(mode if mode is not None else _default_new_file_mode()))
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def append_feedback(deck_path: str, entry: FeedbackEntry) -> Path:
    """Appends one entry to the yaml's `feedback:` list.

    Read-modify-write transaction: holds a local advisory lock (see
    `_locked`) for the entire read + validate + splice + atomic-replace
    sequence, so a lost update requires a writer that bypasses this
    function entirely (out of scope -- see `_locked`'s docstring).
    Validation (`_compute_appended_text` -> `_parse_document` ->
    `_safe_load_strict`/`_validate_feedback_field`) happens entirely
    in-memory before any file is touched: a duplicate key, a non-mapping
    top level, or an invalid `feedback:` value raises and leaves the
    original file's bytes and permissions completely unchanged.

    **Real bug fixed here, caught by an independent code review before it
    shipped**: an earlier version assumed `feedback:` (if present at all)
    was always a bare block key with no inline value, AND always the LAST
    top-level key in the file -- so it just appended the new entry at
    end-of-file. Neither assumption holds: `load_deck_config`/whatever
    first creates the yaml can just as easily write `feedback: []` (an
    inline empty list -- exactly what this session's own derived config
    for a real deck did), and nothing stops a human from adding a key
    after `feedback:` later (e.g. reordering `gameplan:` below it), or
    populating that inline list directly (`feedback: [{date: ..., ...}]`).
    `_compute_appended_text` now locates the `feedback:` key's value via a
    real parse tree instead of guessing from indentation."""
    path = config_path_for(deck_path)
    lock_path = path.with_name(path.name + ".lock")

    with _locked(lock_path):
        exists = path.exists()
        original_bytes = path.read_bytes() if exists else b""
        original_mode = path.stat().st_mode if exists else None
        text = original_bytes.decode("utf-8")

        new_text = _compute_appended_text(text, entry)

        _atomic_write(path, new_text.encode("utf-8"), original_mode)
    return path


@dataclass
class PlaygroupConfig:
    """Rules that apply across EVERY deck, not one -- distinct from
    per-deck `decks/<name>.yaml` and from `KNOWN_ISSUES.md` (tool bugs,
    not playgroup rules). User-requested directly: "do not include the
    super expensive dual lands like badlands. this is a condition of my
    play group. this needs to be defined somewhere" -- `playgroup.yaml`
    at the repo root is that "somewhere"."""
    exclude_original_dual_lands: bool = False
    # Optional ManaBox-style inventory of available spares not in decks. It is
    # positive evidence for nonland additions only, never a full ownership
    # ledger or a reason to cut a card already in a deck. Lands are ignored.
    collection_file: str | None = None


def load_playgroup_config(path: str = "playgroup.yaml") -> PlaygroupConfig:
    """Missing file -> all-default config (nothing excluded), not an
    error -- this file is optional; its absence just means no playgroup
    rules are active."""
    p = Path(path)
    if not p.exists():
        return PlaygroupConfig()
    with open(p, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    collection_file = doc.get("collection_file")
    if collection_file is not None and not isinstance(collection_file, str):
        raise DeckConfigError("playgroup.yaml 'collection_file' must be a path string or null")
    return PlaygroupConfig(
        exclude_original_dual_lands=bool(doc.get("exclude_original_dual_lands", False)),
        collection_file=collection_file,
    )
