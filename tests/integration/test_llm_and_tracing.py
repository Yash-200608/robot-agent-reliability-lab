"""Gate 6: optional LLM and Langfuse adapters. Everything is offline: scripted provider + fake clients.
No real API call is made anywhere in this file."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from robot_eval.agents.factory import AgentUnavailable, build_agent
from robot_eval.agents.llm import LLMAgent, LLMCore, RunBudget, build_llm_agent, build_two_stage
from robot_eval.agents.providers import (
    AnthropicProvider,
    LLMResponse,
    ProviderError,
    ScriptedProvider,
    inline_refs,
    tool_call_response,
)
from robot_eval.config import load_dotenv
from robot_eval.domain.case import ExpectedOutcome, Family
from robot_eval.domain.errors import AgentStatus
from robot_eval.domain.models import Usage
from robot_eval.evaluation.dataset import load_cases
from robot_eval.evaluation.runner import RunOptions, run_benchmark, run_case
from robot_eval.evaluation.scoring import score_case
from robot_eval.observability.langfuse_adapter import LangfuseExporter, build_langfuse_exporter
from robot_eval.simulator.sim import Simulator
from robot_eval.simulator.world import load_worlds
from robot_eval.tools.registry import tool_descriptors

ROOT = Path(__file__).resolve().parents[2]
CASES = load_cases(ROOT / "datasets" / "v1" / "development.jsonl")
WORLDS = load_worlds(ROOT / "datasets" / "worlds.json")
CFG = ROOT / "configs" / "agents.yaml"


def case_of(fam: Family, outcome: ExpectedOutcome = ExpectedOutcome.SUCCESS):  # type: ignore[no-untyped-def]
    return next(
        c
        for c in CASES
        if c.intent.family is fam and c.expected.outcome is outcome and c.fault is None
    )


def submit(i: str, _inp: int | None = 10, _out: int | None = 5, **kw: Any) -> LLMResponse:
    return tool_call_response((i, "submit_result", kw), inp=_inp, out=_out)


def agent_with(script: list[Any], **core_kw: Any) -> tuple[LLMAgent, ScriptedProvider]:
    prov = ScriptedProvider(script)
    return LLMAgent("llm_test", LLMCore(prov, **core_kw), prompt_version="t1"), prov


def execute(case: Any, agent: Any) -> tuple[dict[str, Any], Any]:
    sim = Simulator(WORLDS[case.world_id], [case.fault] if case.fault else [])
    out, client, _ = run_case(case, agent, sim, 0, 40, 60)
    return score_case(case, WORLDS[case.world_id], client.records, out, sim.ee)["scoring"], out


# ------------------------------------------------------------------ availability / no credentials
def test_no_credentials_is_unavailable_not_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("anthropic")
    for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ROBOT_EVAL_LLM_MODEL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AgentUnavailable, match="ANTHROPIC_API_KEY"):
        build_agent("llm_single", CFG)


def test_missing_model_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.delenv("ROBOT_EVAL_LLM_MODEL", raising=False)
    with pytest.raises(AgentUnavailable, match="ROBOT_EVAL_LLM_MODEL"):
        build_llm_agent("x", {"provider": "anthropic"})


def test_missing_package_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)  # simulates a missing optional package
    with pytest.raises(AgentUnavailable, match="not installed"):
        build_llm_agent("x", {"provider": "anthropic"})
    with pytest.raises(AgentUnavailable, match="not installed"):
        build_agent("llm_single", CFG)


def test_unknown_provider_is_unavailable() -> None:
    with pytest.raises(AgentUnavailable, match="not implemented"):
        build_llm_agent("x", {"provider": "other"})


def test_agent_builds_when_configured_without_any_network(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ROBOT_EVAL_LLM_MODEL", "some-model-id")
    ag = build_agent("llm_two_stage", CFG)  # constructing performs no request
    d = ag.describe()
    assert d["llm"] is True and d["model"] == "some-model-id" and "key" not in json.dumps(d).lower()


def test_dotenv_loader_never_overrides_and_returns_names_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nA_NEW_VAR=abc\nexport QUOTED='x y'\nALREADY_SET=from_file\nEMPTY=\n")
    monkeypatch.delenv("A_NEW_VAR", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.setenv("ALREADY_SET", "from_env")
    names = load_dotenv(env)
    assert sorted(names) == ["A_NEW_VAR", "QUOTED"]
    assert os.environ["ALREADY_SET"] == "from_env" and os.environ["QUOTED"] == "x y"
    monkeypatch.delenv("A_NEW_VAR")
    monkeypatch.delenv("QUOTED")


# ------------------------------------------------------------------------------ loop behaviours
def test_happy_path_single_stage_uses_tools_and_records_usage() -> None:
    case = case_of(Family.QUERY_REACH)
    p = case.intent.params
    ag, prov = agent_with(
        [
            tool_call_response(
                ("t1", "check_reachability", {"x": p["x"], "y": p["y"]}), inp=100, out=20
            ),
            submit(
                "t2", status="completed", answer={"reachable": case.expected.answer["reachable"]}
            ),
        ]
    )
    sc, out = execute(case, ag)
    assert sc["task_success"] and sc["tool_selection_correct"] and sc["arguments_valid_case"]
    # 100/20 (tool turn) + 10/5 (submit turn)
    assert (
        out.usage.input_tokens == 110
        and out.usage.output_tokens == 25
        and out.model_id == "scripted-test-double"
    )
    # the request carried tool schemas without $ref and no sampling parameters / forced tool choice
    first = prov.requests[0]
    assert {t["name"] for t in first["tools"]} == {d["name"] for d in tool_descriptors()} | {
        "submit_result"
    }
    assert "$ref" not in json.dumps(first["tools"]) and "$defs" not in json.dumps(first["tools"])
    # the tool result was returned to the model in a single user message
    tr = prov.requests[1]["messages"][-1]
    assert tr["role"] == "user" and tr["content"][0]["type"] == "tool_result"


def test_invalid_tool_arguments_surface_as_tool_errors_not_crashes() -> None:
    case = case_of(Family.QUERY_REACH)
    ag, prov = agent_with(
        [
            tool_call_response(("t1", "check_reachability", {"x": "one", "y": 2})),
            submit("t2", status="failed", failure_code="INVALID_ARGUMENT", message="bad args"),
        ]
    )
    sc, out = execute(case, ag)
    result = json.loads(prov.requests[1]["messages"][-1]["content"][0]["content"])
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert prov.requests[1]["messages"][-1]["content"][0]["is_error"] is True
    assert sc["n_calls"] == 1 and sc["n_calls_schema_valid"] == 0 and not sc["arguments_valid_case"]
    assert not sc["task_success"]  # expected success; failing is still scored against the oracle


def test_unknown_tool_from_model_is_rejected_by_simulator() -> None:
    case = case_of(Family.QUERY_REACH)
    ag, prov = agent_with(
        [tool_call_response(("t1", "launch_missiles", {})), submit("t2", status="failed")]
    )
    execute(case, ag)
    assert (
        json.loads(prov.requests[1]["messages"][-1]["content"][0]["content"])["error_code"]
        == "UNKNOWN_TOOL"
    )


def test_submit_must_be_alone_and_valid() -> None:
    case = case_of(Family.QUERY_REACH)
    p = case.intent.params
    ag, prov = agent_with(
        [
            tool_call_response(
                ("t1", "check_reachability", {"x": p["x"], "y": p["y"]}),
                ("t2", "submit_result", {"status": "completed", "answer": {"reachable": True}}),
            ),
            submit("t3", status="bogus"),  # invalid enum -> rejected, loop continues
            submit(
                "t4", status="completed", answer={"reachable": case.expected.answer["reachable"]}
            ),
        ]
    )
    sc, out = execute(case, ag)
    second = prov.requests[1]["messages"][-1]["content"]
    assert any("alone" in r["content"] and r["is_error"] for r in second)
    third = prov.requests[2]["messages"][-1]["content"]
    assert "invalid submit_result" in third[0]["content"]
    assert out.status is AgentStatus.COMPLETED and sc["task_success"]


def test_provider_timeout_is_an_agent_error_not_a_result() -> None:
    case = case_of(Family.QUERY_REACH)
    ag, _ = agent_with([ProviderError("timeout", "request timed out after 60s")])
    sc, out = execute(case, ag)
    assert out.status is AgentStatus.ERROR and "ProviderError(timeout)" in (out.error or "")
    assert not sc["task_success"] and sc["primary_failure_category"] == "agent_error"
    assert (
        out.answer == {} and out.usage.input_tokens is None
    )  # nothing invented, tokens unknown not zero


def test_provider_refusal_is_not_credited_as_a_safe_refusal() -> None:
    case = case_of(Family.MOVE, ExpectedOutcome.SAFE_REFUSAL)
    refusal = LLMResponse(
        text="",
        tool_calls=[],
        raw_content=[],
        stop_reason="refusal",
        usage=Usage(input_tokens=5, output_tokens=0),
        refusal_category="cyber",
    )
    ag, _ = agent_with([refusal])
    sc, out = execute(case, ag)
    assert out.status is AgentStatus.ERROR and "ProviderRefusal" in (out.error or "")
    assert not sc["task_success"]


def test_model_that_never_submits_is_an_error() -> None:
    case = case_of(Family.QUERY_REACH)
    plain = LLMResponse(
        text="I think it is reachable.",
        tool_calls=[],
        raw_content=[{"type": "text", "text": "x"}],
        stop_reason="end_turn",
        usage=Usage(input_tokens=3, output_tokens=3),
    )
    ag, prov = agent_with([plain, plain])
    sc, out = execute(case, ag)
    assert out.status is AgentStatus.ERROR and "NoResult" in (out.error or "")
    assert len(prov.requests) == 2  # exactly one nudge


def test_max_rounds_bounds_the_loop() -> None:
    case = case_of(Family.QUERY_REACH)
    ag, prov = agent_with(
        [tool_call_response((f"t{i}", "get_workcell_state", {})) for i in range(10)], max_rounds=3
    )
    _, out = execute(case, ag)
    assert (
        out.status is AgentStatus.ERROR
        and "MaxRounds" in (out.error or "")
        and len(prov.requests) == 3
    )


def test_budget_is_enforced_across_cases() -> None:
    case = case_of(Family.QUERY_REACH)
    p = case.intent.params
    script = [
        tool_call_response(("t", "check_reachability", {"x": p["x"], "y": p["y"]}), inp=60, out=40),
        submit("s", status="completed", answer={"reachable": True}),
    ]
    ag, prov = agent_with(script + script, budget=RunBudget(max_total_tokens=100))
    _, out1 = execute(
        case, ag
    )  # first request consumes 100 tokens -> second request is refused by the budget
    assert out1.status is AgentStatus.ERROR and "BudgetExceeded" in (out1.error or "")
    _, out2 = execute(case, ag)
    assert (
        out2.status is AgentStatus.ERROR and len(prov.requests) == 1
    )  # no further provider calls were made


def test_unreported_usage_stays_null() -> None:
    case = case_of(Family.QUERY_REACH)
    p = case.intent.params
    ag, _ = agent_with(
        [
            tool_call_response(
                ("t", "check_reachability", {"x": p["x"], "y": p["y"]}), inp=None, out=None
            ),
            submit(
                "s",
                None,
                None,
                status="completed",
                answer={"reachable": case.expected.answer["reachable"]},
            ),
        ]
    )
    _, out = execute(case, ag)
    assert (
        out.usage.input_tokens is None
        and out.usage.output_tokens is None
        and out.usage.cost_usd is None
    )


# --------------------------------------------------------------------------------- two-stage LLM
def triage(i: str, **kw: Any) -> LLMResponse:
    return tool_call_response((i, "submit_triage", kw))


def test_two_stage_llm_clarify_skips_execution() -> None:
    case = next(c for c in CASES if c.expected.outcome is ExpectedOutcome.CLARIFICATION)
    prov = ScriptedProvider([triage("a", action="clarify", family="move", reason="missing y")])
    ag = build_two_stage("llm2", LLMCore(prov), "t1")
    sc, out = execute(case, ag)
    assert out.status is AgentStatus.CLARIFICATION and sc["task_success"] and sc["n_calls"] == 0
    assert [s["stage"] for s in out.stages] == ["triage"] and len(prov.requests) == 1


def test_two_stage_llm_proceed_logs_both_stages_and_merges_usage() -> None:
    case = case_of(Family.QUERY_REACH)
    p = case.intent.params
    prov = ScriptedProvider(
        [
            triage("a", action="proceed", family="reachability", reason="complete"),
            tool_call_response(
                ("t", "check_reachability", {"x": p["x"], "y": p["y"]}), inp=50, out=10
            ),
            submit(
                "s", status="completed", answer={"reachable": case.expected.answer["reachable"]}
            ),
        ]
    )
    ag = build_two_stage("llm2", LLMCore(prov), "t1")
    sc, out = execute(case, ag)
    assert sc["task_success"] and [s["stage"] for s in out.stages] == ["triage", "execution"]
    # triage 10/5 + tool turn 50/10 + submit 10/5
    assert out.usage.input_tokens == 70 and out.usage.output_tokens == 20
    assert "triage stage" in prov.requests[1]["system"]


def test_two_stage_llm_bad_triage_is_recorded_as_error(tmp_path: Path) -> None:
    prov = ScriptedProvider(
        [
            LLMResponse(
                text="proceed", tool_calls=[], raw_content=[], stop_reason="end_turn", usage=Usage()
            )
        ]
    )
    ag = build_two_stage("llm2", LLMCore(prov), "t1")
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "benchmark_v0.jsonl",
            agent="llm2",
            out_root=tmp_path,
            limit=1,
        ),
        ag,
    )
    assert (
        res.records[0]["status"] == "error"
        and "did not call submit_triage" in res.records[0]["error"]
    )


# --------------------------------------------------------------------------- Anthropic adapter
class FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self.outcome, self.kwargs = outcome, None

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome: Any) -> None:
        self.messages = FakeMessages(outcome)
        self.options: dict[str, Any] = {}

    def with_options(self, **kw: Any) -> FakeClient:
        self.options = kw
        return self


def sdk_response(**kw: Any) -> Any:
    base = dict(
        content=[
            SimpleNamespace(type="text", text="ok"),
            SimpleNamespace(
                type="tool_use", id="tu1", name="check_collision", input={"x": 1, "y": 2}
            ),
        ],
        stop_reason="tool_use",
        model="m-1",
        stop_details=None,
        _request_id="req_123",
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=7,
            cache_creation_input_tokens=3,
            cache_read_input_tokens=5,
        ),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_anthropic_request_shape_and_response_mapping() -> None:
    pytest.importorskip("anthropic")
    client = FakeClient(sdk_response())
    prov = AnthropicProvider(
        "model-x",
        client=client,
        effort="low",
        pricing={"input_per_mtok": 1.0, "output_per_mtok": 2.0},
    )
    r = prov.complete(
        system="S",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "t"}],
        max_tokens=123,
        timeout_s=9,
    )
    kw = client.messages.kwargs
    assert (
        kw["model"] == "model-x"
        and kw["max_tokens"] == 123
        and kw["tool_choice"] == {"type": "auto"}
    )
    assert kw["output_config"] == {"effort": "low"} and client.options == {"timeout": 9}
    for banned in ("temperature", "top_p", "top_k", "thinking", "betas"):
        assert banned not in kw
    assert (
        r.text == "ok"
        and r.tool_calls[0].name == "check_collision"
        and r.tool_calls[0].arguments == {"x": 1, "y": 2}
    )
    assert (
        r.usage.input_tokens == 18
        and r.usage.output_tokens == 7
        and r.usage.request_ids == ["req_123"]
    )
    assert r.usage.cost_usd == pytest.approx((18 * 1.0 + 7 * 2.0) / 1e6)
    # without configured prices the cost is unknown, not zero
    assert (
        AnthropicProvider("m", client=FakeClient(sdk_response()))
        .complete(system="", messages=[], tools=[], max_tokens=1)
        .usage.cost_usd
        is None
    )


def test_anthropic_refusal_details_surface() -> None:
    pytest.importorskip("anthropic")
    resp = sdk_response(
        content=[], stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")
    )
    r = AnthropicProvider("m", client=FakeClient(resp)).complete(
        system="", messages=[], tools=[], max_tokens=1
    )
    assert r.stop_reason == "refusal" and r.refusal_category == "cyber"


def test_anthropic_sdk_errors_map_to_provider_errors() -> None:
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    req = httpx2.Request("POST", "https://example.invalid/v1/messages")

    def status_err(cls: Any, code: int) -> Exception:
        return cls(
            "boom api_key=sk-secretsecretsecret1234",
            response=httpx2.Response(code, request=req),
            body=None,
        )

    cases = [
        (anthropic.APITimeoutError(request=req), "timeout"),
        (anthropic.APIConnectionError(request=req), "connection"),
        (status_err(anthropic.RateLimitError, 429), "rate_limit"),
        (status_err(anthropic.AuthenticationError, 401), "auth"),
        (status_err(anthropic.BadRequestError, 400), "bad_request"),
        (status_err(anthropic.InternalServerError, 500), "server"),
    ]
    for exc, kind in cases:
        with pytest.raises(ProviderError) as ei:
            AnthropicProvider("m", client=FakeClient(exc)).complete(
                system="", messages=[], tools=[], max_tokens=1
            )
        assert ei.value.kind == kind
        assert "secretsecret" not in str(ei.value)


def test_inline_refs_resolves_nested_schemas() -> None:
    plan = next(d for d in tool_descriptors() if d["name"] == "plan_path")["input_schema"]
    assert "$defs" in plan
    flat = inline_refs(plan)
    assert (
        "$ref" not in json.dumps(flat)
        and flat["properties"]["start"]["properties"]["x"]["type"] == "number"
    )


# ------------------------------------------------------------------------------------ Langfuse
def fake_langfuse_module() -> Any:
    return SimpleNamespace(
        Langfuse=lambda: FakeLangfuse(), propagate_attributes=lambda **kw: FakeCtx([], "p", kw)
    )


def test_tracing_off_by_default_and_unavailable_paths_degrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBOT_EVAL_LANGFUSE", raising=False)
    assert build_langfuse_exporter().name == "none"
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setitem(
        sys.modules, "langfuse", fake_langfuse_module()
    )  # independent of the installed extra
    ex = build_langfuse_exporter(enabled=True)
    assert ex.name == "langfuse" and ex.status().startswith("missing_credentials")
    monkeypatch.setitem(sys.modules, "langfuse", None)
    assert build_langfuse_exporter(enabled=True).status().startswith("package_not_installed")


def test_tracing_enabled_with_credentials_builds_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse_module())
    ex = build_langfuse_exporter(enabled=True)
    assert isinstance(ex, LangfuseExporter) and ex.status() == "enabled"
    monkeypatch.setenv("ROBOT_EVAL_LANGFUSE", "1")
    assert isinstance(build_langfuse_exporter(), LangfuseExporter)  # env flag also opts in


def test_run_completes_locally_when_tracing_requested_but_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse_module())
    ex = build_langfuse_exporter(enabled=True)
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "benchmark_v0.jsonl",
            agent="reference",
            agent_config=CFG,
            out_root=tmp_path,
            limit=3,
        ),
        exporter=ex,
    )
    assert len(res.records) == 3 and res.metadata["tracing"]["status"].startswith(
        "missing_credentials"
    )
    assert (res.run_dir / "cases.jsonl").exists()


class FakeCtx:
    def __init__(self, log: list[Any], name: str, kw: dict[str, Any]) -> None:
        self.log, self.name, self.kw = log, name, kw

    def __enter__(self) -> FakeCtx:
        self.log.append((self.name, self.kw))
        return self

    def __exit__(self, *a: Any) -> None:
        return None


class FakeLangfuse:
    def __init__(self) -> None:
        self.log: list[Any] = []
        self.scores: list[dict[str, Any]] = []
        self.flushed = False

    def create_trace_id(self, seed: str | None = None) -> str:
        return "a" * 32

    def start_as_current_observation(self, **kw: Any) -> FakeCtx:
        return FakeCtx(self.log, "obs", kw)

    def create_score(self, **kw: Any) -> None:
        self.scores.append(kw)

    def flush(self) -> None:
        self.flushed = True


def test_langfuse_export_payload_excludes_labels_and_secrets(tmp_path: Path) -> None:
    fake = FakeLangfuse()
    prop_calls: list[dict[str, Any]] = []
    ex = LangfuseExporter(fake, lambda **kw: FakeCtx(prop_calls, "prop", kw))
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "benchmark_v0.jsonl",
            agent="reference",
            agent_config=CFG,
            out_root=tmp_path,
            limit=4,
        ),
        exporter=ex,
    )
    assert (
        all(r["export_status"].startswith("exported trace") for r in res.records) and fake.flushed
    )
    blob = json.dumps([fake.log, fake.scores, prop_calls], default=str)
    assert "oracle" not in blob and "expected" not in blob and "ANTHROPIC" not in blob
    assert {s["name"] for s in fake.scores} == {
        "task_success",
        "tool_selection_correct",
        "safe_outcome",
        "false_safe_claim",
    }
    assert all(s["data_type"] == "BOOLEAN" for s in fake.scores)


def test_langfuse_failures_never_break_a_run(tmp_path: Path) -> None:
    class Broken(FakeLangfuse):
        def create_trace_id(self, seed: str | None = None) -> str:
            raise ConnectionError("cannot reach host key=sk-lf-secretsecretsecret")

        def flush(self) -> None:
            raise TimeoutError("flush timeout")

    ex = LangfuseExporter(Broken(), lambda **kw: FakeCtx([], "p", kw))
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "benchmark_v0.jsonl",
            agent="reference",
            agent_config=CFG,
            out_root=tmp_path,
            limit=2,
        ),
        exporter=ex,
    )
    assert all(
        r["export_status"].startswith("error:") and "secretsecret" not in r["export_status"]
        for r in res.records
    )
    assert res.metadata["tracing"]["flush"].startswith("error:") and len(res.records) == 2
