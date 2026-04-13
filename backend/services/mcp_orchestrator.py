"""
MCP-based Orchestrator
When settings.USE_LANGGRAPH=True (default), delegates to LangGraphOrchestrator
for chained / parallel / conditional tool execution via LangGraph.
Falls back to the legacy single-shot planner when USE_LANGGRAPH=False.
"""
from typing import Dict, Any, Optional, List, AsyncGenerator
import logging
import re
import time
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.artifacts import (
    delete_session_workspace,
    delete_visualization_artifacts,
    ensure_session_workspace,
    session_plot_dir,
    write_visualization_index,
)
from core.config import settings
from core.llm_factory import LLMFactory
from core.database import SessionLocal
from models.database import ChatSession, ChatMessage as DBChatMessage, TokenUsage, GuestTokenUsage
from services.mcp_aggregator import MCPAggregator

logger = logging.getLogger(__name__)

_PENDING_OFFER_RE = re.compile(
    r"If you['’]d like, I can\s+(.+?)(?:[.?!])?\s*$",
    re.IGNORECASE | re.DOTALL,
)

_SUMMARY_DANGLING_END_RE = re.compile(r"(?:[,;:/=\-–—(\[{]|(?:\*\*)|`)\s*$")
_SUMMARY_TERMINAL_PUNCT_RE = re.compile(r"[.!?](?:\*\*|[`\"'\)\]\u201d\u2019]+)?\s*$")


def _extract_pending_offer_from_text(text: Any) -> Optional[str]:
    """Extract a follow-up offer sentence and convert it into a reusable query."""
    if not isinstance(text, str) or not text.strip():
        return None
    matches = list(_PENDING_OFFER_RE.finditer(text.strip()))
    if not matches:
        return None
    offer = re.sub(r"\s+", " ", matches[-1].group(1)).strip().rstrip(".?!")
    if not offer:
        return None
    return offer[:1].upper() + offer[1:]


def _extract_pending_offer_from_response(response: Dict[str, Any]) -> Optional[str]:
    """Prefer the summary offer, then fall back to the full message."""
    if not isinstance(response, dict):
        return None
    return (
        _extract_pending_offer_from_text(response.get("summary"))
        or _extract_pending_offer_from_text(response.get("message"))
    )


def _has_balanced_summary_markup(text: str) -> bool:
    """Return True when common markdown delimiters look balanced."""
    if text.count("**") % 2 != 0:
        return False
    if text.count("`") % 2 != 0:
        return False
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        balance = 0
        for char in text:
            if char == opener:
                balance += 1
            elif char == closer:
                balance -= 1
            if balance < 0:
                return False
        if balance != 0:
            return False
    return True


def _summary_has_complete_ending(text: str) -> bool:
    """Heuristic: summaries should end with balanced markup and terminal punctuation."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if not _has_balanced_summary_markup(stripped):
        return False
    if _SUMMARY_DANGLING_END_RE.search(stripped):
        return False
    return bool(_SUMMARY_TERMINAL_PUNCT_RE.search(stripped))


def _trim_summary_to_complete_boundary(text: str) -> str:
    """Trim an incomplete summary back to the last sentence boundary."""
    stripped = (text or "").strip()
    if not stripped:
        return ""
    if _summary_has_complete_ending(stripped):
        return stripped

    boundary_positions = [
        match.end()
        for match in re.finditer(r"[.!?](?:\*\*|[`\"'\)\]\u201d\u2019]+)?(?:\s+|$)", stripped)
    ]
    for end in reversed(boundary_positions):
        candidate = stripped[:end].strip()
        if _summary_has_complete_ending(candidate):
            return candidate

    lines = [line.rstrip() for line in stripped.splitlines()]
    while lines:
        lines.pop()
        candidate = "\n".join(lines).strip()
        if _summary_has_complete_ending(candidate):
            return candidate

    first_sentence = re.search(r"^.*?[.!?](?:\*\*|[`\"'\)\]\u201d\u2019]+)?(?:\s+|$)", stripped, re.DOTALL)
    if first_sentence:
        candidate = first_sentence.group(0).strip()
        if _summary_has_complete_ending(candidate):
            return candidate
    return ""


def _normalize_summary_text(text: str) -> str:
    """Normalize whitespace and remove obviously broken trailing markdown."""
    stripped = (text or "").strip()
    if not stripped:
        return ""
    stripped = stripped.replace("\r\n", "\n")
    stripped = re.sub(r"[ \t]+\n", "\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def _summary_bullet_count(text: str) -> int:
    """Count markdown bullet lines in a summary."""
    return sum(
        1
        for line in (text or "").splitlines()
        if re.match(r"^\s*[-*]\s+", line)
    )

# Per-cohort brand colors (CPTAC/LinkedOmics palette)
_COHORT_COLORS: dict[str, str] = {
    "BRCA":  "#fd8cd5",
    "CCRCC": "#ed7711",
    "COAD":  "#0728e4",
    "GBM":   "#62666b",
    "HCC":   "#117c21",
    "HNSCC": "#89263b",
    "LSCC":  "#cb4763",
    "LUAD":  "#d3d3d3",
    "OV":    "#107d9d",
    "PDAC":  "#b80ec4",
    "UCEC":  "#f04688",
}
_COHORT_COLOR_FALLBACK = [
    "#2980b9", "#27ae60", "#e67e22", "#8e44ad", "#16a085",
    "#f39c12", "#1abc9c", "#e74c3c", "#9b59b6", "#34495e",
]

def _cohort_color(cohort: str, fallback_index: int = 0) -> str:
    return _COHORT_COLORS.get(cohort, _COHORT_COLOR_FALLBACK[fallback_index % len(_COHORT_COLOR_FALLBACK)])

# Full names for TCGA cohort abbreviations
_TCGA_COHORT_NAMES: dict[str, str] = {
    "ACC":     "Adrenocortical Carcinoma",
    "BLCA":    "Bladder Urothelial Carcinoma",
    "BRCA":    "Breast Invasive Carcinoma",
    "CESC":    "Cervical Squamous Cell Carcinoma",
    "CHOL":    "Cholangiocarcinoma",
    "COAD":    "Colon Adenocarcinoma",
    "COADREAD":"Colorectal Adenocarcinoma",
    "DLBC":    "Diffuse Large B-Cell Lymphoma",
    "ESCA":    "Esophageal Carcinoma",
    "GBM":     "Glioblastoma Multiforme",
    "GBMLGG":  "Glioma",
    "HNSC":    "Head and Neck Squamous Cell Carcinoma",
    "KICH":    "Kidney Chromophobe",
    "KIPAN":   "Pan-Kidney",
    "KIRC":    "Kidney Renal Clear Cell Carcinoma",
    "KIRP":    "Kidney Renal Papillary Cell Carcinoma",
    "LAML":    "Acute Myeloid Leukemia",
    "LGG":     "Brain Lower Grade Glioma",
    "LIHC":    "Liver Hepatocellular Carcinoma",
    "LUAD":    "Lung Adenocarcinoma",
    "LUSC":    "Lung Squamous Cell Carcinoma",
    "MESO":    "Mesothelioma",
    "OV":      "Ovarian Serous Cystadenocarcinoma",
    "PAAD":    "Pancreatic Adenocarcinoma",
    "PCPG":    "Pheochromocytoma and Paraganglioma",
    "PRAD":    "Prostate Adenocarcinoma",
    "SARC":    "Sarcoma",
    "SKCM":    "Skin Cutaneous Melanoma",
    "STAD":    "Stomach Adenocarcinoma",
    "STES":    "Stomach and Esophageal Carcinoma",
    "TGCT":    "Testicular Germ Cell Tumors",
    "THCA":    "Thyroid Carcinoma",
    "THYM":    "Thymoma",
    "UCEC":    "Uterine Corpus Endometrial Carcinoma",
    "UCS":     "Uterine Carcinosarcoma",
    "UVM":     "Uveal Melanoma",
}


def _generate_km_static(samples: list, gene: str, cohort: str, omics: str,
                        hr: float, pvalue: float, n: int) -> Optional[dict]:
    """Compute Kaplan-Meier curves and return PNG (base64), SVG, and CSV data.

    Args:
        samples: list of {"group": "High"|"Low", "time": int, "status": int, "expr": float}
        gene, cohort, omics: used for the plot title / file naming
        hr, pvalue, n: summary statistics for annotation
    Returns:
        dict with keys: png_b64, svg, csv, title — or None on failure
    """
    try:
        import io, base64, csv as _csv
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from lifelines import KaplanMeierFitter

        high = [s for s in samples if s.get("group") == "High"]
        low  = [s for s in samples if s.get("group") == "Low"]
        if not high or not low:
            return None

        omics_label = {
            "RNAseq": "RNA expression",
            "RPPA": "protein (RPPA)",
            "Methylation": "methylation",
            "SCNA": "copy number",
            "miRNASeq": "miRNA expression",
        }.get(omics, omics or "expression")
        title = f"{gene} {omics_label} vs. Overall Survival — TCGA {cohort}"

        COLORS = {"High": "#c0392b", "Low": "#2980b9"}
        fig, ax = plt.subplots(figsize=(7, 4.5))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        csv_rows = []

        for label, group in [("High", high), ("Low", low)]:
            kmf = KaplanMeierFitter()
            kmf.fit(
                [s["time"] for s in group],
                event_observed=[s["status"] for s in group],
                label=f"{label} (n={len(group)})",
            )
            kmf.plot_survival_function(
                ax=ax,
                ci_show=True,
                ci_alpha=0.12,
                color=COLORS[label],
                linewidth=2,
            )
            # Censoring ticks
            censored = [s for s in group if s.get("status") == 0]
            if censored:
                cens_t = [s["time"] for s in censored]
                cens_p = [float(kmf.predict(t)) for t in cens_t]
                ax.scatter(cens_t, cens_p, marker="+", color=COLORS[label],
                           s=60, linewidths=1.5, zorder=5)
            # Collect CSV rows
            sf = kmf.survival_function_
            et = kmf.event_table
            for t in sf.index:
                prob = float(sf.loc[t].iloc[0])
                at_risk = int(et.loc[t, "at_risk"]) if t in et.index else ""
                csv_rows.append([label, t, round(prob, 6), at_risk])

        # Stats annotation
        annot_parts = []
        if hr is not None:
            annot_parts.append(f"HR = {hr:.4f}")
        if pvalue is not None:
            sig = " *" if pvalue < 0.05 else ""
            annot_parts.append(f"p = {pvalue:.4f}{sig}")
        if n is not None:
            annot_parts.append(f"n = {n}")
        if annot_parts:
            ax.text(0.03, 0.05, "\n".join(annot_parts),
                    transform=ax.transAxes, fontsize=9, verticalalignment="bottom",
                    bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                              edgecolor="#cccccc", linewidth=0.8))

        ax.set_title(title, fontsize=11, pad=10)
        ax.set_xlabel("Time (days)", fontsize=10)
        ax.set_ylabel("Survival Probability", fontsize=10)
        ax.set_ylim(-0.05, 1.05)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
        ax.grid(True, color="#eeeeee", linewidth=0.8)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.85)
        ax.spines[["top", "right"]].set_visible(False)

        # Set x-axis ticks at ~8 evenly spaced points across the data range
        all_times = [s["time"] for s in high + low]
        t_max = max(all_times)
        step = int(np.ceil(t_max / 8 / 100) * 100)  # round up to nearest 100
        xticks = list(range(0, int(t_max) + step, step))
        ax.set_xticks(xticks)
        fig.tight_layout()

        # PNG
        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        # SVG
        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()

        plt.close(fig)

        # CSV
        csv_buf = io.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow(["group", "time_days", "survival_probability", "at_risk"])
        writer.writerows(csv_rows)
        csv_str = csv_buf.getvalue()

        return {
            "png_b64": png_b64,
            "svg": svg_str,
            "csv": csv_str,
            "title": title,
        }

    except Exception as e:
        logger.warning(f"[KM plot] Failed to generate static survival curve: {e}")
        return None


def _generate_volcano_static(
    results: list,
    cohort: str,
    omics: str,
    title: str,
) -> Optional[dict]:
    """Generate a volcano plot (log2 HR vs −log10 FDR) as PNG, SVG, and CSV.

    Args:
        results: list of {gene, hr, pvalue, fdr, n} dicts
        cohort, omics: used for axis/title labels
        title: plot title
    Returns:
        dict with png_b64, svg, csv, title — or None on failure
    """
    try:
        import io, base64, csv as _csv, math
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patheffects as pe
        from adjustText import adjust_text  # pip install adjustText

        sig_threshold = 0.05
        sig_pts, nonsig_pts = [], []
        csv_rows = []

        for r in results:
            hr  = r.get("hr")
            fdr = r.get("fdr") or r.get("pvalue")
            gene = r.get("gene", "")
            n    = r.get("n")
            if hr is None or fdr is None or fdr <= 0 or hr <= 0:
                continue
            x = math.log2(hr)
            y = -math.log10(fdr)
            sig = fdr < sig_threshold
            entry = (x, y, gene, sig, hr > 1)
            (sig_pts if sig else nonsig_pts).append(entry)
            csv_rows.append([gene, round(hr, 6), round(fdr, 8), n, "significant" if sig else "not_significant"])

        if not sig_pts and not nonsig_pts:
            return None

        fig, ax = plt.subplots(figsize=(8, 5.5))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        # Non-significant (grey, smaller, semi-transparent)
        if nonsig_pts:
            ax.scatter([p[0] for p in nonsig_pts], [p[1] for p in nonsig_pts],
                       c="#cccccc", s=12, alpha=0.4, linewidths=0, rasterized=True)

        # Significant harmful (red) and protective (blue)
        # Point size scales with |log2(HR)| so effect size is visible at a glance.
        max_abs_x = max((abs(p[0]) for p in sig_pts), default=1.0) or 1.0
        def _sig_size(x: float) -> float:
            return 15 + 55 * (abs(x) / max_abs_x)

        harmful  = [p for p in sig_pts if p[4]]
        protect  = [p for p in sig_pts if not p[4]]
        if harmful:
            ax.scatter([p[0] for p in harmful], [p[1] for p in harmful],
                       c="#c0392b", s=[_sig_size(p[0]) for p in harmful],
                       alpha=0.85, linewidths=0, label="Harmful (sig.)")
        if protect:
            ax.scatter([p[0] for p in protect], [p[1] for p in protect],
                       c="#2980b9", s=[_sig_size(p[0]) for p in protect],
                       alpha=0.85, linewidths=0, label="Protective (sig.)")

        # FDR threshold line
        threshold_y = -math.log10(sig_threshold)
        x_min = min(p[0] for p in sig_pts + nonsig_pts) - 0.3
        x_max = max(p[0] for p in sig_pts + nonsig_pts) + 0.3
        ax.axhline(threshold_y, color="#e74c3c", linestyle="--", linewidth=0.9, alpha=0.7,
                   label=f"FDR = {sig_threshold}")
        ax.axvline(0, color="#999999", linestyle="-", linewidth=0.7, alpha=0.5)

        # Label top 15 significant genes by -log10(FDR)
        top_genes = sorted(sig_pts, key=lambda p: -p[1])[:15]
        texts = []
        for p in top_genes:
            t = ax.text(p[0], p[1], p[2], fontsize=7, ha="center", va="bottom",
                        color="#222222",
                        path_effects=[pe.withStroke(linewidth=2, foreground="white")])
            texts.append(t)
        try:
            adjust_text(texts, ax=ax, arrowprops=dict(arrowstyle="-", color="#999999", lw=0.5))
        except Exception:
            pass  # adjustText optional — fall back to un-adjusted labels

        ax.set_xlabel("log₂(Hazard Ratio)\n← Protective  |  Harmful →", fontsize=10, labelpad=6)
        ax.set_ylabel("−log₁₀(FDR)", fontsize=10)
        ax.set_title(title, fontsize=11, pad=10)
        ax.set_xlim(x_min, x_max)
        ax.xaxis.label.set_color("#333333")
        ax.legend(loc="upper left", fontsize=8, framealpha=0.85)
        ax.grid(True, color="#eeeeee", linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()

        # PNG
        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        # SVG
        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()

        plt.close(fig)

        # CSV
        csv_buf = io.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow(["gene", "hr", "fdr", "n", "significance"])
        writer.writerows(csv_rows)

        return {
            "png_b64": png_b64,
            "svg": svg_str,
            "csv": csv_buf.getvalue(),
            "title": title,
        }

    except Exception as e:
        logger.warning(f"[Volcano plot] Failed to generate static plot: {e}")
        return None


def _generate_enrichment_static(rows: list, title: str) -> Optional[dict]:
    """Generate a dot plot for pathway enrichment results as PNG, SVG, and CSV."""
    try:
        import io, base64, csv as _csv, math, textwrap
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors

        plot_rows = []
        csv_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            description = str(row.get("description") or row.get("geneSet") or "").strip()
            gene_set = str(row.get("geneSet") or "").strip()
            link = str(row.get("link") or "").strip()
            overlap_id = str(row.get("overlapId") or "").strip()
            try:
                ratio = float(row.get("enrichmentRatio"))
                fdr = float(row.get("FDR"))
            except (TypeError, ValueError):
                continue
            try:
                overlap = int(float(row.get("overlap", 0)))
            except (TypeError, ValueError):
                overlap = 0
            try:
                size = int(float(row.get("size", 0)))
            except (TypeError, ValueError):
                size = 0
            try:
                expect = float(row.get("expect", 0))
            except (TypeError, ValueError):
                expect = 0.0
            try:
                pvalue = float(row.get("pValue"))
            except (TypeError, ValueError):
                pvalue = float("nan")

            if ratio <= 0 or fdr < 0:
                continue

            plot_rows.append({
                "description": description,
                "gene_set": gene_set,
                "ratio": ratio,
                "fdr": max(fdr, 1e-300),
                "overlap": max(overlap, 1),
                "size": max(size, 0),
                "expect": expect,
            })
            csv_rows.append([
                gene_set,
                description,
                size,
                overlap,
                round(expect, 6),
                round(ratio, 6),
                "" if math.isnan(pvalue) else f"{pvalue:.8g}",
                f"{fdr:.8g}",
                overlap_id,
                link,
            ])

        if not plot_rows:
            return None

        display_rows = list(reversed(plot_rows))
        labels = []
        ratios = []
        overlaps = []
        neglog_fdr = []
        for entry in display_rows:
            label = textwrap.fill(entry["description"], width=48)
            if entry["gene_set"] and entry["gene_set"] not in entry["description"]:
                label = f"{label}\n{entry['gene_set']}"
            labels.append(label)
            ratios.append(entry["ratio"])
            overlaps.append(entry["overlap"])
            neglog_fdr.append(-math.log10(entry["fdr"]))

        fig_height = max(3.8, 0.8 * len(display_rows) + 1.8)
        fig, ax = plt.subplots(figsize=(8.4, fig_height))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        y_pos = list(range(len(display_rows)))
        x_max = max(ratios) * 1.18 if ratios else 1.0
        min_size = 80
        max_size = 280
        max_overlap = max(overlaps) if overlaps else 1
        if max_overlap <= 1:
            sizes = [min_size for _ in overlaps]
        else:
            sizes = [
                min_size + ((ov - 1) / (max_overlap - 1)) * (max_size - min_size)
                for ov in overlaps
            ]

        cmap = plt.get_cmap("YlOrRd")
        norm = mcolors.Normalize(vmin=min(neglog_fdr), vmax=max(neglog_fdr) if max(neglog_fdr) > min(neglog_fdr) else min(neglog_fdr) + 1)

        for y, ratio in zip(y_pos, ratios):
            ax.hlines(y, xmin=0, xmax=ratio, color="#d1d5db", linewidth=1.2, zorder=1)

        scatter = ax.scatter(
            ratios,
            y_pos,
            s=sizes,
            c=neglog_fdr,
            cmap=cmap,
            norm=norm,
            edgecolors="#374151",
            linewidths=0.6,
            zorder=3,
        )

        label_offset = 0.22
        for y, ratio in zip(y_pos, ratios):
            ax.text(
                ratio,
                y - label_offset,
                f"{ratio:.1f}x",
                va="top",
                ha="center",
                fontsize=7.5,
                color="#374151",
            )

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_xlabel("Enrichment Ratio", fontsize=10)
        ax.set_xlim(0, x_max)
        ax.set_ylim(-0.55, len(display_rows) - 0.35)
        ax.grid(axis="x", color="#eeeeee", linewidth=0.8)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", labelsize=9)

        cbar = fig.colorbar(scatter, ax=ax, pad=0.02)
        cbar.set_label("−log10(FDR)", fontsize=9)
        cbar.ax.tick_params(labelsize=8)

        fig.suptitle(title, fontsize=12, y=0.985)
        fig.text(
            0.125,
            0.965,
            "Dot size = overlap genes · label = enrichment ratio",
            fontsize=8.5,
            color="#6b7280",
            ha="left",
            va="top",
        )

        fig.tight_layout(rect=[0, 0, 1, 0.94])

        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()

        plt.close(fig)

        csv_buf = io.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow([
            "geneSet",
            "description",
            "size",
            "overlap",
            "expect",
            "enrichmentRatio",
            "pValue",
            "FDR",
            "overlapId",
            "link",
        ])
        writer.writerows(csv_rows)

        return {
            "png_b64": png_b64,
            "svg": svg_str,
            "csv": csv_buf.getvalue(),
            "title": title,
        }

    except Exception as e:
        logger.warning(f"[Enrichment plot] Failed to generate static plot: {e}")
        return None


def _generate_expression_tile_static(data: dict, gene: str, is_survival: bool = False) -> Optional[dict]:
    """Generate a 2-row × N-col color tile matrix for expression or survival data.

    Args:
        data: {"protein_level": {"status": ..., "data": {cancer: msg}}, "RNA_level": {...}}
        gene: gene symbol for title
        is_survival: False for tumor-vs-normal expression, True for survival association
    Returns:
        dict with png_b64, svg, csv, title — or None on failure
    """
    try:
        import re, io, base64, csv as _csv, math
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch

        p_data = (data.get("protein_level") or {}).get("data") or {}
        r_data = (data.get("RNA_level") or {}).get("data") or {}
        cancers = sorted(set(list(p_data.keys()) + list(r_data.keys())))
        if not cancers:
            return None

        def _parse_entry(msg: str):
            if not msg or msg in ("Data unavailable", "-", ""):
                return 0, None, False
            m = re.search(r'p=([\d.e+\-]+)', msg, re.IGNORECASE)
            pval = float(m.group(1)) if m else None
            msg_l = msg.lower()
            if is_survival:
                if "higher expression associated with poor" in msg_l:
                    return 1, pval, True
                if "lower expression associated with poor" in msg_l:
                    return -1, pval, True
            else:
                if "significantly higher" in msg_l:
                    return 1, pval, True
                if "significantly lower" in msg_l:
                    return -1, pval, True
            return 0, pval, False

        layers = [("Protein", p_data), ("RNA", r_data)]
        n_cols = len(cancers)
        tile_colors, tile_annots = [], []
        csv_rows = []  # flat: one row per (layer, cancer)

        # First pass: collect all significant p-values to set adaptive intensity scale
        all_sig_pvals = []
        for _, layer_data in layers:
            for cancer in cancers:
                msg = layer_data.get(cancer, "Data unavailable")
                _, pval, sig = _parse_entry(msg)
                if sig and pval and pval > 0:
                    all_sig_pvals.append(-math.log10(pval))
        max_neglog_p = max(all_sig_pvals) if all_sig_pvals else 6.0
        max_neglog_p = max(max_neglog_p, 1.5)  # avoid division by near-zero

        for layer_name, layer_data in layers:
            row_c, row_a = [], []
            for cancer in cancers:
                msg = layer_data.get(cancer, "Data unavailable")
                direction, pval, sig = _parse_entry(msg)
                if sig and pval and pval > 0:
                    intensity = min(1.0, -math.log10(pval) / max_neglog_p)
                    if direction > 0:
                        color = (1.0, 1.0 - intensity * 0.75, 1.0 - intensity * 0.75)
                    else:
                        color = (1.0 - intensity * 0.75, 1.0 - intensity * 0.75, 1.0)
                    annot = f"p={pval:.1e}" if pval < 0.001 else f"p={pval:.3f}"
                else:
                    color = (0.88, 0.88, 0.88)
                    annot = "N/A" if pval is None else "N.S."
                row_c.append(color); row_a.append(annot)
                dir_label = {1: "up", -1: "down", 0: "NS"}.get(direction, "")
                csv_rows.append([layer_name, cancer, msg,
                                  dir_label,
                                  f"{pval:.4e}" if pval is not None else "",
                                  "yes" if sig else "no"])
            tile_colors.append(row_c); tile_annots.append(row_a)

        title_suffix = "Survival Association — CPTAC" if is_survival else "Tumor vs. Normal — CPTAC"
        title = f"{gene} {title_suffix}"

        fig_w = max(7, n_cols * 0.9 + 1.5)
        fig, ax = plt.subplots(figsize=(fig_w, 2.6))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        for ri, (row_c, row_a) in enumerate(zip(tile_colors, tile_annots)):
            for ci, (color, annot) in enumerate(zip(row_c, row_a)):
                rect = plt.Rectangle([ci - 0.46, ri - 0.46], 0.92, 0.92,
                                      facecolor=color, edgecolor="#cccccc", linewidth=0.7)
                ax.add_patch(rect)
                if annot:
                    ax.text(ci, ri, annot, ha="center", va="center",
                            fontsize=6.5, color="#333333")

        if is_survival:
            legend_els = [
                Patch(facecolor="#c0392b", label="Higher expr → poor survival"),
                Patch(facecolor="#2980b9", label="Lower expr → poor survival"),
                Patch(facecolor="#dddddd", label="Not significant (N.S.) or no data (N/A)"),
            ]
        else:
            legend_els = [
                Patch(facecolor="#c0392b", label="Higher in tumor"),
                Patch(facecolor="#2980b9", label="Lower in tumor"),
                Patch(facecolor="#dddddd", label="Not significant (N.S.) or no data (N/A)"),
            ]
        ax.legend(handles=legend_els, loc="upper center", fontsize=7.5,
                  framealpha=0.9, bbox_to_anchor=(0.5, -0.22), ncol=3)

        ax.set_xlim(-0.55, n_cols - 0.45)
        ax.set_ylim(-0.55, 1.55)
        ax.set_xticks(range(n_cols))
        ax.set_xticklabels(cancers, fontsize=9)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["Protein", "RNA"], fontsize=9)
        ax.tick_params(length=0)
        ax.set_title(title, fontsize=11, pad=8)
        for sp in ax.spines.values():
            sp.set_visible(False)
        fig.tight_layout(rect=[0, 0.12, 1, 1])

        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()
        plt.close(fig)

        csv_buf = io.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow(["layer", "cancer", "full_message", "direction", "pvalue", "significant"])
        writer.writerows(csv_rows)

        return {"png_b64": png_b64, "svg": svg_str, "csv": csv_buf.getvalue(), "title": title}

    except Exception as e:
        logger.warning(f"[Expression tile] Failed to generate: {e}")
        return None


def _trials_table(studies: list, heading: str) -> list[str]:
    """Render a list of clinical trial study dicts as a compact markdown table."""
    lines = [f"### {heading}"]
    if not studies:
        lines.append("_No significant results._")
        return lines
    lines.append("| Series | Disease | Treatment | AUROC | N |")
    lines.append("|---|---|---|---|---|")
    for s in studies:
        treatment = str(s.get("treatment", "") or "")
        # Truncate very long treatment strings
        treatment_display = (treatment[:40] + "…") if len(treatment) > 40 else treatment
        lines.append(
            f"| {s.get('series','')} | {s.get('disease','')} "
            f"| {treatment_display} | {s.get('auroc','')} "
            f"| {s.get('sample_size','')} |"
        )
    return lines


def _generate_trials_auroc_chart(data: dict, label: str) -> Optional[dict]:
    """Generate a horizontal AUROC bar chart for clinical trial associations.

    Shows all significant studies sorted by AUROC with a reference line at 0.5.
    Bars colored teal (sensitive, AUROC<0.5) or orange (resistant, AUROC>0.5).
    """
    try:
        import io, base64, csv as _csv
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        resistant = data.get("resistant", data.get("top_resistant", []))
        sensitive = data.get("sensitive", data.get("top_sensitive", []))
        if not resistant and not sensitive:
            return None

        studies = []
        for s in sensitive:
            studies.append({
                "label": f"{s.get('series','')} — {str(s.get('treatment',''))[:28]}",
                "auroc": float(s.get("auroc", 0.5)),
                "direction": "sensitive",
            })
        for s in resistant:
            studies.append({
                "label": f"{s.get('series','')} — {str(s.get('treatment',''))[:28]}",
                "auroc": float(s.get("auroc", 0.5)),
                "direction": "resistant",
            })
        # Sort by AUROC ascending (sensitive at top, resistant at bottom for horizontal bars)
        studies.sort(key=lambda x: x["auroc"])

        labels = [s["label"] for s in studies]
        aurocs = [s["auroc"] for s in studies]
        colors = ["#3b82f6" if s["direction"] == "sensitive" else "#f97316" for s in studies]

        fig_h = max(3.0, len(studies) * 0.38 + 1.2)
        fig, ax = plt.subplots(figsize=(8.5, fig_h))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        y_pos = np.arange(len(studies))
        bars = ax.barh(y_pos, aurocs, height=0.65, color=colors, edgecolor="none")

        # Reference line at AUROC = 0.5
        ax.axvline(0.5, color="#666666", linewidth=1.0, linestyle="--", label="AUROC = 0.5")

        # AUROC value labels at bar tips
        for bar, val in zip(bars, aurocs):
            x_tip = bar.get_width()
            ax.text(x_tip + 0.008, bar.get_y() + bar.get_height() / 2,
                    f"{val:.3f}", va="center", ha="left", fontsize=7.5, color="#333333")

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xlim(0.0, 1.15)
        ax.set_xlabel("AUROC", fontsize=9)
        ax.set_title(f"Clinical Trial Associations — {label}", fontsize=11, fontweight="bold", pad=8)
        ax.tick_params(axis="x", labelsize=8)

        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor="#3b82f6", label="Sensitive (AUROC < 0.5)"),
            Patch(facecolor="#f97316", label="Resistant (AUROC > 0.5)"),
        ]
        ax.legend(handles=legend_elements, loc="lower right", fontsize=8, frameon=False)

        fig.tight_layout()

        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()
        plt.close(fig)

        # CSV: flat table of all studies
        rows_out = []
        for s in studies:
            rows_out.append({"series": s["label"].split(" — ")[0],
                             "direction": s["direction"], "auroc": s["auroc"]})
        csv_buf = io.StringIO()
        if rows_out:
            writer = _csv.DictWriter(csv_buf, fieldnames=list(rows_out[0].keys()))
            writer.writeheader()
            writer.writerows(rows_out)

        return {
            "title": f"Clinical Trial Associations — {label}",
            "png_b64": png_b64,
            "svg": svg_str,
            "csv": csv_buf.getvalue(),
        }
    except Exception as e:
        logger.warning(f"[Trials AUROC chart] Failed to generate: {e}")
        return None


def _generate_meta_analysis_chart(items: list, label_key: str, title: str) -> Optional[dict]:
    """Generate a bidirectional horizontal bar chart for meta-analysis results.

    Bars extend left (negative) for sensitive genes (AUROC < 0.5) and right (positive)
    for resistant genes (AUROC > 0.5), centered at 0. Value plotted is (avg_auc - 0.5).
    """
    try:
        import io, base64
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.patches import Patch

        if not items:
            return None

        labels = [str(g.get(label_key, ""))[:40] for g in items]
        aurocs = [float(g.get("avg_auc", 0.5)) for g in items]
        # Center at 0: sensitive → negative, resistant → positive
        centered = [a - 0.5 for a in aurocs]
        colors = ["#3b82f6" if a < 0.5 else "#f97316" for a in aurocs]
        fdrs = [g.get("meta_fdr", 1.0) for g in items]

        # Sort: most sensitive (most negative) at bottom, most resistant at top
        order = sorted(range(len(centered)), key=lambda i: centered[i])
        labels   = [labels[i]   for i in order]
        centered = [centered[i] for i in order]
        aurocs   = [aurocs[i]   for i in order]
        colors   = [colors[i]   for i in order]
        fdrs     = [fdrs[i]     for i in order]

        fig_h = max(3.5, len(labels) * 0.27 + 1.2)
        fig, ax = plt.subplots(figsize=(9, fig_h))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        y_pos = np.arange(len(labels))
        # Alpha dim for FDR > 0.05
        alphas = [1.0 if abs(float(f)) <= 0.05 else 0.45 for f in fdrs]
        for y, val, col, alpha in zip(y_pos, centered, colors, alphas):
            ax.barh(y, val, height=0.75, color=col, edgecolor="none", alpha=alpha)

        ax.axvline(0, color="#444444", linewidth=1.0)

        # Value labels: right of bar for resistant, left for sensitive
        for y, val, auc in zip(y_pos, centered, aurocs):
            offset = 0.006 if val >= 0 else -0.006
            ha = "left" if val >= 0 else "right"
            ax.text(val + offset, y, f"{auc:.3f}", va="center", ha=ha,
                    fontsize=7.5, color="#333333")

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=8)
        max_ext = max(abs(v) for v in centered) if centered else 0.5
        ax.set_xlim(-(max_ext + 0.12), max_ext + 0.12)
        # x-axis ticks: show as AUROC values (add 0.5 back)
        tick_vals = np.linspace(-(max_ext + 0.1), max_ext + 0.1, 7)
        ax.set_xticks(tick_vals)
        ax.set_xticklabels([f"{v + 0.5:.2f}" for v in tick_vals], fontsize=8)
        ax.set_xlabel("Avg AUROC", fontsize=9)
        ax.set_title(title, fontsize=11, fontweight="bold", pad=8)

        ax.legend(handles=[
            Patch(facecolor="#3b82f6", alpha=1.0, label="Sensitive (AUROC < 0.5)"),
            Patch(facecolor="#f97316", alpha=1.0, label="Resistant (AUROC > 0.5)"),
            Patch(facecolor="#aaaaaa", alpha=0.45, label="FDR > 0.05"),
        ], loc="lower right", fontsize=8, frameon=False)

        fig.tight_layout()
        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()
        plt.close(fig)

        return {"title": title, "png_b64": png_b64, "type": "static_plot"}
    except Exception as e:
        logger.warning(f"[Meta-analysis chart] Failed: {e}")
        return None


def _generate_cis_correlation_static(data: dict, gene: str) -> Optional[dict]:
    """Generate a single grouped horizontal bar chart for cis-correlations.

    Data format: {cohort: [{x: mol1, y: mol2, val: float, pval: float}, ...]}
    Each pair appears twice (both directions); we deduplicate by canonical sorted key.
    Layout: y-axis = omics pairs, grouped bars = one bar per cancer cohort per pair.

    Args:
        data: {cohort: [record, ...]}
        gene: gene symbol for title
    Returns:
        dict with png_b64, svg, csv, title — or None on failure
    """
    try:
        import io, base64, csv as _csv
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        # ── 1. Parse records into canonical (pair_label → {cohort: (val, pval)}) ──
        pair_data: dict = {}   # {pair_label: {cohort: (val, pval)}}
        cohort_set: set = set()

        for cohort, records in data.items():
            if not isinstance(records, list):
                continue
            cohort_set.add(cohort)
            seen_pairs: set = set()
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                x = str(rec.get("x", "")).strip()
                y = str(rec.get("y", "")).strip()
                if not x or not y:
                    continue
                try:
                    val = float(rec.get("val", rec.get("value", rec.get("correlation", "nan"))))
                    pval = float(rec.get("pval", rec.get("pvalue", rec.get("p_value", "1"))))
                except (ValueError, TypeError):
                    continue
                parts = sorted([x, y])
                label = f"{parts[0]} ↔ {parts[1]}"
                if label in seen_pairs:
                    continue
                seen_pairs.add(label)
                if label not in pair_data:
                    pair_data[label] = {}
                pair_data[label][cohort] = (val, pval)

        if not pair_data or not cohort_set:
            return None

        cohorts = sorted(cohort_set)
        pairs = sorted(pair_data.keys())
        n_pairs = len(pairs)
        n_cohorts = len(cohorts)
        title = f"{gene} Cis-Correlations"

        # ── 2. Grouped horizontal bar chart ──
        cohort_colors = {c: _cohort_color(c, i) for i, c in enumerate(cohorts)}

        bar_h = 0.8 / n_cohorts   # height per bar within a group

        fig_w = 9.0
        fig_h = max(3.5, n_pairs * (0.28 * n_cohorts + 0.6))
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        offsets = np.linspace(-(n_cohorts - 1) / 2 * bar_h,
                               (n_cohorts - 1) / 2 * bar_h,
                               n_cohorts)

        # y positions for pair group label ticks
        ytick_pos = []

        for pi, pair_label in enumerate(pairs):
            group_center = pi
            for ci, cohort in enumerate(cohorts):
                entry = pair_data[pair_label].get(cohort)
                ypos = group_center + offsets[ci]
                if entry is None:
                    continue
                v, p = entry
                color = cohort_colors[cohort]
                alpha = 1.0 if p < 0.05 else 0.35
                ax.barh(ypos, v, height=bar_h * 0.85,
                        color=color, alpha=alpha, edgecolor="none")
                # Cohort label just inside the bar's base (left of axis for pos, right for neg)
                label_x = 0.02 if v >= 0 else -0.02
                label_ha = "left" if v >= 0 else "right"
                ax.text(label_x, ypos, cohort, ha=label_ha, va="center",
                        fontsize=6.5, color="white" if abs(v) > 0.15 else "#333333",
                        fontweight="bold", clip_on=True)
                # Significance asterisk beyond the bar tip
                if p < 0.05:
                    tip_x = v + (0.02 if v >= 0 else -0.02)
                    ax.text(tip_x, ypos, "*", ha=label_ha, va="center",
                            fontsize=9, color="#333333")

            ytick_pos.append(group_center)

        ax.axvline(0, color="#666666", linewidth=0.8, linestyle="--")
        ax.set_yticks(ytick_pos)
        ax.set_yticklabels(pairs, fontsize=9)
        ax.set_xlim(-1.15, 1.15)
        ax.set_xlabel("Pearson r", fontsize=9)
        ax.tick_params(axis="x", labelsize=8)

        fig.suptitle(title, fontsize=12, fontweight="bold", y=0.985)

        # Legend: significance guide only (cohort labels are inline)
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor="#888888", alpha=1.0,  label="p < 0.05  (*)"),
            Patch(facecolor="#888888", alpha=0.35, label="p ≥ 0.05 (ns)"),
        ]
        fig.legend(
            handles=legend_elements,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.945),
            ncol=2,
            fontsize=7.5,
            frameon=False,
            columnspacing=1.8,
            handletextpad=0.6,
        )

        fig.tight_layout(rect=[0, 0, 1, 0.88])

        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()
        plt.close(fig)

        # ── 3. CSV: deduplicated flat table ──
        csv_buf = io.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow(["cohort", "pair", "pearson_r", "pval", "significant"])
        for pair_label in pairs:
            for cohort in cohorts:
                entry = pair_data[pair_label].get(cohort)
                if entry:
                    v, p = entry
                    writer.writerow([cohort, pair_label, f"{v:.4f}", f"{p:.4g}", "yes" if p < 0.05 else "no"])

        return {"png_b64": png_b64, "svg": svg_str, "csv": csv_buf.getvalue(), "title": title}

    except Exception as e:
        logger.warning(f"[Cis-correlation] Failed to generate: {e}")
        return None


def _generate_tcga_omics_heatmap_static(results: list, gene: str, cohort: str) -> Optional[dict]:
    """Generate a horizontal bar chart of survival HR per omics type for TCGA mode 2.

    Args:
        results: [{omics, hr, pvalue, fdr, n}, ...]  (one entry per omics type)
        gene: gene symbol
        cohort: TCGA cohort name
    Returns:
        dict with png_b64, svg, csv, title — or None on failure
    """
    try:
        import io, base64, csv as _csv, math
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        _OMICS_LABEL = {
            "RNAseq": "RNA expression", "RPPA": "protein (RPPA)",
            "Methylation": "methylation", "SCNA": "copy number",
            "miRNASeq": "miRNA expression",
        }

        entries = []
        for res in results:
            hr = res.get("hr")
            pval = res.get("fdr") or res.get("pvalue")
            omics = res.get("omics", "")
            n = res.get("n")
            if hr is None or hr <= 0:
                continue
            entries.append({
                "omics": _OMICS_LABEL.get(omics, omics),
                "log2hr": math.log2(hr),
                "hr": hr,
                "pval": pval,
                "n": n,
                "sig": pval is not None and pval < 0.05,
            })
        if not entries:
            return None

        entries.sort(key=lambda e: e["log2hr"])
        title = f"{gene} Survival — {cohort} (all omics)"

        fig, ax = plt.subplots(figsize=(7, max(2.8, len(entries) * 0.6 + 1.2)))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        y_pos = list(range(len(entries)))
        colors = ["#c0392b" if e["log2hr"] > 0 else "#2980b9" for e in entries]
        edge_colors = ["#8e1a0e" if e["sig"] else "#aaaaaa" for e in entries]

        bars = ax.barh(y_pos, [e["log2hr"] for e in entries],
                       color=colors, edgecolor=edge_colors, linewidth=1.2,
                       height=0.6)

        for bar, entry in zip(bars, entries):
            label = f"HR={entry['hr']:.3f}"
            if entry["pval"] is not None:
                label += f"  p={entry['pval']:.2e}"
            if entry["sig"]:
                label += " *"
            x_off = 0.04 if entry["log2hr"] >= 0 else -0.04
            ha = "left" if entry["log2hr"] >= 0 else "right"
            ax.text(entry["log2hr"] + x_off, bar.get_y() + bar.get_height() / 2,
                    label, va="center", ha=ha, fontsize=8, color="#333333")

        ax.axvline(0, color="#555555", linewidth=0.9, linestyle="-")
        ax.set_yticks(y_pos)
        ax.set_yticklabels([e["omics"] for e in entries], fontsize=9)
        ax.set_xlabel("log₂(Hazard Ratio)\n← Protective  |  Harmful →", fontsize=9)
        ax.set_title(title, fontsize=11, pad=8)
        ax.text(0.99, 0.01, "* FDR < 0.05", transform=ax.transAxes,
                fontsize=8, color="#666666", ha="right", va="bottom")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", color="#eeeeee", linewidth=0.7)
        fig.tight_layout()

        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()
        plt.close(fig)

        csv_buf = io.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow(["omics", "hr", "log2_hr", "pvalue", "n", "significant"])
        for e in entries:
            writer.writerow([e["omics"], round(e["hr"], 6), round(e["log2hr"], 6),
                             f"{e['pval']:.4e}" if e["pval"] is not None else "",
                             e["n"] or "", "yes" if e["sig"] else "no"])

        return {"png_b64": png_b64, "svg": svg_str, "csv": csv_buf.getvalue(), "title": title}

    except Exception as e:
        logger.warning(f"[TCGA omics heatmap] Failed to generate: {e}")
        return None


def _generate_tcga_cohort_bar_static(results: list, gene: str, omics_label: str) -> Optional[dict]:
    """Generate a horizontal bar chart of log2(HR) per TCGA cohort for mode 3 (all cohorts).

    Args:
        results: [{cohort, hr, pvalue, n}, ...]
        gene: gene symbol
        omics_label: human-readable omics type label
    Returns:
        dict with png_b64, svg, csv, title — or None on failure
    """
    try:
        import io, base64, csv as _csv, math
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        entries = []
        for res in results:
            hr = res.get("hr")
            pval = res.get("fdr") or res.get("pvalue")
            cohort = res.get("cohort", "")
            n = res.get("n")
            if hr is None or hr <= 0 or not cohort:
                continue
            full_name = _TCGA_COHORT_NAMES.get(cohort, cohort)
            label = f"{cohort} — {full_name}" if full_name != cohort else cohort
            entries.append({
                "label": label,
                "cohort": cohort,
                "log2hr": math.log2(hr),
                "hr": hr,
                "pval": pval,
                "n": n,
                "sig": pval is not None and pval < 0.05,
            })
        if not entries:
            return None

        entries.sort(key=lambda e: e["log2hr"])
        title = f"{gene} {omics_label} Survival — all TCGA cohorts"

        fig, ax = plt.subplots(figsize=(8, max(3.5, len(entries) * 0.38 + 1.2)))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        y_pos = list(range(len(entries)))
        # Use per-cohort brand colors; alpha encodes significance
        bar_colors = [_cohort_color(e["cohort"], i) for i, e in enumerate(entries)]
        alphas = [1.0 if e["sig"] else 0.45 for e in entries]
        edge_colors = ["#333333" if e["sig"] else "#aaaaaa" for e in entries]
        lw = [1.2 if e["sig"] else 0.5 for e in entries]

        bars = ax.barh(y_pos, [e["log2hr"] for e in entries],
                       color=bar_colors, edgecolor=edge_colors, linewidth=lw, height=0.65)
        for bar, alpha in zip(bars, alphas):
            bar.set_alpha(alpha)

        # Annotate significant bars with p-value
        for bar, entry in zip(bars, entries):
            if entry["sig"] and entry["pval"] is not None:
                x_off = 0.04 if entry["log2hr"] >= 0 else -0.04
                ha = "left" if entry["log2hr"] >= 0 else "right"
                ax.text(entry["log2hr"] + x_off, bar.get_y() + bar.get_height() / 2,
                        f"p={entry['pval']:.1e} *", va="center", ha=ha,
                        fontsize=7, color="#333333")

        ax.axvline(0, color="#555555", linewidth=0.9)
        ax.set_yticks(y_pos)
        ax.set_yticklabels([e["label"] for e in entries], fontsize=8)
        ax.set_xlabel("log₂(Hazard Ratio)\n← Protective  |  Harmful →", fontsize=9)
        ax.set_title(title, fontsize=11, pad=8)
        ax.text(0.99, 0.01, "* p < 0.05  |  bold border = significant",
                transform=ax.transAxes, fontsize=7.5, color="#666666", ha="right", va="bottom")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", color="#eeeeee", linewidth=0.7)
        fig.tight_layout()

        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()
        plt.close(fig)

        csv_buf = io.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow(["cohort", "cancer", "hr", "log2_hr", "pvalue", "n", "significant"])
        for e in entries:
            writer.writerow([e["cohort"], _TCGA_COHORT_NAMES.get(e["cohort"], e["cohort"]),
                             round(e["hr"], 6), round(e["log2hr"], 6),
                             f"{e['pval']:.4e}" if e["pval"] is not None else "",
                             e["n"] or "", "yes" if e["sig"] else "no"])

        return {"png_b64": png_b64, "svg": svg_str, "csv": csv_buf.getvalue(), "title": title}

    except Exception as e:
        logger.warning(f"[TCGA cohort bar] Failed to generate: {e}")
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _tcga_survival_mode4_top_hits(
    results: list[dict[str, Any]],
    *,
    limit: int = 10,
    fdr_threshold: float = 0.05,
) -> list[dict[str, Any]]:
    """Return the most significant genome-wide TCGA survival hits."""
    import math

    hits: list[dict[str, Any]] = []
    for row in results or []:
        gene = row.get("gene", "")
        hr = _safe_float(row.get("hr"))
        fdr = _safe_float(row.get("fdr") if row.get("fdr") is not None else row.get("pvalue"))
        if not gene or hr is None or hr <= 0 or fdr is None or fdr >= fdr_threshold:
            continue
        hits.append({
            "gene": gene,
            "hr": hr,
            "log2_hr": math.log2(hr),
            "fdr": fdr,
            "n": row.get("n", ""),
            "direction": "harmful" if hr > 1 else "protective",
        })

    return sorted(hits, key=lambda entry: entry["fdr"])[:limit]


def _tcga_survival_mode2_effect_entries(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize TCGA survival mode-2 entries using the same ordering as the plot."""
    import math

    omics_labels = {
        "RNAseq": "RNA expression",
        "RPPA": "protein (RPPA)",
        "Methylation": "methylation",
        "SCNA": "copy number",
        "miRNASeq": "miRNA expression",
    }

    entries: list[dict[str, Any]] = []
    for row in results or []:
        hr = _safe_float(row.get("hr"))
        if hr is None or hr <= 0:
            continue
        pval = _safe_float(row.get("fdr") if row.get("fdr") is not None else row.get("pvalue"))
        omics = row.get("omics", "")
        entries.append({
            "omics": omics_labels.get(omics, omics),
            "hr": hr,
            "log2_hr": math.log2(hr),
            "pvalue": pval,
            "n": row.get("n", ""),
            "significant": pval is not None and pval < 0.05,
        })

    return sorted(entries, key=lambda entry: entry["log2_hr"])


def _tcga_survival_mode3_effect_entries(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize TCGA survival mode-3 entries using the same ordering as the cohort bar chart."""
    import math

    entries: list[dict[str, Any]] = []
    for row in results or []:
        hr = _safe_float(row.get("hr"))
        cohort = row.get("cohort", "")
        if hr is None or hr <= 0 or not cohort:
            continue
        pval = _safe_float(row.get("fdr") if row.get("fdr") is not None else row.get("pvalue"))
        entries.append({
            "cohort": cohort,
            "cancer": _TCGA_COHORT_NAMES.get(cohort, cohort),
            "hr": hr,
            "log2_hr": math.log2(hr),
            "pvalue": pval,
            "n": row.get("n", ""),
            "significant": pval is not None and pval < 0.05,
        })

    return sorted(entries, key=lambda entry: entry["log2_hr"])


def _compact_tcga_survival_group_for_summary(
    parsed_list: list[dict[str, Any]],
    gene_name: str = "",
    cohort_key: str = "",
) -> dict[str, Any]:
    """Build a summary-friendly grouped representation matching rendered TCGA survival sections."""
    all_results: list[dict[str, Any]] = []
    mode = 1
    omics_query = ""
    query_gene = ""
    for parsed in parsed_list or []:
        if not isinstance(parsed, dict):
            continue
        mode = parsed.get("mode", mode)
        query = parsed.get("query", {}) or {}
        omics_query = omics_query or query.get("omics", "")
        query_gene = query_gene or query.get("gene", "")
        all_results.extend(parsed.get("results") or [])

    gene = (query_gene or gene_name or "").upper()
    compact: dict[str, Any] = {
        "dataset": "TCGA survival analysis",
        "mode": mode,
        "query": {
            "gene": gene,
            "cohort": cohort_key,
            "omics": omics_query,
        },
        "n_results": len(all_results),
    }

    if not all_results:
        return compact

    if mode == 4:
        top_hits = _tcga_survival_mode4_top_hits(all_results, limit=10, fdr_threshold=0.05)
        compact.update({
            "n_significant_fdr_lt_0_05": len(_tcga_survival_mode4_top_hits(all_results, limit=len(all_results), fdr_threshold=0.05)),
            "ranking_basis": "Use `top_genes_by_fdr_lt_0_05` as the authoritative strongest-hit ranking. It matches the Top prognostic genes table shown with the volcano plot.",
            "top_genes_by_fdr_lt_0_05": top_hits,
        })
        return compact

    if mode == 3 and not cohort_key:
        import math

        entries = _tcga_survival_mode3_effect_entries(all_results)
        compact.update({
            "ranking_basis": "Use `top_harmful_cohorts_by_log2_hr` and `top_protective_cohorts_by_log2_hr` for the all-cohort bar chart ordering. Use `km_plots_generated_for_significant_cohorts` only when referring to the Kaplan-Meier plots appended below that chart.",
            "top_protective_cohorts_by_log2_hr": entries[:5],
            "top_harmful_cohorts_by_log2_hr": list(reversed(entries[-5:])),
            "km_plots_generated_for_significant_cohorts": [
                {
                    "cohort": row.get("cohort", ""),
                    "cancer": _TCGA_COHORT_NAMES.get(row.get("cohort", ""), row.get("cohort", "")),
                    "hr": hr,
                    "log2_hr": math.log2(hr) if hr is not None and hr > 0 else None,
                    "pvalue": pval,
                    "n": row.get("n", ""),
                    "significant": True,
                }
                for row in sorted(
                    all_results,
                    key=lambda result: _safe_float(result.get("fdr") if result.get("fdr") is not None else result.get("pvalue")) or 1.0,
                )
                for hr in [_safe_float(row.get("hr"))]
                for pval in [_safe_float(row.get("fdr") if row.get("fdr") is not None else row.get("pvalue"))]
                if row.get("cohort") and pval is not None and pval < 0.05
            ][:5],
        })
        return compact

    if mode == 2:
        entries = _tcga_survival_mode2_effect_entries(all_results)
        compact.update({
            "ranking_basis": "Use `omics_ranked_by_log2_hr` as the authoritative ordering for the all-omics survival bar chart.",
            "omics_ranked_by_log2_hr": entries,
        })
        return compact

    first = all_results[0]
    compact.update({
        "ranking_basis": "Single-result survival lookup.",
        "correlation_context": {
            "gene": first.get("gene", gene),
            "hr": _safe_float(first.get("hr")),
            "pvalue": _safe_float(first.get("fdr") if first.get("fdr") is not None else first.get("pvalue")),
            "n": first.get("n", ""),
        },
    })
    return compact


def _trial_records_for_summary(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten trial results into a unified list for ranking."""
    resistant = data.get("resistant", data.get("top_resistant", [])) or []
    sensitive = data.get("sensitive", data.get("top_sensitive", [])) or []

    records: list[dict[str, Any]] = []
    for direction, studies in (("resistant", resistant), ("sensitive", sensitive)):
        for study in studies:
            if not isinstance(study, dict):
                continue
            auroc = _safe_float(study.get("auroc"))
            fdr = _safe_float(study.get("fdr"))
            records.append({
                "treatment": str(study.get("treatment", "") or ""),
                "series": study.get("series", ""),
                "study_id": study.get("study_id", ""),
                "direction": direction,
                "auroc": auroc if auroc is not None else 0.5,
                "fdr": fdr,
                "pvalue": _safe_float(study.get("p_value")),
                "sample_size": study.get("sample_size", ""),
                "disease": study.get("disease", ""),
                "subtype": study.get("subtype", ""),
            })
    return records


def _compact_trial_dataset_for_summary(data: dict[str, Any], label: str) -> dict[str, Any]:
    """Build a compact trial summary aligned to the AUROC chart and ranked table."""
    records = _trial_records_for_summary(data)
    compact: dict[str, Any] = {
        "label": label,
        "total_significant": data.get("total_significant", ""),
        "total_studies": data.get("total_studies", ""),
    }
    if not records:
        return compact

    top_by_fdr = sorted(
        records,
        key=lambda rec: abs(rec["fdr"]) if rec["fdr"] is not None else 1.0,
    )[:10]
    top_by_auroc = sorted(
        records,
        key=lambda rec: (
            -abs(rec["auroc"] - 0.5),
            abs(rec["fdr"]) if rec["fdr"] is not None else 1.0,
            rec["treatment"],
            rec["study_id"],
        ),
    )[:10]

    compact.update({
        "ranking_basis": "Use `top_studies_by_abs_fdr` for the most statistically supported associations. Use `top_studies_by_auroc_extremity` for the strongest response separation. The AUROC bar chart itself is display-ordered from low to high AUROC.",
        "top_studies_by_abs_fdr": top_by_fdr,
        "top_studies_by_auroc_extremity": top_by_auroc,
    })
    return compact


def _compact_meta_analysis_payload_for_summary(
    payload: dict[str, Any],
    *,
    item_key: str,
    label_key: str,
) -> dict[str, Any]:
    """Build a summary-friendly meta-analysis payload aligned with the plotted subset."""
    status = payload.get("status", "unavailable")
    data = payload.get("data") or {}
    items = data.get(item_key) or []

    compact: dict[str, Any] = {
        "status": status,
        "study_count": data.get("study_count", 0),
        "filters": data.get("filters", {}),
    }
    if status != "available" or not items:
        return compact

    compact.update({
        "ranking_basis": "Use `reported_top_items` as the authoritative ranking. The bidirectional bar chart uses only the first 25 reported items and reorders them by effect direction for display.",
        "reported_top_items": [
            {
                "rank": idx,
                "label": item.get(label_key, ""),
                "avg_auroc": _safe_float(item.get("avg_auc")),
                "meta_fdr": _safe_float(item.get("meta_fdr")),
                "direction": item.get("direction", ""),
            }
            for idx, item in enumerate(items[:10], 1)
        ],
        "plot_subset_first_25": [item.get(label_key, "") for item in items[:25]],
    })
    return compact


def _funmap_displayed_neighbors(payload: dict[str, Any], gene_name: str = "") -> list[str]:
    """Return the neighbor set actually shown in the plotted network."""
    gene = (gene_name or "").upper()
    nodes = payload.get("nodes") or []
    displayed = [
        node.get("name", "")
        for node in nodes
        if isinstance(node, dict) and node.get("name") and node.get("name") != gene
    ][:50]
    if displayed:
        return displayed
    neighborhood = payload.get("neighborhood") or []
    return [neighbor for neighbor in neighborhood if neighbor and neighbor != gene][:50]


def _tcga_cis_mode4_entries(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize genome-wide TCGA cis-association rows for plotting and summarization."""
    import math

    entries: list[dict[str, Any]] = []
    for row in results or []:
        gene = row.get("gene", "")
        cor = row.get("correlation")
        fdr = row.get("fdr") if row.get("fdr") is not None else row.get("pvalue")
        if cor is None or fdr is None or not gene:
            continue
        try:
            cor_f = float(cor)
            fdr_f = max(float(fdr), 1e-300)
        except (ValueError, TypeError):
            continue
        entries.append({
            "gene": gene,
            "cor": cor_f,
            "fdr": fdr_f,
            "y": -math.log10(fdr_f),
            "pvalue": row.get("pvalue", ""),
            "n": row.get("n", ""),
        })
    return entries


def _tcga_cis_mode4_top_hits(
    results: list[dict[str, Any]],
    *,
    limit: int = 50,
    fdr_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Return the strongest mode-4 cis hits ranked by absolute correlation."""
    entries = _tcga_cis_mode4_entries(results)
    return sorted(
        [entry for entry in entries if entry["fdr"] < fdr_threshold],
        key=lambda entry: (-abs(entry["cor"]), entry["fdr"], entry["gene"]),
    )[:limit]


def _generate_tcga_cis_association_static(result: dict) -> Optional[list[dict[str, Any]]]:
    """Generate mode-appropriate visualizations for tcga_cis_association_analysis.

    API always uses `correlation` (not `cor`). Modes 1 and 2 include `samples`.

    Mode 1 — scatter plot (sample points, single omics pair)
    Mode 2 — multi-panel scatter grid (one subplot per omics pair, using sample data)
    Mode 3 — horizontal bar chart (correlation per cohort, pan-cancer)
    Mode 4 — volcano plot + bidirectional bar chart for top genome-wide hits
    """
    try:
        import io, base64, csv as _csv, math
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        import numpy as np

        mode = result.get("mode")
        results = result.get("results", [])
        query = result.get("query", {})
        gene = (query.get("gene") or "").upper()
        cohort = query.get("cohort") or ""
        source_omics = query.get("source_omics") or ""
        target_omics = query.get("target_omics") or ""
        omics_label = f"{source_omics} → {target_omics}" if source_omics and target_omics else (source_omics or target_omics or "omics")

        _SHORT = {
            "RNAseq": "RNA", "RPPA": "RPPA", "Methylation": "Methyl.",
            "SCNA": "SCNA", "miRNASeq": "miRNA",
        }

        if not results:
            return None

        # ── helpers ──────────────────────────────────────────────────────────

        def _serialize_figure(fig, csv_rows, title_str):
            png_buf = io.BytesIO()
            fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
            png_buf.seek(0)
            png_b64 = base64.b64encode(png_buf.read()).decode()

            svg_buf = io.BytesIO()
            fig.savefig(svg_buf, format="svg", bbox_inches="tight")
            svg_buf.seek(0)
            svg_str = svg_buf.read().decode()
            plt.close(fig)

            csv_buf = io.StringIO()
            writer = _csv.writer(csv_buf)
            for row in csv_rows:
                writer.writerow(row)

            return {"png_b64": png_b64, "svg": svg_str, "csv": csv_buf.getvalue(), "title": title_str}

        def _scatter_panel(ax, xs, ys_pts, cor_val, pval_val, x_lbl, y_lbl, title_str="", dot_color="#2980b9"):
            """Draw a single scatter subplot with regression line and stat box."""
            ax.scatter(xs, ys_pts, s=10, alpha=0.45, color=dot_color, linewidths=0, rasterized=True)
            try:
                m, b_val = np.polyfit(xs, ys_pts, 1)
                x_line = np.linspace(min(xs), max(xs), 100)
                ax.plot(x_line, m * x_line + b_val, color="#c0392b", linewidth=1.2, linestyle="--")
            except Exception:
                pass
            parts = []
            if cor_val is not None:
                parts.append(f"r={float(cor_val):.3f}")
            if pval_val is not None:
                parts.append(f"p={float(pval_val):.1e}")
            stat_txt = "  ".join(parts)
            ax.set_xlabel(x_lbl, fontsize=7)
            ax.set_ylabel(y_lbl, fontsize=7)
            if title_str:
                ax.set_title(title_str, fontsize=8, pad=4)
            ax.tick_params(labelsize=6)
            ax.spines[["top", "right"]].set_visible(False)
            if stat_txt:
                ax.text(0.97, 0.04, stat_txt, transform=ax.transAxes, fontsize=7,
                        ha="right", va="bottom", color="#333333",
                        bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                                  edgecolor="#cccccc", alpha=0.88))

        def _bar_chart(entries, title, x_label):
            """Horizontal bar chart of correlation values, colored by direction + significance."""
            n = len(entries)
            fig_h = max(3.0, n * 0.42 + 1.4)
            fig, ax = plt.subplots(figsize=(8, fig_h))
            fig.patch.set_facecolor("white")
            ax.set_facecolor("white")
            y_pos = list(range(n))
            for i, (yp, e) in enumerate(zip(y_pos, entries)):
                sig = e["pval"] < 0.05
                color = "#c0392b" if e["cor"] > 0 else "#2980b9"
                alpha = 1.0 if sig else 0.40
                ax.barh(yp, e["cor"], color=color, alpha=alpha, height=0.62, edgecolor="none")
                off = 0.015 if e["cor"] >= 0 else -0.015
                ha = "left" if e["cor"] >= 0 else "right"
                txt = f"r = {e['cor']:.3f}"
                if sig:
                    txt += " *"
                ax.text(e["cor"] + off, yp, txt, va="center", ha=ha, fontsize=8, color="#333333")
            ax.axvline(0, color="#444444", linewidth=0.8, linestyle="--")
            ax.set_yticks(y_pos)
            ax.set_yticklabels([e["label"] for e in entries], fontsize=8.5)
            ax.set_xlabel(x_label, fontsize=9)
            ax.set_title(title, fontsize=10, pad=8)
            ax.text(0.99, 0.01, "* p < 0.05  |  faded = not significant",
                    transform=ax.transAxes, fontsize=7.5, color="#666666", ha="right", va="bottom")
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(axis="x", color="#eeeeee", linewidth=0.6)
            fig.tight_layout()
            return fig

        # ── Mode 1: single pair → scatter plot ───────────────────────────────
        if mode == 1:
            r0 = results[0]
            samples = r0.get("samples", [])
            if not samples or not isinstance(samples, list):
                return None
            xs = [s["source_val"] for s in samples if s.get("source_val") is not None]
            ys_pts = [s["target_val"] for s in samples if s.get("target_val") is not None]
            if len(xs) < 3:
                return None
            src_lbl = _SHORT.get(source_omics, source_omics)
            tgt_lbl = _SHORT.get(target_omics, target_omics)
            title = f"{gene} Cis Association — {cohort}  ({source_omics} → {target_omics})"
            fig, ax = plt.subplots(figsize=(5.5, 5.0))
            fig.patch.set_facecolor("white")
            ax.set_facecolor("white")
            # pass cor=None so _scatter_panel skips its small stat box; we draw a fuller one
            _scatter_panel(ax, xs, ys_pts, None, None, source_omics, target_omics)
            n_pts = r0.get("n", len(xs))
            cor_val = r0.get("correlation")
            pval_val = r0.get("pvalue")
            ax.set_title(title, fontsize=10, pad=8)
            stat_txt = (
                f"r = {cor_val:.4f}\np = {pval_val:.2e}\nn = {n_pts}"
                if cor_val is not None and pval_val is not None
                else f"n = {n_pts}"
            )
            ax.text(0.97, 0.04, stat_txt, transform=ax.transAxes, fontsize=9,
                    ha="right", va="bottom", color="#333333",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#cccccc", alpha=0.9))
            fig.tight_layout()
            csv_rows = [["source_val", "target_val"]] + [
                [s.get("source_val", ""), s.get("target_val", "")] for s in samples
            ]
            return [_serialize_figure(fig, csv_rows, title)]

        # ── Mode 2: gene + cohort, all omics pairs → scatter grid ────────────
        elif mode == 2:
            # Build panel list — one per result that has sample data
            panels = []
            for r in results:
                src = r.get("source_omics", "")
                tgt = r.get("target_omics", "")
                samples = r.get("samples", [])
                cor = r.get("correlation")
                pval = r.get("pvalue")
                if not samples or cor is None:
                    continue
                xs = [s["source_val"] for s in samples if s.get("source_val") is not None]
                ys_pts = [s["target_val"] for s in samples if s.get("target_val") is not None]
                if len(xs) < 3:
                    continue
                panels.append({
                    "xs": xs, "ys": ys_pts,
                    "cor": float(cor), "pval": float(pval) if pval is not None else 1.0,
                    "src": src, "tgt": tgt,
                    "src_short": _SHORT.get(src, src), "tgt_short": _SHORT.get(tgt, tgt),
                })
            if not panels:
                return None

            n = len(panels)
            ncols = min(3, n)
            nrows = math.ceil(n / ncols)
            fig_w = ncols * 3.4
            fig_h = nrows * 3.2 + 0.6
            title = f"{gene} Cis Associations — {cohort} (all omics pairs)"
            fig = plt.figure(figsize=(fig_w, fig_h))
            fig.patch.set_facecolor("white")
            fig.suptitle(title, fontsize=11, y=1.01)

            for i, p in enumerate(panels):
                ax = fig.add_subplot(nrows, ncols, i + 1)
                ax.set_facecolor("white")
                sig = p["pval"] < 0.05
                dot_color = "#c0392b" if (sig and p["cor"] > 0) else "#2980b9" if (sig and p["cor"] <= 0) else "#888888"
                panel_title = f"{p['src_short']} → {p['tgt_short']}"
                _scatter_panel(ax, p["xs"], p["ys"], p["cor"], p["pval"],
                               p["src_short"], p["tgt_short"],
                               title_str=panel_title, dot_color=dot_color)

            fig.tight_layout()
            csv_rows = [["source_omics", "target_omics", "correlation", "pvalue", "n"]] + [
                [p["src"], p["tgt"], p["cor"], p["pval"], len(p["xs"])] for p in panels
            ]
            return [_serialize_figure(fig, csv_rows, title)]

        # ── Mode 3: gene + omics pair, all cohorts → bar chart ───────────────
        elif mode == 3:
            entries = []
            for r in results:
                coh = r.get("cohort", "")
                cor = r.get("correlation")
                pval = r.get("pvalue")
                if cor is None or not coh:
                    continue
                full = _TCGA_COHORT_NAMES.get(coh, coh)
                entries.append({
                    "cohort": coh,
                    "label": f"{coh} — {full}" if full != coh else coh,
                    "cor": float(cor),
                    "pval": float(pval) if pval is not None else 1.0,
                    "n": r.get("n", ""),
                })
            if not entries:
                return None
            entries.sort(key=lambda e: e["cor"])
            title = f"{gene} Cis Association — {omics_label} across TCGA cohorts"
            fig = _bar_chart(entries, title, "Spearman correlation (r)")
            csv_rows = [["cohort", "cancer_type", "correlation", "pvalue", "n"]] + [
                [e["cohort"], _TCGA_COHORT_NAMES.get(e["cohort"], e["cohort"]),
                 e["cor"], e["pval"], e["n"]] for e in entries
            ]
            return [_serialize_figure(fig, csv_rows, title)]

        # ── Mode 4: genome-wide scan → volcano plot ───────────────────────────
        elif mode == 4:
            entries = _tcga_cis_mode4_entries(results)
            if not entries:
                return None

            xs = [e["cor"] for e in entries]
            ys = [e["y"] for e in entries]
            fdr_thresh = -math.log10(0.05)
            colors_list = [
                "#c0392b" if (e["fdr"] < 0.05 and e["cor"] > 0.3) else
                "#2980b9" if (e["fdr"] < 0.05 and e["cor"] < -0.3) else
                "#f39c12" if (e["fdr"] < 0.05) else "#bbbbbb"
                for e in entries
            ]
            title = f"Genome-wide Cis Association — {cohort} ({omics_label})"
            fig, ax = plt.subplots(figsize=(9.8, 5.8))
            fig.patch.set_facecolor("white")
            ax.set_facecolor("white")
            ax.scatter(xs, ys, c=colors_list, s=11, alpha=0.65, linewidths=0, rasterized=True)

            # Label top significant genes (highest -log10 FDR)
            sig_entries = sorted(
                [(i, e) for i, e in enumerate(entries) if e["fdr"] < 0.05 and abs(e["cor"]) > 0.3],
                key=lambda ie: ie[1]["y"], reverse=True
            )[:18]
            for idx, e in sig_entries:
                ax.text(e["cor"], e["y"] + 0.06, e["gene"], fontsize=6,
                        ha="center", va="bottom", color="#222222", clip_on=True)

            ax.axhline(fdr_thresh, color="#666666", linewidth=0.85, linestyle="--")
            ax.axvline(0.3, color="#888888", linewidth=0.7, linestyle=":")
            ax.axvline(-0.3, color="#888888", linewidth=0.7, linestyle=":")
            ax.axvline(0, color="#444444", linewidth=0.5, linestyle="-")
            ax.set_xlabel("Spearman correlation (r)", fontsize=9)
            ax.set_ylabel("-log₁₀(FDR)", fontsize=9)
            ax.set_title(title, fontsize=10, pad=8)
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(color="#f0f0f0", linewidth=0.5)

            from matplotlib.patches import Patch
            ax.legend(handles=[
                Patch(color="#c0392b", label="FDR<0.05, r>0.3 (positive)"),
                Patch(color="#2980b9", label="FDR<0.05, r<−0.3 (negative)"),
                Patch(color="#f39c12", label="FDR<0.05, |r|≤0.3"),
                Patch(color="#bbbbbb", label="not significant"),
            ], fontsize=7.5, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0, framealpha=0.9)

            # Count sig genes
            n_pos = sum(1 for e in entries if e["fdr"] < 0.05 and e["cor"] > 0.3)
            n_neg = sum(1 for e in entries if e["fdr"] < 0.05 and e["cor"] < -0.3)
            ax.text(0.01, 0.97, f"Positive: {n_pos}  Negative: {n_neg}  Total genes: {len(entries)}",
                    transform=ax.transAxes, fontsize=8, color="#555555", va="top")
            fig.tight_layout(rect=(0, 0, 0.82, 1))
            volcano_csv_rows = [["gene", "correlation", "fdr", "pvalue", "n"]] + [
                [e["gene"], e["cor"], e["fdr"], e["pvalue"], e["n"]] for e in entries
            ]
            plots = [_serialize_figure(fig, volcano_csv_rows, title)]

            top_bar_entries = _tcga_cis_mode4_top_hits(results, limit=50, fdr_threshold=0.5)
            if top_bar_entries:
                bar_title = f"Top Cis-Associated Genes — {cohort} ({omics_label}, FDR < 0.5)"
                fig_h = max(6.0, len(top_bar_entries) * 0.28 + 1.8)
                fig, ax = plt.subplots(figsize=(9.2, fig_h))
                fig.patch.set_facecolor("white")
                ax.set_facecolor("white")

                y_pos = np.arange(len(top_bar_entries))
                colors = ["#c0392b" if e["cor"] >= 0 else "#2980b9" for e in top_bar_entries]
                alphas = [1.0 if e["fdr"] < 0.05 else 0.65 for e in top_bar_entries]
                bars = ax.barh(y_pos, [e["cor"] for e in top_bar_entries], color=colors, height=0.68, edgecolor="none")
                for bar, alpha in zip(bars, alphas):
                    bar.set_alpha(alpha)

                max_abs_cor = max(abs(e["cor"]) for e in top_bar_entries)
                x_pad = max(0.04, max_abs_cor * 0.14)
                text_pad = max(0.015, max_abs_cor * 0.03)
                ax.set_xlim(-(max_abs_cor + x_pad), max_abs_cor + x_pad)
                ax.axvline(0, color="#444444", linewidth=0.8, linestyle="--")
                ax.grid(axis="x", color="#eeeeee", linewidth=0.6)
                ax.set_yticks(y_pos)
                ax.set_yticklabels([e["gene"] for e in top_bar_entries], fontsize=7.5)
                ax.invert_yaxis()
                ax.set_xlabel("Correlation (r)", fontsize=9)
                ax.set_title(bar_title, fontsize=10, pad=8)
                ax.text(
                    0.99,
                    0.01,
                    "Ranked by |r|  |  opaque = FDR < 0.05  |  faded = 0.05 ≤ FDR < 0.5",
                    transform=ax.transAxes,
                    fontsize=7.5,
                    color="#666666",
                    ha="right",
                    va="bottom",
                )
                ax.spines[["top", "right"]].set_visible(False)

                for yp, entry in zip(y_pos, top_bar_entries):
                    x_val = entry["cor"]
                    ax.text(
                        x_val + (text_pad if x_val >= 0 else -text_pad),
                        yp,
                        f"{x_val:.3f}",
                        va="center",
                        ha="left" if x_val >= 0 else "right",
                        fontsize=6.6,
                        color="#333333",
                    )

                fig.tight_layout()
                bar_csv_rows = [["rank", "gene", "correlation", "abs_correlation", "fdr", "pvalue", "n"]] + [
                    [rank, e["gene"], e["cor"], abs(e["cor"]), e["fdr"], e["pvalue"], e["n"]]
                    for rank, e in enumerate(top_bar_entries, 1)
                ]
                plots.append(_serialize_figure(fig, bar_csv_rows, bar_title))

            return plots

        else:
            return None

    except Exception as e:
        logger.warning(f"[TCGA cis association] Failed to generate plot: {e}")
        return None


def _generate_funmap_network_static(nodes: list, edges: list, gene: str) -> Optional[dict]:
    """Generate a spring-layout network graph for FunMap functional partners.

    Args:
        nodes: list of dicts with "name" and "value" keys from the API
        edges: list of dicts with "source" and "target" keys from the API
        gene: query gene symbol (center node)
    Returns:
        dict with png_b64, svg, csv, title — or None on failure
    """
    try:
        import io, base64, csv as _csv
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx

        # Build node set (cap at 50 neighbors for readability)
        all_names = [n["name"] for n in nodes if isinstance(n, dict) and n.get("name")]
        neighbors = [n for n in all_names if n != gene][:50]
        shown_nodes = set(neighbors) | {gene}

        if not neighbors:
            return None

        title = f"{gene} Functional Network — FunMap"

        G = nx.Graph()
        for name in shown_nodes:
            G.add_node(name)

        # Use actual edges from the API; fall back to star topology if none match
        edge_count = 0
        for e in edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            if src in shown_nodes and tgt in shown_nodes:
                G.add_edge(src, tgt)
                edge_count += 1
        if edge_count == 0:
            for n in neighbors:
                G.add_edge(gene, n)

        pos = nx.spring_layout(G, seed=42, k=2.2 / max(len(neighbors) ** 0.5, 1))

        fig_side = max(7, min(12, 5.5 + len(neighbors) * 0.15))
        fig, ax = plt.subplots(figsize=(fig_side, fig_side))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#cccccc", width=0.8, alpha=0.7)
        nx.draw_networkx_nodes(G, pos, ax=ax,
                               nodelist=[gene],
                               node_color="#c0392b", node_size=700, alpha=0.95)
        nx.draw_networkx_nodes(G, pos, ax=ax,
                               nodelist=neighbors,
                               node_color="#2980b9", node_size=240, alpha=0.75)
        nx.draw_networkx_labels(G, pos, ax=ax,
                                labels={gene: gene},
                                font_size=10, font_weight="bold", font_color="white")
        nx.draw_networkx_labels(G, pos, ax=ax,
                                labels={n: n for n in neighbors},
                                font_size=7.5, font_color="#222222")

        ax.set_title(title, fontsize=11, pad=8)
        ax.text(0.5, -0.02,
                f"{len(neighbors)} nodes · {G.number_of_edges()} edges  ·  Center node = {gene}",
                transform=ax.transAxes, fontsize=8.5, color="#666666", ha="center")
        ax.axis("off")
        fig.tight_layout()

        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight")
        png_buf.seek(0)
        png_b64 = base64.b64encode(png_buf.read()).decode()

        svg_buf = io.BytesIO()
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        svg_buf.seek(0)
        svg_str = svg_buf.read().decode()
        plt.close(fig)

        # CSV: full edge list from API (filtered to shown nodes)
        csv_buf = io.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow(["source", "target"])
        for e in edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            if src in shown_nodes and tgt in shown_nodes:
                writer.writerow([src, tgt])
        if edge_count == 0:
            for n in neighbors:
                writer.writerow([gene, n])

        return {"png_b64": png_b64, "svg": svg_str, "csv": csv_buf.getvalue(), "title": title}

    except Exception as e:
        logger.warning(f"[FunMap network] Failed to generate: {e}")
        return None


class MCPOrchestrator:
    """Orchestrator that uses MCP tools instead of direct agent calls"""
    
    def __init__(self):
        self.mcp_aggregator = MCPAggregator()
        self.llm = LLMFactory.create_llm(
            model=settings.DEFAULT_LLM_MODEL,
            temperature=0.3
        )
        self.sessions = {}

        # LangGraph delegate (initialised lazily in initialize())
        self._langgraph_orch = None
        if settings.USE_LANGGRAPH:
            try:
                from services.langgraph_orchestrator import LangGraphOrchestrator
                # Pass self so LangGraph shares our sessions dict and DB session
                # methods — this ensures chat history persists and the chat API
                # (GET /sessions/{id}, etc.) continues to work unchanged.
                self._langgraph_orch = LangGraphOrchestrator(parent_orchestrator=self)
                logger.info("LangGraphOrchestrator created — will be used for process_query.")
            except Exception as e:
                logger.warning(f"Could not create LangGraphOrchestrator: {e}. Falling back to legacy planner.")

        # Try to load valid genes for strict validation
        self.valid_genes = set()
        try:
            import os
            # Assume valid_genes.txt is in the project root (2 levels up from services/)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            valid_genes_path = os.path.join(project_root, "valid_genes.txt")
            if os.path.exists(valid_genes_path):
                with open(valid_genes_path, "r") as f:
                    self.valid_genes = {line.strip().upper() for line in f if line.strip()}
                logger.info(f"Loaded {len(self.valid_genes)} valid genes from {valid_genes_path}")
            else:
                logger.warning(f"valid_genes.txt not found at {valid_genes_path}, falling back to loose validation")
        except Exception as e:
            logger.error(f"Failed to load valid_genes.txt: {e}")

        # Expert guidelines for biological reasoning
        self.BIO_GUIDELINES = """
### BIOLOGICAL REASONING GUIDELINES:
1. **Statistical Significance**: A p-value < 0.05 is typically significant. For survival curves (Kaplan-Meier), a lower p-value indicates a stronger correlation.
2. **Omics Vocabulary**:
   - 'mRNA/RNA' refers to gene expression levels.
   - 'Protein' refers to proteomic abundance.
   - 'Log Ratio' or 'Fold Change' indicates relative expression (positive = upregulated, negative = downregulated).
3. **Cross-Omics Synthesis**: If you have information about both expression and survival, explain how they relate (e.g., "High expression of MYC correlates with poor survival outcomes, suggesting oncogenic potential").
4. **Context Matters**: LinkedOmics data comes from specific CPTAC and TCGA cohorts. Always mention the cancer type (e.g., GBM, BRCA) if known.
"""

    def _default_llm_model_name(self) -> Optional[str]:
        """Best-effort model name for usage attribution."""
        return (
            getattr(self.llm, "model_name", None)
            or getattr(self.llm, "model", None)
            or settings.DEFAULT_LLM_MODEL
        )

    def _new_llm_usage_tracker(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initialize a per-query usage accumulator."""
        return {
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "model": model or self._default_llm_model_name(),
        }

    def _record_llm_usage(
        self,
        usage_tracker: Optional[Dict[str, Any]],
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: Optional[str] = None,
    ) -> None:
        """Accumulate LLM usage into a mutable per-query tracker."""
        if usage_tracker is None:
            return
        usage_tracker["input_tokens"] = int(usage_tracker.get("input_tokens", 0) or 0) + int(input_tokens or 0)
        usage_tracker["output_tokens"] = int(usage_tracker.get("output_tokens", 0) or 0) + int(output_tokens or 0)
        if model:
            usage_tracker["model"] = model

    async def _invoke_llm_tracked(
        self,
        messages: List[Any],
        usage_tracker: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        """Invoke the configured LLM and merge any reported usage into the tracker."""
        result = await LLMFactory.invoke_async_with_metadata(self.llm, messages, **kwargs)
        self._record_llm_usage(
            usage_tracker,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            model=result.model,
        )
        return result.text
    
    async def initialize(self):
        """Initialize MCP connections (and the LangGraph agent if enabled)."""
        logger.info("Initializing MCP Orchestrator...")
        await self.mcp_aggregator.initialize()
        logger.info("MCP Orchestrator initialized")
        if self._langgraph_orch:
            try:
                await self._langgraph_orch.initialize()
                logger.info("LangGraphOrchestrator initialized successfully.")
            except Exception as e:
                logger.warning(f"LangGraphOrchestrator init failed: {e}. Falling back to legacy planner.")
                self._langgraph_orch = None
    
    async def cleanup(self):
        """Cleanup resources."""
        if self._langgraph_orch:
            await self._langgraph_orch.cleanup()
        await self.mcp_aggregator.cleanup()
        self.sessions.clear()
        logger.info("MCP Orchestrator cleaned up")
    
    async def process_query_stream(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream the execution progress using Server-Sent Events (SSE).
        Delegates to LangGraph if enabled.
        """
        if self._langgraph_orch:
            # We must use 'async for' to yield chunks from the delegated generator
            async for chunk in self._langgraph_orch.process_query_stream(query, user_id, session_id, client_ip=client_ip):
                yield chunk
        else:
            import json
            yield f"data: {json.dumps({'type': 'status', 'content': 'Processing query (Legacy mode)...'})}\n\n"
            result = await self.process_query(query, user_id, session_id)
            yield f"data: {json.dumps({'type': 'final', 'content': result})}\n\n"

    async def process_query(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a user query using MCP tools

        Args:
            query: User's research question
            user_id: User identifier
            session_id: Optional session ID for context
            client_ip: Client IP for guest token tracking

        Returns:
            Response with data from MCP tools
        """
        # Delegate to LangGraph when available
        if self._langgraph_orch:
            return await self._langgraph_orch.process_query(query, user_id, session_id, client_ip=client_ip)

        # ── Legacy single-shot planner (fallback) ───────────────────────────
        try:
            logger.info(f"Processing query via MCP (legacy planner): {query}")

            # Get or create session
            session = await self._get_or_create_session(session_id, user_id, client_ip=client_ip)
            usage_tracker = self._new_llm_usage_tracker()
            from services.langgraph_orchestrator import _expand_contextual_shortcuts
            effective_query = _expand_contextual_shortcuts(query, session)
            if effective_query != query:
                logger.info("Expanded contextual shortcut for legacy processing.")
            
            # Simple intent classification
            intent = await self._classify_intent(effective_query, session, usage_tracker=usage_tracker)
            logger.info(f"Query intent: {intent}")
            
            # Use LLM to determine which tools to call
            tools_to_call = await self._determine_tools(effective_query, intent, session, usage_tracker=usage_tracker)

            from services.langgraph_orchestrator import (
                _extract_query_identifiers,
                _query_uses_active_gene_reference,
                _validate_tool_identifier_integrity,
            )
            requested_identifiers = _extract_query_identifiers(effective_query)
            allow_active_gene_reference = _query_uses_active_gene_reference(effective_query)
            
            # Execute tools
            results = {}
            active_gene = session.get("context", {}).get("active_gene")
            
            # Track tool call counts to generate unique keys for duplicate tools
            tool_call_counts = {}
            
            for tool_call in tools_to_call:
                tool_id = tool_call["tool"]
                args = tool_call["arguments"]
                
                # Generate unique key for this tool call
                if tool_id in tool_call_counts:
                    tool_call_counts[tool_id] += 1
                    unique_key = f"{tool_id}#{tool_call_counts[tool_id]}"
                else:
                    tool_call_counts[tool_id] = 0
                    unique_key = f"{tool_id}#0"

                validation_error = _validate_tool_identifier_integrity(
                    tool_name=tool_id,
                    args=args,
                    requested_identifiers=requested_identifiers,
                    active_gene=active_gene,
                    allow_active_gene_reference=allow_active_gene_reference,
                    tool_results=results,
                )
                
                # Update active gene tracking from tool arguments
                # Most genomic tools use 'protein' or 'gene_symbol'; batch tools use 'proteins'
                gene_arg = args.get("protein") or args.get("gene_symbol") or args.get("gene")
                proteins_arg = args.get("proteins")
                if gene_arg and isinstance(gene_arg, str) and gene_arg.lower() not in ["it", "its", "it's"]:
                    active_gene = gene_arg.upper()
                elif proteins_arg and isinstance(proteins_arg, list) and proteins_arg:
                    active_gene = proteins_arg[0].upper()
                    gene_arg = None  # keep None so renderers detect batch via data structure
                
                if validation_error:
                    logger.warning(f"Blocked invalid tool call {tool_id}: {validation_error}")
                    results[unique_key] = {
                        "_gene": gene_arg,
                        "_args": args,
                        "_result": {"error": validation_error},
                    }
                    continue

                try:
                    result = await self.mcp_aggregator.call_tool(tool_id, args)
                    # Wrap result with metadata for formatting
                    results[unique_key] = {
                        "_gene": gene_arg,  # Store gene name for display
                        "_args": args,
                        "_result": result
                    }
                    logger.info(f"Tool {tool_id} executed successfully (stored as {unique_key})")
                except Exception as e:
                    logger.error(f"Error calling tool {tool_id}: {e}")
                    results[unique_key] = {
                        "_gene": gene_arg,
                        "_args": args,
                        "_result": {"error": str(e)}
                    }
            
            # Update session context with last used gene
            if not active_gene:
                # If no tools were called or no gene found in args, try to extract from query
                gene_symbols = self._extract_gene_symbols(effective_query)
                active_gene = gene_symbols[0] if gene_symbols else None
                
            if "context" not in session:
                session["context"] = {}
            if active_gene:
                session["context"]["active_gene"] = active_gene
            
            # Generate final response using LLM (pass intent to avoid gene extraction for conversational queries)
            final_response = await self._generate_response(effective_query, results, session, intent, usage_tracker=usage_tracker)
            
            # Format response to match expected API structure (before saving)
            formatted_response = {
                "success": final_response.get("success", True),
                "summary": final_response.get("summary", ""),
                "message": final_response.get("message", ""),  # Keep for backward compatibility
                "query": query,
                "tools_used": final_response.get("tools_used", []),
                "raw_results": final_response.get("raw_results", {}),
                "visualizations": [],
                "analyses": [],
                "suggestions": [],
                "datasets": [],
                "papers": [],
                "_input_tokens": usage_tracker.get("input_tokens", 0),
                "_output_tokens": usage_tracker.get("output_tokens", 0),
                "_model": usage_tracker.get("model") or self._default_llm_model_name(),
            }
            
            # Update session
            turn_id = await self._update_session(session, query, formatted_response)
            
            # Return with session_id
            return {
                **formatted_response,
                "session_id": session["id"],
                "turn_id": turn_id,
            }
            
        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Error processing query: {str(e)}",
                "query": query
            }
    
    async def _get_or_create_session(
        self,
        session_id: Optional[str],
        user_id: str,
        client_ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get or create a session. Guest sessions (user_id='guest') are in-memory only."""
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]

        # Guest sessions: skip DB entirely, create in-memory session only
        if user_id == "guest":
            sid = session_id or f"guest-{time.time()}"
            session = {
                "id": sid,
                "user_id": "guest",
                "client_ip": client_ip,
                "title": "Guest Session",
                "context": {},
                "history": [],
                "created_at": time.time(),
                "last_updated": time.time(),
            }
            self.sessions[sid] = session
            return session

        # Load from database or create new
        if settings.DATABASE_URL.startswith("sqlite"):
            db = SessionLocal()
            try:
                if session_id:
                    db_session = db.query(ChatSession).filter(
                        ChatSession.id == session_id,
                        ChatSession.user_id == user_id
                    ).first()
                    if db_session:
                        # Load history as well
                        messages = db.query(DBChatMessage).filter(
                            DBChatMessage.session_id == session_id
                        ).order_by(DBChatMessage.timestamp.asc()).all()
                        
                        history = [
                            {"id": m.id, "query": m.query, "response": m.response, "timestamp": m.timestamp}
                            for m in messages
                        ]
                        
                        session = {
                            "id": db_session.id,
                            "user_id": db_session.user_id,
                            "title": db_session.title,
                            "context": db_session.context or {},
                            "history": history,
                            "created_at": db_session.created_at,
                            "last_updated": db_session.last_updated
                        }
                        ensure_session_workspace(session["id"])
                        self.sessions[session_id] = session
                        return session
                
                # Create new session
                new_session = ChatSession(
                    id=session_id or str(time.time()),
                    user_id=user_id,
                    title="New Chat",
                    created_at=time.time(),
                    last_updated=time.time(),
                    context={}
                )
                db.add(new_session)
                db.commit()
                
                session = {
                    "id": new_session.id,
                    "user_id": new_session.user_id,
                    "title": new_session.title,
                    "context": new_session.context or {},
                    "history": [],
                    "created_at": new_session.created_at,
                    "last_updated": new_session.last_updated
                }
                ensure_session_workspace(session["id"])
                self.sessions[session["id"]] = session
                return session
            finally:
                db.close()
        else:
            # PostgreSQL async
            async with SessionLocal() as db:
                if session_id:
                    result = await db.execute(
                        select(ChatSession).filter(
                            ChatSession.id == session_id,
                            ChatSession.user_id == user_id
                        )
                    )
                    db_session = result.scalar_one_or_none()
                    if db_session:
                        # Load history (async)
                        messages_result = await db.execute(
                            select(DBChatMessage).filter(
                                DBChatMessage.session_id == session_id
                            ).order_by(DBChatMessage.timestamp.asc())
                        )
                        messages = messages_result.scalars().all()
                        
                        history = [
                            {"id": m.id, "query": m.query, "response": m.response, "timestamp": m.timestamp}
                            for m in messages
                        ]
                        
                        session = {
                            "id": db_session.id,
                            "user_id": db_session.user_id,
                            "title": db_session.title,
                            "context": db_session.context or {},
                            "history": history,
                            "created_at": db_session.created_at,
                            "last_updated": db_session.last_updated
                        }
                        ensure_session_workspace(session["id"])
                        self.sessions[session_id] = session
                        return session
                
                # Create new session
                new_session = ChatSession(
                    id=session_id or str(time.time()),
                    user_id=user_id,
                    title="New Chat",
                    created_at=time.time(),
                    last_updated=time.time(),
                    context={}
                )
                db.add(new_session)
                await db.commit()
                
                session = {
                    "id": new_session.id,
                    "user_id": new_session.user_id,
                    "title": new_session.title,
                    "context": new_session.context or {},
                    "history": [],
                    "created_at": new_session.created_at,
                    "last_updated": new_session.last_updated
                }
                ensure_session_workspace(session["id"])
                self.sessions[session["id"]] = session
                return session
    
    async def _classify_intent(
        self,
        query: str,
        session: Dict[str, Any],
        usage_tracker: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Classify query intent using LLM for robust, context-aware categorization"""
        
        # Fast path: very short queries are likely conversational
        if len(query.strip()) <= 3:
            return "conversational"
        
        # Use LLM for intent classification if available
        if self.llm and not settings.MOCK_LLM:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                
                # Get recent conversation context
                history_str = self._format_recent_history(session, limit=5)
                
                system_prompt = """You are an intent classifier for a bioinformatics research assistant.

Your task: Classify the user's query into ONE of these categories:

1. **conversational**: Greetings, thanks, general chat, questions about the assistant itself
   Examples: "hello", "thanks", "who are you", "what can you do", "ok", "why?"

2. **linkedomics_query**: Requests for omics data from LinkedOmics/CPTAC/TCGA databases
   Examples: survival analysis, expression data, correlations, clinical trials, FunMap neighborhoods
   Keywords: survival, expression, correlation, methylation, clinical trial, funmap, cis, trans

3. **gene_query**: Questions about specific genes/proteins (general information)
   Examples: "What is TP53?", "Tell me about BRCA1", "What does MYC do?"
   
4. **data_query**: Questions about datasets, data availability, or data sources
   Examples: "What datasets do you have?", "Show me TCGA data", "What's in CPTAC?"

5. **general**: Everything else (fallback category)

CRITICAL RULES:
- Output ONLY valid JSON: {"intent": "category_name", "reasoning": "brief explanation"}
- NO markdown, NO code blocks, NO extra text
- Consider conversation context when classifying
- If a query mentions a gene AND asks for omics data → linkedomics_query (not gene_query)
- If uncertain, prefer the most specific category that matches"""

                human_prompt = f"""Conversation History:
{history_str if history_str else "(No previous context)"}

Current User Query: "{query}"

Classify this query. Return JSON only."""

                response = await self._invoke_llm_tracked(
                    [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)],
                    usage_tracker=usage_tracker,
                )
                
                # Parse LLM response
                parsed = self._extract_json_obj(response)
                if parsed and isinstance(parsed, dict) and "intent" in parsed:
                    intent = parsed["intent"]
                    reasoning = parsed.get("reasoning", "")
                    
                    # Validate intent is one of our known categories
                    valid_intents = {"conversational", "linkedomics_query", "gene_query", "data_query", "general"}
                    if intent in valid_intents:
                        logger.info(f"LLM Intent Classification: {intent} | Reasoning: {reasoning}")
                        return intent
                    else:
                        logger.warning(f"LLM returned invalid intent '{intent}', falling back to keyword-based")
                
            except Exception as e:
                logger.warning(f"LLM intent classification failed: {e}, falling back to keyword-based")
        
        # Fallback: keyword-based classification (legacy behavior)
        return self._classify_intent_keywords(query)
    
    def _classify_intent_keywords(self, query: str) -> str:
        """Fallback keyword-based intent classification (legacy)"""
        query_lower = query.lower()
        
        # Check for short conversational responses or common words first
        if query_lower in ["not", "why", "why not", "ok", "okay", "thanks", "thank you", "yes", "no", "sure"]:
            return "conversational"

        if any(word in query_lower for word in ["hello", "hi", "how are you", "who are you", "what can you do", "help"]):
            return "conversational"
        
        if any(
            word in query_lower
            for word in [
                "survival",
                "clinical trial",
                "trial",
                "funmap",
                "neighborhood",
                "linkedomics",
                "expression",
                "overexpress",
                "underexpress",
                "tumor vs normal",
                "tumour vs normal",
                "cis",
                "correlation",
                "methylation",
                "scnv",
                "copy number",
            ]
        ):
            return "linkedomics_query"
        if any(word in query_lower for word in ["gene", "protein", "tp53", "brca", "rb1", "egfr", "myc"]):
            return "gene_query"
        elif any(word in query_lower for word in ["data", "dataset", "tcga", "cptac"]):
            return "data_query"
        else:
            return "general"
    
    def _extract_gene_symbols(self, query: str) -> List[str]:
        """Extract all likely gene/protein symbols from the query using strict validation."""
        import re
        
        query_upper = query.upper()
        # Regex for gene-like tokens (2-10 chars, allowing digits)
        gene_pattern = r"\b([A-Z]{2,10}(?:\d+)?)\b"
        matches = re.findall(gene_pattern, query_upper)
        
        unique_genes = []
        seen = set()
        
        # If we have a valid gene list, use it for strict validation
        if self.valid_genes:
            # Denylist for common English words that happen to be valid HUGO gene symbols.
            # We want to ignore these unless explicitly capitalized by the user or 
            # if we have deeper NLP. For basic regex, it's safer to exclude them.
            ambiguous_genes = {"IMPACT", "SET", "MET", "FAT1", "FAT2", "FAT3", "FAT4", "CLOCK"}
            
            for match in matches:
                # Direct lookup in the valid genes set, but ignore ambiguous words
                if match in self.valid_genes and match not in seen and match not in ambiguous_genes:
                    unique_genes.append(match)
                    seen.add(match)
            return unique_genes
            
        # Fallback if valid_genes.txt couldn't be loaded (Keep minimal heuristcs)
        logger.warning("valid_genes.txt not loaded, using basic heuristics")
        skip_words = {
            "TELL", "ME", "ABOUT", "THE", "WHAT", "IS", "GENE", "PROTEIN",
            "INFORMATION", "DATA", "SHOW", "GIVE", "FIND", "SEARCH", "QUERY",
            "SURVIVAL", "CLINICAL", "TRIAL", "TRIALS", "PLOT",
            "CANCER", "TUMOR", "DISEASE", "PATIENT", "STUDY", "ANALYSIS",
            "BIOLOGY", "BIOINFORMATICS", "SCIENCE", "GENOMICS", "GENETICS"
        }
        
        for match in matches:
            if match not in skip_words and len(match) >= 3 and match not in seen:
                 unique_genes.append(match)
                 seen.add(match)
                 
        return unique_genes

    def _extract_cancer_type(self, query: str) -> Optional[str]:
        """Extract a cancer type abbreviation used by LinkedOmicsKB."""
        import re
        # Supported types in linkedomics_server.py docs
        allowed = {"CCRCC", "HNSCC", "LSCC", "LUAD", "PDAC", "BRCA", "COAD", "GBM", "OV", "UCEC"}
        tokens = re.findall(r"\b([A-Z]{2,10})\b", query.upper())
        for t in tokens:
            if t in allowed:
                return t
        return None

    def _extract_omic(self, query: str) -> str:
        q = query.lower()
        if "protein" in q:
            return "protein"
        return "RNA"

    def _compact_results_for_llm(self, results: Dict[str, Any]) -> str:
        """Create a compact, mostly-text representation of tool results for LLM summarization.

        Drops inline images/base64 blobs and caps size to avoid slow UI / huge prompts.
        """
        import json

        def _is_probably_base64(s: str) -> bool:
            # Heuristic: long strings with no whitespace are often base64
            if len(s) < 2000:
                return False
            if any(ch.isspace() for ch in s):
                return False
            return True

        def _sanitize_value(v: Any) -> Any:
            if isinstance(v, dict):
                out: Dict[str, Any] = {}
                for k, vv in v.items():
                    # Avoid heavy fields
                    if k in {"raw_results", "visualizations"}:
                        continue
                    if isinstance(vv, str) and vv.startswith("data:image/"):
                        out[k] = "<omitted: inline image data url>"
                        continue
                    if isinstance(vv, str) and _is_probably_base64(vv):
                        out[k] = f"<omitted: large base64 ({len(vv)} chars)>"
                        continue
                    out[k] = _sanitize_value(vv)
                return out
            if isinstance(v, list):
                return [_sanitize_value(x) for x in v[:50]]
            if isinstance(v, str):
                if v.startswith("data:image/"):
                    return "<omitted: inline image data url>"
                if _is_probably_base64(v):
                    return f"<omitted: large base64 ({len(v)} chars)>"
                if len(v) > 20_000:
                    return v[:20_000] + "\n...[truncated]..."
                return v
            return v

        def _unwrap_tool_value(v: Any) -> tuple[str, Any]:
            wrapped_gene = v.get("_gene", "") if isinstance(v, dict) else ""
            payload = v.get("_result") if isinstance(v, dict) and "_result" in v else v
            return wrapped_gene, payload

        def _rewrap_payload(original: Any, compact_payload: Any) -> Any:
            if isinstance(original, dict) and isinstance(original.get("_result"), dict):
                wrapped = dict(original)
                wrapped["_result"] = compact_payload
                return wrapped
            return compact_payload

        def _parsed_payload(v: Any) -> tuple[str, Any]:
            wrapped_gene, payload = _unwrap_tool_value(v)
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    pass
            return wrapped_gene, payload

        def _compact_tcga_cis_mode4_payload(v: Any) -> Any:
            payload = v.get("_result") if isinstance(v, dict) and isinstance(v.get("_result"), dict) else v
            if not isinstance(payload, dict) or payload.get("mode") != 4:
                return v

            results_list = payload.get("results")
            if not isinstance(results_list, list):
                return v

            top_hits = _tcga_cis_mode4_top_hits(results_list, limit=10, fdr_threshold=0.5)
            if not top_hits:
                return payload

            compact_payload = {
                "dataset": payload.get("dataset"),
                "mode": payload.get("mode"),
                "query": payload.get("query"),
                "n_results": payload.get("n_results", len(results_list)),
                "ranking_basis": "Use `top_hits_by_abs_correlation_fdr_lt_0_5` as the authoritative strongest-hit ranking. It matches the Top Cis-Associated Genes bar chart.",
                "top_hits_by_abs_correlation_fdr_lt_0_5": [
                    {
                        "rank": rank,
                        "gene": entry["gene"],
                        "correlation": entry["cor"],
                        "fdr": entry["fdr"],
                        "pvalue": entry["pvalue"],
                        "n": entry["n"],
                    }
                    for rank, entry in enumerate(top_hits, 1)
                ],
            }

            if isinstance(v, dict) and isinstance(v.get("_result"), dict):
                wrapped = dict(v)
                wrapped["_result"] = compact_payload
                return wrapped
            return compact_payload

        def _compact_trial_tool_payload(v: Any) -> Any:
            wrapped_gene, payload = _parsed_payload(v)
            if not isinstance(payload, dict):
                return v

            status = payload.get("status", "unavailable")
            data = payload.get("data") or {}
            is_batch = (
                isinstance(data, dict)
                and bool(data)
                and all(isinstance(item, dict) and "status" in item for item in data.values())
            )

            if is_batch:
                compact_items: Dict[str, Any] = {}
                for label, item in data.items():
                    if not isinstance(item, dict):
                        continue
                    item_status = item.get("status", "unavailable")
                    if item_status != "available":
                        compact_items[label] = {"status": item_status}
                        continue
                    compact_items[label] = _compact_trial_dataset_for_summary(item.get("data") or {}, label)
                compact_payload = {
                    "status": status,
                    "batch": True,
                    "items": compact_items,
                }
                return _rewrap_payload(v, compact_payload)

            label = payload.get("gene_set") or wrapped_gene or payload.get("gene") or "query"
            compact_payload = {
                "status": status,
                **_compact_trial_dataset_for_summary(data if isinstance(data, dict) else {}, str(label)),
            }
            return _rewrap_payload(v, compact_payload)

        def _compact_meta_analysis_tool_payload(v: Any, *, item_key: str, label_key: str) -> Any:
            _, payload = _parsed_payload(v)
            if not isinstance(payload, dict):
                return v
            compact_payload = _compact_meta_analysis_payload_for_summary(
                payload,
                item_key=item_key,
                label_key=label_key,
            )
            return _rewrap_payload(v, compact_payload)

        def _compact_funmap_payload(v: Any) -> Any:
            wrapped_gene, payload = _parsed_payload(v)
            if not isinstance(payload, dict):
                return v
            compact_payload = {
                "gene": wrapped_gene or payload.get("gene") or "",
                "neighborhood_size": len(payload.get("neighborhood") or []),
                "display_basis": "Use `displayed_network_neighbors_first_50` as the set shown in the network plot. The raw neighborhood may be larger.",
                "displayed_network_neighbors_first_50": _funmap_displayed_neighbors(payload, wrapped_gene),
            }
            return _rewrap_payload(v, compact_payload)

        def _apply_tool_specific_compaction(bare_tool_id: str, value: Any) -> Any:
            if bare_tool_id.endswith("tcga_cis_association_analysis"):
                return _compact_tcga_cis_mode4_payload(value)
            if bare_tool_id.endswith("clinical_trial_information") or bare_tool_id.endswith("gene_set_trial_information"):
                return _compact_trial_tool_payload(value)
            if bare_tool_id.endswith("meta_analysis_predictive_genes"):
                return _compact_meta_analysis_tool_payload(value, item_key="top_genes", label_key="gene")
            if bare_tool_id.endswith("meta_analysis_predictive_gene_sets"):
                return _compact_meta_analysis_tool_payload(value, item_key="top_gene_sets", label_key="gene_set")
            if bare_tool_id.endswith("funmap_neighborhood"):
                return _compact_funmap_payload(value)
            return value

        compact: Dict[str, Any] = {}
        tcga_survival_groups: Dict[tuple[str, str], list[dict[str, Any]]] = {}
        tcga_survival_group_order: list[tuple[str, str]] = []

        for tool_id, raw in (results or {}).items():
            bare_tool_id = tool_id.split('#')[0] if '#' in tool_id else tool_id
            if bare_tool_id.endswith("tcga_survival_analysis"):
                wrapped_gene, payload = _parsed_payload(raw)
                if isinstance(payload, dict):
                    query = payload.get("query", {}) or {}
                    gene_key = (wrapped_gene or query.get("gene") or "").upper()
                    cohort_key = query.get("cohort", "") or ""
                    group_key = (gene_key, cohort_key)
                    if group_key not in tcga_survival_groups:
                        tcga_survival_groups[group_key] = []
                        tcga_survival_group_order.append(group_key)
                    tcga_survival_groups[group_key].append(payload)
                    continue
                compact[tool_id] = _sanitize_value(raw)
                continue

            # If aggregator returned structured JSON string, parse and strip image parts.
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and isinstance(parsed.get("parts"), list):
                        parsed["parts"] = [
                            p
                            for p in parsed["parts"]
                            if not (isinstance(p, dict) and p.get("type") == "image")
                        ]
                    parsed = _apply_tool_specific_compaction(bare_tool_id, parsed)
                    compact[tool_id] = _sanitize_value(parsed)
                    continue
                except Exception:
                    compact[tool_id] = _sanitize_value(raw)
                    continue
            raw = _apply_tool_specific_compaction(bare_tool_id, raw)
            compact[tool_id] = _sanitize_value(raw)

        for gene_key, cohort_key in tcga_survival_group_order:
            parsed_list = tcga_survival_groups.get((gene_key, cohort_key), [])
            compact_key = (
                f"linkedomics::tcga_survival_analysis"
                f"[group:{gene_key or 'ALL_GENES'}:{cohort_key or 'all_cohorts'}]"
            )
            compact[compact_key] = _sanitize_value(
                _compact_tcga_survival_group_for_summary(parsed_list, gene_key, cohort_key)
            )

        text = json.dumps(compact, indent=2)
        if len(text) > 80_000:
            text = text[:80_000] + "\n...[truncated]..."
        return text

    async def _llm_summarize_tool_results(
        self,
        query: str,
        results: Dict[str, Any],
        usage_tracker: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Ask the LLM to summarize tool outputs (short summary separate from full message)."""
        if not self.llm or settings.MOCK_LLM or not results:
            return ""

        try:
            from langchain_core.messages import SystemMessage, HumanMessage

            def _summary_requirements() -> dict[str, Any]:
                query_lower = (query or "").lower()
                genes = self._extract_gene_symbols(query or "")
                compare_like = (
                    len(genes) >= 2
                    and any(marker in query_lower for marker in ("compare", "versus", " vs ", "priorit", "rank"))
                )
                return {
                    "genes": genes[:4],
                    "compare_like": compare_like,
                    "min_bullets": 2 if compare_like else 1,
                    "min_chars": 450 if compare_like else 120,
                }

            requirements = _summary_requirements()

            def _meets_detail_floor(text: str) -> bool:
                normalized = _normalize_summary_text(text)
                if not normalized:
                    return False
                if len(normalized) < requirements["min_chars"]:
                    return False
                if _summary_bullet_count(normalized) < requirements["min_bullets"]:
                    return False
                if requirements["compare_like"]:
                    for gene in requirements["genes"]:
                        if not re.search(rf"\b{re.escape(gene)}\b", normalized, re.IGNORECASE):
                            return False
                return True

            evidence = self._compact_results_for_llm(results)
            base_prompt = f"""User question:
{query}

Tool results (sanitized JSON):
{evidence}

CRITICAL: Your response must DIRECTLY ANSWER the user's question using the tool results above.
The app will show detailed tables, plots, and structured tool outputs separately. Your job is to provide a concise executive takeaway that complements those details instead of repeating them.

If the user is asking to:
- **Prioritize/Compare genes**: Provide a clear recommendation on which gene(s) to prioritize and why, based on the data.
- **Understand a gene**: Explain what the data reveals about the gene's role, expression patterns, and clinical relevance.
- **Explore relationships**: Connect the findings across different omics types and explain the biological significance.

Structure your response as:

(1-2 sentences directly answering the user's question with a clear recommendation or conclusion)

- [2-4 bullet points highlighting only the most decision-relevant findings]

(1-2 sentences connecting the findings and explaining the biological/clinical implications)

(Optional: ONE brief closing sentence offering the single most useful next analysis step, only when the tool results contain clear positive findings that justify a specific follow-up)

Rules:
- Output ONLY the markdown text above — no section headers, no extra sections.
- DO NOT use JSON, code blocks (```), or any preamble/metadata.
- DO NOT add follow-up questions, suggested next queries, or "you might also want to ask" sections.
- You MAY add exactly one short final sentence offering the next analysis step, but ONLY when all of the following are true: (1) the tool results contain specific positive findings; (2) the offered next step is directly supported by those findings; (3) the result is not no-data, error-only, clarification-like, or general-knowledge-like; and (4) there is one clearly best next step rather than several equally plausible options.
- If you include that final sentence, phrase it in this style: "If you'd like, I can <specific supported analysis>." Make it specific, concrete, and immediately doable in LinkedOmicsChat.
- The offer must be for something LinkedOmicsChat can actually do now from the current findings. Do not offer vague help like "explore further" or "look deeper."
- Capability guardrails for the optional offer:
  - Expression follow-ups must stay within tumor-vs-normal CPTAC expression comparisons.
  - Survival follow-ups must stay within CPTAC or TCGA survival analyses that the tools already support.
  - Cis-correlation follow-ups must be phrased as molecular-pair correlation / dosage / methylation / RNA-protein questions for a specific gene and optional cancer type.
  - FunMap follow-ups must be phrased as a functional neighborhood / co-functional network query for a gene. Describe FunMap as a co-functional network. FunMap is pan-cancer; do NOT invent cohort-specific or cancer-specific co-expression/network analyses such as "in LUAD".
  - Do NOT offer unsupported workflows such as ranked co-expressed genes within a specific cohort unless the tool outputs explicitly support that exact capability.
- Never add a next-step offer when the findings are weak, absent, mixed without a clear direction, or already fully answer the user's request.
- Use ONLY the provided tool results.
- If the results include explicit guidance such as `ranking_basis`, `display_basis`, `top_hits_by_abs_correlation_fdr_lt_0_5`, `top_genes_by_fdr_lt_0_05`, `top_studies_by_abs_fdr`, or `reported_top_items`, treat those as authoritative instead of inferring order from raw list position.
- Be precise with biological terminology.
- DO NOT state your identity or use phrases like 'As a Senior Analyst'.
- MOST IMPORTANT: Directly answer what the user asked, don't just summarize data.
- When data is partially available (some cohorts/omics present, others missing), lead with what IS available and what it shows. Mention missing data only as a brief caveat at the end, not as the opening statement.
- Do NOT restate the full ranked list, table, or plot contents row-by-row.
- Do NOT copy tool phrases verbatim unless a specific wording is biologically important.
- Mention at most 3 specific genes, pathways, cohorts, or terms unless the user explicitly asked for an exhaustive list.
- Prefer synthesis, ranking, caveats, and notable exceptions over repeating exact values that will already be visible in the detailed output.
- FORMATTING (mandatory): Use **bold** for every gene name, cancer type/cohort, key statistic (p-value, FDR, correlation, hazard ratio), and notable finding. Example: "**TP53** shows a **Spearman ρ = 0.87** (FDR < **1e-285**) in **BRCA**." Never leave gene names or numerical statistics as plain text.
- Every paragraph and bullet MUST end cleanly with terminal punctuation. Never leave a sentence, bullet, parenthesis, or markdown marker unfinished.
"""

            async def _generate_summary(prompt_text: str) -> str:
                resp = await self._invoke_llm_tracked(
                    [
                        SystemMessage(
                            content=(
                                "You are a Senior Multi-Omics Bioinformatics Analyst.\n"
                                "FORMATTING: Always use **bold** for gene names, cancer types, cohort names, "
                                "and all key statistics (p-values, FDR, correlations, hazard ratios). "
                                "Use bullet lists for multiple findings. Never leave gene names or numbers as plain text.\n"
                                "Every sentence and bullet must be fully closed and grammatically complete.\n"
                                f"{self.BIO_GUIDELINES}"
                            )
                        ),
                        HumanMessage(content=prompt_text),
                    ],
                    usage_tracker=usage_tracker,
                )
                return _normalize_summary_text(resp)

            summary = await _generate_summary(base_prompt)
            if _summary_has_complete_ending(summary) and _meets_detail_floor(summary):
                return summary

            repaired = _trim_summary_to_complete_boundary(summary)
            logger.warning(
                "Summary output was incomplete or under-detailed; retrying with a stricter complete-summary prompt. original_len=%s repaired_len=%s",
                len(summary),
                len(repaired),
            )

            retry_prompt = f"""User question:
{query}

Tool results (sanitized JSON):
{evidence}

Write a COMPLETE executive summary that directly answers the user's question.

Strict format:
- 1 opening paragraph with the main conclusion.
- {requirements["min_bullets"]} to 3 bullet points.
- Optional 1 closing sentence.

Hard requirements:
- Every bullet must be exactly one complete sentence.
- Every line must end with a period.
- Keep the summary between {requirements["min_chars"]} and 1400 characters when possible.
- Do not leave any markdown, parenthesis, or statistic unfinished.
- Use **bold** for every gene name, cancer type/cohort, and key statistic.
- If the query compares multiple genes, mention each compared gene explicitly.
- Output markdown only. No headings, no JSON, no code fences.
"""
            retry_summary = await _generate_summary(retry_prompt)
            if _summary_has_complete_ending(retry_summary) and _meets_detail_floor(retry_summary):
                return retry_summary

            retry_repaired = _trim_summary_to_complete_boundary(retry_summary)
            if retry_repaired and _meets_detail_floor(retry_repaired):
                logger.warning(
                    "Returning repaired retry summary after incomplete output. retry_len=%s repaired_len=%s",
                    len(retry_summary),
                    len(retry_repaired),
                )
                return retry_repaired
            if repaired and _meets_detail_floor(repaired):
                logger.warning(
                    "Retry summary still incomplete; returning repaired first-pass summary."
                )
                return repaired
            logger.warning(
                "Summary generation failed completeness/detail checks twice; returning empty summary instead of a thin or truncated summary."
            )
            return ""
        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}")
            return ""

    async def _generate_suggestions(
        self,
        query: str,
        response_text: str,
        session: Dict[str, Any],
        n: int = 3,
        usage_tracker: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Generate n follow-up question suggestions using the LLM.

        Based on the current query, the assistant's response, and the recent
        chat history so the suggestions stay contextually relevant.
        """
        if not self.llm or settings.MOCK_LLM:
            return []

        try:
            from langchain_core.messages import SystemMessage, HumanMessage

            history_str = self._format_recent_history(session) if session else ""
            history_block = f"\nRecent conversation:\n{history_str}\n" if history_str else ""
            # Use the query itself as context when the response text is empty
            context_text = response_text.strip() or query

            prompt = f"""{history_block}
The user just asked:
{query}

The assistant responded (excerpt):
{context_text[:800]}

Generate exactly {n} short, specific follow-up questions the user might naturally ask next.
Each question should be on its own line, numbered 1. 2. 3. etc.
Do NOT include any preamble or explanation — output only the numbered questions.

IMPORTANT — LinkedOmicsChat can ONLY answer questions that use one of these capabilities:
- Tumor vs. normal differential expression (RNA + protein) for a gene across 10 CPTAC cancer cohorts (BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC)
- Overall survival association (CPTAC) for a gene across cancer cohorts
- TCGA survival analysis for a gene across cohorts or omics layers (RNAseq, RPPA, Methylation, SCNA, miRNASeq)
- TCGA multi-omics cis associations — correlations between any two omics types (RNAseq, RPPA, Methylation, SCNA, miRNASeq) for a specific gene, cohort, or genome-wide scan
- CPTAC cis correlations between any omics pair (RNA–protein, DNA–RNA, etc.) for a gene in a cancer type
- Protein/gene interaction neighborhood from the FunMap co-functional network (pan-cancer, no cancer-type filter)
- Drug target ranking and druggability assessment (oncology evidence tiers T1–T5, tumor dependency) for one or multiple genes
- Clinical trial treatment-response prediction: which drugs/studies a gene or gene set predicts response to; meta-analysis of top biomarkers across trials; top genes/pathways in a specific study
- Pathway enrichment analysis (WebGestalt GO overrepresentation) on a list of genes
- Literature/PubMed search for a gene, drug, or research topic

Every suggestion MUST be directly and fully answerable by one of the capabilities above.
Do NOT suggest questions about: protein structure, sequence alignment, GWAS, somatic mutation profiles, variant annotation, drug mechanism of action, pharmacokinetics, cancer cohorts outside CPTAC (for expression/CPTAC survival) or TCGA (for TCGA survival/cis), or any other topic not listed above.
"""
            resp = await self._invoke_llm_tracked(
                [
                    SystemMessage(content=(
                        "You are LinkedOmicsChat, a specialized cancer multi-omics assistant. "
                        "Generate concise follow-up questions that are FULLY answerable using only the listed capabilities. "
                        "If you are unsure whether a question is answerable, do not suggest it. "
                        "Never suggest questions about protein structure, mutations, variant annotation, GWAS, drug mechanisms, "
                        "or cancer cohorts outside the supported datasets."
                    )),
                    HumanMessage(content=prompt),
                ],
                usage_tracker=usage_tracker,
            )
            text = (resp or "").strip()
            # Parse numbered lines
            import re as _re
            suggestions: List[str] = []
            for line in text.splitlines():
                line = line.strip()
                line = _re.sub(r"^\d+[\.\)]\s*", "", line).strip()
                line = line.strip("`").strip()
                if line and len(line) > 10:
                    suggestions.append(line)
            return suggestions[:n]
        except Exception as e:
            logger.warning(f"Suggestion generation failed: {e}")
            return []

    def _tool_catalog_for_prompt(self, available_tools: Dict[str, Dict[str, Any]]) -> str:
        """Build a compact tool catalog string for LLM prompting."""

        def _first_paragraph(text: str) -> str:
            """Return only the opening summary sentence(s), capped at 200 chars."""
            text = text.strip()
            # Stop at the first blank line (paragraph break)
            para = text.split("\n\n")[0].replace("\n", " ").strip()
            return para[:200] + ("…" if len(para) > 200 else "")

        def _enum_from_param(v: dict) -> Optional[list]:
            """Extract enum values from a plain enum or an anyOf [{enum:[...]},{type:'null'}] schema."""
            if isinstance(v.get("enum"), list):
                return v["enum"]
            for sub in (v.get("anyOf") or []):
                if isinstance(sub, dict) and isinstance(sub.get("enum"), list):
                    return sub["enum"]
            return None

        lines: List[str] = []
        for tool_id, meta in sorted(available_tools.items(), key=lambda kv: kv[0]):
            desc = _first_paragraph(meta.get("description") or "")
            schema = meta.get("inputSchema") or {}
            props = schema.get("properties") or {}
            required = schema.get("required") or []

            if props:
                parts: List[str] = []
                for k, v in props.items():
                    enum_vals = _enum_from_param(v)
                    t = v.get("type") or (v.get("anyOf") or [{}])[0].get("type") or "any"
                    if enum_vals is not None and len(enum_vals) <= 8:
                        parts.append(f"{k}: enum{enum_vals}")
                    elif enum_vals is not None:
                        # Long enum (e.g. 35 cohorts): show type + count hint
                        parts.append(f"{k}: str ({len(enum_vals)} options)")
                    else:
                        parts.append(f"{k}: {t}")
                sig = ", ".join(parts)
            else:
                sig = ""

            req = f" required={required}" if required else ""
            lines.append(f"- {tool_id}({sig}){req} — {desc}".strip())

        return "\n".join(lines)

    def _extract_json_obj(self, text: Any) -> Optional[Any]:
        """Extract and parse first JSON object/array from a string."""
        if not text or not isinstance(text, str):
            return None
        import json

        s = text.strip()
        # Remove common markdown fences
        if s.startswith("```"):
            s = s.strip("`")
            # Sometimes includes a leading 'json'
            s = s.replace("json", "", 1).strip()

        # Fast path
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                pass

        # Heuristic: find first {...} or [...] span
        start = None
        open_ch = None
        for i, ch in enumerate(s):
            if ch in "{[":
                start = i
                open_ch = ch
                break
        if start is None:
            return None
        close_ch = "}" if open_ch == "{" else "]"
        end = s.rfind(close_ch)
        if end <= start:
            return None
        chunk = s[start : end + 1]
        try:
            return json.loads(chunk)
        except Exception:
            return None

    def _validate_tool_calls(
        self,
        parsed: Any,
        available_tools: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Validate LLM output schema and tool arguments."""
        if not isinstance(parsed, dict) or "calls" not in parsed:
            # logger.warning(f"LLM output is not a dict or missing 'calls' key: {parsed}")
            return []
            
        calls = []
        for call in parsed["calls"]:
            if not isinstance(call, dict):
                continue
                
            # Flexible field names
            tool_name = (
                call.get("tool") or 
                call.get("tool_name") or 
                call.get("tool_id")
            )
            args = (
                call.get("arguments") or 
                call.get("args") or 
                call.get("parameters") or 
                call.get("tool_input") or 
                {}
            )
            
            if not tool_name or tool_name not in available_tools:
                # logger.warning(f"LLM suggested unknown tool: {tool_name}")
                continue
                
            calls.append({"tool": tool_name, "arguments": args})
            
        return calls

    def _format_recent_history(self, session: Dict[str, Any], limit: int = 20) -> str:
        """Format recent conversation history for LLM context."""
        if not session or not session.get("history"):
            return ""
        
        history_text = []
        # Get last N messages
        recent = session["history"][-limit:]
        logger.info(f"Formatting history from {len(session['history'])} total messages. Using last {len(recent)}.")
        
        for item in recent:
            query = item.get("query", "")
            # Try to get summary first, then message, then empty
            resp = item.get("response", {})
            content = ""
            if isinstance(resp, dict):
                content = resp.get("summary") or resp.get("message") or ""
            elif isinstance(resp, str):
                content = resp
            
            # Truncate very long responses to save context window
            if len(content) > 800:
                content = content[:800] + "... (truncated)"
            
            if query:
                history_text.append(f"User: {query}")
            if content:
                history_text.append(f"Assistant: {content}")
                
        return "\n".join(history_text)

    def _resolve_pronouns_in_place(self, *args, **kwargs):
        """DEPRECATED: Pronoun resolution is now handled natively by the LLM with context injection."""
        pass

    async def _llm_plan_tools(
        self,
        query: str,
        available_tools: Dict[str, Dict[str, Any]],
        history_str: str,
        session: Optional[Dict[str, Any]] = None,
        usage_tracker: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Use LLM to produce a tool-call plan with arguments, validated by schema."""
        if not self.llm or not available_tools:
            return []

        from langchain_core.messages import SystemMessage, HumanMessage

        catalog = self._tool_catalog_for_prompt(available_tools)
        system = SystemMessage(
            content=(
                "You are a Senior Multi-Omics Bioinformatics Analyst. Your goal is to determine if tool calls are needed to answer a user's question.\n"
                f"{self.BIO_GUIDELINES}\n"
                "Rules:\n"
                "- Only use tools from the provided catalog.\n"
                "- Never silently replace one gene / protein / identifier with a different symbol. Use the exact user-provided token unless a dedicated resolver tool returns a validated replacement for that exact token.\n"
                "- Output must be valid JSON. No markdown, no explanations.\n"
                "- Output shape: {\"reasoning\": \"...\", \"calls\": [{\"tool\": \"tool_name\", \"arguments\": {\"arg\": \"val\"}}]}.\n"
                "- IMPORTANT: If the user is just saying hello, asking who you are, or asking a general question that doesn't require genomic data, output an EMPTY calls list: {\"reasoning\": \"...\", \"calls\": []}.\n"
                "- Do NOT force a tool call if the question is conversational.\n"
                f"- CONTEXT: The currently active gene of interest is '{session.get('context', {}).get('active_gene') or 'unknown'}'. Resolve 'it' or 'this' to this gene unless the user specifies otherwise.\n"
                "- If research data IS needed, use at most 3 calls.\n"
                "- PROMPT INSTRUCTION: Explain your reasoning first, including pronoun resolution from History.\n"
            )
        )

        human = HumanMessage(
            content=(
                f"Conversation History:\n{history_str}\n\n"
                f"Current User query:\n{query}\n\n"
                f"Tool catalog:\n{catalog}\n\n"
                "Return the JSON tool call plan now."
            )
        )
        
        logger.info(f"Planning tools. History len: {len(history_str)}. Query: {query}")
        if len(history_str) > 0:
            logger.info(f"History context preview: {history_str[:200]}...")

        # Attempt 1
        raw = await self._invoke_llm_tracked([system, human], usage_tracker=usage_tracker)
        # Log raw string content
        logger.info(f"Raw LLM Tool Plan: {raw}")
        parsed = self._extract_json_obj(raw)
        
        # CoT: Log the functioning to verify reasoning
        if isinstance(parsed, dict) and "reasoning" in parsed:
            logger.info(f"LLM Reasoning: {parsed['reasoning']}")

        calls = self._validate_tool_calls(parsed, available_tools)
        if calls:
            return calls

        # Attempt 2: provide a correction prompt with common failure modes
        human2 = HumanMessage(
            content=(
                f"Your previous output was invalid or missing required arguments.\n"
                f"Conversation History:\n{history_str}\n\n"
                f"User query:\n{query}\n\n"
                f"Tool catalog:\n{catalog}\n\n"
                "Return ONLY valid JSON in the required shape with correct tool ids and required arguments."
            )
        )
        raw2 = await self._invoke_llm_tracked([system, human2], usage_tracker=usage_tracker)
        logger.info(f"Raw LLM Tool Plan (Attempt 2): {raw2}")
        parsed2 = self._extract_json_obj(raw2)
        return self._validate_tool_calls(parsed2, available_tools)

    async def _determine_tools(
        self,
        query: str,
        intent: str,
        session: Dict[str, Any] = None,
        usage_tracker: Optional[Dict[str, Any]] = None,
    ) -> list:
        """Determine which MCP tools to call based on query.

        Tool selection is fully delegated to the LLM via _llm_plan_tools, which
        receives the live tool catalog from mcp_aggregator.list_tools(). This means
        any new tool added to the MCP server is automatically available — no changes
        needed here.
        """
        available_tools = self.mcp_aggregator.list_tools()

        if self.llm and available_tools:
            try:
                history_str = self._format_recent_history(session) if session else ""
                if session:
                    logger.info(f"Formatted history length: {len(history_str)}")
                else:
                    logger.warning("No session provided to _determine_tools")

                planned = await self._llm_plan_tools(query, available_tools, history_str, session, usage_tracker=usage_tracker)
                logger.info(f"LLM planned tools: {planned}")
                return planned  # trust LLM; empty list means no tools needed
            except Exception as e:
                logger.error(f"LLM tool planning failed: {e}", exc_info=True)
                return []

        # No LLM available — cannot determine tools
        logger.warning("No LLM available for tool planning; returning empty tool list.")
        return []
    
    async def _generate_response(
        self,
        query: str,
        results: Dict[str, Any],
        session: Dict[str, Any],
        intent: str = "general",
        usage_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate final response from tool results"""
        if not results:
            # Use LLM to generate a natural response for conversational queries
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                history_str = self._format_recent_history(session)
                
                # Only extract gene symbols if the intent was actually a gene query
                # This prevents false positives like "ME" in "tell me a joke"
                gene_symbols = []
                if intent == "gene_query":
                    gene_symbols = self._extract_gene_symbols(query)
                
                if gene_symbols:
                    if len(gene_symbols) == 1:
                        gene_symbol = gene_symbols[0]
                        prompt = f"""Conversation History:
{history_str}

The user asks: "{query}"

This appears to be a question about the gene {gene_symbol}. Please provide a comprehensive answer about this gene using your general knowledge of molecular biology and genomics. Include:
- What the gene is and what it does
- Its biological function
- Its relevance in disease (if applicable)
- Any other important information

Be specific, accurate, and informative."""
                    else:
                        # Multi-gene comparison
                        genes_str = ", ".join(gene_symbols)
                        prompt = f"""Conversation History:
{history_str}

The user asks: "{query}"

This appears to be a request involving multiple genes: {genes_str}.
Please provide a comprehensive response that addresses these genes.
- If the user is asking to prioritize or compare them, analyze their relative importance, functions, or disease relevance.
- If the user is asking for information on all of them, provide a summary for each and any known connections between them.

Use your expert knowledge of molecular biology and genomics."""
                else:
                    prompt = f"""Conversation History:
{history_str}

The user says: "{query}"

Please provide a helpful, natural, and professional response. If they are just greeting you, greet them back as a Senior Multi-Omics Bioinformatics Analyst. If they are asking for help or about your capabilities, explain them clearly."""
                
                response = await self._invoke_llm_tracked(
                    [
                        SystemMessage(
                            content=(
                                "You are a Senior Multi-Omics Bioinformatics Analyst. You are helpful, professional, and precise. "
                                "CRITICAL RULE: Do not explicitly state your title (e.g., Avoid 'As a Senior Analyst...'). Just provide the response.\n"
                                "FORMATTING: Use rich markdown in every response. Use **bold** for gene names, key terms, and statistics. "
                                "Use bullet lists (`-`) when enumerating features, functions, or data points. "
                                "Use `###` headers to separate distinct sections when covering multiple topics. "
                                "Never write walls of plain prose when bullets or headers would be clearer."
                            )
                        ),
                        HumanMessage(content=prompt)
                    ],
                    usage_tracker=usage_tracker,
                )
                
                return {
                    "success": True,
                    "summary": "", # No summary needed for basic chat
                    "message": response,
                    "query": query,
                    "tools_used": [],
                    "raw_results": {}
                }
            except Exception as e:
                logger.error(f"Error generating conversational response: {e}", exc_info=True)
                return {
                    "success": True,
                    "message": f"I'm here to help, but I encountered an error: {str(e)}. How can I assist you today?",
                    "query": query
                }
        
        # Literature tools: the LangGraph agent already produced a formatted summary
        # in llm_summary; just return that rather than re-formatting raw JSON.
        if any(tool_id.startswith("literature::") for tool_id in results.keys()):
            # Pull the LLM's own summary out of the results wrapper if present,
            # otherwise fall back gracefully.
            return {
                "success": True,
                "summary": "",
                "message": None,   # sentinel → caller uses llm_summary instead
                "query": query,
                "tools_used": list(results.keys()),
                "raw_results": results,
            }

        # If LinkedOmics tools were used, format them nicely as markdown
        if any(tool_id.startswith("linkedomics::") for tool_id in results.keys()):
            try:
                fmt = self._format_linkedomics_results(results, query, session_id=session.get("id", ""))
                message = fmt["message"]
                visualizations = fmt.get("visualizations", [])
                rendered_ids = fmt.get("rendered_tool_ids", set())
                # Only surface badges for tools that actually produced visible output
                if rendered_ids:
                    tools_used = [k for k in results.keys() if (k.split('#')[0] if '#' in k else k) in rendered_ids]
                else:
                    tools_used = list(results.keys())
                summary = await self._llm_summarize_tool_results(query, results, usage_tracker=usage_tracker)
                return {
                    "success": True,
                    "summary": summary or "",
                    "message": message,
                    "query": query,
                    "tools_used": tools_used,
                    "raw_results": results,
                    "visualizations": visualizations,
                }
            except Exception as e:
                logger.error(f"Error formatting LinkedOmics results: {e}", exc_info=True)

        # Resolver-only turns should not expose the internal result wrappers in chat.
        if results and all(tool_id.startswith("gene_utils::resolve_gene_identifier") for tool_id in results.keys()):
            summary = await self._llm_summarize_tool_results(query, results, usage_tracker=usage_tracker)
            formatted_results = []
            for wrapped_result in results.values():
                payload = wrapped_result.get("_result", wrapped_result) if isinstance(wrapped_result, dict) else wrapped_result
                args = wrapped_result.get("_args", {}) if isinstance(wrapped_result, dict) else {}

                if not isinstance(payload, dict):
                    continue

                identifier = str(payload.get("input") or args.get("identifier") or "the identifier").strip()
                symbol = str(payload.get("hgnc_symbol") or "").strip()
                error = str(payload.get("error") or "").strip()

                if error:
                    formatted_results.append(
                        f"I couldn't resolve **{identifier}** to an official **HGNC symbol**. {error}"
                    )
                elif symbol:
                    if symbol.upper() == identifier.upper():
                        formatted_results.append(f"**{symbol}** is a valid **HGNC symbol**.")
                    else:
                        formatted_results.append(
                            f"**{identifier}** resolves to the official **HGNC symbol {symbol}**."
                        )

            message = summary.strip() or "\n\n".join(formatted_results) or "I validated the gene identifier."
            return {
                "success": True,
                "summary": "",
                "message": message,
                "query": query,
                "tools_used": list(results.keys()),
                "raw_results": results,
            }

        # Format results for display - extract actual gene data
        gene_info = None
        for tool_id, result in results.items():
            if isinstance(result, str):
                # Try to parse JSON if it's a string
                try:
                    import json
                    parsed = json.loads(result)
                    if isinstance(parsed, dict) and "gene" in parsed:
                        gene_info = parsed
                        break
                except:
                    pass
        
        # Use LLM to generate natural language response with actual data
        if self.llm and gene_info:
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                
                # Build a clear prompt with the actual gene data
                gene_details = f"""
Gene: {gene_info.get('gene', 'Unknown')}
Description: {gene_info.get('description', 'N/A')}
Chromosome: {gene_info.get('chromosome', 'N/A')}
Function: {gene_info.get('function', 'N/A')}
"""
                
                # Format history for context
                history_str = self._format_recent_history(session)

                prompt = f"""Conversation History:
{history_str}

The user asked: "{query}"

Here is the information I found:
{gene_details}

Please provide a clear, informative response about this gene. Include the key details: what the gene is, what chromosome it's on, and its main function. Write in a natural, conversational way. Refer to previous context if relevant."""
                
                response = await self._invoke_llm_tracked(
                    [
                        SystemMessage(
                            content=(
                                "You are a Senior Multi-Omics Bioinformatics Analyst. When providing information about genes, "
                                "always include specific details from the data. Be clear, analytical, and professional.\n"
                                "CRITICAL RULE: Do not explicitly state your title or identity (e.g., Avoid 'As a Senior Analyst...'). Just provide the analysis.\n"
                                "FORMATTING: Use rich markdown. Use **bold** for gene names, key terms, and statistics. "
                                "Use bullet lists for enumerating features or findings. Use `###` headers for distinct sections.\n"
                                f"{self.BIO_GUIDELINES}"
                            )
                        ),
                        HumanMessage(content=prompt)
                    ],
                    usage_tracker=usage_tracker,
                )
                
                # Ensure the response actually contains the information
                if response and len(response.strip()) > 20:
                    summary = await self._llm_summarize_tool_results(query, results, usage_tracker=usage_tracker)
                    return {
                        "success": True,
                        "summary": summary or "",
                        "message": response,
                        "query": query,
                        "tools_used": list(results.keys()),
                        "raw_results": results
                    }
                else:
                    # If response is too short or empty, it might be an error or a 429 fallback
                    if not any(tool_id.startswith("linkedomics::") for tool_id in results.keys()):
                         return {
                            "success": True,
                            "summary": "",
                            "message": response or "I'm here to help with your multi-omics research. What would you like to explore?",
                            "query": query,
                            "tools_used": [],
                            "raw_results": {}
                        }
            except Exception as e:
                logger.error(f"Error generating LLM response: {e}")
        
        # Fallback: format the gene info directly if LLM failed or no LLM
        if gene_info:
            message = f"""**{gene_info.get('gene', 'Gene')} Information:**

**Description:** {gene_info.get('description', 'N/A')}
**Chromosome:** {gene_info.get('chromosome', 'N/A')}
**Function:** {gene_info.get('function', 'N/A')}"""
        else:
            # Format raw results
            formatted_results = []
            for tool_id, result in results.items():
                display_result = result.get("_result", result) if isinstance(result, dict) else result
                if isinstance(result, str):
                    try:
                        import json
                        parsed = json.loads(result)
                        formatted_results.append(f"**{tool_id}**:\n{json.dumps(parsed, indent=2)}")
                    except:
                        formatted_results.append(f"**{tool_id}**:\n{result}")
                else:
                    formatted_results.append(f"**{tool_id}**:\n{display_result}")
            message = f"I found the following information:\n\n" + "\n\n".join(formatted_results)
        summary = await self._llm_summarize_tool_results(query, results, usage_tracker=usage_tracker)
        return {
            "success": True,
            "summary": summary or "",
            "message": message,
            "query": query,
            "tools_used": list(results.keys()),
            "raw_results": results
        }

    def _format_linkedomics_results(self, results: Dict[str, Any], query: str = "", session_id: str = "") -> Dict[str, Any]:
        """Format LinkedOmics MCP tool outputs into nice markdown for chat UI.

        Returns a dict with keys:
            "message":       str  — markdown text
            "visualizations": list — list of Plotly figure dicts
        """
        import json

        def _maybe_json(v: Any) -> Any:
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except Exception:
                    return v
            return v

        def _as_data_url(img_part: Dict[str, Any]) -> Optional[str]:
            data = img_part.get("data")
            mime = img_part.get("mimeType") or "image/png"
            if not data:
                return None
            # `data` from MCP ImageContent is already base64 in practice
            return f"data:{mime};base64,{data}"

        sections: List[str] = []
        _visualizations: list = []
        _rendered_tool_ids: set = set()  # tracks tools that produced visible output

        import uuid as _uuid

        # Pre-collect tcga_survival_analysis results grouped by (gene, cohort).
        # Rendered inline in the main loop to preserve section ordering.
        _tcga_groups: Dict[tuple, List[Any]] = {}
        _OMICS_LABEL_PRE = {
            "RNAseq": "RNA expression", "RPPA": "protein (RPPA)",
            "Methylation": "methylation", "SCNA": "copy number",
            "miRNASeq": "miRNA expression",
        }
        for unique_key, wrapped_result in results.items():
            tid = unique_key.split('#')[0] if '#' in unique_key else unique_key
            if not tid.endswith("tcga_survival_analysis"):
                continue
            raw = wrapped_result["_result"] if isinstance(wrapped_result, dict) and "_result" in wrapped_result else wrapped_result
            parsed = _maybe_json(raw)
            if not isinstance(parsed, dict) or parsed.get("status") == "error" or "results" not in parsed:
                continue
            gene_key = wrapped_result.get("_gene", "") if isinstance(wrapped_result, dict) else ""
            cohort_key = parsed.get("query", {}).get("cohort", "")
            _tcga_groups.setdefault((gene_key, cohort_key), []).append(parsed)

        _tcga_rendered: set = set()

        def _normalize_tool_id(tool_id: str) -> str:
            return tool_id.split("::", 1)[1] if "::" in tool_id else tool_id

        def _placeholder_title_for_tool(tool_id: str) -> Optional[str]:
            normalized = _normalize_tool_id(tool_id)
            if normalized in {"cancer_gene_expression", "batch_cancer_gene_expression"}:
                return "Cancer expression (Tumor vs Normal)"
            if normalized in {"overall_survival_per_cancer", "batch_overall_survival_per_cancer"}:
                return "Overall survival associations"
            if normalized == "tcga_survival_analysis":
                return "TCGA survival analysis"
            if normalized == "get_survival_plot":
                return "Survival plot"
            if normalized in {"get_target", "batch_get_target"}:
                return "Drug target profile"
            if normalized == "clinical_trial_information":
                return "Clinical trial associations"
            if normalized in {"get_cis_correlations", "batch_get_cis_correlations"}:
                return "Cis-Correlations"
            if normalized == "tcga_cis_association_analysis":
                return "TCGA Cis Association"
            return None

        def _covered_genes_for_result(tool_id: str, wrapped_result: Any) -> set[str]:
            covered: set[str] = set()
            if not isinstance(wrapped_result, dict):
                return covered

            gene_name = wrapped_result.get("_gene")
            if isinstance(gene_name, str) and gene_name.strip():
                covered.add(gene_name.upper())

            raw_result = wrapped_result.get("_result", wrapped_result)
            parsed_result = _maybe_json(raw_result)
            if not isinstance(parsed_result, dict):
                return covered

            normalized = _normalize_tool_id(tool_id)
            batch_gene_map = None
            if normalized in {"batch_cancer_gene_expression", "batch_overall_survival_per_cancer"}:
                batch_gene_map = parsed_result.get("data")
            elif normalized == "batch_get_target":
                batch_gene_map = parsed_result.get("results")
            elif normalized == "batch_get_cis_correlations":
                batch_gene_map = parsed_result.get("data")

            if isinstance(batch_gene_map, dict):
                for batch_gene, batch_payload in batch_gene_map.items():
                    if not isinstance(batch_gene, str) or not batch_gene.strip():
                        continue
                    if normalized == "batch_get_target":
                        if not (isinstance(batch_payload, dict) and isinstance(batch_payload.get("result"), dict)):
                            continue
                    elif normalized == "batch_get_cis_correlations":
                        if not (isinstance(batch_payload, dict) and isinstance(batch_payload.get("data"), dict)):
                            continue
                    covered.add(batch_gene.upper())

            return covered

        def _filter_label(f: dict) -> str:
            cat = f.get("treatment_category", "")
            cancers_f = f.get("cancers", [])
            parts = []
            if cat:
                parts.append(f"treatment={cat}")
            elif f.get("drugs"):
                parts.append(f"drugs={f['drugs']}")
            if cancers_f:
                parts.append(f"cancers={cancers_f}")
            return ", ".join(parts) if parts else "all studies"

        def _dir_label(d: str) -> str:
            return "↑ Sensitive" if d == "sensitive" else "↓ Resistant"

        def _target_filter_label(payload: dict) -> str:
            if not isinstance(payload, dict):
                return "all targets"
            label = payload.get("filter_label")
            if isinstance(label, str) and label.strip():
                return label
            applied = payload.get("applied_filters")
            if isinstance(applied, dict) and applied:
                ordered = []
                for key in ("tier", "tiers", "family", "antigen", "drug_name"):
                    value = applied.get(key)
                    if value:
                        display_key = "drug" if key == "drug_name" else key
                        ordered.append(f"{display_key}={value}")
                if ordered:
                    return ", ".join(ordered)
            return "all targets"

        def _target_ranking_meta(payload: dict) -> tuple[str, str, str, str]:
            if not isinstance(payload, dict):
                return (
                    "balanced",
                    "Balanced evidence-first",
                    "Balanced ranking is evidence-first and does not favor established or exploratory tiers.",
                    "Balanced Score",
                )
            mode = str(payload.get("ranking_mode") or "balanced").strip().lower()
            if mode not in {"balanced", "established", "exploratory"}:
                mode = "balanced"
            label = str(payload.get("ranking_mode_label") or "").strip() or {
                "balanced": "Balanced evidence-first",
                "established": "Established / clinically advanced",
                "exploratory": "Exploratory / discovery-stage",
            }[mode]
            explanation = str(payload.get("ranking_explanation") or "").strip()
            if not explanation:
                explanation = {
                    "balanced": "Balanced ranking is evidence-first and does not favor established or exploratory tiers.",
                    "established": "Established ranking favors clinically advanced targets.",
                    "exploratory": "Exploratory ranking favors discovery-stage targets.",
                }[mode]
            score_label = str(payload.get("score_label") or "").strip() or {
                "balanced": "Balanced Score",
                "established": "Clinical Readiness Score",
                "exploratory": "Exploratory Score",
            }[mode]
            return mode, label, explanation, score_label

        def _target_ranking_title(mode: str) -> str:
            if mode == "established":
                return "Top therapeutic targets — ranked by clinical readiness"
            if mode == "exploratory":
                return "Top therapeutic targets — ranked by exploratory novelty"
            return "Top therapeutic targets — ranked by evidence"

        def _trial_scope_lines(label: str, *, signal_label: str, batch: bool = False) -> list[str]:
            lines = [
                f"**Scope:** Study-level treatment-response associations for {label} across LinkedOmics Trials datasets.",
                f"**Interpretation:** AUROC > 0.5 means higher {signal_label} is associated with resistance; AUROC < 0.5 means higher {signal_label} is associated with sensitivity.",
            ]
            if batch:
                lines.append("**Batch mode:** One subsection is shown for each queried gene.")
            return lines

        def _tcga_scope_lines(
            *,
            mode: int,
            gene: str,
            cohort: str,
            cohort_full: str,
            omics_label: str,
            n_results: int,
        ) -> list[str]:
            cohort_display = f"{cohort} ({cohort_full})" if cohort and cohort_full and cohort_full != cohort else (cohort or cohort_full)
            if mode == 4:
                scope = f"**Scope:** Genome-wide TCGA survival scan in {cohort_display} using {omics_label}; each point or row represents one gene."
            elif mode == 3:
                scope = f"**Scope:** Pan-cancer TCGA survival comparison for {gene} using {omics_label}; each bar or row represents one cohort."
            elif mode == 2:
                scope = f"**Scope:** Single-gene TCGA survival analysis for {gene} in {cohort_display} across all available omics layers."
            else:
                scope = f"**Scope:** Single-gene TCGA survival analysis for {gene} in {cohort_display} using {omics_label}."
            return [
                scope,
                f"**Interpretation:** Hazard ratio (HR) > 1 means higher signal is associated with worse survival; HR < 1 means it is associated with better survival. Results shown: {n_results}.",
            ]

        for unique_key, wrapped_result in results.items():
            # Strip the #N suffix to get the actual tool_id
            tool_id = unique_key.split('#')[0] if '#' in unique_key else unique_key

            # Extract gene name and actual result from wrapper
            gene_name = ""
            if isinstance(wrapped_result, dict) and "_result" in wrapped_result:
                gene_name = wrapped_result.get("_gene", "")
                raw = wrapped_result["_result"]
            else:
                # Fallback for non-wrapped results (backward compatibility)
                raw = wrapped_result

            parsed = _maybe_json(raw)
            _sections_before = len(sections)  # track whether this tool produces output

            # Structured payload from MCPAggregator (images etc.)
            if isinstance(parsed, dict) and "mcp" in parsed and "parts" in parsed:
                parts = parsed.get("parts") or []
                text = (parsed.get("text") or "").strip()
                if tool_id.endswith("get_survival_plot"):
                    # Prefer image rendering
                    img_url = None
                    for p in parts:
                        if isinstance(p, dict) and p.get("type") == "image":
                            img_url = _as_data_url(p)
                            break
                    survival_title = f"Survival plot - {gene_name}" if gene_name else "Survival plot"
                    if img_url:
                        sections.append(f"## {survival_title}\n\n![Survival plot]({img_url})\n")
                    elif text:
                        sections.append(f"## {survival_title}\n\n{text}\n")
                    else:
                        sections.append(f"## {survival_title}\n\n(Plot unavailable)\n")
                else:
                    # Generic structured output: show text + any unknown parts
                    md = [f"## {tool_id.split('::',1)[1].replace('_',' ').title()}"]
                    if text:
                        md.append(text)
                    unknowns = [p for p in parts if isinstance(p, dict) and p.get("type") == "unknown"]
                    if unknowns:
                        md.append("\n\n```text\n" + "\n".join(u.get("repr","") for u in unknowns) + "\n```\n")
                    sections.append("\n\n".join(md) + "\n")
                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue

            # Tool-specific formatting for dict outputs
            if tool_id.endswith("funmap_neighborhood"):
                neigh = []
                api_nodes = []
                api_edges = []
                if isinstance(parsed, dict):
                    neigh = parsed.get("neighborhood") or []
                    api_nodes = parsed.get("nodes") or []
                    api_edges = parsed.get("edges") or []

                funmap_title = f"FunMap neighborhood — {gene_name}" if gene_name else "FunMap neighborhood"
                md = [
                    f"## {funmap_title}",
                    f"**Nodes found:** {len(neigh)}",
                    "",
                ]

                if api_nodes:
                    # Build CSV edge list for download
                    import io as _io, csv as _csv_mod
                    shown = set(n["name"] for n in api_nodes[:51] if isinstance(n, dict) and n.get("name"))
                    csv_buf = _io.StringIO()
                    _csv_writer = _csv_mod.writer(csv_buf)
                    _csv_writer.writerow(["source", "target"])
                    for e in api_edges:
                        src, tgt = e.get("source", ""), e.get("target", "")
                        if src in shown and tgt in shown:
                            _csv_writer.writerow([src, tgt])

                    viz_id = _uuid.uuid4().hex
                    _visualizations.append({
                        "type": "network_plot",
                        "id": viz_id,
                        "title": funmap_title,
                        "nodes": api_nodes,
                        "edges": api_edges,
                        "csv": csv_buf.getvalue(),
                    })
                    md.append(f"[NETWORK:{viz_id}]")
                    md.append("")

                if neigh:
                    md.append("| # | Gene |")
                    md.append("|---|---|")
                    for i, g in enumerate(neigh, 1):
                        md.append(f"| {i} | {g} |")
                else:
                    md.append("\n_No neighborhood found._")

                md.append("\n> **Source:** [FunMap](#source:funmap)")
                sections.append("\n".join(md) + "\n")
                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("cancer_gene_expression") or tool_id.endswith("overall_survival_per_cancer"):
                # parsed: {"protein_level": {"status":..., "data": {...}}, "RNA_level": {...}}
                # OR batch: {"status": "available", "data": {"GENE1": {"protein_level":..., "RNA_level":...}, ...}}
                if not isinstance(parsed, dict):
                    sections.append(f"## {tool_id}\n\n```json\n{json.dumps(parsed, indent=2)}\n```\n")
                    _rendered_tool_ids.add(tool_id)
                    continue

                if tool_id.endswith("cancer_gene_expression"):
                    base_title = "Cancer expression (Tumor vs Normal)"
                    subtitle = " · CPTAC"
                    source_desc = "CPTAC cohorts"
                    col_rna = "RNA (Tumor vs Normal)"
                    col_prot = "Protein (Tumor vs Normal)"
                else:
                    base_title = "Overall survival associations"
                    subtitle = ""
                    source_desc = "LinkedOmics CPTAC cohorts · RNA expression and protein level vs. overall survival"
                    col_rna = "RNA expression"
                    col_prot = "Protein level"

                # Detect batch result: {"status": ..., "data": {"GENE": {...}, ...}}
                batch_data = parsed.get("data") if ("data" in parsed and isinstance(parsed.get("data"), dict) and not parsed.get("protein_level") and not parsed.get("RNA_level")) else None

                is_surv = tool_id.endswith("overall_survival_per_cancer")

                def _render_single_gene_section(g_name, g_parsed, b_title, sub, s_desc, c_rna, c_prot):
                    p = (g_parsed.get("protein_level") or {})
                    r = (g_parsed.get("RNA_level") or {})
                    pd_ = p.get("data") or {}
                    rd_ = r.get("data") or {}
                    cancers_ = sorted(set(list(pd_.keys()) + list(rd_.keys())))
                    t = f"{b_title} - {g_name}{sub}" if g_name else f"{b_title}{sub}"
                    ls = [f"## {t}", ""]
                    fig_dict = _generate_expression_tile_static(g_parsed, g_name or "Gene", is_survival=is_surv)
                    has_plot = False
                    if fig_dict:
                        viz_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "static_plot",
                            "id": viz_id,
                            "title": fig_dict["title"],
                            **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")},
                        })
                        ls.append(f"[PLOT:{viz_id}]")
                        ls.append("")
                        has_plot = True
                    # Only show table as fallback if the plot could not be generated
                    if not has_plot:
                        if not cancers_:
                            # No data at all — skip this section entirely
                            return None
                        ls.extend([f"| Cancer | {c_rna} | {c_prot} |", "|---|---|---|"])
                        for c in cancers_:
                            ls.append(f"| {c} | {rd_.get(c,'-')} | {pd_.get(c,'-')} |")
                        ls.append("")
                    ls.append(f"> **Source:** [LinkedOmics](#source:linkedomics) · {s_desc}")
                    return "\n".join(ls) + "\n"

                if batch_data:
                    for g, g_result in batch_data.items():
                        if isinstance(g_result, dict) and ("protein_level" in g_result or "RNA_level" in g_result):
                            sec = _render_single_gene_section(g, g_result, base_title, subtitle, source_desc, col_rna, col_prot)
                            if sec is not None:
                                sections.append(sec)
                else:
                    # Use gene_name from metadata wrapper
                    sec = _render_single_gene_section(gene_name, parsed, base_title, subtitle, source_desc, col_rna, col_prot)
                    if sec is not None:
                        sections.append(sec)
                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("get_target") or tool_id.endswith("batch_get_target"):
                if not isinstance(parsed, dict):
                    continue
                # batch returns {"results": {"GENE": {"result": {...}}, ...}}
                # single returns {"result": {...}}
                entries: list[tuple[str, dict]] = []
                if tool_id.endswith("batch_get_target"):
                    for g_sym, g_data in (parsed.get("results") or {}).items():
                        r = g_data.get("result") if isinstance(g_data, dict) else None
                        if isinstance(r, dict):
                            entries.append((g_sym, r))
                else:
                    r = parsed.get("result")
                    if isinstance(r, dict):
                        entries.append((gene_name or "Gene", r))
                if not entries:
                    continue
                _GRID_FEATURES = [
                    ("Gene dependency in cell line", "cell_line_dependency"),
                    ("Increased in tumor, summary",  "tumor_increase_summary"),
                    ("Mutation cis effect",           "mutation_cis_effect"),
                    ("Methylation driver",            "methylation_driver"),
                    ("CNV driver",                    "cnv_driver"),
                    ("TSG associated dependency",     "tsg_dependency"),
                    ("Neoantigen, somatic mutation",  "neoantigen_mutations"),
                    ("Neoantigen, fusion",            "neoantigen_fusions"),
                    ("Tumor associated antigen",      "tumor_associated_antigen"),
                ]
                _GRID_COHORTS = ["BRCA", "CCRCC", "COAD", "GBM", "HNSCC", "LSCC", "LUAD", "OV", "PDAC", "UCEC"]

                import re as _re2
                def _cohorts_in(val) -> set:
                    if not val or (isinstance(val, str) and val.startswith("No evidence")):
                        return set()
                    if isinstance(val, list):
                        return {e["cohort"] for e in val if isinstance(e, dict) and "cohort" in e}
                    return {c for c in _GRID_COHORTS if _re2.search(rf'\b{_re2.escape(c)}\b', str(val))}

                for g_sym, r in entries:
                    title = f"Drug target profile — {g_sym}"
                    md = [f"## {title}", ""]

                    hyper_raw = r.get("hyperactivated_sites", "")
                    hyper_sites = hyper_raw if isinstance(hyper_raw, list) else []

                    presence = [
                        [c in _cohorts_in(r.get(field, "")) for c in _GRID_COHORTS]
                        for _, field in _GRID_FEATURES
                    ]

                    viz_id = _uuid.uuid4().hex
                    _visualizations.append({
                        "type": "drug_target_grid",
                        "id": viz_id,
                        "title": title,
                        "gene": g_sym,
                        "tier": r.get("tier", ""),
                        "family": r.get("Family", "") or r.get("family", ""),
                        "drugs": r.get("drugs", ""),
                        "drug_tiers": r.get("drug_tiers", ""),
                        "drug_details": r.get("_drug_details", []),
                        "features": [{"label": lbl, "field": fld} for lbl, fld in _GRID_FEATURES],
                        "cohorts": _GRID_COHORTS,
                        "presence": presence,
                        "plot_map": r.get("_plot_map", {}),
                        "table_map": r.get("_table_map", {}),
                        "hyper_sites": hyper_sites,
                        "protein_cohorts": sorted(_cohorts_in(r.get("tumor_increase_protein", "")) & set(_GRID_COHORTS)),
                    })
                    md.append(f"\n[PLOT:{viz_id}]")
                    md.append("")
                    md.append("\n> **Source:** [LinkedOmics Targets](#source:targets)")
                    sections.append("\n".join(md) + "\n")
                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("rank_targets"):
                if not isinstance(parsed, dict):
                    continue
                genes = parsed.get("genes", [])
                total = parsed.get("total", len(genes))
                top_n = parsed.get("top_n", len(genes))
                filter_label = _target_filter_label(parsed)
                ranking_mode, ranking_label, ranking_explanation, score_label = _target_ranking_meta(parsed)
                if not genes:
                    sections.append(
                        f"_No druggable targets found for {filter_label} using {ranking_label.lower()} ranking._\n"
                    )
                    _rendered_tool_ids.add(tool_id)
                    continue
                viz_id = _uuid.uuid4().hex
                description = (
                    f"Ranking mode: {ranking_label}; filters: {filter_label}. "
                    f"**How targets are ranked** — {ranking_explanation} "
                    f"The **{score_label}** column shows this value. "
                    f"Showing top {top_n} of {total} ranked targets."
                )
                _visualizations.append({
                    "type": "target_search_table",
                    "id": viz_id,
                    "title": _target_ranking_title(ranking_mode),
                    "total": top_n,
                    "genes": genes,
                    "description": description,
                    "score_label": score_label,
                })
                md = [f"\n[PLOT:{viz_id}]", ""]
                md.append("\n> **Source:** [LinkedOmics Targets](#source:targets)")
                sections.append("\n".join(md) + "\n")
                _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("search_targets"):
                if not isinstance(parsed, dict):
                    continue
                genes = parsed.get("genes", [])
                total = parsed.get("total", len(genes))
                filter_label = _target_filter_label(parsed)
                if not genes:
                    sections.append(f"_No targets matched this search ({filter_label})._\n")
                    _rendered_tool_ids.add(tool_id)
                    continue
                viz_id = _uuid.uuid4().hex
                _visualizations.append({
                    "type": "target_search_table",
                    "id": viz_id,
                    "title": f"Target search results ({total} genes)",
                    "total": total,
                    "genes": genes,
                    "description": f"Filters: {filter_label}",
                })
                md = [f"\n[PLOT:{viz_id}]", ""]
                md.append("\n> **Source:** [LinkedOmics Targets](#source:targets)")
                sections.append("\n".join(md) + "\n")
                _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("clinical_trial_information"):
                if not isinstance(parsed, dict):
                    continue  # skip unrenderable result silently
                status = parsed.get("status", "unavailable")
                raw_data = parsed.get("data") or {}

                # Detect batch vs single: batch data is a dict of {protein: result}
                is_batch = (
                    tool_id.endswith("batch_clinical_trial_information")
                    or (isinstance(raw_data, dict) and all(
                        isinstance(v, dict) and "status" in v
                        for v in raw_data.values()
                    ) and raw_data)
                )

                def _render_single_trial(data: dict, label: str) -> list[str]:
                    lines: list[str] = []
                    total_sig = data.get("total_significant", "")
                    total_all = data.get("total_studies", "")
                    if total_sig or total_all:
                        lines.append(f"**Significant studies:** {total_sig} / {total_all}")
                    lines.append("")
                    fig_dict = _generate_trials_auroc_chart(data, label)
                    if fig_dict:
                        viz_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "static_plot",
                            "id": viz_id,
                            "title": fig_dict["title"],
                            **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")},
                        })
                        lines.append(f"[PLOT:{viz_id}]")
                        lines.append("")
                    resistant = data.get("resistant", data.get("top_resistant", []))
                    sensitive = data.get("sensitive", data.get("top_sensitive", []))
                    all_rows = []
                    for s in resistant:
                        all_rows.append({
                            "label": str(s.get("treatment", "") or ""),
                            "series": s.get("series", ""),
                            "study_id": s.get("study_id", ""),
                            "studies": s.get("sample_size", ""),
                            "avg_auroc": s.get("auroc"),
                            "meta_fdr": s.get("fdr"),
                            "p_value": s.get("p_value"),
                            "response_evaluation": s.get("response_evaluation", ""),
                            "direction": "resistant",
                            "disease": s.get("disease", ""),
                            "subtype": s.get("subtype", ""),
                        })
                    for s in sensitive:
                        all_rows.append({
                            "label": str(s.get("treatment", "") or ""),
                            "series": s.get("series", ""),
                            "study_id": s.get("study_id", ""),
                            "studies": s.get("sample_size", ""),
                            "avg_auroc": s.get("auroc"),
                            "meta_fdr": s.get("fdr"),
                            "p_value": s.get("p_value"),
                            "response_evaluation": s.get("response_evaluation", ""),
                            "direction": "sensitive",
                            "disease": s.get("disease", ""),
                            "subtype": s.get("subtype", ""),
                        })
                    # Sort by FDR magnitude (most significant first)
                    all_rows.sort(key=lambda r: abs(float(r.get("meta_fdr") or 1)))
                    for i, r in enumerate(all_rows, 1):
                        r["rank"] = i
                    if all_rows:
                        table_viz_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "predictive_results_table",
                            "variant": "clinical_trial",
                            "id": table_viz_id,
                            "title": f"Clinical Trial Associations — {label}",
                            "row_label": "Treatment",
                            "gene": label,
                            "description": f"{total_sig} significant / {total_all} total studies — click a row to view expression plots",
                            "rows": all_rows,
                        })
                        lines.append(f"[TABLE:{table_viz_id}]")
                    return lines

                if is_batch:
                    md = ["## Clinical trial associations — batch"]
                    if status != "available":
                        md.append(f"_Status: {status}_")
                    else:
                        md.extend(_trial_scope_lines("the requested genes", signal_label="expression", batch=True))
                        md.append("")
                        for protein, result in raw_data.items():
                            if not isinstance(result, dict):
                                continue
                            if result.get("status") != "available":
                                md.append(f"\n### {protein}")
                                md.append(f"_No clinical-trial associations available (status: {result.get('status', 'unavailable')})._")
                                continue
                            pdata = result.get("data") or {}
                            md.append(f"\n### {protein}")
                            md.extend(_render_single_trial(pdata, protein))
                else:
                    chart_label = gene_name or "Gene"
                    md = [f"## Clinical trial associations — {chart_label}"]
                    if status != "available":
                        md.append(f"_Status: {status}_")
                    else:
                        md.extend(_trial_scope_lines(chart_label, signal_label="expression"))
                        md.append("")
                        md.extend(_render_single_trial(raw_data, chart_label))

                md.append("\n> **Source:** [LinkedOmics Trials](#source:trials)")
                sections.append("\n".join(md) + "\n")
                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("get_study_info"):
                if not isinstance(parsed, dict):
                    continue
                status = parsed.get("status", "unavailable")
                d = parsed.get("data") or {}
                if status != "available" or not d:
                    sections.append("_Study information unavailable._\n")
                    _rendered_tool_ids.add(tool_id)
                    continue
                series = d.get("series", d.get("study_id", ""))
                md = [f"## Study Details — {series}", ""]

                # Metadata as a compact 2-column table
                nct = d.get("clinical_trial_id", "")
                pubmed = d.get("pub_med_id", d.get("pubmed_id", ""))
                sample_n = d.get("sample_size", "")
                resp = d.get("responder_size", "")
                non_resp = d.get("non_responder_size", "")
                sample_str = f"{sample_n} (R: {resp}, NR: {non_resp})" if resp or non_resp else sample_n
                download = d.get("download_url", "")

                rows = [
                    ("Disease",      f"{d.get('disease','')} — {d.get('subtype','')}".rstrip(" —")),
                    ("Treatment",    d.get("treatment", "")),
                    ("Response eval", d.get("response_eval", "")),
                    ("Sample size",  sample_str),
                    ("NCT Trial ID", nct),
                    ("PubMed ID",    pubmed),
                    ("Platform",     d.get("platform", "")),
                    ("Normalization", d.get("normalization_method", "")),
                ]
                if download:
                    rows.append(("Data download", f"[Download]({download})"))

                md.append("| Field | Value |")
                md.append("|---|---|")
                for field, val in rows:
                    if val and str(val).strip():
                        md.append(f"| {field} | {val} |")

                abstract = d.get("study_abstract") or d.get("abstract", "")
                if abstract:
                    md.append("\n### Abstract")
                    md.append(abstract)
                md.append("\n> **Source:** [LinkedOmics Trials](#source:trials)")
                sections.append("\n".join(md) + "\n")
                _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("gene_set_trial_information"):
                if not isinstance(parsed, dict):
                    continue
                status = parsed.get("status", "unavailable")
                gs = parsed.get("gene_set", "")
                data = parsed.get("data") or {}
                gs_title = f"Pathway trial associations — {gs}" if gs else "Pathway trial associations"
                md = [f"## {gs_title}"]
                if status != "available":
                    md.append(f"_Status: {status}_")
                else:
                    md.extend(_trial_scope_lines(gs or "this gene set", signal_label="pathway activity"))
                    md.append("")
                    total_sig = data.get("total_significant", "")
                    total_all = data.get("total_studies", "")
                    if total_sig or total_all:
                        md.append(f"**Significant studies:** {total_sig} / {total_all}")
                    md.append("")
                    fig_dict = _generate_trials_auroc_chart(data, gs or "Gene Set")
                    if fig_dict:
                        viz_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "static_plot",
                            "id": viz_id,
                            "title": fig_dict["title"],
                            **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")},
                        })
                        md.append(f"[PLOT:{viz_id}]")
                        md.append("")
                    resistant_gs = data.get("resistant", data.get("top_resistant", []))
                    sensitive_gs = data.get("sensitive", data.get("top_sensitive", []))
                    gs_rows = []
                    for s in resistant_gs:
                        gs_rows.append({
                            "label": str(s.get("treatment", "") or ""),
                            "series": s.get("series", ""),
                            "study_id": s.get("study_id", ""),
                            "studies": s.get("sample_size", ""),
                            "avg_auroc": s.get("auroc"),
                            "meta_fdr": s.get("fdr"),
                            "p_value": s.get("p_value"),
                            "response_evaluation": s.get("response_evaluation", ""),
                            "direction": "resistant",
                            "disease": s.get("disease", ""),
                            "subtype": s.get("subtype", ""),
                        })
                    for s in sensitive_gs:
                        gs_rows.append({
                            "label": str(s.get("treatment", "") or ""),
                            "series": s.get("series", ""),
                            "study_id": s.get("study_id", ""),
                            "studies": s.get("sample_size", ""),
                            "avg_auroc": s.get("auroc"),
                            "meta_fdr": s.get("fdr"),
                            "p_value": s.get("p_value"),
                            "response_evaluation": s.get("response_evaluation", ""),
                            "direction": "sensitive",
                            "disease": s.get("disease", ""),
                            "subtype": s.get("subtype", ""),
                        })
                    gs_rows.sort(key=lambda r: abs(float(r.get("meta_fdr") or 1)))
                    for i, r in enumerate(gs_rows, 1):
                        r["rank"] = i
                    if gs_rows:
                        gs_table_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "predictive_results_table",
                            "variant": "clinical_trial",
                            "plot_type": "gene_set",
                            "id": gs_table_id,
                            "title": f"Pathway Trial Associations — {gs}",
                            "row_label": "Treatment",
                            "gene": gs,
                            "description": f"{total_sig} significant / {total_all} total studies — click a row to view expression plots",
                            "rows": gs_rows,
                        })
                        md.append(f"[TABLE:{gs_table_id}]")
                md.append("\n> **Source:** [LinkedOmics Trials](#source:trials)")
                sections.append("\n".join(md) + "\n")
                _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("filter_clinical_trials"):
                if not isinstance(parsed, dict):
                    continue
                status = parsed.get("status", "unavailable")
                d = parsed.get("data") or {}
                filters = d.get("filters_applied", {})
                md = ["## Clinical Trial Study Filter"]
                if status != "available":
                    md.append(f"_Status: {status}_")
                else:
                    drugs_f = filters.get('drugs', [])
                    cancers_f = filters.get('cancers', [])
                    md.append(
                        f"**Drugs:** {', '.join(drugs_f) if drugs_f else 'any'}  "
                        f"**Cancers:** {', '.join(cancers_f) if cancers_f else 'any'}  "
                        f"**Matching studies:** {d.get('study_count', 0)}"
                    )
                    possible = d.get("possible_cancers", [])
                    if possible:
                        md.append(f"**Cancer types present:** {', '.join(str(c) for c in possible)}")
                    study_list = d.get("study_list", [])
                    if study_list:
                        md.append("")
                        md.append("| # | Study | Series |")
                        md.append("|---|---|---|")
                        for i, s in enumerate(study_list, 1):
                            # Strip .csv suffix; try to split into a readable series name
                            bare = s.removesuffix(".csv")
                            # Series is the GSE-style prefix or full name before treatment suffix
                            md.append(f"| {i} | {bare} | {bare.split('_')[0]} |")
                    else:
                        md.append("_No matching studies found._")
                md.append("\n> **Source:** [LinkedOmics Trials](#source:trials)")
                sections.append("\n".join(md) + "\n")
                _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("meta_analysis_predictive_genes"):
                if not isinstance(parsed, dict):
                    continue
                status = parsed.get("status", "unavailable")
                d = parsed.get("data") or {}
                filters = d.get("filters", {})
                md = ["## Meta-analysis: Top Predictive Genes"]
                if status == "no_studies":
                    md.append(f"_No studies found matching filters: {_filter_label(filters)}._")
                elif status != "available":
                    md.append(f"_Status: {status}_")
                else:
                    md.append(
                        f"**Studies analyzed:** {d.get('study_count',0)} | "
                        f"**Filters:** {_filter_label(filters)}"
                    )
                    md.append("")
                    genes = d.get("top_genes", [])
                    if genes:
                        chart = _generate_meta_analysis_chart(
                            genes[:25], "gene",
                            f"Top Predictive Genes — {_filter_label(filters)}"
                        )
                        if chart:
                            viz_id = _uuid.uuid4().hex
                            _visualizations.append({"type": "static_plot", "id": viz_id, **chart})
                            md.append(f"[PLOT:{viz_id}]\n")
                        table_viz_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "predictive_results_table",
                            "plot_type": "treatment_gene",
                            "id": table_viz_id,
                            "title": "Top Predictive Genes",
                            "row_label": "Gene",
                            "study_list": d.get("study_list", []),
                            "description": f"Studies analyzed: {d.get('study_count',0)} | Filters: {_filter_label(filters)}",
                            "rows": [
                                {
                                    "rank": i,
                                    "label": g.get("gene", ""),
                                    "studies": g.get("datasets", ""),
                                    "avg_auroc": g.get("avg_auc", ""),
                                    "meta_fdr": g.get("meta_fdr", ""),
                                    "meta_fdr_signed": g.get("meta_fdr_signed", g.get("meta_fdr", "")),
                                    "meta_fdr_sci": g.get("meta_fdr_sci", ""),
                                    "direction": g.get("direction", ""),
                                }
                                for i, g in enumerate(genes, 1)
                            ],
                        })
                        md.append(f"[TABLE:{table_viz_id}]")
                    else:
                        md.append("_No significant predictive genes found._")
                md.append("\n> **Source:** [LinkedOmics Trials](#source:trials)")
                sections.append("\n".join(md) + "\n")
                _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("meta_analysis_predictive_gene_sets"):
                if not isinstance(parsed, dict):
                    continue
                status = parsed.get("status", "unavailable")
                d = parsed.get("data") or {}
                filters = d.get("filters", {})
                md = ["## Meta-analysis: Top Predictive Pathways"]
                if status == "no_studies":
                    md.append(f"_No studies found matching filters: {_filter_label(filters)}._")
                elif status != "available":
                    md.append(f"_Status: {status}_")
                else:
                    md.append(
                        f"**Studies analyzed:** {d.get('study_count',0)} | "
                        f"**Filters:** {_filter_label(filters)}"
                    )
                    md.append("")
                    gene_sets = d.get("top_gene_sets", [])
                    if gene_sets:
                        chart = _generate_meta_analysis_chart(
                            gene_sets[:25], "gene_set",
                            f"Top Predictive Pathways — {_filter_label(filters)}"
                        )
                        if chart:
                            viz_id = _uuid.uuid4().hex
                            _visualizations.append({"type": "static_plot", "id": viz_id, **chart})
                            md.append(f"[PLOT:{viz_id}]\n")
                        table_viz_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "predictive_results_table",
                            "plot_type": "treatment_gene_set",
                            "id": table_viz_id,
                            "title": "Top Predictive Pathways",
                            "row_label": "Pathway / Gene Set",
                            "study_list": d.get("study_list", []),
                            "description": f"Studies analyzed: {d.get('study_count',0)} | Filters: {_filter_label(filters)}",
                            "rows": [
                                {
                                    "rank": i,
                                    "label": g.get("gene_set", ""),
                                    "studies": g.get("datasets", ""),
                                    "avg_auroc": g.get("avg_auc", ""),
                                    "meta_fdr": g.get("meta_fdr", ""),
                                    "meta_fdr_signed": g.get("meta_fdr_signed", g.get("meta_fdr", "")),
                                    "meta_fdr_sci": g.get("meta_fdr_sci", ""),
                                    "direction": g.get("direction", ""),
                                }
                                for i, g in enumerate(gene_sets, 1)
                            ],
                        })
                        md.append(f"[TABLE:{table_viz_id}]")
                    else:
                        md.append("_No significant predictive pathways found._")
                md.append("\n> **Source:** [LinkedOmics Trials](#source:trials)")
                sections.append("\n".join(md) + "\n")
                _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("get_study_predictive_genes") or tool_id.endswith("get_study_predictive_gene_sets"):
                if not isinstance(parsed, dict):
                    continue
                status = parsed.get("status", "unavailable")
                d = parsed.get("data") or {}
                sid = d.get("study_id", parsed.get("study_id", ""))
                is_gene_sets = tool_id.endswith("get_study_predictive_gene_sets")
                analyte_label = "Gene Set" if is_gene_sets else "Gene"
                analyte_key = "top_gene_sets" if is_gene_sets else "top_genes"
                total_key = "total_gene_sets" if is_gene_sets else "total_genes"
                title = f"Predictive {analyte_label}s — {sid}" if sid else f"Predictive {analyte_label}s"
                md = [f"## {title}"]
                if status != "available":
                    md.append(f"_Status: {status}_")
                else:
                    md.append(f"**Study:** {sid}  **Total {analyte_label.lower()}s tested:** {d.get(total_key, '')}")
                    md.append("")
                    analytes = d.get(analyte_key, [])
                    if analytes:
                        md.append(f"| # | {analyte_label} | AUROC | FDR | Direction |")
                        md.append("|---|---|---|---|---|")
                        for i, g in enumerate(analytes, 1):
                            md.append(
                                f"| {i} | {g.get('analyte','')} | {g.get('auc','')} "
                                f"| {g.get('fdr','')} | {g.get('direction','').capitalize()} |"
                            )
                    else:
                        md.append(f"_No significant predictive {analyte_label.lower()}s found._")
                md.append("\n> **Source:** [LinkedOmics Trials](#source:trials)")
                sections.append("\n".join(md) + "\n")
                _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("get_cis_correlations"):
                if not isinstance(parsed, dict):
                    continue  # skip unrenderable result silently

                def _render_single_cis_section(
                    g_name: str,
                    g_parsed: dict,
                    fallback_applied_pairs: list[str] | None = None,
                    fallback_applied_cancers: list[str] | None = None,
                ) -> Optional[str]:
                    if not isinstance(g_parsed, dict):
                        return None

                    data = g_parsed.get("data", {})
                    applied_pairs = g_parsed.get("applied_pairs") or fallback_applied_pairs or []
                    applied_cancers = g_parsed.get("applied_cancers") or fallback_applied_cancers or []
                    status = g_parsed.get("status", "available")
                    message = g_parsed.get("message", "")

                    cis_title = f"Cis-Correlations - {g_name}" if g_name else "Cis-Correlations"
                    md = [f"## {cis_title}", ""]
                    if applied_pairs:
                        md.append(f"**Pairs:** {', '.join(applied_pairs)}")
                    if applied_cancers:
                        md.append(f"**Cancer Types:** {', '.join(applied_cancers)}")
                    if applied_pairs or applied_cancers:
                        md.append("")

                    fig_dict = _generate_cis_correlation_static(data, g_name or "Gene")
                    cis_has_plot = False
                    if fig_dict:
                        viz_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "static_plot",
                            "id": viz_id,
                            "title": fig_dict["title"],
                            **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")},
                        })
                        md.append(f"[PLOT:{viz_id}]")
                        md.append("")
                        cis_has_plot = True

                    # Only show per-cohort tables as fallback if plot could not be generated
                    if not cis_has_plot:
                        if status != "available" and message:
                            md.append(f"_{message}_")
                        elif not data:
                            md.append(f"_{message or 'No correlation data found.'}_")
                        else:
                            for cohort, records in data.items():
                                if not records:
                                    continue
                                md.append(f"\n### {cohort}")
                                if isinstance(records, list) and len(records) > 0:
                                    keys = list(records[0].keys())
                                    header = "| " + " | ".join(keys) + " |"
                                    separator = "| " + " | ".join(["---"] * len(keys)) + " |"
                                    md.append(header)
                                    md.append(separator)
                                    for rec in records[:10]:
                                        row = "| " + " | ".join(str(rec.get(k, "")) for k in keys) + " |"
                                        md.append(row)
                                    if len(records) > 10:
                                        md.append(f"_(showing 10 of {len(records)} records)_")
                                else:
                                    md.append("_No records._")

                    md.append("\n> **Source:** [LinkedOmics](#source:linkedomics)")
                    return "\n".join(md) + "\n"

                if tool_id.endswith("batch_get_cis_correlations"):
                    batch_data = parsed.get("data") or {}
                    fallback_applied_pairs = parsed.get("applied_pairs") or []
                    fallback_applied_cancers = parsed.get("applied_cancers") or []
                    if isinstance(batch_data, dict) and batch_data:
                        for batch_gene, batch_payload in batch_data.items():
                            sec = _render_single_cis_section(
                                batch_gene,
                                batch_payload,
                                fallback_applied_pairs,
                                fallback_applied_cancers,
                            )
                            if sec is not None:
                                sections.append(sec)
                    else:
                        sec = _render_single_cis_section(
                            "",
                            parsed,
                            fallback_applied_pairs,
                            fallback_applied_cancers,
                        )
                        if sec is not None:
                            sections.append(sec)
                else:
                    sec = _render_single_cis_section(gene_name, parsed)
                    if sec is not None:
                        sections.append(sec)

                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("tcga_cis_association_analysis"):
                if not isinstance(parsed, dict):
                    continue

                mode_val = parsed.get("mode")
                results_list = parsed.get("results", [])
                query_params = parsed.get("query", {})
                g = (query_params.get("gene") or gene_name or "").upper()
                coh = query_params.get("cohort") or ""
                src_o = query_params.get("source_omics") or ""
                tgt_o = query_params.get("target_omics") or ""
                coh_full = _TCGA_COHORT_NAMES.get(coh, coh)
                coh_display = f"{coh} ({coh_full})" if coh and coh_full and coh_full != coh else (coh or coh_full)
                omics_disp = f"{src_o} → {tgt_o}" if src_o and tgt_o else (src_o or tgt_o or "omics")
                n_results = parsed.get("n_results", len(results_list))

                if mode_val == 1:
                    sec_title = f"TCGA Cis Association — {g} in {coh_display} ({omics_disp})"
                elif mode_val == 2:
                    sec_title = f"TCGA Cis Associations — {g} in {coh_display} (all omics pairs)"
                elif mode_val == 3:
                    sec_title = f"TCGA Cis Association — {g} ({omics_disp}, all cohorts)"
                elif mode_val == 4:
                    sec_title = f"TCGA Cis Association Genome Scan — {coh_display} ({omics_disp})"
                else:
                    sec_title = "TCGA Cis Association"

                md = [f"## {sec_title}", ""]

                # Scope line
                if mode_val == 1:
                    r1 = results_list[0] if results_list else {}
                    cor_v = r1.get("correlation", "N/A")
                    pval_v = r1.get("pvalue", "N/A")
                    n_v = r1.get("n", "N/A")
                    md.append(f"**Correlation:** {cor_v}  |  **p-value:** {pval_v}  |  **n:** {n_v}")
                    md.append("")
                    # Scatter plot if samples are available
                    plot_dicts = _generate_tcga_cis_association_static(parsed) or []
                    for fig_dict in plot_dicts:
                        viz_id = _uuid.uuid4().hex
                        _visualizations.append({
                            "type": "static_plot",
                            "id": viz_id,
                            "title": fig_dict["title"],
                            **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")},
                        })
                        md.append(f"[PLOT:{viz_id}]")
                        md.append("")
                else:
                    md.append(f"**Results:** {n_results}")
                    md.append("")
                    plot_dicts = _generate_tcga_cis_association_static(parsed) or []
                    if plot_dicts:
                        for fig_dict in plot_dicts:
                            viz_id = _uuid.uuid4().hex
                            _visualizations.append({
                                "type": "static_plot",
                                "id": viz_id,
                                "title": fig_dict["title"],
                                **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")},
                            })
                            md.append(f"[PLOT:{viz_id}]")
                            md.append("")

                    rendered_mode4_table = False
                    if mode_val == 4:
                        top_hits = _tcga_cis_mode4_top_hits(results_list, limit=50, fdr_threshold=0.5)
                        if top_hits:
                            table_viz_id = _uuid.uuid4().hex
                            _visualizations.append({
                                "type": "predictive_results_table",
                                "variant": "tcga_cis",
                                "id": table_viz_id,
                                "title": f"Top Cis-Associated Genes — {coh_display} ({omics_disp})",
                                "row_label": "Gene",
                                "col_auroc": "Correlation",
                                "col_fdr": "FDR",
                                "page_size": 10,
                                "description": (
                                    "Same ranked gene set as the bidirectional bar chart: "
                                    "up to 50 genes with FDR < 0.5, ordered by absolute correlation. "
                                    "Opaque bars indicate FDR < 0.05."
                                ),
                                "rows": [
                                    {
                                        "rank": rank,
                                        "label": entry["gene"],
                                        "avg_auroc": entry["cor"],
                                        "meta_fdr": entry["fdr"],
                                        "meta_fdr_sci": f"{entry['fdr']:.4e}",
                                        "studies": entry["n"],
                                        "direction": "positive" if entry["cor"] >= 0 else "negative",
                                    }
                                    for rank, entry in enumerate(top_hits, 1)
                                ],
                            })
                            md.append("**Top hits by |correlation| (same ranking as the bar chart):**")
                            md.append("")
                            md.append("[TABLE:" + table_viz_id + "]")
                            md.append("")
                            rendered_mode4_table = True

                    if not plot_dicts and not rendered_mode4_table:
                        # Fallback table (cap at 20 rows)
                        if results_list:
                            keys = list(results_list[0].keys())
                            md.append("| " + " | ".join(keys) + " |")
                            md.append("| " + " | ".join(["---"] * len(keys)) + " |")
                            for row in results_list[:20]:
                                md.append("| " + " | ".join(str(row.get(k, "")) for k in keys) + " |")
                            if len(results_list) > 20:
                                md.append(f"_(showing 20 of {len(results_list)} results)_")
                            md.append("")

                md.append("> **Source:** [LinkedOmics TCGA](#source:linkedomics)")
                sections.append("\n".join(md) + "\n")
                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("webgestalt"):
                rows = []
                if isinstance(parsed, dict):
                    rows = parsed.get("data") or []
                if not isinstance(rows, list):
                    rows = []
                enrich_title = f"Pathway / GO enrichment - {gene_name}" if gene_name else "Pathway / GO enrichment"
                md = [f"## {enrich_title}", ""]
                fig_dict = _generate_enrichment_static(rows, enrich_title)
                if fig_dict:
                    viz_id = _uuid.uuid4().hex
                    _visualizations.append({
                        "type": "static_plot",
                        "id": viz_id,
                        "title": fig_dict["title"],
                        **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")},
                    })
                    md.append(f"[PLOT:{viz_id}]")
                    md.append("")
                md.extend([
                    "| GO Term | Description | Enrichment Ratio | FDR |",
                    "|---|---|---|---|",
                ])
                for row in rows:
                    gs = row.get("geneSet", "")
                    desc = row.get("description", "")
                    er = row.get("enrichmentRatio", "")
                    fdr = row.get("FDR", "")
                    try:
                        er = f"{float(er):.2f}"
                    except Exception:
                        pass
                    try:
                        fdr = f"{float(fdr):.2e}"
                    except Exception:
                        pass
                    md.append(f"| {gs} | {desc} | {er} | {fdr} |")
                if not rows:
                    md.append("| — | No enriched terms found | — | — |")
                md.append("\n> **Source:** [WebGestalt](#source:webgestalt)")
                sections.append("\n".join(md) + "\n")
                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue

            if tool_id.endswith("tcga_survival_analysis"):
                # Render the merged group section on first encounter; skip duplicates.
                gene_name_k = wrapped_result.get("_gene", "") if isinstance(wrapped_result, dict) else ""
                raw_k = wrapped_result["_result"] if isinstance(wrapped_result, dict) and "_result" in wrapped_result else wrapped_result
                parsed_k = _maybe_json(raw_k)
                cohort_key_k = (parsed_k.get("query", {}).get("cohort", "") if isinstance(parsed_k, dict) else "")
                group_key = (gene_name_k, cohort_key_k)
                if group_key in _tcga_rendered:
                    continue
                _tcga_rendered.add(group_key)
                parsed_list = _tcga_groups.get(group_key, [])
                if not parsed_list:
                    continue
                all_results = []
                mode = 1
                omics_query = ""
                for p in parsed_list:
                    mode = p.get("mode", 1)
                    omics_query = omics_query or p.get("query", {}).get("omics", "")
                    all_results.extend(p.get("results") or [])
                if not all_results:
                    continue
                first_res = all_results[0]
                g = first_res.get("gene") or gene_name_k or "Gene"
                logger.info(f"[tcga_survival] grouped mode={mode} gene={g} cohort={cohort_key_k!r} n_results={len(all_results)}")
                if mode == 4:
                    # Genome-wide scan (cohort + omics): render volcano plot + top-gene table
                    omics_label = _OMICS_LABEL_PRE.get(omics_query, omics_query)
                    cohort_full = _TCGA_COHORT_NAMES.get(cohort_key_k, cohort_key_k)
                    section_title = f"TCGA Genome-wide Survival Scan — {cohort_key_k} ({omics_label})"
                    viz_title = f"Survival associations — {cohort_key_k} {omics_label}"
                    viz_id = _uuid.uuid4().hex
                    fig_dict = _generate_volcano_static(all_results, cohort_key_k, omics_query, viz_title)
                    # Top 20 significant genes table
                    sig_results = sorted(
                        [r for r in all_results if (r.get("fdr") or r.get("pvalue") or 1.0) < 0.05],
                        key=lambda r: float(r.get("fdr") or r.get("pvalue") or 1.0),
                    )[:20]
                    md = [f"## {section_title}", ""]
                    md.extend(_tcga_scope_lines(
                        mode=mode,
                        gene=g,
                        cohort=cohort_key_k,
                        cohort_full=cohort_full,
                        omics_label=omics_label,
                        n_results=len(all_results),
                    ))
                    md.append("")
                    if fig_dict:
                        _visualizations.append({"type": "static_plot", "id": viz_id, "title": fig_dict["title"],
                                                 **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")}})
                        md.append(f"[PLOT:{viz_id}]")
                        md.append("")
                    n_sig = len([r for r in all_results if (r.get("fdr") or r.get("pvalue") or 1.0) < 0.05])
                    md.append(f"**{n_sig}** significant genes (FDR < 0.05) out of **{len(all_results)}** tested in {cohort_full}.")
                    md.append("")
                    if sig_results:
                        md.append("**Top prognostic genes:**")
                        md.append("")
                        md.append("| Gene | HR | FDR | N | Direction |")
                        md.append("|---|---|---|---|---|")
                        for res in sig_results:
                            gene_r = res.get("gene", ""); hr_r = res.get("hr"); fdr_r = res.get("fdr") or res.get("pvalue"); n_r = res.get("n")
                            direction = "↑ Harmful" if hr_r and hr_r > 1 else "↓ Protective"
                            md.append(f"| {gene_r} | {f'{hr_r:.4f}' if hr_r is not None else '—'} | {f'{fdr_r:.2e}' if fdr_r is not None else '—'} | {n_r if n_r is not None else '—'} | {direction} |")
                    else:
                        md.append("_No significant associations found at FDR < 0.05._")
                    md.append("")
                    md.append(f"> **Source:** [LinkedOmics](#source:linkedomics) · TCGA dataset")
                elif mode == 3 and not cohort_key_k:
                    omics_label = _OMICS_LABEL_PRE.get(omics_query, omics_query)
                    section_title = f"TCGA Survival Analysis — {g} ({omics_label}, all cohorts)"
                    md = [f"## {section_title}", ""]
                    md.extend(_tcga_scope_lines(
                        mode=mode,
                        gene=g,
                        cohort="",
                        cohort_full="",
                        omics_label=omics_label,
                        n_results=len(all_results),
                    ))
                    md.append("")
                    # Bar chart across all cohorts (samples not available in mode 3)
                    cohort_fig = _generate_tcga_cohort_bar_static(all_results, g, omics_label)
                    has_cohort_plot = False
                    if cohort_fig:
                        viz_id = _uuid.uuid4().hex
                        _visualizations.append({"type": "static_plot", "id": viz_id, "title": cohort_fig["title"], **{k: cohort_fig[k] for k in ("png_b64", "svg", "csv")}})
                        md.append(f"[PLOT:{viz_id}]")
                        md.append("")
                        has_cohort_plot = True
                    # Only show table as fallback if plot could not be generated
                    if not has_cohort_plot:
                        sorted_results = sorted(all_results, key=lambda r: float(r.get("pvalue") or 1.0))
                        md.extend(["| Cohort | Cancer | HR | p-value | N | Significant |", "|---|---|---|---|---|---|"])
                        for res in sorted_results:
                            c = res.get("cohort", ""); hr = res.get("hr"); pval = res.get("pvalue"); n_tot = res.get("n")
                            c_full = _TCGA_COHORT_NAMES.get(c, c)
                            md.append(f"| {c} | {c_full} | {f'{hr:.4f}' if hr is not None else '—'} | {f'{pval:.4e}' if pval is not None else '—'} | {n_tot if n_tot is not None else '—'} | {'✓' if pval is not None and pval < 0.05 else ''} |")
                    else:
                        sorted_results = sorted(all_results, key=lambda r: float(r.get("pvalue") or 1.0))
                    md.append("\n> **Source:** [LinkedOmics](#source:linkedomics) · TCGA dataset")
                    # KM plots for significant cohorts when samples are available
                    for res in [r for r in sorted_results if (r.get("pvalue") or 1.0) < 0.05][:5]:
                        c = res.get("cohort", "")
                        fig_dict = _generate_km_static(res.get("samples") or [], g, c, omics_query, res.get("hr"), res.get("pvalue"), res.get("n"))
                        if fig_dict:
                            viz_id = _uuid.uuid4().hex
                            _visualizations.append({"type": "static_plot", "id": viz_id, "title": fig_dict["title"], **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")}})
                            md.append(f"\n[PLOT:{viz_id}]")
                else:
                    # Mode 1 (cohort+gene+omics) or Mode 2 (cohort+gene, all omics): KM plot per omics type
                    cohort = first_res.get("cohort", "") or cohort_key_k
                    cohort_full = _TCGA_COHORT_NAMES.get(cohort, cohort)
                    cohort_display = f"{cohort} — {cohort_full}" if cohort_full and cohort_full != cohort else cohort
                    section_title = f"TCGA Survival Analysis — {g} ({cohort_display})" if cohort_display else f"TCGA Survival Analysis — {g}"
                    md = [f"## {section_title}"]
                    summary_omics_label = _OMICS_LABEL_PRE.get(omics_query, omics_query) or "omics data"
                    md.append("")
                    md.extend(_tcga_scope_lines(
                        mode=mode,
                        gene=g,
                        cohort=cohort,
                        cohort_full=cohort_full,
                        omics_label=summary_omics_label,
                        n_results=len(all_results),
                    ))
                    # Mode 2: cohort + gene, all omics → show summary omics bar chart
                    if mode == 2:
                        omics_fig = _generate_tcga_omics_heatmap_static(all_results, g, cohort)
                        if omics_fig:
                            viz_id = _uuid.uuid4().hex
                            _visualizations.append({"type": "static_plot", "id": viz_id, "title": omics_fig["title"], **{k: omics_fig[k] for k in ("png_b64", "svg", "csv")}})
                            md.append(f"\n[PLOT:{viz_id}]")
                    for res in all_results:
                        omics = res.get("omics", "") or omics_query
                        hr = res.get("hr"); pval = res.get("pvalue"); n_tot = res.get("n")
                        omics_label = _OMICS_LABEL_PRE.get(omics, omics) or "expression"
                        fig_dict = _generate_km_static(res.get("samples") or [], g, cohort, omics, hr, pval, n_tot)
                        if fig_dict:
                            viz_id = _uuid.uuid4().hex
                            _visualizations.append({"type": "static_plot", "id": viz_id, "title": fig_dict["title"], **{k: fig_dict[k] for k in ("png_b64", "svg", "csv")}})
                            md.append(f"\n[PLOT:{viz_id}]")
                        else:
                            stats = []
                            if hr is not None: stats.append(f"HR={hr:.4f}")
                            if pval is not None: stats.append(f"p={pval:.4f}")
                            if n_tot is not None: stats.append(f"n={n_tot}")
                            md.append(f"\n**{omics_label}**: " + (", ".join(stats) if stats else "no data"))
                    md.append("\n> **Source:** [LinkedOmics](#source:linkedomics) · TCGA dataset")
                sections.append("\n".join(md) + "\n")
                if len(sections) > _sections_before:
                    _rendered_tool_ids.add(tool_id)
                continue


            # Fallback: tool has no specific renderer — skip raw output.
            # The LLM's analytical summary in the 'summary' field covers this.
            logger.debug(f"[format] No specific renderer for {tool_id}, skipping raw output.")

            if len(sections) > _sections_before:
                _rendered_tool_ids.add(tool_id)

        # Add placeholder sections for genes that were requested but have no data.
        # Skip entirely if any tool returned an error (e.g. invalid gene resolution) —
        # in that case the LLM summary already explains what went wrong.
        any_errors = any(
            isinstance(v, dict) and isinstance(v.get("_result"), dict) and "error" in v["_result"]
            for v in results.values()
        )
        if query and not any_errors:
            requested_genes = self._extract_gene_symbols(query)
            if requested_genes:
                tool_types = [key.split('#')[0] for key in results.keys()]
                placeholder_title = next(
                    (title for title in (_placeholder_title_for_tool(tool_id) for tool_id in tool_types) if title),
                    None,
                )
                if not placeholder_title:
                    requested_genes = []

            if requested_genes:
                # Extract genes that already have data in the results
                genes_with_data = set()
                for unique_key, wrapped_result in results.items():
                    tool_id = unique_key.split('#')[0] if '#' in unique_key else unique_key
                    genes_with_data.update(_covered_genes_for_result(tool_id, wrapped_result))

                # Find genes without data
                genes_without_data = [g for g in requested_genes if g not in genes_with_data]

                # Add placeholder sections for genes without data
                for gene in genes_without_data:
                    sections.append(f"## {placeholder_title} - {gene}\n\nData unavailable\n")

        # Re-order sections so related analyses group together:
        # 1. Survival (TCGA + CPTAC) 2. Expression (tumor vs normal) 3. Everything else
        def _section_priority(s: str) -> int:
            h = s.lstrip("#").lstrip().lower()
            if h.startswith("tcga survival") or h.startswith("overall survival"):
                return 0
            if h.startswith("cancer expression"):
                return 2
            return 1
        sections.sort(key=_section_priority, reverse=False)

        return {
            "message": "\n\n".join(sections).strip() or "No LinkedOmics results.",
            "visualizations": _visualizations,
            "rendered_tool_ids": _rendered_tool_ids,
        }

    async def _generate_session_title(self, first_query: str) -> str:
        """Generate a short title for the chat session based on first query"""
        if settings.MOCK_LLM:
            return first_query[:50] + ("..." if len(first_query) > 50 else "")
        
        try:
            prompt = f"""Generate a short, descriptive title (max 6 words) for a chat conversation that starts with this question:

"{first_query}"

Respond with ONLY the title, nothing else. Make it specific and informative."""
            
            from langchain_core.messages import HumanMessage
            response = await LLMFactory.invoke_async(self.llm, [HumanMessage(content=prompt)])
            title = response.strip().strip('"').strip("'")
            
            # Limit length
            if len(title) > 60:
                title = title[:57] + "..."
            
            return title
        except Exception as e:
            logger.error(f"Error generating title: {e}")
            return first_query[:50] + ("..." if len(first_query) > 50 else "")
    
    @staticmethod
    def _persist_viz_to_disk(visualizations: list, session_id: str) -> None:
        """Save plot files into the session workspace and index them by visualization ID."""
        import os, json as _json, base64 as _b64
        plot_dir = session_plot_dir(session_id)
        for viz in visualizations:
            viz_type = viz.get("type")
            viz_id = viz.get("id")
            if not viz_id or viz_type not in ("static_plot", "network_plot", "drug_target_grid", "target_search_table", "predictive_results_table", "tcga_cis_results_table"):
                continue
            safe_viz_id = os.path.basename(str(viz_id))
            title = viz.get("title", "")

            if viz_type == "target_search_table":
                try:
                    with open(plot_dir / f"{safe_viz_id}.json", "w", encoding="utf-8") as f:
                        _json.dump({k: viz[k] for k in viz if k != "id"}, f)
                    write_visualization_index(safe_viz_id, session_id, title)
                except Exception:
                    pass
                continue

            if viz_type == "predictive_results_table":
                try:
                    with open(plot_dir / f"{safe_viz_id}.json", "w", encoding="utf-8") as f:
                        _json.dump({k: viz[k] for k in viz if k != "id"}, f)
                    write_visualization_index(safe_viz_id, session_id, title)
                except Exception:
                    pass
                continue

            if viz_type == "tcga_cis_results_table":
                try:
                    with open(plot_dir / f"{safe_viz_id}.json", "w", encoding="utf-8") as f:
                        _json.dump({k: viz[k] for k in viz if k != "id"}, f)
                    write_visualization_index(safe_viz_id, session_id, title)
                except Exception:
                    pass
                continue

            if viz_type == "drug_target_grid":
                try:
                    with open(plot_dir / f"{safe_viz_id}.json", "w", encoding="utf-8") as f:
                        _json.dump({k: viz[k] for k in viz if k != "id"}, f)
                    write_visualization_index(safe_viz_id, session_id, title)
                except Exception:
                    pass
                continue

            if viz_type == "network_plot":
                # Persist nodes + edges in the JSON sidecar so the API can serve them
                try:
                    with open(plot_dir / f"{safe_viz_id}.json", "w", encoding="utf-8") as f:
                        _json.dump({
                            "type": "network_plot",
                            "title": title,
                            "nodes": viz.get("nodes", []),
                            "edges": viz.get("edges", []),
                        }, f)
                except Exception:
                    pass
                csv = viz.get("csv")
                if csv:
                    try:
                        with open(plot_dir / f"{safe_viz_id}.csv", "w", encoding="utf-8") as f:
                            f.write(csv)
                    except Exception:
                        pass
                try:
                    write_visualization_index(safe_viz_id, session_id, title)
                except Exception:
                    pass
                continue

            # static_plot
            if title:
                try:
                    with open(plot_dir / f"{safe_viz_id}.json", "w", encoding="utf-8") as f:
                        _json.dump({"title": title}, f)
                except Exception:
                    pass
            png = viz.get("png_b64")
            if png:
                try:
                    with open(plot_dir / f"{safe_viz_id}.png", "wb") as f:
                        f.write(_b64.b64decode(png))
                except Exception:
                    pass
            svg = viz.get("svg")
            if svg:
                try:
                    with open(plot_dir / f"{safe_viz_id}.svg", "w", encoding="utf-8") as f:
                        f.write(svg)
                except Exception:
                    pass
            csv = viz.get("csv")
            if csv:
                try:
                    with open(plot_dir / f"{safe_viz_id}.csv", "w", encoding="utf-8") as f:
                        f.write(csv)
                except Exception:
                    pass
            try:
                write_visualization_index(safe_viz_id, session_id, title)
            except Exception:
                pass

    @staticmethod
    def _extract_visualization_ids(response: Any) -> set[str]:
        """Collect static visualization IDs from a stored response payload."""
        viz_ids: set[str] = set()
        if not isinstance(response, dict):
            return viz_ids
        visualizations = response.get("visualizations") or []
        if not isinstance(visualizations, list):
            return viz_ids
        for viz in visualizations:
            if not isinstance(viz, dict):
                continue
            if viz.get("type") not in ("static_plot", "network_plot"):
                continue
            viz_id = viz.get("id")
            if isinstance(viz_id, str) and viz_id.strip():
                viz_ids.add(viz_id)
        return viz_ids

    @classmethod
    def _extract_visualization_ids_from_messages(cls, messages: List[Any]) -> set[str]:
        viz_ids: set[str] = set()
        for msg in messages or []:
            response = getattr(msg, "response", None)
            if response is None and isinstance(msg, dict):
                response = msg.get("response")
            viz_ids.update(cls._extract_visualization_ids(response))
        return viz_ids

    @staticmethod
    def _strip_viz_binary(response: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of response with visualization binary data removed.
        We keep viz metadata (type, id, title) so the frontend knows plots existed,
        but strip png_b64 / svg / csv / heavy grid data to keep the DB row small.
        Data is served on-demand from disk via /api/v1/chat/visualizations/{id}.
        """
        _STATIC_STRIP = frozenset(("png_b64", "svg", "csv", "nodes", "edges"))
        # Fields to strip from drug_target_grid (full data is in JSON sidecar on disk)
        _GRID_KEEP = frozenset(("id", "type", "title", "gene", "tier", "family"))
        # Fields to strip from target_search_table (genes array can be thousands of items)
        _TABLE_STRIP = frozenset(("genes",))

        vizs = response.get("visualizations")
        if not vizs:
            return response
        slim_vizs = []
        for viz in vizs:
            vt = viz.get("type")
            if vt == "drug_target_grid":
                slim_vizs.append({k: v for k, v in viz.items() if k in _GRID_KEEP})
            elif vt == "target_search_table":
                slim_vizs.append({k: v for k, v in viz.items() if k not in _TABLE_STRIP})
            else:
                slim_vizs.append({k: v for k, v in viz.items() if k not in _STATIC_STRIP})
        slim = dict(response)
        slim["visualizations"] = slim_vizs
        return slim

    async def _update_session(
        self,
        session: Dict[str, Any],
        query: str,
        response: Dict[str, Any]
    ) -> Optional[int]:
        """Update session with query and response. Guest sessions skip DB persistence."""
        import asyncio

        def _make_turn_summary(resp: dict, max_chars: int = 600) -> str:
            """Extract a compact summary for history context injection."""
            import re as _re
            content = resp.get("summary") or resp.get("message") or ""
            if not content or len(content) <= max_chars:
                return content
            parts = _re.split(r'(?<=[.!?])\s+', content.strip())
            short = " ".join(parts[:2]) if len(parts) >= 2 else parts[0]
            return (short + " [...]") if len(short) <= max_chars else content[:max_chars] + "..."

        context = session.setdefault("context", {})
        pending_offer = _extract_pending_offer_from_response(response)
        if pending_offer:
            context["pending_offer"] = pending_offer
        else:
            context.pop("pending_offer", None)

        # Guest sessions: update in-memory + record token usage to DB
        if session.get("user_id") == "guest":
            session.setdefault("history", []).append({
                "query": query,
                "response": response,
                "turn_summary": _make_turn_summary(response),
                "timestamp": time.time(),
            })
            session["last_updated"] = time.time()

            in_tok = response.get("_input_tokens", 0) or 0
            out_tok = response.get("_output_tokens", 0) or 0
            model_name = response.get("_model") or self._default_llm_model_name()
            if (in_tok or out_tok) and session.get("client_ip"):
                db = SessionLocal()
                try:
                    db.add(GuestTokenUsage(
                        ip_address=session["client_ip"],
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        model=model_name,
                        timestamp=time.time(),
                    ))
                    db.commit()
                finally:
                    db.close()
            return None

        if settings.DATABASE_URL.startswith("sqlite"):
            db = SessionLocal()
            session_id = session["id"]
            try:
                db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if db_session:
                    db_session.last_updated = time.time()
                    db_session.context = session.get("context", {})
                    
                    # Check if this is the first message (for title generation)
                    message_count = db.query(DBChatMessage).filter(
                        DBChatMessage.session_id == session_id
                    ).count()
                    is_first_message = message_count == 0
                    
                    # Persist plot files to disk, then strip binary from DB row
                    self._persist_viz_to_disk(response.get("visualizations") or [], session_id)
                    message = DBChatMessage(
                        session_id=session_id,
                        query=query,
                        response=self._strip_viz_binary(response),
                        timestamp=time.time()
                    )
                    db.add(message)
                    db.flush()
                    turn_id = message.id

                    # Record token usage if present (set by LangGraphOrchestrator)
                    in_tok = response.get("_input_tokens", 0) or 0
                    out_tok = response.get("_output_tokens", 0) or 0
                    model_name = response.get("_model") or self._default_llm_model_name()
                    if in_tok or out_tok:
                        if session.get("user_id") not in (None, "guest"):
                            db.add(TokenUsage(
                                user_id=session["user_id"],
                                session_id=session_id,
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                model=model_name,
                                timestamp=time.time(),
                            ))
                        elif session.get("client_ip"):
                            db.add(GuestTokenUsage(
                                ip_address=session["client_ip"],
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                model=model_name,
                                timestamp=time.time(),
                            ))

                    db.commit()

                    # Update in-memory session if it exists
                    if session_id in self.sessions:
                        self.sessions[session_id]["last_updated"] = db_session.last_updated
                        if "history" not in self.sessions[session_id]:
                            self.sessions[session_id]["history"] = []
                        self.sessions[session_id]["history"].append({
                            "id": turn_id,
                            "query": query,
                            "response": response,
                            "turn_summary": _make_turn_summary(response),
                            "timestamp": message.timestamp
                        })

                    # Generate title after first message
                    if is_first_message and db_session.title == "New Chat":
                        # Set a quick title immediately (truncated query) so the UI
                        # always shows something meaningful even if LLM refining fails.
                        quick_title = query[:50] + ("..." if len(query) > 50 else "")
                        db_session.title = quick_title
                        if session_id in self.sessions:
                            self.sessions[session_id]["title"] = quick_title
                        db.commit()
                        # Refine with LLM in background (skip when MOCK_LLM — would produce identical result)
                        if not settings.MOCK_LLM:
                            asyncio.create_task(self._update_session_title(session_id, query))
                    return turn_id
            finally:
                db.close()
        else:
            # PostgreSQL async
            async with SessionLocal() as db:
                session_id = session["id"]
                result = await db.execute(
                    select(ChatSession).filter(ChatSession.id == session_id)
                )
                db_session = result.scalar_one_or_none()
                if db_session:
                    db_session.last_updated = time.time()
                    db_session.context = session.get("context", {})
                    
                    # Check if this is the first message
                    msg_count_result = await db.execute(
                        select(DBChatMessage).filter(DBChatMessage.session_id == session_id)
                    )
                    message_count = len(msg_count_result.scalars().all())
                    is_first_message = message_count == 0
                    
                    # Persist plot files to disk, then strip binary from DB row
                    self._persist_viz_to_disk(response.get("visualizations") or [], session_id)
                    message = DBChatMessage(
                        session_id=session_id,
                        query=query,
                        response=self._strip_viz_binary(response),
                        timestamp=time.time()
                    )
                    db.add(message)
                    await db.flush()
                    turn_id = message.id

                    # Record token usage if present (set by LangGraphOrchestrator)
                    in_tok = response.get("_input_tokens", 0) or 0
                    out_tok = response.get("_output_tokens", 0) or 0
                    model_name = response.get("_model") or self._default_llm_model_name()
                    if in_tok or out_tok:
                        if session.get("user_id") not in (None, "guest"):
                            db.add(TokenUsage(
                                user_id=session["user_id"],
                                session_id=session_id,
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                model=model_name,
                                timestamp=time.time(),
                            ))
                        elif session.get("client_ip"):
                            db.add(GuestTokenUsage(
                                ip_address=session["client_ip"],
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                model=model_name,
                                timestamp=time.time(),
                            ))

                    await db.commit()

                    # Update in-memory session if it exists
                    if session_id in self.sessions:
                        self.sessions[session_id]["last_updated"] = db_session.last_updated
                        if "history" not in self.sessions[session_id]:
                            self.sessions[session_id]["history"] = []
                        self.sessions[session_id]["history"].append({
                            "id": turn_id,
                            "query": query,
                            "response": response,
                            "turn_summary": _make_turn_summary(response),
                            "timestamp": message.timestamp
                        })

                    # Generate title after first message
                    if is_first_message and db_session.title == "New Chat":
                        # Set a quick title immediately (truncated query) so the UI
                        # always shows something meaningful even if LLM refining fails.
                        quick_title = query[:50] + ("..." if len(query) > 50 else "")
                        db_session.title = quick_title
                        if session_id in self.sessions:
                            self.sessions[session_id]["title"] = quick_title
                        await db.commit()
                        # Refine with LLM in background (skip when MOCK_LLM — would produce identical result)
                        if not settings.MOCK_LLM:
                            asyncio.create_task(self._update_session_title(session_id, query))
                    return turn_id
        return None
    
    async def _update_session_title(self, session_id: str, first_query: str):
        """Async task to generate and update session title"""
        try:
            logger.info(f"Generating title for session {session_id} from query: {first_query[:50]}")
            title = await self._generate_session_title(first_query)
            
            # Update in memory cache if exists
            if session_id in self.sessions:
                self.sessions[session_id]["title"] = title
            
            # Update in database
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if db_session:
                        db_session.title = title
                        db.commit()
                        logger.info(f"✅ Generated title for session {session_id}: {title}")
                finally:
                    db.close()
            else:
                # PostgreSQL async
                async with SessionLocal() as db:
                    result = await db.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    db_session = result.scalar_one_or_none()
                    if db_session:
                        db_session.title = title
                        await db.commit()
                        logger.info(f"✅ Generated title for session {session_id}: {title}")
        except Exception as e:
            logger.error(f"Error updating session title: {e}", exc_info=True)
            # Fallback to truncated query
            fallback_title = first_query[:50] + ("..." if len(first_query) > 50 else "")
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if db_session:
                        db_session.title = fallback_title
                        db.commit()
                finally:
                    db.close()
            else:
                async with SessionLocal() as db:
                    result = await db.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    db_session = result.scalar_one_or_none()
                    if db_session:
                        db_session.title = fallback_title
                        await db.commit()
    
    async def _load_all_sessions_from_db(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Load all sessions from database, optionally filtered by user_id"""
        from typing import List
        from sqlalchemy import func
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                # SQLite uses sync session
                db = SessionLocal()
                try:
                    q = db.query(ChatSession)
                    if user_id:
                        q = q.filter(ChatSession.user_id == user_id)
                    db_sessions = q.all()

                    # Single GROUP BY query for all message counts — avoids N+1
                    session_ids = [s.id for s in db_sessions]
                    counts: dict = {}
                    if session_ids:
                        counts = dict(
                            db.query(DBChatMessage.session_id, func.count(DBChatMessage.id))
                            .filter(DBChatMessage.session_id.in_(session_ids))
                            .group_by(DBChatMessage.session_id)
                            .all()
                        )

                    return [
                        {
                            "id": s.id,
                            "user_id": s.user_id,
                            "title": s.title,
                            "created_at": s.created_at,
                            "last_updated": s.last_updated,
                            "message_count": counts.get(s.id, 0),
                        }
                        for s in db_sessions
                    ]
                finally:
                    db.close()
            else:
                # PostgreSQL uses async session
                async with SessionLocal() as db:
                    q = select(ChatSession)
                    if user_id:
                        q = q.filter(ChatSession.user_id == user_id)
                    result = await db.execute(q)
                    db_sessions = result.scalars().all()

                    # Single GROUP BY query for all message counts — avoids N+1
                    session_ids = [s.id for s in db_sessions]
                    counts: dict = {}
                    if session_ids:
                        counts_result = await db.execute(
                            select(DBChatMessage.session_id, func.count(DBChatMessage.id))
                            .filter(DBChatMessage.session_id.in_(session_ids))
                            .group_by(DBChatMessage.session_id)
                        )
                        counts = dict(counts_result.all())

                    return [
                        {
                            "id": s.id,
                            "user_id": s.user_id,
                            "title": s.title,
                            "created_at": s.created_at,
                            "last_updated": s.last_updated,
                            "message_count": counts.get(s.id, 0),
                        }
                        for s in db_sessions
                    ]
        except Exception as e:
            logger.error(f"Error loading sessions from database: {e}")
            return []
    
    async def _load_session_from_db(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load a session from database"""
        def _sanitize_large_inline_images(resp: Any) -> Any:
            """
            Prevent huge stored responses (data URLs / raw_results base64) from freezing the UI.

            If a response contains a markdown image with a very large data:image/... URL,
            replace it with a short placeholder so the frontend stays responsive.
            """
            try:
                if not isinstance(resp, dict):
                    return resp

                msg = resp.get("message")
                if not isinstance(msg, str):
                    msg = ""

                import re
                import json

                new_resp = dict(resp)

                # Always drop heavy fields that the chat UI doesn't need for history rendering.
                # Keeping these can make some sessions too large to load smoothly.
                new_resp.pop("raw_results", None)
                # Record presence before stripping so the frontend can lazy-fetch
                new_resp["has_visualizations"] = bool(new_resp.get("visualizations"))
                new_resp.pop("visualizations", None)

                # 1) Only sanitize inline data URLs if they're large.
                # Small inline plots (tens of KB) should render fine and are useful in chat history.
                if "data:image" in msg and len(msg) > 200_000:
                    msg_sanitized = re.sub(
                        r"!\[[^\]]*\]\(data:image/[^)]+\)",
                        "_(Plot omitted for performance — please re-run the plot query to regenerate it.)_",
                        msg,
                        flags=re.IGNORECASE,
                    )
                    new_resp["message"] = msg_sanitized
                    if "summary" in new_resp and isinstance(new_resp.get("summary"), str):
                        new_resp["summary"] = msg_sanitized

                # 2) If the overall stored response is still huge, drop heavy fields (raw_results, etc.)
                try:
                    approx_size = len(json.dumps(new_resp, default=str))
                except Exception:
                    approx_size = 0

                if approx_size > 200_000:
                    # Keep only what the UI needs to render history.
                    keep_keys = {"success", "summary", "message", "query", "tools_used"}
                    compact = {k: new_resp.get(k) for k in keep_keys if k in new_resp}
                    # Preserve minimal structure expected elsewhere
                    compact.setdefault("success", True)
                    # Prefer already-sanitized message if present
                    compact.setdefault("message", new_resp.get("message", msg) or "")
                    compact.setdefault("summary", new_resp.get("summary", compact.get("message", "")))
                    compact["__note__"] = "Large fields omitted from history for performance."
                    return compact

                return new_resp
            except Exception:
                return resp

        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                # SQLite uses sync session
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if not db_session:
                        return None
                    
                    # Load messages
                    messages = db.query(DBChatMessage).filter(
                        DBChatMessage.session_id == session_id
                    ).order_by(DBChatMessage.timestamp).all()
                    
                    history = [
                        {
                            "id": msg.id,
                            "query": msg.query,
                            "response": _sanitize_large_inline_images(msg.response),
                            "timestamp": msg.timestamp
                        }
                        for msg in messages
                    ]
                    
                    session = {
                        "id": db_session.id,
                        "user_id": db_session.user_id,
                        "title": db_session.title,
                        "history": history,
                        "context": db_session.context or {},
                        "created_at": db_session.created_at,
                        "last_updated": db_session.last_updated
                    }
                    
                    return session
                finally:
                    db.close()
            else:
                # PostgreSQL uses async session
                async with SessionLocal() as db:
                    result = await db.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    db_session = result.scalar_one_or_none()
                    if not db_session:
                        return None
                    
                    # Load messages
                    messages_result = await db.execute(
                        select(DBChatMessage)
                        .filter(DBChatMessage.session_id == session_id)
                        .order_by(DBChatMessage.timestamp)
                    )
                    messages = messages_result.scalars().all()
                    
                    history = [
                        {
                            "id": msg.id,
                            "query": msg.query,
                            "response": _sanitize_large_inline_images(msg.response),
                            "timestamp": msg.timestamp
                        }
                        for msg in messages
                    ]
                    
                    session = {
                        "id": db_session.id,
                        "user_id": db_session.user_id,
                        "title": db_session.title,
                        "history": history,
                        "context": db_session.context or {},
                        "created_at": db_session.created_at,
                        "last_updated": db_session.last_updated
                    }
                    
                    return session
        except Exception as e:
            logger.error(f"Error loading session from database: {e}")
            return None

    def _derive_active_gene_from_db_messages(self, messages: List[DBChatMessage]) -> Optional[str]:
        """Best-effort reconstruction of active_gene from persisted turns."""
        for msg in reversed(messages):
            resp = msg.response if isinstance(msg.response, dict) else {}
            raw_results = resp.get("raw_results") if isinstance(resp, dict) else None
            if isinstance(raw_results, dict):
                for wrapped in reversed(list(raw_results.values())):
                    if not isinstance(wrapped, dict):
                        continue
                    gene = wrapped.get("_gene")
                    if isinstance(gene, str) and gene.strip():
                        return gene.upper()

                    args = wrapped.get("_args") or {}
                    if isinstance(args, dict):
                        gene = args.get("protein") or args.get("gene_symbol") or args.get("gene")
                        if isinstance(gene, str) and gene.strip():
                            return gene.upper()
                        proteins = args.get("proteins")
                        if isinstance(proteins, list) and proteins:
                            first = proteins[0]
                            if isinstance(first, str) and first.strip():
                                return first.upper()

            genes = self._extract_gene_symbols(msg.query or "")
            if genes:
                return genes[0]

        return None

    def _derive_pending_offer_from_db_messages(self, messages: List[DBChatMessage]) -> Optional[str]:
        """Best-effort reconstruction of the latest conversational follow-up offer."""
        for msg in reversed(messages):
            resp = msg.response if isinstance(msg.response, dict) else {}
            offer = _extract_pending_offer_from_response(resp)
            if offer:
                return offer
        return None

    def _derive_session_context_from_db_messages(self, messages: List[DBChatMessage]) -> Dict[str, Any]:
        """Rebuild persisted session context from the remaining turns."""
        context: Dict[str, Any] = {}
        active_gene = self._derive_active_gene_from_db_messages(messages)
        if active_gene:
            context["active_gene"] = active_gene
        pending_offer = self._derive_pending_offer_from_db_messages(messages)
        if pending_offer:
            context["pending_offer"] = pending_offer
        return context

    async def _truncate_session_from_message(self, session_id: str, message_id: int) -> Dict[str, int]:
        """Delete the specified turn and all later turns, then rebuild session context."""
        deleted_turns = 0
        remaining_turns = 0
        removed_viz_ids: set[str] = set()
        now = time.time()

        if settings.DATABASE_URL.startswith("sqlite"):
            db = SessionLocal()
            try:
                db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if not db_session:
                    raise ValueError("Session not found")

                target = (
                    db.query(DBChatMessage)
                    .filter(DBChatMessage.session_id == session_id, DBChatMessage.id == message_id)
                    .first()
                )
                if not target:
                    raise ValueError("Turn not found in this session")

                remaining_messages = (
                    db.query(DBChatMessage)
                    .filter(DBChatMessage.session_id == session_id, DBChatMessage.id < message_id)
                    .order_by(DBChatMessage.timestamp.asc(), DBChatMessage.id.asc())
                    .all()
                )
                deleted_messages = (
                    db.query(DBChatMessage)
                    .filter(DBChatMessage.session_id == session_id, DBChatMessage.id >= message_id)
                    .order_by(DBChatMessage.timestamp.asc(), DBChatMessage.id.asc())
                    .all()
                )

                # Compute viz IDs before the bulk delete (instances become inaccessible after)
                removed_viz_ids = (
                    self._extract_visualization_ids_from_messages(deleted_messages)
                    - self._extract_visualization_ids_from_messages(remaining_messages)
                )

                deleted_turns = (
                    db.query(DBChatMessage)
                    .filter(DBChatMessage.session_id == session_id, DBChatMessage.id >= message_id)
                    .delete(synchronize_session=False)
                )

                db_session.context = self._derive_session_context_from_db_messages(remaining_messages)
                db_session.last_updated = now
                if not remaining_messages:
                    db_session.title = "New Chat"

                db.commit()
                remaining_turns = len(remaining_messages)
            finally:
                db.close()
        else:
            async with SessionLocal() as db:
                result = await db.execute(
                    select(ChatSession).filter(ChatSession.id == session_id)
                )
                db_session = result.scalar_one_or_none()
                if not db_session:
                    raise ValueError("Session not found")

                result = await db.execute(
                    select(DBChatMessage).filter(
                        DBChatMessage.session_id == session_id,
                        DBChatMessage.id == message_id,
                    )
                )
                target = result.scalar_one_or_none()
                if not target:
                    raise ValueError("Turn not found in this session")

                result = await db.execute(
                    select(DBChatMessage)
                    .filter(DBChatMessage.session_id == session_id, DBChatMessage.id < message_id)
                    .order_by(DBChatMessage.timestamp.asc(), DBChatMessage.id.asc())
                )
                remaining_messages = list(result.scalars().all())
                result = await db.execute(
                    select(DBChatMessage)
                    .filter(DBChatMessage.session_id == session_id, DBChatMessage.id >= message_id)
                    .order_by(DBChatMessage.timestamp.asc(), DBChatMessage.id.asc())
                )
                deleted_messages = list(result.scalars().all())

                # Compute viz IDs BEFORE the bulk delete. SQLAlchemy's default
                # synchronize_session="evaluate" marks matching ORM instances as
                # "deleted" after the DELETE executes, making .response inaccessible.
                removed_viz_ids = (
                    self._extract_visualization_ids_from_messages(deleted_messages)
                    - self._extract_visualization_ids_from_messages(remaining_messages)
                )

                delete_result = await db.execute(
                    delete(DBChatMessage).where(
                        DBChatMessage.session_id == session_id,
                        DBChatMessage.id >= message_id,
                    )
                )
                deleted_turns = delete_result.rowcount or 0

                db_session.context = self._derive_session_context_from_db_messages(remaining_messages)
                db_session.last_updated = now
                if not remaining_messages:
                    db_session.title = "New Chat"

                await db.commit()
                remaining_turns = len(remaining_messages)

        for viz_id in removed_viz_ids:
            delete_visualization_artifacts(viz_id)

        return {
            "deleted_turns": deleted_turns,
            "remaining_turns": remaining_turns,
        }
    
    def _save_session_to_db(self, session: Dict[str, Any]):
        """Save session to database (sync for SQLite compatibility)"""
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session["id"]).first()
                    if db_session:
                        db_session.title = session.get("title", "New Chat")
                        db_session.last_updated = session.get("last_updated", time.time())
                        db_session.context = session.get("context", {})
                    else:
                        db_session = ChatSession(
                            id=session["id"],
                            user_id=session["user_id"],
                            title=session.get("title", "New Chat"),
                            created_at=session.get("created_at", time.time()),
                            last_updated=session.get("last_updated", time.time()),
                            context=session.get("context", {})
                        )
                        db.add(db_session)
                    db.commit()
                finally:
                    db.close()
            else:
                # For PostgreSQL, use async (but this is a sync method for compatibility)
                import asyncio
                asyncio.create_task(self._save_session_to_db_async(session))
        except Exception as e:
            logger.error(f"Error saving session to database: {e}")
    
    async def _save_session_to_db_async(self, session: Dict[str, Any]):
        """Async version for PostgreSQL"""
        try:
            async with SessionLocal() as db:
                result = await db.execute(
                    select(ChatSession).filter(ChatSession.id == session["id"])
                )
                db_session = result.scalar_one_or_none()
                
                if db_session:
                    db_session.title = session.get("title", "New Chat")
                    db_session.last_updated = session.get("last_updated", time.time())
                    db_session.context = session.get("context", {})
                else:
                    db_session = ChatSession(
                        id=session["id"],
                        user_id=session["user_id"],
                        title=session.get("title", "New Chat"),
                        created_at=session.get("created_at", time.time()),
                        last_updated=session.get("last_updated", time.time()),
                        context=session.get("context", {})
                    )
                    db.add(db_session)
                await db.commit()
        except Exception as e:
            logger.error(f"Error saving session to database (async): {e}")
    
    async def _delete_session_from_db(self, session_id: str):
        """Delete session from database"""
        try:
            viz_ids: set[str] = set()
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    messages = db.query(DBChatMessage).filter(DBChatMessage.session_id == session_id).all()
                    viz_ids = self._extract_visualization_ids_from_messages(messages)
                    # Delete messages first
                    db.query(DBChatMessage).filter(DBChatMessage.session_id == session_id).delete()
                    # Delete session
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if db_session:
                        db.delete(db_session)
                    db.commit()
                finally:
                    db.close()
            else:
                # PostgreSQL async
                async with SessionLocal() as db:
                    result = await db.execute(
                        select(DBChatMessage).filter(DBChatMessage.session_id == session_id)
                    )
                    messages = list(result.scalars().all())
                    viz_ids = self._extract_visualization_ids_from_messages(messages)
                    # Delete messages first, then the session row.
                    await db.execute(
                        delete(DBChatMessage).where(DBChatMessage.session_id == session_id)
                    )
                    result = await db.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    db_session = result.scalar_one_or_none()
                    if db_session:
                        await db.delete(db_session)
                    await db.commit()
            for viz_id in viz_ids:
                delete_visualization_artifacts(viz_id)
            delete_session_workspace(session_id)
        except Exception as e:
            logger.error(f"Error deleting session from database: {e}")
