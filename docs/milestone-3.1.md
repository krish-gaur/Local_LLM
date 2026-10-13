# Milestone 3.1 — wake word, Hindi voice, and hands-free browser agent

## What is implemented

- A separate `WakeWordProvider` contract and optional local `OpenWakeWordProvider`.
- An explicit custom ONNX wake model path, score threshold, cooldown, bounded audio queue, mute,
  cancellation, and cleanup. Background audio is not written to disk or sent over a network.
- An honest unavailable provider and clearly labeled push-to-talk fallback.
- A tested conversation state machine: `IDLE`, `WAKE_DETECTED`, `LISTENING`, `TRANSCRIBING`,
  `PLANNING`, `EXECUTING`, `SPEAKING`, `INTERRUPTED`, `ERROR`, and `STOPPED`.
- Local end-of-utterance capture based on speech followed by bounded silence.
- Faster-whisper detailed transcripts with detected language, probability, and uncertainty.
- Hindi, English, and Hinglish heuristics plus explicit language-switch, cancel, and stop commands.
- Duplicate-command suppression and wake cooldown.
- A deterministic Hindi/Hinglish browser-search intent routed through the existing MCP tools,
  runtime, verifier, permission policy, and cancellation callback.
- Language-aware Piper routing. Hindi audio is allowed only when a separate voice model's Piper
  metadata verifies a language code beginning with `hi`; otherwise Hindi remains visible text.

## Wake engine evaluation

`openwakeword==0.6.0` was selected as an optional engine because it is local, can run lightweight
ONNX models, and does not require a cloud key. It does not provide a guaranteed bundled “Hello Jean
Grey” model. A custom compatible model must be acquired or trained separately with explicit user
approval. Porcupine was not selected because normal use requires a vendor access key. Running full
faster-whisper continuously was rejected as a wake detector because wake detection must remain
separate and lightweight.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice,wake,mcp]"
$env:JEAN_GREY_WAKE_WORD_MODEL_PATH = "$HOME\.jean-grey\models\wake\hello-jean-grey.onnx"
$env:JEAN_GREY_HINDI_PIPER_VOICE_PATH = "$HOME\.jean-grey\models\piper\hi_voice.onnx"
jean-grey voice --check
jean-grey voice --hands-free --wake-word --speak-responses --language auto
```

No model is downloaded by Jean Grey. `voice --check` reports wake and Hindi-TTS readiness without
opening the microphone. Start muted with `--mute`; Ctrl+C cancels the active runtime and exits.

## Speech and language behavior

Faster-whisper receives `language=None` by default, allowing its multilingual model to detect the
dominant language while retaining code-switched text. Detection is not a guarantee of perfect
Hinglish recognition. A language probability below 0.65 triggers transcript review. Explicit
language commands override automatic reply selection for the conversation.

The wake acknowledgement is “Haan, bolo. Main sun rahi hoon. What can I do for you?” unless English
is explicitly preferred. Replies remain concise. Detailed browser evidence stays visible rather
than being read aloud as raw snapshots, stack traces, or long URLs.

## Browser limitations

A command such as “Chrome par BYD ki sabse sasti car search karo” is parsed into a bounded query,
opens the configured HTTPS search page through Playwright MCP, and verifies the resulting browser
snapshot. Jean Grey does not claim a cheapest model or price from that search page alone. The
current deterministic flow does not reliably extract result links, inspect three independent source
pages, normalize market/currency/date, and synthesize a price comparison without a validated model
planner. The assistant says so rather than inventing a result.

Clicks, forms, purchases, messages, deletes, and other consequential actions retain Milestone 3's
approval requirements. Web text remains untrusted data and cannot change language preferences,
permissions, plans, or policy.

The state machine and cancellation callback support programmatic interruption, and Ctrl+C cancels
an active CLI browser runtime. The current single-microphone CLI does not listen concurrently while
MCP execution or speech playback is running, so a spoken “Ruko” barge-in during those exact phases
is not yet verified or claimed; cancel phrases work when captured as an utterance.

## Automated and hardware testing

The automated tests use fake wake audio, speech transcripts, TTS providers, agent callbacks, MCP
backends, and browser pages. They cover wake activation/unavailability, Hindi/Hinglish detection,
language switching, low-confidence transcripts, Hindi voice metadata failure, interruption,
cancellation callbacks, duplicate suppression, microphone failure, return-to-listening, browser
permissions, prompt injection, and text/push-to-talk fallback.

The final sandbox suite ran **85 tests: 83 passed and 2 explicit real-integration tests were
skipped** (Playwright MCP and wake/microphone speech). Compilation and `git diff --check` passed.
The skipped tests are not claimed as successful.

The sandbox has no physical microphone/speaker, custom wake model, faster-whisper model, verified
Hindi Piper voice, Playwright MCP server, or Chrome session. Therefore the complete spoken
wake → Hindi transcription → real browser → Hindi speech flow is **not verified and not claimed**.
An operator can run the opt-in hardware portion only after configuring all local files:

```powershell
$env:JEAN_GREY_REAL_VOICE_TEST = "1"
python -m unittest tests.integration.test_real_hands_free -v
```

The operator must say the configured wake phrase and a test utterance. Browser verification remains
the separate opt-in MCP integration test. Use controlled pages before public websites.

## Resource notes

On the 8 GB target, wake detection stays lightweight and bounded. Faster-whisper and Piper load
lazily. Avoid loading a large LLM and larger speech model concurrently. No cloud provider is
implemented; adding one would require a separate explicit opt-in and disclosure before any audio or
transcript leaves the computer.
