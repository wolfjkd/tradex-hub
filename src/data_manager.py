#!/usr/bin/env python3
"""
data_manager.py - 多数据源管理器
=================================
基于 daily_stock_analysis 的 data_provider 模式实现的多数据源自动降级管理器。

功能特性：
  - 支持多个数据源（eltdx、腾讯、AkShare）
  - 自动降级：主数据源失败时自动切换到备数据源
  - 自动恢复：主数据源恢复后自动切回
  - 详细日志：记录降级原因和切换过程
  - 健康检查：定期检测各数据源状态

使用方式：
  from data_manager import DataFetcherManager
  
  manager = DataFetcherManager()
  quotes = manager.get_quote(["sz000001", "sh600000"])
  auction = manager.get_auction("sz000001")
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from abc import ABC, abstractmethod

from .eltdx_provider import (
    EltdxProvider,
    AuctionData,
    TickData,
    F10Data,
    QuoteSnapshot,
    MinuteData
)

logger = logging.getLogger(__name__)


# ============================================================
# 数据源抽象基类
# ============================================================

class DataProvider(ABC):
    """数据提供者抽象基类"""
    
    NAME = "base"
    PRIORITY = 100  # 优先级：数字越小优先级越高
    
    @abstractmethod
    def get_quote(self, codes: List[str]) -> Dict[str, QuoteSnapshot]:
        """获取行情快照"""
        pass
    
    @abstractmethod
    def get_auction(self, code: str) -> AuctionData:
        """获取集合竞价数据"""
        pass
    
    @abstractmethod
    def get_ticks(self, code: str, date: str) -> TickData:
        """获取逐笔成交数据"""
        pass
    
    @abstractmethod
    def get_minute(self, code: str) -> MinuteData:
        """获取分时数据"""
        pass
    
    @abstractmethod
    def get_f10(self, code: str) -> F10Data:
        """获取F10资料"""
        pass
    
    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        pass
    
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        try:
            result = self.health_check()
            return result.get("status") == "healthy"
        except Exception:
            return False


# ============================================================
# Eltdx 数据源实现
# ============================================================

class EltdxDataProvider(DataProvider):
    """基于 eltdx 的数据提供者（主数据源）"""
    
    NAME = "eltdx"
    PRIORITY = 10
    
    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.provider = None
    
    def _ensure_connected(self):
        if self.provider is None:
            try:
                self.provider = EltdxProvider(timeout=self.timeout)
                self.provider.__enter__()
            except Exception as e:
                logger.warning(f"eltdx 连接失败: {e}")
                self.provider = None
    
    def get_quote(self, codes: List[str]) -> Dict[str, QuoteSnapshot]:
        self._ensure_connected()
        if self.provider:
            try:
                return self.provider.get_quote(codes)
            except Exception as e:
                logger.error(f"eltdx get_quote 失败: {e}")
                self.provider = None
        return {}
    
    def get_auction(self, code: str) -> AuctionData:
        self._ensure_connected()
        if self.provider:
            try:
                return self.provider.get_auction(code)
            except Exception as e:
                logger.error(f"eltdx get_auction 失败: {e}")
                self.provider = None
        return AuctionData(code=code, status="error", error_message="eltdx不可用")
    
    def get_ticks(self, code: str, date: str) -> TickData:
        self._ensure_connected()
        if self.provider:
            try:
                return self.provider.get_ticks(code, date)
            except Exception as e:
                logger.error(f"eltdx get_ticks 失败: {e}")
                self.provider = None
        return TickData(code=code, date=date, status="error", error_message="eltdx不可用")
    
    def get_minute(self, code: str) -> MinuteData:
        self._ensure_connected()
        if self.provider:
            try:
                return self.provider.get_minute(code)
            except Exception as e:
                logger.error(f"eltdx get_minute 失败: {e}")
                self.provider = None
        return MinuteData(code=code, status="error", error_message="eltdx不可用")
    
    def get_f10(self, code: str) -> F10Data:
        self._ensure_connected()
        if self.provider:
            try:
                return self.provider.get_f10(code)
            except Exception as e:
                logger.error(f"eltdx get_f10 失败: {e}")
                self.provider = None
        return F10Data(code=code, status="error", error_message="eltdx不可用")
    
    def health_check(self) -> Dict[str, Any]:
        self._ensure_connected()
        if self.provider:
            try:
                return self.provider.health_check()
            except Exception as e:
                return {"status": "unhealthy", "error": str(e)}
        return {"status": "unhealthy", "error": "未连接"}


# ============================================================
# 腾讯数据源实现
# ============================================================

class TencentDataProvider(DataProvider):
    """基于腾讯行情接口的数据提供者（备用数据源）"""
    
    NAME = "tencent"
    PRIORITY = 20
    
    def __init__(self):
        self.session = None
    
    def _get_session(self):
        if self.session is None:
            import requests
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
        return self.session
    
    def get_quote(self, codes: List[str]) -> Dict[str, QuoteSnapshot]:
        try:
            session = self._get_session()
            result = {}
            
            for code in codes:
                market = "sh" if code.startswith("sh") else "sz"
                pure_code = code[2:] if len(code) > 6 else code
                
                url = f"https://qt.gtimg.cn/q={market}{pure_code}"
                response = session.get(url, timeout=5)
                
                if response.status_code == 200:
                    data = response.text
                    parts = data.split("~")
                    if len(parts) >= 10:
                        try:
                            result[code] = QuoteSnapshot(
                                code=code,
                                price=self._safe_float(parts[3], 0),
                                change=self._safe_float(parts[4], 0),
                                change_pct=self._safe_float(parts[5], 0),
                                open=self._safe_float(parts[1], 0),
                                high=self._safe_float(parts[44], 0) if len(parts) > 44 else 0,
                                low=self._safe_float(parts[45], 0) if len(parts) > 45 else 0,
                                volume=self._safe_int(parts[6], 0),
                                amount=self._safe_float(parts[37], 0) if len(parts) > 37 else 0
                            )
                        except Exception as parse_e:
                            logger.debug(f"解析腾讯数据失败 {code}: {parse_e}")
            
            return result
        except Exception as e:
            logger.error(f"tencent get_quote 失败: {e}")
            return {}
    
    def _safe_float(self, value, default=0):
        """安全转换为float"""
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _safe_int(self, value, default=0):
        """安全转换为int"""
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    def get_auction(self, code: str) -> AuctionData:
        try:
            session = self._get_session()
            market = "sh" if code.startswith("sh") else "sz"
            pure_code = code[2:] if len(code) > 6 else code
            
            url = f"https://qt.gtimg.cn/q={market}{pure_code}"
            response = session.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.text
                parts = data.split("~")
                if len(parts) >= 46:
                    return AuctionData(
                        code=code,
                        status="success",
                        last_price=float(parts[3]),
                        last_matched_volume=int(parts[6])
                    )
            
            return AuctionData(code=code, status="no_data")
        except Exception as e:
            logger.error(f"tencent get_auction 失败: {e}")
            return AuctionData(code=code, status="error", error_message=str(e))
    
    def get_ticks(self, code: str, date: str) -> TickData:
        logger.warning("tencent 不支持逐笔成交数据，返回空数据")
        return TickData(code=code, date=date, status="no_data")
    
    def get_minute(self, code: str) -> MinuteData:
        try:
            session = self._get_session()
            market = "sh" if code.startswith("sh") else "sz"
            pure_code = code[2:] if len(code) > 6 else code
            
            url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/getTimeData?param={market}{pure_code},m1,,1440"
            response = session.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                data_key = f"{market}{pure_code}"
                if data_key in data.get("data", {}):
                    points = []
                    for item in data["data"][data_key].get("data", []):
                        points.append({
                            "time_label": item[0],
                            "price": float(item[1]),
                            "avg_price": float(item[2]),
                            "volume": int(item[5])
                        })
                    return MinuteData(
                        code=code,
                        status="success",
                        points=points
                    )
            
            return MinuteData(code=code, status="no_data")
        except Exception as e:
            logger.error(f"tencent get_minute 失败: {e}")
            return MinuteData(code=code, status="error", error_message=str(e))
    
    def get_f10(self, code: str) -> F10Data:
        logger.warning("tencent 不支持F10资料，返回空数据")
        return F10Data(code=code, status="no_data")
    
    def health_check(self) -> Dict[str, Any]:
        start = time.time()
        try:
            quotes = self.get_quote(["sz000001"])
            latency = (time.time() - start) * 1000
            return {
                "status": "healthy" if quotes else "unhealthy",
                "latency_ms": round(latency, 1),
                "tests": {
                    "quote": {
                        "status": "ok" if quotes else "fail",
                        "latency_ms": round(latency, 1)
                    }
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "error": str(e)
            }


# ============================================================
# AkShare 数据源实现（可选）
# ============================================================

class AkShareDataProvider(DataProvider):
    """基于 AkShare 的数据提供者（三级备用数据源）"""
    
    NAME = "akshare"
    PRIORITY = 30
    
    def __init__(self):
        self.ak = None
    
    def _ensure_akshare(self):
        if self.ak is None:
            try:
                import akshare as ak
                self.ak = ak
            except ImportError:
                logger.warning("akshare 未安装，跳过此数据源")
                return False
        return True
    
    def get_quote(self, codes: List[str]) -> Dict[str, QuoteSnapshot]:
        if not self._ensure_akshare():
            return {}
        
        try:
            result = {}
            for code in codes:
                pure_code = code[2:] if len(code) > 6 else code
                
                try:
                    df = self.ak.stock_zh_a_spot_em()
                    row = df[df["代码"] == pure_code]
                    if not row.empty:
                        data = row.iloc[0]
                        result[code] = QuoteSnapshot(
                            code=code,
                            price=float(data.get("最新价", 0)),
                            change=float(data.get("涨跌额", 0)),
                            change_pct=float(data.get("涨跌幅", 0)),
                            open=float(data.get("今开", 0)),
                            high=float(data.get("最高", 0)),
                            low=float(data.get("最低", 0)),
                            volume=int(data.get("成交量", 0)),
                            amount=float(data.get("成交额", 0))
                        )
                except Exception:
                    continue
            
            return result
        except Exception as e:
            logger.error(f"akshare get_quote 失败: {e}")
            return {}
    
    def get_auction(self, code: str) -> AuctionData:
        logger.warning("akshare 不支持集合竞价数据，返回空数据")
        return AuctionData(code=code, status="no_data")
    
    def get_ticks(self, code: str, date: str) -> TickData:
        logger.warning("akshare 不支持逐笔成交数据，返回空数据")
        return TickData(code=code, date=date, status="no_data")
    
    def get_minute(self, code: str) -> MinuteData:
        if not self._ensure_akshare():
            return MinuteData(code=code, status="error", error_message="akshare未安装")
        
        try:
            pure_code = code[2:] if len(code) > 6 else code
            df = self.ak.stock_zh_a_minute(symbol=pure_code, period="1")
            
            if df is not None and not df.empty:
                points = []
                for _, row in df.iterrows():
                    points.append({
                        "time_label": str(row.get("datetime", "")),
                        "price": float(row.get("close", 0)),
                        "avg_price": float(row.get("close", 0)),
                        "volume": int(row.get("volume", 0))
                    })
                return MinuteData(
                    code=code,
                    status="success",
                    points=points
                )
            
            return MinuteData(code=code, status="no_data")
        except Exception as e:
            logger.error(f"akshare get_minute 失败: {e}")
            return MinuteData(code=code, status="error", error_message=str(e))
    
    def get_f10(self, code: str) -> F10Data:
        if not self._ensure_akshare():
            return F10Data(code=code, status="error", error_message="akshare未安装")
        
        try:
            pure_code = code[2:] if len(code) > 6 else code
            df = self.ak.stock_f10_ths(stock=pure_code)
            
            if df is not None and not df.empty:
                return F10Data(
                    code=code,
                    status="success"
                )
            
            return F10Data(code=code, status="no_data")
        except Exception as e:
            logger.error(f"akshare get_f10 失败: {e}")
            return F10Data(code=code, status="error", error_message=str(e))
    
    def health_check(self) -> Dict[str, Any]:
        if not self._ensure_akshare():
            return {"status": "unhealthy", "error": "akshare未安装"}
        
        start = time.time()
        try:
            result = self.get_quote(["sz000001"])
            latency = (time.time() - start) * 1000
            return {
                "status": "healthy" if result else "unhealthy",
                "latency_ms": round(latency, 1),
                "tests": {
                    "quote": {
                        "status": "ok" if result else "fail",
                        "latency_ms": round(latency, 1)
                    }
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "error": str(e)
            }


# ============================================================
# 数据源管理器
# ============================================================

class DataFetcherManager:
    """
    多数据源管理器，支持自动降级和自动恢复。
    
    使用示例：
        manager = DataFetcherManager()
        
        # 获取行情快照（自动选择最优数据源）
        quotes = manager.get_quote(["sz000001", "sh600000"])
        
        # 获取集合竞价（优先使用eltdx）
        auction = manager.get_auction("sz000001")
        
        # 检查当前使用的数据源
        current = manager.get_current_provider_name()
        print(f"当前数据源: {current}")
    """
    
    def __init__(self, providers: Optional[List[DataProvider]] = None):
        """
        初始化数据源管理器。
        
        Args:
            providers: 自定义数据源列表，默认使用 eltdx + tencent + akshare
        """
        if providers is None:
            self.providers = [
                EltdxDataProvider(),
                TencentDataProvider(),
                AkShareDataProvider(),
            ]
        else:
            self.providers = providers
        
        # 按优先级排序
        self.providers.sort(key=lambda p: p.PRIORITY)
        
        self._current_provider_index = 0
        self._failure_count = {}
        self._last_fallback_time = {}
        self._recovery_check_interval = 60  # 恢复检查间隔（秒）
        
        for p in self.providers:
            self._failure_count[p.NAME] = 0
            self._last_fallback_time[p.NAME] = 0
        
        logger.info(f"DataFetcherManager 初始化完成，数据源: {[p.NAME for p in self.providers]}")
    
    def _get_provider_by_name(self, name: str) -> Optional[DataProvider]:
        """按名称获取数据源"""
        for p in self.providers:
            if p.NAME == name:
                return p
        return None
    
    def _should_recover(self, provider_name: str) -> bool:
        """检查是否应该尝试恢复到高优先级数据源"""
        last_fallback = self._last_fallback_time[provider_name]
        if last_fallback == 0:
            return False
        
        elapsed = time.time() - last_fallback
        return elapsed >= self._recovery_check_interval
    
    def _switch_provider(self, reason: str = "") -> bool:
        """
        切换到下一个可用的数据源。
        
        Args:
            reason: 切换原因
        
        Returns:
            bool: 是否成功切换
        """
        current_name = self.providers[self._current_provider_index].NAME
        
        for i in range(len(self.providers)):
            idx = (self._current_provider_index + 1 + i) % len(self.providers)
            if idx == self._current_provider_index:
                continue
            
            provider = self.providers[idx]
            
            # 检查是否应该尝试恢复
            if idx < self._current_provider_index and not self._should_recover(provider.NAME):
                continue
            
            # 检查数据源是否可用
            if provider.is_available():
                old_name = self.providers[self._current_provider_index].NAME
                self._current_provider_index = idx
                self._last_fallback_time[old_name] = time.time()
                self._failure_count[old_name] += 1
                
                logger.warning(
                    f"数据源切换: {old_name} -> {provider.NAME}, 原因: {reason}, "
                    f"失败次数: {self._failure_count[old_name]}"
                )
                return True
        
        logger.error(f"所有数据源都不可用！当前: {current_name}")
        return False
    
    def _execute_with_fallback(self, method_name: str, *args, **kwargs) -> Any:
        """
        执行方法，失败时自动降级。
        
        Args:
            method_name: 要执行的方法名
            *args: 位置参数
            **kwargs: 关键字参数
        
        Returns:
            Any: 方法执行结果
        """
        max_retries = len(self.providers)
        
        for attempt in range(max_retries):
            provider = self.providers[self._current_provider_index]
            
            try:
                method = getattr(provider, method_name)
                result = method(*args, **kwargs)
                
                # 检查结果是否有效
                if self._is_result_valid(method_name, result):
                    # 如果之前降级过，尝试恢复
                    if self._current_provider_index > 0 and self._should_recover(provider.NAME):
                        for i in range(self._current_provider_index):
                            if self.providers[i].is_available():
                                old_name = provider.NAME
                                self._current_provider_index = i
                                logger.info(f"数据源恢复: {old_name} -> {self.providers[i].NAME}")
                                break
                    
                    return result
                else:
                    raise ValueError("返回结果无效")
            
            except Exception as e:
                logger.debug(f"数据源 {provider.NAME} {method_name} 失败: {e}")
                
                # 尝试切换数据源
                if attempt < max_retries - 1:
                    self._switch_provider(str(e))
        
        # 所有数据源都失败
        provider = self.providers[self._current_provider_index]
        logger.error(f"所有数据源 {method_name} 都失败，返回默认值")
        return self._get_default_result(method_name, *args)
    
    def _is_result_valid(self, method_name: str, result: Any) -> bool:
        """检查返回结果是否有效"""
        if result is None:
            return False
        
        if method_name == "get_quote":
            return len(result) > 0
        
        if method_name in ("get_auction", "get_ticks", "get_minute", "get_f10"):
            return result.status == "success"
        
        return True
    
    def _get_default_result(self, method_name: str, *args) -> Any:
        """获取默认返回值"""
        if method_name == "get_quote":
            return {}
        
        code = args[0] if args else ""
        if method_name == "get_auction":
            return AuctionData(code=code, status="error", error_message="所有数据源不可用")
        if method_name == "get_ticks":
            date = args[1] if len(args) > 1 else ""
            return TickData(code=code, date=date, status="error", error_message="所有数据源不可用")
        if method_name == "get_minute":
            return MinuteData(code=code, status="error", error_message="所有数据源不可用")
        if method_name == "get_f10":
            return F10Data(code=code, status="error", error_message="所有数据源不可用")
        
        return None
    
    # ============================================================
    # 对外接口
    # ============================================================
    
    def get_quote(self, codes: List[str]) -> Dict[str, QuoteSnapshot]:
        """
        获取行情快照。
        
        Args:
            codes: 股票代码列表，如 ['sz000001', 'sh600000']
        
        Returns:
            {code: QuoteSnapshot}字典
        """
        return self._execute_with_fallback("get_quote", codes)
    
    def get_auction(self, code: str) -> AuctionData:
        """
        获取集合竞价数据。
        
        Args:
            code: 股票代码，如 'sz000001'
        
        Returns:
            AuctionData对象
        """
        return self._execute_with_fallback("get_auction", code)
    
    def get_ticks(self, code: str, date: str) -> TickData:
        """
        获取逐笔成交数据。
        
        Args:
            code: 股票代码，如 'sz000001'
            date: 日期，如 '20260604'
        
        Returns:
            TickData对象
        """
        return self._execute_with_fallback("get_ticks", code, date)
    
    def get_minute(self, code: str) -> MinuteData:
        """
        获取分时数据。
        
        Args:
            code: 股票代码，如 'sz000001'
        
        Returns:
            MinuteData对象
        """
        return self._execute_with_fallback("get_minute", code)
    
    def get_f10(self, code: str) -> F10Data:
        """
        获取F10资料。
        
        Args:
            code: 股票代码，如 '000001'
        
        Returns:
            F10Data对象
        """
        return self._execute_with_fallback("get_f10", code)
    
    def get_current_provider_name(self) -> str:
        """获取当前使用的数据源名称"""
        return self.providers[self._current_provider_index].NAME
    
    def get_provider_status(self) -> Dict[str, Any]:
        """获取所有数据源状态"""
        status = {}
        for i, provider in enumerate(self.providers):
            health = provider.health_check()
            status[provider.NAME] = {
                "priority": provider.PRIORITY,
                "is_current": i == self._current_provider_index,
                "is_available": health.get("status") == "healthy",
                "health": health,
                "failure_count": self._failure_count[provider.NAME],
                "last_fallback_time": self._last_fallback_time[provider.NAME]
            }
        return status
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        start = time.time()
        current = self.providers[self._current_provider_index]
        health = current.health_check()
        
        return {
            "status": health["status"],
            "current_provider": current.NAME,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "provider_status": self.get_provider_status()
        }


# ============================================================
# 全局单例
# ============================================================

_global_manager = None


def get_global_manager() -> DataFetcherManager:
    """获取全局数据源管理器单例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = DataFetcherManager()
    return _global_manager


# ============================================================
# CLI测试
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    
    print("=== DataFetcherManager 测试 ===\n")
    
    manager = DataFetcherManager()
    
    # 1. 健康检查
    print("1. 健康检查...")
    health = manager.health_check()
    print(f"   状态: {health['status']}")
    print(f"   当前数据源: {health['current_provider']}")
    print(f"   延迟: {health['latency_ms']}ms")
    
    # 2. 获取行情快照
    print("\n2. 获取行情快照...")
    quotes = manager.get_quote(["sz000001", "sh600000"])
    print(f"   当前数据源: {manager.get_current_provider_name()}")
    for code, quote in quotes.items():
        print(f"   {code}: {quote.price}元 ({quote.change_pct:+.2f}%)")
    
    # 3. 获取集合竞价
    print("\n3. 获取集合竞价...")
    auction = manager.get_auction("sz000001")
    print(f"   状态: {auction.status}")
    if auction.status == "success":
        print(f"   价格: {auction.last_price}元")
        print(f"   匹配量: {auction.last_matched_volume}手")
    
    # 4. 获取数据源状态
    print("\n4. 数据源状态...")
    status = manager.get_provider_status()
    for name, info in status.items():
        print(f"   {name}: {'当前' if info['is_current'] else '备用'} | "
              f"可用: {'是' if info['is_available'] else '否'} | "
              f"失败次数: {info['failure_count']}")
    
    print("\n=== 测试完成 ===")