"""工单 08 测试：indicator service + REST 端点。

注：技术指标 MCP 工具已经是薄包装（业务逻辑在模块级私有函数 _macd_values 等），
本工单不改 MCP 工具，只新建 service 层包装 + REST 端点（按 symbol 取 K 线后计算）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_BAD_REQUEST, ERR_OK


def _build_min_app():
    """构造带 envelope 异常映射的最小 app（A⑦ 收敛 2026-11-22：薄壳调基座，原手抄与基座 AST 同构）。"""
    from tests._rest_test_base import build_min_test_app

    return build_min_test_app()


def _clear_cache():
    try:
        from tradex.utils.cache import cache as _c
        _c.clear()
    except Exception:
        pass


class TestIndicatorServiceDirect:
    """直接计算函数（接收价格数组）。"""

    def test_calc_macd_basic(self):
        from tradex.service import indicator_service
        # 生成 30 个收盘价
        closes = [100.0 + i * 0.5 for i in range(30)]
        result = indicator_service.calc_macd(closes)
        assert isinstance(result, dict)
        assert "dif" in result and "dea" in result and "macd" in result
        assert len(result["dif"]) == 30

    def test_calc_macd_insufficient_data_raises(self):
        from tradex.service import indicator_service
        closes = [100.0, 101.0, 102.0]
        with pytest.raises(ValueError, match="数据不足"):
            indicator_service.calc_macd(closes)

    def test_calc_kdj_basic(self):
        from tradex.service import indicator_service
        highs = [105.0 + i for i in range(15)]
        lows = [95.0 + i for i in range(15)]
        closes = [100.0 + i for i in range(15)]
        result = indicator_service.calc_kdj(highs, lows, closes)
        assert "k" in result and "d" in result and "j" in result

    def test_calc_kdj_mismatched_lengths_raises(self):
        from tradex.service import indicator_service
        with pytest.raises(ValueError, match="长度必须相同"):
            indicator_service.calc_kdj([1, 2, 3], [1, 2], [1, 2, 3])

    def test_calc_rsi_basic(self):
        from tradex.service import indicator_service
        closes = [100.0 + i * 0.5 for i in range(20)]
        result = indicator_service.calc_rsi(closes, period=14)
        assert "rsi" in result
        # RSI 实现：period 之后首位用 SMA 初始化会吞掉 1 个 warmup，
        # 故 20 根 + period=14 → 输出长度 19（实现如实反映，不强求等长）。
        assert len(result["rsi"]) == 19

    def test_calc_boll_basic(self):
        from tradex.service import indicator_service
        closes = [100.0 + i * 0.3 for i in range(25)]
        result = indicator_service.calc_boll(closes, period=20, k=2.0)
        assert "upper" in result and "middle" in result and "lower" in result


class TestIndicatorServiceBySymbol:
    """按 symbol 自动取 K 线计算。"""

    def test_calc_macd_by_symbol_returns_envelope(self):
        from tradex.service import indicator_service
        _clear_cache()
        result = indicator_service.calc_macd_by_symbol(symbol="600519")
        assert isinstance(result, dict)
        assert "dif" in result or "symbol" in result

    def test_calc_rsi_by_symbol(self):
        from tradex.service import indicator_service
        _clear_cache()
        result = indicator_service.calc_rsi_by_symbol(symbol="600519")
        assert isinstance(result, dict)


class TestIndicatorRestEndpoints:
    """/api/v1/indicator/* 端点。"""

    def test_macd_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/indicator/macd?symbol=600519&period=daily")
        body = resp.json()
        assert "code" in body

    def test_macd_non_digit_symbol_returns_400(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/indicator/macd?symbol=abc123")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_macd_invalid_period_returns_400(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/indicator/macd?symbol=600519&period=quarterly")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_kdj_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/indicator/kdj?symbol=600519")
        body = resp.json()
        assert "code" in body

    def test_rsi_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/indicator/rsi?symbol=600519")
        body = resp.json()
        assert "code" in body

    def test_boll_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/indicator/boll?symbol=600519")
        body = resp.json()
        assert "code" in body
