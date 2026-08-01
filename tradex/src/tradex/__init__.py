"""tradex: China Financial Data MCP Server based on AKShare."""

from pathlib import Path


def _read_version() -> str:
    """从项目根目录的 VERSION 文件读取版本号(单一事实来源)。"""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        version_file = parent / "VERSION"
        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


__version__ = _read_version()
