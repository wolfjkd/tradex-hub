#!/usr/bin/env python
"""生成 docs/MCP_TOOLS.md —— MCP 工具清单（真源 = 源码 AST，不手工维护）。

背景：README 第 245 行引用 `docs/MCP_TOOLS.md`，但该文件历史上从未落盘
（2026-10-20 发现断链）。本脚本按项目既定原则「文档由代码派生」补齐，
工具增删后重跑即可，避免清单与实现漂移。

真源与判定规则
--------------
1. 只统计 `tradex/src/tradex/tools/*.py` 中**带 `@mcp.tool` 装饰器**的函数
   —— 与 tools/registry.py 的 `register(mcp)` 函数轨一致（装饰器轨会静默
   丢工具，已废弃，故不纳入统计）。
2. 每个工具的说明取 docstring 首句；若首行以逗号/顿号等续行标点结尾，
   继续拼接下一行至句末（避免"……量能序列，"这类截断）。
3. 模块与领域的分组关系写在 `MODULE_GROUPS` 里；出现未登记的模块直接抛错
   —— 强制新增工具模块时同步更新本表，防止清单悄悄漏项。

用法
----
    python scripts/generate_tool_docs.py            # 重新生成
    python scripts/generate_tool_docs.py --check     # 只校验，不写文件
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tradex" / "src" / "tradex" / "tools"
OUT_PATH = REPO_ROOT / "docs" / "MCP_TOOLS.md"

# 模块 → (层级, 领域名, 排序键)。层级用于分组展示顺序。
MODULE_GROUPS: dict[str, tuple[str, str, int]] = {
    # ---- L1 数据获取层 ----
    "company_info.py": ("L1 数据获取", "公司信息", 100),
    "price_data.py": ("L1 数据获取", "价格行情", 110),
    "industry.py": ("L1 数据获取", "板块行业", 120),
    "financial_stmt.py": ("L1 数据获取", "财务数据", 130),
    "valuation.py": ("L1 数据获取", "估值与持仓", 140),
    "news_events.py": ("L1 数据获取", "新闻公告", 150),
    "market.py": ("L1 数据获取", "市场总览与资金", 160),
    "macro_fx.py": ("L1 数据获取", "宏观与两融", 170),
    "macro_official.py": ("L1 数据获取", "宏观官方源（统计局 / 中债）", 180),
    "signal_data_base.py": ("L1 数据获取", "信号数据 · 基础", 200),
    "signal_data_flow.py": ("L1 数据获取", "信号数据 · 资金流与龙虎榜", 210),
    "signal_data_board.py": ("L1 数据获取", "信号数据 · 涨停板与情绪", 220),
    "signal_data_etf.py": ("L1 数据获取", "信号数据 · ETF", 230),
    "signal_data_cb.py": ("L1 数据获取", "信号数据 · 可转债", 240),
    "eltdx_data.py": ("L1 数据获取", "eltdx 通达信协议专有", 300),
    "local_data.py": ("L1 数据获取", "本地数据（通达信盘后文件）", 310),
    "tdx_mcp.py": ("L1 数据获取", "通达信官方 MCP（tdx_mcp）", 320),
    "tdx_tq.py": ("L1 数据获取", "通达信 TQ 本地源", 330),
    "backup_source_tools.py": ("L1 数据获取", "独立备源（新浪 / 百度 / baostock）", 400),
    "exchange_official.py": ("L1 数据获取", "交易所与巨潮官方", 410),
    "event_driven.py": ("L1 数据获取", "事件驱动（东财 datacenter）", 420),
    "global_market_news.py": ("L1 数据获取", "全球资讯与宏观日历", 430),
    "industry_news.py": ("L1 数据获取", "产业链资讯（106 源）", 440),
    "sw_industry_history.py": ("L1 数据获取", "申万行业变迁史", 450),
    # ---- L2 计算引擎层 ----
    "technical_indicators.py": ("L2 计算引擎", "技术指标计算", 500),
    "performance_metrics.py": ("L2 计算引擎", "绩效指标", 510),
    # ---- L3 决策支持层 ----
    "signal_generation.py": ("L3 决策支持", "交易信号生成", 600),
    "factor_analysis.py": ("L3 决策支持", "多因子分析", 610),
    "stock_screening.py": ("L3 决策支持", "条件选股", 620),
    "composite_analysis.py": ("L3 决策支持", "综合分析", 630),
    "analysis_engine.py": ("L3 决策支持", "技术分析引擎", 640),
    # ---- 系统诊断 ----
    "diagnostics.py": ("系统诊断", "健康检查与可观测性", 900),
}

_SENTENCE_END = "。！？.!?"
_CONTINUE_END = "，,、：:；;（("


@dataclass(frozen=True)
class ToolEntry:
    name: str
    module: str
    summary: str


def _is_mcp_tool(node: ast.AST) -> bool:
    """判断函数是否带 @mcp.tool(...) 装饰器。"""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr == "tool":
            if isinstance(target.value, ast.Name) and target.value.id == "mcp":
                return True
    return False


def _summarize(doc: str | None, limit: int = 90) -> str:
    """取 docstring 首句；遇续行标点则续拼下一行，超长截断。"""
    if not doc:
        return "—"
    lines = [ln.strip() for ln in doc.strip().splitlines() if ln.strip()]
    if not lines:
        return "—"
    text = lines[0]
    idx = 1
    while idx < len(lines) and text and text[-1] in _CONTINUE_END and len(text) < limit:
        text += lines[idx].rstrip("，,、：:；;")
        idx += 1
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text.replace("|", "\\|")


def collect_tools() -> list[ToolEntry]:
    """扫描 tools/*.py，返回按（领域排序键, 模块名, 工具名）排序的工具清单。"""
    entries: list[ToolEntry] = []
    unmapped: list[str] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found = [
            ToolEntry(name=node.name, module=path.name, summary=_summarize(ast.get_docstring(node)))
            for node in ast.walk(tree)
            if _is_mcp_tool(node)
        ]
        if found and path.name not in MODULE_GROUPS:
            unmapped.append(path.name)
        entries.extend(found)
    if unmapped:
        raise SystemExit(
            "以下工具模块未登记到 MODULE_GROUPS，请先补领域归属再生成：\n  - "
            + "\n  - ".join(unmapped)
        )
    if not entries:
        raise SystemExit(f"未在 {TOOLS_DIR} 发现任何 @mcp.tool 装饰的函数")
    entries.sort(key=lambda e: (MODULE_GROUPS[e.module][2], e.name))
    names = [e.name for e in entries]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise SystemExit(f"检测到工具重名（会静默覆盖）：{sorted(dupes)}")
    return entries


def render(entries: list[ToolEntry]) -> str:
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    total = len(entries)

    by_layer: dict[str, list[ToolEntry]] = {}
    for entry in entries:
        by_layer.setdefault(MODULE_GROUPS[entry.module][0], []).append(entry)

    out: list[str] = [
        "# MCP 工具清单",
        "",
        f"> 本文件由 `scripts/generate_tool_docs.py` 从源码 AST 生成（`tradex/src/tradex/tools/*.py`",
        f"> 中带 `@mcp.tool` 装饰器的函数），**请勿手工编辑**。当前版本 **v{version}**，共 **{total} 个工具**。",
        "> 工具增删后重跑脚本即可：`python scripts/generate_tool_docs.py`。",
        "",
        "## 总览",
        "",
        "| 层级 | 工具数 |",
        "|------|--------|",
    ]
    for layer, items in by_layer.items():
        out.append(f"| {layer} | {len(items)} |")
    out.append(f"| **合计** | **{total}** |")
    out.append("")

    for layer, items in by_layer.items():
        out.append(f"## {layer}（{len(items)} 个）")
        out.append("")
        grouped: dict[str, list[ToolEntry]] = {}
        for entry in items:
            grouped.setdefault(MODULE_GROUPS[entry.module][1], []).append(entry)
        for domain, domain_items in grouped.items():
            out.append(f"### {domain}（{len(domain_items)} 个）")
            out.append("")
            out.append("| 工具 | 说明 |")
            out.append("|------|------|")
            for entry in domain_items:
                out.append(f"| `{entry.name}` | {entry.summary} |")
            out.append("")

    out.append("---")
    out.append("")
    out.append("工具调用方式见 [README.md](../README.md#mcp-工具清单168-个)。")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 docs/MCP_TOOLS.md")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()

    entries = collect_tools()
    content = render(entries)

    if args.check:
        if not OUT_PATH.exists():
            print(f"[FAIL] {OUT_PATH} 不存在")
            return 1
        if OUT_PATH.read_text(encoding="utf-8") != content:
            print("[FAIL] docs/MCP_TOOLS.md 与源码不一致，请重新生成")
            return 1
        print(f"[OK] {len(entries)} 个工具，文档与源码一致")
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(content, encoding="utf-8", newline="\n")
    print(f"[OK] 已写入 {OUT_PATH.relative_to(REPO_ROOT)}：{len(entries)} 个工具")
    return 0


if __name__ == "__main__":
    sys.exit(main())
