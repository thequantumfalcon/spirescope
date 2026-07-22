"""Fix card rarity data using authoritative wiki.gg Lua module data.

Usage: python scripts/fix_card_rarity.py [--dry-run]
"""
import json
import sys
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "sts2" / "data" / "cards.json"

# Authoritative rarity data from slaythespire.wiki.gg/wiki/Module:Cards/StS2_data/*
# Wiki uses "Basic" which we map to "Starter"
RARITY_MAP: dict[tuple[str, str], str] = {}

def _add(char: str, names: list[str], rarity: str):
    for n in names:
        RARITY_MAP[(char, n)] = rarity

# ── IRONCLAD ──
_add("Ironclad", ["Strike", "Defend", "Bash"], "Starter")
_add("Ironclad", [
    "Anger", "Armaments", "Blood Wall", "Body Slam",
    "Breakthrough", "Cinder", "Havoc", "Headbutt", "Iron Wave",
    "Molten Fist", "Perfected Strike", "Pommel Strike", "Setup Strike",
    "Shrug It Off", "Sword Boomerang", "Thunderclap", "Tremble",
    "True Grit", "Twin Strike",
], "Common")
_add("Ironclad", [
    "Ashen Strike", "Battle Trance", "Bludgeon", "Bully", "Burning Pact",
    "Demonic Shield", "Dismantle", "Drum of Battle", "Evil Eye",
    "Expect a Fight", "Feel No Pain", "Fight Me!", "Flame Barrier",
    "Forgotten Ritual", "Grapple", "Hemokinesis", "Howl from Beyond",
    "Infernal Blade", "Inferno", "Inflame", "Juggling", "Pillage", "Rage",
    "Rampage", "Rupture", "Second Wind", "Spite", "Stampede", "Stomp",
    "Stone Armor", "Unrelenting", "Uppercut", "Vicious", "Whirlwind",
], "Uncommon")
_add("Ironclad", [
    "Aggression", "Barricade", "Brand", "Cascade", "Colossus",
    "Conflagration", "Crimson Mantle", "Dark Embrace",
    "Demon Form", "Feed", "Fiend Fire", "Hellraiser", "Impervious",
    "Juggernaut", "Mangle", "Offering", "One-Two Punch", "Pact's End",
    "Primal Force", "Pyre", "Stoke", "Tank", "Tear Asunder", "Thrash",
    "Unmovable",
], "Rare")
_add("Ironclad", ["Break", "Corruption"], "Ancient")
# v0.109.0 rarity changes (wiki Lua module still stale)
_add("Ironclad", ["Taunt"], "Common")
_add("Ironclad", ["Bloodletting", "Cruelty"], "Uncommon")
_add("Ironclad", ["Dominate"], "Rare")

# ── SILENT ──
_add("Silent", ["Strike", "Defend", "Neutralize", "Survivor"], "Starter")
_add("Silent", [
    "Acrobatics", "Anticipate", "Backflip", "Blade Dance",
    "Cloak and Dagger", "Dagger Spray", "Dagger Throw", "Deadly Poison",
    "Deflect", "Dodge and Roll", "Flick-Flack", "Leading Strike",
    "Piercing Wail", "Poisoned Stab", "Prepared", "Ricochet", "Slice",
    "Snakebite", "Sucker Punch", "Untouchable",
], "Common")
_add("Silent", [
    "Accuracy", "Backstab", "Blur", "Bouncing Flask", "Bubble Bubble",
    "Calculated Gamble", "Dash", "Escape Plan", "Expertise", "Expose",
    "Finisher", "Flechettes", "Footwork",
    "Hand Trick", "Haze", "Hidden Daggers", "Infinite Blades", "Leg Sweep",
    "Memento Mori", "Mirage", "Noxious Fumes", "Outbreak", "Phantom Blades",
    "Pinpoint", "Pounce", "Precise Cut", "Reflex", "Skewer",
    "Speedster", "Strangle", "Tactician", "Up My Sleeve",
], "Uncommon")
# Predator moved Uncommon -> Common in v0.106.0 (wiki Lua module still stale)
_add("Silent", ["Predator"], "Common")
_add("Silent", [
    "Abrasive", "Adrenaline", "Afterimage", "Assassinate",
    "Blade of Ink", "Bullet Time", "Burst", "Corrosive Wave", "Echoing Slash",
    "Envenom", "Fan of Knives", "Grand Finale", "Knife Trap", "Malaise",
    "Master Planner", "Murder", "Nightmare", "Serpent Form", "Shadow Step",
    "Shadowmeld", "Sneaky", "Storm of Steel", "The Hunt",
    "Tools of the Trade", "Tracking",
], "Rare")
_add("Silent", ["Suppress", "Wraith Form"], "Ancient")
# Patch overrides: Scare (renamed from Follow Through, v0.107.1);
# Flanking Uncommon -> Rare (v0.108.0); Accelerant Rare -> Uncommon and
# Well-Laid Plans Uncommon -> Rare (v0.109.0)
_add("Silent", ["Scare", "Accelerant"], "Uncommon")
_add("Silent", ["Flanking", "Well-Laid Plans"], "Rare")

# ── DEFECT ──
_add("Defect", ["Strike", "Defend", "Dualcast", "Zap"], "Starter")
_add("Defect", [
    "Ball Lightning", "Barrage", "Beam Cell", "Boost Away", "Charge Battery",
    "Claw", "Cold Snap", "Compile Driver", "Coolheaded", "Focused Strike",
    "Go for the Eyes", "Gunk Up", "Hologram", "Hotfix", "Leap",
    "Lightning Rod", "Momentum Strike", "Sweeping Beam", "TURBO", "Uproar",
], "Common")
_add("Defect", [
    "Boot Sequence", "Bulk Up", "Capacitor", "Chaos", "Chill", "Compact",
    "Darkness", "Double Energy", "Energy Surge", "FTL", "Feral",
    "Fight Through", "Fusion", "Glacier", "Glasswork", "Hailstorm",
    "Iteration", "Loop", "Null", "Overclock", "Refract", "Rip and Tear",
    "Rocket Punch", "Scavenge", "Scrape", "Shadow Shield", "Skim",
    "Smokestack", "Storm", "Subroutine", "Sunder", "Synchronize",
    "Synthesis", "Tempest", "Tesla Coil", "Thunder", "White Noise",
], "Uncommon")
_add("Defect", [
    "Adaptive Strike", "All for One", "Buffer", "Consuming Shadow", "Coolant",
    "Creative AI", "Defragment", "Echo Form", "Flak Cannon",
    "Genetic Algorithm", "Helix Drill", "Hyperbeam", "Ice Lance",
    "Machine Learning", "Meteor Strike", "Modded", "Multi-Cast", "Rainbow",
    "Reboot", "Shatter", "Signal Boost", "Spinner", "Supercritical",
    "Trash to Treasure", "Voltaic",
], "Rare")
_add("Defect", ["Biased Cognition", "Quadcast"], "Ancient")
# Ignition Rare -> Uncommon in v0.108.0
_add("Defect", ["Ignition"], "Uncommon")

# ── NECROBINDER ──
_add("Necrobinder", ["Strike", "Defend", "Bodyguard", "Unleash"], "Starter")
_add("Necrobinder", [
    "Afterlife", "Blight Strike", "Defile", "Defy", "Drain Power", "Fear",
    "Flatten", "Grave Warden", "Graveblast", "Invoke", "Negative Pulse",
    "Poke", "Pull Aggro", "Reap", "Reave", "Scourge", "Sculpting Strike",
    "Snap", "Sow", "Wisp",
], "Common")
_add("Necrobinder", [
    "Bone Shards", "Borrowed Time", "Bury", "Calcify", "Capture Spirit",
    "Cleanse", "Countdown", "Danse Macabre", "Death March", "Death's Door",
    "Deathbringer", "Debilitate", "Delay", "Dirge", "Dredge",
    "Enfeebling Touch", "Fetch", "Friendship", "Haunt", "High Five",
    "Legion of Bone", "Lethality", "Melancholy", "No Escape", "Pagestorm",
    "Parse", "Pull from Below", "Putrefy", "Rattle", "Right Hand Hand",
    "Severance", "Shroud", "Sic 'Em", "Sleight of Flesh", "Spur",
    "Veilpiercer",
], "Uncommon")
_add("Necrobinder", [
    "Banshee's Cry", "Call of the Void", "Demesne", "Devour Life", "Eidolon",
    "End of Days", "Eradicate", "Glimpse Beyond", "Hang", "Misery",
    "Necro Mastery", "Neurosurge", "Oblivion", "Reanimate", "Reaper Form",
    "Sacrifice", "Seance", "Sentry Mode", "Shared Fate", "Soul Storm",
    "Spirit of Ash", "Squeeze", "The Scythe", "Time's Up", "Transfigure",
    "Undeath",
], "Rare")
_add("Necrobinder", ["Forbidden Grimoire", "Protector"], "Ancient")

# ── REGENT ──
_add("Regent", ["Strike", "Defend", "Falling Star", "Venerate"], "Starter")
_add("Regent", [
    "Astral Pulse", "BEGONE!", "Celestial Might", "Cloak of Stars",
    "Collision Course", "Cosmic Indifference", "Crescent Spear", "Crush Under",
    "Gather Light", "Glitterstream", "Glow", "Guiding Star", "Hidden Cache",
], "Common")
_add("Regent", [
    "Alignment", "Black Hole", "Bulwark", "CHARGE!!", "Child of the Stars",
    "Conqueror", "Convergence", "Devastate", "Furnace", "Gamma Blast",
    "Glimmer", "Hegemony", "Kingly Kick", "Kingly Punch", "Knockout Blow",
    "Largesse", "Lunar Blast", "Manifest Authority", "Monologue", "Orbit",
    "Pale Blue Dot", "Parry", "Particle Wall", "Pillar of Creation",
    "Prophesize", "Quasar", "Radiate", "Reflect", "Resonance", "Royal Gamble",
    "Shining Strike", "Spectrum Shift", "Stardust", "Summon Forth",
    "Supermassive", "Terraforming",
], "Uncommon")
_add("Regent", [
    "Arsenal", "Beat into Shape", "Big Bang", "Bombardment", "Bundle of Joy",
    "Comet", "Crash Landing", "Decisions, Decisions", "Dying Star",
    "Foregone Conclusion", "GUARDS!!!", "Genesis", "Hammer Time",
    "Heavenly Drill", "Heirloom Hammer", "I Am Invincible", "Make It So",
    "Monarch's Gaze", "Neutron Aegis", "Royalties", "Seeking Edge",
    "Seven Stars", "Sword Sage", "The Smith", "Tyranny", "Void Form",
], "Rare")
_add("Regent", ["Meteor Shower", "The Sealed Throne"], "Ancient")

# ── COLORLESS ──
_add("Colorless", [
    "Automation", "Believe in You", "Catastrophe", "Coordinate",
    "Dark Shackles", "Discovery", "Dramatic Entrance", "Equilibrium",
    "Fasten", "Finesse", "Fisticuffs", "Flash of Steel", "Gang Up",
    "Huddle Up", "Impatience", "Intercept", "Jack of All Trades", "Lift",
    "Mind Blast", "Omnislice", "Panache", "Panic Button", "Prep Time",
    "Production", "Prolong", "Prowess", "Purity", "Restlessness",
    "Seeker Strike", "Shockwave", "Splash", "Stratagem", "Tag Team",
    "The Bomb", "Thinking Ahead", "Thrumming Hatchet", "Ultimate Defend",
    "Ultimate Strike", "Volley",
], "Uncommon")
_add("Colorless", [
    "Alchemize", "Anointed", "Beacon of Hope", "Beat Down", "Bolas",
    "Calamity", "Entropy", "Eternal Armor", "Gold Axe", "Hand of Greed",
    "Hidden Gem", "Jackpot", "Knockdown", "Master of Strategy", "Mayhem",
    "Mimic", "Nostalgia", "Rally", "Rend", "Rolling Boulder", "Salvo",
    "Scrawl", "Secret Technique", "Secret Weapon", "The Gambit",
], "Rare")
_add("Colorless", [
    "Apotheosis", "Apparition", "Brightest Flame", "Maul", "Neow's Fury",
    "Relax", "Whistle", "Wish",
], "Ancient")

# ── COLORLESS SPECIAL CATEGORIES ──
# These are separate card categories that happen to be in the Colorless module
STATUS_CARDS = {
    "Beckon", "Burn", "Dazed", "Debris", "Disintegration", "Frantic Escape",
    "Infection", "Mind Rot", "Slimed", "Sloth", "Soot", "Toxic", "Void",
    "Waste Away", "Wither", "Wound",
}
CURSE_CARDS = {
    "Ascender's Bane", "Bad Luck", "Clumsy", "Curse of the Bell", "Debt",
    "Decay", "Doubt", "Enthralled", "Folly", "Greed", "Guilty", "Injury",
    "Normality", "Poor Sleep", "Regret", "Shame", "Spore Mind", "Writhe",
}
EVENT_CARDS = {
    "Byrd Swoop", "Enlightenment", "Exterminate", "Feeding Frenzy",
    "Metamorphosis", "Mad Science", "Peck", "Squash", "Toric Toughness",
}
QUEST_CARDS = {"Byrdonis Egg", "Lantern Key", "Spoils Map"}
TOKEN_CARDS = {
    "Fuel", "Giant Rock", "Luminesce", "Minion Dive Bomb", "Minion Sacrifice",
    "Minion Strike", "Shiv", "Soul", "Sovereign Blade", "Sweeping Gaze",
}

# Event cards from character modules (separate IDs with _EVENT suffix)
IRONCLAD_EVENTS = {"Clash", "Dual Wield", "Entrench"}
SILENT_EVENTS = {"Caltrops", "Distraction", "Outmaneuver"}
DEFECT_EVENTS = {"Hello World", "Rebound", "Stack"}

# Name fixes: our name -> canon name
NAME_FIXES = {
    ("Defect", "All For One"): "All for One",
}

# Character reassignments: (current_char, name) -> new_char
# Brightest Flame is Colorless Ancient in wiki, but Ironclad Uncommon in ours
CHAR_FIXES = {
    ("Ironclad", "Brightest Flame"): "Colorless",
}

# Cards in our data not in wiki — keep their current rarity if it looks correct,
# or leave as-is since they may be newer game content not yet documented
NOT_IN_WIKI_OK = {
    "Despair", "Impale", "Pael's Strike", "Sharp Edge",  # Colorless
    "Charge",  # Ironclad
    "Know Thy Place", "Patter", "Photon Cut", "Refine Blade",  # Regent
    "Solar Strike", "Spoils of Battle", "Wrought in War",  # Regent
}


def main(dry_run: bool | None = None):
    if dry_run is None:
        dry_run = "--dry-run" in sys.argv

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        cards = json.load(f)

    changes = []
    not_found = []
    deprecated_removed = False

    new_cards = []
    for card in cards:
        char = card["character"]
        name = card["name"]

        # Remove Deprecated Card and entries renamed away by patches
        # (Follow Through -> Scare in v0.107.1; the old row lingers via
        # merge). "Prepare" (Silent) is absent from both data sources —
        # removed from the game; distinct from "Prepared".
        if name in ("Deprecated Card", "Follow Through", "Prepare"):
            changes.append(f"REMOVED: {name} ({card['id']})")
            deprecated_removed = True
            continue

        # Fix character reassignments
        char_key = (char, name)
        if char_key in CHAR_FIXES:
            new_char = CHAR_FIXES[char_key]
            changes.append(f"CHAR: {char}/{name} -> {new_char}")
            card["character"] = new_char
            char = new_char

        # Fix card names
        name_key = (char, name)
        if name_key in NAME_FIXES:
            new_name = NAME_FIXES[name_key]
            changes.append(f"NAME: {char}/{name} -> {new_name}")
            card["name"] = new_name
            name = new_name

        key = (char, name)
        if key in RARITY_MAP:
            new_rarity = RARITY_MAP[key]
            if card["rarity"] != new_rarity:
                changes.append(
                    f"RARITY: {char}/{name}: {card['rarity']!r} -> {new_rarity!r}"
                )
                card["rarity"] = new_rarity
        elif char == "Colorless":
            # Fix character assignment for Colorless cards that belong to
            # special categories (Status, Curse, Event, Quest, Token)
            if name in STATUS_CARDS:
                new_rarity = "Status"
                if card["rarity"] != new_rarity:
                    changes.append(f"RARITY: Colorless/{name}: {card['rarity']!r} -> {new_rarity!r}")
                    card["rarity"] = new_rarity
            elif name in CURSE_CARDS:
                new_rarity = "Curse"
                if card["rarity"] != new_rarity:
                    changes.append(f"RARITY: Colorless/{name}: {card['rarity']!r} -> {new_rarity!r}")
                    card["rarity"] = new_rarity
            elif name in EVENT_CARDS:
                new_rarity = "Event"
                if card["rarity"] != new_rarity:
                    changes.append(f"RARITY: Colorless/{name}: {card['rarity']!r} -> {new_rarity!r}")
                    card["rarity"] = new_rarity
            elif name in QUEST_CARDS:
                new_rarity = "Quest"
                if card["rarity"] != new_rarity:
                    changes.append(f"RARITY: Colorless/{name}: {card['rarity']!r} -> {new_rarity!r}")
                    card["rarity"] = new_rarity
            elif name in TOKEN_CARDS:
                new_rarity = "Token"
                if card["rarity"] != new_rarity:
                    changes.append(f"RARITY: Colorless/{name}: {card['rarity']!r} -> {new_rarity!r}")
                    card["rarity"] = new_rarity
            else:
                not_found.append(f"{char}/{name}")
        elif char == "Event":
            # Event copies of character cards — set rarity to Event
            if card["rarity"] != "Event":
                changes.append(f"RARITY: Event/{name}: {card['rarity']!r} -> 'Event'")
                card["rarity"] = "Event"
        elif char == "Token":
            if card["rarity"] != "Token":
                changes.append(f"RARITY: Token/{name}: {card['rarity']!r} -> 'Token'")
                card["rarity"] = "Token"
        elif char == "Quest":
            if card["rarity"] != "Quest":
                changes.append(f"RARITY: Quest/{name}: {card['rarity']!r} -> 'Quest'")
                card["rarity"] = "Quest"
        elif char == "Status":
            if card["rarity"] != "Status":
                changes.append(f"RARITY: Status/{name}: {card['rarity']!r} -> 'Status'")
                card["rarity"] = "Status"
        elif char == "Curse":
            if card["rarity"] != "Curse":
                changes.append(f"RARITY: Curse/{name}: {card['rarity']!r} -> 'Curse'")
                card["rarity"] = "Curse"
        else:
            not_found.append(f"{char}/{name}")

        new_cards.append(card)

    print(f"Total changes: {len(changes)}")
    print(f"Deprecated removed: {deprecated_removed}")
    print(f"Cards not in wiki: {len(not_found)}")
    for nf in not_found:
        print(f"  NOT FOUND: {nf}")
    print()
    for c in changes:
        print(f"  {c}")

    if not dry_run and changes:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(new_cards, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {len(new_cards)} cards to {DATA_FILE}")
    elif dry_run:
        print(f"\nDRY RUN — no changes written ({len(new_cards)} cards)")


if __name__ == "__main__":
    main()
