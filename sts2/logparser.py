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
    _LOG_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "SlayTheSpire2" / "logs"

LOG_FILE = _LOG_DIR / "godot.log"

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
_RE_MOVING = re.compile(r"\[DEBUG\] \[MapSelectionSynchronizer\] Moving to coordinate MapCoord \((\d+), (\d+)\)")
_RE_ROOM_PRELOAD = re.compile(r"\[INFO\] Preloading '(.+?)' assets")
_RE_EPOCH = re.compile(r"\[INFO\] Epoch obtained for completing Act (\d+)")
_RE_CHAR_SELECT = re.compile(r"Received LobbyPlayerChangedCharacterMessage for \d+ (CHARACTER\.\w+)")
_RE_LOCAL_READY = re.compile(r"\[INFO\] \[StartRunLobby.*?\] Local player (\d+) is ready")
_RE_CLIENT_CONNECT = re.compile(r"\[INFO\] \[StartRunLobby.*?\] Client (\d+) connected")
_RE_NEOW_EVENT = re.compile(r"\[VERYDEBUG\] \[EventSynchronizer\] Event EVENT\.NEOW began for player (\d+)")

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

    def __init__(self):
        self.reset()

    def reset(self):
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

    def to_dict(self) -> dict:
        """Convert to dict compatible with CurrentRun.model_dump()."""
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
        }


class LogTailer:
    """Tails the STS2 godot.log and maintains live run state."""

    def __init__(self, log_path: Path | None = None):
        self.path = log_path or LOG_FILE
        self.state = LogRunState()
        self._offset = 0
        self._last_size = 0
        self._initialized = False

    def _parse_initial(self):
        """Parse the entire log file to build initial state."""
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            self._offset = self.path.stat().st_size
            self._last_size = self._offset

            # Find the LAST run start (work backwards to find it)
            last_run_start = -1
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i]
                if "Wrote" in line and "current_run" in line and ".save " in line:
                    # Find the first save write of this run
                    last_run_start = i
                    # Keep going back to find the true start
                    continue
                if "[StartRunLobby" in line and "Local player" in line:
                    last_run_start = i
                    break
                if "Saved run history" in line and last_run_start > i:
                    # There was a run end after i, so last_run_start is correct
                    break

            if last_run_start < 0:
                return

            # Check if the run ended after last_run_start
            run_ended = False
            for i in range(last_run_start, len(lines)):
                if "Saved run history" in lines[i]:
                    run_ended = True
                if "QuitGameOver" in lines[i]:
                    run_ended = True

            if run_ended:
                # No active run
                return

            # Parse from last_run_start to build state
            self.state.reset()
            for i in range(last_run_start, len(lines)):
                self._process_line(lines[i])

            self._initialized = True
        except OSError:
            log.debug("Failed to read log file", exc_info=True)

    def poll(self) -> dict | None:
        """Check for new log data. Returns updated state dict or None if unchanged.

        Call this periodically (e.g. every 2-5 seconds).
        """
        if not self.path.exists():
            return None

        if not self._initialized:
            self._parse_initial()
            self._initialized = True
            if self.state.active:
                return self.state.to_dict()
            return None

        try:
            current_size = self.path.stat().st_size
        except OSError:
            return None

        if current_size == self._last_size:
            return None  # No new data

        if current_size < self._last_size:
            # Log was rotated/truncated — re-parse from scratch
            self._initialized = False
            self._offset = 0
            self._last_size = 0
            return self.poll()

        changed = False
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                new_data = f.read()
                self._offset = f.tell()
            self._last_size = current_size

            for line in new_data.splitlines():
                if self._process_line(line):
                    changed = True
        except OSError:
            log.debug("Failed to read new log data", exc_info=True)
            return None

        if changed and self.state.active:
            return self.state.to_dict()
        return None

    def _process_line(self, line: str) -> bool:
        """Process a single log line. Returns True if state changed."""
        if not line:
            return False

        # Run start detection
        m = _RE_LOCAL_READY.search(line)
        if m:
            self.state.reset()
            self.state.active = True
            self.state.run_started = True
            return True

        m = _RE_NEOW_EVENT.search(line)
        if m:
            self.state.active = True
            self.state.run_started = True
            self.state.events_seen.append("EVENT.NEOW")
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

        return False
