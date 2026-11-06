"""短线端点 CATALOG 生成（工单 H1）。

三个消费者共用同一份声明：
  - MCP 工具 ``get_shortline_catalog``
  - REST ``GET /api/v1/shortline/catalog``
  - 文档 ``docs/SHORTLINE_ENDPOINTS.md``（由 scripts/gen_shortline_catalog.py 生成）

幂等要求：文档内容只由声明决定（不含时间戳），内容不变就不重写文件。
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .meta import CACHE_POLICIES, SHORTLINE_ENDPOINTS, validate_registry

CATALOG_SCHEMA_VERSION = "1.0"


def build_catalog(*, include_generated_at: bool = True) -> dict[str, Any]:
    """构造 CATALOG 结构（按 id 排序，保证可复现）。"""
    problems = validate_registry()
    catalog: dict[str, Any] = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "count": len(SHORTLINE_ENDPOINTS),
        "cache_policies": {
            name: {
                "ttl_seconds": policy.ttl_seconds,
                "file_cache": policy.file_cache,
                "cache_partial": policy.cache_partial,
                "description": policy.description,
            }
            for name, policy in sorted(CACHE_POLICIES.items())
        },
        "endpoints": [
            SHORTLINE_ENDPOINTS[key].to_dict()
            for key in sorted(SHORTLINE_ENDPOINTS)
        ],
        "validation": {"ok": not problems, "problems": problems},
    }
    if include_generated_at:
        catalog["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return catalog


def render_markdown(catalog: dict[str, Any] | None = None) -> str:
    """把 CATALOG 渲染成 Markdown 文档（内容确定性，可直接做幂等比对）。"""
    data = catalog or build_catalog(include_generated_at=False)
    lines = [
        "# 短线端点 CATALOG",
        "",
        "> 本文件由 `scripts/gen_shortline_catalog.py` 依据 "
        "`tradex.shortline.meta` 声明生成，请勿手改。",
        "",
        f"- schema_version: **{data['schema_version']}**",
        f"- 端点数量: **{data['count']}**",
        f"- 声明校验: {'全绿' if data['validation']['ok'] else '有问题'}",
        "",
        "| 端点 id | 标题 | 阶段 | 缓存策略 | 来源 | 合规 | MCP 工具 | REST 路径 | 状态 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for endpoint in data["endpoints"]:
        cache = endpoint["cache"]
        cache_text = (
            f"{endpoint['cache_policy']}（{cache['ttl_seconds']}s）"
            if cache["ttl_seconds"] is not None
            else f"{endpoint['cache_policy']}（不缓存）"
        )
        lines.append(
            "| {id} | {title} | {phase} | {cache} | {source} | {compliance} | "
            "{mcp_tool} | {rest_path} | {status} |".format(
                id=endpoint["id"],
                title=endpoint["title"],
                phase=endpoint["phase"],
                cache=cache_text,
                source=endpoint["source"],
                compliance=endpoint["compliance"],
                mcp_tool=endpoint["mcp_tool"],
                rest_path=endpoint["rest_path"],
                status=endpoint["status"],
            )
        )

    lines += ["", "## 口径说明", ""]
    for endpoint in data["endpoints"]:
        lines.append(f"### `{endpoint['id']}` — {endpoint['title']}")
        lines.append("")
        lines.append(endpoint["description"])
        lines.append("")
        lines.append(
            "- 参数：{params} ｜ 产出字段：{fields} ｜ 计算函数：`{compute}`".format(
                params=", ".join(endpoint["params"]) or "无",
                fields=", ".join(endpoint["fields"]),
                compute=endpoint["compute"],
            )
        )
        lines.append("")

    lines += [
        "## 缓存策略总表",
        "",
        "| 策略 | TTL | 落文件缓存 | partial 可缓存 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for name, policy in data["cache_policies"].items():
        ttl = f"{policy['ttl_seconds']}s" if policy["ttl_seconds"] is not None else "—"
        lines.append(
            f"| {name} | {ttl} | {'是' if policy['file_cache'] else '否'} | "
            f"{'是' if policy['cache_partial'] else '否'} | {policy['description']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_catalog(path: str | os.PathLike[str]) -> bool:
    """把 CATALOG 写入文件；内容不变则不重写（幂等）。

    Returns:
        True = 本次写入（新建或内容变化），False = 内容未变、跳过写入。
    """
    target = Path(path)
    content = render_markdown(build_catalog(include_generated_at=False))
    if target.is_file():
        try:
            if target.read_text(encoding="utf-8") == content:
                return False
        except OSError:
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, target)
    return True


def missing_compute_refs() -> list[str]:
    """检查已实现端点的 compute 引用是否真实存在（module:function 可导入）。

    planned 端点不检查（它们本来就还没实现）。返回缺失项列表。
    """
    missing: list[str] = []
    for endpoint in SHORTLINE_ENDPOINTS.values():
        if endpoint.status != "implemented":
            continue
        module_name, _, func_name = endpoint.compute.partition(":")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - 导入失败本身就是问题
            missing.append(f"{endpoint.id}: 模块不可导入 {module_name}（{exc}）")
            continue
        if not callable(getattr(module, func_name, None)):
            missing.append(f"{endpoint.id}: 函数不存在 {endpoint.compute}")
    return missing
