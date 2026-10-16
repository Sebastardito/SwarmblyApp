"""Composition planner (P1): the local model plans a long text; workers write sections.

A single composition — an essay, a speech, a report of N words — has no
enumerated structure to split, and P0 stopped splitting it by accident. It
does have a structure the request implies: an opening, a few lines of
argument, a closing, sometimes a table. This module makes that structure
explicit *on this device*:

1. **Outline** — the local model reads the whole request and returns a JSON
   outline: title, topic, style line, and 3–6 sections, each with a purpose,
   a word budget, key points, the explicit requirements that belong to it
   ("open with the presenter", "a summary table") and a kind (prose/table).
   The code validates it; if the model's output is not usable, a
   deterministic outline is used instead, and the monitor says so.
2. **Sections** — every section becomes one micro-task. Its packet carries
   Γ (minimised), the title, the topic, its own brief and its position — not
   the request. That is the decontextualisation the SPEC asks for: a worker
   sees one section's brief, never the instruction list, the rubric or the
   other sections' requirements.
3. **Assembly** — sections are joined in order under the title. Workers
   write their own opening transition (the brief asks for one); no bridges
   are generated, because the upstream bridge prompt is English.
4. **Requirement check** — every ``must_include`` of the outline is checked
   against the final text and reported (found / not found). It is a lexical
   check, not a judgement of quality.

The local model never writes the answer here; it only plans. Whether this
beats one local model writing the whole text is an open question that P3.2
measures (preregistered); nothing in this module assumes it does.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

MIN_SECTIONS = 3
MIN_SECTION_WORDS = 60
TABLE_SECTION_WORDS = 120
OUTLINE_MAX_TOKENS = 900

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French"}
_TABLE_CUE = re.compile(r"\b(tablas?|tables?|tabelas?|tableaux?|tabla de resumen)\b", re.I)
_BULLET = re.compile(r"^\s*[-*•]\s+(.+?)\s*$", re.M)
_HEADING_LINE = re.compile(r"^\s*(#{1,6}\s+.*|\*\*[^*]{1,120}\*\*\s*:?)\s*$")


@dataclass
class Section:
    heading: str
    purpose: str
    words: int
    key_points: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    kind: str = "prose"                 # prose | table

    def to_dict(self) -> dict[str, Any]:
        return {"heading": self.heading, "purpose": self.purpose, "words": self.words,
                "key_points": list(self.key_points),
                "must_include": list(self.must_include), "kind": self.kind}


@dataclass
class Outline:
    title: str
    topic: str
    style: str
    sections: list[Section]
    source: str                         # local_model | fallback
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "topic": self.topic, "style": self.style,
                "source": self.source, "errors": list(self.errors),
                "sections": [s.to_dict() for s in self.sections]}


# -- outline -----------------------------------------------------------------------
def outline_prompt(prompt: str, lang: str, target_words: int, max_sections: int) -> str:
    language = LANGUAGE_NAMES.get(lang, "the language of the request")
    return (
        "You are planning a long text before it is written. Read the request and "
        "return ONLY a JSON object, with no commentary and no code fence.\n\n"
        f"Request:\n<<<\n{prompt.strip()}\n>>>\n\n"
        f"Return this JSON, with every value written in {language}:\n"
        '{"title": "...", "topic": "short topic phrase", '
        '"style": "one line: register, tone, voice and formatting rules from the request", '
        '"sections": [{"heading": "...", "purpose": "what this section does", '
        '"words": 150, "key_points": ["short phrase", "short phrase"], '
        '"must_include": ["explicit requirement of the request that belongs here"], '
        '"kind": "prose"}]}\n\n'
        "Rules:\n"
        f"- {MIN_SECTIONS} to {max_sections} sections; their words add up to about "
        f"{target_words}.\n"
        "- The first section opens the text; the last section closes it.\n"
        "- Put each explicit requirement of the request (people, how to open, tables, "
        "examples, how to close) in the must_include of the one section where it "
        "belongs.\n"
        '- If the request asks for tables, add a section with "kind": "table".\n'
        "- key_points are short phrases. Do not invent figures or statistics.\n"
    )


def _json_block(raw: str) -> Any:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.M)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the outline")
    body = text[start:end + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", body))   # trailing commas


def _strings(value: Any, limit: int, max_chars: int = 160) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = [" ".join(str(v).split())[:max_chars] for v in value
           if isinstance(v, (str, int, float)) and str(v).strip()]
    return out[:limit]


def _rescale(sections: list[Section], target_words: int) -> None:
    """Prose sections share ``target_words``; table sections keep a fixed size."""
    prose = [s for s in sections if s.kind != "table"]
    if not prose:
        return
    budget = max(MIN_SECTION_WORDS * len(prose),
                 target_words - TABLE_SECTION_WORDS * (len(sections) - len(prose)))
    total = sum(max(1, s.words) for s in prose)
    for s in prose:
        s.words = max(MIN_SECTION_WORDS, round(budget * max(1, s.words) / total))
    for s in sections:
        if s.kind == "table":
            s.words = TABLE_SECTION_WORDS


def parse_outline(raw: str, *, target_words: int, max_sections: int) -> Outline:
    """Validate the local model's outline; raises ``ValueError`` when unusable."""
    data = _json_block(raw)
    if not isinstance(data, dict):
        raise ValueError("the outline is not a JSON object")
    items = data.get("sections")
    if not isinstance(items, list):
        raise ValueError("the outline has no section list")
    sections: list[Section] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        heading = " ".join(str(item.get("heading") or "").split())[:120]
        purpose = " ".join(str(item.get("purpose") or "").split())[:240]
        if not heading:
            continue
        try:
            words = int(float(item.get("words") or 0))
        except (TypeError, ValueError):
            words = 0
        kind = "table" if (str(item.get("kind") or "").lower() == "table"
                           or _TABLE_CUE.search(heading)) else "prose"
        sections.append(Section(heading=heading, purpose=purpose or heading,
                                words=words, key_points=_strings(item.get("key_points"), 5),
                                must_include=_strings(item.get("must_include"), 4),
                                kind=kind))
    if len(sections) < MIN_SECTIONS:
        raise ValueError(f"the outline has {len(sections)} usable sections "
                         f"(minimum {MIN_SECTIONS})")
    sections = sections[:max_sections]
    if sections[0].kind == "table" or sections[-1].kind == "table":
        prose = [s for s in sections if s.kind != "table"]
        tables = [s for s in sections if s.kind == "table"]
        if len(prose) < 2:
            raise ValueError("the outline has no prose opening and closing")
        sections = prose[:-1] + tables + prose[-1:]   # tables before the closing
    _rescale(sections, target_words)
    return Outline(title=" ".join(str(data.get("title") or "").split())[:160],
                   topic=" ".join(str(data.get("topic") or "").split())[:160],
                   style=" ".join(str(data.get("style") or "").split())[:240],
                   sections=sections, source="local_model")


_STYLE_CUE = re.compile(r"\b(tono|registro|estilo|voz|persona|lenguaje|español|neutro|tone|"
                        r"register|style|voice|plain|formal|informal|tom|estilo|ton|registre)\b",
                        re.I)
_ANGLES = {
    "es": ("contexto e historia", "situación actual, con ejemplos concretos",
           "retos y perspectivas futuras"),
    "en": ("context and history", "the present situation, with concrete examples",
           "challenges and future prospects"),
}
_FALLBACK = {
    "es": ("Introducción", "Presenta el tema y la idea central",
           "Perspectiva {n}", "Desarrolla un argumento con ejemplos concretos, centrado en {a}",
           "Tabla de resumen", "Resume los datos clave en una tabla",
           "Conclusión", "Sintetiza los puntos principales y cierra con una reflexión"),
    "en": ("Introduction", "Present the topic and the central idea",
           "Perspective {n}", "Develop one argument with concrete examples, focused on {a}",
           "Summary table", "Summarise the key facts in a table",
           "Conclusion", "Synthesise the main points and close with a reflection"),
}


_ABOUT = re.compile(r"\b(?:sobre|acerca de|about|on|sur|à propos de)\b\s*:?\s*(.+)$", re.I | re.S)
_LENGTH_PHRASE = re.compile(r"\b(?:de\s+|of\s+)?(?:aproximadamente\s+|about\s+|unas\s+)?\d[\d.,]*\s*"
                            r"(?:words|palabras|palavras|mots)\b", re.I)


def topic_from(objective: str) -> str:
    """The subject of the request, without the whole text's length ("800 words")."""
    text = " ".join((objective or "").split())
    match = _ABOUT.search(text)
    topic = match.group(1) if match else _LENGTH_PHRASE.sub("", text)
    return " ".join(topic.split()).strip(" .:;\"'“”«»")[:160]


def fallback_outline(prompt: str, contract, lang: str, target_words: int,
                     error: str = "") -> Outline:
    """Deterministic outline: opening, three perspectives, optional table, closing.

    The request's closing paragraph (after the last blank line) usually holds
    its delivery requirements ("as a speech opened by …"); it is attached to
    the opening section. Bullet instructions become the style line.
    """
    s = _FALLBACK.get(lang, _FALLBACK["en"])
    angles = _ANGLES.get(lang, _ANGLES["en"])
    # Style = the instruction bullets that speak of tone/register/voice only;
    # structural bullets ("open with…", "include a title") are not sent to
    # every section.
    bullets = [b for b in _BULLET.findall(prompt) if _STYLE_CUE.search(b)][:2]
    tail = (prompt or "").strip().split("\n\n")[-1].strip()
    opening_req, table_req = [], []
    if tail and not tail.lstrip().startswith(("-", "1")):
        for sentence in re.split(r"(?<=[.!?])\s+", " ".join(tail.split())):
            (table_req if _TABLE_CUE.search(sentence) else opening_req).append(sentence[:200])
    sections = [Section(s[0], s[1], 15, must_include=opening_req[:2])]
    sections += [Section(s[2].format(n=i), s[3].format(a=angles[i - 1]), 20)
                 for i in (1, 2, 3)]
    if _TABLE_CUE.search(prompt or ""):
        sections.append(Section(s[4], s[5], TABLE_SECTION_WORDS, kind="table",
                                must_include=table_req[:1]))
    sections.append(Section(s[6], s[7], 15))
    _rescale(sections, target_words)
    topic = topic_from(getattr(contract, "objective", "") or "")
    return Outline(title="", topic=topic, style="; ".join(bullets)[:240],
                   sections=sections, source="fallback",
                   errors=[error] if error else [])


def make_outline(prompt: str, contract, lang: str, target_words: int, backend,
                 max_sections: int) -> Outline:
    """Outline from the local model, or the deterministic fallback."""
    raw = ""
    if backend is not None:
        raw = backend.generate(outline_prompt(prompt, lang, target_words, max_sections),
                               max_tokens=OUTLINE_MAX_TOKENS, temperature=0.2) or ""
    if not raw.strip():
        return fallback_outline(prompt, contract, lang, target_words,
                                "no local model output for the outline")
    try:
        outline = parse_outline(raw, target_words=target_words, max_sections=max_sections)
    except (ValueError, json.JSONDecodeError) as exc:
        return fallback_outline(prompt, contract, lang, target_words, str(exc)[:160])
    if not outline.topic:
        outline.topic = topic_from(getattr(contract, "objective", "") or "")
    return outline


# -- section briefs ----------------------------------------------------------------
_BRIEF = {
    "es": {
        "head": "Escribe la sección {i} de {n} de un texto{title} sobre {topic}.",
        "title": " titulado «{t}»",
        "section": "Sección: {h}.", "purpose": "Propósito: {p}.",
        "points": "Puntos clave: {x}.", "must": "Debe incluir: {x}.",
        "style": "Estilo: {x}.", "words": "Extensión: unas {w} palabras.",
        "first": "Es la apertura: empieza el texto.",
        "last": ("Es el cierre: empieza con una transición desde «{prev}» y termina el "
                 "texto con una conclusión."),
        "middle": ("Empieza con una frase de transición desde la sección anterior "
                   "(«{prev}»). No escribas introducción ni conclusión del texto completo."),
        "table": ("Presenta esta sección como una tabla en Markdown con encabezados de "
                  "columna, precedida por una frase breve."),
        "only": "Escribe solo el contenido de esta sección, sin el encabezado ni el título.",
    },
    "en": {
        "head": "Write section {i} of {n} of a text{title} about {topic}.",
        "title": " titled “{t}”",
        "section": "Section: {h}.", "purpose": "Purpose: {p}.",
        "points": "Key points: {x}.", "must": "Must include: {x}.",
        "style": "Style: {x}.", "words": "Length: about {w} words.",
        "first": "This is the opening: it starts the text.",
        "last": ("This is the closing: begin with a transition from “{prev}” and end the "
                 "text with a conclusion."),
        "middle": ("Begin with a transition sentence from the previous section "
                   "(“{prev}”). Do not write an introduction or a conclusion of the "
                   "whole text."),
        "table": ("Present this section as a Markdown table with column headers, "
                  "preceded by one short sentence."),
        "only": "Write only the content of this section, without its heading or the title.",
    },
}


def _bare(text: str) -> str:
    return (text or "").strip().rstrip(" .;")


def section_instruction(outline: Outline, index: int, lang: str) -> str:
    """The task text of one section: its brief and position, never the request."""
    b = _BRIEF.get(lang, _BRIEF["en"])
    sec = outline.sections[index]
    n = len(outline.sections)
    prev = outline.sections[index - 1].heading if index > 0 else ""
    lines = [b["head"].format(i=index + 1, n=n,
                              title=b["title"].format(t=outline.title) if outline.title else "",
                              topic=outline.topic or "—"),
             b["section"].format(h=_bare(sec.heading)), b["purpose"].format(p=_bare(sec.purpose))]
    if sec.key_points:
        lines.append(b["points"].format(x="; ".join(_bare(k) for k in sec.key_points)))
    if sec.must_include:
        lines.append(b["must"].format(x="; ".join(_bare(m) for m in sec.must_include)))
    if outline.style and sec.kind != "table":
        lines.append(b["style"].format(x="; ".join(_bare(x) for x in outline.style.split("; "))))
    lines.append(b["words"].format(w=sec.words))
    if sec.kind == "table":
        lines.append(b["table"])
    elif index == 0:
        lines.append(b["first"])
    elif index == n - 1:
        lines.append(b["last"].format(prev=prev))
    else:
        lines.append(b["middle"].format(prev=prev))
    lines.append(b["only"])
    return "\n".join(lines)


def section_budget(section: Section, tokens_per_word: float, headroom: float = 1.5) -> int:
    return int(section.words * tokens_per_word * headroom) + 32


# -- assembly ----------------------------------------------------------------------
def clean_section(text: str, section: Section, title: str) -> str:
    """Drop what a worker adds around its section: fences, headings, the title."""
    body = (text or "").strip()
    body = re.sub(r"^```[a-zA-Z]*\s*\n?|\n?```\s*$", "", body).strip()
    lines = body.splitlines()
    names = {section.heading.casefold().strip(" .:*#"), (title or "").casefold().strip(" .:*#")}
    while lines and (not lines[0].strip()
                     or (section.kind != "table" and _HEADING_LINE.match(lines[0]))
                     or lines[0].strip().casefold().strip(" .:*#") in names):
        lines.pop(0)
    return "\n".join(lines).strip()


def assemble(outline: Outline, texts: list[str]) -> str:
    parts = [t for t in texts if t.strip()]
    head = f"# {outline.title}\n\n" if outline.title else ""
    return head + "\n\n".join(parts)


def _significant(term: str) -> list[str]:
    words = re.findall(r"\w{4,}", term.casefold())
    proper = [w for w in re.findall(r"\b[A-ZÁÉÍÓÚÑ][\wáéíóúñ]{2,}", term)]
    return [w.casefold() for w in proper] or words[:3]


def requirement_report(outline: Outline, final_text: str) -> dict[str, Any]:
    """Lexical check of each ``must_include`` and of requested tables."""
    lowered = (final_text or "").casefold()
    checks = []
    for sec in outline.sections:
        for req in sec.must_include:
            keys = _significant(req)
            found = bool(keys) and all(k in lowered for k in keys)
            checks.append({"section": sec.heading, "requirement": req, "found": found,
                           "matched_on": keys})
    tables_requested = any(s.kind == "table" for s in outline.sections)
    table_lines = len(re.findall(r"^\s*\|.*\|\s*$", final_text or "", re.M))
    return {"checks": checks,
            "found": sum(1 for c in checks if c["found"]), "total": len(checks),
            "tables_requested": tables_requested, "table_rows": table_lines,
            "words": len((final_text or "").split()),
            "note": "lexical presence check, not a quality judgement"}
