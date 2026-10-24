"""Context for answers produced on this device (P2e).

Two optional steps around LCE C1 retrieval, both decided here and run here:

1. **Query expansion** — the local model rewrites the question as search
   keywords in English plus the public entities it names (species, places,
   programmes). Spanish questions then reach English sources (a thesis, papers)
   that plain BM25 never matched. One short generation on the local model;
   nothing leaves the device.
2. **Public evidence for local answers** — when the user enabled public
   evidence, Wikipedia is asked about at most ``evidence.local_max_entities``
   entity names. Only those names are sent: never the question, never a
   passage. Names come from the question (scientific binomials, the entities
   the local model listed) and, as a bridge, from scientific binomials in the
   retrieved passages (species names are public nomenclature, not personal
   data); every name sent is listed in the answer's metadata.

The answer then gets two system blocks: the user's local sources ([1], [2]…)
and the public evidence ([W1], [W2]…), with an instruction to state both when
they differ (a thesis written before a reclassification, for instance).
"""

from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

BINOMIAL = re.compile(r"\b([A-Z][a-z]{3,})\s([a-z]{4,})\b")
# Capitalised words that start a binomial-looking pair but are not genera.
_NOT_GENUS = frozenset("""Para Como Cual Cuando Donde Desde Hasta Entre Sobre Segun Según Mientras
Esta Este Estos Estas Esto Aquel Dime Dame Escribe Explica Relaciona Indica Compara Cuantos Cuántos
Que Qué Quien Quién Porque Pero Also After Before During From Into Over Under With Within Without
This That These Those There Their They What When Where Which While Write Explain Compare Tell Give
Since Until Then Than Thus Hence Here Each Every Both Many Most Some Such Only Even""".split())
_NOT_EPITHET = frozenset("""species genus individuals population populations genome genomes support
lineage lineages samples sample clade data results analysis analyses mockingbirds islands island""".split())

EXPAND_SYSTEM = ("You turn a question into search terms. Reply with exactly one line and "
                 "nothing else.")
EXPAND_USER = ("Question: {q}\n\n"
               "Write 8 to 15 English search keywords for finding documents that answer it "
               "(translate the question's terms; add scientific names and synonyms). Then "
               "write ' || ' and up to 3 public named things the question mentions "
               "(species, places, programmes, organisations), in English, separated by ';'.\n"
               "Format: keyword, keyword, ... || name; name")


@dataclass
class Expansion:
    keywords: str = ""
    entities: list[str] = field(default_factory=list)
    raw: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"keywords": self.keywords, "entities": self.entities,
                **({"error": self.error} if self.error else {})}


def parse_expansion(text: str) -> Expansion:
    line = " ".join((text or "").strip().split())
    line = re.sub(r"^(keywords?|format)\s*:\s*", "", line, flags=re.I)
    if "||" in line:
        kw, ents = line.split("||", 1)
    else:
        kw, ents = line, ""
    kw = re.sub(r"\s*,\s*", ", ", kw.strip(" .|"))[:400]
    names = []
    for n in re.split(r"[;\n]", ents):
        n = n.strip(" .,'\"*-")
        n = re.sub(r"^(name|names)\s*:\s*", "", n, flags=re.I)
        if 3 <= len(n) <= 60 and n.lower() not in {"none", "n/a", "name"}:
            names.append(n)
    return Expansion(keywords=kw, entities=names[:3], raw=line[:600])


def expand_query(backend: Any, model: str, question: str,
                 timeout_tokens: int = 90) -> Expansion:
    """One short local generation; failures leave the question unexpanded."""
    try:
        result = backend.stream_chat(
            [{"role": "system", "content": EXPAND_SYSTEM},
             {"role": "user", "content": EXPAND_USER.format(q=question.strip()[:800])}],
            model=model, max_tokens=timeout_tokens, temperature=0.0)
        return parse_expansion(getattr(result, "text", "") or "")
    except Exception as exc:          # the answer must not depend on this step
        return Expansion(error=type(exc).__name__)


def binomials(text: str) -> list[str]:
    out = []
    for m in BINOMIAL.finditer(text or ""):
        genus, epithet = m.group(1), m.group(2)
        if genus in _NOT_GENUS or epithet in _NOT_EPITHET:
            continue
        name = f"{genus} {epithet}"
        if name not in out:
            out.append(name)
    return out


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def public_entities(question: str, expansion: Expansion,
                    sources: list[dict[str, Any]], max_n: int = 3) -> list[dict[str, str]]:
    """Names that may be sent to the public provider, with where each came from."""
    picked: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, origin: str) -> None:
        key = _fold(name)
        if len(picked) >= max_n or key in seen or len(name) < 3:
            return
        if any(key in s or s in key for s in seen):     # "Galapagos rail" ~ "rail"
            return
        seen.add(key)
        picked.append({"name": name, "from": origin})

    for b in binomials(question):
        add(b, "question")
    for e in expansion.entities:
        add(e, "question (local model)")
    for s in sources:                                   # bridge: species names only
        for b in binomials(s.get("text", "")):
            add(b, "local passage (scientific name)")
            break
    return picked


def focus_terms(expansion: Expansion, entity: str) -> list[str]:
    ent = {_fold(w) for w in re.findall(r"\w+", entity)}
    terms = []
    for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", expansion.keywords):
        f = _fold(w)
        if f not in ent and f not in terms and f not in {"galapagos", "thesis", "article",
                                                        "paper", "study", "island", "islands"}:
            terms.append(f)
    return terms[:12]


def public_evidence(entities: list[dict[str, str]], expansion: Expansion, provider: Any
                    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    errors: list[str] = []

    def one(ent):
        try:
            return provider.passages(ent["name"], focus_terms(expansion, ent["name"])), None
        except Exception as exc:
            return None, type(exc).__name__

    if entities:
        with ThreadPoolExecutor(max_workers=min(3, len(entities))) as pool:
            for ent, (hit, err) in zip(entities, pool.map(one, entities)):
                if hit:
                    hit["sent"] = ent["name"]
                    hit["from"] = ent["from"]
                    hits.append(hit)
                if err:
                    errors.append(err)
    report = {"provider": "wikipedia", "lang": getattr(provider, "lang", ""),
              "local_answer": True,
              "queried": [e["name"] for e in entities],
              "queried_from": entities,
              "used": len(hits),
              "sources": [{"item": h["sent"], "title": h["title"], "url": h["url"],
                           "query": h["sent"]} for h in hits],
              "errors": sorted(set(errors))}
    return hits, report


PUBLIC_HEAD = {
    "es": ("Evidencia pública (Wikipedia, consultada ahora; solo se enviaron estos nombres: {names}). "
           "Úsala para los datos públicos y cítala como [W1], [W2]…. Si difiere de las fuentes "
           "locales (por ejemplo, porque cambió con el tiempo), di las dos versiones y cuál es la "
           "más reciente:"),
    "en": ("Public evidence (Wikipedia, fetched now; only these names were sent: {names}). Use it "
           "for public facts and cite it as [W1], [W2]…. If it differs from the local sources (for "
           "instance because it changed over time), give both and say which is more recent:"),
}


def render_public(hits: list[dict[str, Any]], lang: str) -> str:
    if not hits:
        return ""
    names = ", ".join(h["sent"] for h in hits)
    lines = [PUBLIC_HEAD.get(lang, PUBLIC_HEAD["en"]).format(names=names)]
    for i, h in enumerate(hits, 1):
        lines.append(f"[W{i}] ({h['title']}) {h['text']}")
    return "\n".join(lines)
