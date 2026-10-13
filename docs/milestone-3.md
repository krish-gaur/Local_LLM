# Milestone 3 — MCP and Playwright browser automation

## Architecture

Jean Grey uses the official Python MCP SDK (`mcp==1.30.0`, optional extra) through a lazy stdio
transport. `McpManager` owns server lifecycle; `McpClient` initializes sessions, discovers schemas,
and registers only explicitly allowlisted tools in the existing `ToolRegistry`. Discovered names,
descriptions, results, and web content are untrusted. Unsupported schemas fail closed.

Microsoft's `@playwright/mcp` was reviewed from its upstream README on 2026-10-13. The documented
stdio command is `npx @playwright/mcp@latest`; for reproducibility and to prevent an implicit
diagnostic-time download, the example pins the version observed during implementation (`0.0.83`)
and uses npm's offline mode. Upstream discovered names mapped by Jean Grey are:

- `browser_navigate` → `browser.navigate`
- `browser_snapshot` → `browser.get_page_content` and `browser.get_accessibility_tree`
- `browser_click` → `browser.click`
- `browser_fill_form` → `browser.fill_form`
- `browser_tabs` → `browser.list_tabs`
- `browser_take_screenshot` → `browser.capture_screenshot`

An alias exists only when that exact remote tool is both discovered and allowlisted. Dynamic tools
also remain available as `mcp.<server>.<remote-tool>`. No arbitrary shell tool is created.

## Windows setup (explicit installation)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
# Review package/version first; this is an explicit network install:
npm install --global @playwright/mcp@0.0.83
Copy-Item .\mcp.example.json "$HOME\.jean-grey\mcp.json"
# Edit YOUR_NAME, set enabled=true, and retain only tools you approve.
jean-grey mcp --check
jean-grey browser --check
```

The example uses Chrome and a dedicated profile at `~/.jean-grey/browser-profile`. It never attaches
to a personal Chrome profile. Attaching to one can expose authenticated sessions and must be a
manual, informed configuration change. Cookies, credentials, and browser tokens are not logged.
Complete required authentication manually in the dedicated browser. Jean Grey does not bypass
CAPTCHAs, access controls, or browser security protections.

## Configuration and secrets

See `mcp.example.json`. Each server must be explicitly enabled and every tool must have a permission
classification. Unknown servers are absent from the allowlist; unknown/discovered-only tools are
not registered. `env_from` maps a child variable name to the name of a host environment variable:

```json
"env_from": {"GITHUB_TOKEN": "JEAN_GREY_GITHUB_TOKEN"}
```

The secret value is never stored in JSON. Diagnostics redact secret-like keys and known values.
Protect the config file using normal Windows user ACLs. Diagnostic commands connect and discover
but never invoke tools or download packages.

## Research command

```powershell
jean-grey browser --topic "Compare these controlled sources" `
  --source "https://example.org/source-one" `
  --source "https://example.org/source-two" `
  --source "https://example.org/source-three" `
  --report "$HOME\.jean-grey\reports\comparison.md"
```

The bounded plan navigates to each supplied HTTP(S) URL, captures Playwright accessibility/page
snapshots, records each URL with observed evidence, writes Markdown or CSV inside the approved
report root, reopens it, and verifies exact contents. It does not invent citations or fill facts not
present in results. The current deterministic workflow accepts explicit source URLs; autonomous web
search/ranking still requires a capable validated model planner and is not claimed.

Defaults cap research at 10 pages, 30 planned browser actions, 100,000 characters per page result,
and a 1 MB report. The existing runtime's 12-step default is stricter and takes precedence (normally
up to five sources plus the report step). Existing retries, task deadline, cancellation, and loop
detection remain active.

## Permissions and trust boundaries

Navigation/snapshots may be configured read-only. Clicks and form filling are sensitive in the
example and stop in `WAITING_FOR_APPROVAL`. Report creation is write-class and path-contained;
overwrite uses a separate sensitive tool with atomic replacement. Canonical and symlink escape,
traversal, wrong extension, output size, and reopened-content checks fail closed.

Page text is labeled `untrusted_web_content`. Suspicious instruction detection is advisory; the real
boundary is structural: page output is only data in result references and cannot modify plans,
registries, permissions, environment, or approvals. No instruction in a page can authorize a tool.
Consequential forms, purchases, messages, deletes, and authentication are not automated by the
research workflow.

## Local processing versus network access

Planning, policy, MCP client logic, and report generation are local. Browser research is not fully
offline: Chrome and target websites require network access unless browsing local pages. Offline LLM
mode does not imply offline websites.

## Tests and limitations

Normal tests use deterministic fake MCP backends and browser results. They cover discovery,
allowlists, schemas, invocation, failures, reconnect, timeout/cancellation, cleanup, redaction,
navigation, extraction, recovery, approval, loop prevention, injection resistance, grounded
multi-page reports, Markdown/CSV, traversal/symlinks, overwrite approval, and verification.

The pre-change baseline was **45 tests passing**. The final sandbox suite ran **72 tests: 71 passed
and 1 opt-in real Playwright integration test was skipped**; Python compilation and
`git diff --check` also passed. The skipped test is not claimed as successful.

No real MCP SDK, Playwright MCP process, Chrome instance, or network website was started in the
sandbox. The server package and browsers were not downloaded. Real Windows/Chrome verification is
therefore **unverified**, not passed. Optional real integration should be run only after the explicit
setup above, first against non-sensitive controlled pages:

```powershell
$env:JEAN_GREY_REAL_MCP_TEST = "1"
$env:JEAN_GREY_MCP_CONFIG = "$HOME\.jean-grey\mcp.json"
$env:JEAN_GREY_REAL_TEST_URL = "https://your-controlled-test-site.example/"
python -m unittest tests.integration.test_real_playwright_mcp -v
```

This milestone is not a production-readiness claim.
