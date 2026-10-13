# Milestone 2.1 — Jean Grey rename and voice communication

## Rename and compatibility

The product/distribution/primary command are now **Jean Grey**, `jean-grey`, and `jean-grey`.
The internal `localpilot` import package and a `localpilot` console alias remain intentionally for
backward compatibility. `JEAN_GREY_*` settings take precedence over legacy `LOCALPILOT_*` settings.
New installs default to `~/.jean-grey`; when only `~/.localpilot` exists, it remains in use in place
without automatic moves or deletion.

## Voice architecture

Provider contracts separate microphone capture, STT, TTS, and playback. The concrete providers are:

- lazy `sounddevice` microphone capture;
- lazy CPU/int8 `faster-whisper` with `local_files_only=True` and an explicit local directory;
- local Piper executable/model invocation;
- interruptible `sounddevice`/`soundfile` WAV playback.

`VoiceSession` handles transcript review, cancellation, text fallback, asynchronous synthesis and
playback, and cleanup. Its agent callback is the existing Milestone 2 runtime. A spoken request
cannot authorize a tool or bypass verification. Push-to-talk is default; repeated hands-free turns
require explicit `--hands-free` activation.

## Downloads and resource behavior

No voice dependency, binary, transcription model, or voice model is downloaded automatically.
Providers load lazily and release model references at close. Health checks are passive. The 2 GiB
available-RAM voice check is a warning-level preflight, not proof of real-time performance. On the
8 GB target, choose a small/int8 STT model and avoid retaining all models concurrently.

## Tested versus unverified

Automated tests use deterministic fake providers and require no microphone, speaker, internet,
Ollama, or model weight. They cover dependency/device/model failures, recognition and transcript
errors, review, TTS failure, playback interruption, cancellation, runtime/permission integration,
cleanup, fallback text, renamed metadata, legacy settings, and offline health reporting.

The final sandbox run completed **45 automated tests successfully**. Compilation and whitespace
checks also passed. The passive CLI health check correctly returned unavailable status (exit 3).

The sandbox has no configured audio hardware or speech models. Therefore real microphone capture,
real faster-whisper latency/accuracy, Piper output quality, real speaker playback, target Windows
driver behavior, and real-time performance are **unverified**. They are not reported as successful.
MCP, browser control, GUI, and always-on background recording are not part of this milestone.
