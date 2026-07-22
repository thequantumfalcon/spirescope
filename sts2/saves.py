"""Save file reader for STS2 progress, run history, and current run."""
import hashlib
import json
import logging
from pathlib import Path

from sts2.config import CHARACTER_IDS, SAVE_DIR, SAVE_DIRS
from sts2.models import CurrentRun, PlayerProgress, RunFloor, RunHistory

log = logging.getLogger(__name__)


def _save_origin(save_dir: Path) -> str:
    """Which save tree a directory belongs to: 'modded' or 'vanilla'."""
    return "modded" if "modded" in save_dir.parts else "vanilla"


def _history_search_dirs() -> list[tuple[Path, str]]:
    """(save_dir, origin) pairs to merge run history from, freshest first.

    When SAVE_DIR has been repointed (tests patch it; SAVE_DIRS untouched),
    honor it alone to preserve single-dir semantics.
    """
    dirs = SAVE_DIRS if SAVE_DIRS and SAVE_DIRS[0] == SAVE_DIR else [SAVE_DIR]
    return [(d, _save_origin(d)) for d in dirs]


def _read_json(path: Path) -> dict | None:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to read %s: %s", path, e)
    return None


def _get_player(players: list[dict], index: int = 0) -> dict:
    """Get a player by index from the player list. Falls back to first player."""
    if not players:
        return {}
    if 0 <= index < len(players):
        return players[index]
    return players[0]


def _get_player_stats(player_stats: list[dict], player: dict) -> dict:
    """Find matching player stats for a floor. Returns {} when no match — co-op
    runs must not cross-contaminate by returning the wrong player's stats."""
    player_id = str(player.get("id", ""))
    for ps in player_stats:
        if str(ps.get("player_id", "")) == player_id:
            return ps
    return {}


def get_current_run(player_index: int = 0) -> CurrentRun:
    """Read the current active run, if any. Use player_index for co-op."""
    # Prefer live save files; fall back to backups (picking most recent)
    data = None
    for fname in ("current_run.save", "current_run_mp.save"):
        data = _read_json(SAVE_DIR / fname)
        if data:
            break

    if not data:
        # No live file — check backups, pick the most recently saved.
        # Only use a backup if the run hasn't already finished (i.e. its
        # start_time doesn't appear as a history file).
        history_dir = SAVE_DIR / "history"
        history_starts: set[str] = set()
        if history_dir.exists():
            history_starts = {p.stem for p in history_dir.iterdir() if p.suffix == ".run"}
        best, best_time = None, 0
        for fname in ("current_run.save.backup", "current_run_mp.save.backup"):
            candidate = _read_json(SAVE_DIR / fname)
            if not candidate:
                continue
            start = str(candidate.get("start_time", ""))
            if start in history_starts:
                continue  # This run already finished
            try:
                save_time = int(candidate.get("save_time") or 0)
            except (TypeError, ValueError):
                save_time = 0
            if save_time > best_time:
                best = candidate
                best_time = save_time
        if best:
            data = best

    if not data:
        return CurrentRun(active=False)

    players = data.get("players", [])
    total_players = len(players)
    player = _get_player(players, player_index)
    character = CHARACTER_IDS.get(
        player.get("character_id", player.get("character", "")),
        player.get("character_id", "Unknown"),
    )
    # Filter empty IDs: malformed entries would pollute analytics with "" keys.
    deck_entries = [c for c in player.get("deck", []) if c.get("id")]
    deck = [c.get("id", "") for c in deck_entries]
    deck_upgrades = [(c.get("upgrade_count") or 0) > 0 for c in deck_entries]
    deck_enchantments = [
        (c.get("enchantment") or {}).get("id", "") for c in deck_entries
    ]
    relics = [r.get("id", "") for r in player.get("relics", []) if r.get("id")]
    potions = [p.get("id", "") for p in player.get("potions", []) if p.get("id")]

    # Parse floor history
    floors = []
    floor_num = 0
    for act_floors in data.get("map_point_history", []):
        for floor_data in act_floors:
            floor_num += 1
            rooms = floor_data.get("rooms", [])
            room = rooms[0] if rooms else {}
            p_stats = _get_player_stats(
                floor_data.get("player_stats", []), player
            )
            card_picked = ""
            for cc in p_stats.get("card_choices", []):
                if cc.get("was_picked"):
                    card_picked = cc.get("card", {}).get("id", "")
            floors.append(RunFloor(
                floor=floor_num,
                type=floor_data.get("map_point_type", room.get("room_type", "")),
                encounter=room.get("model_id", ""),
                monsters=room.get("monster_ids", []),
                turns=room.get("turns_taken", 0),
                damage_taken=p_stats.get("damage_taken", 0),
                hp_healed=p_stats.get("hp_healed", 0),
                current_hp=p_stats.get("current_hp", 0),
                max_hp=p_stats.get("max_hp", 0),
                gold=p_stats.get("current_gold", 0),
                card_picked=card_picked,
            ))

    return CurrentRun(
        active=True,
        character=character,
        current_hp=player.get("current_hp", 0),
        max_hp=player.get("max_hp", 0),
        gold=player.get("gold", 0),
        act=(data.get("current_act_index") or 0) + 1,
        floor=floor_num,
        run_time=data.get("run_time", 0),
        deck=deck,
        deck_upgrades=deck_upgrades,
        deck_enchantments=deck_enchantments,
        relics=relics,
        potions=potions,
        events_seen=data.get("events_seen", []),
        floors=floors,
        player_index=player_index,
        total_players=total_players,
    )


def get_progress() -> PlayerProgress | None:
    """Read player progress from progress.save."""
    data = _read_json(SAVE_DIR / "progress.save")
    if not data:
        return None

    char_stats = {}
    badges: dict[str, dict[str, int]] = {}
    for cs in data.get("character_stats", []):
        # Badges are stored per character; aggregate by badge id and tier
        for b in cs.get("badges", []):
            bid = b.get("id", "")
            rarity = b.get("rarity", "")
            if bid and rarity:
                tiers = badges.setdefault(bid, {})
                tiers[rarity] = tiers.get(rarity, 0) + (b.get("count") or 1)
        char_name = CHARACTER_IDS.get(cs.get("id", ""), cs.get("id", ""))
        char_stats[char_name] = {
            "wins": cs.get("total_wins", 0),
            "losses": cs.get("total_losses", 0),
            "playtime": cs.get("playtime", 0),
            "max_ascension": cs.get("max_ascension", 0),
            "best_streak": cs.get("best_win_streak", 0),
            "current_streak": cs.get("current_streak", 0),
            "fastest_win": cs.get("fastest_win_time", -1),
        }

    card_stats = {}
    for cs in data.get("card_stats", []):
        cid = cs.get("id", "")
        if not cid:
            continue  # malformed save entry — skip rather than collapse into ""
        card_stats[cid] = {
            "picked": cs.get("times_picked", 0),
            "skipped": cs.get("times_skipped", 0),
            "won": cs.get("times_won", 0),
            "lost": cs.get("times_lost", 0),
        }

    encounter_stats = {}
    for es in data.get("encounter_stats", []):
        enc_id = es.get("encounter_id", "")
        if not enc_id:
            continue  # skip empty IDs
        encounter_stats[enc_id] = {}
        for fs in es.get("fight_stats", []):
            char_name = CHARACTER_IDS.get(fs.get("character", ""), fs.get("character", ""))
            encounter_stats[enc_id][char_name] = {
                "wins": fs.get("wins", 0),
                "losses": fs.get("losses", 0),
            }

    # Enemy stats (per-monster win/loss by character)
    enemy_stats = {}
    for es in data.get("enemy_stats", []):
        enemy_id = es.get("enemy_id", "")
        if not enemy_id:
            continue  # malformed entry — skip rather than create enemy_stats[""]
        enemy_stats[enemy_id] = {}
        for fs in es.get("fight_stats", []):
            char_name = CHARACTER_IDS.get(fs.get("character", ""), fs.get("character", ""))
            enemy_stats[enemy_id][char_name] = {
                "wins": fs.get("wins", 0),
                "losses": fs.get("losses", 0),
            }

    return PlayerProgress(
        total_playtime=data.get("total_playtime", 0),
        character_stats=char_stats,
        badges=badges,
        card_stats=card_stats,
        encounter_stats=encounter_stats,
        enemy_stats=enemy_stats,
        # Filter empties — malformed save entries would create phantom Card/
        # Relic/Potion/Event records with id="" that pollute search + analytics.
        discovered_cards=[i for i in data.get("discovered_cards", []) if i],
        discovered_relics=[i for i in data.get("discovered_relics", []) if i],
        discovered_potions=[i for i in data.get("discovered_potions", []) if i],
        discovered_events=[i for i in data.get("discovered_events", []) if i],
        epochs=[
            {"id": e.get("id", ""), "state": e.get("state", "not_obtained"),
             "obtain_date": e.get("obtain_date", 0)}
            for e in data.get("epochs", [])
        ],
    )


def get_run_history() -> list[RunHistory]:
    """Read all completed run history files, merged across save trees.

    Since game v0.108.0 a first modded launch copies vanilla saves into the
    modded tree, so the same run file (same stem, same bytes) can exist in
    both — those collapse to one run. Same stem with different bytes (rare
    divergent edit) keeps both, disambiguated as "<stem>@<origin>".
    """
    entries: list[tuple[Path, str, str]] = []  # (run_file, run_id, origin)
    first_digest: dict[str, str] = {}  # stem -> sha256 of first-seen file
    used_ids: set[str] = set()
    for save_dir, origin in _history_search_dirs():
        history_dir = save_dir / "history"
        if not history_dir.exists():
            continue
        for run_file in history_dir.glob("*.run"):
            try:
                digest = hashlib.sha256(run_file.read_bytes()).hexdigest()
            except OSError as e:
                log.warning("Failed to read run file %s: %s", run_file.name, e)
                continue
            stem = run_file.stem
            if stem not in first_digest:
                first_digest[stem] = digest
                run_id = stem
            elif first_digest[stem] == digest:
                continue  # identical copy in the other tree — one run
            else:
                run_id = f"{stem}@{origin}"
                while run_id in used_ids:
                    run_id += "+"
                log.warning(
                    "Run %s diverged between save trees; keeping both (id %s)",
                    stem, run_id,
                )
            used_ids.add(run_id)
            entries.append((run_file, run_id, origin))

    runs = []
    for run_file, run_id, origin in sorted(
        entries, key=lambda e: e[0].name, reverse=True
    ):
        try:
            data = _read_json(run_file)
            if not data:
                continue

            players = data.get("players", [])
            player = _get_player(players)

            # History files use "character"; current_run files use "character_id".
            # Try both to keep per-character analytics consistent across both.
            char_key = player.get("character_id") or player.get("character", "")
            character = CHARACTER_IDS.get(char_key, char_key or "Unknown")
            deck = [c.get("id", "") for c in player.get("deck", []) if c.get("id")]
            enchantments = {
                c["id"]: (c.get("enchantment") or {}).get("id", "")
                for c in player.get("deck", [])
                if c.get("id") and (c.get("enchantment") or {}).get("id")
            }
            relics = [r.get("id", "") for r in player.get("relics", []) if r.get("id")]

            # Parse floor history
            floors = []
            floor_num = 0
            for act_floors in data.get("map_point_history", []):
                for floor_data in act_floors:
                    floor_num += 1
                    rooms = floor_data.get("rooms", [])
                    room = rooms[0] if rooms else {}

                    p_stats = _get_player_stats(
                        floor_data.get("player_stats", []), player
                    )

                    card_picked = ""
                    cards_offered = []
                    for cc in p_stats.get("card_choices", []):
                        card_info = cc.get("card", {})
                        cid = card_info.get("id", "")
                        if not cid:
                            continue  # skip empty IDs — they pollute pick-rate counters
                        cards_offered.append(cid)
                        if cc.get("was_picked"):
                            card_picked = cid

                    floors.append(RunFloor(
                        floor=floor_num,
                        type=floor_data.get("map_point_type", room.get("room_type", "")),
                        encounter=room.get("model_id", ""),
                        monsters=room.get("monster_ids", []),
                        turns=room.get("turns_taken", 0),
                        damage_taken=p_stats.get("damage_taken", 0),
                        hp_healed=p_stats.get("hp_healed", 0),
                        current_hp=p_stats.get("current_hp", 0),
                        max_hp=p_stats.get("max_hp", 0),
                        gold=p_stats.get("current_gold", 0),
                        cards_offered=cards_offered,
                        card_picked=card_picked,
                        potions_used=[p for p in p_stats.get("potion_used", []) if p],
                        potions_gained=[p.get("choice", "") for p in p_stats.get("potion_choices", []) if p.get("was_picked") and p.get("choice")],
                    ))

            # Timestamp: prefer start_time from data, fallback to filename
            timestamp = data.get("start_time", 0)
            if not timestamp:
                try:
                    timestamp = int(run_file.stem)
                except (ValueError, TypeError):
                    timestamp = 0

            runs.append(RunHistory(
                id=run_id,
                character=character,
                win=data.get("win", False),
                ascension=data.get("ascension", 0),
                seed=data.get("seed", ""),
                acts=data.get("acts", []),
                killed_by=data.get("killed_by_encounter", ""),
                run_time=data.get("run_time", 0),
                deck=deck,
                relics=relics,
                floors=floors,
                build_id=data.get("build_id", ""),
                timestamp=timestamp,
                total_players=len(players),
                origin=origin,
                enchantments=enchantments,
            ))
        except Exception as e:
            log.warning("Failed to parse run file %s: %s", run_file.name, e)

    return runs
