"""lockup 字段改版重映射测试（2026-11-10 审计 A6）。

东财 RPT_LIFT_STAGE 实测改名：LIMITED_STOCK_TYPE→FREE_SHARES_TYPE、
FREE_SHARES_NUM→CURRENT_FREE_SHARES/FREE_SHARES。旧名兜底保留，
对再次改版容忍。此前按旧名取值全空串=空壳行（ratio 有值、type/shares 全空）。
"""

from unittest.mock import patch

_NEW_ROW = {
    "SECURITY_CODE": "600170",
    "FREE_DATE": "2026-06-30",
    "FREE_SHARES_TYPE": "定向增发",
    "CURRENT_FREE_SHARES": 12345.0,
    "FREE_SHARES": 12345.0,
    "FREE_RATIO": 1.5,
}

_OLD_ROW = {
    "SECURITY_CODE": "600170",
    "FREE_DATE": "2026-06-30",
    "LIMITED_STOCK_TYPE": "定向增发",
    "FREE_SHARES_NUM": 12345.0,
    "FREE_RATIO": 1.5,
}


class TestLockupFieldMapping:
    def test_new_field_names_populate(self):
        """新字段名必须出数（2026-09-23 起旧实现空壳缺陷的回归锁）。"""
        from astock_signals.lockup import get_lockup_expiry_json

        with patch("astock_signals.lockup.em_datacenter", return_value=[_NEW_ROW]):
            result = get_lockup_expiry_json("600170", "2026-06-24", 90)
        assert result["history"], "新字段名下 history 不得为空壳"
        assert result["history"][0]["type"] == "定向增发"
        assert result["history"][0]["shares"] != ""
        assert result["upcoming"], "新字段名下 upcoming 不得为空壳"
        assert result["upcoming"][0]["shares"] != ""
        assert result["upcoming"][0]["type"] == "定向增发"

    def test_old_field_names_fallback(self):
        """旧字段名兜底仍出数（对上游再次回摆/混排容忍）。"""
        from astock_signals.lockup import get_lockup_expiry_json

        with patch("astock_signals.lockup.em_datacenter", return_value=[_OLD_ROW]):
            result = get_lockup_expiry_json("600170", "2026-06-24", 90)
        assert result["history"][0]["type"] == "定向增发"
        assert result["history"][0]["shares"] != ""


class TestLockupTextFieldMapping:
    def test_text_version_new_field_names_populate(self):
        """文本版 get_lockup_expiry 同样吃字段映射单点（批次C3）。

        2026-11-10 重映射只修了 JSON 版两处，文本版两处漏改仍读旧名
        ——正是审计「列名漂移漏一处=假 0」的现行实例，本测试锁死收敛后行为。
        """
        from astock_signals.lockup import get_lockup_expiry

        with patch("astock_signals.lockup.em_datacenter", return_value=[_NEW_ROW]):
            text = get_lockup_expiry("600170", "2026-06-24", 90)
        assert "定向增发" in text, "文本版 history 段不得空壳（新字段名必须出数）"
        assert "12345" in text

    def test_text_version_old_field_names_fallback(self):
        from astock_signals.lockup import get_lockup_expiry

        with patch("astock_signals.lockup.em_datacenter", return_value=[_OLD_ROW]):
            text = get_lockup_expiry("600170", "2026-06-24", 90)
        assert "定向增发" in text
        assert "12345" in text
