"""Check the numbers in a written answer against the tool results behind it.

Each number in the answer is marked as found (a value that rounds to it appears in the tool
results), not found, or not checked (counts the model made, percentages it computed, and
thresholds such as "p < 0.05", none of which a tool result would contain). The answer is
returned with every number wrapped as a ``[text](#num:i)`` link so the frontend can show it.

"Not found" therefore means no tool returned the value. Which result a number belongs to is not
judged: large results hold thousands of values, so "found" says the value exists, not that the
sentence reads it correctly. The words the sentence names (a gene, a cohort, a GO term) pick
which matching value the hover shows: each value carries the words of its path, of the short text
fields in the same record, and of the gene the tool was called for.
"""

import bisect
import json
import re
from collections import Counter
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Set, Tuple

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")

# A number that stands on its own: not part of a gene symbol (TP53), an ID (GO:0048732,
# GSE25066), a version, or a name like hsa-mir-21. Allows 1,234, 0.004, 6.0e-4, 6.0 × 10⁻⁴, 43%.
_NUMBER_RE = re.compile(
    r"(?<![\w.:/#])(?<![A-Za-z]-)"
    r"(?P<sign>[-−])?"
    r"(?P<mantissa>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?:\s?[eE](?P<exp>[-−+]?\d+)|\s?[×x]\s?10\^?(?P<exp10>[-−⁻]?[\d⁰¹²³⁴⁵⁶⁷⁸⁹]+))?"
    r"(?P<pct>%)?"
    r"(?!\w)"
)
_THRESHOLD_RE = re.compile(
    r"(?:[<>≤≥]=?|\b(?:below|above|under|over|less than|greater than|more than|at least|at most|up to|exceed(?:s|ing)?|cutoff|threshold(?: of)?))[\s*_]*$",
    re.IGNORECASE,
)
# Parts of the answer whose digits are not values: links and their URLs, inline code, plot
# markers, and the numbers of ordered list items
_SKIP_RE = re.compile(r"\[[^\]]*\]\([^)]*\)|`[^`]*`|\[(?:PLOT|NETWORK|TABLE):[^\]]*\]|^[ \t]*\d+[.)][ \t]", re.MULTILINE)

_MAX_VALUES = 300_000
# A word in this share of all values or more (RNA, data, pvalue) does not tell results apart.
# Words right before a number (its own clause) may be commoner, since they name it directly.
_DISTINCTIVE_SHARE = 0.2
_CLAUSE_SHARE = 0.5
# Lists longer than this are raw arrays (per-patient samples), not result records
_LONG_LIST = 100
# Sentence boundaries: a period that is not a decimal point, !, ?, or a new line
_SENTENCE_END_RE = re.compile(r"(?<!\d)\.(?!\d)|[!?\n]")

Value = Tuple[float, str, str, str, FrozenSet[str]]  # (absolute value, tool, path, as stored, context words)


def _words(text: str) -> Set[str]:
    """Upper-case words with at least one letter (TP53, LUAD, KRAS), not bare digits."""
    return {w for w in re.findall(r"[A-Z0-9]+", text.upper()) if len(w) > 1 and not w.isdigit()}


# How answers name omics layers, and the names the results use for them
_LAYER_ALIASES = {
    "COPY": {"SCNA", "SCNV", "CNV"}, "CNV": {"SCNA", "SCNV"}, "CNA": {"SCNA", "SCNV"},
    "MRNA": {"RNASEQ", "RNA"}, "RNA": {"RNASEQ"}, "TRANSCRIPT": {"RNASEQ", "RNA"},
    "PROTEIN": {"RPPA"}, "MIRNA": {"MIRNASEQ"}, "MICRORNA": {"MIRNASEQ"},
}


def _answer_words(text: str) -> Set[str]:
    """The words of a stretch of the answer, plus the results' names for any omics layer it mentions."""
    words = _words(text)
    return words | {alias for word in words for alias in _LAYER_ALIASES.get(word, ())}


def _parse(match: "re.Match[str]") -> Tuple[float, float]:
    """Return (absolute value, tolerance from the precision as written)."""
    mantissa = match.group("mantissa").replace(",", "")
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    exponent_text = match.group("exp") or match.group("exp10")
    exponent = int(exponent_text.translate(_SUPERSCRIPTS).replace("−", "-")) if exponent_text else 0
    scale = 10.0 ** exponent
    # Half a unit in the last written digit: the value rounds to the number as written
    return abs(float(mantissa)) * scale, 0.5 * (10.0 ** -decimals) * scale


def _numbers_in(text: str) -> Iterator[float]:
    for match in _NUMBER_RE.finditer(text):
        try:
            yield _parse(match)[0]
        except (ValueError, OverflowError):
            continue


def _collect_values(raw_results: Dict[str, Any]) -> List[Value]:
    """Every number in the tool results, with the words recorded around it."""
    values: List[Value] = []

    def walk(node: Any, tool: str, path: List[str], path_words: FrozenSet[str], record_words: FrozenSet[str]) -> None:
        if len(values) >= _MAX_VALUES or isinstance(node, bool) or node is None:
            return
        context = path_words | record_words
        if isinstance(node, (int, float)):
            values.append((abs(float(node)), tool, " › ".join(path), str(node), context))
        elif isinstance(node, str):
            # Results often carry values inside text, e.g. "... survival (p=6.000e-04)"
            for number in _numbers_in(node):
                values.append((number, tool, " › ".join(path), node[:160], context))
        elif isinstance(node, dict):
            # A record is named by its short text labels (a GO term's ID and description, an omics
            # layer) and its numeric field names (hr, pvalue, n), which every value in it shares.
            # Text holding numbers ("No significant association with survival (p=0.77)") is a
            # result, not a label; an identifier with digits in it (GSE25066, Liu_NatMed_2019_nivo)
            # is still a label.
            record = set(record_words)
            for key, child in node.items():
                if isinstance(child, str) and len(child) <= 80 and (
                    not any(ch.isspace() for ch in child.strip()) or next(_numbers_in(child), None) is None
                ):
                    record |= _words(child)
                elif isinstance(child, (int, float)) and not isinstance(child, bool):
                    record |= _words(str(key))
            for key, child in node.items():
                walk(child, tool, path + [str(key)], path_words | _words(str(key)), frozenset(record))
        elif isinstance(node, list):
            # Entries of long raw arrays (per-patient samples) do not take on the record's words
            inherited = frozenset() if len(node) > _LONG_LIST else record_words
            for i, child in enumerate(node):
                walk(child, tool, path + [str(i)], path_words, inherited)

    for key, wrapped in (raw_results or {}).items():
        payload = wrapped.get("_result") if isinstance(wrapped, dict) and "_result" in wrapped else wrapped
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                pass
        args = wrapped.get("_args") if isinstance(wrapped, dict) else None
        call_words = _words(str((args or {}).get("protein") or (args or {}).get("gene") or ""))
        walk(payload, key.rsplit("#", 1)[0], [], frozenset(call_words), frozenset())
    values.sort(key=lambda item: item[0])
    return values


def _sentence_span(text: str, start: int, end: int) -> Tuple[int, int]:
    lefts = [m.end() for m in _SENTENCE_END_RE.finditer(text, 0, start)]
    right = _SENTENCE_END_RE.search(text, end)
    return (lefts[-1] if lefts else 0), (right.start() if right else len(text))


def check_numbers(text: str, raw_results: Dict[str, Any], model_input: str = "") -> Optional[Dict[str, Any]]:
    """Check each number in ``text`` against ``raw_results``; None if there is nothing to check.

    ``model_input`` is the text the summary was written from. It is the tool results, but prepared:
    some values differ from the raw ones (an FDR of 0 shown as 1e-300), so its numbers count too,
    when no raw value matches.
    """
    if not text or not raw_results:
        return None
    values = _collect_values(raw_results)
    if not values:
        return None
    keys = [v[0] for v in values]
    prepared = sorted(set(_numbers_in(model_input))) if model_input else []
    word_counts = Counter(word for v in values for word in v[4])
    distinctive = {word for word, count in word_counts.items() if count < _DISTINCTIVE_SHARE * len(values)}
    clause_distinctive = {word for word, count in word_counts.items() if count < _CLAUSE_SHARE * len(values)}
    # The same within each tool's results: one large result (a drug target grid naming every
    # cohort) makes its words common overall, though they still tell another tool's results apart
    tool_values: Dict[str, List[Value]] = {}
    for v in values:
        tool_values.setdefault(v[1], []).append(v)
    tool_distinctive: Dict[str, Tuple[Set[str], Set[str]]] = {}
    for tool, own in tool_values.items():
        counts = Counter(word for v in own for word in v[4])
        tool_distinctive[tool] = ({w for w, c in counts.items() if c < _DISTINCTIVE_SHARE * len(own)},
                                  {w for w, c in counts.items() if c < _CLAUSE_SHARE * len(own)})
    skipped = [(m.start(), m.end()) for m in _SKIP_RE.finditer(text)]

    numbers: List[Dict[str, Any]] = []
    pieces: List[str] = []
    cursor = 0
    previous_end = 0
    number_ends: List[int] = []
    for match in _NUMBER_RE.finditer(text):
        start, end = match.span()
        if any(s <= start < e for s, e in skipped):
            continue
        try:
            value, tolerance = _parse(match)
        except (ValueError, OverflowError):
            continue
        written = match.group(0)
        entry: Dict[str, Any] = {"text": written}

        if _THRESHOLD_RE.search(text[max(0, start - 20):start]):
            entry["status"], entry["kind"] = "not_checked", "threshold"
        else:
            targets = [(value, tolerance)]
            if match.group("pct"):
                targets.append((value / 100, tolerance / 100))
            candidates = []
            for target, tol in targets:
                margin = tol * 1.000001  # keeps exact halves (0.0465 written as 0.047) inside
                lo = bisect.bisect_left(keys, target - margin)
                hi = bisect.bisect_right(keys, target + margin)
                candidates.extend(values[lo:hi])
            # The words of the sentence, and those just before the number, that tell results apart
            # pick the value the hover shows: the one recorded next to most of them, then the closest.
            # Names can come before the number ("mitotic cell cycle phase transition (FDR 7.03e-14)")
            # or after it ("r = 0.91 in UCEC").
            sentence_start, sentence_end = _sentence_span(text, start, end)
            clause_start = max(previous_end, sentence_start)
            # Numbers in parentheses describe what is named just before them, so their clause reaches
            # back there: "Liu_NatMed_2019_nivo (score 0.741, FDR 0.19)" for 0.19 as well as for 0.741
            open_paren = text.rfind("(", sentence_start, start)
            if open_paren > text.rfind(")", sentence_start, start):
                before = [e for e in number_ends if e <= open_paren]
                owner_start = max(sentence_start, text.rfind(")", sentence_start, open_paren) + 1, before[-1] if before else 0)
                clause_start = min(clause_start, owner_start)
            clause = text[clause_start:start]
            sentence_words, clause_words = _answer_words(text[sentence_start:sentence_end]), _answer_words(clause)
            named = (sentence_words & distinctive) | (clause_words & clause_distinctive)

            def named_for(c: Value) -> Set[str]:
                own, own_clause = tool_distinctive[c[1]]
                return named | (sentence_words & own) | (clause_words & own_clause)

            # Any value that rounds to the number counts as found. Reading which gene, cohort, or study
            # a sentence means from its words misfired again and again (2026-11-19), so the names only
            # choose which value the hover shows.
            prepared_match = next((v for target, tol in targets for v in prepared[bisect.bisect_left(prepared, target - tol * 1.000001):]
                                   if v <= target + tol * 1.000001), None)
            if candidates:
                best = min(candidates, key=lambda c: (-len(c[4] & named_for(c)), abs(c[0] - value)))
                entry["status"] = "found"
                entry["source"] = {"tool": best[1], "path": best[2], "value": best[3]}
            elif prepared_match is not None:
                entry["status"] = "found"
                entry["source"] = {"tool": "", "path": "the results as prepared for the summary", "value": f"{prepared_match:g}"}
            elif match.group("pct") or not (("." in match.group("mantissa")) or match.group("exp") or match.group("exp10")):
                # Whole numbers and percentages that no tool returned are counts or shares the
                # model worked out ("9 of 50 genes", "18%")
                entry["status"], entry["kind"] = "not_checked", "count"
            else:
                entry["status"] = "not_found"

        pieces.append(text[cursor:start])
        pieces.append(f"[{written}](#num:{len(numbers)})")
        cursor = end
        previous_end = end
        number_ends.append(end)
        numbers.append(entry)

    if not numbers:
        return None
    pieces.append(text[cursor:])
    counts = {status: sum(1 for n in numbers if n["status"] == status) for status in ("found", "not_found", "not_checked")}
    return {"marked": "".join(pieces), "numbers": numbers, "counts": counts}
