"""Parse STS2 godot.log to reconstruct live run state in real-time."""
import logging
import os
import re
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# Log file location (same AppData tree as saves)
_LOG_DIR = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "SlayTheSpire2" / "logs"
if sys.platform == "darwin":
    _LOG_DIR = Path.home() / "Library" / "Application Support" / "SlayTheSpire2" / "logs"
elif sys.platform == "linux":
    # On Linux STS2 typically runs under Proton — match the save-dir resolution
    # in sts2/config.py so the log poller and save watcher see the same install.
    _proton_base = (
        Path.home() / ".local" / "share" / "Steam" / "steamapps"
        / "compatdata" / "2868840" / "pfx" / "drive_c" / "users"
        / "steamuser" / "AppData" / "Local" / "SlayTheSpire2"
    )
    if _proton_base.exists():
        _LOG_DIR = _proton_base / "logs"
    else:
        _LOG_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "SlayTheSpire2" / "logs"

LOG_FILE = _LOG_DIR / "godot.log"

# How much of an existing log to parse at startup, and how much backlog a
# single poll will read. godot.log grows for as long as the game runs;
# reading it whole pinned startup and memory to the log's size.
_INIT_TAIL_BYTES = 5 * 1024 * 1024
_MAX_POLL_BYTES = 10 * 1024 * 1024


def _resolve_log_path() -> Path:
    """STS2_LOG_FILE overrides detection (tests, sandboxes, custom installs).

    Resolved per call: the fixed import-time path meant a redirected
    deployment silently tailed the host user's real log.
    """
    env = os.environ.get("STS2_LOG_FILE")
    return Path(env) if env else LOG_FILE

# Regex patterns for extracting game events
_RE_OBTAINED_CARD = re.compile(r"\[INFO\] Obtained (CARD\.\w+) from card reward")
_RE_OBTAINED_POTION = re.compile(r"\[INFO\] Obtained (POTION\.\w+) from potion reward")
_RE_OBTAINED_GOLD = re.compile(r"\[INFO\] Obtained (\d+) gold from reward")
_RE_USED_POTION = re.compile(r"\[INFO\] Player \d+ using potion (\w+)")
_RE_DISCARD_POTION = re.compile(r"\[INFO\] Player \d+ discarding potion (\w+)")
_RE_COMBAT_START = re.compile(r"\[INFO\] Creating NCombatRoom with mode=ActiveCombat encounter=(\w+)")
_RE_WON_ENCOUNTER = re.compile(r"\[INFO\] (CHARACTER\.\w+) has won against encounter (ENCOUNTER\.\w+)")
_RE_LOST_ENCOUNTER = re.compile(r"\[INFO\] (CHARACTER\.\w+) fought (ENCOUNTER\.\w+) for the first time and LOST")
_RE_WROTE_SAVE = re.compile(r"\[INFO\] Wrote \d+ bytes to path=.*?\\(current_run(?:_mp)?\.save)")
_RE_SAVED_HISTORY = re.compile(r"\[INFO\] Saved run history: (\d+)\.run")
_RE_LOBBY_DISCONNECT = re.compile(r"\[INFO\] \[RunLobby\] Disconnected\. Reason: (\w+)")
# Unmatched on real logs: a full v0.103.2 session emitted no
# MapSelectionSynchronizer lines at all (0 hits over 1367 lines, while the
# neighbouring preload pattern hit 83), so state.floor stays 0 in practice.
# The live view takes floor from the save, which is authoritative and
# cumulative, so this only ever supplemented. Left in place in case other
# builds emit it; do not make anything depend on it without re-measuring.
_RE_MOVING = re.compile(r"\[DEBUG\] \[MapSelectionSynchronizer\] Moving to coordinate MapCoord \((\d+), (\d+)\)")
_RE_ROOM_PRELOAD = re.compile(r"\[INFO\] Preloading '(.+?)' assets")
_RE_EPOCH = re.compile(r"\[INFO\] Epoch obtained for completing Act (\d+)")
_RE_CHAR_SELECT = re.compile(r"Received LobbyPlayerChangedCharacterMessage for \d+ (CHARACTER\.\w+)")
_RE_LOCAL_READY = re.compile(r"\[INFO\] \[StartRunLobby.*?\] Local player (\d+) is ready")
_RE_CLIENT_CONNECT = re.compile(r"\[INFO\] \[StartRunLobby.*?\] Client (\d+) connected")
_RE_NEOW_EVENT = re.compile(r"\[VERYDEBUG\] \[EventSynchronizer\] Event EVENT\.NEOW began for player (\d+)")
# Combat telemetry — surfaces signal the godot.log emits but the parser
# previously ignored. Enables turn-by-turn analytics without requiring the
# STS2MCP mod.
# Card ids are dotted (CARD.BASH), so a bare \w+ captured only "CARD" —
# every play recorded the same meaningless token. The player number is
# captured too: in co-op the log interleaves both players, and attributing
# a teammate's plays to whoever the page is watching is simply wrong.
# Real logs name the card without its CARD. prefix
# ("Player 1 playing card STRIKE_IRONCLAD (targeting ...)"), and the number
# is the player's id as the save records it ("1" in solo), not a seat index.
_RE_PLAYING_CARD = re.compile(r"\[INFO\] Player (\d+) playing card ([\w.]+)")
_RE_EXTRA_TURN = re.compile(r"\[INFO\] Player (\d+) \([A-Z]+\) is taking an extra turn")
_RE_ELITES_DEFEATED = re.compile(r"\[INFO\] Elites Defeated: (\d+)/\d+")
# Run identity: "Embarking on a singleplayer IRONCLAD run. Ascension: 1
# Seed: 0GUR32LH2X". The seed matches the save's "seed" for the same run, so
# the live view can refuse to mix a stale or foreign log into the save.
_RE_EMBARK = re.compile(r"\[INFO\] Embarking on an? (\w+) (\w+) run\.(?: Ascension: (\d+))?(?: Seed: (\w+))?")

# Character ID mapping
_CHAR_MAP = {
    "CHARACTER.IRONCLAD": "Ironclad",
    "CHARACTER.SILENT": "Silent",
    "CHARACTER.DEFECT": "Defect",
    "CHARACTER.NECROBINDER": "Necrobinder",
    "CHARACTER.REGENT": "Regent",
}


class LogRunState:
    """Mutable state built from log parsing."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.active = False
        self.character = ""
        self.deck: list[str] = []
        self.relics: list[str] = []
        self.potions: list[str] = []
        self.gold = 0
        self.act = 1
        self.floor = 0
        self.current_encounter = ""
        self.encounters_won: list[str] = []
        self.events_seen: list[str] = []
        self.total_players = 1
        self.run_started = False
        # Combat telemetry captured from godot.log, kept per player because
        # a co-op log interleaves both. Each list is bounded to prevent
        # unbounded memory growth on long runs (O(n) copy per SSE poll).
        self.cards_played_by_player: dict[int, list[str]] = {}
        self._cards_played_cap = 500
        self.extra_turns_by_player: dict[int, int] = {}
        # Run-wide, not per player: the game emits a cumulative count.
        self.elites_defeated = 0
        # The number this machine's player appears under in "Player N ..."
        # lines, from "Local player N is ready". None until seen.
        self.local_player: int | None = None
        # Run identity from the "Embarking on ..." line; empty/None = unknown.
        self.seed = ""
        self.ascension: int | None = None

    def _telemetry_player(self, player: int | None) -> int | None:
        """Which logged player number to report telemetry for.

        An explicit number wins. Otherwise the local player named by the
        lobby line, and failing that the only player the log has seen (a
        solo log only ever names one).
        """
        if player is not None:
            return player
        if self.local_player is not None:
            return self.local_player
        seen = set(self.cards_played_by_player) | set(self.extra_turns_by_player)
        if len(seen) == 1:
            return next(iter(seen))
        return None

    def to_dict(self, player: int | None = None) -> dict:
        """Convert to dict compatible with CurrentRun.model_dump().

        Combat telemetry (cards_played, extra_turns, elites_defeated) is
        declared on CurrentRun with defaults, so log-sourced state carries it
        through to API/SSE payloads while save-file-only paths just leave
        the defaults. Before the fields were declared, pydantic silently
        dropped them here and no consumer ever saw them.

        Telemetry is reported for `player` -- the number the log prints in
        "Player N ...", which is the save's player id ("1" in solo), not a
        seat index -- defaulting to the local player. The full per-player
        breakdown rides along under keys CurrentRun does not declare so
        callers that know whose id they are watching can select. Reporting
        one merged total attributed a co-op partner's plays to whoever the
        page happened to be showing.
        """
        who = self._telemetry_player(player)
        return {
            "active": self.active,
            "character": self.character,
            "current_hp": 0,  # Not available from log
            "max_hp": 0,
            "gold": self.gold,
            "act": self.act,
            "floor": self.floor,
            "run_time": 0,
            "deck": list(self.deck),
            "deck_upgrades": [False] * len(self.deck),
            "relics": list(self.relics),
            "potions": list(self.potions),
            "events_seen": list(self.events_seen),
            "encounters_won": list(self.encounters_won),
            "floors": [],
            "player_index": 0,
            "total_players": self.total_players,
            "cards_played": list(self.cards_played_by_player.get(who, []))
                            if who is not None else [],
            "extra_turns": self.extra_turns_by_player.get(who, 0)
                           if who is not None else 0,
            "elites_defeated": self.elites_defeated,
            "cards_played_by_player": {p: list(v) for p, v
                                       in self.cards_played_by_player.items()},
            "extra_turns_by_player": dict(self.extra_turns_by_player),
            "seed": self.seed,
            "ascension": self.ascension or 0,
            # None = the log never said; lets the live merge tell "unknown"
            # apart from a real ascension 0.
            "log_ascension": self.ascension,
        }


class LogTailer:
    """Tails the STS2 godot.log and maintains live run state."""

    def __init__(self, log_path: Path | None = None):
        self.path = log_path or _resolve_log_path()
        self.state = LogRunState()
        self._offset = 0
        self._last_size = 0
        self._identity = None
        self._pending = b""
        self._discard_line = False
        self._initialized = False

    def _read_lines(self, raw: bytes):
        raw = self._pending + raw
        parts = raw.split(b"\n")
        self._pending = parts.pop()
        # A malformed writer must not make a partial line grow indefinitely.
        if len(self._pending) > 65536:
            self._pending = b""
            self._discard_line = True
        if self._discard_line and parts:
            parts.pop(0)
            self._discard_line = False
        return [line.decode("utf-8", errors="replace") for line in parts]

    def _parse_initial(self):
        self.state.reset()
        self._pending = b""
        self._discard_line = False
        try:
            with open(self.path, "rb") as stream:
                import os
                stat = os.fstat(stream.fileno())
                self._identity = (stat.st_dev, stat.st_ino)
                start = max(0, stat.st_size - _INIT_TAIL_BYTES)
                stream.seek(start)
                self._discard_line = start > 0
                lines = self._read_lines(stream.read(_INIT_TAIL_BYTES))
                self._offset = stream.tell()
                self._last_size = self._offset
            for line in lines:
                self._process_line(line)
            self._initialized = True
        except OSError:
            log.debug("Failed to read log file", exc_info=True)

    def poll(self) -> dict | None:
        """Read complete byte-delimited lines; reset on replacement or truncation."""
        try:
            stat = self.path.stat()
        except OSError:
            was_active = self.state.active
            self.state.reset()
            self._initialized = False
            return self.state.to_dict() if was_active else None
        identity = (stat.st_dev, stat.st_ino)
        restart = (not self._initialized or identity != self._identity
                   or stat.st_size < self._offset
                   or stat.st_size - self._offset > _MAX_POLL_BYTES)
        if restart:
            was_active = self.state.active
            self._parse_initial()
            return self.state.to_dict() if was_active or self.state.active else None
        if stat.st_size == self._offset:
            return None
        changed = False
        try:
            with open(self.path, "rb") as stream:
                stream.seek(self._offset)
                lines = self._read_lines(stream.read(_MAX_POLL_BYTES))
                self._offset = stream.tell()
                self._last_size = self._offset
            for line in lines:
                changed = self._process_line(line) or changed
        except OSError:
            log.debug("Failed to read new log data", exc_info=True)
        return self.state.to_dict() if changed else None

    def _process_line(self, line: str) -> bool:
        """Process a single log line. Returns True if state changed."""
        if not line:
            return False

        # Run start detection
        m = _RE_LOCAL_READY.search(line)
        if m:
            self.state.reset()
            self.state.local_player = int(m.group(1))
            self.state.active = True
            self.state.run_started = True
            return True

        m = _RE_NEOW_EVENT.search(line)
        if m:
            self.state.active = True
            self.state.run_started = True
            self.state.events_seen.append("EVENT.NEOW")
            return True

        # Run embark: carries the seed and ascension that identify the run
        m = _RE_EMBARK.search(line)
        if m:
            if self.state.seed:
                self.state.reset()
            self.state.active = True
            self.state.run_started = True
            if m.group(1).lower() == "singleplayer":
                # Only unambiguous solo: in co-op whose character this names
                # has not been checked against a real log.
                char_id = "CHARACTER." + m.group(2)
                self.state.character = _CHAR_MAP.get(char_id, self.state.character)
            if m.group(3) is not None:
                self.state.ascension = int(m.group(3))
            if m.group(4):
                self.state.seed = m.group(4)
            return True

        # Character selection (during lobby)
        m = _RE_CHAR_SELECT.search(line)
        if m:
            char_id = m.group(1)
            self.state.character = _CHAR_MAP.get(char_id, char_id)
            return True

        # Client connected (co-op)
        if _RE_CLIENT_CONNECT.search(line):
            self.state.total_players = 2
            return True

        # Save file written (confirms active run + gives us save file data)
        m = _RE_WROTE_SAVE.search(line)
        if m:
            self.state.active = True
            return True

        # Floor movement
        m = _RE_MOVING.search(line)
        if m:
            act_idx = int(m.group(1))
            floor_in_act = int(m.group(2))
            self.state.act = act_idx + 1
            self.state.floor = floor_in_act + 1
            return True

        # Act completion
        m = _RE_EPOCH.search(line)
        if m:
            completed_act = int(m.group(1))
            self.state.act = completed_act + 1
            return True

        # Room type detection
        m = _RE_ROOM_PRELOAD.search(line)
        if m:
            return False  # Info only, no state change

        # Combat start
        m = _RE_COMBAT_START.search(line)
        if m:
            self.state.current_encounter = "ENCOUNTER." + m.group(1)
            return True

        # Won encounter
        m = _RE_WON_ENCOUNTER.search(line)
        if m:
            char_id = m.group(1)
            if not self.state.character:
                self.state.character = _CHAR_MAP.get(char_id, char_id)
            self.state.encounters_won.append(m.group(2))
            return True

        # Lost encounter (run over)
        m = _RE_LOST_ENCOUNTER.search(line)
        if m:
            char_id = m.group(1)
            if not self.state.character:
                self.state.character = _CHAR_MAP.get(char_id, char_id)
            return True

        # Card obtained
        m = _RE_OBTAINED_CARD.search(line)
        if m:
            self.state.deck.append(m.group(1))
            return True

        # Potion obtained
        m = _RE_OBTAINED_POTION.search(line)
        if m:
            self.state.potions.append(m.group(1))
            return True

        # Gold obtained
        m = _RE_OBTAINED_GOLD.search(line)
        if m:
            self.state.gold += int(m.group(1))
            return True

        # Potion used
        m = _RE_USED_POTION.search(line)
        if m:
            potion_id = "POTION." + m.group(1)
            if potion_id in self.state.potions:
                self.state.potions.remove(potion_id)
            return True

        # Potion discarded
        m = _RE_DISCARD_POTION.search(line)
        if m:
            potion_id = "POTION." + m.group(1)
            if potion_id in self.state.potions:
                self.state.potions.remove(potion_id)
            return True

        # Run ended — saved to history
        m = _RE_SAVED_HISTORY.search(line)
        if m:
            self.state.active = False
            return True

        # Run ended — lobby disconnect
        m = _RE_LOBBY_DISCONNECT.search(line)
        if m and m.group(1) == "QuitGameOver":
            self.state.active = False
            return True

        # Card played in combat
        m = _RE_PLAYING_CARD.search(line)
        if m:
            player = int(m.group(1))
            played = self.state.cards_played_by_player.setdefault(player, [])
            card_id = m.group(2)
            # Everything else in the app keys cards as CARD.X; the log omits it.
            if not card_id.startswith("CARD."):
                card_id = "CARD." + card_id
            played.append(card_id)
            # Cap each list to prevent unbounded growth on long runs.
            if len(played) > self.state._cards_played_cap:
                del played[:-self.state._cards_played_cap]
            return True

        # Extra turn triggered (Regent / Heel / etc.)
        m = _RE_EXTRA_TURN.search(line)
        if m:
            player = int(m.group(1))
            self.state.extra_turns_by_player[player] = (
                self.state.extra_turns_by_player.get(player, 0) + 1)
            return True

        # Elites defeated counter — game emits cumulative count
        m = _RE_ELITES_DEFEATED.search(line)
        if m:
            self.state.elites_defeated = int(m.group(1))
            return True

        return False
