"""业务逻辑层（阶段一工单 01 建立骨架）。

本包承载从 tools/*.py 的 @mcp.tool() 装饰器内抽出的纯业务逻辑函数。
MCP 工具和 REST 路由各自薄包装，共享同一份代码（契约一致性）。

参考先例：tools/diagnostics.py 的 build_dashboard_data() 已是纯函数先例。

阶段一按领域拆分（后续工单填充）：
- market_service.py    行情/资金（工单 02/03）
- price_service.py     价格/K线（工单 04）
- eltdx_service.py     通达信专用数据（工单 04，含 native panic 防护）
- company_service.py   公司概况（工单 05）
- financial_service.py 三大报表/指标（工单 05）
- news_service.py      新闻/公告（工单 06）
- industry_service.py  行业/板块（工单 07）
- indicator_service.py 技术指标（工单 08）
- diagnostic_service.py 综合诊断（工单 09，复用 diagnostics.build_dashboard_data）
- write_service.py     写操作（工单 10，文件存储）
"""
