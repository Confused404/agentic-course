import json
import threading

import pytest

from agentlab.llm import fake
from agentlab.multi import architectures as A
from agentlab.multi.tasks import TASKS, gold_top_units
from agentlab.multi.tools import categories

TOP = next(t for t in TASKS if t.id == "top_units_90d")


def brief(shard):
    return f"For every product in {shard}, report {{SKU: {{reviews, units_90d}}}}. Use product_stats in batches."


def test_single_agent_submits_once(conn):
    m = fake.ScriptedModel([fake.call("list_categories"), fake.call("submit_answer", answer=["A", "B", "C"]),
                            fake.say("done")])
    r = A.run_single(m, conn, TOP)
    assert r.answer == ["A", "B", "C"] and r.agents == 1 and r.error is None
    assert len(r.calls) == 3 and all(c.agent == "single" for c in r.calls)
    assert "submit_answer" in m.calls[0]["tools"] and "product_stats" in m.calls[0]["tools"]
    lazy = A.run_single(fake.ScriptedModel([fake.say("the answer is A, B, C")]), conn, TOP)
    assert lazy.answer is None and "no answer" in lazy.error


def test_submit_accepts_a_json_string_and_only_once(conn):
    m = fake.ScriptedModel([fake.call("submit_answer", answer='["X"]'), fake.call("submit_answer", answer=["Y"]),
                            fake.say("ok")])
    r = A.run_single(m, conn, TOP)
    assert r.answer == ["X"]
    assert "already submitted" in m.calls[2]["messages"][-1].content[0].text


def lead_script(conn, answer_from_results, extra_steps=()):
    shards = categories(conn)
    tasks = [{"shard": s, "brief": brief(s)} for s in shards]

    def answer(system, messages, tools, opts):
        res = json.loads(fake.last_tool_results(messages)[0].text)
        return fake.call("submit_answer", answer=answer_from_results(res))
    return [fake.call("delegate", tasks=tasks), *extra_steps, answer, fake.say("done")]


def top3(res):
    items = res["results"]
    return [k for k, _ in sorted(items.items(), key=lambda kv: (-kv[1]["units_90d"], kv[0]))[:3]]


def test_orchestrator_isolated_parallel_workers(conn, naive_reconcile, oracle_worker, oracle_data):
    data = oracle_data
    log = []
    barrier = threading.Barrier(6, timeout=10)
    lead = fake.ScriptedModel(lead_script(conn, top3))
    r = A.run_orchestrator(lead, lambda: oracle_worker(data, barrier=barrier, log=log), conn, TOP)
    assert r.answer == gold_top_units(conn), r.error
    assert r.agents == 7 and r.delegations == 1 and r.missing_shards == []
    assert sorted(x["shard"] for x in log) == categories(conn)
    for x in log:
        first = x["first_messages"]
        assert len(first) == 1 and TOP.question not in first[0], "a worker sees ONLY its brief"
        assert x["tools"] == ["list_categories", "list_products", "list_reviews", "product_stats", "report"]
    assert "product_stats" not in lead.calls[0]["tools"], "the lead can't query data itself"
    roles = r.tokens_by_role()
    assert set(roles) == {"lead", "worker"}


def test_orchestrator_reports_missing_and_redelegates(conn, naive_reconcile, oracle_worker, oracle_data):
    data = oracle_data
    seen = {}

    def check_missing(system, messages, tools, opts):
        res = json.loads(fake.last_tool_results(messages)[0].text)
        seen.update(res)
        return fake.call("delegate", tasks=[{"shard": "kitchen", "brief": brief("kitchen")}])
    workers = iter([oracle_worker(data, skip={"kitchen"}) for _ in range(6)] + [oracle_worker(data)])
    lock = threading.Lock()

    def factory():
        with lock:
            return next(workers)
    lead = fake.ScriptedModel(lead_script(conn, lambda res: ["?"], extra_steps=[check_missing]))
    r = A.run_orchestrator(lead, factory, conn, TOP)
    assert seen["missing_shards"] == ["kitchen"] and seen["not_yet_covered"] == ["kitchen"]
    assert r.delegations == 2 and r.missing_shards == [] and r.agents == 8


def test_delegate_validates(conn, naive_reconcile):
    lead = fake.ScriptedModel([
        fake.call("delegate", tasks=[{"shard": "toys", "brief": brief("toys")}]),
        fake.call("delegate", tasks=[{"shard": "bags", "brief": "do it"}]),
        fake.call("delegate", tasks=[]),
        fake.call("delegate", tasks=[{"shard": "bags", "brief": brief("bags")}, {"shard": "bags", "brief": brief("x")}]),
        fake.say("giving up")])
    r = A.run_orchestrator(lead, lambda: pytest.fail("no worker should start"), conn, TOP)
    errs = [m.content[0].text for m in lead.calls[-1]["messages"] if m.role == "user"][1:]
    assert "Unknown shard" in errs[0] and "too short" in errs[1] and "empty" in errs[2] and "twice" in errs[3]
    assert r.answer is None and r.delegations == 0 and r.missing_shards == categories(conn)


def test_delegation_limit(conn, naive_reconcile, oracle_worker, oracle_data):
    data = oracle_data
    one = [{"shard": "bags", "brief": brief("bags")}]
    lead = fake.ScriptedModel([fake.call("delegate", tasks=one), fake.call("delegate", tasks=one),
                               fake.say("stop")])
    A.run_orchestrator(lead, lambda: oracle_worker(data), conn, TOP, max_delegations=1)
    assert "limit" in lead.calls[-1]["messages"][-1].content[0].text


def test_a_crashing_worker_is_a_missing_shard(conn, naive_reconcile, oracle_worker, oracle_data):
    class Boom:
        provider, model = "fake", "boom"

        def complete(self, **kw):
            raise RuntimeError("worker exploded")
    made = iter([oracle_worker(oracle_data), Boom(), oracle_worker(oracle_data)])
    lock = threading.Lock()

    def factory():
        with lock:
            return next(made)
    tasks = [("bags", brief("bags")), ("kitchen", brief("kitchen")), ("lighting", brief("lighting"))]
    reports = A.run_workers(factory, conn, tasks, None, [], lock, {}, "t", max_parallel=1)
    assert [r.ok for r in reports] == [True, False, True], "one crash doesn't stop the others"
    assert "exploded" in reports[1].notes and reports[1].error_kind == "agent"


def test_map_reduce_retries_missing_once_and_reduces(conn, naive_reconcile, oracle_worker, oracle_data):
    data = oracle_data
    made = []
    lock = threading.Lock()

    def factory():
        with lock:
            made.append(1)
            return oracle_worker(data, skip={"outdoor"} if len(made) <= 6 else ())
    gold = gold_top_units(conn)
    sent = {}

    def reducer_step(system, messages, tools, opts):
        sent["payload"] = messages[0].text
        return fake.say("```json\n" + json.dumps({"answer": gold}) + "\n```")
    reducer = fake.ScriptedModel([reducer_step])
    r = A.run_map_reduce(factory, reducer, conn, TOP)
    assert len(made) == 7, "one retry, for the one missing shard"
    assert r.answer == gold and r.missing_shards == [] and r.agents == 8
    assert TOP.question in sent["payload"] and "OUT-" in sent["payload"]
    assert reducer.calls[0]["tools"] == [], "the reducer is one plain call"
    assert sum(c.agent == "reducer" for c in r.calls) == 1 and "reducer" in r.tokens_by_role()
    assert sum(c.agent.startswith("worker:") for c in r.calls) == 7 * 3 - 1, "retried workers are metered too"


def test_map_reduce_brief_carries_question_and_shard(conn, naive_reconcile, oracle_worker, oracle_data):
    log = []
    reducer = fake.ScriptedModel([fake.say("not json")])
    r = A.run_map_reduce(lambda: oracle_worker(oracle_data, log=log), reducer, conn, TOP)
    assert all(TOP.question in x["first_messages"][0] and x["shard"] in x["first_messages"][0] for x in log)
    assert r.answer is None and "unparseable" in r.error


def test_peak_context_is_per_call(conn, naive_reconcile, oracle_worker, oracle_data, sized):
    data = oracle_data
    lead = sized(fake.ScriptedModel(lead_script(conn, top3)))
    r = A.run_orchestrator(lead, lambda: sized(oracle_worker(data)), conn, TOP)
    assert r.peak_context == max(c.input_tokens for c in r.calls)
    assert r.peak_context < r.input_tokens, "no single prompt holds everything"


@pytest.mark.parametrize("spec", ["single:fast", "orch:mid:fast", "mapreduce:fast:mid", "orch:fast:fast@brief2"])
def test_parse_arch_ok(spec):
    A.parse_arch(spec)


@pytest.mark.parametrize("spec", ["", "single", "single:a:b", "orch:mid", "orch:mid:", "map:fast:mid", "single:fast@"])
def test_parse_arch_bad(spec):
    with pytest.raises(ValueError):
        A.parse_arch(spec)


def test_provider_failure_keeps_accounting(conn):
    from agentlab.costs import Budget
    from agentlab.llm.types import Usage

    class RateLimitError(Exception):
        pass
    b = Budget(limit_usd=1.0)
    m = fake.ScriptedModel([fake.call("list_categories", _usage_override=Usage(input_tokens=1000, output_tokens=10)),
                            fake.fail(RateLimitError("429"))])
    m.model = "claude-haiku-5-5"
    r = A.run_single(m, conn, TOP, budget=b)
    assert r.error and "RateLimitError" in r.error and r.provider_errors == 1
    assert r.cost_usd == pytest.approx(b.spent_usd) and r.cost_usd > 0 and len(r.calls) == 1
