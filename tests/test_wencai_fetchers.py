"""
问财 WAP 通道 fetcher 测试（对应交接文档 07/09 · T2 施工）。

背景（2026-11-07 逆向实测）：
  - Web 端点被 TLS 指纹风控（requests/curl/curl_cffi 全 403），pywencai
    0.13.1 默认走该端点开箱必挂；
  - WAP 端点（unifiedwap/.../get-robot-data）只认 hexin-v 头，token 由
    pywencai 随包 bundle.js 生成；
  - WAP 服务端单会话锁页：perpage 硬钳 10、page 参数被忽略——fetcher
    内置重复页首行指纹检测防无限拼接。

本测试 mock 隔离网络，专注验证解析/翻页保护/降级纪律与消费方合并制。
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


def _wap_payload(rows, row_count=None):
    """构造一页 WAP 应答（answer[].txt[].content.components[].data.datas）。"""
    meta = {"extra": {"row_count": row_count if row_count is not None else len(rows)}}
    return {
        "status_code": 0,
        "status_msg": "ok",
        "data": {
            "answer": [
                {
                    "txt": [
                        {
                            "content": {
                                "components": [
                                    {
                                        "show_type": "xuangu_tableV1",
                                        "data": {"datas": rows, "meta": meta},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    }


def _row(code, name="甲", price=10.0):
    return {"股票代码": code, "股票简称": name, "最新价": price}


class TestCleanWencaiColumns:
    """列名清洗：剥日期后缀 + 去重复列。"""

    def test_strip_date_suffix(self):
        from tradex.data_sources.wencai_fetchers import _clean_wencai_columns

        df = pd.DataFrame(
            [{"股票代码[20261106]": "000525", "涨停[20261106]": "涨停"}]
        )
        out = _clean_wencai_columns(df)
        assert list(out.columns) == ["股票代码", "涨停"]

    def test_keep_columns_without_suffix(self):
        from tradex.data_sources.wencai_fetchers import _clean_wencai_columns

        df = pd.DataFrame([{"股票代码": "000525", "最新价": 5.0}])
        out = _clean_wencai_columns(df)
        assert list(out.columns) == ["股票代码", "最新价"]

    def test_drop_duplicated_columns_after_strip(self):
        from tradex.data_sources.wencai_fetchers import _clean_wencai_columns

        df = pd.DataFrame(
            [[1, 2]], columns=["涨停[20261105]", "涨停[20261106]"]
        )
        out = _clean_wencai_columns(df)
        assert list(out.columns) == ["涨停"]
        assert out.iloc[0]["涨停"] == 1  # 保留首列


class TestExtractWapTable:
    """WAP 应答表格提取。"""

    def test_extract_rows_and_row_count(self):
        from tradex.data_sources.wencai_fetchers import _extract_wap_table

        payload = _wap_payload([_row("000525"), _row("000595")], row_count=33)
        df, count = _extract_wap_table(payload["data"])
        assert len(df) == 2
        assert count == 33
        assert df.iloc[0]["股票代码"] == "000525"

    def test_extract_no_table_returns_empty(self):
        from tradex.data_sources.wencai_fetchers import _extract_wap_table

        df, count = _extract_wap_table({"answer": []})
        assert df.empty
        assert count is None

    def test_extract_missing_data_key(self):
        from tradex.data_sources.wencai_fetchers import _extract_wap_table

        df, count = _extract_wap_table({})
        assert df.empty
        assert count is None


class TestFetchWencaiQuery:
    """fetch_wencai_query 主流程（mock WAP 请求）。"""

    def test_empty_query_returns_empty(self):
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        assert fetch_wencai_query("").empty

    def test_single_page_success(self):
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        payload = _wap_payload([_row("000525"), _row("000595")], row_count=2)
        with patch(
            "tradex.data_sources.wencai_fetchers._get_hexin_v",
            return_value="tok",
        ), patch(
            "tradex.data_sources.wencai_fetchers._wencai_wap_request",
            return_value=payload["data"],
        ) as m_req:
            df = fetch_wencai_query("2026年11月6日涨停")
        assert len(df) == 2
        assert list(df.columns) == ["股票代码", "股票简称", "最新价"]
        # 达到 row_count 后不再翻页
        assert m_req.call_count == 1

    def test_locked_page_detection_stops_pagination(self):
        """锁页保护：第 2 页与第 1 页首行相同 → 停止，不无限拼接。"""
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        payload = _wap_payload(
            [_row(f"00000{i}") for i in range(1, 4)], row_count=100
        )
        with patch(
            "tradex.data_sources.wencai_fetchers._get_hexin_v",
            return_value="tok",
        ), patch(
            "tradex.data_sources.wencai_fetchers._wencai_wap_request",
            return_value=payload["data"],
        ) as m_req, patch(
            "tradex.data_sources.wencai_fetchers.time.sleep"
        ):
            df = fetch_wencai_query("2026年11月6日涨停")
        # 第 2 页首行指纹相同 → break，共 2 次请求、10 行不重复拼接
        assert m_req.call_count == 2
        assert len(df) == 3

    def test_pagination_concat_distinct_pages(self):
        """未来解锁翻页时：不同页数据正常拼接直到 row_count。"""
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        pages = [
            _wap_payload([_row(f"00000{i}") for i in range(1, 4)], row_count=5)["data"],
            _wap_payload([_row(f"00000{i}") for i in range(4, 6)], row_count=5)["data"],
        ]
        with patch(
            "tradex.data_sources.wencai_fetchers._get_hexin_v",
            return_value="tok",
        ), patch(
            "tradex.data_sources.wencai_fetchers._wencai_wap_request",
            side_effect=pages,
        ), patch(
            "tradex.data_sources.wencai_fetchers.time.sleep"
        ):
            df = fetch_wencai_query("2026年11月6日涨停")
        assert len(df) == 5

    def test_pywencai_missing_raises(self):
        """pywencai 未安装 → ImportError 抛出（SmartRouter 降级纪律）。"""
        import builtins
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("pywencai"):
                raise ImportError("No module named 'pywencai'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ImportError):
                fetch_wencai_query("2026年11月6日涨停")

    def test_abnormal_status_raises(self):
        """网关返回非 0 状态码 → RuntimeError（含 -302 缺参/风控拒绝）。"""
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        bad = {"status_code": -302, "status_msg": "缺少必要参数", "data": {}}
        with patch(
            "tradex.data_sources.wencai_fetchers._get_hexin_v",
            return_value="tok",
        ), patch(
            "tradex.data_sources.wencai_fetchers._wencai_wap_request",
            side_effect=RuntimeError("问财WAP返回异常 status_code=-302"),
        ):
            with pytest.raises(RuntimeError):
                fetch_wencai_query("2026年11月6日涨停")

    def test_sort_key_local_sort(self):
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        payload = _wap_payload(
            [_row("000525", price=5.0), _row("000595", price=9.0)], row_count=2
        )
        with patch(
            "tradex.data_sources.wencai_fetchers._get_hexin_v",
            return_value="tok",
        ), patch(
            "tradex.data_sources.wencai_fetchers._wencai_wap_request",
            return_value=payload["data"],
        ):
            df = fetch_wencai_query("涨停", sort_key="最新价", sort_order="desc")
        assert df.iloc[0]["最新价"] == 9.0

    def test_sort_key_missing_column_ignored(self):
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        payload = _wap_payload([_row("000525")], row_count=1)
        with patch(
            "tradex.data_sources.wencai_fetchers._get_hexin_v",
            return_value="tok",
        ), patch(
            "tradex.data_sources.wencai_fetchers._wencai_wap_request",
            return_value=payload["data"],
        ):
            df = fetch_wencai_query("涨停", sort_key="不存在的列")
        assert len(df) == 1  # 忽略排序，不抛错


class TestRshUnlock:
    """rsh 解锁 perpage（2026-11-08 票3）：请求必须带随机 rsh，perpage 可上探。"""

    def test_request_carries_rsh_and_perpage(self):
        from tradex.data_sources.wencai_fetchers import _wencai_wap_request

        captured = {}
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"status_code": 0, "data": {}}

        def fake_post(url, headers=None, data=None, timeout=None):
            captured.update(data or {})
            return resp

        session = MagicMock()
        session.post.side_effect = fake_post
        _wencai_wap_request(session, "tok", "涨停", "stock", page=1)
        import uuid as _uuid
        assert len(captured.get("rsh", "")) == 32  # uuid4().hex
        assert captured.get("perpage") == "100"

    def test_perpage_clamped_to_server_max(self):
        from tradex.data_sources.wencai_fetchers import (
            WENCAI_PERPAGE_MAX,
            _wencai_wap_request,
        )

        captured = {}
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"status_code": 0, "data": {}}
        session = MagicMock()
        session.post.side_effect = lambda url, **kw: (
            captured.update(kw.get("data") or {}), resp)[1]
        _wencai_wap_request(session, "tok", "涨停", "stock", page=1, perpage=99999)
        assert captured.get("perpage") == str(WENCAI_PERPAGE_MAX)


class TestSessionDirectConnect:
    """直连铁律：WAP 会话必须禁读代理环境变量。"""

    def test_session_trust_env_disabled(self):
        from tradex.data_sources.wencai_fetchers import _wencai_wap_session

        session = _wencai_wap_session()
        assert session.trust_env is False


class TestFetchReasonsMerge:
    """消费方合并制（shortline_service.fetch_reasons）：问财优先、同花顺补缺。"""

    def _svc(self):
        from tradex.service import shortline_service as svc

        return svc

    def test_merge_wencai_priority_over_ths(self):
        svc = self._svc()
        with patch.object(
            svc,
            "_reasons_from_wencai",
            return_value={"000525": "问财原因", "000595": "共有着"},
        ), patch.object(
            svc, "_reasons_from_ths", return_value={"001258": "同花顺原因", "000595": "共有着"}
        ):
            reasons, source, problems = svc.fetch_reasons("20261106")
        assert reasons == {
            "000525": "问财原因",
            "000595": "共有着",  # 问财覆盖同花顺
            "001258": "同花顺原因",
        }
        assert source == "问财+同花顺补缺"
        assert problems == []

    def test_wencai_only(self):
        svc = self._svc()
        with patch.object(
            svc, "_reasons_from_wencai", return_value={"000525": "问财原因"}
        ), patch.object(
            svc, "_reasons_from_ths", return_value={}
        ):
            reasons, source, problems = svc.fetch_reasons("20261106")
        assert reasons == {"000525": "问财原因"}
        assert source == "问财"
        assert problems == ["同花顺归因为空"]

    def test_ths_fallback_when_wencai_empty(self):
        svc = self._svc()
        with patch.object(
            svc, "_reasons_from_wencai", return_value={}
        ), patch.object(
            svc, "_reasons_from_ths", return_value={"001258": "同花顺原因"}
        ):
            reasons, source, problems = svc.fetch_reasons("20261106")
        assert reasons == {"001258": "同花顺原因"}
        assert source == "同花顺涨停归因"
        assert "问财返回空（无 key 或未覆盖）" in problems

    def test_both_fail_returns_empty(self):
        svc = self._svc()
        with patch.object(
            svc, "_reasons_from_wencai", side_effect=RuntimeError("依赖缺失")
        ), patch.object(
            svc, "_reasons_from_ths", side_effect=RuntimeError("同花顺挂了")
        ):
            reasons, source, problems = svc.fetch_reasons("20261106")
        assert reasons == {}
        assert source == "无（问财与同花顺均失败）"
        assert len(problems) == 2


@pytest.mark.network
class TestWencaiNetworkSmoke:
    """真实联网冒烟（pytest -m network 单独跑，不进默认回归集）。"""

    def test_real_query_limit_up_full(self):
        from tradex.data_sources.wencai_fetchers import fetch_wencai_query

        df = fetch_wencai_query("2026年11月6日涨停")
        assert not df.empty
        assert "股票代码" in df.columns
        # 2026-11-08 rsh 解锁后：一次拿全量（2026-11-06 涨停 33 只，问财口径）
        assert len(df) >= 30
        assert df["股票代码"].nunique() == len(df)
