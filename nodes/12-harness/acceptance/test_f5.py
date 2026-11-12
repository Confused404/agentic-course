import json
import os
import subprocess
import sys


def run(tmp_path, payload, raw=None):
    f = tmp_path / "cart.json"
    f.write_text(raw if raw is not None else json.dumps(payload))
    ws = os.environ.get("PROMO_WORKSPACE", os.getcwd())
    return subprocess.run([sys.executable, "-m", "promo", "explain", str(f)], capture_output=True, text=True,
                          cwd=ws, timeout=30)


def test_explain_output(tmp_path):
    p = run(tmp_path, {"lines": [{"sku": "S", "unit_cents": 1000, "qty": 3}],
                       "coupons": [{"code": "Ten", "kind": "fixed", "amount_cents": 1005},
                                   {"code": "b", "kind": "bogo", "buy_sku": "S", "buy_qty": 2, "free_qty": 1},
                                   {"code": "ten", "kind": "fixed", "amount_cents": 1}],
                       "now": "2026-11-04T12:00:00+00:00"})
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == ["APPLIED b -$10.00", "APPLIED Ten -$10.05", "REJECTED ten (duplicate)",
                                     "TOTAL $9.95"]


def test_errors(tmp_path):
    for raw in ("{not json", json.dumps({"coupons": []}), json.dumps({"lines": [{"sku": "S"}]}),
                json.dumps({"lines": [], "coupons": [{"kind": "fixed"}]}),
                json.dumps({"lines": [], "now": "2026-11-04T12:00:00"})):
        p = run(tmp_path, None, raw)
        assert p.returncode == 2 and p.stdout == "" and p.stderr.startswith("error:"), raw
    missing = subprocess.run([sys.executable, "-m", "promo", "explain", str(tmp_path / "nope.json")],
                             capture_output=True, text=True, cwd=os.environ.get("PROMO_WORKSPACE", os.getcwd()))
    assert missing.returncode == 2 and missing.stdout == "" and missing.stderr.startswith("error:")
