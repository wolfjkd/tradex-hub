# Tickets — 通达信官方MCP平级集成（SP-2026-09-21-001）

> 状态：全部 pending · 先开发不发版
> 关联 Spec：`docs/spec-tdx-mcp-integration-2026-09-21.md`
> 阻塞边：T1→T2→T3 有依赖；T4 独立；T5 最后回归

## 工单清单

| ID | 标题 | 描述（垂直切片焦点） | 阻塞 | 完成标准 |
|----|------|----------------------|------|----------|
| T1 | 新增 td_mcp_fetchers.py | 官方 MCP HTTP 客户端 + token 缺省降级 | - | 缺 token 时返回 NotAvailable；有 token 时可通 `/health` |
| T2 | registry.py 注册 tdx_mcp | 加到 3 个 data_type 给 priority=1，更新文档矩阵头 | 搭 T1 | 同 priority=1；eltdx 保留不变 |
| T3 | 新增 tools/tdx_mcp.py | 3 个工具透传（screener/research/conind） | 搭 T1 | 工具注册进 MCP server；走 route 统一取值 |
| T4 | .env.example + README 注明 token | 开源可分发 | - | 文档清晰，用户能自助填 token |
| T5 | 回归冒烟 + 工具数断言 | server 起 → 129→132 断言更新 | T3 | register 幂等、health 正常、route 降级验证 |
| T6 | 选股占比与限流防护 | high-volume 边界 | 搭 T3 | 防超额调用，观测健康分 |

---

*wolfjkd · 2026-09-21*