#!/usr/bin/env python3
"""D05/#3: /mcp 并发收益饱和压测基线脚本（入库，可重复执行）。

背景：KNOWN-ISSUES #8 重立题——/mcp 并发收益在 3 路左右饱和（6 路加速比仅 2.60x），
疑似工具 async def 包裹同步阻塞调用占满事件循环（H1）。本脚本建可复现基线，
为根因验证（H1 A/B）与解法评估（S1/S2）提供数据。

设计（交接文档 04 §4）：
- HTTP 直连 /mcp，不经过 MCP 客户端（避免客户端串行化污染结论）
- 标的池 20 只，每轮轮换 symbol 避开服务端缓存
- 三类工具组合：① 本地快 get_historical_price ② 网络慢 get_financial_indicators ③ 混合
- 并发档位 1/4/8/16，每档 3 轮取中位数，档间静置 ≥30s
- 采集：单请求 P50/P95、端到端墙钟、加速比、错误率

用法：
    # 先起 tradex-hub 服务（另一终端）
    python -m tradex --http --port 8000

    # 跑压测（默认打 127.0.0.1:8000）
    python scripts/benchmark_mcp_concurrency.py

    # 自定义端口 / 只跑某工具
    python scripts/benchmark_mcp_concurrency.py --port 9000 --tools local_fast
    python scripts/benchmark_mcp_concurrency.py --rounds 1 --levels 1,8  # 快速验证

输出：
- 控制台：每档摘要 + 最终基线表
- reports/mcp_concurrency_baseline_<时间戳>.json：完整原始数据
- reports/mcp_concurrency_baseline_<时间戳>.md：Markdown 基线表（可贴交接文档）
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from typing import Any

# ===== 配置区 =====

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
DEFAULT_PORT = 8000
REQUEST_TIMEOUT_SEC = 60

# 20 只活跃 A 股（避免指数，指数需带前缀；裸 6 位代码避撞号）
SYMBOL_POOL = [
    "600519", "000001", "600036", "000858", "600276",
    "300750", "600887", "000333", "600030", "601318",
    "600000", "000651", "600436", "300059", "600585",
    "000568", "600406", "002594", "600900", "601166",
]

# 工具组合：name = (tool_name, extra_args, 分类)
TOOL_GROUPS: dict[str, tuple[str, dict[str, Any], str]] = {
    "local_fast": ("get_historical_price", {}, "本地快（eltdx）"),
    "network_slow": ("get_financial_indicators", {}, "网络慢（akshare）"),
    "network_fast": ("get_stock_news", {}, "网络快（东财）"),
}

DEFAULT_LEVELS = [1, 4, 8, 16]
DEFAULT_ROUNDS = 3
COOLDOWN_SEC = 30  # 档间静置，让上游限流恢复


# ===== 数据结构 =====

@dataclass
class SingleCall:
    req_id: int
    symbol: str
    status: int  # HTTP 状态码；0 = 网络异常
    elapsed: float  # 秒
    error: str | None = None


@dataclass
class LevelResult:
    tool_group: str
    level: int
    round_idx: int
    wall_clock: float  # 端到端墙钟
    calls: list[SingleCall] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.calls if c.status == 200 and c.error is None)

    @property
    def error_rate(self) -> float:
        n = len(self.calls)
        return 0.0 if n == 0 else 1 - self.ok_count / n

    @property
    def latencies(self) -> list[float]:
        return [c.elapsed for c in self.calls if c.status == 200]

    @property
    def p50(self) -> float | None:
        l = self.latencies
        return statistics.median(l) if l else None

    @property
    def p95(self) -> float | None:
        l = sorted(self.latencies)
        if not l:
            return None
        idx = max(0, int(len(l) * 0.95) - 1)
        return l[idx]


# ===== MCP HTTP 调用 =====

def parse_response(raw: str) -> dict | None:
    """解析 /mcp 响应：可能是纯 JSON，也可能是 SSE 流（data: {...}）。"""
    raw = raw.strip()
    if not raw:
        return None
    # SSE 流：多行 "data: {...}"，取最后一个非空 data
    if raw.startswith("data:") or "\ndata:" in raw:
        last = None
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                last = line[5:].strip()
        if last:
            try:
                return json.loads(last)
            except json.JSONDecodeError:
                return None
    # 纯 JSON
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def call_mcp(base_url: str, tool_name: str, symbol: str, extra_args: dict, req_id: int) -> SingleCall:
    """单次 MCP tools/call HTTP 请求（JSON-RPC 2.0 over HTTP）。"""
    body = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {"symbol": symbol, **extra_args}},
    }
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            base_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.perf_counter() - t0
            payload = parse_response(raw)
            # JSON-RPC 错误（即使 HTTP 200）
            err = None
            if payload and isinstance(payload, dict):
                if "error" in payload:
                    err = json.dumps(payload["error"], ensure_ascii=False)[:200]
            return SingleCall(req_id=req_id, symbol=symbol, status=resp.status, elapsed=elapsed, error=err)
    except urllib.error.HTTPError as e:
        return SingleCall(req_id=req_id, symbol=symbol, status=e.code, elapsed=time.perf_counter() - t0, error=f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        return SingleCall(req_id=req_id, symbol=symbol, status=0, elapsed=time.perf_counter() - t0, error=str(e)[:200])


def run_level(base_url: str, tool_name: str, extra_args: dict, level: int, symbols: list[str], round_idx: int) -> LevelResult:
    """单档并发：level 个请求，每个用不同 symbol 避缓存。"""
    result = LevelResult(tool_group=tool_name, level=level, round_idx=round_idx, wall_clock=0.0)
    with concurrent.futures.ThreadPoolExecutor(max_workers=level) as pool:
        futures = []
        for i in range(level):
            sym = symbols[(round_idx * level + i) % len(symbols)]
            fut = pool.submit(call_mcp, base_url, tool_name, sym, extra_args, i + 1)
            futures.append(fut)
        t0 = time.perf_counter()
        for fut in concurrent.futures.as_completed(futures):
            result.calls.append(fut.result())
        result.wall_clock = time.perf_counter() - t0
    return result


# ===== 主流程 =====

def median_of_rounds(rounds: list[LevelResult]) -> dict:
    """对同一 (tool_group, level) 的多轮结果取中位数，返回汇总。"""
    walls = sorted(r.wall_clock for r in rounds)
    p50s = sorted(r.p50 for r in rounds if r.p50 is not None)
    p95s = sorted(r.p95 for r in rounds if r.p95 is not None)
    errs = sorted(r.error_rate for r in rounds)
    return {
        "wall_clock_median": statistics.median(walls) if walls else None,
        "p50_median": statistics.median(p50s) if p50s else None,
        "p95_median": statistics.median(p95s) if p95s else None,
        "error_rate_median": statistics.median(errs) if errs else None,
        "rounds": len(rounds),
    }


def compute_speedup(baseline_p50: float | None, level_wall: float | None, level: int) -> float | None:
    """加速比 = level × 单发 P50 ÷ 并发墙钟。

    用 level=1 的 P50（单请求典型耗时）而非墙钟，避免 ThreadPoolExecutor 启动
    开销与服务端缓存对单发基线的污染（交接文档 §4.2 定义）。
    """
    if not baseline_p50 or not level_wall or level_wall == 0:
        return None
    return round(level * baseline_p50 / level_wall, 2)


def main() -> int:
    ap = argparse.ArgumentParser(description="/mcp 并发收益饱和压测基线")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="tradex-hub 端口（默认 8000）")
    ap.add_argument("--host", default="127.0.0.1", help="tradex-hub 主机")
    ap.add_argument("--levels", default=",".join(map(str, DEFAULT_LEVELS)), help="并发档位，逗号分隔")
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="每档重复轮数（取中位数）")
    ap.add_argument("--tools", default=",".join(TOOL_GROUPS.keys()), help="工具组合，逗号分隔")
    ap.add_argument("--cooldown", type=int, default=COOLDOWN_SEC, help="档间静置秒数")
    ap.add_argument("--out-dir", default="reports", help="报告输出目录")
    args = ap.parse_args()

    base_url = f"http://{args.host}:{args.port}/mcp"
    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    tools = [t.strip() for t in args.tools.split(",") if t.strip() in TOOL_GROUPS]
    if not tools:
        print(f"无有效工具组合，可选：{list(TOOL_GROUPS.keys())}", file=sys.stderr)
        return 2

    print(f"=== /mcp 并发压测基线 ===")
    print(f"目标: {base_url}")
    print(f"工具组合: {tools}")
    print(f"并发档位: {levels}")
    print(f"每档轮数: {args.rounds}（取中位数）")
    print(f"档间静置: {args.cooldown}s")
    print(f"标的池: {len(SYMBOL_POOL)} 只")
    print()

    # 健康检查
    try:
        hc = urllib.request.urlopen(f"http://{args.host}:{args.port}/health", timeout=10)
        if hc.status != 200:
            print(f"⚠ 健康检查返回 {hc.status}，继续尝试…")
        else:
            print(f"健康检查 OK（{json.loads(hc.read()).get('name', '?')}）")
    except Exception as e:
        print(f"✗ 健康检查失败：{e}", file=sys.stderr)
        print(f"  请确认 tradex-hub 服务已启动：python -m tradex --http --port {args.port}", file=sys.stderr)
        return 1
    print()

    os.makedirs(args.out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    all_rounds: list[LevelResult] = []
    summary: dict = {"config": {"url": base_url, "levels": levels, "rounds": args.rounds, "tools": tools}, "results": {}}

    for tg in tools:
        tool_name, extra_args, label = TOOL_GROUPS[tg]
        print(f"--- 工具组合：{tg}（{label}，tool={tool_name}）---")
        summary["results"][tg] = {}
        baseline_p50 = None  # level=1 的 P50 中位数，用于算加速比（比墙钟更稳）

        for li, level in enumerate(levels):
            rounds_res: list[LevelResult] = []
            for r in range(args.rounds):
                print(f"  [{tg}] level={level} round={r + 1}/{args.rounds} …", end="", flush=True)
                res = run_level(base_url, tool_name, extra_args, level, SYMBOL_POOL, r)
                rounds_res.append(res)
                ok = res.ok_count
                print(f" 墙钟={res.wall_clock:.2f}s ok={ok}/{level} err={res.error_rate:.0%} p50={res.p50:.3f}s" if res.p50 else f" 墙钟={res.wall_clock:.2f}s ok={ok}/{level} err={res.error_rate:.0%}")
                all_rounds.append(res)
            med = median_of_rounds(rounds_res)
            if level == 1:
                baseline_p50 = med["p50_median"]
            sp = compute_speedup(baseline_p50, med["wall_clock_median"], level)
            med["speedup"] = sp
            summary["results"][tg][str(level)] = med
            print(f"  [{tg}] level={level} 中位数: 墙钟={med['wall_clock_median']:.2f}s p50={med['p50_median']:.3f}s p95={med['p95_median']:.3f}s err={med['error_rate_median']:.0%} 加速比={sp}")
            if li < len(levels) - 1:
                print(f"  静置 {args.cooldown}s …")
                time.sleep(args.cooldown)
        print()

    # 输出 JSON
    json_path = os.path.join(args.out_dir, f"mcp_concurrency_baseline_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"原始数据: {json_path}")

    # 输出 Markdown 基线表
    md_lines = [f"# /mcp 并发收益饱和压测基线（{ts}）", "", f"目标：`{base_url}` ｜ 每档 {args.rounds} 轮取中位数 ｜ 档间静置 {args.cooldown}s", ""]
    for tg in tools:
        _, _, label = TOOL_GROUPS[tg]
        md_lines.append(f"## {tg}（{label}）")
        md_lines.append("")
        md_lines.append("| 并发 | 墙钟(s) | P50(s) | P95(s) | 错误率 | 加速比 |")
        md_lines.append("|---|---|---|---|---|---|")
        for level in levels:
            r = summary["results"][tg].get(str(level), {})
            sp = r.get("speedup")
            md_lines.append(
                f"| {level} | {r.get('wall_clock_median', 0):.2f} | {r.get('p50_median', 0):.3f} | {r.get('p95_median', 0):.3f} | {r.get('error_rate_median', 0):.0%} | {sp if sp is not None else '—'} |"
            )
        md_lines.append("")
    md_path = os.path.join(args.out_dir, f"mcp_concurrency_baseline_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"基线表: {md_path}")

    # 通过标准判定（交接文档 §4.3）
    print()
    print("=== 通过标准判定 ===")
    for tg in tools:
        r8 = summary["results"][tg].get("8", {})
        sp8 = r8.get("speedup")
        r16 = summary["results"][tg].get("16", {})
        err16 = r16.get("error_rate_median")
        sp8_str = f"{sp8}" if sp8 is not None else "—"
        err16_str = f"{err16:.0%}" if err16 is not None else "—"
        sp8_ok = "✓" if sp8 is not None and sp8 >= 4.0 else "✗"
        err16_ok = "✓" if err16 is not None and err16 == 0 else "✗"
        print(f"  [{tg}] 8 路加速比 {sp8_str}（目标 ≥4.0）{sp8_ok} ｜ 16 路错误率 {err16_str}（目标 =0）{err16_ok}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
