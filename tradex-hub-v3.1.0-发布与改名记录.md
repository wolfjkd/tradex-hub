# tradex-hub v3.1.0 发布与改名记录

> **会话时间**：2026-08-02  
> **项目**：tradex-hub（原 trader-finance-hub）  
> **版本**：v3.1.0  
> **操作人**：AI 助手 + 老板（郭良勇）

---

## 目录

- [1. 任务总览](#1-任务总览)
- [2. v3.1.0 版本发布](#2-v310-版本发布)
- [3. GitHub 仓库改名](#3-github-仓库改名)
- [4. 本地目录改名影响评估](#4-本地目录改名影响评估)
- [5. 文件更新执行](#5-文件更新执行)
- [6. 待办事项](#6-待办事项)
- [7. 验证清单](#7-验证清单)

---

## 1. 任务总览

### 1.1 背景

项目原名 `trader-finance-hub`，Python 包名 `cn_financial_mcp`（历史遗留）。老板决定：
- 项目名改为 `tradex-hub`
- 包名改为 `tradex`
- GitHub 仓库名同步改名
- 全局规则与记忆 MD 文档同步更新
- 代码与模块引用同步更新
- MCP 配置及其他项目调用同步更新

### 1.2 v3.1.0 核心变更

| 变更项 | 说明 |
|--------|------|
| SmartRouter 全量覆盖 | 25 数据类型 34 源注册，L1 工具统一 `route()` 获取 |
| data_sources 数据源层 | L1 工具获取数据的唯一入口（含独占源注册） |
| eltdx 升为行情类第一主源 | 集合竞价/逐笔/F10/实时/K线/分时 |
| 数据源看板 | dashboard 模块（HTML 可视化 端口 8765 + MCP 工具 `get_data_source_dashboard`） |
| 数据源版本检查 | eltdx/akshare 只提醒不自动升级 |
| HTTP 防封参数环境变量化 | EM_RATE_LIMIT_INTERVAL / EM_JITTER_MIN / EM_JITTER_MAX / EM_MAX_RETRY |
| astock_signals 独立成包 | v1.1.0，pip install -e 安装 |
| 项目改名 | cn_financial_mcp → tradex，仓库 trader-finance-hub → tradex-hub |
| 工具数 | 88 → 89（新增 get_data_source_dashboard） |

---

## 2. v3.1.0 版本发布

### 2.1 发布前自检

| 检查项 | 结果 |
|--------|------|
| 版本号 3 处同步 | ✅ src/__init__.py=3.1.0, tradex/pyproject.toml=3.1.0, VERSION=3.1.0 |
| README 版本号 | ✅ Version-3.1.0 |
| config/mcp-servers.json | ✅ version=3.1.0, tools=89 |
| docs/architecture.md | ✅ v3.1.0 |
| CHANGELOG.md | ✅ [3.1.0] - 2026-08-02 |
| 旧名残留 | ✅ 仅 spec 文档/CHANGELOG 历史条目（合理保留） |
| 测试 | ✅ 根目录 317 passed + tradex/tests 33 passed, 1 skipped = **350 passed** |

### 2.2 发布操作记录

| 步骤 | 命令 | 结果 |
|------|------|------|
| git commit | `git commit -m "release(v3.1.0): ..."` | ✅ `78ae9b4`，51 files changed, +3338/-1359 |
| git tag | `git tag -a v3.1.0 -m "..."` | ✅ tag v3.1.0 创建 |
| git push 分支 | `git push -u origin refactor/v3.1.0` | ✅ new branch |
| git push tag | `git push origin v3.1.0` | ✅ new tag |
| GitHub Release | `gh release create v3.1.0 --title "..." --notes "..."` | ✅ [v3.1.0 Release](https://github.com/wolfjkd/tradex-hub/releases/tag/v3.1.0) |

### 2.3 Commit 信息

```
release(v3.1.0): 数据源治理完成 + SmartRouter 全量路由 + 看板

主要变更：
- SmartRouter 全量覆盖：25 数据类型 34 源注册，L1 工具统一 route() 获取
- data_sources 数据源层：L1 工具获取数据的唯一入口（含独占源注册）
- eltdx 升为行情类第一主源（集合竞价/逐笔/F10/实时/K线/分时）
- 数据源看板：dashboard 模块（HTML 可视化 端口8765 + MCP 工具 get_data_source_dashboard）
- 数据源版本检查：eltdx/akshare 只提醒不自动升级
- HTTP 防封参数环境变量化（EM_RATE_LIMIT_INTERVAL 等）
- 测试修复：route() 返回值 tuple 解包（eltdx_data + test_tick_store_integration）
- 文档同步：README/CHANGELOG/architecture.md/mcp-servers.json
- 工具数 88 -> 89（新增 get_data_source_dashboard）

测试：350 passed, 1 skipped
```

---

## 3. GitHub 仓库改名

### 3.1 操作

```powershell
gh repo rename tradex-hub --yes
```

### 3.2 结果

| 项 | 值 |
|----|-----|
| 旧仓库名 | `wolfjkd/trader-finance-hub` |
| 新仓库名 | `wolfjkd/tradex-hub` |
| remote URL 自动更新 | ✅ `https://github.com/wolfjkd/tradex-hub.git` |
| Release URL | https://github.com/wolfjkd/tradex-hub/releases/tag/v3.1.0 |
| 旧 URL 重定向 | GitHub 自动支持旧 URL 重定向 |

---

## 4. 本地目录改名影响评估

### 4.1 评估范围

扫描以下目录中所有 `trader-finance-hub` 路径引用：
- `c:\Users\wolfj\Documents\trae_projects\` — 所有项目
- `c:\Users\wolfj\.trae-cn\skills\` — 所有 skills
- `c:\Users\wolfj\.trae-cn\` — MCP 配置等

### 4.2 影响分级

| 级别 | 影响范围 | 文件数 | 说明 |
|------|---------|--------|------|
| **P0 阻断** | MCP 服务无法启动 | 1 处 | 必须同步改 |
| **P1 自动化任务** | 早盘/盘后脚本路径错误 | 6 处 | 应同步改 |
| **P2 规则文档** | 不影响运行，名字不一致 | 5 处 | 可选改 |
| **P3 历史文档** | 不影响运行 | 10+ 处 | 不需要改 |

### 4.3 P0 — 阻断性（必须改）

| 文件 | 行 | 内容 |
|------|---|------|
| `c:\Users\wolfj\.trae-cn\mcp.json` | 10 | `"cwd": "C:\\Users\\wolfj\\Documents\\trae_projects\\trader-finance-hub\\tradex"` |

### 4.4 P1 — 自动化任务脚本和提示词（6 处）

| 文件 | 说明 |
|------|------|
| `trae-config\work\6a45d891db920e1592f8c789\write_md.py` | 路径表 + MCP 配置示例 |
| `trae-config\work\6a45d891db920e1592f8c789\pre-market-v2.py` | 早盘脚本路径表 |
| `trae-config\work\6a45d891db920e1592f8c789\post-market-v3.py` | 盘后脚本路径表 |
| `trae-config\盘后复盘-TRAE提示词v3.0.md` | 提示词模板路径引用 |
| `trae-config\早盘作战-TRAE提示词v2.1.md` | 提示词模板路径引用 |
| `trae-config\早盘作战-TRAE提示词v2.0.md` | 提示词模板路径引用 |

### 4.5 P2 — 规则/记忆文档（5 处）

| 文件 | 说明 |
|------|------|
| `trae-config\user_rules\MEMORY.md` | 旧版 MEMORY |
| `trae-config\user_rules\github_repos.md` | 旧版仓库列表 |
| `trae-config\user_rules\VERSION-CONTROL-RULES.md` | 联动说明 |
| `trae-config\user_rules\project_dir_rule.md` | 目录规则示例 |
| `trae-config\memory\user_profile.md` | 旧版用户画像 |

### 4.6 不受影响的项目

| 项目 | 代码层引用 | 结论 |
|------|-----------|------|
| astock_signals | 无 | 不受影响 |
| quantterminal | 仅 CHANGELOG | 不受影响 |
| trader-data-router | 仅 CHANGELOG | 不受影响 |
| daily_stock_analysis | 仅历史 spec | 不受影响 |

### 4.7 P3 — 历史文档（不需要改）

- `项目核对与补漏执行报告.md` — 历史报告
- `量化交易系统总开发计划书.md` — 历史计划书
- `量化交易系统开发计划书-最终核对报告.md` — 历史报告
- `vibe-astock\Vibe-Astock-深度拆解与抄作业指南.md` — 分析文档
- `quantterminal\CHANGELOG.md` — 历史变更日志
- `skills\trader-data-router\CHANGELOG.md` — 历史变更日志
- `daily_stock_analysis\.trae\specs\*` — 历史 spec
- `trae-config\自动化任务报告\*` — 历史报告
- 会话记忆文件 — 历史记录

---

## 5. 文件更新执行

### 5.1 P0 — mcp.json（已完成）

```json
// c:\Users\wolfj\.trae-cn\mcp.json
{
  "mcpServers": {
    "tradex": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "tradex"],
      "cwd": "C:\\Users\\wolfj\\Documents\\trae_projects\\tradex-hub\\tradex"
    }
  }
}
```

### 5.2 P1 + P2 — trae-config 11 个文件（已完成）

使用 `replace_all=true` 批量替换 `trader-finance-hub` → `tradex-hub`：

| # | 文件 | 替换处数 |
|---|------|---------|
| 1 | `work\6a45d891db920e1592f8c789\write_md.py` | 17 处 |
| 2 | `work\6a45d891db920e1592f8c789\pre-market-v2.py` | 11 处 |
| 3 | `work\6a45d891db920e1592f8c789\post-market-v3.py` | 10 处 |
| 4 | `盘后复盘-TRAE提示词v3.0.md` | 1 处 |
| 5 | `早盘作战-TRAE提示词v2.1.md` | 1 处 |
| 6 | `早盘作战-TRAE提示词v2.0.md` | 1 处 |
| 7 | `user_rules\MEMORY.md` | 10 处 |
| 8 | `user_rules\github_repos.md` | 2 处 |
| 9 | `user_rules\VERSION-CONTROL-RULES.md` | 4 处 |
| 10 | `user_rules\project_dir_rule.md` | 1 处 |
| 11 | `memory\user_profile.md` | 2 处 |

**合计**：约 60 处替换。

替换规则：
- ✅ 路径引用 `trader-finance-hub` → `tradex-hub`
- ✅ GitHub URL `wolfjkd/trader-finance-hub` → `wolfjkd/tradex-hub`
- ✅ 项目名提及 `trader-finance-hub` → `tradex-hub`
- ✅ 版本号保留（v2.5.0 等不动）

---

## 6. 待办事项

### 6.1 本地目录改名（需老板手动操作）

目录被 Trae IDE 进程占用，无法在 IDE 内部改名。

**操作步骤**：

1. **关闭 Trae IDE**

2. **打开独立 PowerShell**（Win+X → 终端），执行：
   ```powershell
   Rename-Item -Path "C:\Users\wolfj\Documents\trae_projects\trader-finance-hub" -NewName "tradex-hub"
   ```
   或在文件管理器中右键 `trader-finance-hub` → 重命名为 `tradex-hub`

3. **重新打开 Trae IDE**，打开新路径：
   ```
   C:\Users\wolfj\Documents\trae_projects\tradex-hub
   ```

### 6.2 可选：合并分支到 master

`refactor/v3.1.0` 分支已 push，但未合并到 `master`（v3.0.0 也未合并）。由老板决定分支策略。

---

## 7. 验证清单

改名后重新打开 IDE，执行以下验证：

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| git remote | `git remote -v` | `https://github.com/wolfjkd/tradex-hub.git` |
| git status | `git status` | clean |
| 测试套件 | `python -m pytest tests -q` | 317 passed |
| tradex 测试 | `python -m pytest tradex/tests -q` | 33 passed, 1 skipped |
| MCP 配置 | 检查 `.trae-cn/mcp.json` cwd | `tradex-hub\tradex` |
| MCP 服务 | `python -m tradex` 可启动 | 正常启动 |

---

## 附录：关键文件路径

| 文件 | 路径 |
|------|------|
| 项目根目录 | `C:\Users\wolfj\Documents\trae_projects\tradex-hub\`（改名后） |
| MCP 配置 | `C:\Users\wolfj\.trae-cn\mcp.json` |
| tradex 包 | `tradex-hub\tradex\src\tradex\` |
| astock_signals 独立包 | `C:\Users\wolfj\Documents\trae_projects\astock_signals\` |
| 数据源看板 | `python -m tradex.dashboard`（端口 8765） |
| GitHub Release | https://github.com/wolfjkd/tradex-hub/releases/tag/v3.1.0 |
| Spec 文档 | `tradex-hub\.trae\specs\refactor-v3.1.0\spec.md` |

---

*本文档由 AI 助手生成，记录 tradex-hub v3.1.0 发布与改名的完整过程。*
