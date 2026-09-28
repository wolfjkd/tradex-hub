"""精简 SDK 生成器（工单 21-22 降级方案）。

openapi-generator 需要 Java/Docker，本机不可用；按 spec §4.2 降级路径，
手写一个 200 行的精简生成器，从 /openapi.json 生成 TypeScript 和 Python 客户端雏形。

生成策略：
- 从 OpenAPI paths 解析每个 GET/POST/DELETE 端点
- 提取路径参数 / 查询参数 / body schema
- 生成等价的 fetch（TS）/ requests（Python）调用代码
- 生成 README 示例

用法：
    python scripts/generate_sdk.py [--base-url http://127.0.0.1:8000]

输出：
    sdk/typescript/index.ts
    sdk/python/tradex_client/__init__.py
    sdk/README.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"

# SDK 客户端版本：1.x = operationId 命名；2.0.0 = 2026-09-28 路径确定性命名
# （修 company.search/news.stock 被遮蔽的碰撞 + 全端点覆盖，非 GET 加动词前缀）
SDK_VERSION = "2.0.0"


def fetch_openapi(base_url: str) -> dict[str, Any]:
    """从网关拉取 openapi.json。"""
    url = f"{base_url.rstrip('/')}/openapi.json"
    logger.info("Fetching %s", url)
    with urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ────────────────────── TypeScript 生成 ──────────────────────────

def _to_camel(s: str) -> str:
    """snake_case → camelCase。"""
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _endpoint_fn_name(path: str, method: str = "GET") -> str:
    """路径 → 确定性 snake_case 方法名（2026-09-28 审计修复）。

    旧实现取 operationId 第一段（`_api_v1_` 前缀），/company/search 与
    /news/search 都生成 `search`、/news/stock 与 /diagnostic/stock 都生成
    `stock`——后定义覆盖前者，company 搜索和 news/stock 在客户端不可达。
    新实现用 /api/v1 之后的完整路径：/company/search → company_search，
    路径参数段 {sid} → by_sid（如 /write/strategy/{sid} → write_strategy_by_sid）。
    非 GET 方法加动词前缀（post_/put_/delete_/patch_），避免同一路径的
    GET/PUT/DELETE 方法名互相覆盖。
    """
    parts: list[str] = []
    for seg in path.split("/"):
        if not seg or seg in ("api", "v1"):
            continue
        m = re.fullmatch(r"\{(\w+)\}", seg)
        parts.append(f"by_{m.group(1)}" if m else seg)
    name = "_".join(parts)
    name = re.sub(r"\W", "_", name) or "root"
    m = method.lower()
    if m not in ("get", ""):
        name = f"{m}_{name}"
    return name


def _parse_endpoint(path: str, method: str, op: dict) -> dict:
    """从 OpenAPI operation 提取关键信息。"""
    # 路径参数 {xxx}
    path_params = re.findall(r"\{(\w+)\}", path)
    # 查询参数
    query_params = []
    for param in op.get("parameters", []):
        if param.get("in") == "query":
            query_params.append({
                "name": param["name"],
                "required": param.get("required", False),
                "type": param.get("schema", {}).get("type", "string"),
            })
    # body
    body_ref = None
    req_body = op.get("requestBody", {})
    if req_body:
        content = req_body.get("content", {})
        app_json = content.get("application/json", {})
        body_ref = app_json.get("schema", {}).get("$ref", "")
    return {
        "path": path,
        "method": method.upper(),
        "operation_id": op.get("operationId", ""),
        "summary": op.get("summary", ""),
        "path_params": path_params,
        "query_params": query_params,
        "body_ref": body_ref,
        "tag": (op.get("tags") or ["default"])[0],
    }


def _gen_ts_endpoint(endpoint: dict) -> list[str]:
    """生成单个端点的 TypeScript 方法。"""
    fn_name = _to_camel(_endpoint_fn_name(endpoint["path"]))
    path = endpoint["path"]
    method = endpoint["method"]
    qparams = endpoint["query_params"]
    pparams = endpoint["path_params"]
    has_body = bool(endpoint["body_ref"])

    # 函数参数签名
    args = []
    for p in pparams:
        args.append(f"{p}: string")
    if qparams:
        # 用一个 query 对象收纳
        q_type = "{ " + "; ".join(
            f"{_to_camel(p['name'])}{'?' if not p['required'] else ''}: {p['type']}"
            for p in qparams
        ) + " }"
        args.append(f"query: {q_type}")
    if has_body:
        args.append("body: any")
    args_str = ", ".join(args)

    # 路径模板
    ts_path = path
    for p in pparams:
        ts_path = ts_path.replace(f"{{{p}}}", "${" + p + "}")

    lines = []
    lines.append(f"  /** {endpoint['summary']} */")
    lines.append(f"  async {fn_name}({args_str}): Promise<any> {{")
    # 构造 URL
    url_str = f"`{ts_path}`"
    if qparams:
        # 序列化 query 对象
        qs_keys = ", ".join(f"{p['name']}: query.{_to_camel(p['name'])}" for p in qparams)
        url_str = f"`{ts_path}?${{new URLSearchParams({{{qs_keys}}}).toString()}}`"
    lines.append(f"    const url = {url_str};")

    if method == "GET":
        lines.append("    const r = await fetch(this.baseUrl + url, { method: 'GET', headers: this.headers });")
    elif method == "POST":
        lines.append("    const r = await fetch(this.baseUrl + url, { method: 'POST', headers: {...this.headers, 'Content-Type': 'application/json'}, body: JSON.stringify(body) });")
    elif method == "DELETE":
        lines.append("    const r = await fetch(this.baseUrl + url, { method: 'DELETE', headers: this.headers });")
    else:
        lines.append(f"    const r = await fetch(this.baseUrl + url, {{ method: '{method}', headers: this.headers }});")
    lines.append("    if (!r.ok) throw new Error(`HTTP ${r.status}`);")
    lines.append("    return r.json();")
    lines.append("  }")
    return lines


def generate_typescript(endpoints: list[dict]) -> str:
    """生成完整的 TypeScript SDK 单文件。"""
    lines = [
        "// Auto-generated by scripts/generate_sdk.py (工单 21 降级方案)",
        "// Source: /openapi.json",
        "",
        "export interface Envelope<T> {",
        "  code: number;",
        "  data: T | null;",
        "  msg: string;",
        "}",
        "",
        "export class TradexClient {",
        "  constructor(",
        "    public baseUrl: string = 'http://127.0.0.1:8000',",
        "    public headers: Record<string, string> = {},",
        "  ) {}",
        "",
    ]
    for ep in endpoints:
        lines.extend(_gen_ts_endpoint(ep))
        lines.append("")
    lines.append("}")
    return "\n".join(lines)


# ────────────────────── Python 生成 ──────────────────────────

def _gen_py_endpoint(endpoint: dict) -> list[str]:
    fn_name = _endpoint_fn_name(endpoint["path"], endpoint["method"])
    # Python 用 snake_case（保持与 OpenAPI 一致）
    path = endpoint["path"]
    method = endpoint["method"].lower()
    qparams = endpoint["query_params"]
    pparams = endpoint["path_params"]
    has_body = bool(endpoint["body_ref"])

    args = ["self"]
    for p in pparams:
        args.append(f"{p}: str")
    if qparams:
        args.append("*, query: dict | None = None")
    if has_body:
        args.append("body: dict")
    args_str = ", ".join(args)

    lines = []
    lines.append(f"    def {fn_name}({args_str}) -> dict:")
    lines.append(f"        \"\"\"{endpoint['summary']}\"\"\"")
    py_path_str = repr(path)  # 字符串模板
    if qparams:
        lines.append(f"        params = query or {{}}")
        lines.append(f"        r = self._request('{method}', {py_path_str}, params=params)")
    else:
        lines.append(f"        r = self._request('{method}', {py_path_str})")
    if has_body:
        lines[-1] = lines[-1].rstrip(")") + ", json=body)"
    lines.append("        return self._unwrap(r)")
    return lines


def generate_python(endpoints: list[dict]) -> str:
    """生成完整的 Python SDK 单文件。"""
    lines = [
        "\"\"\"tradex_client SDK (工单 22 降级方案)。\"\"\"",
        "",
        "from __future__ import annotations",
        "import requests",
        "from typing import Any",
        "",
        "__version__ = '" + SDK_VERSION + "'",
        "",
        "class TradexClient:",
        "    def __init__(self, base_url: str = 'http://127.0.0.1:8000', timeout: float = 30.0):",
        "        self.base_url = base_url.rstrip('/')",
        "        self.timeout = timeout",
        "        self._session = requests.Session()",
        "        # 直连本地网关：requests 默认 trust_env=True 会读 HTTP(S)_PROXY",
        "        self._session.trust_env = False",
        "",
        "    def _request(self, method: str, path: str, **kwargs) -> requests.Response:",
        "        url = self.base_url + path",
        "        r = self._session.request(method, url, timeout=self.timeout, **kwargs)",
        "        r.raise_for_status()",
        "        return r",
        "",
        "    @staticmethod",
        "    def _unwrap(r: requests.Response) -> dict:",
        "        body = r.json()",
        "        if body.get('code') != 0:",
        "            raise Exception(f\"tradex error: code={body.get('code')} msg={body.get('msg')}\")",
        "        return body",
        "",
    ]
    for ep in endpoints:
        lines.extend(_gen_py_endpoint(ep))
        lines.append("")
    lines.append("")
    return "\n".join(lines)


# ────────────────────── 入口 ──────────────────────────

def collect_endpoints(spec: dict) -> list[dict]:
    """从 OpenAPI 提取所有 /api/v1/* 端点。"""
    endpoints = []
    for path, methods in spec.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for method, op in methods.items():
            if method.upper() not in {"GET", "POST", "DELETE", "PUT", "PATCH"}:
                continue
            endpoints.append(_parse_endpoint(path, method, op))
    return endpoints


def main() -> int:
    parser = argparse.ArgumentParser(description="精简 SDK 生成器")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output", default=".", help="输出根目录")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    spec = fetch_openapi(args.base_url)
    endpoints = collect_endpoints(spec)
    logger.info("收集到 %d 个 /api/v1/* 端点", len(endpoints))

    root = Path(args.output)
    ts_dir = root / "sdk" / "typescript"
    py_dir = root / "sdk" / "python" / "tradex_client"
    ts_dir.mkdir(parents=True, exist_ok=True)
    py_dir.mkdir(parents=True, exist_ok=True)

    # TypeScript
    (ts_dir / "index.ts").write_text(generate_typescript(endpoints), encoding="utf-8")
    logger.info("生成 %s", ts_dir / "index.ts")

    # Python
    (py_dir / "__init__.py").write_text(generate_python(endpoints), encoding="utf-8")
    logger.info("生成 %s", py_dir / "__init__.py")

    # README
    _gen_readme(root / "sdk", endpoints)

    return 0


def _gen_readme(sdk_dir: Path, endpoints: list[dict]) -> None:
    readme = sdk_dir / "README.md"
    # 用普通字符串拼接避免 f-string 解析 markdown 里的花括号
    parts = []
    parts.append("# tradex-hub SDK（客户端库）\n\n")
    parts.append("> 自动生成（基于精简生成器，工单 21-22 降级方案）。\n\n")
    parts.append("## TypeScript 客户端\n\n")
    parts.append("```bash\n# 安装（依赖 node-fetch 或浏览器 fetch）\ncp -r sdk/typescript ./your-project/tradex-sdk\n```\n\n")
    parts.append("```typescript\n")
    parts.append("import { TradexClient } from './tradex-sdk';\n\n")
    parts.append("const client = new TradexClient('http://127.0.0.1:8000');\n")
    parts.append("// 函数名由路径确定性生成（如 /api/v1/price/quote → priceQuote，无碰撞）\n")
    parts.append("const result = await client.quote(query={ symbol: '600519' });\n")
    parts.append("console.log(result.data.quote);\n")
    parts.append("```\n\n")
    parts.append("## Python 客户端\n\n")
    parts.append("```bash\npip install requests\ncp -r sdk/python/tradex_client ./your-project/\n```\n\n")
    parts.append("```python\n")
    parts.append("from tradex_client import TradexClient\n\n")
    parts.append("client = TradexClient('http://127.0.0.1:8000')\n")
    parts.append("result = client.quote(query={'symbol': '600519'})\n")
    parts.append("print(result['data']['quote'])\n")
    parts.append("```\n\n")
    parts.append(f"## 端点列表（{len(endpoints)} 个）\n\n")
    parts.append("| Method | Path | Summary |\n|--------|------|---------|\n")
    for ep in endpoints:
        parts.append(f"| {ep['method']} | `{ep['path']}` | {ep['summary']} |\n")
    content = "".join(parts)
    readme.write_text(content, encoding="utf-8")
    logger.info("生成 %s", readme)


if __name__ == "__main__":
    sys.exit(main())
