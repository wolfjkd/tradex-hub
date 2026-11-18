"""akshare 公共层（QI-ARCH-09 六上游拆分，2026-11-19）：_ak 延迟导入、周期别名、季度末工具——全部 akshare_* 子模块共享，防循环 import。"""
from __future__ import annotations
import calendar
import logging
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger("tradex.akshare")

_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}

_AK_TIMEOUT_APPLIED = False

_AK_PERIOD_ALIASES = {
    "day": "daily", "daily": "daily", "d": "daily", "1d": "daily",
    "week": "weekly", "weekly": "weekly", "w": "weekly", "1w": "weekly",
    "month": "monthly", "monthly": "monthly", "m": "monthly", "1m": "monthly",
}

def _prev_quarter_end(today: "datetime | None" = None) -> str:
    """返回「上一季度末」的真实日期，格式 YYYYMMDD。

    以真实月末为准（6→30、9→30、12→31），不再硬编码 31 日。
    今天 2026-09-14 → 所属 Q3 → 上一季度末 = 20260630。
    """
    d = (today or datetime.now()).date()
    q = (d.month - 1) // 3 + 1          # 当前季度 1-4
    py, pq = (d.year, q - 1) if q > 1 else (d.year - 1, 4)   # 上一季度
    m = _QUARTER_END_MONTH[pq]
    last_day = calendar.monthrange(py, m)[1]                  # 真实月末，不假设 31
    return f"{py}{m:02d}{last_day:02d}"


def _ak():
    """延迟导入 akshare，避免模块加载时副作用。

    工单 04（2026-11-01）：akshare 1.20.4 起对所有 requests 接口启用全局
    默认硬超时 (连接 10s / 读取 60s)，此前本项目从未显式管理超时，升级即
    被动继承隐含默认值。此处显式设定，不再依赖库的隐含行为：
      - 连接 10s：与上游默认一致，容忍慢握手；
      - 读取 30s：全市场 spot / 龙虎榜翻页等大表耗时 3–15s 量级，30s 留足
        余量；走 SmartRouter 的调用另有 12s 路由超时先行掐断（二者取小），
        本值主要保护 fetcher 内部 fallback 链等非路由直调场景。
    """
    global _AK_TIMEOUT_APPLIED
    import akshare as ak
    if not _AK_TIMEOUT_APPLIED:
        # set_timeout 是 akshare 1.20.4 与「全局默认硬超时」同期引入的 API；
        # 更旧的版本既没有此 API、也没有隐含全局超时问题，跳过即语义正确。
        # 缺属性时绝不抬源（2026-11-08：TradeX 侧 uv.lock 锁 1.19.1，无防御会令
        # akshare_em 源全灭、情绪复盘等下游五块全挂）。
        set_timeout = getattr(ak, "set_timeout", None)
        if set_timeout is not None:
            set_timeout((10, 30))
        _AK_TIMEOUT_APPLIED = True
    return ak


def _normalize_ak_period(period: str) -> str:
    """把 eltdx 风格周期名(day/week/month)转成 akshare 期望的(daily/weekly/monthly)。

    已是 akshare 风格的值保持不变；未识别的值原样透传，交由 akshare 自行报错。
    """
    key = str(period or "").strip().lower()
    return _AK_PERIOD_ALIASES.get(key, period)


def _is_arrow_escape_invalid(e: BaseException) -> bool:
    """判定是否 akshare stock_news_em 的 pyarrow ArrowInvalid 库内 bug。

    akshare stock_news_em 内部 `.str.replace(r"\\u3000",…, regex=True)` 在装了
    pyarrow 的环境由 RE2 内核执行，不支持 `\\u` 转义 → ArrowInvalid("invalid
    escape sequence")。hub venv 无 pyarrow 不触发，下游环境（如 TradeX）必炸。
    pyarrow 可导入时按 isinstance 精判；否则按类型名 + 消息特征兜底（测试用
    假异常与真 ArrowInvalid 同名同特征）。
    """
    try:
        from pyarrow.lib import ArrowInvalid  # noqa: PLC0415 仅 pyarrow 环境可导入
    except ImportError:
        return type(e).__name__ == "ArrowInvalid" or "invalid escape sequence" in str(e)
    return isinstance(e, ArrowInvalid)
