# Limitations, threat model and safety statement

## Non-certification statement

This project is a **simulation-only research prototype** for studying how to evaluate tool-using AI agents. It does
**not** certify, validate or demonstrate that any agent, guard, or process is safe for real industrial, robotic or
safety-critical use. No result here supports a claim of industrial readiness, functional safety (e.g. ISO 10218 /
IEC 61508), or regulatory compliance. Do not connect these tools to real equipment.

## What the simulator is and is not

* 2-D point end effector, circular obstacles, an annular reach band, rectangular workspace and box joint limits. There
  is no kinematic chain, no dynamics, no sensor noise, no time, no tool geometry beyond a point, and no 3-D.
* `validate_joint_limits` checks supplied angles against limits; joint angles are not coupled to end-effector position.
* The planner is a small visibility graph and is **incomplete**: failing to find a path does not prove none exists.
  Benchmark cases are restricted to ones where an independent witness path or an exact blocking certificate exists.
* Equality semantics (touching = collision; margin equality = safe; closed intervals) are a modelling choice,
  documented and tested; another reasonable convention would change some boundary answers.

## Threat model (what the evaluation guards against, and what it does not)

In scope: an agent mis-selecting tools, sending malformed/unsafe arguments, claiming success it did not achieve,
ignoring user-supplied constraints the simulator does not know about, mishandling tool faults, being talked into
bypassing checks, or fabricating results. The simulator re-validates every state-changing call independently of any
justification the agent gives.

Out of scope: prompt injection through tool outputs or datasets, adversarial users, malicious tool servers,
model-weight issues, side channels, and any real-world actuation. MCP is exposed over local stdio only; the server
has no authentication because it is not meant to be network-exposed. Do not bind it to a network interface.

## Unsafe outputs

The benchmark contains requests that ask an agent to ignore or override safety checks. The correct behaviour is
refusal or a reported failure; these cases test *refusal*, they do not contain harmful content. LLM-judged labels are
never used as safety ground truth - every expected outcome is recomputed with exact arithmetic.

## Evidence limits and known weaknesses

1. **Same-author benchmark.** One author wrote the dataset templates (both splits), the oracle and the reference agent.
   The held-out split is held out from *tuning*, not from the author's knowledge of the wording. Disjoint template
   pools reduce wording reuse but do not make the split independent. Development results were inspected while
   building the reference agent; held-out results were not (see `reports/heldout_access_log.jsonl`).
2. **Synthetic language.** Prompts are template-generated English with numeric values; they are far narrower than
   real operator language. Results do not generalise to real requests.
3. **Small, uneven coverage.** 288 v1 cases (164 development / 124 held-out) across 17 categories; several families
   have very few cases (e.g. `describe_state`, `schema_lookup`), so per-family rates are unreliable. Answer polarity
   is only roughly balanced; `plan_path` positive-answer cases are all "found".
4. **Rule-based comparisons are about rules.** The guard (RQ2) and two-stage (RQ3) experiments run on rule-based
   agents. Because the simulator already rejects every unsafe move, the guarded vs unguarded difference in
   *executed* unsafe actions is zero by construction; only *attempts*, call counts and latency differ. The two-stage
   rule agent differs from the single-stage one only by triage rules (contradiction detection).
5. **No LLM results exist in this repository.** The LLM adapter was never run against a live API (no credentials in
   the build environment). It is tested with a scripted provider and a fake SDK client only; Experiment 4's LLM arms
   are reported as blocked. Any LLM result must record model id, prompt version, date and repeats, and treat provider
   nondeterminism as a limitation (current APIs reject `temperature`/`top_p`/`top_k`, so there is no sampling control).
6. **Langfuse export is untested against a live server** and was written from the installed SDK's own docstrings
   because the online documentation was unreachable from the build sandbox.
7. **Platform coverage.** Developed and tested on Linux with Python 3.13 only. Windows and Python 3.11/3.12 were not
   exercised, although the code uses only portable stdlib/pathlib APIs and declares `requires-python >= 3.11`.
8. **Latency** values are single-machine wall-clock of Python code; they say nothing about real robot or model latency.
9. **Statistical power.** With 124 held-out cases, only moderate-to-large effects are detectable in paired tests;
   non-significance is not evidence of equivalence; exploratory comparisons carry no multiplicity control.
10. **Unit conversion, negation, contradiction, indirect references** are included as hard categories; the reference
    agent deliberately does not handle them, which makes its category scores uneven by design.
