"""JSON tool protocol — parsing across model quirks (think blocks, fences)."""

import pytest

from new_horizons.shared.harness.protocol import Final, ProtocolError, ToolCall, parse_decision


def test_plain_tool_call():
    d = parse_decision('{"tool": "sql_query", "args": {"sql": "SELECT 1"}}')
    assert isinstance(d, ToolCall) and d.tool == "sql_query"


def test_final_with_citations():
    d = parse_decision('{"final": "4,128,996 دينار", '
                       '"citations": [{"source": "121007.pdf", "page": 10}]}')
    assert isinstance(d, Final)
    assert d.citations[0].page == 10


def test_think_block_stripped():
    raw = "<think>let me reason…\n{\"tool\": \"fake\"}</think>\n" \
          '{"tool": "kb_search", "args": {"query": "التعرفة"}}'
    d = parse_decision(raw)
    assert isinstance(d, ToolCall) and d.tool == "kb_search"


def test_unclosed_think_block():
    raw = '<think>reasoning forever with {"tool": "x"}'
    with pytest.raises(ProtocolError):
        parse_decision(raw)


def test_fenced_json():
    raw = 'Here is my move:\n```json\n{"tool": "drift_report", "args": {}}\n```'
    d = parse_decision(raw)
    assert isinstance(d, ToolCall) and d.tool == "drift_report"


def test_prose_wrapped_json():
    raw = 'Sure! I will use {"tool": "pattern_scan", "args": {}} now.'
    d = parse_decision(raw)
    assert isinstance(d, ToolCall) and d.tool == "pattern_scan"


def test_nested_braces_in_args():
    raw = '{"tool": "sql_query", "args": {"sql": "SELECT \'{a}\' FROM t"}}'
    d = parse_decision(raw)
    assert d.args["sql"] == "SELECT '{a}' FROM t"


def test_garbage_raises():
    with pytest.raises(ProtocolError):
        parse_decision("I cannot answer that.")
