"""results.py: JSONL round trip and summary statistics."""
import pytest

from agentlab.probe.results import ProbeResult, append_jsonl, load_jsonl, summarize


def R(model, label, ttft, total, out=100, err=None, **extra):
    return ProbeResult("e", "p", model, label=label, ttft_s=ttft, total_s=total, output_tokens=out,
                       error=err, extra=extra, params={"T": label})


def test_output_tps():
    assert R("m", "a", 1.0, 3.0, out=200).output_tps == pytest.approx(100.0)
    assert R("m", "a", None, 3.0).output_tps is None
    assert R("m", "a", 2.0, 2.0).output_tps is None


def test_jsonl_roundtrip(tmp_path):
    p = tmp_path / "sub" / "r.jsonl"
    a = R("m", "x", 0.5, 1.0, ok=True)
    a.tool_calls = [{"id": "1", "name": "t", "arguments": {"a": 1}, "raw_arguments": None, "parse_error": None}]
    append_jsonl(p, a)
    append_jsonl(p, R("m", "y", None, 2.0))
    back = load_jsonl(p)
    assert len(back) == 2 and back[0] == a and back[1].ttft_s is None


def test_summarize_groups_stats_and_excludes_errors_and_none():
    rs = [R("m1", "a", 1.0, 2.0), R("m1", "a", 3.0, 4.0), R("m1", "a", None, 9.0, err="boom"),
          R("m2", "a", None, 1.0), R("m1", "b", 2.0, 2.0)]
    rows = summarize(rs, ["model", "label"], ["ttft_s", "total_s"])
    assert [(r["model"], r["label"]) for r in rows] == [("m1", "a"), ("m2", "a"), ("m1", "b")]
    g = rows[0]
    assert g["n"] == 3 and g["errors"] == 1
    assert g["ttft_s_mean"] == pytest.approx(2.0) and g["total_s_mean"] == pytest.approx(3.0)
    assert g["ttft_s_std"] == pytest.approx(1.4142, rel=1e-3)
    assert rows[1]["ttft_s_mean"] is None and rows[1]["total_s_std"] == 0.0
    assert rows[2]["total_s_p50"] == 2.0


def test_summarize_params_and_extra_and_percentiles():
    rs = [R("m", "a", None, float(i), ok=(i % 2 == 0)) for i in range(1, 11)]
    rows = summarize(rs, ["params.T"], ["total_s", "extra.ok"])
    assert rows[0]["params.T"] == "a"
    assert rows[0]["total_s_p50"] == 5.0 and rows[0]["total_s_p90"] == 9.0      # nearest-rank
    assert rows[0]["extra.ok_mean"] == pytest.approx(0.5)
