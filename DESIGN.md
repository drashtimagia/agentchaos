# Design log

Significant decisions, the alternatives considered, and why. Newest last.

## 1. Fault decisions use a per-call RNG, not one stream per run

Each (call index, rule index) pair gets its own `random.Random` seeded from
`"{seed}:{call_index}:{rule_index}"`.

Alternative: a single `random.Random(seed)` per run, consumed in call order.
That is deterministic only if the agent makes exactly the same calls in the same
order. LLM agents don't. With a shared stream, one extra call early in a run
shifts every later decision, so "same seed, same faults" stops meaning anything
useful. With per-call derivation, call 7 under seed 42 always gets the same
decision regardless of what happened before it. String seeds are hashed with
SHA-512 by `random.Random`, so the result is stable across processes and
platforms.

This slightly reinterprets the spec's "a `random.Random` seeded per run" in
`ctx.rng`: it is still derived only from the run seed, just at finer grain.

## 2. Call indices are reserved before the call runs

`Injector.call` takes the next index before awaiting the tool, so parallel tool
calls within one run get distinct, stable indices. Indices are global per run,
not per tool, which keeps `call_indices` in policies simple to reason about.

## 3. Timeout has a `phase` parameter

`phase: before` (default) fails without reaching the upstream. `phase: after`
lets the upstream execute and then reports a timeout. The second case is the one
that causes duplicate writes in production, and it is what the ticketing oracle's
duplicate check exists to catch. The default is `before` because it is the
least surprising reading of "timeout"; profiles that target write safety should
set `after` explicitly.

## 4. One discovery path for faults and scenarios

Built-in faults and scenarios are declared as entry points in this package's own
`pyproject.toml`, under the same groups third-party packages use
(`agentchaos.faults`, `agentchaos.scenarios`). `register_fault` exists for
runtime registration in tests and notebooks, layered on top. A hard-coded
built-in dict was rejected because it would let the plugin path rot untested.

## 5. Faults are dataclasses; params are their fields

`FaultRule.params` is passed straight to the fault's constructor, so a fault's
dataclass fields are its public parameter schema. Unknown or misspelled params
fail at policy load time, not mid-run.

## 6. Tools are framework-neutral `ToolSpec`s, wrapped once per run

Scenarios expose `ToolSpec(name, description, JSON schema, fn)`. `run_trial`
wraps each `fn` with the run's injector before handing tools to the agent
runner, so runners never see policies or faults, only tools that sometimes raise.
This keeps runners thin. In Phase 2 the MCP proxy becomes the primary path, and
`ToolSpec` maps directly onto MCP tool definitions.

## 7. `@chaos.tool` uses a `ContextVar`

The active injector is stored in a `ContextVar`, so concurrent runs in separate
asyncio tasks each see their own injector without passing it through call
signatures. Outside `chaos.activate(...)` a decorated tool behaves exactly like
the original. Decorated tools are always async because faults are async
middleware; wrapping sync tools in a sync shim would need a nested event loop.

## 8. The scripted agent is a fixed yardstick

Tests and `--agent scripted` use an agent that follows the scenario's reference
plan, retries `ToolFault`s up to twice, does not retry real tool errors, and
writes an explicit surrender message when it gives up. It does not check state
before retrying a write, so it produces duplicates under `timeout(phase=after)`.
That is intentional: it shows the oracle catching the failure mode.

## 9. Claude Agent SDK runner isolation

The runner disables all built-in Claude Code tools (`tools=[]`), loads no
user or project settings (`setting_sources=[]`), and exposes only scenario tools
through an in-process SDK MCP server. Without this, a developer's local
`CLAUDE.md` or extra tools would change benchmark results. Model comes from
`AGENTCHAOS_MODEL` (default `claude-opus-5-5`).

## 10. Confidence intervals use the Wilson score interval

Trial counts are small (10 in smoke runs) and success rates are often 0% or
100%, where the normal approximation gives zero-width or out-of-range intervals.
Wilson behaves well in both cases.

## 11. Trace format v1 (approved)

JSONL, one file per CLI invocation, written and flushed record by record.
Concurrent runs interleave and are keyed by `run_id`. Four record types, all
carrying `schema_version: 1`: `run_start` (scenario, fault class, seed, agent,
the fully resolved policy), `tool_call`, `fault`, and `outcome`. Schema:
`schemas/trace.v1.schema.json`, checked against the models by a test.

One file per run was the alternative. It makes single-run inspection easier
but produces thousands of tiny files for a benchmark and makes appending from
concurrent runs no simpler, since each line is already self-describing.

## 12. Fault events record the rule that fired; replay pins rules to calls

`FaultEvent.rule` (approved) is the index of the policy rule. Replay rebuilds
the policy with each rule's probability set to 1 and `call_indices` set to the
calls it fired on in the recording. Seeds are kept too, so each fault gets the
same per-call RNG and its details (truncation point, renamed field) match. For
the scripted agent this reproduces the run exactly. For an LLM agent it
reproduces the fault schedule even if the agent's calls drift; if the agent
makes fewer calls, later faults simply never trigger, and `agentchaos replay`
reports the difference and exits non-zero.

## 13. Result-rewriting faults go through `core/payload.py`

Faults see either plain Python values (in-process runs) or MCP
`CallToolResult`s (behind the proxy). `get_data`, `with_data` and `with_text`
hide that difference. Nothing is decoded or re-encoded unless a fault actually
rewrites the result, which is what keeps the proxy exactly transparent when no
fault fires. In-process, a truncated body becomes `RawText`, a `str` subclass
that runners pass to the model verbatim rather than JSON-encoding it into a
valid string.

## 14. Fault semantics worth knowing

- `MalformedJSON` truncates only objects and arrays. Any proper prefix of
  those is invalid JSON; a prefix of a scalar (`12` -> `1`) can still parse.
- `StaleData` returns the *oldest* earlier response to the same tool and
  arguments in the same run, and does not call the upstream. With no earlier
  response it does nothing. It reads the injector's per-run history rather
  than keeping its own state.
- `SchemaDrift` renames to `<field>_v2` by default, or drops the field. It
  touches top-level objects and objects in a top-level list only.
- MCP tool errors from the upstream (`isError`) are recorded as failed calls
  and are never served back by `StaleData`.

## 15. Profiles are includes, resolved at load time

`profile: flaky-network` in a policy prepends that profile's rules and clears
the field, so a loaded policy is always fully resolved and reloading it never
applies the profile twice. The YAMLs live in `agentchaos/profiles/` rather than
a top-level `profiles/` so they ship in the wheel and load via
`importlib.resources`.

## 16. The proxy is one run per process

A proxy has one injector: one seed, one call counter, one trace. For parallel
runs, start several proxies. Per-session injectors inside one HTTP proxy were
considered, but MCP's newer per-request protocol era does not guarantee a
stable session per client, and per-process isolation is simpler to reason
about. Upstream connections use the SDK's unified `mcp.Client`, which accepts a
URL (streamable HTTP) or stdio parameters.

## 17. The final-message judge runs only on failed runs

State oracles decide success. The judge classifies only what the final message
*claims*: `claims_success`, `reports_failure` or `unclear` (stored as
`Outcome.claim`, approved). It runs only when the oracle failed, because a
claim matters only then and it saves cost:

- `hallucinated_success` (a safety violation): oracle failed, claims success.
- graceful surrender: oracle failed, clearly reports failure.

`KeywordJudge` is a deterministic regex heuristic for tests and the scripted
agent. `ClaudeJudge` uses structured output (`messages.parse`) and server-side
refusal fallbacks; it defaults to `claude-opus-5-5` (`AGENTCHAOS_JUDGE_MODEL`).
`--judge auto` picks keyword for scripted runs and Claude otherwise.

## 18. Scenario design notes

- Bank transfer: the server honours idempotency keys, so an agent that uses
  one survives `timeout(phase=after)`; one that doesn't double-transfers.
- Inventory: the server accepts orders that oversell (as many legacy systems
  do), so trusting a stale stock reading shows up as negative stock.
- File edit: there is no transaction API. "All or none" is the agent's job;
  a mix of versions is `partial_write`, anything else is `corrupted_write`.
- Search/summarize: citing a document id that does not exist is
  `fabricated_reference`.

## Open questions (need sign-off)

- **Overall resilience score weights.** Proposed at the Phase 2 checkpoint;
  not implemented until approved.
