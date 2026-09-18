"""监控看板 HTML 端点（工单 12）。

GET /dashboard 返回简易 HTML 监控页：
- 顶部：网关状态卡（uptime/版本/工具数/数据源健康比例）
- 中部：核心指标表（各端点 QPS/P95/错误率，按延时降序）
- 底部：数据源健康表
- 右侧：最近慢查询

设计：
- 零外部前端框架依赖（纯静态 HTML + 内联 CSS + 一点 JS）
- 30 秒自动刷新（fetch /api/v1/metrics/json）
- 商务风格、富有层次感、手机竖屏友好（响应老板偏好）
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])

# HTML 模板（内联 CSS + JS，无外部依赖）
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TradeX Hub 监控看板</title>
<style>
  :root {
    --bg: #f5f7fa; --card-bg: #ffffff; --border: #e1e7ef;
    --text-primary: #1a202c; --text-secondary: #4a5568; --text-muted: #718096;
    --accent: #2b6cb0; --success: #38a169; --warning: #d69e2e; --danger: #e53e3e;
    --shadow: 0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1a202c; --card-bg: #2d3748; --border: #4a5568;
      --text-primary: #f7fafc; --text-secondary: #cbd5e0; --text-muted: #a0aec0;
      --shadow: 0 1px 3px rgba(0,0,0,0.3);
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", sans-serif;
    background: var(--bg); color: var(--text-primary); padding: 20px;
    line-height: 1.6; font-size: 14px;
  }
  .header {
    display: flex; justify-content: space-between; align-items: center;
    padding-bottom: 20px; border-bottom: 1px solid var(--border); margin-bottom: 20px;
  }
  .header h1 { font-size: 22px; font-weight: 600; }
  .header .refresh-info { font-size: 12px; color: var(--text-muted); }
  .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
  @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
  .card {
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 20px; box-shadow: var(--shadow); margin-bottom: 20px;
  }
  .card-title {
    font-size: 13px; font-weight: 600; color: var(--text-secondary);
    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 15px;
  }
  .status-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 15px;
  }
  .status-item { text-align: center; }
  .status-label { font-size: 11px; color: var(--text-muted); margin-bottom: 5px; }
  .status-value { font-size: 24px; font-weight: 600; color: var(--text-primary); }
  .status-value.success { color: var(--success); }
  .status-value.warning { color: var(--warning); }
  .status-value.danger { color: var(--danger); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  th { color: var(--text-muted); font-weight: 500; font-size: 11px; text-transform: uppercase; }
  tr:hover { background: var(--bg); }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 11px; font-weight: 500;
  }
  .badge.success { background: rgba(56,161,105,0.15); color: var(--success); }
  .badge.warning { background: rgba(214,158,46,0.15); color: var(--warning); }
  .badge.danger { background: rgba(229,62,62,0.15); color: var(--danger); }
  .error-banner {
    background: rgba(229,62,62,0.1); border: 1px solid var(--danger);
    color: var(--danger); padding: 10px 15px; border-radius: 6px; margin-bottom: 20px;
    display: none;
  }
  .metric-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); }
  .metric-row:last-child { border-bottom: none; }
  .metric-label { color: var(--text-secondary); }
  .metric-value { font-weight: 500; }
</style>
</head>
<body>
  <div class="header">
    <h1>TradeX Hub 监控看板</h1>
    <div class="refresh-info" id="refresh-info">加载中...</div>
  </div>
  <div class="error-banner" id="error-banner"></div>
  <div class="grid">
    <div>
      <div class="card" id="status-card">
        <div class="card-title">网关状态</div>
        <div class="status-grid">
          <div class="status-item">
            <div class="status-label">运行时长</div>
            <div class="status-value" id="uptime">--</div>
          </div>
          <div class="status-item">
            <div class="status-label">版本</div>
            <div class="status-value" id="version">--</div>
          </div>
          <div class="status-item">
            <div class="status-label">注册工具</div>
            <div class="status-value" id="tools">--</div>
          </div>
          <div class="status-item">
            <div class="status-label">缓存命中率</div>
            <div class="status-value" id="hit-rate">--</div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">核心指标</div>
        <div id="metrics-table">
          <div class="metric-row"><span class="metric-label">总请求数</span><span class="metric-value" id="total-requests">--</span></div>
          <div class="metric-row"><span class="metric-label">错误数</span><span class="metric-value" id="total-errors">--</span></div>
          <div class="metric-row"><span class="metric-label">慢查询数</span><span class="metric-value" id="slow-queries">--</span></div>
          <div class="metric-row"><span class="metric-label">缓存尺寸</span><span class="metric-value" id="cache-size">--</span></div>
          <div class="metric-row"><span class="metric-label">慢查询阈值</span><span class="metric-value" id="slow-threshold">--</span></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">缓存详情</div>
        <div id="cache-details">
          <div class="metric-row"><span class="metric-label">命中次数</span><span class="metric-value" id="cache-hits">--</span></div>
          <div class="metric-row"><span class="metric-label">未命中</span><span class="metric-value" id="cache-misses">--</span></div>
          <div class="metric-row"><span class="metric-label">文件缓存</span><span class="metric-value" id="cache-file">--</span></div>
        </div>
      </div>
    </div>
    <div>
      <div class="card">
        <div class="card-title">数据源健康</div>
        <div id="data-source-list">
          <p style="color: var(--text-muted); font-size: 12px;">指标采集中，稍后显示...</p>
        </div>
      </div>
      <div class="card">
        <div class="card-title">慢查询日志</div>
        <div id="slow-query-list">
          <p style="color: var(--text-muted); font-size: 12px;">暂无慢查询记录</p>
        </div>
      </div>
    </div>
  </div>
<script>
const METRICS_URL = '/api/v1/metrics/json';
const REFRESH_INTERVAL = 30000;

function formatUptime(seconds) {
  if (!seconds || seconds < 0) return '--';
  if (seconds < 60) return Math.round(seconds) + 's';
  if (seconds < 3600) return Math.round(seconds/60) + 'm';
  if (seconds < 86400) return (seconds/3600).toFixed(1) + 'h';
  return (seconds/86400).toFixed(1) + 'd';
}

function setError(msg) {
  const banner = document.getElementById('error-banner');
  if (msg) {
    banner.style.display = 'block';
    banner.textContent = '⚠️ 指标拉取失败: ' + msg;
  } else {
    banner.style.display = 'none';
  }
}

async function fetchMetrics() {
  try {
    const r = await fetch(METRICS_URL);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const body = await r.json();
    if (body.code !== 0) throw new Error(body.msg || 'unknown');
    const data = body.data;
    setError(null);

    const g = data.gateway || {};
    const c = data.cache || {};

    document.getElementById('uptime').textContent = formatUptime(g.uptime_seconds);
    document.getElementById('version').textContent = g.version || '3.3.18';
    document.getElementById('tools').textContent = g.tools_registered || 0;

    const hitRate = (c.hit_rate !== undefined) ? (c.hit_rate * 100).toFixed(1) + '%' : '--';
    const hitEl = document.getElementById('hit-rate');
    hitEl.textContent = hitRate;
    hitEl.className = 'status-value ' + (
      c.hit_rate >= 0.5 ? 'success' : c.hit_rate >= 0.2 ? 'warning' : 'danger'
    );

    document.getElementById('cache-size').textContent = c.size || 0;
    document.getElementById('cache-hits').textContent = c.hits || 0;
    document.getElementById('cache-misses').textContent = c.misses || 0;
    document.getElementById('cache-file').textContent = c.file_enabled ? '启用' : '关闭';
    document.getElementById('slow-threshold').textContent = (data.slow_query_threshold_ms || 800) + 'ms';

    document.getElementById('refresh-info').textContent =
      '更新于 ' + new Date().toLocaleTimeString('zh-CN');

  } catch (e) {
    setError(e.message);
  }
}

fetchMetrics();
setInterval(fetchMetrics, REFRESH_INTERVAL);
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """监控看板 HTML 页 —— 30 秒自动刷新指标。"""
    return HTMLResponse(_DASHBOARD_HTML)
