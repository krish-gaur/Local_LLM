# Milestone 3.2 — verified browser research and end-to-end test gates

## Implemented research flow

A verified search task now uses one bounded `AgentRuntime` plan:

1. Navigate to the configured HTTPS search provider.
2. Verify and retain its accessibility snapshot as untrusted content.
3. Run one adapter-owned, fixed DOM query through Playwright MCP `browser_evaluate` to collect
   visible anchor text and absolute URLs. User/model JavaScript is never accepted.
4. Canonicalize, rank, deduplicate, and select two or three observed HTTP(S) result links.
5. Navigate to and snapshot each actual selected source page.
6. Compare only facts in those snapshots using deterministic criteria.
7. Detect missing market, unspecified/conflicting price types, conflicting prices, and missing,
   unparsed, or older-than-one-year source dates.
8. Produce a conclusion only when the configured evidence threshold is met.
9. Write a Markdown report under the approved root, reopen it, and verify exact contents.

Three-source research plus its report uses exactly 12 runtime steps, preserving the existing strict
step limit. Content and report size limits, retries, deadlines, cancellation, loop detection,
permissions, and prompt-injection boundaries remain unchanged.

## Safety of link extraction

`browser_evaluate` is configured as:

```json
"browser_evaluate": {"permission": "read_only", "adapter_only": true}
```

`adapter_only` means the discovered remote tool is not registered as a general
`mcp.playwright.browser_evaluate` tool. Jean Grey exposes only `browser.extract_links`, whose
JavaScript is a constant owned by the adapter. This closes the arbitrary-JavaScript path while
allowing real DOM URLs to be observed. Page-provided text and URLs remain untrusted data and cannot
alter permissions, plans, or filesystem roots.

## Comparison behavior

For vehicle-price requests, findings retain:

- observed subject/model text near the price;
- original stated price and normalized INR value;
- ex-showroom, on-road, starting/unspecified price type;
- requested market presence;
- observed source date and freshness status;
- evidence excerpt and source URL.

A “lowest comparable observed price” conclusion requires price evidence from three distinct
sources, at least one BYD/manufacturer domain for the BYD example, an explicit shared price type,
explicit market evidence, no material same-subject conflict, and current parseable dates. Otherwise
the result says evidence is insufficient and lists limitations. The BYD model and price are not
hardcoded.

This deterministic comparator currently specializes structured price comparisons. Non-price topics
still retain inspected snapshots and URLs, but semantic synthesis for arbitrary domains requires a
validated local model planner and remains a limitation.

## CLI

```powershell
# Install only after explicit review/approval, using project-local environments:
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
npm.cmd install --no-save --package-lock=false @playwright/mcp@0.0.83
Copy-Item .\mcp.windows.example.json "$HOME\.jean-grey\mcp.json"
# Review the isolated-browser allowlist, then set enabled=true.

jean-grey mcp --check
jean-grey browser --check
jean-grey browser --topic "cheapest BYD car available in India" `
  --market "India" --source-count 3 `
  --report "$HOME\.jean-grey\reports\byd-india.md"

jean-grey voice --hands-free --wake-word --speak-responses --language auto
```

The visible CLI result contains the comparison, every inspected source URL, limitations, report
metadata, and task status. Voice uses the same function/runtime and speaks a concise conclusion or
an insufficiency warning. A verified Hindi Piper voice is still required for Hindi audio.

## Automated tests

Deterministic fake MCP/browser pages test:

- search-page navigation and fixed DOM-link extraction;
- dynamic source URL tracking;
- inspection of three source pages;
- model/price type/market/date evidence;
- verified and insufficient conclusions;
- conflicting and undated prices;
- insufficient result links and partial failure;
- prompt-injection isolation;
- no direct arbitrary `browser_evaluate` registration;
- Markdown writing and reopened verification.

## Real integration status and exact blocker

The development sandbox has `npx`, but the official Python `mcp` SDK is missing,
`@playwright/mcp` is not installed, `~/.jean-grey/mcp.json` is absent, and the checked-in example is
disabled. `jean-grey browser --check --config mcp.example.json` correctly returns status 3.
Therefore no public website or source was actually inspected in this sandbox, and the real BYD
acceptance test is **not passed**.

After explicit setup, run:

```powershell
$env:JEAN_GREY_REAL_MCP_TEST = "1"
$env:JEAN_GREY_MCP_CONFIG = "$HOME\.jean-grey\mcp.json"
$env:JEAN_GREY_REAL_TEST_URL = "https://your-controlled-test-site.example/"
python -m unittest tests.integration.test_real_playwright_mcp -v

$env:JEAN_GREY_REAL_RESEARCH_TEST = "1"
$env:JEAN_GREY_REAL_RESEARCH_QUERY = "cheapest BYD car available in India"
python -m unittest tests.integration.test_real_verified_research -v
```

The real research test does not hardcode a car or price. It requires three extracted URLs, actual
source navigation, structured comparison, and an exactly reopened report. An insufficient factual
conclusion can still be an honest completed research task; it is not counted as a cheapest-price
finding.

Wake-word, Hindi STT/TTS, and full-duplex barge-in remain subject to Milestone 3.1's documented
hardware limitations. No audio or browser package/model was automatically downloaded.
