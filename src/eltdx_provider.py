#!/usr/bin/env python3
"""
eltdx_provider.py - 通达信行情协议数据提供者
============================================
基于eltdx库（https://github.com/electkismet/eltdx/）封装的标准化数据提供者。

独有数据源（腾讯接口无此功能）：
  - 集合竞价数据（Call Auction）
  - 逐笔成交数据（Tick Data）
  - F10资料数据（公司概况/热点题材/财务诊断）

互补数据源：
  - 行情快照（比腾讯延迟更低）
  - 分时数据（与腾讯接口互补）
  - K线数据（与腾讯接口互补）

使用方式：
  from eltdx_provider import EltdxProvider

  with EltdxProvider() as provider:
      # 集合竞价数据（开盘前）
      auction = provider.get_auction("sz000001")
      
      # 逐笔成交数据
      ticks = provider.get_ticks("sz000001", "20260604")
      
      # F10资料
      f10 = provider.get_f10("000001")
      
      # 行情快照
      quote = provider.get_quote(["sz000001", "sh600000"])
      
      # 分时数据
      minute = provider.get_minute("sz000001")
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

try:
    from eltdx import TdxClient
    ELTDX_AVAILABLE = True
except ImportError:
    ELTDX_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class AuctionPoint:
    """集合竞价数据点"""
    time_label: str
    price: float
    matched_volume: int
    unmatched_volume: int
    matched_amount: float = 0.0


@dataclass
class AuctionData:
    """集合竞价数据"""
    code: str
    status: str  # success/no_data/error
    points: list[AuctionPoint] = field(default_factory=list)
    last_price: float = 0.0
    last_matched_volume: int = 0
    total_amount: float = 0.0
    error_message: str = ""


@dataclass
class TickRecord:
    """逐笔成交记录"""
    time: str
    price: float
    volume: int
    amount: float
    buy_or_sell: str  # buy/sell


@dataclass
class TickData:
    """逐笔成交数据"""
    code: str
    date: str
    status: str  # success/no_data/error
    ticks: list[TickRecord] = field(default_factory=list)
    buy_count: int = 0
    sell_count: int = 0
    total_amount: float = 0.0
    error_message: str = ""


@dataclass
class CompanyProfile:
    """公司概况"""
    name: str = ""
    industry: str = ""
    list_date: str = ""
    main_business: str = ""


@dataclass
class HotTopic:
    """热点题材"""
    name: str
    relevance: str = ""
    reason: str = ""


@dataclass
class FinanceDiagnosis:
    """财务诊断"""
    score: str = ""
    operation: str = ""
    profit: str = ""
    growth: str = ""


@dataclass
class F10Data:
    """F10资料数据"""
    code: str
    status: str  # success/no_data/error
    profile: Optional[CompanyProfile] = None
    topics: list[HotTopic] = field(default_factory=list)
    finance: Optional[FinanceDiagnosis] = None
    error_message: str = ""


@dataclass
class QuoteSnapshot:
    """行情快照"""
    code: str
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    amount: float = 0.0
    inside: int = 0
    outer: int = 0


@dataclass
class MinutePoint:
    """分时数据点"""
    time_label: str
    price: float
    avg_price: float
    volume: int


@dataclass
class MinuteData:
    """分时数据"""
    code: str
    status: str  # success/no_data/error
    points: list[MinutePoint] = field(default_factory=list)
    trading_date: str = ""
    prev_close: float = 0.0
    open_price: float = 0.0
    avg_price: float = 0.0
    error_message: str = ""


@dataclass
class KlineBar:
    """K线数据点"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float = 0.0


@dataclass
class KlineData:
    """K线数据"""
    code: str
    status: str  # success/no_data/error
    bars: list[KlineBar] = field(default_factory=list)
    error_message: str = ""


# ============================================================
# EltdxProvider 主类
# ============================================================

class EltdxProvider:
    """
    通达信行情协议数据提供者。
    
    特点：
    - 独有数据源：集合竞价、逐笔成交、F10资料
    - 低延迟：本地TCP连接，延迟<150ms
    - 免费开源：MIT License
    
    使用示例：
        with EltdxProvider() as provider:
            auction = provider.get_auction("sz000001")
    """
    
    NAME = "eltdx"
    VERSION = "1.0.2"
    
    def __init__(self, timeout: int = 5) -> None:
        """
        初始化提供者。
        
        Args:
            timeout: 连接超时时间（秒）
        """
        if not ELTDX_AVAILABLE:
            raise ImportError("eltdx库未安装，请运行: pip install eltdx")
        
        self.timeout = timeout
        self.client = None

    def __enter__(self) -> "EltdxProvider":
        self.client = TdxClient(timeout=self.timeout)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.client:
            self.client.close()
    
    # ============================================================
    # 独有数据源（腾讯接口无此功能）
    # ============================================================
    
    def get_auction(self, code: str) -> AuctionData:
        """
        获取集合竞价数据（独有功能）。
        
        集合竞价发生在开盘前（9:15-9:25），用于确定开盘价。
        腾讯接口无法获取此数据。
        
        Args:
            code: 股票代码，如 'sz000001'
        
        Returns:
            AuctionData对象
        """
        try:
            auction = self.client.get_call_auction(code)
            
            if not auction.points:
                return AuctionData(code=code, status="no_data")
            
            # 计算竞价总额
            total_amount = sum(
                p.matched_amount_estimated 
                for p in auction.points 
                if p.matched_amount_estimated
            )
            
            # 转换为标准格式
            points = [
                AuctionPoint(
                    time_label=p.time_label,
                    price=p.price,
                    matched_volume=p.matched_volume,
                    unmatched_volume=p.unmatched_volume,
                    matched_amount=p.matched_amount_estimated or 0.0
                )
                for p in auction.points
            ]
            
            last_point = auction.points[-1]
            
            return AuctionData(
                code=code,
                status="success",
                points=points,
                last_price=last_point.price,
                last_matched_volume=last_point.matched_volume,
                total_amount=total_amount
            )
        except Exception as e:
            logger.exception("获取集合竞价数据失败: code=%s", code)
            return AuctionData(
                code=code,
                status="error",
                error_message=str(e)
            )
    
    def get_ticks(self, code: str, date: str) -> TickData:
        """
        获取逐笔成交数据（独有功能）。
        
        每笔成交明细，包含时间、价格、数量、买卖方向。
        腾讯接口无法获取此数据。
        
        Args:
            code: 股票代码，如 'sz000001'
            date: 日期，如 '20260604' 或 '2026-06-04'
        
        Returns:
            TickData对象
        """
        try:
            # 标准化日期格式
            date = date.replace('-', '')
            
            ticks = self.client.get_history_trade_day(code, date)
            
            if not ticks.ticks:
                return TickData(code=code, date=date, status="no_data")
            
            # 统计买卖方向
            buy_count = sum(1 for t in ticks.ticks if t.buy_or_sell == 0)
            sell_count = sum(1 for t in ticks.ticks if t.buy_or_sell == 1)
            
            # 计算总成交额
            total_amount = sum(t.amount for t in ticks.ticks if t.amount)
            
            # 转换为标准格式
            tick_records = [
                TickRecord(
                    time=t.time,
                    price=t.price,
                    volume=t.volume,
                    amount=t.amount,
                    buy_or_sell="buy" if t.buy_or_sell == 0 else "sell"
                )
                for t in ticks.ticks
            ]
            
            return TickData(
                code=code,
                date=date,
                status="success",
                ticks=tick_records,
                buy_count=buy_count,
                sell_count=sell_count,
                total_amount=total_amount
            )
        except Exception as e:
            logger.exception("获取逐笔成交数据失败: code=%s, date=%s", code, date)
            return TickData(
                code=code,
                date=date,
                status="error",
                error_message=str(e)
            )
    
    def get_f10(self, code: str) -> F10Data:
        """
        获取F10资料数据（独有功能）。
        
        包含公司概况、热点题材、财务诊断。
        腾讯接口无法获取此数据。
        
        Args:
            code: 股票代码，如 '000001' 或 'sz000001'
        
        Returns:
            F10Data对象
        """
        try:
            # 去掉市场前缀，只使用6位代码
            if code.startswith(('sz', 'sh', 'bj')):
                code = code[2:]
            
            # 获取公司概况
            profile = self.client.f10.company_profile(code)
            
            # 获取热点题材
            topics = self.client.f10.hot_topics(code)
            
            # 获取财务诊断
            finance = self.client.f10.finance_diagnosis(code)
            
            # 构建公司概况
            company_profile = None
            if profile.rows:
                row = profile.rows[0]
                company_profile = CompanyProfile(
                    name=row.get('name', ''),
                    industry=row.get('industry', ''),
                    list_date=row.get('list_date', ''),
                    main_business=row.get('main_business', '')
                )
            
            # 构建热点题材列表
            hot_topics = [
                HotTopic(
                    name=t.get('topic_name', ''),
                    relevance=t.get('relevance', ''),
                    reason=t.get('reason', '')
                )
                for t in (topics.rows[:5] if topics.rows else [])
            ]
            
            # 构建财务诊断
            finance_diagnosis = None
            if finance.rows:
                row = finance.rows[0]
                finance_diagnosis = FinanceDiagnosis(
                    score=str(row.get('total_score', '')),
                    operation=str(row.get('operation_score', '')),
                    profit=str(row.get('profit_score', '')),
                    growth=str(row.get('growth_score', ''))
                )
            
            return F10Data(
                code=code,
                status="success",
                profile=company_profile,
                topics=hot_topics,
                finance=finance_diagnosis
            )
        except Exception as e:
            logger.exception("获取F10资料数据失败: code=%s", code)
            return F10Data(
                code=code,
                status="error",
                error_message=str(e)
            )
    
    # ============================================================
    # 互补数据源（与腾讯接口互补）
    # ============================================================
    
    def get_quote(self, codes: list[str]) -> dict[str, QuoteSnapshot]:
        """
        获取行情快照（与腾讯接口互补）。
        
        eltdx使用通达信私有协议，本地TCP连接，延迟更低。
        
        Args:
            codes: 股票代码列表，如 ['sz000001', 'sh600000']
        
        Returns:
            {code: QuoteSnapshot}字典
        """
        try:
            quotes = self.client.get_quote(codes)
            
            result = {}
            for code in codes:
                # 找到对应的行情数据
                quote_data = next((q for q in quotes if q.full_code == code), None)
                
                if quote_data:
                    result[code] = QuoteSnapshot(
                        code=code,
                        price=quote_data.last_price,
                        change=quote_data.change,
                        change_pct=quote_data.change_pct,
                        open=quote_data.open_price,
                        high=quote_data.high_price,
                        low=quote_data.low_price,
                        volume=quote_data.total_hand,
                        amount=quote_data.amount,
                        inside=quote_data.inside_dish,
                        outer=quote_data.outer_disc
                    )
            
            return result
        except Exception as e:
            logger.exception("获取行情快照失败: codes=%s", codes)
            return {}
    
    def get_minute(self, code: str) -> MinuteData:
        """
        获取分时数据（与腾讯接口互补）。
        
        Args:
            code: 股票代码，如 'sz000001'
        
        Returns:
            MinuteData对象
        """
        try:
            minute = self.client.get_minute(code)
            
            if not minute.points:
                return MinuteData(code=code, status="no_data")
            
            # 计算分时均价
            total_volume = sum(p.volume for p in minute.points if p.volume)
            weighted_price = sum(
                p.price * p.volume 
                for p in minute.points 
                if p.price and p.volume
            )
            avg_price = weighted_price / total_volume if total_volume > 0 else 0
            
            # 转换为标准格式
            points = [
                MinutePoint(
                    time_label=p.time_label,
                    price=p.price,
                    avg_price=p.avg_price,
                    volume=p.volume
                )
                for p in minute.points
            ]
            
            return MinuteData(
                code=code,
                status="success",
                points=points,
                trading_date=str(minute.trading_date),
                prev_close=minute.prev_close,
                open_price=minute.open_price,
                avg_price=avg_price
            )
        except Exception as e:
            logger.exception("获取分时数据失败: code=%s", code)
            return MinuteData(
                code=code,
                status="error",
                error_message=str(e)
            )
    
    def get_kline(self, code: str, period: str = "day", count: int = 500) -> KlineData:
        """
        获取 K 线数据（与腾讯/东方财富接口互补）。
        
        eltdx 使用通达信 TCP 协议，比 HTTP 接口更稳定。
        
        Args:
            code: 股票代码，如 'sz000001'
            period: K线周期，"day" / "week" / "month" / "5m" / "15m" / "30m" / "60m"
            count: 返回 K 线根数（默认 500）
        
        Returns:
            KlineData对象
        """
        try:
            result = self.client.bars.get(code, period=period, count=count)
            bars = getattr(result, "bars", None) or []
            
            if not bars:
                return KlineData(code=code, status="no_data")
            
            # 转换为标准格式
            kline_bars = [
                KlineBar(
                    date=getattr(b, "time", "").strftime("%Y-%m-%d") if getattr(b, "time") else "",
                    open=float(getattr(b, "open", 0) or 0),
                    high=float(getattr(b, "high", 0) or 0),
                    low=float(getattr(b, "low", 0) or 0),
                    close=float(getattr(b, "close", 0) or 0),
                    volume=int(getattr(b, "volume_wire_value", 0) or 0),
                    amount=float(getattr(b, "amount", 0) or 0),
                )
                for b in bars
            ]
            
            return KlineData(
                code=code,
                status="success",
                bars=kline_bars,
            )
        except Exception as e:
            logger.exception("获取K线数据失败: code=%s, period=%s", code, period)
            return KlineData(
                code=code,
                status="error",
                error_message=str(e)
            )
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def health_check(self) -> dict[str, Any]:
        """
        健康检测。
        
        Returns:
            {
                "status": "healthy" | "unhealthy",
                "latency_ms": float,
                "tests": {...}
            }
        """
        import time
        
        start = time.time()
        tests = {}
        
        try:
            # 测试行情快照
            quote_start = time.time()
            quotes = self.get_quote(["sz000001"])
            quote_latency = (time.time() - quote_start) * 1000
            tests["quote"] = {
                "status": "ok" if quotes else "fail",
                "latency_ms": round(quote_latency, 1)
            }
            
            # 测试集合竞价
            auction_start = time.time()
            auction = self.get_auction("sz000001")
            auction_latency = (time.time() - auction_start) * 1000
            tests["auction"] = {
                "status": "ok" if auction.status != "error" else "fail",
                "latency_ms": round(auction_latency, 1)
            }
            
            # 测试分时数据
            minute_start = time.time()
            minute = self.get_minute("sz000001")
            minute_latency = (time.time() - minute_start) * 1000
            tests["minute"] = {
                "status": "ok" if minute.status != "error" else "fail",
                "latency_ms": round(minute_latency, 1)
            }
            
            total_latency = (time.time() - start) * 1000
            
            # 判断整体状态
            all_ok = all(t["status"] == "ok" for t in tests.values())
            
            return {
                "status": "healthy" if all_ok else "unhealthy",
                "latency_ms": round(total_latency, 1),
                "tests": tests
            }
        except Exception as e:
            logger.exception("健康检测失败")
            return {
                "status": "unhealthy",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "error": str(e),
                "tests": tests
            }
    
    def format_auction_report(self, data: AuctionData) -> str:
        """格式化集合竞价报告"""
        if data.status != "success":
            return f"❌ {data.code}: {data.error_message or '无数据'}"
        
        return f"""
📊 {data.code} 集合竞价数据
├─ 竞价点数: {len(data.points)}
├─ 最新价格: {data.last_price} 元
├─ 匹配量: {data.last_matched_volume} 手
├─ 总成交额: {data.total_amount:,.0f} 元
└─ 最后时间: {data.points[-1].time_label if data.points else '-'}
"""
    
    def format_tick_report(self, data: TickData) -> str:
        """格式化逐笔成交报告"""
        if data.status != "success":
            return f"❌ {data.code}: {data.error_message or '无数据'}"
        
        total_ticks = len(data.ticks)
        buy_ratio = data.buy_count / total_ticks * 100 if total_ticks > 0 else 0
        
        last_tick = data.ticks[-1] if data.ticks else None
        last_tick_str = (
            f"{last_tick.time} {last_tick.price}元 {last_tick.volume}手"
            if last_tick else "-"
        )
        
        return f"""
📈 {data.code} 逐笔成交数据 ({data.date})
├─ 成交笔数: {total_ticks}
├─ 买入笔数: {data.buy_count} ({buy_ratio:.1f}%)
├─ 卖出笔数: {data.sell_count} ({100-buy_ratio:.1f}%)
├─ 总成交额: {data.total_amount:,.0f} 元
└─ 最新成交: {last_tick_str}
"""
    
    def format_f10_report(self, data: F10Data) -> str:
        """格式化F10资料报告"""
        if data.status != "success":
            return f"❌ {data.code}: {data.error_message or '无数据'}"
        
        profile = data.profile
        topics = data.topics
        finance = data.finance
        
        topics_str = '\n'.join([
            f"  • {t.name}: {t.reason}" 
            for t in topics[:3]
        ]) if topics else "  • 暂无题材数据"
        
        return f"""
🏢 {data.code} F10资料
├─ 公司名称: {profile.name if profile else '未知'}
├─ 所属行业: {profile.industry if profile else '未知'}
├─ 上市日期: {profile.list_date if profile else '未知'}
├─ 主营业务: {(profile.main_business[:50] + '...') if profile and profile.main_business else '未知'}
├─ 热点题材:
{topics_str}
└─ 财务评分: {finance.score if finance else '未知'} (运营:{finance.operation if finance else '-'} 盈利:{finance.profit if finance else '-'} 成长:{finance.growth if finance else '-'})
"""


# ============================================================
# CLI测试
# ============================================================

if __name__ == "__main__":
    print("=== EltdxProvider 测试 ===\n")
    
    if not ELTDX_AVAILABLE:
        print("❌ eltdx库未安装，请运行: pip install eltdx")
        exit(1)
    
    with EltdxProvider() as provider:
        # 健康检测
        print("1. 健康检测...")
        health = provider.health_check()
        print(f"   状态: {health['status']}, 延迟: {health['latency_ms']}ms")
        print(f"   测试详情: {json.dumps(health['tests'], ensure_ascii=False, indent=2)}")
        
        # 集合竞价数据
        print("\n2. 集合竞价数据...")
        auction = provider.get_auction("sz000001")
        print(provider.format_auction_report(auction))
        
        # 逐笔成交数据
        print("\n3. 逐笔成交数据...")
        ticks = provider.get_ticks("sz000001", "20260604")
        print(provider.format_tick_report(ticks))
        
        # F10资料
        print("\n4. F10资料...")
        f10 = provider.get_f10("000001")
        print(provider.format_f10_report(f10))
        
        # 行情快照
        print("\n5. 行情快照...")
        quotes = provider.get_quote(["sz000001", "sh600000"])
        for code, quote in quotes.items():
            print(f"   {code}: {quote.price}元 ({quote.change_pct:+.2f}%)")
        
        # 分时数据
        print("\n6. 分时数据...")
        minute = provider.get_minute("sz000001")
        if minute.status == "success":
            print(f"   数据点数: {len(minute.points)}")
            print(f"   均价: {minute.avg_price:.2f}元")
        else:
            print(f"   ❌ {minute.error_message or '无数据'}")
    
    print("\n=== 测试完成 ===")
