# Architecture

Simulation only. Nothing in this repository connects to a real robot, PLC, industrial system or physical
equipment, and the simulated tools have no network or hardware capability.

## Components and boundaries

```text
datasets/*.jsonl  --load-->  evaluation.dataset  --validate-->  evaluation.oracle (exact, independent)
                                    |                                  ^
                                    v                                  | recomputes every expectation
                              evaluation.runner  --per case-->  simulator.Simulator  <-- tools.registry (11 tools)
                                    |   ^                              ^
                  agents.* (common  |   | RecordingToolClient          | same call path
                  Agent interface) -+---+ (harness records calls)      |
                                    |                         mcp_server (optional) -> any MCP client
                                    v
                            evaluation.scoring -> per-case record (cases.jsonl, events.jsonl)
                                    v
                            evaluation.metrics.summarize (pure function of cases.jsonl) -> summary.json
                                    v
              evaluation.report / compare / regression / experiments  -> Markdown + JSON
```

| package | responsibility | depends on |
|---|---|---|
| `domain` | error taxonomy, `Point`, `ToolResult`, `AgentOutput`, `BenchmarkCase` schema | pydantic |
| `simulator` | world data, float geometry, checks, planner, `Simulator` (validation, fault injection, op log) | domain |
| `tools` | strict arg schemas, 11 tool handlers + registry, tool clients, generated docs | simulator, domain |
| `evaluation.oracle` | **independent** exact rational geometry (`Fraction`, squared distances, no sqrt) | domain only (does *not* import `simulator.geometry/checks`) |
| `evaluation.groundtruth` | derives `Expected` for a case from world + hidden intent | oracle |
| `evaluation.dataset/generator/audit` | I/O, validation, seeded generation, audit | groundtruth, simulator |
| `agents` | common `Agent` protocol; reference, mock fixtures, two-stage, LLM, provider adapters | tools (client interface only) |
| `evaluation.scoring/metrics/runner/...` | scoring, aggregation, run directories, comparison, regression, experiments | all of the above |
| `observability` | local JSONL event log, redaction, optional Langfuse exporter | - |
| `mcp_server` (extra `mcp`) | MCP plumbing around `Simulator.call` | simulator, tools |

Rules that keep the evaluation honest:

1. The simulator and oracle are deterministic and know nothing about any LLM.
2. Agents receive only the prompt, a `ToolClient` and a `RunContext(seed, case_id)` - never the world spec, the
   expected result or oracle notes.
3. The evaluator trusts only what the harness recorded (tool calls, final pose) and checks the agent's *claims*
   (status, answer, failure code) against oracle-derived expectations.
4. Every state-changing action is validated by the simulator regardless of what the agent says.
5. Optional integrations (LLM, MCP, Langfuse) sit behind adapters; their absence never breaks offline tests.

## Data flow of one case

1. `run_benchmark` builds a fresh `Simulator(world, faults)` for the case and a `RecordingToolClient`.
2. `agent.run(prompt, tools, ctx)` returns an `AgentOutput` (status, message, structured `answer`, `failure_code`,
   stage timings, usage). Crashes and budget overruns become `status="error"` with a sanitized message.
3. `score_case` compares the trace, final pose and claims with the oracle-derived `Expected` and writes a record.
4. Records are appended to `cases.jsonl` (strict JSON, NaN/inf as strings) and events to `events.jsonl`.
5. After all cases, `summarize(records)` writes `summary.json`; `report.md` is rendered from the saved files.

Run directory (never overwritten; a numeric suffix is added on collision):
`outputs/runs/<UTC timestamp>_<agent>_<version>_<split>/{metadata.json, cases.jsonl, events.jsonl, summary.json, report.md}`.

## Tools, worlds and conventions

Eleven tools (`docs/tools.md` has real example outputs): `get_workcell_state`, `check_reachability`,
`check_collision`, `check_clearance`, `validate_joint_limits`, `plan_path`, `validate_path`,
`estimate_operation_feasibility`, `move_end_effector` (the only state-changing one), `inspect_tool_schema`,
`get_simulation_diagnostics`. Five worlds in `datasets/worlds.json` (circular obstacles, annular reach band,
rectangular workspace, per-joint limits). Units: metres and degrees; x right, y up.

## Agents

| name | what it is |
|---|---|
| `reference` | regex/keyword baseline (A). Not an LLM, not an upper bound. Unguarded. |
| `reference_guarded` | same agent + `validate_args`, `verify` (pre/post checks), `refuse_overrides` (RQ2). |
| `reference_{validate,verify,refuse}_only` | single-component ablations (exploratory). |
| `reference_regressed` | **test fixture**: injected clearance->collision routing bug (Experiment 5). |
| `mock_<mode>` | **test fixtures** (B): wrong tool, malformed args, crash, fabricate, always_move, ... Never models. |
| `two_stage_rule` | triage -> execution with rule backends (D, offline). |
| `llm_single`, `llm_two_stage` | optional LLM agents (C/D) via the provider boundary; need credentials. |

Guards never disable the simulator: the same hard constraints apply in every configuration.

## Optional LLM provider (Anthropic Messages API)

Install `pip install -e ".[llm]"` and set `ANTHROPIC_API_KEY` (environment or a local, git-ignored `.env`) and
`ROBOT_EVAL_LLM_MODEL`. No model is hard-coded: the model id is operator-supplied. Behaviour, per the API facts
checked on 2026-10-22:

* no `temperature`/`top_p`/`top_k` are sent (current API versions reject them), so runs are *not* seed-controlled -
  use `--repeats` and read the repeatability section;
* no forced `tool_choice`; the final result is returned through a `submit_result` tool, which must be called alone;
* provider `stop_reason: "refusal"`, timeouts, rate limits etc. become `status="error"` records and are never
  credited as a task refusal; token usage unknown stays `null`; cost is only an estimate when `pricing` is configured;
* bounded: `max_rounds`, `max_tokens`, SDK `max_retries`, per-request `timeout_s`, and a run-wide budget
  (`max_total_tokens`, `max_cost_usd`, `max_requests`).

If credentials, model or package are missing, `robot-eval run --agent llm_single` prints why and exits with code 3,
without running anything. **The live API path has not been exercised** (no credentials in the build environment);
it is covered by a scripted provider and a fake SDK client only.

## MCP server (optional extra `mcp`, mcp 2.3)

`pip install -e ".[mcp]"` then `robot-eval mcp-serve --world cell_a` serves the tools over stdio using the
low-level `mcp.server.lowlevel.Server` (mcp 2.x renamed FastMCP to MCPServer; the low-level server was chosen so the
published JSON schemas are exactly the strict pydantic schemas and validation happens once, in the simulator).
Results are structured (`structuredContent` = `ToolResult`: ok, error_code, message, data, operation_id) with
`isError` set on failures. One simulator instance lives for the process lifetime (pose persists across calls).

Python client example:

```python
import anyio, sys
from mcp import Client, StdioServerParameters

async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "robot_eval.cli", "mcp-serve", "--world", "cell_a"])
    async with Client(params) as c:
        print([t.name for t in (await c.list_tools()).tools])
        r = await c.call_tool("move_end_effector", {"x": 1.2, "y": 0.9})   # into an obstacle
        print(r.is_error, r.structured_content["error_code"])               # True COLLISION

anyio.run(main)
```

`robot-eval run --transport mcp` executes a benchmark through an in-process MCP session; per-case records are
identical to the direct transport on the 12 smoke cases covered by `tests/integration/test_mcp.py`.

## Logging and optional remote tracing

* Always on, local: `events.jsonl` (run/case/tool/stage events with `trace_id`/`span_id`) and `cases.jsonl`.
  Secrets are redacted by key name and value pattern before writing; exceptions are recorded as sanitized
  `Type: message` strings (max 500 chars).
* Opt-in Langfuse: `--tracing` or `ROBOT_EVAL_LANGFUSE=1` plus `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`
  (`pip install -e ".[tracing]"`). **Transmitted:** prompt text, tool names/arguments/ok/error codes, agent
  status/message/answer, model id, token counts, latencies and four boolean scores. **Not transmitted:** expected
  outcomes/answers, oracle notes, dataset files, API keys. Export errors are recorded in `export_status` and
  never fail a run. Written against the installed `langfuse` 5.0.4 API as documented by its docstrings
  (langfuse.com was unreachable from the build sandbox); live export is untested.
