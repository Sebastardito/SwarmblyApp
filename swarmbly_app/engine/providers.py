"""Public evidence providers beyond Wikipedia (P2e follow-up).

Wikipedia prose answered statuses and dates badly in P2e (a Spanish article
with no IUCN status; an island article full of unrelated years). Here:

- **Wikidata** (official API, free): structured facts with their property —
  IUCN conservation status (P141), dates of death, birth, inception, start,
  end, discovery, publication. One short sentence per entity.
- **PubMed** (NCBI E-utilities, official, free): sentences from article
  abstracts that carry the asked terms or a year — scientific facts such as
  a first record.
- **SearXNG** (optional, the user's own instance): a free metasearch engine
  that queries DuckDuckGo, Google, Bing, Google Scholar… on the user's behalf;
  snippets of the top results.
- **Google Custom Search** (optional, the user's API key and engine id).

Same privacy rule as Wikipedia: only entity names (and generic English focus
words such as "first record") are sent, never the question or a passage.
Every provider is injectable (``fetch``) for tests and fails closed: an
error means no evidence, never a broken answer.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable

from .evidence import _WORD, _YEAR, _fold, _sentences, _stem

USER_AGENT = "SwarmblyApp (https://github.com/Sebastardito/SwarmblyApp)"
Fetch = Callable[[str, float, str], Any]


def _get(url: str, timeout_s: float, user_agent: str) -> Any:
    """JSON, or the raw text for XML answers (PubMed efetch)."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                               "Accept": "application/json, text/xml"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:   # noqa: S310 (fixed hosts)
        body = resp.read().decode("utf-8", "replace")
    return body if "retmode=xml" in url else json.loads(body)


def _shares_word(a: str, b: str) -> bool:
    wa = {_stem(_fold(w)) for w in _WORD.findall(a) if len(w) >= 4}
    wb = {_stem(_fold(w)) for w in _WORD.findall(b) if len(w) >= 4}
    return bool(wa & wb)


# --- Wikidata ------------------------------------------------------------------
STATUS_PROPS = ("P141",)
DATE_PROPS = ("P570", "P569", "P571", "P580", "P576", "P582", "P575", "P577", "P585")
PROP_LABEL = {
    "es": {"P141": "estado de conservación UICN", "P570": "fecha de muerte",
           "P569": "fecha de nacimiento", "P571": "fecha de fundación o creación",
           "P580": "fecha de inicio", "P576": "fecha de disolución o fin",
           "P582": "fecha de fin", "P575": "fecha de descubrimiento",
           "P577": "fecha de publicación", "P585": "fecha"},
    "en": {"P141": "IUCN conservation status", "P570": "date of death",
           "P569": "date of birth", "P571": "inception", "P580": "start time",
           "P576": "dissolved or ended", "P582": "end time", "P575": "time of discovery",
           "P577": "publication date", "P585": "point in time"},
}
# Spanish event words (folded prefixes) → the date property that answers them.
EVENT_PROPS = {
    "muerte": ("P570",), "fallec": ("P570",), "nacimiento": ("P569",),
    "inicio": ("P571", "P580"), "comienzo": ("P571", "P580"), "fundacion": ("P571",),
    "creacion": ("P571",), "fin": ("P582", "P576"), "disolucion": ("P576",),
    "descubrimiento": ("P575",), "publicacion": ("P577",),
}
_STATUS_WORDS = {"iucn", "uicn", "status", "conservation", "conservacion", "threatened",
                 "endangered", "vulnerable", "amenaza", "categoria", "roja"}


def wanted_props(focus: list[str], item: str = "") -> tuple[str, ...]:
    folded = {_stem(_fold(f)) for f in focus}
    props: list[str] = []
    if folded & {_stem(w) for w in _STATUS_WORDS}:
        props += STATUS_PROPS
    if "__year__" in focus:
        words = [_fold(w) for w in _WORD.findall(item)]
        event = [p for w in words for k, ps in EVENT_PROPS.items() if w.startswith(k) for p in ps]
        props += event or list(DATE_PROPS)
    return tuple(dict.fromkeys(props))


@dataclass
class WikidataProvider:
    lang: str = "es"
    timeout_s: float = 4.0
    fetch: Fetch | None = None
    user_agent: str = USER_AGENT
    name: str = "wikidata"
    api: str = "https://www.wikidata.org/w/api.php"

    def _call(self, **params) -> Any:
        params.update({"format": "json"})
        return (self.fetch or _get)(self.api + "?" + urllib.parse.urlencode(params),
                                    self.timeout_s, self.user_agent)

    def facts(self, entity: str, props: tuple[str, ...]) -> dict[str, Any] | None:
        if not props:
            return None
        found = self._call(action="wbsearchentities", search=entity, language="en",
                           uselang=self.lang, type="item", limit="1").get("search") or []
        if not found:
            return None
        hit = found[0]
        label = (hit.get("display", {}).get("label", {}) or {}).get("value") or hit.get("label", "")
        matched = (hit.get("match") or {}).get("text", "")
        if not (_shares_word(entity, label) or _shares_word(entity, matched)):
            return None
        qid = hit["id"]
        ent = self._call(action="wbgetentities", ids=qid, props="claims|labels|descriptions",
                         languages=f"{self.lang}|en").get("entities", {}).get(qid, {})
        claims = ent.get("claims", {})
        parts, value_ids = [], []
        for prop in props:
            for claim in claims.get(prop, [])[:1]:
                value = (claim.get("mainsnak", {}).get("datavalue") or {}).get("value")
                if isinstance(value, dict) and "id" in value:
                    value_ids.append(value["id"])
                    parts.append((prop, value["id"]))
                elif isinstance(value, dict) and "time" in value:
                    m = re.match(r"[+-]?(\d{1,4})-(\d{2})-(\d{2})", value["time"])
                    if m:
                        y, mo, d = m.groups()
                        date = y if value.get("precision", 11) < 11 or (mo, d) == ("00", "00") \
                            else f"{int(d)}/{int(mo)}/{y}"
                        parts.append((prop, date))
        if not parts:
            return None
        names = {}
        if value_ids:
            got = self._call(action="wbgetentities", ids="|".join(value_ids), props="labels",
                             languages=f"{self.lang}|en").get("entities", {})
            for vid, data in got.items():
                labels = data.get("labels", {})
                names[vid] = (labels.get(self.lang) or labels.get("en") or {}).get("value", vid)
        title = ((ent.get("labels", {}).get(self.lang) or ent.get("labels", {}).get("en") or {})
                 .get("value") or label)
        desc = ((ent.get("descriptions", {}).get(self.lang) or ent.get("descriptions", {}).get("en")
                 or {}).get("value", ""))
        plabel = PROP_LABEL.get(self.lang, PROP_LABEL["en"])
        facts = "; ".join(f"{plabel.get(p, p)}: {names.get(v, v)}" for p, v in parts)
        text = f"{title}{f' ({desc})' if desc else ''} — {facts}."
        return {"item": entity, "query": entity, "title": f"Wikidata: {title}",
                "text": text, "url": f"https://www.wikidata.org/wiki/{qid}", "provider": "wikidata"}


# --- PubMed ----------------------------------------------------------------------
@dataclass
class PubMedProvider:
    timeout_s: float = 6.0
    fetch: Fetch | None = None
    user_agent: str = USER_AGENT
    name: str = "pubmed"
    max_chars: int = 600
    base: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def passages(self, entity: str, focus: list[str]) -> dict[str, Any] | None:
        fetch = self.fetch or _get
        terms = [f for f in focus if f != "__year__" and len(f) >= 4][:3]
        query = f'"{entity}"' + (" AND (" + " OR ".join(terms) + ")" if terms else "")
        ids = self._ids(query) or (self._ids(f'"{entity}"') if terms else [])
        if not ids:
            return None
        xml = fetch(self.base + "efetch.fcgi?" + urllib.parse.urlencode(
            {"db": "pubmed", "id": ",".join(ids), "rettype": "abstract", "retmode": "xml",
             "tool": "SwarmblyApp"}), self.timeout_s, self.user_agent)
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return None
        stems = {_stem(_fold(t)) for t in terms}
        want_year = "__year__" in focus
        best = None
        for art in root.iter("PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            title = (art.findtext(".//ArticleTitle") or "").strip()
            year = art.findtext(".//PubDate/Year") or ""
            abstract = " ".join("".join(t.itertext()) for t in art.iter("AbstractText"))
            if not _shares_word(entity, f"{title} {abstract}"):
                continue
            chosen = []
            for sent in _sentences(abstract):
                words = {_stem(_fold(w)) for w in _WORD.findall(sent)}
                score = len(words & stems) + (2 if want_year and _YEAR.search(sent) else 0)
                if score:
                    chosen.append((score, sent))
            chosen.sort(key=lambda x: -x[0])
            if chosen and (best is None or chosen[0][0] > best[0]):
                text = " ".join(s for _, s in chosen[:2])
                if len(text) > self.max_chars:
                    text = text[: self.max_chars].rsplit(" ", 1)[0] + " …"
                best = (chosen[0][0], {"item": entity, "query": query,
                                       "title": f"PubMed {pmid}: {title[:90]} ({year})",
                                       "text": text, "provider": "pubmed",
                                       "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
        return best[1] if best else None

    def _ids(self, query: str) -> list[str]:
        data = (self.fetch or _get)(self.base + "esearch.fcgi?" + urllib.parse.urlencode(
            {"db": "pubmed", "term": query, "retmode": "json", "retmax": "3",
             "sort": "relevance", "tool": "SwarmblyApp"}), self.timeout_s, self.user_agent)
        return ((data or {}).get("esearchresult") or {}).get("idlist") or []


# --- Web search (optional) ---------------------------------------------------------
@dataclass
class WebSearchProvider:
    """SearXNG instance (``url``) or Google Custom Search (``key`` + ``cx``)."""
    url: str = ""
    key: str = ""
    cx: str = ""
    lang: str = "es"
    timeout_s: float = 6.0
    fetch: Fetch | None = None
    user_agent: str = USER_AGENT
    max_chars: int = 500

    @property
    def name(self) -> str:
        return "searxng" if self.url else "google"

    def passages(self, entity: str, focus: list[str]) -> dict[str, Any] | None:
        terms = [f for f in focus if f != "__year__" and len(f) >= 4][:3]
        q = " ".join([entity, *terms])
        fetch = self.fetch or _get
        if self.url:
            data = fetch(self.url.rstrip("/") + "/search?" + urllib.parse.urlencode(
                {"q": q, "format": "json", "language": self.lang}), self.timeout_s, self.user_agent)
            results = [(r.get("title", ""), r.get("content", ""), r.get("url", ""))
                       for r in (data or {}).get("results", [])[:5]]
        elif self.key and self.cx:
            data = fetch("https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(
                {"key": self.key, "cx": self.cx, "q": q, "num": "5"}), self.timeout_s, self.user_agent)
            results = [(r.get("title", ""), r.get("snippet", ""), r.get("link", ""))
                       for r in (data or {}).get("items", [])[:5]]
        else:
            return None
        stems = {_stem(_fold(t)) for t in terms}
        want_year = "__year__" in focus
        for title, content, link in results:
            if not _shares_word(entity, f"{title} {content}"):
                continue
            words = {_stem(_fold(w)) for w in _WORD.findall(content)}
            if stems and not (words & stems) and not (want_year and _YEAR.search(content)):
                continue
            text = content if len(content) <= self.max_chars else \
                content[: self.max_chars].rsplit(" ", 1)[0] + " …"
            return {"item": entity, "query": q, "title": f"{self.name}: {title[:90]}",
                    "text": text, "url": link, "provider": self.name}
        return None


# --- Composite ---------------------------------------------------------------------
_EVENT_PREFIXES = tuple(EVENT_PROPS) + ("extirpacion", "extincion", "proteccion", "registro",
                                         "llegada", "erupcion", "declaracion")


def _names_only(item: str) -> str:
    """'Muerte del Solitario George' → 'Solitario George' (an event's proper names)."""
    words = _WORD.findall(item)
    if not words or not _fold(words[0]).startswith(_EVENT_PREFIXES):
        return item
    names = [w for w in words[1:] if len(w) >= 3 and w[:1].isupper()]
    return " ".join(names) or item


@dataclass
class MultiProvider:
    """Wikidata for structured facts, Wikipedia for prose, PubMed for science,
    and the optional web search; each only when enabled."""
    wikipedia: Any
    wikidata: WikidataProvider | None = None
    pubmed: PubMedProvider | None = None
    web: WebSearchProvider | None = None

    @property
    def lang(self) -> str:
        return getattr(self.wikipedia, "lang", "")

    @property
    def names(self) -> list[str]:
        return [p for p, on in (("wikidata", self.wikidata), ("wikipedia", self.wikipedia),
                                ("pubmed", self.pubmed), ("web", self.web)) if on]

    def lookup(self, item: str, profile) -> dict[str, Any] | None:
        """Batch items: a structured fact when the operation asks for a status or
        a date and Wikidata has it; otherwise Wikipedia (with its fallback)."""
        if self.wikidata is not None and profile is not None:
            focus = list(profile.focus) + (["__year__"] if profile.wants_year else [])
            entity = _names_only(item)
            props = wanted_props(focus, item)
            if props:
                try:
                    fact = self.wikidata.facts(entity, props)
                except Exception:
                    fact = None
                if fact:
                    fact["item"] = item
                    return fact
        return self.wikipedia.lookup(item, profile) if self.wikipedia is not None else None

    def passages(self, entity: str, focus: list[str]) -> list[dict[str, Any]]:
        """Local answers: every enabled provider that has something."""
        hits = []
        calls = []
        if self.wikidata is not None:
            calls.append(lambda: self.wikidata.facts(entity, wanted_props(focus, entity)))
        if self.wikipedia is not None:
            calls.append(lambda: self.wikipedia.passages(entity, focus))
        if self.pubmed is not None:
            calls.append(lambda: self.pubmed.passages(entity, focus))
        if self.web is not None:
            calls.append(lambda: self.web.passages(entity, focus))
        for call in calls:
            try:
                hit = call()
            except Exception:
                hit = None
            if hit:
                hits.append(hit)
        return hits


def build(lang: str, ev_cfg: dict[str, Any], wikipedia: Any) -> MultiProvider:
    enabled = set(ev_cfg.get("providers") or ["wikidata", "wikipedia", "pubmed"])
    timeout = float(ev_cfg.get("timeout_s", 4.0))
    web = None
    if "web" in enabled and (ev_cfg.get("searxng_url") or
                             (ev_cfg.get("google_cse_key") and ev_cfg.get("google_cse_cx"))):
        web = WebSearchProvider(url=str(ev_cfg.get("searxng_url") or ""),
                                key=str(ev_cfg.get("google_cse_key") or ""),
                                cx=str(ev_cfg.get("google_cse_cx") or ""), lang=lang,
                                timeout_s=max(timeout, 6.0))
    return MultiProvider(
        wikipedia=wikipedia if "wikipedia" in enabled else None,
        wikidata=WikidataProvider(lang=lang, timeout_s=timeout) if "wikidata" in enabled else None,
        pubmed=PubMedProvider(timeout_s=max(timeout, 6.0)) if "pubmed" in enabled else None,
        web=web)
