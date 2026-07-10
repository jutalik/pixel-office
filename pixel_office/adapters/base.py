"""The Adapter descriptor: everything Pixel Office needs to know about one CLI."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple

# a JSONL/SQLite parser: (record|row) -> (kind, ts, session_id|None, meta) | None
ParseFn = Callable[[object], Optional[Tuple[str, str, Optional[str], dict]]]
# how to name a session when a record carries no id (given the file path)
SessionIdFn = Callable[[Path], str]


@dataclass(frozen=True)
class Adapter:
    name: str

    # --- normalization: the ONLY per-CLI kind->activity table -----------------
    #: full lifecycle vocabulary (hooks can emit all of it)
    kinds: Mapping[str, str] = field(default_factory=dict)
    #: the subset of `kinds` this CLI's tailer/session-parser actually emits
    emitted_kinds: frozenset = frozenset()

    # --- detection ------------------------------------------------------------
    is_cli: bool = True                            # False = pseudo-source (e.g. the org runtime)
    bin_name: Optional[str] = None                 # PATH name (defaults to `name`)
    extra_bin_dirs: Tuple[Path, ...] = ()
    env_home: Optional[str] = None                 # home-override env var, if any
    home: Optional[Path] = None                    # config/session home

    # --- session store --------------------------------------------------------
    session_kind: str = "none"                     # 'jsonl' | 'sqlite' | 'none'
    session_glob: Optional[str] = None             # jsonl glob, relative to home
    session_sqlite: Optional[str] = None           # sqlite db glob, relative to home
    sqlite_query: Optional[str] = None
    sqlite_mapper: Optional[ParseFn] = None        # None => provisional (unverified)
    parse_line: Optional[ParseFn] = None           # jsonl parser
    session_id_from_path: Optional[SessionIdFn] = None

    # --- hooks ----------------------------------------------------------------
    hooks_capable: bool = False                    # the CLI itself supports hooks
    #: Pixel Office can actually install AND observe hooks for this CLI TODAY
    #: (an installer exists + its hook event names are in `kinds`). Only Claude
    #: so far — codex/grok/agy hooks are planned, not shipped.
    hooks_installable: bool = False
    hook_kind: str = "settings"                    # settings | config | plugin

    # ---- derived -------------------------------------------------------------
    @property
    def binary(self) -> str:
        return self.bin_name or self.name

    @property
    def has_verified_tailer(self) -> bool:
        """True when this CLI can actually be tailed today (verified parser)."""
        if self.session_kind == "jsonl":
            return self.parse_line is not None
        if self.session_kind == "sqlite":
            return self.sqlite_mapper is not None
        return False

    @property
    def normalize_supported(self) -> bool:
        return bool(self.kinds) and self.has_verified_tailer

    @property
    def tailer_derivable(self) -> Tuple[str, ...]:
        """The activity states this CLI's tailer can actually produce."""
        return tuple(sorted({self.kinds[k] for k in self.emitted_kinds if k in self.kinds}))

    def session_id_for(self, path: Path) -> str:
        fn = self.session_id_from_path or (lambda p: p.stem)
        return fn(path)
