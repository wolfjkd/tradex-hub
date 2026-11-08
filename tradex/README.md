# tradex（Python 包）

> 本目录是 tradex-hub 的 **Python 包实现**（`src/tradex`）。项目门面文档、快速开始、
> 工具清单、版本历史一律以 **[仓库根 README](../README.md)** 为准，本文件不再重复维护。

## 包结构速览

| 目录 | 职责 |
|------|------|
| `src/tradex/api/` | FastAPI REST 路由与 Schema（81 端点，`/api/v1/*`） |
| `src/tradex/tools/` | MCP 工具注册（190 个，`registry.py` 自动发现 + 可见性 profile 过滤） |
| `src/tradex/data_sources/` | 数据源 fetcher 与 SmartRouter 注册（113 类型 / 157 注册） |
| `src/tradex/service/` | 业务服务层（短线读数/大市值/成交额榜等） |
| `src/tradex/shortline/` | 短线数据底座（声明式元数据/计算/落库/漂移） |
| `src/tradex/dashboard/` | 数据源看板（独立进程，`python -m tradex.dashboard`，默认 :8765） |
| `src/tradex/astock_signals/` | 智能路由与信号子包（v3.3.11 并入，独立仓退役） |
| `src/tradex/utils/` | 缓存/限流/格式化等公共件 |

## 版本

当前版本见仓库根 `VERSION` 文件（v3.9.0）。版本历史与变更日志见根目录
[README 版本历史](../README.md#版本历史) 与 [CHANGELOG](../CHANGELOG.md)。

## 快速使用

```bash
# 从仓库根安装（可编辑 + http 网关 extras）
uv pip install -e ".[http]"

# 启动 MCP 网关（HTTP 模式，:8000）
python -m tradex --http --host 127.0.0.1 --port 8000

# 启动数据源看板（:8765）
python -m tradex.dashboard
```

详细配置（数据源矩阵、限流、访问门控）见 [根 README](../README.md#安装) 与
[docs/architecture.md](../docs/architecture.md)。
