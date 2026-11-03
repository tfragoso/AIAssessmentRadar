"""Deterministic enrichment rules (EN / DE / FR). Each rule returns "" / None when it isn't sure,
leaving the field for the later LLM pass."""

from __future__ import annotations

import re

from ..models import Posting, RawPosting
from ..textutil import fold, has_term

# --- seniority -----------------------------------------------------------------------

SENIORITY_RULES: list[tuple[str, list[str]]] = [
    ("intern", ["intern", "internship", "praktikum", "praktikant", "praktikantin", "stagiaire", "stage",
                "werkstudent", "working student", "trainee", "apprenti", "apprentice", "lernende", "lehrstelle",
                "summer analyst", "student assistant", "hilfsassistent"]),
    ("director", ["director", "head of", "head", "vice president", "vp", "chief", "managing director",
                  "executive director", "partner", "direktor", "direktorin", "directeur", "directrice",
                  "bereichsleiter", "abteilungsleiter", "mitglied der geschaftsleitung"]),
    ("lead", ["lead", "leader", "principal", "staff", "manager", "senior manager", "team lead", "teamleiter",
              "teamleiterin", "leiter", "leiterin", "leitung", "responsable", "chef", "cheffe", "expert",
              "senior expert", "group leader"]),
    ("senior", ["senior", "sr", "experienced", "erfahren", "confirme", "confirmee", "senior associate",
                "senior consultant", "senior analyst", "avp", "assistant vice president"]),
    ("junior", ["junior", "jr", "graduate", "entry level", "associate", "assistant", "phd", "doktorand",
                "doktorandin", "doctoral", "doctorant", "doctorante", "postdoc", "postdoctoral",
                "young professional", "berufseinsteiger", "einsteiger", "debutant"]),
]
# "Senior Manager" is lead, "Associate Director" is director, "Senior Associate" is senior: check order matters,
# except that "senior manager" must win over "senior" - handled by checking lead before senior.


def seniority(title: str, years: int | None = None) -> str:
    t = fold(title)
    for level, terms in SENIORITY_RULES:
        if has_term(t, terms):
            return level
    if years is not None:  # no cue in the title: fall back on years of experience asked
        return "junior" if years <= 1 else "mid" if years <= 4 else "senior" if years <= 7 else "lead"
    return ""


# --- years of experience -------------------------------------------------------------------

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "ein": 1, "einem": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "neun": 9, "zehn": 10,
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
}
_NUM = r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")"
_UNIT = r"(?:years?|yrs?|jahren?|jahre|ans|annees?)"
_EXP = r"(?:experience|erfahrung|berufserfahrung|praxis|expertise|track record)"
YEARS_RE = re.compile(
    rf"(?<!\w){_NUM}\s*\+?\s*(?:(?:-|to|bis|a|à)\s*{_NUM}\s*\+?\s*)?{_UNIT}(?!\w)[^.;\n]{{0,60}}?{_EXP}"
    rf"|{_EXP}[^.;\n]{{0,40}}?(?:of|von|de|d|mindestens|at least|minimum)?\s*{_NUM}\s*\+?\s*{_UNIT}(?!\w)"
)


def _num(s: str | None) -> int | None:
    if not s:
        return None
    return int(s) if s.isdigit() else NUMBER_WORDS.get(s)


def years_required(text: str) -> int | None:
    for line in (text or "").splitlines():
        m = YEARS_RE.search(fold(line, keep_hyphens=True).replace("-", " - "))
        if m:
            n = _num(m.group(1)) or _num(m.group(3))
            if n and 0 < n <= 25:
                return n
    return None


# --- languages ------------------------------------------------------------------------------

LANG_NAMES = {
    "de": ["german", "deutsch", "deutschkenntnisse", "allemand", "allemande", "tedesco"],
    "fr": ["french", "franzosisch", "franzosischkenntnisse", "francais", "francaise", "francese"],
    "en": ["english", "englisch", "englischkenntnisse", "anglais", "anglaise", "inglese"],
    "it": ["italian", "italienisch", "italienischkenntnisse", "italien", "italienne", "italiano"],
}
LEVEL_WORDS = [  # checked in order; first hit wins
    ("C2", ["native", "mother tongue", "muttersprache", "langue maternelle", "c2"]),
    ("C1", ["fluent", "fluency", "fliessend", "verhandlungssicher", "courant", "couramment", "excellent",
            "sehr gute", "sehr gut", "proficient", "proficiency", "business level", "professional working",
            "stilsicher", "c1", "bilingual", "bilingue", "parfaite", "parfaitement", "ausgezeichnete"]),
    ("B2", ["good", "gute", "bonne", "bonnes", "solid", "solide", "b2", "working knowledge"]),
    ("B1", ["basic", "grundkenntnisse", "notions", "b1", "a2", "a1", "conversational"]),
]
LANG_CONTEXT = ["language", "sprach", "langue", "lingu", "fluent", "fluency", "fliessend", "proficien", "command",
                "kenntnis", "knowledge", "connaissance", "maitrise", "spoken", "written", "oral", "ecrit", "mundlich",
                "schriftlich", "native", "mother tongue", "muttersprache", "verhandlungssicher", "courant", "bilingu",
                "speak", "parle", "beherrsch", "skills", "cefr", "level", "niveau", "excellent", "required",
                "erforderlich", "exige", "must", "sehr gut", "gute ", "bonne", "good", "von vorteil", "a plus",
                "advantage", "atout"]
PLUS_WORDS = ["is a plus", "a plus", "an advantage", "advantageous", "of advantage", "von vorteil", "ein plus",
              "vorteilhaft", "wunschenswert", "erwunscht", "un atout", "un plus", "un avantage", "nice to have",
              "desirable", "preferred", "ideally", "idealerweise", "idealement", "would be", "beneficial",
              "appreciated", "apprecie", "apprecie e", "souhaite", "souhaitable", "bonus"]
_CEFR = re.compile(r"(?<![a-z])([abc][12])(?![a-z0-9])")
_IDEALLY = ["ideally", "idealerweise", "idealement", "preferably", "vorzugsweise", "de preference", "optional"]


def _level(window: str) -> str:
    cefr = _CEFR.search(window)
    if cefr:
        return cefr.group(1).upper()
    for lv, words in LEVEL_WORDS:
        if has_term(window, [w for w in words if not _CEFR.fullmatch(w)]):
            return lv
    return ""


def languages_required(text: str) -> str:
    """'de:C1:required; fr:B2:plus' from requirement sentences that name a language."""
    found: dict[str, tuple[str, str]] = {}
    for raw_line in (text or "").splitlines():
        for sentence in re.split(r"(?<=[.;!?])\s+|•", raw_line):
            line = fold(sentence)
            # substring test on purpose: German compounds ("Englischkenntnisse", "Sprachkenntnisse")
            if not line or not (any(w in line for w in LANG_CONTEXT) or _CEFR.search(line)):
                continue
            hits = sorted(
                (m.start(), m.end(), lang)
                for lang, names in LANG_NAMES.items()
                for name in names
                for m in re.finditer(rf"(?<!\w){name}(?!\w)", line)
            )
            for i, (start, end, lang) in enumerate(hits):
                prev_end = hits[i - 1][1] if i else 0
                next_start = hits[i + 1][0] if i + 1 < len(hits) else len(line)
                if re.match(r"\s?(speaking|sprachig)", line[end:]):  # "English-speaking team"
                    continue
                # the clause around this language: from the previous comma to the next one
                after = re.split(r"[,;]", line[end:next_start])[0]
                before = re.split(r"[,;]", line[prev_end:start])[-1]
                cefr = _CEFR.search(line[end:end + 12]) or _CEFR.search(line[max(prev_end, start - 8):start])
                plus = has_term(after, PLUS_WORDS) or has_term(before[-30:], _IDEALLY)
                level = cefr.group(1).upper() if cefr else _level(before + " " + after)
                if not level and not plus:  # "fluent in German and English": the level covers the list
                    level = _level(line)
                need = "plus" if plus else "required"
                prev = found.get(lang)
                if prev is None or (prev[1] == "plus" and need == "required"):
                    found[lang] = (level, need)
                elif prev[1] == need and level > prev[0]:
                    found[lang] = (level, need)
    order = ["de", "fr", "en", "it"]
    return "; ".join(f"{l}:{found[l][0] or '?'}:{found[l][1]}" for l in order if l in found)


# --- ad language ----------------------------------------------------------------------------

STOPWORDS = {
    "de": ["und", "der", "die", "das", "mit", "für", "fur", "wir", "sie", "ist", "eine", "auf", "von"],
    "fr": ["et", "le", "la", "les", "des", "pour", "avec", "vous", "nous", "une", "dans", "est", "du"],
    "en": ["and", "the", "with", "for", "you", "our", "are", "will", "this", "your", "of", "to", "in"],
    "it": ["e", "il", "la", "per", "con", "che", "di", "una", "del", "sono", "nel", "gli"],
}


def ad_language(text: str) -> str:
    if not text or len(text) < 40:
        return ""
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        lang = detect(text[:3000])
        if lang in STOPWORDS:
            return lang
    except Exception:
        pass
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿñæœäöß]+", text.lower()[:3000])
    scores = {l: sum(words.count(w) for w in sw) for l, sw in STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""


# --- contract type ---------------------------------------------------------------------------

AGENCY = ["temporary", "temporar", "temporaire", "interim", "interimaire", "external payroll", "payroll partner",
          "through an agency", "via agency", "personalverleih", "personalvermittlung", "staffing agency",
          "contractor", "freelance", "freelancer", "location de services", "placement temporaire", "temp position",
          "contract through", "auf mandatsbasis", "mission temporaire"]
FIXED = ["befristet", "befristete", "befristeten", "cdd", "duree determinee", "fixed term", "limited contract",
         "limited duration", "zeitlich begrenzt", "maternity cover", "mutterschaftsvertretung",
         "remplacement", "projektanstellung", "contrat a duree determinee"]
PERMANENT = ["permanent", "unbefristet", "unbefristete", "unbefristeten", "festanstellung", "cdi",
             "duree indeterminee", "open ended", "regular full time", "regular part time"]
_MONTHS = re.compile(r"(?<!\w)(\d{1,2})\s*(?:-\s*)?(?:months?|monate?n?|mois)(?!\w)")
_MONTHS_CTX = ["contract", "vertrag", "contrat", "befrist", "duration", "dauer", "duree", "limited", "assignment",
               "mission", "for", "fur", "pour", "de", "von", "position", "role", "stelle", "poste", "einsatz"]


def contract_type(title: str, text: str, hint: str = "", agency_employer: bool = False) -> str:
    t = fold(f"{title}\n{hint}")
    d = fold(text)
    if agency_employer or has_term(t, AGENCY) or has_term(d, [a for a in AGENCY if a not in ("contractor",)]):
        return "temporary-agency"
    if has_term(t, FIXED) or has_term(d, FIXED):
        return "fixed-term"
    for m in _MONTHS.finditer(f"{t} {d}"):
        ctx = f"{t} {d}"[max(0, m.start() - 30): m.end() + 20]
        if 3 <= int(m.group(1)) <= 24 and has_term(ctx, _MONTHS_CTX) and not has_term(ctx, ["probation", "probezeit",
                                                                                              "periode d essai", "notice"]):
            return "fixed-term"
    if has_term(t, PERMANENT) or has_term(d, PERMANENT):
        return "permanent"
    return ""


# --- workload ------------------------------------------------------------------------------------

_RANGE = re.compile(r"(?<!\d)(\d{2,3})\s*%?\s*(?:-|–|bis|to|a|à)\s*(\d{2,3})\s*%")
_SINGLE = re.compile(r"(?<!\d)(\d{2,3})\s*%")
WORKLOAD_CTX = ["pensum", "arbeitspensum", "beschaftigungsgrad", "taux d activite", "taux d occupation", "taux",
                "workload", "work load", "employment level", "auslastung", "anstellungsgrad", "full time",
                "part time", "vollzeit", "teilzeit", "plein temps", "temps partiel", "degree of employment"]


def workload(title: str, text: str, hint: str = "") -> str:
    def ok(a: int, b: int | None = None) -> bool:
        return 10 <= a <= 100 and (b is None or (a < b <= 100))

    for src, need_ctx in ((title, False), (hint, False), (text, True)):
        s = (src or "").replace("–", "-")
        for m in _RANGE.finditer(s):
            a, b = int(m.group(1)), int(m.group(2))
            ctx = fold(s[max(0, m.start() - 60): m.end() + 30])
            if ok(a, b) and (not need_ctx or has_term(ctx, WORKLOAD_CTX)):
                return f"{a}-{b}%"
        for m in _SINGLE.finditer(s):
            a = int(m.group(1))
            ctx = fold(s[max(0, m.start() - 60): m.end() + 30])
            if ok(a) and (not need_ctx or has_term(ctx, WORKLOAD_CTX)) and not has_term(
                ctx, ["remote", "travel", "reise", "deplacement", "home office", "homeoffice", "teletravail", "bonus"]
            ):
                return f"{a}%"
    if has_term(fold(f"{title} {hint}"), ["full time", "vollzeit", "plein temps", "temps plein"]):
        return "100%"
    return ""


# --- salary -----------------------------------------------------------------------------------------

_AMOUNT = r"(\d{2,3}(?:['’ ,.]?\d{3})|\d{2,3}\s*k)"
_SAL_RANGE = re.compile(rf"(?:chf|fr\.)\s*{_AMOUNT}\s*(?:-|–|to|bis|a|à)\s*(?:chf\s*)?{_AMOUNT}"
                        rf"|{_AMOUNT}\s*(?:-|–|to|bis|a|à)\s*{_AMOUNT}\s*(?:chf)", re.I)


def _amount(s: str) -> int:
    s = s.lower().replace(" ", "")
    if s.endswith("k"):
        return int(s[:-1]) * 1000
    return int(re.sub(r"\D", "", s))


def salary(text: str, hint: str = "") -> tuple[str, str]:
    for src in (hint, text):
        m = _SAL_RANGE.search(src or "")
        if m:
            g = [x for x in m.groups() if x]
            lo, hi = _amount(g[0]), _amount(g[1])
            if 20_000 <= lo <= hi <= 1_000_000:
                return str(lo), str(hi)
    return "", ""


# --- remote --------------------------------------------------------------------------------------------


def remote(title: str, text: str, hint: str = "") -> str:
    h = fold(hint)
    if h:
        if "remote" in h:
            return "remote"
        if "hybrid" in h:
            return "hybrid"
        if any(w in h for w in ("onsite", "on site", "office")):
            return "onsite"
    t = fold(f"{title}\n{text}")
    if has_term(t, ["fully remote", "100 % remote", "100% remote", "remote first", "remote position",
                    "work from anywhere", "remote role"]):
        return "remote"
    if has_term(t, ["hybrid", "hybride", "home office", "homeoffice", "teletravail", "remote work", "mobile working",
                    "mobiles arbeiten", "flexible working location", "work from home"]):
        return "hybrid"
    return ""


# --- apply all ---------------------------------------------------------------------------------------------


def enrich(p: Posting, raw: RawPosting, emp: dict) -> Posting:
    text = p.description
    yrs = years_required(text)
    p.years_required = str(yrs) if yrs is not None else ""
    p.seniority = seniority(p.title, yrs)
    p.languages_required = languages_required(text)
    p.ad_language = ad_language(text)
    p.contract_type = contract_type(p.title, text, raw.contract_hint, bool(emp.get("agency")))
    p.workload = workload(p.title, text, raw.workload_hint)
    p.salary_min, p.salary_max = salary(text, raw.salary_hint)
    p.remote = remote(p.title, text, raw.remote_hint)
    return p
