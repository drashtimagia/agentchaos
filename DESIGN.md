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

## Open questions (need sign-off)

- **Overall resilience score weights.** Not implemented. The CLI reports per
  fault class only: success with 95% CI, degradation vs. clean, safety
  violation rate, mean calls, mean faults. A weighting proposal will come with
  Phase 2, once safety violations and surrender rates exist for more than one
  scenario.
- **Trace format.** The `Run` model is versioned and complete, but nothing is
  written to disk yet. The JSONL layout (one record per call, fault event and
  outcome) lands with the recorder in Phase 2.
