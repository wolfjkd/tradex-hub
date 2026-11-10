# AGENTS.md — tradex-hub 仓内工作约定（一页导航，背景叙事见 Obsidian）

> 本页只放**硬约定与指针**，不讲原理。项目背景 / 历史裁决 / 交接叙事在
> Obsidian `D:\wolfjkd-OB\wolfjkd\开发计划\项目-tradex-hub\`（交接文档按 NN 编号递增）。

## 环境与命令

- **venv 口径**：pytest 在 `tradex/.venv`（仓库根 `.venv` 无 pytest；`tradex/venv` 不存在）。
- **全量回归**（两层，`tests` + `tradex/tests` 各自 conftest）：
  `./tradex/.venv/Scripts/python.exe -m pytest tests tradex/tests -m "not network" -q`
  基线 **1207 passed / 5 skipped / 36 deselected**（2026-11-11，批次BCD 后）。
  只认「退出码 + 总结行」；跑前确认无遗留 python/pytest 进程（并发 pytest 互污染 `.pytest_cache`）。
- 依赖用 **uv** 管理（`tradex/uv.lock`）；装新依赖 `cd tradex && uv add <pkg>`。

## 硬约定（违反即测试/审计翻车）

1. **依赖双处同步**：`tradex/pyproject.toml` 与 `tradex/requirements.txt` 必须同步加
   （uv add 只动 pyproject+uv.lock，requirements 手动补）——历史硬违规 #1。
2. **计数断言护栏**：注册表/工具/端点计数有测试断言钉着，动注册表（`registry.py`
   `_SOURCE_TABLE`，唯一知识源）或加删工具/端点后同步改
   `tests/test_v3314_fixes.py` / `test_v3315_fixes.py` 的计数与演进注释。
3. **接口删除/改名前先 grep 下游消费仓**：TradeX（`wolfjkd/TradeX`）经 MCP 消费本仓
   工具与 service 函数——批次A 曾误删 `shortline_service.get_history`（TradeX
   `emotion_review` 在调），跨仓调用方在 CI 才炸。删改前查 TradeX 仓引用。
4. **真连网用例必须打 `@pytest.mark.network`**：全量回归 `-m "not network"` 跳过；
   录制 fixture / monkeypatch 优先（参照 `tests/test_index_valuation.py`）。
5. **akshare 调用必须过 `_ak()`**（超时防御统一入口），fetcher 失败必须
   **抛出**由 SmartRouter 记账降级——吞成空表 = 降级链失效（v3.3.15 起约定）。
6. **哨兵用自定义异常**，禁止消息字符串匹配做控制流（`"空壳" in str(e)` 反例已清）；
   异常链禁止裸 `raise`（要 `raise ... from exc` 保留真因）。
7. **缓存序列化边界**：对象缓存一律走 `cache.get_or_set(key, factory, ttl)`
   （`tradex/utils/cache.py`）；tools 层 `df_to_json` 字符串缓存继续裸 get/set；
   `None` 不缓存（失败/空值不冻结语义）。
8. **visibility_catalog 手工归组**（`tradex/tools/visibility_catalog.py` 纯数据真源）：
   加 MCP 工具后在此归组，工具计数断言同步。
9. **REST 错误样板**：新端点用 `routes/_helpers.py` 的
   `serve_envelope`（全→502）/ `serve_envelope_400`（ValueError→400）+
   `validate_symbol`；不要新定义本地错误转换 helper。
10. **collect_snapshot 契约**：shortline 四池快照经 `_serve`/`_build_envelope`
    统一信封出（含 compliance/cache 段）；`shortline.history` 例外无此两段（纯落库读）。
11. **数据源注册**：改 `registry.py` 的 `_SOURCE_TABLE` 五元组表（历史裁决注释随行内联），
    不要在 `_do_register` 加散装 register；死源/复活裁决记 Obsidian 交接。

## 工具与文档指针

- MCP 工具清单：`docs/MCP_TOOLS.md`（发版时重生成，头部版本戳要随版本走）。
- 版本管理：SemVer；发版 SOP 见真源 `2-独立规则/版本管理规则.md`（软件项目 6 处同步）。
- CHANGELOG 措辞必须对照 git log 史实（v3.9.1「零代码」失实教训）；
  `scripts/check_changelog_claims.py` 可机械核验（发版前跑）。
- 确定性检查脚本（本仓 CI 替代，无 GitHub Actions，发版/改计数前必跑）：
  `scripts/check_dep_sync.py`（依赖双处）、
  `scripts/check_readme_counts.py`（README 计数 vs 实跑）、
  `scripts/check_changelog_claims.py`（CHANGELOG 措辞 vs git log，`--selftest` 自证）；
  REST 端点计数在 `tests/test_rest_count.py` 断言（改端点四处一体：断言/README badge/正文/CHANGELOG）。
