"""REST 错误样板单点 _helpers 测试（2026-11-11 批次C5 → 裁决统一后形态）。

语义沿革：C5 收拢时双形态（B 形 ValueError→502 怪癖）保留；2026-11-11
老板拍板「统一」→ 全仓单一 A 形语义（ValueError→400）。
"""

import pytest
from fastapi import HTTPException

from tradex.api.routes._helpers import (
    business_error,
    data_source_error,
    serve_envelope,
    validate_symbol,
)


class TestValidateSymbol:
    def test_ok(self):
        validate_symbol("600519")  # 不抛即过

    @pytest.mark.parametrize("bad", ["60051", "6005190", "60051a", ""])
    def test_bad(self, bad):
        with pytest.raises(HTTPException) as ei:
            validate_symbol(bad)
        assert ei.value.status_code == 400


class TestServeEnvelope:
    def test_ok_wraps_envelope(self):
        from tradex.api.schemas import ERR_OK

        out = serve_envelope(lambda: {"k": 1})
        assert out.code == ERR_OK and out.data == {"k": 1} and out.msg == "ok"

    def test_valueerror_becomes_400(self):
        """统一后单一语义：ValueError → 400（原 B 形 502 怪癖已废除）。"""
        with pytest.raises(HTTPException) as ei:
            serve_envelope(lambda: (_ for _ in ()).throw(ValueError("业务错")))
        assert ei.value.status_code == 400

    def test_other_exception_502(self):
        with pytest.raises(HTTPException) as ei:
            serve_envelope(lambda: (_ for _ in ()).throw(RuntimeError("源炸")))
        assert ei.value.status_code == 502

    def test_http_exception_passthrough(self):
        """路由自身 HTTPException（404 等）不被吞成 502。"""
        def boom():
            raise HTTPException(status_code=404, detail="无此端点")

        with pytest.raises(HTTPException) as ei:
            serve_envelope(boom)
        assert ei.value.status_code == 404
