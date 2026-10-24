"""Public evidence for the items of a batch (P2 prototype; off by default).

Several small models can agree on the same wrong answer ("Piquero de patas
azules → pez", "Pingüino de Galápagos → mamífero" in P3b–P3l): a vote cannot
fix an error the voters share. This module looks up a short public
description of each item and the orchestrator adds it to that item's
fragment, so every worker reads the same evidence.

Rules (preregistered in the P2 note of the P3b document):

- **Off by default** (``evidence.enabled``). Turning it on is the user's
  consent to send *item texts* — never the request — to the provider.
- **Public requests only**: the orchestrator calls this module only when the
  request's lane is PUBLIC and the batch is enumerated.
- **Items that name something**: an item qualifies if it has a word of three
  or more letters and is either several words long or capitalised
  ("Piquero de patas azules", "Ecuador"); single lower-case words ("perro")
  and quantities ("1500 m") are not looked up.
- **Relevance gate**: a result is used only if its title or lead shares a
  word of four or more letters with the item (titles are often scientific
  names: "Sula nebouxii" for "Piquero de patas azules"); disambiguation
  pages ("puede referirse a:") are not evidence.
- **Provider**: Wikipedia (MediaWiki Action API, in the request's
  language), first two sentences of the lead, attributed. No API key.

Failures (network, timeout, no result) leave the fragment unchanged; the
metadata says what was looked up and what was used.

**Operation-aware lookups** (P2d, after P2c showed homonyms and neighbouring
facts misleading answers the network already got right):

- the batch operation ("Para cada uno de los siguientes animales, indica…
  si es mamífero, ave…") gives a **topic** ("animal") and **focus** terms
  ("mamífero", "capital", "símbolo", "autor", "año");
- a result must mention the topic or a focus term (or a year, when the
  focus is a year; a writer, when it is an author). If the item alone does
  not give such an article ("Cecilia" → the first name), the search is
  repeated with the topic ("Cecilia animal" → Gymnophiona) and that result
  must pass the same check;
- the snippet is the article's first sentence plus the first sentence that
  carries a focus term ("…su capital es Abuya"), instead of always the first
  two;
- translation batches are not looked up (the items name nothing).
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
WIKI_PAGE = "https://{lang}.wikipedia.org/wiki/{title}"
SUPPORTED_LANGS = ("es", "en", "pt", "fr")

_WORD = re.compile(r"[^\W\d_]+", re.U)
_DISAMBIGUATION = re.compile(r"(puede referirse a|puede hacer referencia a|may refer to|"
                             r"peut faire référence|pode referir-se|se refiere a varios)", re.I)

HEADER = {
    "es": "Contexto público (Wikipedia) sobre algunos elementos; úsalo solo si es pertinente:",
    "en": "Public context (Wikipedia) about some items; use it only if relevant:",
    "pt": "Contexto público (Wikipédia) sobre alguns itens; use-o apenas se for pertinente:",
    "fr": "Contexte public (Wikipédia) sur certains éléments ; utilise-le seulement s'il est pertinent :",
}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                   if unicodedata.category(c) != "Mn")


def qualifies(item: str) -> bool:
    words = _WORD.findall(item or "")
    if not any(len(w) >= 3 for w in words):
        return False
    return len(words) >= 2 or (words[0][:1].isupper() if words else False)


def _stem(word: str) -> str:
    """Singular-ish form, so "tortuga" meets "tortugas" and "tiburón" meets
    "tiburones"."""
    if word.endswith("ces") and len(word) > 4:      # peces → pez, luces → luz
        return word[:-3] + "z"
    if word.endswith("es") and len(word) > 5:
        return word[:-2]
    if word.endswith("s") and len(word) > 3:       # aves → ave
        return word[:-1]
    return word


def relevant(item: str, text: str) -> bool:
    a = {_stem(w) for w in (_fold(x) for x in _WORD.findall(item)) if len(w) >= 4}
    b = {_stem(w) for w in (_fold(x) for x in _WORD.findall(text)) if len(w) >= 4}
    return bool(a & b)


_STOP = frozenset(_fold(w) for w in (
    "para cada uno una unos unas los las del de la el en su sus si es o y u a al "
    "que por con sin solo sola indica indicar da dar escribe di dime nombre nombres "
    "palabra palabras siguientes siguiente following each for the of a an in its "
    "only one word give write name answer what which is are it this that its "
    "ocurrio ocurrió occurred happened se").split())
_TRANSLATION = re.compile(r"\b(tradu\w*|translat\w*|tradui\w*)", re.I)
_TOPIC = re.compile(r"(?:siguientes|following|seguintes|suivant(?:e)?s)\s+([^,:;]+?)"
                    r"(?:\s+en\s+\w+)?\s*[,:;]", re.I)
_YEAR = re.compile(r"\b(1\d{3}|20\d{2})\b")
_AUTHOR = frozenset({"autor", "autora", "escritor", "escritora", "novelista", "poeta",
                     "poetisa", "dramaturgo", "escrita", "escrito", "author", "writer",
                     "novelist", "poet", "ecrivain", "auteur", "escritor"})


@dataclass
class OperationProfile:
    topic: list[str]                    # stems of the topic noun phrase
    focus: list[str]                    # stems of what is asked
    translation: bool = False
    query_topic: str = ""               # singular topic phrase for a retry

    @property
    def wants_year(self) -> bool:
        return "ano" in self.focus or "year" in self.focus or "date" in self.focus

    @property
    def wants_author(self) -> bool:
        return any(f in ("autor", "author", "auteur") for f in self.focus)

    def to_dict(self) -> dict[str, Any]:
        return {"topic": self.query_topic, "focus": self.focus,
                "translation": self.translation}


def _singular(phrase: str) -> str:
    out = []
    for w in phrase.split():
        f = w.lower()
        if f.endswith(("íses", "eses")) or (f.endswith("es") and len(f) > 5
                                             and f[-3] in "lrndz"):
            w = w[:-2]
        elif f.endswith("s") and len(f) > 3:
            w = w[:-1]
        out.append(w)
    return " ".join(out)


def operation_profile(preamble: str) -> OperationProfile:
    """Topic and focus of a batch operation ("…siguientes países, indica…
    su capital" → topic "país", focus "capital")."""
    text = " ".join((preamble or "").split())
    match = _TOPIC.search(text)
    topic_phrase = match.group(1).strip() if match else ""
    rest = text[match.end():] if match else text
    words = lambda t: [_stem(_fold(w)) for w in _WORD.findall(t)
                       if _fold(w) not in _STOP and len(w) >= 3]
    topic = words(topic_phrase)
    # "su símbolo químico" for "elementos químicos": "químico" is the topic,
    # only "símbolo" is what is asked (P2d dry run: a first sentence with
    # "elemento químico de número atómico 47" passed as the focus sentence).
    focus = [w for w in words(rest) if w not in topic]
    return OperationProfile(topic=topic, focus=focus,
                            translation=bool(_TRANSLATION.search(text)),
                            query_topic=_singular(topic_phrase))


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡(«\"])", text)
    return [p.strip() for p in parts if p.strip()]


def _mentions(profile: OperationProfile, text: str) -> bool:
    stems = {_stem(_fold(w)) for w in _WORD.findall(text)}
    if stems & set(profile.topic) or stems & set(profile.focus):
        return True
    if profile.wants_year and _YEAR.search(text):
        return True
    return profile.wants_author and bool(stems & {_stem(a) for a in _AUTHOR})


def _focus_sentence(profile: OperationProfile, sentence: str) -> bool:
    stems = {_stem(_fold(w)) for w in _WORD.findall(sentence)}
    if stems & set(profile.focus):
        return True
    if profile.wants_year and _YEAR.search(sentence):
        return True
    return profile.wants_author and bool(stems & {_stem(a) for a in _AUTHOR})


def _http_get_json(url: str, timeout_s: float, user_agent: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:   # noqa: S310 (fixed host)
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class WikipediaEvidence:
    lang: str = "es"
    timeout_s: float = 4.0
    max_chars: int = 220
    user_agent: str = "SwarmblyApp (https://github.com/Sebastardito/SwarmblyApp)"
    fetch: Callable[[str, float, str], Any] | None = None   # injectable for tests

    def url_for(self, query: str, sentences: int | None = 2) -> str:
        params = {"action": "query", "format": "json", "utf8": "1",
                  "generator": "search", "gsrsearch": query, "gsrlimit": "1",
                  "prop": "extracts", "exintro": "1", "explaintext": "1",
                  "redirects": "1"}
        if sentences:
            params["exsentences"] = str(sentences)
        return WIKI_API.format(lang=self.lang) + "?" + urllib.parse.urlencode(params)

    def _page(self, query: str, sentences: int | None):
        data = (self.fetch or _http_get_json)(self.url_for(query, sentences),
                                              self.timeout_s, self.user_agent)
        pages = ((data or {}).get("query") or {}).get("pages") or {}
        for page in pages.values():
            title = str(page.get("title") or "")
            text = " ".join(str(page.get("extract") or "").split())
            if title and text and not _DISAMBIGUATION.search(text):
                return title, text
        return None

    def _cut(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        cut = text[: self.max_chars]
        return cut[: cut.rfind(" ")] + " …" if " " in cut else cut

    def lookup(self, item: str, profile: OperationProfile | None = None) -> dict[str, Any] | None:
        if profile is None:                       # P2a behaviour
            page = self._page(item, 2)
            if not page or not relevant(item, f"{page[0]} {page[1][:300]}"):
                return None
            title, text = page
            return self._hit(item, item, title, self._cut(text))
        queries = [item]
        if profile.query_topic:
            queries.append(f"{item} {profile.query_topic}")
        for query in queries:
            page = self._page(query, None)        # whole lead: pick the sentence
            if not page:
                continue
            title, text = page
            head = f"{title} {text[:600]}"
            if not relevant(item, head) or not _mentions(profile, head):
                continue
            sentences = _sentences(text)
            first = sentences[0] if sentences else text
            focus = next((x for x in sentences[1:] if _focus_sentence(profile, x)), "")
            if _focus_sentence(profile, first) or not focus:
                snippet = self._around_focus(profile, first)
            else:
                snippet = f"{first} {focus}"
                if len(snippet) > self.max_chars:
                    snippet = self._around_focus(profile, focus)   # the asked-for fact
            return self._hit(item, query, title, self._cut(snippet))
        return None

    def _around_focus(self, profile: OperationProfile, sentence: str) -> str:
        """A long sentence is cut around its first focus term, so the cut
        does not drop the asked-for fact ("…el mayor animal" without
        "mamífero", P2d dry run)."""
        if len(sentence) <= self.max_chars:
            return sentence
        pos = None
        for m in _WORD.finditer(sentence):
            if _stem(_fold(m.group(0))) in profile.focus:
                pos = m.start()
                break
        if pos is None and profile.wants_year:
            year = _YEAR.search(sentence)
            pos = year.start() if year else None
        if pos is None or pos < self.max_chars - 40:
            return sentence
        start = sentence.rfind(" ", 0, max(0, pos - self.max_chars // 3)) + 1
        return "… " + sentence[start:]

    def _hit(self, item: str, query: str, title: str, text: str) -> dict[str, Any]:
        return {"item": item, "query": query, "title": title, "text": text,
                "url": WIKI_PAGE.format(lang=self.lang,
                                        title=urllib.parse.quote(title.replace(" ", "_")))}


def gather(items: dict[int, str], provider: WikipediaEvidence,
           max_items: int = 24, profile: OperationProfile | None = None
           ) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Evidence per item number, and a report of what was asked and used."""
    if profile is not None and profile.translation:
        return {}, {"provider": "wikipedia", "lang": provider.lang, "queried": [],
                    "used": 0, "sources": [], "errors": [],
                    "skipped": "translation batch: its items name nothing",
                    "operation": profile.to_dict()}
    wanted = [(n, t) for n, t in sorted(items.items()) if qualifies(t)][:max_items]
    found: dict[int, dict[str, Any]] = {}
    errors: list[str] = []

    def one(pair):
        n, text = pair
        try:
            return n, provider.lookup(text, profile), None
        except Exception as exc:          # network, timeout, bad JSON
            return n, None, f"{type(exc).__name__}"

    if wanted:
        with ThreadPoolExecutor(max_workers=min(6, len(wanted))) as pool:
            for n, hit, err in pool.map(one, wanted):
                if hit:
                    found[n] = hit
                if err:
                    errors.append(err)
    report = {"provider": "wikipedia", "lang": provider.lang,
              "queried": [t for _, t in wanted], "used": len(found),
              "sources": [{"item": h["item"], "title": h["title"], "url": h["url"],
                           "query": h.get("query", h["item"])}
                          for _, h in sorted(found.items())],
              "errors": sorted(set(errors))}
    if profile is not None:
        report["operation"] = profile.to_dict()
        report["retried"] = sum(1 for h in found.values()
                                if h.get("query", h["item"]) != h["item"])
    return found, report


def render(evidence: dict[int, dict[str, Any]], lang: str) -> str:
    """The block added to a fragment, after its items."""
    if not evidence:
        return ""
    lines = [HEADER.get(lang, HEADER["en"])]
    for n, hit in sorted(evidence.items()):
        lines.append(f"- {hit['item']}: {hit['text']}")
    return "\n".join(lines)
