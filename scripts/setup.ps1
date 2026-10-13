[CmdletBinding()]
param(
    [switch]$InstallCore,
    [switch]$InstallDev,
    [switch]$InstallMcp,
    [switch]$Connect
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvJeanGrey = Join-Path $Root ".venv\Scripts\jean-grey.exe"
$Config = if ($env:JEAN_GREY_MCP_CONFIG) { $env:JEAN_GREY_MCP_CONFIG } else { Join-Path $HOME ".jean-grey\mcp.json" }

function Write-Check([string]$Name, [bool]$Passed, [string]$Detail, [string]$Next = "") {
    $label = if ($Passed) { "PASS" } else { "MISSING" }
    Write-Host ("[{0}] {1}: {2}" -f $label, $Name, $Detail)
    if (-not $Passed -and $Next) { Write-Host ("  Next: {0}" -f $Next) }
}

$Py = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $Py) { $Py = Get-Command python.exe -ErrorAction SilentlyContinue }
$PythonOk = $false
if ($Py) {
    $launcherArgs = if ($Py.Name -eq "py.exe") { @("-3.11") } else { @() }
    try {
        $versionText = & $Py.Source @launcherArgs -c "import sys; print('.'.join(map(str,sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
        $PythonOk = $LASTEXITCODE -eq 0
        Write-Check "Python" $PythonOk $versionText "winget install Python.Python.3.11"
    } catch { Write-Check "Python" $false $_.Exception.Message "winget install Python.Python.3.11" }
} else { Write-Check "Python" $false "python launcher not found" "winget install Python.Python.3.11" }

$VenvExists = Test-Path $VenvPython
Write-Check "Project virtual environment" $VenvExists $(if ($VenvExists) { $VenvPython } else { ".venv does not exist" }) "py -3.11 -m venv .venv"

if ($InstallCore -or $InstallDev -or $InstallMcp) {
    if (-not $PythonOk) { throw "Python 3.11 or newer is required." }
    if (-not $VenvExists) { & $Py.Source @launcherArgs -m venv .venv; $VenvExists = $true }
    $extra = if ($InstallDev -and $InstallMcp) { ".[dev,mcp]" } elseif ($InstallDev) { ".[dev]" } elseif ($InstallMcp) { ".[mcp]" } else { "." }
    & $VenvPython -m pip install -e $extra
}

if ($VenvExists) {
    $Editable = & $VenvPython -c "import importlib.metadata as m,json; d=m.distribution('jean-grey'); u=json.loads(d.read_text('direct_url.json') or '{}'); print('yes' if u.get('dir_info',{}).get('editable') else 'no')" 2>$null
    Write-Check "Editable Jean Grey install" ($LASTEXITCODE -eq 0 -and $Editable -eq "yes") $(if ($Editable -eq "yes") { "installed" } else { "not installed editable" }) ".\.venv\Scripts\python.exe -m pip install -e ."
    $McpSdk = & $VenvPython -c "import importlib.util; print('yes' if importlib.util.find_spec('mcp') else 'no')"
    Write-Check "Official Python MCP SDK" ($McpSdk -eq "yes") $(if ($McpSdk -eq "yes") { "installed" } else { "not installed" }) ".\.venv\Scripts\python.exe -m pip install -e '.[mcp]'"
}

$Node = Get-Command node.exe -ErrorAction SilentlyContinue
$Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
$Npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
$NodeOk = $false
if ($Node) {
    $NodeVersion = (& $Node.Source --version).Trim()
    $NodeMajor = [int](($NodeVersion -replace '^v','').Split('.')[0])
    $NodeOk = $NodeMajor -ge 18
    Write-Check "Node.js" $NodeOk "$NodeVersion (Playwright MCP requires Node.js 18+)" "winget install OpenJS.NodeJS.LTS"
} else { Write-Check "Node.js" $false "not found (Playwright MCP requires Node.js 18+)" "winget install OpenJS.NodeJS.LTS" }
Write-Check "npm" ($null -ne $Npm) $(if ($Npm) { $Npm.Source } else { "not found" }) "winget install OpenJS.NodeJS.LTS"
Write-Check "npx" ($null -ne $Npx) $(if ($Npx) { $Npx.Source } else { "not found" }) "winget install OpenJS.NodeJS.LTS"

$McpPackage = Test-Path (Join-Path $Root "node_modules\@playwright\mcp\package.json")
if ($InstallMcp -and $NodeOk -and $Npm -and -not $McpPackage) {
    & $Npm.Source install --no-save --package-lock=false "@playwright/mcp@0.0.83"
    $McpPackage = $LASTEXITCODE -eq 0
}
Write-Check "Microsoft Playwright MCP 0.0.83" $McpPackage $(if ($McpPackage) { "project-local package installed" } else { "project-local package missing" }) "npm.cmd install --no-save --package-lock=false @playwright/mcp@0.0.83"

$EdgePaths = @(
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
)
$Edge = $EdgePaths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
Write-Check "Microsoft Edge browser" ($null -ne $Edge) $(if ($Edge) { "available" } else { "not found" }) "winget install Microsoft.Edge"

if (Test-Path $Config) {
    try {
        $Parsed = Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json
        $Valid = $null -ne $Parsed.servers
        Write-Check "MCP configuration" $Valid $(if ($Valid) { "JSON and servers object present (values not printed)" } else { "servers object missing" }) "Copy-Item .\mcp.windows.example.json '$Config'"
    } catch { Write-Check "MCP configuration" $false "invalid JSON (contents not printed)" "Repair '$Config' or copy the example after backing it up" }
} else {
    Write-Check "MCP configuration" $false "not found: $Config" "New-Item -ItemType Directory -Force '$HOME\.jean-grey'; Copy-Item .\mcp.windows.example.json '$Config'"
}

if ($Connect) {
    if (-not (Test-Path $VenvJeanGrey)) { throw "Install Jean Grey in .venv first." }
    & $VenvJeanGrey mcp --check --config $Config
    $McpExit = $LASTEXITCODE
    & $VenvJeanGrey browser --check --config $Config
    if ($McpExit -ne 0 -or $LASTEXITCODE -ne 0) { exit 3 }
}

Write-Host "No models, voices, browsers, or MCP packages are downloaded unless an Install switch is supplied."
Write-Host "The Windows example is disabled by default and uses isolated Edge state, not your personal profile."
