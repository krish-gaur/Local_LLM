# Jean Grey

Jean Grey is a local-first, resource-aware AI agent for Windows. It combines local Ollama chat, a
bounded permission-controlled agent runtime, and an optional offline voice pipeline. Models are
never downloaded automatically, keyboard input always remains available, and voice commands enter
the same verified agent runtime as typed commands.

The Python import package remains `localpilot` to preserve compatibility and Git history. The
product, distribution, and primary executable are now `Jean Grey` / `jean-grey`; the old
`localpilot` executable is retained as a compatibility alias.

## Install on Windows

```powershell
.\scripts\setup.ps1
# Optional microphone, faster-whisper, and playback packages:
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
```

Ollama, Piper, LLM weights, transcription models, and voice models are not installed or downloaded
by setup. Obtain each from its official source only after reviewing its size/license and explicitly
approving the download. Keep weights under `%USERPROFILE%\.jean-grey\models` or another directory
outside this repository.

## Text usage

```powershell
# Local chat (requires running Ollama and an already-installed model)
jean-grey chat
jean-grey chat --prompt "Explain offline-first operation."
jean-grey chat --check

# Verified deterministic agent demonstration (does not require a model)
jean-grey agent --prompt "Prepare a verified local report"
Get-Content "$HOME\.jean-grey\demo\report.txt"
```

Legacy invocations such as `localpilot --check` and `LOCALPILOT_MODEL` still work. New
`JEAN_GREY_*` variables take precedence. If `~/.localpilot` already exists and `~/.jean-grey` does
not, Jean Grey continues using the old directory without moving or deleting anything. Explicit
`JEAN_GREY_DATA_DIR` or legacy `LOCALPILOT_DATA_DIR` overrides that fallback.

## Voice usage

Voice is optional and local-first:

```powershell
jean-grey voice --check
jean-grey voice --push-to-talk
jean-grey voice --push-to-talk --speak-responses
jean-grey voice --hands-free --speak-responses   # explicit activation only
# Keyboard fallback routed through the same agent runtime:
jean-grey voice --prompt "Prepare a report"
```

Push-to-talk is the default. Jean Grey shows the transcript and asks for confirmation or an edit
before execution. `/cancel` rejects it. Hands-free mode is never enabled by default and has an easy
`/stop` control. Sensitive plans remain in `WAITING_FOR_APPROVAL`; voice cannot override permissions.
Text status and results are retained even if synthesis or playback fails.

### Offline speech setup

- **STT:** `faster-whisper` loads only a local directory configured by
  `JEAN_GREY_STT_MODEL_PATH`. The recommended starting point on an 8 GB system is a small CPU/int8
  model, but performance has not been measured on the target PC.
- **TTS:** install the Piper executable separately and set `JEAN_GREY_PIPER_EXECUTABLE` and
  `JEAN_GREY_PIPER_VOICE_PATH` to local files. Speaking rate is `JEAN_GREY_VOICE_RATE` (0.5–2.0).
- **Audio:** the optional `sounddevice`/`soundfile` packages need working Windows input/output
  devices and drivers.

`voice --check` reports libraries, detectable microphone/speaker devices, local STT/TTS model
availability, RAM preflight, and offline status. It never records audio or downloads a model.

Troubleshooting:

1. If dependencies are missing, rerun the optional install command; typed modes remain functional.
2. If no device is detected, check Windows Privacy & Security → Microphone and the default devices.
3. If a model is missing, verify the configured local path. Do not point it at a remote model ID.
4. Use Ctrl+C to cancel recording/session and omit `--speak-responses` if output is unavailable.

## Security and resource behavior

Only registered, schema-validated tools execute. Writes are restricted to approved roots,
execution tools are disabled by default, unknown tools fail closed, and sensitive tools require
explicit approval. The runtime enforces retries, timeouts, cancellation, step limits, loop
detection, and actual-result verification. No generated Python or shell is executed.

The i3/8 GB target should avoid keeping an LLM, STT model, and TTS model loaded simultaneously.
Voice providers load lazily and release references on session close. Real-time transcription and
specific Windows-device compatibility are **unverified**, not claimed.

## Wake word, Hindi/Hinglish, and hands-free mode

Hands-free mode is explicit and local. It is **not** enabled by default:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[wake]"
jean-grey voice --check
jean-grey voice --hands-free --wake-word --speak-responses --language auto
```

Jean Grey uses `openwakeword` only when a user-supplied custom local model configured by
`JEAN_GREY_WAKE_WORD_MODEL_PATH` is present. A generic bundled model is not claimed to recognize
“Hello Jean Grey.” If the engine/model/microphone is unavailable, the CLI explicitly falls back to
push-to-talk. Background frames are processed in a bounded in-memory queue and are neither retained
nor sent to a cloud service.

`faster-whisper` runs with automatic dominant-language detection and preserves Hindi/English
code-switching in the transcript. Low-confidence transcripts require review. Captured commands can
switch language (“Ab English mein baat karo”, “Hindi mein samjhao”), cancel, or stop listening. The
CLI does not yet listen concurrently during MCP execution/playback; Ctrl+C remains the immediate
active-task interruption. Local Hindi
speech requires a separately configured Piper Hindi model whose `.onnx.json` metadata verifies a
`hi...` language code; otherwise Hindi remains text-only.

The deterministic Hinglish intent parser routes commands such as “Chrome par Python course search
karo” through the same MCP registry, `AgentRuntime`, permissions, verifier, cancellation, and
untrusted-web-content boundary as typed browser tasks. It opens and verifies a configured search
page. It does **not** yet autonomously follow/rank arbitrary search results or claim a lowest price
without inspecting reliable source pages.

Real wake detection, microphone endpointing, Hindi transcription, Hindi Piper output, and Chrome
have not been tested together in this development sandbox. Full hands-free operation is therefore
not claimed. See [Milestone 3.1](docs/milestone-3.1.md).

## MCP and controlled browser research

MCP support uses the optional official Python SDK and explicit server/tool allowlists. Install only
after review:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
npm install --global @playwright/mcp@0.0.83
Copy-Item .\mcp.example.json "$HOME\.jean-grey\mcp.json"
# Edit the dedicated profile path and explicitly enable the server.
jean-grey mcp --check
jean-grey browser --check
```

Checks connect and discover schemas but never call tools or download packages. The example uses
`npx --offline`, Chrome, and a dedicated Jean Grey browser profile. It does not expose personal
cookies or saved passwords. Browser clicks/form fills are sensitive by default and require the
existing approval path.

A source-grounded mock-tested research workflow accepts explicit URLs:

```powershell
jean-grey browser --topic "Compare controlled sources" `
  --source "https://example.org/one" --source "https://example.org/two" `
  --report "$HOME\.jean-grey\reports\comparison.md"
```

Browser evidence is untrusted data, never policy or instructions. Reports are path-contained,
size-limited, reopened, and verified. Local AI processing can remain offline, but browsing internet
websites inherently needs network access. See [Milestone 3](docs/milestone-3.md) for setup, exact
mapped tools, security boundaries, and truthful mock-versus-real test status.

## Configuration and development

See [`.env.example`](.env.example). Defaults are offline and Ollama URLs are loopback-only.

```powershell
python -m unittest discover -v
python -m compileall -q localpilot tests
python -m localpilot.app.main voice --check
```

Documentation: [Milestone 1](docs/milestone-1.md), [Milestone 2](docs/milestone-2.md), and
[Milestone 2.1](docs/milestone-2.1.md), [Milestone 3](docs/milestone-3.md), and
[Milestone 3.1](docs/milestone-3.1.md).

Real Playwright/Chrome integration remains environment-dependent and unverified in the sandbox.
Persistent SQLite checkpoints and a desktop GUI are not implemented yet.
