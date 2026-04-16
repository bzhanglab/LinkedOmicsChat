"""Treatment-category normalization and expansion for ClinicalOmicsDB trial filters.

The website's treatment selector exposes a nested category tree. We pin that tree in
`backend/data/clinicalomics_treatment_tree.json` and derive category expansions from it
so the backend can resolve both convenience aliases and arbitrary tree nodes such as
``Targeted Therapy``, ``Antibody``, or ``HER2 Inhibitor``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

_TREE_PATH = Path(__file__).resolve().parent.parent / "data" / "clinicalomics_treatment_tree.json"
_TARGETED_CATEGORY_LABEL = "Targeted Therapy"
_ICI_CATEGORY_LABEL = "Immune Checkpoint Inhibitor"
_CHEMOTHERAPY_CATEGORY_LABEL = "Chemotherapy"
_COMBINATIONS_CATEGORY_LABEL = "Combinations"


def _normalized_label(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _normalized_lookup_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().casefold())


def _load_tree() -> list[dict[str, Any]]:
    with _TREE_PATH.open("r", encoding="utf-8") as handle:
        tree = json.load(handle)
    if not isinstance(tree, list):
        raise RuntimeError(f"Expected a list of treatment nodes in {_TREE_PATH}")
    return tree


def _walk_nodes(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for node in nodes:
        yield node
        children = node.get("nodes")
        if isinstance(children, list):
            yield from _walk_nodes(children)


def _find_node(nodes: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    target = _normalized_lookup_key(label)
    for node in _walk_nodes(nodes):
        if _normalized_lookup_key(node.get("label")) == target:
            return node
    return None


def _leaf_labels(node: dict[str, Any]) -> list[str]:
    label = str(node.get("label", "")).strip()
    children = node.get("nodes")
    if not isinstance(children, list) or not children:
        return [label] if label else []

    labels: list[str] = []
    for child in children:
        labels.extend(_leaf_labels(child))
    return labels


def _dedupe_preserving_order(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for label in labels:
        normalized = _normalized_label(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(label)
    return deduped


def _category_leaves(tree: list[dict[str, Any]], *, include_root: str) -> list[str]:
    include_node = _find_node(tree, include_root)
    if include_node is None:
        raise RuntimeError(f"Treatment root '{include_root}' not found in {_TREE_PATH}")

    labels: list[str] = []
    for label in _leaf_labels(include_node):
        labels.append(label)
    return _dedupe_preserving_order(labels)


def _plural_variant(label: str) -> str | None:
    stripped = label.strip()
    if not stripped:
        return None
    if stripped.endswith("ies"):
        return None
    if stripped.endswith("y") and len(stripped) > 1 and stripped[-2].lower() not in "aeiou":
        return stripped[:-1] + "ies"
    if stripped.endswith("s"):
        return None
    return stripped + "s"


def _label_variants(label: str) -> set[str]:
    variants = {label}
    plural = _plural_variant(label)
    if plural:
        variants.add(plural)
    return variants


TREATMENT_TREE = _load_tree()
_TREE_CATEGORY_EXPANSIONS: dict[str, list[str]] = {}
for node in _walk_nodes(TREATMENT_TREE):
    label = str(node.get("label", "")).strip()
    if label and label not in _TREE_CATEGORY_EXPANSIONS:
        _TREE_CATEGORY_EXPANSIONS[label] = _dedupe_preserving_order(_leaf_labels(node))
TREATMENT_CATEGORIES: dict[str, list[str]] = dict(_TREE_CATEGORY_EXPANSIONS)

_SPECIAL_CATEGORY_ALIASES: dict[str, str] = {
    "targeted": _TARGETED_CATEGORY_LABEL,
    "targetedtherapy": _TARGETED_CATEGORY_LABEL,
    "ici": _ICI_CATEGORY_LABEL,
    "immunecheckpointinhibitor": _ICI_CATEGORY_LABEL,
    "immunecheckpointinhibitors": _ICI_CATEGORY_LABEL,
    "checkpointinhibitor": _ICI_CATEGORY_LABEL,
    "checkpointinhibitors": _ICI_CATEGORY_LABEL,
    "immunecheckpoint": _ICI_CATEGORY_LABEL,
    "immunecheckpoints": _ICI_CATEGORY_LABEL,
    "immunotherapy": _ICI_CATEGORY_LABEL,
    "pd1": _ICI_CATEGORY_LABEL,
    "pdl1": _ICI_CATEGORY_LABEL,
    "ctla4": _ICI_CATEGORY_LABEL,
    "chemotherapy": _CHEMOTHERAPY_CATEGORY_LABEL,
    "chemo": _CHEMOTHERAPY_CATEGORY_LABEL,
    "cytotoxic": _CHEMOTHERAPY_CATEGORY_LABEL,
    "combinations": _COMBINATIONS_CATEGORY_LABEL,
    "combination": _COMBINATIONS_CATEGORY_LABEL,
    "combinationtherapy": _COMBINATIONS_CATEGORY_LABEL,
    "combo": _COMBINATIONS_CATEGORY_LABEL,
}

TREATMENT_CATEGORY_LOOKUP: dict[str, str] = dict(_SPECIAL_CATEGORY_ALIASES)
for label in _TREE_CATEGORY_EXPANSIONS:
    for variant in _label_variants(label):
        TREATMENT_CATEGORY_LOOKUP.setdefault(_normalized_lookup_key(variant), label)


def normalize_treatment_category(value: Any) -> str | None:
    """Return the canonical treatment-category label for a user or LLM-provided value."""
    key = _normalized_lookup_key(value)
    if not key:
        return None
    return TREATMENT_CATEGORY_LOOKUP.get(key)


def expand_treatment_category(value: Any) -> list[str] | None:
    """Expand a treatment category value to the treatment labels accepted by the trials API."""
    canonical = normalize_treatment_category(value)
    if canonical is None:
        return None
    return TREATMENT_CATEGORIES.get(canonical)
