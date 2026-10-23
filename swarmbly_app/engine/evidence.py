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
_DISAMBIGUATION = re.compile(r"(puede referirse a|may refer to|peut faire référence|"
                             r"pode referir-se|se refiere a varios)", re.I)

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
    if word.endswith("es") and len(word) > 5:
        return word[:-2]
    if word.endswith("s") and len(word) > 4:
        return word[:-1]
    return word


def relevant(item: str, text: str) -> bool:
    a = {_stem(w) for w in (_fold(x) for x in _WORD.findall(item)) if len(w) >= 4}
    b = {_stem(w) for w in (_fold(x) for x in _WORD.findall(text)) if len(w) >= 4}
    return bool(a & b)


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

    def url_for(self, item: str) -> str:
        params = {"action": "query", "format": "json", "utf8": "1",
                  "generator": "search", "gsrsearch": item, "gsrlimit": "1",
                  "prop": "extracts", "exintro": "1", "explaintext": "1",
                  "exsentences": "2", "redirects": "1"}
        return WIKI_API.format(lang=self.lang) + "?" + urllib.parse.urlencode(params)

    def lookup(self, item: str) -> dict[str, Any] | None:
        data = (self.fetch or _http_get_json)(self.url_for(item), self.timeout_s,
                                              self.user_agent)
        pages = ((data or {}).get("query") or {}).get("pages") or {}
        for page in pages.values():
            title = str(page.get("title") or "")
            text = " ".join(str(page.get("extract") or "").split())
            if (not title or not text or _DISAMBIGUATION.search(text)
                    or not relevant(item, f"{title} {text[:300]}")):
                return None
            if len(text) > self.max_chars:
                cut = text[: self.max_chars]
                text = cut[: cut.rfind(" ")] + " …" if " " in cut else cut
            return {"item": item, "title": title, "text": text,
                    "url": WIKI_PAGE.format(lang=self.lang,
                                            title=urllib.parse.quote(title.replace(" ", "_")))}
        return None


def gather(items: dict[int, str], provider: WikipediaEvidence,
           max_items: int = 24) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Evidence per item number, and a report of what was asked and used."""
    wanted = [(n, t) for n, t in sorted(items.items()) if qualifies(t)][:max_items]
    found: dict[int, dict[str, Any]] = {}
    errors: list[str] = []

    def one(pair):
        n, text = pair
        try:
            return n, provider.lookup(text), None
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
              "sources": [{"item": h["item"], "title": h["title"], "url": h["url"]}
                          for _, h in sorted(found.items())],
              "errors": sorted(set(errors))}
    return found, report


def render(evidence: dict[int, dict[str, Any]], lang: str) -> str:
    """The block added to a fragment, after its items."""
    if not evidence:
        return ""
    lines = [HEADER.get(lang, HEADER["en"])]
    for n, hit in sorted(evidence.items()):
        lines.append(f"- {hit['item']}: {hit['text']}")
    return "\n".join(lines)
