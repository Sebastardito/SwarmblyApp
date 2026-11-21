"""Node roles (3.5, D-018): what a *machine* offers the swarm.

These are not the per-answer MODEL roles in :mod:`swarmbly_app.roles` (writer,
search_terms, fusion, verifier, embeddings). A node role describes a
capability of the worker node itself, is announced in its signed
advertisement and is used only for placement:

- ``large_model``: a shared model with at least ``large_model_min_b`` billion
  parameters (``model`` and ``params_b``);
- ``reasoner``: a shared model the owner marked as a reasoning model, used
  with ``think: true`` (``model`` and ``think``);
- ``search``: the public search engines a worker can reach (up to four short
  names); its executor arrives in WP4b;
- ``corpus``: a display name and a size bucket (``S``, ``M``, ``L``) of a
  local corpus; never titles, paths or contents. Its executor arrives in
  WP4b.

Roles are self-declared metadata. They never widen a permission: circle
admission, lane/tier, model family/size, egress and the worker gates still
decide independently.

The wire stays 0.2. ``roles`` is an advertisement extension and
``constraints.role`` / ``constraints.think`` are packet extensions, all
MINOR-safe: an older node ignores them (SPEC §3).
"""

from __future__ import annotations

import math
import re
from typing import Any

# The complete set fixed now, so WP4b can add executors without a wire change.
NODE_ROLES = ("large_model", "reasoner", "search", "corpus")
# Roles a generic worker may answer when no node advertises the role: the
# answer is still useful, only the quality is lower, and the metadata says so.
# ``search`` and ``corpus`` are different: without their executor the task
# cannot be done truthfully, so it fails instead of being substituted.
FALLBACK_ROLES = frozenset({"large_model", "reasoner"})

MAX_ADVERTISEMENT_ROLES = 8
MAX_SEARCH_ENGINES = 4
MAX_CORPUS_NAME_CHARS = 40
MIN_PARAMS_B = 0.01
MAX_PARAMS_B = 10000.0
DEFAULT_LARGE_MODEL_MIN_B = 7.0

# Same conservative model-tag charset as the rest of the advertisement
# (handshake._SAFE_TEXT); kept local to avoid a circular import.
_MODEL_TAG = re.compile(r"^[\w .:/@+\-]{0,96}$", re.UNICODE)
_ENGINE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,15}$")
# A display name, not a path: no slashes, colons or backslashes may pass.
_CORPUS_NAME = re.compile(r"^[\w .&'()+-]{1,40}$", re.UNICODE)
_ROLE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _model_versions(advertisement_or_models: Any) -> set[str]:
    if isinstance(advertisement_or_models, dict):
        models = advertisement_or_models.get("models") or []
    else:
        models = advertisement_or_models or []
    out: set[str] = set()
    for model in models:
        if isinstance(model, dict):
            version = model.get("version")
            if isinstance(version, str) and version:
                out.add(version)
        elif isinstance(model, str) and model:
            out.add(model)
    return out


def _valid_model_tag(value: Any) -> bool:
    return isinstance(value, str) and bool(_MODEL_TAG.match(value))


def clean_roles(value: Any, models: Any = ()) -> tuple[list[str], list[dict]]:
    """Validate ``roles`` and return ``(problems, clean_entries)``.

    Known roles with malformed metadata produce a problem (the handshake
    rejects the advertisement). Unknown role names and a known role that
    names a model this node does not advertise are *dropped*, not fatal, so
    a newer peer can add a role without being refused by an older one. Only
    the documented metadata of each known role is kept.
    """
    if value is None:
        return [], []
    if not isinstance(value, list):
        return ["roles must be a list of at most 8 entries"], []
    problems: list[str] = []
    if len(value) > MAX_ADVERTISEMENT_ROLES:
        problems.append("roles must be a list of at most 8 entries")
    advertised_models = _model_versions(models)
    clean: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            problems.append("each roles entry must be an object")
            continue
        role = item.get("role")
        if not isinstance(role, str) or not _ROLE_NAME.fullmatch(role):
            problems.append("each roles entry needs a role name")
            continue
        if role not in NODE_ROLES:
            # Forward compatibility: a role this version does not know is
            # ignored, never a reason to refuse the peer.
            continue
        if role in ("large_model", "reasoner"):
            model = item.get("model")
            if not _valid_model_tag(model):
                problems.append(f"{role} needs a model tag with allowed characters")
                continue
            if model not in advertised_models:
                # A role for a model this node does not offer admits nothing;
                # drop it instead of rejecting the whole advertisement.
                continue
            if role == "large_model":
                params = item.get("params_b")
                if isinstance(params, bool) or not isinstance(params, (int, float)) \
                        or not math.isfinite(float(params)) \
                        or not MIN_PARAMS_B <= float(params) <= MAX_PARAMS_B:
                    problems.append(
                        f"large_model params_b must be a number in "
                        f"[{MIN_PARAMS_B}, {MAX_PARAMS_B}]")
                    continue
                clean.append({"role": "large_model", "model": model,
                              "params_b": float(params)})
            else:
                if item.get("think") is not True:
                    problems.append("reasoner needs think: true")
                    continue
                clean.append({"role": "reasoner", "model": model, "think": True})
        elif role == "search":
            engines = item.get("engines")
            if not isinstance(engines, list) or len(engines) > MAX_SEARCH_ENGINES:
                problems.append("search engines must be a list of at most 4 entries")
                continue
            if any(not isinstance(engine, str) or not _ENGINE.fullmatch(engine)
                   for engine in engines):
                problems.append("search engine names have disallowed characters or length")
                continue
            clean.append({"role": "search", "engines": list(engines)})
        else:  # corpus
            name = item.get("name")
            if not isinstance(name, str) or not _CORPUS_NAME.fullmatch(name) \
                    or name != name.strip():
                problems.append(
                    "corpus name must be a display name of at most 40 characters "
                    "(letters, digits, spaces and . & ' ( ) + -)")
                continue
            size = item.get("size")
            if size not in ("S", "M", "L"):
                problems.append("corpus size must be S, M or L")
                continue
            clean.append({"role": "corpus", "name": name, "size": size})
    return problems, clean[:MAX_ADVERTISEMENT_ROLES]


def normalise_advertisement(advertisement: Any) -> dict[str, Any]:
    """A copy of an advertisement whose ``roles`` are the accepted entries.

    Used after validation, before the advertisement is stored or shown: an
    unknown role or a role for a model that is not advertised never reaches
    placement or the UI.
    """
    if not isinstance(advertisement, dict):
        return {}
    out = dict(advertisement)
    _, clean = clean_roles(advertisement.get("roles"), advertisement)
    out["roles"] = clean
    return out


def advertised_role_names(advertisement: Any) -> set[str]:
    """Role names a (normalised) advertisement offers."""
    if not isinstance(advertisement, dict):
        return set()
    roles = advertisement.get("roles") or []
    return {str(entry.get("role")) for entry in roles
            if isinstance(entry, dict) and entry.get("role") in NODE_ROLES}


def roles_for(advertisement: Any, role: str) -> list[dict[str, Any]]:
    """Accepted metadata entries for one role in an advertisement."""
    if not isinstance(advertisement, dict) or role not in NODE_ROLES:
        return []
    return [entry for entry in (advertisement.get("roles") or [])
            if isinstance(entry, dict) and entry.get("role") == role]


def models_for_role(advertisement: Any, role: str) -> list[str]:
    """The models a role names, in advertisement order (empty for search/corpus)."""
    return [str(entry["model"]) for entry in roles_for(advertisement, role)
            if isinstance(entry.get("model"), str) and entry["model"]]


def large_model_min_b(cfg: dict[str, Any]) -> float:
    """The configured large-model threshold, with a safe fallback."""
    raw = ((cfg.get("node_roles") or {}).get("large_model_min_b"))
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) \
            or not math.isfinite(float(raw)) or float(raw) <= 0:
        return DEFAULT_LARGE_MODEL_MIN_B
    return float(raw)


def reasoner_models(cfg: dict[str, Any]) -> list[str]:
    raw = ((cfg.get("node_roles") or {}).get("reasoner_models"))
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for name in raw:
        if isinstance(name, str) and name and name not in out:
            out.append(name)
    return out


def derive_roles(models: list[str], cfg: dict[str, Any], *,
                 announce: bool = True) -> list[dict[str, Any]]:
    """The roles a node may advertise for ``models`` (WP4a: large_model, reasoner).

    ``models`` is the exact set the node offers: shared models for a remote
    worker, the local pool models for the local pseudo-peer. The caller decides
    whether the worker role is on (``announce=False`` returns no roles). Search
    and corpus are never derived here: their executors arrive in WP4b and in
    WP4a the configuration keys stay absent or inert.
    """
    if not announce:
        return []
    offered = []
    for name in models or []:
        if isinstance(name, str) and name and name not in offered:
            offered.append(name)
    threshold = large_model_min_b(cfg)
    marked = set(reasoner_models(cfg))
    roles: list[dict[str, Any]] = []
    from .engine.capability import model_params_b
    for name in offered:
        size = model_params_b(name)
        if size is not None and size >= threshold:
            roles.append({"role": "large_model", "model": name,
                          "params_b": float(size)})
    for name in offered:
        if name in marked:
            roles.append({"role": "reasoner", "model": name, "think": True})
    # The advertisement has a hard cap; the same validator bounds the rest.
    return roles[:MAX_ADVERTISEMENT_ROLES]
