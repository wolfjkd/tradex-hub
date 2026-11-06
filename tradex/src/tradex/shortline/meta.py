"""短线端点声明式元数据（对应工单 H1）。

为什么要有这一层：
  原先每个工具把 id / 缓存 TTL / 来源 / 口径散落在函数体里，改缓存策略要
  逐个函数翻代码，端点之间口径也没法对齐。本模块把「端点是什么、从哪来、
  什么阶段能用、缓存多久、合规级别、计算函数在哪、产出哪些字段」集中成
  一份声明；工具层只负责取数 + 调计算函数 + 按元数据缓存。

缓存策略铁律（来自 vibe-astock 的 registry.json 实践）：
  1. 已收盘的日子结果不变 → 长期缓存；
  2. 没收盘的一天一律标 partial、不缓存（免得盘中的数被冻住）；
  3. 盘中 live 最多 15 秒。

只登记短线相关端点，不照搬上游 182 个——没有消费者的元数据只会腐坏。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- 缓存策略


@dataclass(frozen=True)
class CachePolicy:
    """一条缓存策略声明。"""

    name: str
    ttl_seconds: int | None
    file_cache: bool
    cache_partial: bool
    description: str


CACHE_POLICIES: dict[str, CachePolicy] = {
    "live_15s": CachePolicy(
        name="live_15s",
        ttl_seconds=15,
        file_cache=False,
        cache_partial=False,
        description="盘中读数最多缓存 15 秒，不落文件",
    ),
    "closed_long": CachePolicy(
        name="closed_long",
        ttl_seconds=7 * 86400,
        file_cache=True,
        cache_partial=False,
        description="已收盘结果长期缓存（7 天，落文件缓存）",
    ),
    "hourly": CachePolicy(
        name="hourly",
        ttl_seconds=3600,
        file_cache=True,
        cache_partial=False,
        description="最多缓存 1 小时",
    ),
    "package_long": CachePolicy(
        name="package_long",
        ttl_seconds=30 * 86400,
        file_cache=True,
        cache_partial=False,
        description="按交易日的盘后包长期缓存（30 天）",
    ),
    "none": CachePolicy(
        name="none",
        ttl_seconds=None,
        file_cache=False,
        cache_partial=False,
        description="不缓存（写操作 / 必须实时）",
    ),
}


@dataclass(frozen=True)
class CacheDecision:
    """一次缓存决策：能否缓存、缓存多久、为什么。"""

    ttl_seconds: int | None
    file_cache: bool
    reason: str

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds is not None


def resolve_cache(policy_name: str, *, partial: bool = False) -> CacheDecision:
    """按元数据里的策略名解析出实际缓存决策。

    Args:
        policy_name: ``CACHE_POLICIES`` 中的策略名。
        partial: 本次结果是否为未收盘的盘中读数。

    Raises:
        KeyError: 策略名未登记（声明写错就当配置错误暴露，不静默降级）。
    """
    policy = CACHE_POLICIES[policy_name]
    if policy.ttl_seconds is None:
        return CacheDecision(None, False, f"policy={policy.name}：不缓存")
    if partial and not policy.cache_partial:
        return CacheDecision(None, False, f"policy={policy.name}：partial 结果不缓存")
    return CacheDecision(policy.ttl_seconds, policy.file_cache, f"policy={policy.name}")


def cache_key(endpoint_id: str, **params: Any) -> str:
    """生成稳定的端点缓存键（参数按 key 排序，空值忽略）。"""
    parts = [endpoint_id]
    for key in sorted(params):
        value = params[key]
        if value in (None, "", 0):
            continue
        parts.append(f"{key}={value}")
    return "|".join(parts)


# ---------------------------------------------------------------- 端点声明


@dataclass(frozen=True)
class EndpointMeta:
    """一个短线端点的完整声明。

    字段说明：
      id          全局唯一端点 id（``shortline.xxx``）
      title       中文短标题
      description 口径说明（给模型和文档读）
      params      入参名清单
      fields      产出字段清单（result 里的 key）
      source      上游来源口径（数据实际从哪来）
      compliance  合规分级：cn-public（国内公开网页接口）
      phase       适用阶段：close（收盘后定稿）/ intraday（盘中）/ postclose（收盘落库）/ anytime
      cache_policy 缓存策略名（见 ``CACHE_POLICIES``）
      compute     计算函数引用 ``module:function``（声明式，不在工具层写死）
      mcp_tool    对应 MCP 工具名
      rest_path   对应 REST 路径
      status      implemented（本批已实现）/ planned（本批声明、后续工单实现）
    """

    id: str
    title: str
    description: str
    params: tuple[str, ...]
    fields: tuple[str, ...]
    source: str
    compliance: str
    phase: str
    cache_policy: str
    compute: str
    mcp_tool: str
    rest_path: str
    status: str = "planned"
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典（供 MCP / REST / CATALOG 三方共用）。"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "params": list(self.params),
            "fields": list(self.fields),
            "source": self.source,
            "compliance": self.compliance,
            "phase": self.phase,
            "cache_policy": self.cache_policy,
            "cache": {
                "ttl_seconds": CACHE_POLICIES[self.cache_policy].ttl_seconds,
                "file_cache": CACHE_POLICIES[self.cache_policy].file_cache,
                "cache_partial": CACHE_POLICIES[self.cache_policy].cache_partial,
                "description": CACHE_POLICIES[self.cache_policy].description,
            },
            "compute": self.compute,
            "mcp_tool": self.mcp_tool,
            "rest_path": self.rest_path,
            "status": self.status,
            **self.extra,
        }


_POOL_SOURCE = "akshare_em(zt/zb/dt/prev_zt)"

# H2 八个读数端点 + H3 收盘落库/历史回读。
# compute 引用先声明后实现（status 会随后续工单翻成 implemented）。
_ENDPOINTS: tuple[EndpointMeta, ...] = (
    EndpointMeta(
        id="shortline.emotion",
        title="情绪四项",
        description=(
            "赚钱效应 / 晋级率 / 连板溢价 / 梯队断层。"
            "赚钱效应=昨日涨停股今日上涨占比；晋级率=昨日涨停今日仍涨停占比；"
            "连板溢价=昨日连板股今日均涨幅−昨日首板今日均涨幅；梯隊断层=今日梯队缺失层级。"
        ),
        params=("date",),
        fields=("money_effect", "promotion_rate", "premium", "ladder_gap"),
        source=_POOL_SOURCE,
        compliance="cn-public",
        phase="close",
        cache_policy="closed_long",
        compute="tradex.shortline.compute:emotion",
        mcp_tool="get_shortline_emotion",
        rest_path="/api/v1/shortline/emotion",
    ),
    EndpointMeta(
        id="shortline.cycle",
        title="情绪周期",
        description=(
            "近 N 日涨停数 / 最高板 / 炸板率合成窗口分位。"
            "窗口数据来自收盘定稿落库；缺天不给 0，写 missing_reason。"
        ),
        params=("days",),
        fields=("window", "percentile", "metrics"),
        source="shortline_store + " + _POOL_SOURCE,
        compliance="cn-public",
        phase="close",
        cache_policy="closed_long",
        compute="tradex.shortline.compute:cycle",
        mcp_tool="get_shortline_cycle",
        rest_path="/api/v1/shortline/cycle",
    ),
    EndpointMeta(
        id="shortline.daily",
        title="每日读数",
        description=(
            "涨停数 / 最高板 / 炸板率 / 昨日涨停今日中位 / 1进2。"
            "昨日涨停今日中位=昨日涨停股今日涨跌幅中位数；1进2=昨日首板今日涨停。"
        ),
        params=("date",),
        fields=("limit_up_count", "max_board", "break_rate", "prev_median", "first_to_second"),
        source=_POOL_SOURCE,
        compliance="cn-public",
        phase="close",
        cache_policy="closed_long",
        compute="tradex.shortline.compute:daily",
        mcp_tool="get_shortline_daily",
        rest_path="/api/v1/shortline/daily",
    ),
    EndpointMeta(
        id="shortline.settled",
        title="昨日涨停股当日表现",
        description="昨日涨停股今日表现明细（涨停样本原料）：代码/名称/连板数/今日涨跌幅/成交额。",
        params=("date",),
        fields=("count", "stocks"),
        source=_POOL_SOURCE,
        compliance="cn-public",
        phase="close",
        cache_policy="closed_long",
        compute="tradex.shortline.compute:settled",
        mcp_tool="get_shortline_settled",
        rest_path="/api/v1/shortline/settled",
    ),
    EndpointMeta(
        id="shortline.live",
        title="盘中情绪",
        description="此刻涨停 / 炸板 / 跌停家数、封板率、1进2。盘中读数标 partial，最多缓存 15 秒。",
        params=(),
        fields=("limit_up", "broken", "limit_down", "seal_rate", "first_to_second"),
        source=_POOL_SOURCE,
        compliance="cn-public",
        phase="intraday",
        cache_policy="live_15s",
        compute="tradex.shortline.compute:live",
        mcp_tool="get_shortline_live",
        rest_path="/api/v1/shortline/live",
    ),
    EndpointMeta(
        id="shortline.ladder",
        title="昨日梯队",
        description="昨日全部涨停股按连板数排（连板高度 + 各层名单）。",
        params=("date",),
        fields=("levels", "stocks"),
        source=_POOL_SOURCE,
        compliance="cn-public",
        phase="close",
        cache_policy="closed_long",
        compute="tradex.shortline.compute:ladder",
        mcp_tool="get_shortline_ladder",
        rest_path="/api/v1/shortline/ladder",
    ),
    EndpointMeta(
        id="shortline.board_ladder",
        title="连板天梯",
        description="今日连板天梯 + 低一层没接上的票去向（晋级/炸板/走弱）。",
        params=("date",),
        fields=("levels", "missed"),
        source=_POOL_SOURCE,
        compliance="cn-public",
        phase="close",
        cache_policy="closed_long",
        compute="tradex.shortline.compute:board_ladder",
        mcp_tool="get_shortline_board_ladder",
        rest_path="/api/v1/shortline/board-ladder",
    ),
    EndpointMeta(
        id="shortline.structure",
        title="涨停结构",
        description="涨停结构（板块/制度占比）+ 四池上游字段清单（防假断点）。",
        params=("date",),
        fields=("structure", "upstream_fields", "missing_reason"),
        source=_POOL_SOURCE,
        compliance="cn-public",
        phase="close",
        cache_policy="closed_long",
        compute="tradex.shortline.compute:structure",
        mcp_tool="get_shortline_structure",
        rest_path="/api/v1/shortline/structure",
    ),
    EndpointMeta(
        id="shortline.bigcaps",
        title="大市值名单",
        description=(
            "总市值 ≥ 门槛（默认 500 亿）的 A 股名单。主源新浪 bigcaps，"
            "失败切东财全市场快照；1 小时缓存；返回 as_of / source / compliance，"
            "停牌或缺市值的票不丢整只、写原因。"
        ),
        params=("min_mktcap_yi", "limit"),
        fields=("as_of", "source", "threshold_yi", "count", "stocks", "unpriced", "source_note"),
        source="sina_bigcaps（备源：akshare_em）",
        compliance="cn-public",
        phase="anytime",
        cache_policy="hourly",
        compute="tradex.service.bigcaps_service:get_bigcaps",
        mcp_tool="get_shortline_bigcaps",
        rest_path="/api/v1/shortline/bigcaps",
        status="implemented",
    ),
    EndpointMeta(
        id="shortline.turnover_top",
        title="全市场成交额榜",
        description=(
            "收盘后下载通达信官网盘后包（g4day，约 2.7MB，17:00 后发布），解析全市场"
            "日线含成交额，产出成交额前 N；包未发布/下载失败时降级为实时榜并标「此刻榜」。"
            "当日榜与历史榜由 kind / as_of 区分。"
        ),
        params=("date", "limit", "kind"),
        fields=("kind", "date", "as_of", "source", "count", "stocks", "degradation"),
        source="tdx_official（备：category_quotes 实时榜）",
        compliance="cn-public",
        phase="postclose",
        cache_policy="package_long",
        compute="tradex.service.turnover_service:get_turnover_top",
        mcp_tool="get_shortline_turnover_top",
        rest_path="/api/v1/shortline/turnover-top",
        status="implemented",
    ),
    EndpointMeta(
        id="shortline.close_fetch",
        title="收盘定稿落库",
        description=(
            "幂等收盘取数：把当日定稿读数落本机（对抗东财四池约一个月保留期）。"
            "同一日重复调用不重复写；partial 不覆盖 final。"
        ),
        params=("date", "force"),
        fields=("date", "status", "written", "missing_reasons", "schema_version"),
        source=_POOL_SOURCE,
        compliance="cn-public",
        phase="postclose",
        cache_policy="none",
        compute="tradex.shortline.store:close_fetch",
        mcp_tool="shortline_close_fetch",
        rest_path="/api/v1/shortline/close-fetch",
    ),
    EndpointMeta(
        id="shortline.history",
        title="收盘历史回读",
        description="读取已落库的定稿读数（按日期或区间），覆盖已积累的全部交易日。",
        params=("date", "days"),
        fields=("count", "dates", "records", "missing_dates"),
        source="shortline_store",
        compliance="cn-public",
        phase="anytime",
        cache_policy="closed_long",
        compute="tradex.shortline.store:history",
        mcp_tool="get_shortline_history",
        rest_path="/api/v1/shortline/history",
    ),
)

SHORTLINE_ENDPOINTS: dict[str, EndpointMeta] = {e.id: e for e in _ENDPOINTS}


def get_endpoint(endpoint_id: str) -> EndpointMeta:
    """按 id 取端点声明（未登记直接抛 KeyError）。"""
    return SHORTLINE_ENDPOINTS[endpoint_id]


_REQUIRED_TEXT_FIELDS = ("id", "title", "description", "source", "compliance", "compute")


def validate_registry() -> list[str]:
    """校验所有端点声明完整、无重复。返回问题列表（空列表 = 全绿）。

    校验项：
      - 必填文本字段非空
      - params / fields 至少一项（fields 不能为空）
      - cache_policy 已登记
      - phase / compliance 在允许集合内
      - id / mcp_tool / rest_path 全局唯一
      - compute 形如 ``module:function``
    """
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_tools: set[str] = set()
    seen_paths: set[str] = set()
    for endpoint in _ENDPOINTS:
        for name in _REQUIRED_TEXT_FIELDS:
            if not str(getattr(endpoint, name) or "").strip():
                problems.append(f"{endpoint.id}: 缺少必填字段 {name}")
        if not str(endpoint.id).startswith("shortline."):
            problems.append(f"{endpoint.id}: id 必须以 shortline. 开头")
        if not endpoint.fields:
            problems.append(f"{endpoint.id}: fields 不能为空")
        if endpoint.cache_policy not in CACHE_POLICIES:
            problems.append(f"{endpoint.id}: 未登记的缓存策略 {endpoint.cache_policy}")
        if endpoint.phase not in ("close", "intraday", "postclose", "anytime"):
            problems.append(f"{endpoint.id}: 非法阶段 {endpoint.phase}")
        if endpoint.compliance not in ("cn-public", "S", "B", "C"):
            problems.append(f"{endpoint.id}: 非法合规分级 {endpoint.compliance}")
        if ":" not in endpoint.compute:
            problems.append(f"{endpoint.id}: compute 必须写成 module:function")
        if endpoint.status not in ("implemented", "planned"):
            problems.append(f"{endpoint.id}: 非法状态 {endpoint.status}")

        if endpoint.id in seen_ids:
            problems.append(f"{endpoint.id}: id 重复")
        seen_ids.add(endpoint.id)
        if endpoint.mcp_tool in seen_tools:
            problems.append(f"{endpoint.id}: mcp_tool 重复 {endpoint.mcp_tool}")
        seen_tools.add(endpoint.mcp_tool)
        if endpoint.rest_path in seen_paths:
            problems.append(f"{endpoint.id}: rest_path 重复 {endpoint.rest_path}")
        seen_paths.add(endpoint.rest_path)
    return problems
