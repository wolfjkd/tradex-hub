"""V2.5.0 升级验证脚本：检查15个新工具是否成功注册 + 实际调用测试。"""
import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from cn_financial_mcp.server import mcp


EXPECTED_NEW_TOOLS = [
    'calculate_ma_ema', 'calculate_macd', 'calculate_kdj',
    'calculate_rsi', 'calculate_boll', 'calculate_atr',
    'calculate_performance', 'list_performance_metrics',
    'generate_trading_signal', 'scan_stocks_for_signals', 'validate_signal_quality',
    'calculate_factor_score', 'get_factor_catalog',
    'screen_stocks', 'get_screening_conditions',
]


def extract_text(result):
    """从 call_tool 返回结果中提取文本。

    FastMCP call_tool 返回 tuple: ([TextContent(...)], meta_dict)
    """
    # result 是 tuple (list_of_content, meta)
    if isinstance(result, tuple) and len(result) >= 1:
        result = result[0]
    if isinstance(result, list):
        if len(result) > 0:
            item = result[0]
            if hasattr(item, 'text'):
                return item.text
            if isinstance(item, dict):
                return item.get('text', str(item))
            return str(item)
    return str(result)


async def main():
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]

    print(f'=== TFH v2.5.0 升级验证 ===')
    print(f'总工具数: {len(tools)}')
    print(f'期望新增工具数: {len(EXPECTED_NEW_TOOLS)}')

    missing = [name for name in EXPECTED_NEW_TOOLS if name not in tool_names]
    found = [name for name in EXPECTED_NEW_TOOLS if name in tool_names]

    print(f'已注册新工具: {len(found)}/{len(EXPECTED_NEW_TOOLS)}')

    if missing:
        print(f'\n[FAIL] 缺失工具:')
        for m in missing:
            print(f'  - {m}')
        return 1

    print(f'\n[PASS] 全部15个新工具注册成功')

    # 工具调用测试
    print(f'\n=== 工具调用测试 ===')

    # 1. 技术指标：MA
    closes = [10.0 + i * 0.1 for i in range(50)]
    r = await mcp.call_tool('calculate_ma_ema', {'closes': closes, 'period': 5, 'type': 'sma'})
    text = extract_text(r)
    data = json.loads(text)
    assert data['success'] is True
    assert data['data_points'] == 50
    print(f'[PASS] calculate_ma_ema: 50个数据点，周期5，有效点{data["ma_valid_points"]}')

    # 2. MACD
    r = await mcp.call_tool('calculate_macd', {'closes': closes})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] calculate_macd: DIF长度{len(data["dif"])}')

    # 3. KDJ
    highs = [11.0 + i * 0.1 for i in range(50)]
    lows = [9.5 + i * 0.1 for i in range(50)]
    r = await mcp.call_tool('calculate_kdj', {'highs': highs, 'lows': lows, 'closes': closes})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] calculate_kdj: K={data["k"][-1]}, D={data["d"][-1]}, J={data["j"][-1]}')

    # 4. RSI
    r = await mcp.call_tool('calculate_rsi', {'closes': closes, 'period': 14})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] calculate_rsi: 最后RSI={data["rsi"][-1]}')

    # 5. BOLL
    r = await mcp.call_tool('calculate_boll', {'closes': closes, 'period': 20})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] calculate_boll: upper={data["upper"][-1]}, mid={data["middle"][-1]}, lower={data["lower"][-1]}')

    # 6. ATR
    r = await mcp.call_tool('calculate_atr', {'highs': highs, 'lows': lows, 'closes': closes})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] calculate_atr: 最后ATR={data["atr"][-1]}')

    # 7. Performance
    eq = [1000000 * (1 + 0.001 * i) for i in range(100)]
    trades = [{'profit': 100}, {'profit': -50}, {'profit': 200}, {'profit': -30}]
    r = await mcp.call_tool('calculate_performance', {'equity_curve': eq, 'trades': trades})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] calculate_performance: 总收益{data["return_metrics"]["total_return"]}, 夏普{data["risk_adjusted_metrics"]["sharpe_ratio"]}')

    # 8. list_performance_metrics
    r = await mcp.call_tool('list_performance_metrics', {})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    assert data['total_count'] >= 20
    print(f'[PASS] list_performance_metrics: {data["total_count"]}项指标')

    # 9. generate_trading_signal
    r = await mcp.call_tool('generate_trading_signal', {
        'highs': highs, 'lows': lows, 'closes': closes,
        'volumes': [10000] * 50
    })
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] generate_trading_signal: signal={data["signal"]}, score={data["score"]}')

    # 10. scan_stocks_for_signals
    r = await mcp.call_tool('scan_stocks_for_signals', {
        'stocks_data': {
            '000001': {'highs': highs, 'lows': lows, 'closes': closes, 'volumes': [10000] * 50},
            '600519': {'highs': highs, 'lows': lows, 'closes': closes, 'volumes': [10000] * 50},
        }
    })
    data = json.loads(extract_text(r))
    assert data['success'] is True
    assert data['summary']['total_scanned'] == 2
    print(f'[PASS] scan_stocks_for_signals: 扫描{data["summary"]["total_scanned"]}只')

    # 11. validate_signal_quality
    r = await mcp.call_tool('validate_signal_quality', {
        'closes': closes, 'signal_idx': 10, 'forward_days': 5
    })
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] validate_signal_quality: 收益{data["total_return_pct"]}%')

    # 12. calculate_factor_score
    r = await mcp.call_tool('calculate_factor_score', {
        'stock_codes': ['000001', '600519', '000858'],
        'factor_data': {
            'pe': [8.5, 30.2, 15.8],
            'roe': [12.0, 25.0, 18.0],
        }
    })
    data = json.loads(extract_text(r))
    assert data['success'] is True
    assert data['summary']['total_stocks'] == 3
    print(f'[PASS] calculate_factor_score: 评分前{data["scores"][0]["code"]}={data["scores"][0]["total_score"]}')

    # 13. get_factor_catalog
    r = await mcp.call_tool('get_factor_catalog', {})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] get_factor_catalog: {data["total_count"]}个因子')

    # 14. screen_stocks
    r = await mcp.call_tool('screen_stocks', {
        'stocks_data': [
            {'code': '000001', 'name': '平安银行', 'pe': 8.5, 'pb': 0.6, 'is_st': False},
            {'code': '600519', 'name': '贵州茅台', 'pe': 30.2, 'pb': 8.5, 'is_st': False},
            {'code': '000033', 'name': 'ST测试', 'pe': 5, 'pb': 1, 'is_st': True},
        ],
        'conditions': [
            {'field': 'pe', 'operator': '<', 'value': 20},
            {'field': 'is_st', 'operator': '==', 'value': False}
        ]
    })
    data = json.loads(extract_text(r))
    assert data['success'] is True
    assert data['summary']['total_matched'] == 1
    print(f'[PASS] screen_stocks: 输入3只，匹配{data["summary"]["total_matched"]}只')

    # 15. get_screening_conditions
    r = await mcp.call_tool('get_screening_conditions', {})
    data = json.loads(extract_text(r))
    assert data['success'] is True
    print(f'[PASS] get_screening_conditions: {data["total_count"]}个条件')

    print(f'\n=== 全部15个工具测试通过 ===')
    print(f'总工具数: {len(tools)} (其中V2.5.0新增15个)')
    return 0


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
