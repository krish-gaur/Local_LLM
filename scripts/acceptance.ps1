[CmdletBinding()]
param(
    [switch]$InstallDependencies,
    [switch]$RunMcpSmoke,
    [switch]$RunRealWeb,
    [string]$ResearchTopic,
    [string]$ResearchMarket = "India",
    [switch]$RunVoiceDiagnostics,
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $ConfigPath) {
    $ConfigPath = if ($env:JEAN_GREY_MCP_CONFIG) { $env:JEAN_GREY_MCP_CONFIG } else { Join-Path $HOME ".jean-grey\mcp.json" }
}
$Timestamp = (Get-Date -Format "yyyyMMdd-HHmmss-fff") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))
$ResultsRoot = Join-Path $Root "acceptance-results"
New-Item -ItemType Directory -Force $ResultsRoot | Out-Null
$ReportPath = Join-Path $ResultsRoot "acceptance-$Timestamp.md"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$JeanGrey = Join-Path $Root ".venv\Scripts\jean-grey.exe"
$Results = [System.Collections.Generic.List[object]]::new()
$Commands = [System.Collections.Generic.List[string]]::new()
$ObservedUrls = [System.Collections.Generic.List[string]]::new()
$RequestedStageFailed = $false

function Add-Result([string]$Stage, [ValidateSet("PASS","FAIL","SKIPPED","NOT VERIFIED")][string]$Status,
                    [string]$Detail, [string]$Next = "", [int]$ExitCode = -1) {
    $script:Results.Add([pscustomobject]@{ Stage=$Stage; Status=$Status; Detail=$Detail; Next=$Next; ExitCode=$ExitCode })
    $color = switch ($Status) { "PASS" { "Green" } "FAIL" { "Red" } "SKIPPED" { "Yellow" } default { "Cyan" } }
    Write-Host "[$Status] $Stage - $Detail" -ForegroundColor $color
    if ($Next) { Write-Host "  Next: $Next" }
}

function Invoke-Logged([string]$Label, [string]$Executable, [string[]]$Arguments, [string]$LogName) {
    $displayArgs = [System.Collections.Generic.List[string]]::new()
    for ($index = 0; $index -lt $Arguments.Count; $index++) {
        if ($index -gt 0 -and $Arguments[$index - 1] -eq "--topic") { $displayArgs.Add("[REDACTED TOPIC]") }
        else { $displayArgs.Add((Redact-Text $Arguments[$index])) }
    }
    $display = (Redact-Text $Executable) + " " + ($displayArgs -join " ")
    $script:Commands.Add($display)
    $log = Join-Path $ResultsRoot "$Timestamp-$LogName.log"
    $lines = @(& $Executable @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    $code = $LASTEXITCODE
    $lines | Set-Content -LiteralPath $log -Encoding UTF8
    foreach ($line in $lines) { Write-Host $line }
    return [pscustomobject]@{ ExitCode=$code; Lines=$lines; Log=$log }
}

function Test-Command([string]$Name) { return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue) }
function Redact-Text([string]$Value) {
    if ($HOME -and $Value) { return $Value.Replace($HOME, '$HOME') }
    return $Value
}
function Redact-Url([string]$Value) {
    try { return ([uri]$Value).GetLeftPart([System.UriPartial]::Path) }
    catch { return "[invalid URL redacted]" }
}

Write-Host "Jean Grey Windows acceptance runner"
Write-Host "Inspection is passive by default. Real browser/network stages require explicit flags."

# Stage 1: environment inspection.
$Commit = "unknown"
if (Test-Command "git.exe") {
    $Commit = (& git.exe rev-parse HEAD 2>$null).Trim()
    Add-Result "Environment: Git" "PASS" "commit $Commit"
} else { Add-Result "Environment: Git" "FAIL" "git.exe unavailable" "winget install Git.Git" }
if ($env:OS -eq "Windows_NT") { Add-Result "Environment: platform" "PASS" "Windows $([Environment]::OSVersion.Version)" }
else { Add-Result "Environment: platform" "FAIL" "This acceptance runner requires Windows" }

# Stage 2: dependency inspection. No installation occurs unless explicitly requested.
$PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
$PythonOk = $false
if ($PyLauncher) {
    $pyVersion = & $PyLauncher.Source -3.11 -c "import sys; print('.'.join(map(str,sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
    $PythonOk = $LASTEXITCODE -eq 0
}
if ($PythonOk) { Add-Result "Dependency: Python" "PASS" "Python $pyVersion" }
else { Add-Result "Dependency: Python" "FAIL" "Python 3.11+ unavailable" "winget install Python.Python.3.11" }

if (Test-Path $VenvPython) { Add-Result "Dependency: project venv" "PASS" $VenvPython }
else { Add-Result "Dependency: project venv" "FAIL" ".venv is missing" "py -3.11 -m venv .venv" }

$Editable = $false; $McpSdk = $false
if (Test-Path $VenvPython) {
    $editableText = & $VenvPython -c "import importlib.metadata as m,json; d=m.distribution('jean-grey'); u=json.loads(d.read_text('direct_url.json') or '{}'); print('yes' if u.get('dir_info',{}).get('editable') else 'no')" 2>$null
    $Editable = $LASTEXITCODE -eq 0 -and $editableText -eq "yes"
    $mcpText = & $VenvPython -c "import importlib.util; print('yes' if importlib.util.find_spec('mcp') else 'no')" 2>$null
    $McpSdk = $LASTEXITCODE -eq 0 -and $mcpText -eq "yes"
}
if ($Editable) { Add-Result "Dependency: editable Jean Grey" "PASS" "installed in .venv" }
else { Add-Result "Dependency: editable Jean Grey" "FAIL" "editable package unavailable" ".\.venv\Scripts\python.exe -m pip install -e ." }
if ($McpSdk) { Add-Result "Dependency: Python MCP SDK" "PASS" "official SDK import available" }
else { Add-Result "Dependency: Python MCP SDK" "FAIL" "official SDK unavailable" ".\.venv\Scripts\python.exe -m pip install -e '.[mcp]'" }

$Node = Get-Command node.exe -ErrorAction SilentlyContinue
$Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
$Npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
$NodeOk = $false
if ($Node) {
    $nodeVersion = (& $Node.Source --version).Trim(); $nodeMajor = [int](($nodeVersion -replace '^v','').Split('.')[0]); $NodeOk = $nodeMajor -ge 18
}
if ($NodeOk) { Add-Result "Dependency: Node.js" "PASS" $nodeVersion }
else { Add-Result "Dependency: Node.js" "FAIL" "Node.js 18+ unavailable" "winget install OpenJS.NodeJS.LTS" }
if ($Npm) { Add-Result "Dependency: npm" "PASS" "available" } else { Add-Result "Dependency: npm" "FAIL" "npm.cmd unavailable" "winget install OpenJS.NodeJS.LTS" }
if ($Npx) { Add-Result "Dependency: npx" "PASS" "available" } else { Add-Result "Dependency: npx" "FAIL" "npx.cmd unavailable" "winget install OpenJS.NodeJS.LTS" }

$McpPackagePath = Join-Path $Root "node_modules\@playwright\mcp\package.json"
$McpPackageOk = $false
if (Test-Path $McpPackagePath) {
    try { $McpPackageOk = ((Get-Content -Raw -LiteralPath $McpPackagePath | ConvertFrom-Json).version -eq "0.0.83") } catch { $McpPackageOk = $false }
}
if ($McpPackageOk) { Add-Result "Dependency: Playwright MCP" "PASS" "project-local @playwright/mcp@0.0.83" }
else { Add-Result "Dependency: Playwright MCP" "FAIL" "project-local version 0.0.83 unavailable" "npm.cmd install --no-save --package-lock=false @playwright/mcp@0.0.83" }

$EdgePaths = @("$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe", "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe")
$Edge = $EdgePaths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($Edge) { Add-Result "Dependency: Microsoft Edge" "PASS" "browser executable found" }
else { Add-Result "Dependency: Microsoft Edge" "FAIL" "browser executable unavailable" "winget install Microsoft.Edge" }

if ($InstallDependencies) {
    Add-Result "Installation authorization" "PASS" "explicit -InstallDependencies supplied"
    $script:Commands.Add(".\scripts\setup.ps1 -InstallCore -InstallMcp")
    & (Join-Path $Root "scripts\setup.ps1") -InstallCore -InstallMcp
    if ($LASTEXITCODE -ne 0) { $RequestedStageFailed = $true; Add-Result "Dependency installation" "FAIL" "setup.ps1 failed" "Review setup output" -ExitCode $LASTEXITCODE }
    else {
        Add-Result "Dependency installation" "PASS" "project-local install command completed" -ExitCode 0
        if (Test-Path $VenvPython) {
            $editableText = & $VenvPython -c "import importlib.metadata as m,json; d=m.distribution('jean-grey'); u=json.loads(d.read_text('direct_url.json') or '{}'); print('yes' if u.get('dir_info',{}).get('editable') else 'no')" 2>$null
            $Editable = $LASTEXITCODE -eq 0 -and $editableText -eq "yes"
            $mcpText = & $VenvPython -c "import importlib.util; print('yes' if importlib.util.find_spec('mcp') else 'no')" 2>$null
            $McpSdk = $LASTEXITCODE -eq 0 -and $mcpText -eq "yes"
        }
        if (Test-Path $McpPackagePath) {
            try { $McpPackageOk = ((Get-Content -Raw -LiteralPath $McpPackagePath | ConvertFrom-Json).version -eq "0.0.83") } catch { $McpPackageOk = $false }
        }
    }
} else { Add-Result "Dependency installation" "SKIPPED" "no -InstallDependencies flag; nothing installed" }

# Stage 3: configuration validation without printing values.
$ConfigValid = $false; $ConfigEnabled = $false; $AllowlistValid = $false
if (-not (Test-Path $ConfigPath)) {
    Add-Result "MCP configuration" "FAIL" "configuration not found: $ConfigPath" "Copy-Item .\mcp.windows.example.json '$ConfigPath'"
} else {
    try {
        $config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
        $server = $config.servers.playwright
        $ConfigValid = $null -ne $server -and $server.command -eq "npx.cmd" -and $server.browser -eq $true
        $ConfigEnabled = $ConfigValid -and $server.enabled -eq $true
        $tools = @($server.allowed_tools.PSObject.Properties.Name)
        $AllowlistValid = @("browser_navigate","browser_snapshot","browser_tabs") | Where-Object { $_ -notin $tools } | Measure-Object | Select-Object -ExpandProperty Count
        $AllowlistValid = $ConfigValid -and $AllowlistValid -eq 0
        if ($ConfigValid) { Add-Result "MCP configuration syntax" "PASS" "validated without printing configuration values" }
        else { Add-Result "MCP configuration syntax" "FAIL" "Windows Playwright server definition is invalid" "Compare with .\mcp.windows.example.json" }
        if ($AllowlistValid) { Add-Result "MCP tool allowlist" "PASS" "required read-only tools are allowlisted" }
        else { Add-Result "MCP tool allowlist" "FAIL" "required tools are absent" "Review .\mcp.windows.example.json" }
        if ($ConfigEnabled) { Add-Result "MCP server enabled" "PASS" "explicitly enabled" }
        else { Add-Result "MCP server enabled" "FAIL" "server is disabled" "After review, set servers.playwright.enabled to true" }
    } catch { Add-Result "MCP configuration syntax" "FAIL" "invalid JSON; contents were not printed" "Repair the file or copy the example after backing up existing configuration" }
}

$PreflightReady = $PythonOk -and (Test-Path $VenvPython) -and $Editable -and $McpSdk -and $NodeOk -and $Npm -and $Npx -and $McpPackageOk -and $Edge -and $ConfigValid -and $ConfigEnabled -and $AllowlistValid

# Stages 4 and 5: real connection/discovery followed by the existing controlled test.
$SmokePassed = $false
if ($RunMcpSmoke) {
    if (-not $PreflightReady) {
        Add-Result "MCP connection and discovery" "FAIL" "preflight is incomplete; no server was started" "Resolve failed prerequisite checks"
        Add-Result "Controlled local-page test" "SKIPPED" "blocked by failed preflight"
        $RequestedStageFailed = $true
    } else {
        $env:JEAN_GREY_MCP_CONFIG = $ConfigPath
        $diag = Invoke-Logged "MCP diagnostics" $JeanGrey @("mcp","--check","--config",$ConfigPath) "mcp-diagnostic"
        if ($diag.ExitCode -eq 0 -and (($diag.Lines -join "`n") -match '"discovered":\s*[1-9]')) {
            Add-Result "MCP connection and discovery" "PASS" "real server initialized and returned tools" -ExitCode 0
        } else {
            Add-Result "MCP connection and discovery" "FAIL" "diagnostic failed or discovered no tools" "Review $($diag.Log)" -ExitCode $diag.ExitCode
            $RequestedStageFailed = $true
        }
        if (-not $RequestedStageFailed) {
            $env:JEAN_GREY_REAL_MCP_TEST = "1"
            $test = "tests.integration.test_real_playwright_mcp.RealPlaywrightMcpTests.test_controlled_local_page_navigation_snapshot_url_and_close"
            $smoke = Invoke-Logged "Controlled browser test" $VenvPython @("-m","unittest",$test,"-v") "controlled-smoke"
            $text = $smoke.Lines -join "`n"
            if ($smoke.ExitCode -eq 0 -and $text -notmatch "skipped" -and $text -match "OK") {
                $SmokePassed = $true; Add-Result "Controlled local-page test" "PASS" "real MCP navigation, marker, URL, and cleanup assertions passed" -ExitCode 0
            } elseif ($text -match "skipped") {
                Add-Result "Controlled local-page test" "SKIPPED" "unittest skipped; this is not acceptance" "Review $($smoke.Log)" -ExitCode $smoke.ExitCode; $RequestedStageFailed = $true
            } else {
                Add-Result "Controlled local-page test" "FAIL" "real integration test failed" "Review $($smoke.Log)" -ExitCode $smoke.ExitCode; $RequestedStageFailed = $true
            }
        } else { Add-Result "Controlled local-page test" "SKIPPED" "MCP discovery did not pass" }
    }
} else {
    Add-Result "MCP connection and discovery" "NOT VERIFIED" "no -RunMcpSmoke flag; server was not started"
    Add-Result "Controlled local-page test" "NOT VERIFIED" "no real browser test was requested"
}

# Stage 6: external website, only after the controlled test.
if ($RunRealWeb) {
    if (-not $SmokePassed) {
        Add-Result "Real-web test" "SKIPPED" "controlled local-page acceptance did not pass"; $RequestedStageFailed = $true
    } else {
        $env:JEAN_GREY_REAL_WEB_TEST = "1"; $env:JEAN_GREY_REAL_TEST_URL = "https://example.com/"
        $test = "tests.integration.test_real_playwright_mcp.RealPlaywrightMcpTests.test_optional_real_web_page"
        $web = Invoke-Logged "Real-web test" $VenvPython @("-m","unittest",$test,"-v") "real-web"
        $text = $web.Lines -join "`n"
        if ($web.ExitCode -eq 0 -and $text -notmatch "skipped" -and $text -match "OK") { Add-Result "Real-web test" "PASS" "example.com navigation, extraction, and URL assertion passed" -ExitCode 0 }
        elseif ($text -match "skipped") { Add-Result "Real-web test" "SKIPPED" "test skipped; not accepted" "Review $($web.Log)" -ExitCode $web.ExitCode; $RequestedStageFailed = $true }
        else { Add-Result "Real-web test" "FAIL" "network, MCP, or browser test failed" "Review $($web.Log)" -ExitCode $web.ExitCode; $RequestedStageFailed = $true }
    }
} else { Add-Result "Real-web test" "NOT VERIFIED" "no -RunRealWeb flag; no external website accessed" }

# Stage 7: existing research CLI with unique approved report path.
if ($ResearchTopic) {
    if (-not $SmokePassed) {
        Add-Result "Multi-page research" "SKIPPED" "controlled local-page acceptance did not pass"; $RequestedStageFailed = $true
    } else {
        $safeStamp = (Get-Date -Format "yyyyMMdd-HHmmss-fff") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))
        $researchReport = Join-Path $HOME ".jean-grey\reports\acceptance-research-$safeStamp.md"
        $research = Invoke-Logged "Multi-page research" $JeanGrey @("browser","--config",$ConfigPath,"--topic",$ResearchTopic,"--market",$ResearchMarket,"--source-count","3","--report",$researchReport) "research"
        $text = $research.Lines -join "`n"
        try {
            $payload = $text | ConvertFrom-Json
            foreach ($url in @($payload.comparison.source_urls)) {
                if ($url -is [string] -and $url.StartsWith("http") -and $url -notin $ObservedUrls) { $ObservedUrls.Add($url) }
            }
        } catch { Add-Result "Research output parsing" "FAIL" "CLI output was not valid JSON" "Review $($research.Log)"; $RequestedStageFailed = $true }
        if ($research.ExitCode -eq 0 -and (Test-Path $researchReport) -and $ObservedUrls.Count -ge 2) {
            $reportText = Get-Content -Raw -LiteralPath $researchReport
            $allPresent = $true; foreach ($url in $ObservedUrls) { if (-not $reportText.Contains($url)) { $allPresent = $false } }
            if ($allPresent) { Add-Result "Multi-page research" "PASS" "$($ObservedUrls.Count) distinct observed URLs; report reopened and verified: $researchReport" -ExitCode 0 }
            else { Add-Result "Multi-page research" "FAIL" "saved report did not contain every observed URL" "Review $($research.Log)" -ExitCode 1; $RequestedStageFailed = $true }
        } else { Add-Result "Multi-page research" "FAIL" "workflow failed, report missing, or fewer than two URLs observed" "Review $($research.Log)" -ExitCode $research.ExitCode; $RequestedStageFailed = $true }
    }
} else { Add-Result "Multi-page research" "NOT VERIFIED" "no -ResearchTopic value; no search or report was created" }

# Stage 8: passive voice diagnostics only.
if ($RunVoiceDiagnostics) {
    if (-not (Test-Path $JeanGrey)) { Add-Result "Voice diagnostics" "FAIL" "Jean Grey CLI unavailable" "Install the project in .venv"; $RequestedStageFailed = $true }
    else {
        $voice = Invoke-Logged "Voice diagnostics" $JeanGrey @("voice","--check","--wake-word","--language","hi","--speak-responses") "voice"
        if ($voice.ExitCode -eq 0) { Add-Result "Voice diagnostics" "PASS" "passive dependency/model/device checks report ready" -ExitCode 0 }
        else { Add-Result "Voice diagnostics" "FAIL" "one or more requested voice components unavailable; microphone was not opened" "Review $($voice.Log)" -ExitCode $voice.ExitCode; $RequestedStageFailed = $true }
    }
} else { Add-Result "Voice diagnostics" "NOT VERIFIED" "no -RunVoiceDiagnostics flag; microphone was not opened" }

# Stage 9: redacted timestamped report. No environment dump or configuration values are included.
$pass = @($Results | Where-Object Status -eq "PASS").Count
$fail = @($Results | Where-Object Status -eq "FAIL").Count
$skip = @($Results | Where-Object Status -eq "SKIPPED").Count
$notVerified = @($Results | Where-Object Status -eq "NOT VERIFIED").Count
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Jean Grey Windows acceptance report")
$lines.Add("")
$lines.Add("- Timestamp: $Timestamp")
$lines.Add("- Commit: $Commit")
$lines.Add("- Platform: $([Environment]::OSVersion.VersionString)")
$lines.Add("- Configuration path: $(Redact-Text $ConfigPath)")
$lines.Add("- Totals: PASS=$pass, FAIL=$fail, SKIPPED=$skip, NOT VERIFIED=$notVerified")
$lines.Add("")
$lines.Add("## Outcomes")
$lines.Add("")
$lines.Add("| Stage | Status | Exit code | Detail | Remediation |")
$lines.Add("|---|---|---:|---|---|")
foreach ($item in $Results) {
    $detail = (Redact-Text $item.Detail).Replace("|","/").Replace("`r"," ").Replace("`n"," ")
    $next = (Redact-Text $item.Next).Replace("|","/").Replace("`r"," ").Replace("`n"," ")
    $exit = if ($item.ExitCode -ge 0) { $item.ExitCode } else { "-" }
    $lines.Add("| $($item.Stage) | $($item.Status) | $exit | $detail | $next |")
}
$lines.Add("")
$lines.Add("## Commands actually executed")
if ($Commands.Count -eq 0) { $lines.Add("- None beyond passive PowerShell inspection.") }
else { foreach ($command in $Commands) { $lines.Add("- ``$(Redact-Text $command)``") } }
$lines.Add("")
$lines.Add("## Observed source URLs")
if ($ObservedUrls.Count -eq 0) { $lines.Add("- None.") } else { foreach ($url in $ObservedUrls) { $lines.Add("- $(Redact-Url $url)") } }
$lines.Add("")
$lines.Add("## Safety notes")
$lines.Add("- No complete environment dump, cookies, tokens, passwords, or configuration values are included.")
$lines.Add("- SKIPPED and NOT VERIFIED never count as real-browser acceptance success.")
$lines.Add("- Voice diagnostics are passive; this runner does not perform interactive microphone acceptance.")
$lines | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Host "Acceptance report: $ReportPath"
Write-Host "Totals: PASS=$pass FAIL=$fail SKIPPED=$skip NOT VERIFIED=$notVerified"

if ($RequestedStageFailed) { exit 1 }
if ($fail -gt 0) { exit 3 }
exit 0
