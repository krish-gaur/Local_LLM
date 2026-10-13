# Jean Grey Windows deployment and integration verification

This procedure is intentionally check-first. It never downloads a model, voice, browser, or MCP
package unless the operator supplies an install switch or runs the displayed command.

## Supported baseline

- Windows 10/11 x64
- Python 3.11 or newer (3.11 is the tested target)
- A project-local `.venv`
- Node.js 18 or newer for Microsoft Playwright MCP
- Microsoft Edge for the supplied isolated Windows browser configuration

Run all commands from the repository root in PowerShell. Do not use an elevated shell.

## 1. Inspect only — install nothing

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The script checks Python, `.venv`, editable installation, the Python MCP SDK, Node/npm/npx, the
project-local `@playwright/mcp` package, Edge, and MCP JSON. It prints the next exact command for
each missing item. It does not print configuration values or environment-derived secrets.

## 2. Install into project-local locations

```powershell
# Core plus development/test tools in .venv
.\scripts\setup.ps1 -InstallCore -InstallDev

# Official Python MCP SDK in .venv and Microsoft Playwright MCP in this repo's node_modules
.\scripts\setup.ps1 -InstallMcp
```

Equivalent explicit commands are:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,mcp]"
npm.cmd install --no-save --package-lock=false @playwright/mcp@0.0.83
```

No global npm package is used. `node_modules` is ignored by Git. The selected MCP package requires
Node.js 18 or newer. If Node is absent:

```powershell
winget install OpenJS.NodeJS.LTS
```

The example targets installed Microsoft Edge. If it is absent:

```powershell
winget install Microsoft.Edge
```

This does not install speech models, wake models, Piper, or voices.

## 3. Create a safe disabled configuration

```powershell
New-Item -ItemType Directory -Force "$HOME\.jean-grey" | Out-Null
Copy-Item .\mcp.windows.example.json "$HOME\.jean-grey\mcp.json"
$env:JEAN_GREY_MCP_CONFIG = "$HOME\.jean-grey\mcp.json"
```

The example uses official `@playwright/mcp@0.0.83` over stdio via `npx.cmd --offline`. It selects
`msedge` and `--isolated`, so browser state is temporary and the server does not attach to a personal
Chrome/Edge session or inherit personal cookies. The server is **disabled by default**. Review the
tool allowlist, then change only `"enabled": false` to `true`.

For a persistent dedicated profile, replace `--isolated` with:

```json
"--user-data-dir", ".jean-grey-browser-profile"
```

Use a dedicated directory while running from the repository root. Never point this at an existing
Chrome or Edge profile. No machine-specific absolute path is required.

## 4. Diagnostics

```powershell
.\.venv\Scripts\jean-grey.exe --version
.\.venv\Scripts\jean-grey.exe mcp --check --config "$HOME\.jean-grey\mcp.json"
.\.venv\Scripts\jean-grey.exe browser --check --config "$HOME\.jean-grey\mcp.json"
.\.venv\Scripts\jean-grey.exe voice --check
# Or run setup checks and MCP connection checks together:
.\scripts\setup.ps1 -Connect
```

Exit code `0` means the requested configured subsystem passed its diagnostic gate. Exit code `3`
means unavailable or incomplete. MCP/browser JSON distinguishes missing/invalid configuration,
disabled server, missing Python SDK, missing command, unsupported Node, missing browser, connection
failure, and connected/discovered tools. `browser_navigation_tested` remains false because a check
does not invoke browser tools. Only the real smoke test establishes navigation readiness.

Voice diagnostics distinguish audio input/output, STT model, wake provider/model, default TTS,
verified Hindi TTS, and resource status. They do not request microphone capture or download assets.
Use `voice --check --wake-word` to make wake readiness mandatory, and
`voice --check --language hi --speak-responses` to make verified Hindi synthesis mandatory.

## 5. Real controlled MCP/browser smoke test

The test starts a loopback HTTP page with a unique marker, initializes the actual configured MCP
server, verifies real tool discovery, navigates, extracts the accessibility snapshot, checks the
observed tab URL, and closes browser/server and HTTP server resources.

```powershell
$env:JEAN_GREY_MCP_CONFIG = "$HOME\.jean-grey\mcp.json"
$env:JEAN_GREY_REAL_MCP_TEST = "1"
.\.venv\Scripts\python.exe -m unittest tests.integration.test_real_playwright_mcp.RealPlaywrightMcpTests.test_controlled_local_page_navigation_snapshot_url_and_close -v
```

Optional external-web smoke test (network-dependent and separate):

```powershell
$env:JEAN_GREY_REAL_WEB_TEST = "1"
$env:JEAN_GREY_REAL_TEST_URL = "https://example.com/"
.\.venv\Scripts\python.exe -m unittest tests.integration.test_real_playwright_mcp -v
```

A skipped test is not a successful real integration.

## 6. Real multi-page research

Search providers may rate-limit automation; failure must remain visible rather than being replaced
with mock results.

```powershell
$env:JEAN_GREY_REAL_RESEARCH_TEST = "1"
$env:JEAN_GREY_REAL_RESEARCH_QUERY = Read-Host "Research topic"
.\.venv\Scripts\python.exe -m unittest tests.integration.test_real_verified_research -v

.\.venv\Scripts\jean-grey.exe browser `
  --config "$HOME\.jean-grey\mcp.json" `
  --topic $env:JEAN_GREY_REAL_RESEARCH_QUERY `
  --market "India" --source-count 3 `
  --report "$HOME\.jean-grey\reports\real-research.md"
```

The workflow records observed result links, opens multiple pages, retains evidence and disagreements,
and reopens the requested report. Vehicle-price conclusions require compatible price type, variant
context, market, freshness, official evidence, and sufficient sources. There is no hardcoded BYD
model or expected price.

## 7. Voice component and manual acceptance procedure

Install voice libraries only if wanted:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\jean-grey.exe voice --check
```

Wake-word models, local Whisper models, Piper executable/voices, and verified Hindi voice metadata
must be configured separately; Jean Grey does not download them. Follow `docs/milestone-3.1.md`.

After every component independently passes:

1. Start `jean-grey voice --hands-free --wake-word --speak-responses --language auto`.
2. Say **“Hello Jean Grey.”** and verify wake activation.
3. Say **“Chrome par BYD ki sabse sasti car search karo.”**
4. Read and confirm the actual printed transcript; correct or cancel an uncertain transcript.
5. Confirm actual browser navigation and three extracted source URLs.
6. Confirm the answer cites observed evidence and reports disagreements/insufficiency honestly.
7. Confirm Hindi audio only if `voice --check` reports a verified Hindi voice.
8. Test Ctrl+C and cancellation while capture/runtime cancellation is available.
9. Force a page failure and confirm no model/price/success is invented.

Jean Grey does **not** concurrently listen throughout synchronous MCP execution or speaker playback.
Do not use spoken interruption as an acceptance criterion during those periods. Ctrl+C and
programmatic cancellation remain available.

## Current sandbox result

At implementation time, the sandbox had Python 3.11.2 and Node/npm/npx, but no Python MCP SDK, no
project-local Playwright MCP package, no Chrome/Chromium/Edge executable, no user MCP configuration,
and the checked-in examples were disabled. Consequently, real MCP initialization, real browser
navigation, real-web research, microphone, wake word, Hindi STT/TTS, and playback were not executed.
