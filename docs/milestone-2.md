# Milestone 2 — stateful autonomous agent engine

## Implemented

- Explicit task state machine, UUID/timestamp, current step, structured history, and honest reports.
- Bounded plans and a strict JSON structured-plan parser for future model output.
- Separate planner, executor, verifier, recovery, permissions, and runtime modules.
- Registered-only typed tools with a supported JSON-schema subset and unknown-argument rejection.
- Central read/write/execution/sensitive policy; approved-root containment is resolved before writes.
- Per-tool timeouts, task deadline, cooperative active-operation cancellation, bounded retries with
  exponential backoff, maximum steps, repeated-call detection, and two-step cycle detection.
- Verification of actual tool results and postconditions.
- Deterministic tools for fixture reads, document search, report writes, recoverable/permanent
  failures, timeout, and approval-required destructive action.
- Offline CLI demo that reads a fixture, recovers from a deliberate failure, and writes a verified
  report without contacting Ollama.

## Run the example on Windows

```powershell
.\.venv\Scripts\jean-grey.exe agent --prompt "This text is written only after verified steps."
Get-Content "$HOME\.jean-grey\demo\report.txt"
```

The demo's plan is intentionally deterministic. `parse_plan` validates constrained JSON plans, but
arbitrary natural-language planning through Ollama is not enabled as autonomous execution until
model capability tests are added. This avoids treating unreliable model prose as authorized calls.

## Security and cancellation notes

No generated Python or shell is executed. Unknown tools fail before invocation. Sensitive tools
pause in `WAITING_FOR_APPROVAL`; tests explicitly supply approval on resume. Execution-class tools
are disabled by default. Timed-out and cancelled mock operations receive a cooperative cancellation
event. Python cannot safely kill a non-cooperative thread, so a third-party tool that ignores that
event may finish in the background; MCP subprocess termination will be addressed with MCP lifecycle
management in Milestone 3.

## Actual validation

The full dependency-free unit suite runs without internet, Ollama, or weights. It covers all 15
requested scenarios plus existing Milestone 1 behavior and public schema/CLI interfaces. The exact
count and timing are recorded in the milestone completion report, not hard-coded as a benchmark.

## Limitations

State is in memory; durable SQLite checkpoints are reserved for Milestone 4. Approval is an API
resume operation, not yet a GUI prompt. Mock write tools are for controlled demonstration only.
MCP, Playwright, Chrome, unrestricted terminal access, browser automation, and model training are
not implemented or claimed. No target Windows hardware benchmark has been run.
