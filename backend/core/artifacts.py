"""
Helpers for session-scoped artifact storage.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Optional

from core.config import settings


def _safe_path_token(value: str) -> str:
    base = os.path.basename((value or "").strip())
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return safe or "unknown"


def artifact_root() -> Path:
    root = Path(settings.ARTIFACT_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_workspace_dir(session_id: str) -> Path:
    return artifact_root() / "sessions" / _safe_path_token(session_id)


def ensure_session_workspace(session_id: str) -> Path:
    root = session_workspace_dir(session_id)
    for subdir in ("plots", "exports", "attachments", "cache"):
        (root / subdir).mkdir(parents=True, exist_ok=True)
    return root


def session_plot_dir(session_id: str) -> Path:
    return ensure_session_workspace(session_id) / "plots"


def visualization_index_dir() -> Path:
    root = artifact_root() / "visualization_index"
    root.mkdir(parents=True, exist_ok=True)
    return root


def visualization_index_path(viz_id: str) -> Path:
    return visualization_index_dir() / f"{_safe_path_token(viz_id)}.json"


def write_visualization_index(viz_id: str, session_id: str, title: str = "") -> None:
    idx_path = visualization_index_path(viz_id)
    payload = {
        "viz_id": _safe_path_token(viz_id),
        "session_id": _safe_path_token(session_id),
        "title": title or "",
        "plot_dir": str(session_plot_dir(session_id)),
    }
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def resolve_visualization_paths(viz_id: str) -> Optional[Dict[str, Path]]:
    safe_id = _safe_path_token(viz_id)
    idx_path = visualization_index_path(safe_id)
    if idx_path.exists():
        try:
            with open(idx_path, encoding="utf-8") as f:
                payload = json.load(f)
            session_id = payload.get("session_id") or ""
            if session_id:
                base = session_plot_dir(session_id) / safe_id
                return {
                    "png": base.with_suffix(".png"),
                    "svg": base.with_suffix(".svg"),
                    "csv": base.with_suffix(".csv"),
                    "json": base.with_suffix(".json"),
                    "index": idx_path,
                }
        except Exception:
            pass

    legacy_base = Path(settings.PLOT_DIR) / safe_id
    legacy_paths = {
        "png": legacy_base.with_suffix(".png"),
        "svg": legacy_base.with_suffix(".svg"),
        "csv": legacy_base.with_suffix(".csv"),
        "json": legacy_base.with_suffix(".json"),
        "index": idx_path,
    }
    if any(path.exists() for key, path in legacy_paths.items() if key != "index"):
        return legacy_paths
    return None


def delete_visualization_artifacts(viz_id: str) -> None:
    paths = resolve_visualization_paths(viz_id)
    if not paths:
        return
    for key in ("png", "svg", "csv", "json", "index"):
        path = paths.get(key)
        if not path:
            continue
        try:
            if path.exists():
                path.unlink()
        except FileNotFoundError:
            pass


def delete_session_workspace(session_id: str) -> None:
    workspace = session_workspace_dir(session_id)
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)

    safe_session_id = _safe_path_token(session_id)
    index_dir = visualization_index_dir()
    for idx_path in index_dir.glob("*.json"):
        try:
            with open(idx_path, encoding="utf-8") as f:
                payload = json.load(f)
            if payload.get("session_id") == safe_session_id:
                idx_path.unlink()
        except Exception:
            continue
