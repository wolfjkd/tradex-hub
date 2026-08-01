#!/usr/bin/env python3
"""
金融数据中枢 - 数据源健康检测脚本（v3.0.0）
检测所有数据源的可用性和响应速度

数据源架构（2026-06-24 更新）：
  主力：cn-financial-mcp（AKShare + 东财直连 + 同花顺，61 工具）
  辅助：tdx-connector（通达信协议，独立 connector）
  已废弃：ftshare / Wind MCP / 腾讯直连（均已下线或不可用）
"""

import subprocess
import json
import time
import sys
from datetime import datetime

# 数据源定义
DATA_SOURCES = {
    "akshare_em": {
        "name": "AKShare 东财",
        "type": "HTTP",
        "test_url": "https://push2.eastmoney.com/api/qt/ulist.np/get?fields=f12,f14&secids=1.600519",
        "priority": "P0",
        "note": "cn-financial-mcp 主力数据源"
    },
    "akshare_tencent": {
        "name": "腾讯行情",
        "type": "HTTP",
        "test_url": "https://qt.gtimg.cn/q=sh000001",
        "priority": "P0",
        "note": "个股实时报价（get_realtime_price 备用源）"
    },
    "push2delay": {
        "name": "东财 push2delay",
        "type": "HTTP",
        "test_url": "https://push2delay.eastmoney.com/api/qt/ulist.np/get?fields=f12,f14&secids=1.600519",
        "priority": "P0",
        "note": "东财镜像节点（老板网络直连可用）"
    },
    "datacenter_web": {
        "name": "东财 datacenter",
        "type": "HTTP",
        "test_url": "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL&pageNumber=1&pageSize=1",
        "priority": "P1",
        "note": "龙虎榜/解禁日历数据源"
    },
    "ths_hsgt": {
        "name": "同花顺北向",
        "type": "HTTP",
        "test_url": "https://data.hexin.cn/market/hsgtApi/method/dayChart/",
        "priority": "P1",
        "note": "北向资金/涨停归因数据源"
    },
    "cn_financial_mcp": {
        "name": "cn-financial-mcp",
        "type": "MCP",
        "test_script": "import sys, os\nsys.path.insert(0, os.path.join('cn-financial-mcp', 'src'))\nfrom cn_financial_mcp.server import mcp\nprint('OK')",
        "priority": "P0",
        "note": "61 个 MCP 工具的统一入口"
    },
}


def test_http(url: str) -> dict:
    """测试 HTTP 接口"""
    try:
        import urllib.request
        start = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8", errors="ignore")
            elapsed = (time.time() - start) * 1000
            return {
                "status": "OK",
                "latency_ms": round(elapsed, 1),
                "data_size": len(data)
            }
    except Exception as e:
        return {
            "status": "FAIL",
            "error": str(e)[:100]
        }


def test_command(cmd: str) -> dict:
    """测试命令行工具（使用临时脚本避免 shell 转义问题）"""
    import tempfile, os
    try:
        start = time.time()
        # Write command to a temp script to avoid shell escaping issues on Windows
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir=".", encoding="utf-8"
        ) as f:
            f.write(cmd)
            script_path = f.name
        try:
            import sys
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, timeout=30
            )
        finally:
            os.unlink(script_path)
        elapsed = (time.time() - start) * 1000
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        ok = result.returncode == 0 and len(stdout.strip()) > 0
        return {
            "status": "OK" if ok else "FAIL",
            "latency_ms": round(elapsed, 1),
            "exit_code": result.returncode,
            "output_len": len(stdout)
        }
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "error": "30s timeout"}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)[:100]}


def main():
    print(f"=== 数据源健康检测 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    results = {}
    for key, src in DATA_SOURCES.items():
        print(f"检测 {src['name']} ({src['type']})...", end=" ", flush=True)

        if src["type"] == "HTTP":
            result = test_http(src["test_url"])
        elif "test_script" in src:
            result = test_command(src["test_script"])
        else:
            result = test_command(src["test_command"])

        results[key] = {**src, **result}

        icon = "OK" if result.get("status") == "OK" else "FAIL"
        latency = result.get("latency_ms", "N/A")
        print(f"[{icon}] {latency}ms")

    # 汇总
    print(f"\n=== 检测汇总 ===")
    ok_count = sum(1 for r in results.values() if r.get("status") == "OK")
    total = len(results)
    print(f"可用: {ok_count}/{total}")

    for key, r in results.items():
        status_icon = "+" if r.get("status") == "OK" else "-"
        latency = f"{r.get('latency_ms', 'N/A')}ms"
        print(f"  [{status_icon}] {r['name']:12s} {r['priority']:4s} {latency:>10s}")

    return 0 if ok_count >= total * 0.6 else 1


if __name__ == "__main__":
    sys.exit(main())
