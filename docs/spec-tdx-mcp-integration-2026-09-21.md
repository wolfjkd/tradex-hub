# SP-2026-09-21-001 | 通达信官方 MCP 平级嵌入 tradex-hub 多源中台

> **状态**：Spec（已定稿，老板 6 条拍板确认）
> **日期**：2026-09-21
> **项目**：tradex-hub（包名 `tradex`，v3.5.0，129 工具）
> **集成目标**：把通达信官方云端 MCP（`https://txmcp.tdx.com.cn:3001/txmcp`）作为**与 eltdx 平级的第一梯队数据源**接入，互为备份。

---

## 一、架构目标（老板拍板的 6 条）

| # | 决策项 | 拍板结论 | 落点 |
|---|--------|----------|------|
| 1 | 集成层级 | **与 eltdx 平级、同属第一梯队，互为备份、互为第一梯队兜底** | registry 同 `priority=1`；`smart_router` 零改动，靠健康分动态互备 |
| 2 | token 来源 | **独立 `env`：`.env` 加 `TDX_MCP_TOKEN`**，与 WB connector 解耦（开源分发，用户自己填 token / API key） | `tdx_mcp_fetchers.py` 读 env；缺 token 时该源视为不可用（自动降级到 eltdx） |
| 3 | 集成范围 | **全量兜底**（realtime / kline / 研报 / 公告 / 宏观 / 选股全覆盖） | 覆盖 eltdx 已有类型 + 新增纯增量类型 |
| 4 | 失败降级 | **非独占 + 自动降级**（不设 `exclusive`） | `register(..., exclusive=False)`，健康分机制自动切换 |
| 5 | 研报/宏观暴露 | **走 registry 统一暴露**（单一数据源真源） | 新增 `reserch_report` / `macro_ext` data_type |
| 6 | 自然语言选股 | **是**，新增 L3 独立工具 | 新增 `tdx_screener` wrap → `natural_lang_screener` 工具 |

---

## 2. 关键机制（已验证，零改动的复用）

`SmartRouter.route()` 评分公式：`combined = health.score*0.7 + priority_score*0.3`（smart_router.py#L230-231）。

- **同 `priority=1` 时**，两条源 `priority_score` 相同 → **健康分高者胜出**。
- **失败惩罚**：连续失败 `20×min(consecutive_fails,5)`（一次 -20，两次 -40，五次归零拉黑冷却）→ **eltdx 故障时健康分骤降 → 自动切到 tdx_mcp**；恢复后 +10 回升 → 自动切回。
- **半开探测**：score<20 且冷却结束自动重新参与路由（smart_router.py:65-78）。

**结论：`smart_router.py` 零改动；`registry.py` 加源行即可实现「互为第一梯队、健康互备」。**

---

## 3. 技术实现（待开发 · 先开发不发版）

### 3.1 新增 `tradex/src/tradex/data_sources/tdx_mcp_fetchers.py`
- 读 `TDX_MCP_TOKEN`（os.environ），缺失 → 返回 `NotAvailable`（不抛异常，降级走 eltdx）
- 用 `httpx` / `curl_cffi` 连官方 Streamable-HTTP
- fetch_fn 签名对齐 `eltdx_fetchers.py`：`fetch_xxx(code/symbol=..., **kwargs)`
- 覆盖：`realtime_quote / historical_kline / company_announcements / research_report(新) / macro_data / news`
- 单独封装 `fetch_screener(query, limit)`（自然语言选股）

### 3.2 `data_sources/registry.py` 新增注册行
```python
router.register("realtime_quote", "tdx_mcp", tdx.fetch_realtime_quote, priority=1)   # 与 eltdx 平级
router.register("research_report", "tdx_mcp", tdx.fetch_research_report, priority=1) # 纯增量新类型
router.register("natural_lang_screener", "tdx_mcp", tdx.fetch_screener, priority=1)   # 纯增量
```
- 数据类型矩阵文档头同步更新（38→新增）
- **全程不动 eltdx 现有 priority=1 注册**（避免破坏生参行为）

### 3.3 L3 工具层新增 `tools/tdx_mcp.py`
- `natural_lang_screener(query, limit)` —— 透传 `tdx_screener`
- `research_data(code, type)` —— 透传研报
- `conind_metrics(code, indicators)` —— 透传结构化指标
- 用 `router.register` 后的 `get_router().route(...)` 统一取值（不直接 import tdx）

### 3.4 `resources/.env.example`（新增，开源用）
```dotenv
# 通达信官方 MCP 认证凭证（用户自行填写）
TDX_MCP_TOKEN=
TDX_MCP_ENDPOINT=https://tdn.mcp.tdx.com.cn:3301/txmcp
```

---

## 4. 不发版约定（老板 2026-09-21 铁令）
- **先开发，不 bump 版本、不 tag、不 GitHub Release、不打包 exe**
- 是否发版由老板明确通知
- 发版条件：有阶段性成果 或 解决关键 bug
- 本 spec 落地后攒批次：`数据集成块（含此 + 后续小改动）` 一起发

---

## 5. 待办拆解（to-tickets草案）
- T1：新增 `tdx_mcp_fetchers.py`（token 缺省降级）
- T2：`registry.py` 注册 + 文档头更新
- T3：新增 `tools/tdx_mcp.py`（3 工具透传）
- T4：`.env.example` + 说明文档
- T5（回归）：`tradex` 启动冒烟 → 129+ 工具数断言更新 → `register_all_sources` 幂等
- T6（可选）错误 sampling 收集（健康分展示）

---

*wolfjkd · 2026-09-21*