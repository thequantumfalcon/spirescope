"""Generate content-localization overlays from the installed game.

`python -m sts2 localize` reads the localization files out of the player's
own Slay the Spire 2 install and writes one overlay per language into
sts2/locales/content/, where the knowledge base picks them up (see i18n.py).

Nothing is downloaded and nothing is redistributed: the text comes from the
copy of the game already on this machine, so it always matches the version
being played rather than a snapshot that goes stale on the next patch.

The awkward part is that the game stores descriptions as templates
("Deal {Damage} damage.") with the numbers held elsewhere. Each English
template is aligned against the shipped English description to recover the
values, and those same values are rendered into every other language.
Anything that cannot be resolved cleanly is left out, so the entity falls
back to English rather than showing half-rendered markup.
"""
import json
import logging
import random
import re
import struct
from pathlib import Path

from sts2.config import DATA_DIR, GAME_INSTALL_DIR

log = logging.getLogger(__name__)

# Game locale folder -> app locale code (see sts2/locales/*.json)
LANG_CODES = {
    "deu": "de", "esp": "esla", "fra": "fr", "ita": "it", "jpn": "ja",
    "kor": "ko", "pol": "pl", "ptb": "pt", "rus": "ru", "spa": "es",
    "tha": "th", "tur": "tr", "zhs": "zhs", "zht": "zht",
}

# esp/spa disambiguated from the game's own credits.json headers
NATIVE = {
    "deu": "Deutsch", "esp": "Español (Latinoamérica)", "fra": "Français",
    "ita": "Italiano", "jpn": "日本語", "kor": "한국어", "pol": "Polski",
    "ptb": "Português (Brasil)", "rus": "Русский", "spa": "Español (España)",
    "tha": "ไทย", "tur": "Türkçe", "zhs": "简体中文", "zht": "繁體中文",
}
CJK_NOSPACE = {"zhs", "zht", "jpn"}

TAG_RE = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9]*(?:=[^\]\[]*)?\]")
NUMPAT = r"(?:-?\d+(?:[.,]\d+)?|X)"
RESIDUE = set("{}[]@")

DUAL_SUFFIXES = ("_EVENT", "_QUEST", "_TOKEN")

# Localization tables the builder needs from each language folder
_WANTED = ("cards", "relics", "potions", "monsters", "encounters", "events",
           "static_hover_tips", "enchantments")

# Module state; run() populates these before invoking the builder
APP = DATA_DIR
OUT = Path(__file__).parent / "locales" / "content"
LANGS: list = []
_LOC_DATA: dict = {}


class LocalizeError(RuntimeError):
    """The game install could not be read."""


def read_localization(game_dir=None) -> dict:
    """{lang: {table: parsed json}} read from the game's Godot archive.

    The archive carries a plain index of offsets; only localization/*.json
    is read, and nothing is ever written back to the game directory.
    """
    game_dir = Path(game_dir or GAME_INSTALL_DIR)
    pck = game_dir / "SlayTheSpire2.pck"
    if not pck.exists():
        raise LocalizeError(
            f"No SlayTheSpire2.pck under {game_dir}. Point STS2_GAME_DIR at "
            "the game's install directory.")
    out: dict = {}
    file_size = pck.stat().st_size
    try:
        with open(pck, "rb") as f:
            if f.read(4) != b"GDPC":
                raise LocalizeError(f"{pck} is not a Godot archive")
            f.read(4)                                    # pack format version
            f.read(12)                                   # engine version
            flags, file_base = struct.unpack("<IQ", f.read(12))
            dir_offset, = struct.unpack("<Q", f.read(8))
            f.seek(dir_offset)
            count, = struct.unpack("<I", f.read(4))
            # Each directory entry is at least plen(4) + offset/size(16) +
            # md5(16) + flags(4) bytes; a count that couldn't fit in what's
            # left of the file is corrupt, not just a lot of entries.
            if count > (file_size - f.tell()) // 40:
                raise LocalizeError(f"{pck} directory entry count is implausible")
            wanted = []
            for _ in range(count):
                plen, = struct.unpack("<I", f.read(4))
                if not (0 < plen <= 4096):
                    raise LocalizeError(f"{pck} has an implausible path length")
                raw = f.read(plen)
                if len(raw) != plen:
                    raise LocalizeError(f"{pck} is a corrupt or truncated pack file")
                path = raw.rstrip(b"\x00").decode("utf-8", "replace")
                offset, size = struct.unpack("<2Q", f.read(16))
                f.read(16)                               # md5
                entry_flags, = struct.unpack("<I", f.read(4))
                if entry_flags & 1:                      # encrypted: never touch
                    continue
                parts = path.split("/")
                if (len(parts) != 3 or parts[0] != "localization"
                        or not parts[2].endswith(".json")
                        or parts[2][:-5] not in _WANTED):
                    continue
                real_offset = file_base + offset if flags & 2 else offset
                if not (0 <= real_offset <= file_size and size <= file_size - real_offset):
                    raise LocalizeError(
                        f"{pck} has an out-of-range offset/size for {path}")
                wanted.append((parts[1], parts[2][:-5], real_offset, size))
            for lang, table, offset, size in wanted:
                f.seek(offset)
                try:
                    out.setdefault(lang, {})[table] = json.loads(
                        f.read(size).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    log.warning("Skipping unreadable %s/%s", lang, table)
    except struct.error as ex:
        raise LocalizeError(f"{pck} is a corrupt or truncated pack file") from ex
    if "eng" not in out:
        raise LocalizeError(f"No English localization found in {pck}")
    return out


def load(lang, fn):
    """Localization table for a language, or {} when the game lacks it."""
    return _LOC_DATA.get(lang, {}).get(fn, {})


def strip_tags(s):
    return TAG_RE.sub("", s)


def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def norm_shipped(s):
    """Normalize wiki icon warts in shipped English before alignment:
    '@ST@ST@ST' -> '3 Star', '@Gold' -> 'Gold', 'type:Attack' -> 'Attack'."""
    s = re.sub(r"(?:@ST)+", lambda m: f"{len(m.group(0)) // 3} Star", s)
    s = s.replace("@Gold", "Gold")
    # "play 3 type:Attack" -> "play 3 Attacks" (templates use the plural)
    s = re.sub(r"\b(\d+)\s+type:(Attack|Skill|Power)\b", r"\1 \2s", s)
    s = re.sub(r"\b(?:type|color):", "", s)
    s = re.sub(r"<br\s*/?>", " ", s)
    return norm_ws(s)


# ---------------- template parsing ----------------

class Token:
    __slots__ = ("name", "kind", "fixed", "branches", "cond")
    def __init__(self, name, kind, fixed=None, branches=None, cond=None):
        self.name = name
        self.kind = kind          # NUM, ENERGY, STAR, PLURAL, PLURAL_RU, SHOW, COND, INNER, TEXT
        self.fixed = fixed        # int for fixed icons
        self.branches = branches  # list[str] raw branch templates
        self.cond = cond          # (op, threshold) for COND


def find_close(s, i):
    """s[i] == '{'; return index of matching '}' or -1."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def split_top(s, sep="|"):
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def parse_token(content):
    m = re.match(r"([A-Za-z0-9_.]*)", content)
    name = m.group(1)
    rest = content[m.end():]
    if rest == "":
        if name == "":
            return Token("", "INNER")
        if name == "singleStarIcon":
            return Token(name, "STAR", fixed=1)
        if name in ("EnchantmentName", "Enchantment"):
            return Token(name, "ENCH")
        return Token(name, "NUM")
    if not rest.startswith(":"):
        return None  # unparseable
    spec = rest[1:]
    if spec in ("diff()", "diff)", "inverseDiff()", "percentMore()"):
        if name == "":
            return Token("", "INNER")  # "{:diff()}" inside a plural branch
        return Token(name, "NUM")
    m2 = re.match(r"diff\(\):plural(?:\((\w+)\))?:(.*)$", spec, re.S)
    if m2:  # translator-mangled "{X:diff():plural:a|b}"
        kind = "PLURAL_RU" if m2.group(1) == "ru" else "PLURAL"
        return Token(name, kind, branches=split_top(m2.group(2)))
    m2 = re.fullmatch(r"energyIcons\((\d*)\)", spec)
    if m2:
        return Token(name, "ENERGY", fixed=int(m2.group(1)) if m2.group(1) else None)
    m2 = re.fullmatch(r"starIcons\((\d*)\)", spec)
    if m2:
        return Token(name, "STAR", fixed=int(m2.group(1)) if m2.group(1) else None)
    if spec.startswith("plural(ru):"):
        return Token(name, "PLURAL_RU", branches=split_top(spec[len("plural(ru):"):]))
    if spec.startswith("plural:"):
        return Token(name, "PLURAL", branches=split_top(spec[len("plural:"):]))
    if spec.startswith("show:"):
        br = split_top(spec[len("show:"):])
        if len(br) == 1:
            br = [br[0], ""]
        return Token(name, "SHOW", branches=br)
    if spec.startswith("choose("):
        j = spec.index(")")  # choose(...) arg may contain '|'; find first ')'
        after = spec[j + 1:]
        if not after.startswith(":"):
            return None
        return Token(name, "SHOW", branches=split_top(after[1:]))
    if spec.startswith("cond:"):
        m3 = re.match(r"cond:([<>]=?|==)\s*(\d+)\?(.*)$", spec, re.S)
        if m3:
            return Token(name, "COND", cond=(m3.group(1), int(m3.group(2))),
                         branches=split_top(m3.group(3)))
        # operator-less cond ("{X.StringValue:cond:A|B}") behaves like show
        br = split_top(spec[len("cond:"):])
        if len(br) == 1:
            br = [br[0], ""]
        return Token(name, "SHOW", branches=br)
    # Fallback "{Name:branchA|branchB}" show-style (e.g. MAD_SCIENCE {Chaos:...|})
    br = split_top(spec)
    if len(br) == 1:
        return Token(name, "TEXT", branches=br)  # translator artifact; unresolvable
    return Token(name, "SHOW", branches=br)


def parse_template(text):
    """Return list of ('lit', str) | ('tok', Token). None on parse failure."""
    out, i = [], 0
    while i < len(text):
        j = text.find("{", i)
        if j < 0:
            out.append(("lit", text[i:]))
            break
        if j > i:
            out.append(("lit", text[i:j]))
        k = find_close(text, j)
        if k < 0:
            return None
        tok = parse_token(text[j + 1:k])
        if tok is None:
            return None
        out.append(("tok", tok))
        i = k + 1
    return out


# ---------------- English alignment ----------------

def lit_pattern(lit):
    cleaned = strip_tags(lit)
    parts, ws = [], False
    for ch in cleaned:
        if ch.isspace():
            ws = True
        else:
            if ws:
                parts.append(r"\s*")
                ws = False
            elif ch in ",.;:!?":
                parts.append(r"\s*")  # tolerate stray space before punctuation
            parts.append(re.escape(ch))
    if ws:
        parts.append(r"\s*")
    joined = "".join(parts)
    # wiki sometimes writes "Attack" where the template says "Attacks"
    joined = re.sub(r"\b(Attack|Skill|Power)s\b", r"\1s?", joined)
    return joined


class Registry:
    def __init__(self):
        self.groups = []   # (gname, action) action = callable(match, store)
        self.n = 0
    def newname(self):
        self.n += 1
        return f"g{self.n}"


def branch_pattern(branch_tpl, outer_name, reg):
    """Pattern for a branch body; supports literals + inner {} + nested tokens."""
    elems = parse_template(branch_tpl)
    if elems is None:
        return None
    parts = []
    for kind, val in elems:
        if kind == "lit":
            parts.append(lit_pattern(val))
        else:
            p = token_pattern(val, reg, outer_name=outer_name)
            if p is None:
                return None
            parts.append(p)
    return "".join(parts)


def token_pattern(tok, reg, outer_name=None):
    if tok.kind == "INNER":
        if not outer_name:
            return None
        g = reg.newname()
        reg.groups.append((g, ("val", outer_name)))
        return rf"(?P<{g}>{NUMPAT})"
    if tok.kind == "NUM":
        g = reg.newname()
        reg.groups.append((g, ("val", tok.name)))
        return rf"(?P<{g}>{NUMPAT})"
    if tok.kind == "ENCH":
        g = reg.newname()
        reg.groups.append((g, ("val", tok.name)))
        return rf"(?P<{g}>[A-Z][A-Za-z' -]*?)(?=[,.;:]|$)"
    if tok.kind == "ENERGY":
        if tok.fixed is not None:
            if tok.fixed == 1:
                # wiki renders "0[energy icon]" as plain "0 Energy"
                return r"\s*(?:1\s*)?Energy"
            return rf"\s*{tok.fixed}\s*Energy"
        g = reg.newname()
        reg.groups.append((g, ("energyrun", tok.name)))
        # "2 Energy" or icon runs baked as "1 Energy 1 Energy ..."
        return rf"(?P<{g}>{NUMPAT}(?:\s*Energy\s*{NUMPAT})*\s*Energy)"
    if tok.kind == "STAR":
        if tok.fixed is not None:
            if tok.fixed == 1:
                return r"\s*(?:1\s*)?Stars?"
            return rf"\s*{tok.fixed}\s*Stars?"
        g = reg.newname()
        reg.groups.append((g, ("val", tok.name)))
        return rf"(?P<{g}>{NUMPAT})\s*Stars?"
    if tok.kind in ("PLURAL", "PLURAL_RU", "SHOW", "COND"):
        alts = []
        gnames = []
        for bi, br in enumerate(tok.branches):
            g = reg.newname()
            bp = branch_pattern(br, tok.name, reg)
            if bp is None:
                return None
            alts.append(rf"(?P<{g}>{bp})")
            gnames.append(g)
        act = "plural_branch" if tok.kind in ("PLURAL", "PLURAL_RU") else "branch"
        reg.groups.append((tuple(gnames), (act, tok.name, tok)))
        return "(?:" + "|".join(alts) + ")"
    return None  # TEXT etc.


def extract_english(template, shipped):
    """Align English template against shipped English text.
    Returns (values, branches) dicts name->list, or None on failure."""
    elems = parse_template(template)
    if elems is None:
        return None
    reg = Registry()
    parts = []
    for kind, val in elems:
        if kind == "lit":
            parts.append(lit_pattern(val))
        else:
            p = token_pattern(val, reg)
            if p is None:
                return None
            parts.append(p)
    pattern = "".join(parts)
    # allow the shipped text to drop a trailing period
    if pattern.endswith(r"\."):
        pattern = pattern[:-2] + r"\.?"
    elif pattern.endswith(r"\.\s*"):
        pattern = pattern[:-6] + r"\.?\s*"
    shipped_n = norm_shipped(shipped)
    try:
        m = re.search(pattern, shipped_n)
    except re.error:
        return None
    if not m or not m.group(0).strip():
        return None  # degenerate all-empty-branch match
    values, branches, hints = {}, {}, {}
    for gspec, action in reg.groups:
        act, name = action[0], action[1]
        if act in ("val", "energyrun"):
            v = m.group(gspec)
            if v is None:
                continue  # inside an unmatched branch
            if act == "energyrun":
                nums = re.findall(NUMPAT, v)
                if len(nums) == 1:
                    v = nums[0]
                elif nums and all(n == "1" for n in nums):
                    v = str(len(nums))  # "1 Energy 1 Energy" icon run
                else:
                    return None
            values.setdefault(name, []).append(v)
        else:
            idx = None
            for bi, g in enumerate(gspec):
                if m.group(g) is not None:
                    idx = bi
                    break
            if idx is not None:
                branches.setdefault(name, []).append(idx)
                if act == "plural_branch":
                    tok = action[2]
                    if len(tok.branches) == 2:
                        if idx == 0 and "{}" not in tok.branches[0]:
                            # singular branch matched => the value is exactly 1
                            values.setdefault(name, []).append("1")
                        elif idx == 1:
                            hints[name] = "many"
                elif act == "branch":
                    tok = action[2]
                    if (tok.kind == "COND" and tok.cond
                            and tok.cond[0] == ">" and tok.cond[1] == 1):
                        if idx == 1 and name not in values:
                            # else-branch of ">1" matched => the value is 1
                            values.setdefault(name, []).append("1")
                        elif idx == 0:
                            hints[name] = "many"
    return values, branches, hints


def fallback_single_number(template, shipped):
    """Last-resort extraction when literal wording drifted between the 0.107.1
    template and the wiki-derived shipped text: allowed only when the template
    has exactly ONE value-bearing token name, no branch-choice tokens, and the
    shipped text contains exactly ONE number (ordinals excluded) — then the
    assignment is unambiguous."""
    elems = parse_template(template)
    if elems is None:
        return None
    names = []
    for kind, val in elems:
        if kind != "tok":
            continue
        if val.kind in ("SHOW", "COND", "TEXT", "INNER", "ENCH"):
            return None
        if val.kind in ("PLURAL", "PLURAL_RU"):
            for br in val.branches:
                if "{" in br:
                    return None  # nested tokens inside branches: too risky
            continue
        if val.kind in ("ENERGY", "STAR") and val.fixed is not None:
            continue
        names.append(val.name)
    if len(set(names)) != 1:
        return None
    shipped_n = norm_shipped(shipped)
    nums = [mm.group(0) for mm in
            re.finditer(rf"{NUMPAT}(?!\s*(?:st|nd|rd|th)\b)", shipped_n)]
    if len(nums) != 1:
        return None
    return {names[0]: [nums[0]] * len(names)}, {}, {}


# ---------------- translated rendering ----------------

def plural_index_ru(n, count):
    if count < 3:
        return 0 if n == 1 else min(1, count - 1)
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return 0
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return 1
    return 2


class RenderFail(Exception):
    pass


class Renderer:
    def __init__(self, values, branches, lang, energy_word, star_word,
                 hints=None, ench_lookup=None):
        self.values = values or {}
        self.branches = branches or {}
        self.hints = hints or {}
        self.ench_lookup = ench_lookup
        self.vidx = {}
        self.bidx = {}
        self.lang = lang
        self.energy_word = energy_word
        self.star_word = star_word
        self.sep = "" if lang in CJK_NOSPACE else " "

    def next_val(self, name):
        i = self.vidx.get(name, 0)
        vs = self.values.get(name)
        if not vs:
            raise RenderFail(f"no value for {name}")
        v = vs[i] if i < len(vs) else vs[-1]
        self.vidx[name] = i + 1
        return v

    def peek_val(self, name):
        vs = self.values.get(name)
        return vs[0] if vs else None

    def next_branch(self, name):
        i = self.bidx.get(name, 0)
        bs = self.branches.get(name)
        if bs is None:
            raise RenderFail(f"no branch for {name}")
        b = bs[i] if i < len(bs) else bs[-1]
        self.bidx[name] = i + 1
        return b

    def render(self, template, inner_name=None, prev=""):
        elems = parse_template(template)
        if elems is None:
            raise RenderFail("parse")
        out = []
        for kind, val in elems:
            if kind == "lit":
                out.append(strip_tags(val))
            else:
                out.append(self.render_token(val, inner_name,
                                             prev=prev + "".join(out)))
        return "".join(out)

    def icon_text(self, v, word, prev):
        """'0[energy icon]' style: when a digit directly precedes a 1-valued
        icon, the icon is a unit marker, not another number ('0 Energy')."""
        if v == 1 and prev.rstrip() and prev.rstrip()[-1].isdigit():
            if prev and prev[-1].isspace():
                return word
            return ("" if self.lang in CJK_NOSPACE else " ") + word
        return f"{v}{self.sep}{word}"

    def render_token(self, tok, inner_name=None, prev=""):
        if tok.kind == "INNER":
            name = inner_name
            if not name:
                raise RenderFail("bare {} outside branch")
            v = self.peek_val(name)
            if v is None:
                raise RenderFail(f"no inner value for {name}")
            return str(v)
        if tok.kind == "NUM":
            return str(self.next_val(tok.name))
        if tok.kind == "ENCH":
            v = str(self.next_val(tok.name))
            loc = self.ench_lookup(v) if self.ench_lookup else None
            if not loc:
                raise RenderFail(f"enchantment {v!r} unresolved")
            return loc
        if tok.kind == "ENERGY":
            if tok.fixed is not None:
                return self.icon_text(tok.fixed, self.energy_word, prev)
            v = self.next_val(tok.name)
            return f"{v}{self.sep}{self.energy_word}"
        if tok.kind == "STAR":
            if tok.fixed is not None:
                return self.icon_text(tok.fixed, self.star_word, prev)
            v = self.next_val(tok.name)
            return f"{v}{self.sep}{self.star_word}"
        if tok.kind in ("PLURAL", "PLURAL_RU"):
            v = self.peek_val(tok.name)
            nb = len(tok.branches)
            if v is not None and re.fullmatch(r"-?\d+", str(v)):
                n = int(v)
                if tok.kind == "PLURAL_RU" or nb >= 3:
                    idx = plural_index_ru(n, nb)
                else:
                    idx = 0 if n == 1 else min(1, nb - 1)
            elif v == "X":
                idx = min(1, nb - 1)
            else:
                bs = self.branches.get(tok.name)
                if bs:
                    idx = min(bs[0], nb - 1)
                else:
                    raise RenderFail(f"plural unresolved for {tok.name}")
            return self.render(tok.branches[idx], inner_name=tok.name, prev=prev)
        if tok.kind == "SHOW":
            idx = self.next_branch(tok.name)
            if idx >= len(tok.branches):
                raise RenderFail(f"branch idx out of range for {tok.name}")
            return self.render(tok.branches[idx], inner_name=tok.name, prev=prev)
        if tok.kind == "COND":
            v = self.peek_val(tok.name)
            op, thr = tok.cond
            if v is not None and re.fullmatch(r"-?\d+", str(v)):
                n = int(v)
                res = {"<": n < thr, "<=": n <= thr, ">": n > thr,
                       ">=": n >= thr, "==": n == thr}[op]
            elif (self.hints.get(tok.name) == "many"
                  and op in (">", ">=") and thr <= 1):
                res = True  # English matched the plural branch => value > 1
            else:
                raise RenderFail(f"cond unresolved for {tok.name}")
            idx = 0 if res else 1
            if idx >= len(tok.branches):
                raise RenderFail("cond branches")
            return self.render(tok.branches[idx], inner_name=tok.name, prev=prev)
        raise RenderFail(f"kind {tok.kind}")


def needs_alignment(template):
    """True if rendering this template requires values/branches from English."""
    elems = parse_template(template)
    if elems is None:
        return True  # will fail anyway
    for kind, val in elems:
        if kind == "tok":
            if val.kind in ("ENERGY", "STAR") and val.fixed is not None:
                continue
            return True
    return False


def render_text(template, align, lang, energy_word, star_word, ench_lookup=None):
    values, branches, hints = align
    r = Renderer(values, branches, lang, energy_word, star_word, hints,
                 ench_lookup)
    txt = r.render(template)
    txt = norm_ws(txt.replace("\n", " "))
    if not txt:
        raise RenderFail("empty render")
    if any(c in RESIDUE for c in txt):
        raise RenderFail("residue")
    return txt


# ---------------- main build ----------------


def resolve_key(key, catalog_keys):
    if key in catalog_keys:
        return key
    for suf in DUAL_SUFFIXES:
        if key.endswith(suf):
            base = key[: -len(suf)]
            if base in catalog_keys:
                return base
    return None

def _build_all():
    OUT.mkdir(parents=True, exist_ok=True)
    app = {}
    for fn in ["cards", "relics", "potions", "enemies", "events"]:
        app[fn] = json.loads((APP / f"{fn}.json").read_text(encoding="utf-8"))

    eng = {fn: load("eng", fn) for fn in
           ["cards", "relics", "potions", "monsters", "encounters", "events",
            "static_hover_tips"]}

    # per-language icon words
    words = {}
    for lang in LANGS:
        tips = load(lang, "static_hover_tips")
        words[lang] = (tips.get("ENERGY.title") or "Energy",
                       tips.get("STAR_COUNT.title") or "Star")

    # enchantment-name lookup: English title -> key -> localized title
    eng_ench = load("eng", "enchantments")
    ench_key_by_title = {}
    for k, v in eng_ench.items():
        if k.endswith(".title") and isinstance(v, str):
            ench_key_by_title[v] = k[:-6]
    loc_ench = {lang: load(lang, "enchantments") for lang in LANGS}

    def make_ench_lookup(lang):
        def lookup(title):
            key = ench_key_by_title.get(title)
            if not key:
                return None
            t = loc_ench[lang].get(key + ".title", "")
            t = norm_ws(strip_tags(t))
            return t or None
        return lookup

    # ---- token-name consistency check on 20 random entities ----
    random.seed(42)
    card_keys = sorted({k[:-len(".description")] for k in eng["cards"]
                        if k.endswith(".description")})
    # Spot-check sampling, not cryptography.
    sample = random.sample(card_keys, 20)  # nosec B311
    tokname_re = re.compile(r"\{([A-Za-z0-9_]+)[:}]")
    mismatches = []
    for key in sample:
        etext = eng["cards"].get(key + ".description", "")
        enames = set(tokname_re.findall(etext))
        for lang in LANGS:
            ltext = load(lang, "cards").get(key + ".description", "")
            if not ltext:
                continue
            lnames = set(tokname_re.findall(ltext))
            extra = lnames - enames
            if extra:
                mismatches.append((lang, key, sorted(extra)))
    log.debug("TOKEN-NAME CHECK on 20 random cards: "
          f"{len(mismatches)} languages x entities with token names not in English")
    for mm in mismatches:
        log.debug("   ", mm)

    # ---- English alignment pass (once) ----
    # aligned[(section, shipped_id)] = dict(variant -> (values, branches) or None)
    catalogs = {
        "cards": {k[:-6] for k in eng["cards"] if k.endswith(".title")},
        "relics": {k[:-6] for k in eng["relics"] if k.endswith(".title")},
        "potions": {k[:-6] for k in eng["potions"] if k.endswith(".title")},
    }
    aligned = {}
    key_of = {}     # (section, shipped_id) -> catalog key
    stats_align = {"cards": [0, 0], "relics": [0, 0], "potions": [0, 0]}  # ok, fail
    stats_fallback = {"cards": 0, "relics": 0, "potions": 0}
    uncovered = {"cards": [], "relics": [], "potions": []}
    for section, prefix in [("cards", "CARD."), ("relics", "RELIC."), ("potions", "POTION.")]:
        for item in app[section]:
            sid = item["id"]
            raw = sid.split(".", 1)[1] if "." in sid else sid
            ck = resolve_key(raw, catalogs[section])
            if ck is None:
                uncovered[section].append(sid)
                continue
            key_of[(section, sid)] = ck
            tpl = eng[section].get(ck + ".description", "")
            variants = {}
            shipped_desc = item.get("description", "") or ""
            if not needs_alignment(tpl):
                variants["base"] = ({}, {}, {})
            else:
                res = extract_english(tpl, shipped_desc) if shipped_desc else None
                if res is None and shipped_desc:
                    res = fallback_single_number(tpl, shipped_desc)
                    if res is not None:
                        stats_fallback[section] += 1
                variants["base"] = res
            if section == "cards":
                up = item.get("description_upgraded", "") or ""
                if not needs_alignment(tpl):
                    variants["up"] = ({}, {}, {})
                elif up:
                    upres = extract_english(tpl, up)
                    if upres is None:
                        upres = fallback_single_number(tpl, up)
                    variants["up"] = upres
                else:
                    variants["up"] = None
            aligned[(section, sid)] = variants
            if variants["base"] is not None:
                stats_align[section][0] += 1
            else:
                stats_align[section][1] += 1

    log.debug("\nENGLISH ALIGNMENT (base description): "
          + ", ".join(f"{s}: {v[0]} ok ({stats_fallback[s]} via single-number "
                      f"fallback) / {v[1]} fail" for s, v in stats_align.items()))
    for s in uncovered:
        log.debug(f"  {s}: {len(uncovered[s])} shipped ids not in 0.107.1 catalog "
              f"(skipped): {uncovered[s][:8]}{'...' if len(uncovered[s]) > 8 else ''}")

    # enemy/event key resolution
    mon_names = {k[:-5] for k in eng["monsters"] if k.endswith(".name")}
    enc_titles = {k[:-6] for k in eng["encounters"] if k.endswith(".title")}
    ev_titles = {k[:-6] for k in eng["events"] if k.endswith(".title")}

    enemy_map = {}   # shipped_id -> (file, lockey)
    enemy_uncovered = []
    for e in app["enemies"]:
        sid = e["id"]
        pref, raw = sid.split(".", 1)
        if pref in ("MONSTER", "BOSS") and raw in mon_names:
            enemy_map[sid] = ("monsters", raw + ".name")
        elif pref == "ENCOUNTER" and raw in enc_titles:
            enemy_map[sid] = ("encounters", raw + ".title")
        elif raw in mon_names:
            enemy_map[sid] = ("monsters", raw + ".name")
        else:
            enemy_uncovered.append(sid)
    event_map = {}
    event_uncovered = []
    for e in app["events"]:
        raw = e["id"].split(".", 1)[1]
        if raw in ev_titles:
            event_map[e["id"]] = raw + ".title"
        else:
            event_uncovered.append(e["id"])
    log.debug(f"\nENEMIES: {len(enemy_map)}/{len(app['enemies'])} mapped; "
          f"uncovered {len(enemy_uncovered)}: {enemy_uncovered[:6]}...")
    log.debug(f"EVENTS: {len(event_map)}/{len(app['events'])} names mapped; "
          f"uncovered: {event_uncovered}")

    # ---- per-language build ----
    report = {}
    for lang in LANGS:
        ew, sw = words[lang]
        ench_lookup = make_ench_lookup(lang)
        loc = {fn: load(lang, fn) for fn in
               ["cards", "relics", "potions", "monsters", "encounters", "events"]}
        out = {"_meta": {"language_native": NATIVE[lang],
                         "game_version": "0.107.1",
                         "source": "official game localization"},
               "cards": {}, "relics": {}, "potions": {}, "enemies": {}, "events": {}}
        cnt = {"cards_ok": 0, "cards_fail": 0, "cards_upgraded": 0,
               "cards_name_only": 0,
               "relics_ok": 0, "relics_fail": 0, "relics_name_only": 0,
               "potions_ok": 0, "potions_fail": 0, "potions_name_only": 0,
               "enemies_ok": 0, "enemies_missing": 0,
               "events_ok": 0, "events_missing": 0}
        fail_ids = []
        for section, prefix in [("cards", "CARD."), ("relics", "RELIC."), ("potions", "POTION.")]:
            for item in app[section]:
                sid = item["id"]
                if (section, sid) not in key_of:
                    continue
                ck = key_of[(section, sid)]
                variants = aligned[(section, sid)]
                title = loc[section].get(ck + ".title", "")
                tpl = loc[section].get(ck + ".description", "")
                eng_tpl = eng[section].get(ck + ".description", "")
                if not title:
                    cnt[section + "_fail"] += 1
                    fail_ids.append(sid + " (untranslated)")
                    continue
                name = norm_ws(strip_tags(title))
                if any(c in RESIDUE for c in name):
                    cnt[section + "_fail"] += 1
                    fail_ids.append(sid + " (name residue)")
                    continue
                shipped_desc = item.get("description", "") or ""
                if (not eng_tpl or not tpl
                        or (not shipped_desc and needs_alignment(eng_tpl))):
                    # nothing to translate (curses etc.), description not yet
                    # translated, or no shipped English text to align numbers
                    # against: ship the localized name only
                    out[section][sid] = {"name": name}
                    cnt[section + "_name_only"] += 1
                    continue
                if variants["base"] is None:
                    cnt[section + "_fail"] += 1
                    fail_ids.append(sid + " (eng align)")
                    continue
                try:
                    desc = render_text(tpl, variants["base"], lang, ew, sw,
                                       ench_lookup)
                except RenderFail as ex:
                    cnt[section + "_fail"] += 1
                    fail_ids.append(sid + f" (render: {ex})")
                    continue
                entry = {"name": name, "description": desc}
                if section == "cards":
                    upv = variants.get("up")
                    if upv is not None:
                        try:
                            entry["description_upgraded"] = render_text(
                                tpl, upv, lang, ew, sw, ench_lookup)
                            cnt["cards_upgraded"] += 1
                        except RenderFail:
                            pass
                out[section][sid] = entry
                cnt[section + "_ok"] += 1
        for sid, (fname, lockey) in enemy_map.items():
            t = loc[fname].get(lockey, "")
            if t and not any(c in RESIDUE for c in t):
                out["enemies"][sid] = {"name": norm_ws(strip_tags(t))}
                cnt["enemies_ok"] += 1
            else:
                cnt["enemies_missing"] += 1
        for sid, lockey in event_map.items():
            t = loc["events"].get(lockey, "")
            if t and not any(c in RESIDUE for c in t):
                out["events"][sid] = {"name": norm_ws(strip_tags(t))}
                cnt["events_ok"] += 1
            else:
                cnt["events_missing"] += 1

        path = OUT / f"{lang}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        size = path.stat().st_size
        report[lang] = (cnt, size, fail_ids)
        log.info(f"{lang}: cards {cnt['cards_ok']}/{len(app['cards'])} "
              f"(upgraded {cnt['cards_upgraded']}, name-only {cnt['cards_name_only']}, "
              f"fail {cnt['cards_fail']}), "
              f"relics {cnt['relics_ok']}/{len(app['relics'])} "
              f"(name-only {cnt['relics_name_only']}, fail {cnt['relics_fail']}), "
              f"potions {cnt['potions_ok']}/{len(app['potions'])} "
              f"(name-only {cnt['potions_name_only']}, fail {cnt['potions_fail']}), "
              f"enemies {cnt['enemies_ok']}/{len(app['enemies'])}, "
              f"events {cnt['events_ok']}/{len(app['events'])}, "
              f"size {size/1024:.0f} KB")
        if fail_ids:
            log.debug("%s: entities left in English: %s", lang, fail_ids[:6])

    return report



def available_languages(game_dir=None) -> list:
    """App locale codes this game install can produce overlays for."""
    data = read_localization(game_dir)
    return sorted(LANG_CODES[k] for k in data
                  if k != "eng" and k in LANG_CODES and data[k].get("cards"))


def run(langs=None, game_dir=None) -> list:
    """Write overlays for `langs` (default: every language the game ships).

    Returns the paths written. Raises LocalizeError when the game install
    cannot be read or a requested language is not in it.
    """
    global _LOC_DATA, LANGS
    _LOC_DATA = read_localization(game_dir)
    known = [k for k in _LOC_DATA
             if k != "eng" and k in LANG_CODES and _LOC_DATA[k].get("cards")]
    if langs:
        reverse = {v: k for k, v in LANG_CODES.items()}
        wanted = {reverse.get(str(x).lower(), str(x).lower()) for x in langs}
        unknown = wanted - set(known)
        if unknown:
            available = ", ".join(sorted(LANG_CODES[k] for k in known))
            raise LocalizeError(
                f"Not in this game install: {', '.join(sorted(unknown))}. "
                f"Available: {available}")
        LANGS = sorted(wanted)
    else:
        LANGS = sorted(known)
    if not LANGS:
        raise LocalizeError("This game install has no translatable languages")

    OUT.mkdir(parents=True, exist_ok=True)
    _build_all()

    # The builder names files by game locale; the app looks them up by app code
    written = []
    for lang in LANGS:
        src = OUT / f"{lang}.json"
        if not src.exists():
            continue
        payload = json.loads(src.read_text(encoding="utf-8"))
        payload.setdefault("_meta", {})["code"] = LANG_CODES[lang]
        dest = OUT / f"{LANG_CODES[lang]}.json"
        dest.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
        if src != dest:
            src.unlink()
        written.append(dest)
    return written
