"""tradex: China Financial Data MCP Server based on AKShare."""

import os
from pathlib import Path

# 国内 A 股数据源一律直连，禁止走系统代理（代理仅用于 git push GitHub）。
# akshare/requests/httpx 默认读 HTTP(S)_PROXY 环境变量，此处 import 时统一清除，
# 确保所有数据源 fetcher 直连；本改动只在当前 Python 进程内生效，
# 不影响终端里的 git push（独立进程、独立环境变量）。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

# v3.3.14 修复：仅 pop 环境变量是不够的。
# requests/urllib 的 getproxies() 实现为 getproxies_environment() or getproxies_registry()，
# 当环境变量为空时会**回退读取 Windows 注册表代理**(Internet Settings)，
# 导致 akshare 等基于 requests 的数据源仍走 Clash(127.0.0.1:7897)，
# 国内东财接口被代理拦截（实测 ProxyError）。
# 显式设置 NO_PROXY 使 getproxies_environment() 返回非空({'no':'*'})从而短路注册表读取，
# 彻底绕过系统代理。实测：设后 getproxies() == {'no': '*'}。
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"


def _read_version() -> str:
    """从项目根目录的 VERSION 文件读取版本号(单一事实来源)。"""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        version_file = parent / "VERSION"
        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


__version__ = _read_version()
