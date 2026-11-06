#!/usr/bin/env python
"""生成 docs/SHORTLINE_ENDPOINTS.md —— 短线端点 CATALOG（工单 H1）。

真源 = `tradex/src/tradex/shortline/meta.py` 的声明；本脚本只做渲染 + 落盘。
幂等：内容不变不重写。

用法
----
    python scripts/gen_shortline_catalog.py            # 生成/更新
    python scripts/gen_shortline_catalog.py --check    # 只校验，不写文件（CI 用）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "tradex" / "src"
OUT_PATH = REPO_ROOT / "docs" / "SHORTLINE_ENDPOINTS.md"

sys.path.insert(0, str(SRC))

from tradex.shortline.catalog import (  # noqa: E402
    build_catalog,
    render_markdown,
    validate_registry,
    write_catalog,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成短线端点 CATALOG")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()

    problems = validate_registry()
    if problems:
        print("声明校验失败：")
        for item in problems:
            print(f"  - {item}")
        return 1

    if args.check:
        expected = render_markdown(build_catalog(include_generated_at=False))
        if not OUT_PATH.is_file():
            print(f"CATALOG 不存在：{OUT_PATH}")
            return 1
        if OUT_PATH.read_text(encoding="utf-8") != expected:
            print(f"CATALOG 与声明不一致：{OUT_PATH}")
            return 1
        print("CATALOG 已是最新")
        return 0

    changed = write_catalog(OUT_PATH)
    catalog = build_catalog(include_generated_at=False)
    print(f"{'已更新' if changed else '未变化'}: {OUT_PATH}（{catalog['count']} 个端点）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
