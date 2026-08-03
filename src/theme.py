"""CSS design-token helpers for FXCorrMonitor."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STYLES_CSS_PATH = PROJECT_ROOT / "app" / "styles.css"

_CSS_VAR_RE = re.compile(r"--(fx-[\w-]+)\s*:\s*([^;]+);")


def load_css_vars(path: Path | None = None) -> dict[str, str]:
    css_path = path or STYLES_CSS_PATH
    if not css_path.exists():
        return {}
    text = css_path.read_text(encoding="utf-8")
    return {m.group(1): m.group(2).strip() for m in _CSS_VAR_RE.finditer(text)}


def read_styles_css(path: Path | None = None) -> str:
    css_path = path or STYLES_CSS_PATH
    if not css_path.exists():
        return ""
    return css_path.read_text(encoding="utf-8")
