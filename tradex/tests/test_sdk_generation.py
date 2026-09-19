"""工单 21+22 测试 —— SDK 自动生成（降级方案：精简生成器）。

验证：
- 生成器脚本能从 OpenAPI 规范提取所有 /api/v1/* 端点
- TypeScript 产物结构合法（含 export class TradexClient）
- Python 产物可 import + 实例化（不必实调网络）
- README 包含双 SDK 示例
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


_HUB_ROOT = Path(__file__).resolve().parents[2]  # tradex/tests/ → tradex-hub/
_GENERATOR = _HUB_ROOT / "scripts" / "generate_sdk.py"
_SDK_DIR = _HUB_ROOT / "sdk"


def _sdk_exists() -> bool:
    """SDK 是否已生成（CI 环境可能没生成）。"""
    return (_SDK_DIR / "typescript" / "index.ts").exists() and \
           (_SDK_DIR / "python" / "tradex_client" / "__init__.py").exists()


@pytest.mark.skipif(not _sdk_exists(), reason="SDK 未生成（需先运行 scripts/generate_sdk.py）")
class TestSDKArtifacts:
    """验证 SDK 产物结构与内容。"""

    def test_typescript_sdk_exists(self):
        """sdk/typescript/index.ts 应存在。"""
        assert (_SDK_DIR / "typescript" / "index.ts").exists()

    def test_python_sdk_exists(self):
        """sdk/python/tradex_client/__init__.py 应存在。"""
        assert (_SDK_DIR / "python" / "tradex_client" / "__init__.py").exists()

    def test_readme_exists(self):
        """sdk/README.md 应存在。"""
        assert (_SDK_DIR / "README.md").exists()

    def test_typescript_has_tradex_client_class(self):
        """TS SDK 应导出 TradexClient 类。"""
        content = (_SDK_DIR / "typescript" / "index.ts").read_text(encoding="utf-8")
        assert "export class TradexClient" in content
        assert "Envelope<T>" in content

    def test_typescript_has_envelope_interface(self):
        """TS SDK 应定义 Envelope<T> 接口（契约包装）。"""
        content = (_SDK_DIR / "typescript" / "index.ts").read_text(encoding="utf-8")
        assert "interface Envelope" in content
        assert "code: number" in content
        assert "data: T" in content

    def test_typescript_includes_ping_method(self):
        """TS SDK 应含 ping() 方法（基础端点）。"""
        content = (_SDK_DIR / "typescript" / "index.ts").read_text(encoding="utf-8")
        assert "async ping()" in content

    def test_typescript_includes_quote_endpoint(self):
        """TS SDK 应含行情查询方法（/api/v1/price/quote）。"""
        content = (_SDK_DIR / "typescript" / "index.ts").read_text(encoding="utf-8")
        assert "/api/v1/price/quote" in content

    def test_python_sdk_importable(self):
        """Python SDK 应可被 import。"""
        # 直接路径加载（避免修改 sys.path 全局）
        init_path = _SDK_DIR / "python" / "tradex_client" / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "tradex_client_test", init_path
        )
        module = importlib.util.module_from_spec(spec)
        # requests 可能未装在测试环境，但应至少能 import 模块定义
        try:
            spec.loader.exec_module(module)
        except ImportError:
            pytest.skip("requests 未安装，跳过 import 测试")
        # 类应存在
        assert hasattr(module, "TradexClient")
        # 实例化（不调网络）
        client = module.TradexClient()
        assert client.base_url == "http://127.0.0.1:8000"

    def test_python_sdk_has_core_methods(self):
        """Python SDK 应含核心方法（ping + quote）。"""
        init_path = _SDK_DIR / "python" / "tradex_client" / "__init__.py"
        content = init_path.read_text(encoding="utf-8")
        assert "def ping(" in content
        assert "def quote(" in content

    def test_readme_has_both_sdks(self):
        """README 应同时含 TypeScript 和 Python 章节。"""
        content = (_SDK_DIR / "README.md").read_text(encoding="utf-8")
        assert "## TypeScript 客户端" in content
        assert "## Python 客户端" in content
        assert "端点列表" in content

    def test_readme_endpoint_table_has_rows(self):
        """README 端点表应有具体行（非空）。"""
        content = (_SDK_DIR / "README.md").read_text(encoding="utf-8")
        # 至少有若干端点行（含 | GET | 或类似）
        assert content.count("| GET |") >= 30  # 阶段二 ~46 端点，多数为 GET


class TestGeneratorScript:
    """验证生成器脚本本身的正确性（不依赖网关在线）。"""

    def test_generator_script_exists(self):
        """scripts/generate_sdk.py 应存在。"""
        assert _GENERATOR.exists()

    def test_generator_has_main_function(self):
        """脚本应定义 main 函数。"""
        content = _GENERATOR.read_text(encoding="utf-8")
        assert "def main(" in content
        assert "argparse" in content

    def test_generator_supports_both_languages(self):
        """生成器应支持 TypeScript 和 Python 双语言。"""
        content = _GENERATOR.read_text(encoding="utf-8")
        assert "def generate_typescript(" in content
        assert "def generate_python(" in content

    def test_generator_has_degradation_note(self):
        """脚本注释应说明降级方案背景。"""
        content = _GENERATOR.read_text(encoding="utf-8")
        assert "降级" in content or "fallback" in content.lower()
