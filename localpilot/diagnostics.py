"""Side-effect-free deployment prerequisite diagnostics."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


def _version(command: str) -> str | None:
    try:
        result = subprocess.run([command, "--version"], capture_output=True, text=True,
                                timeout=5, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0][:100] if value and result.returncode == 0 else None


def executable(command: str) -> str | None:
    """Resolve a command without running it or exposing configured arguments."""
    return shutil.which(command)


def node_prerequisites() -> dict[str, Any]:
    node = executable("node.exe" if os.name == "nt" else "node")
    npm = executable("npm.cmd" if os.name == "nt" else "npm")
    npx = executable("npx.cmd" if os.name == "nt" else "npx")
    version = _version(node) if node else None
    major: int | None = None
    if version:
        try: major = int(version.lstrip("v").split(".", 1)[0])
        except ValueError: pass
    return {"node_available": bool(node), "node_version": version, "node_supported": major is not None and major >= 18,
            "npm_available": bool(npm), "npx_available": bool(npx),
            "requirement": "Node.js 18 or newer",
            "next_command": "winget install OpenJS.NodeJS.LTS" if not node else None}


def python_prerequisites() -> dict[str, Any]:
    supported = sys.version_info >= (3, 11)
    return {"version": ".".join(map(str, sys.version_info[:3])), "supported": supported,
            "requirement": "Python 3.11 or newer",
            "virtual_environment": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
            "mcp_sdk_available": importlib.util.find_spec("mcp") is not None,
            "next_command": None if supported else "winget install Python.Python.3.11"}


def _windows_browser_candidates(name: str) -> tuple[Path, ...]:
    roots = [Path(value) for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
             if (value := os.getenv(key))]
    suffixes = {
        "msedge": ("Microsoft/Edge/Application/msedge.exe",),
        "chrome": ("Google/Chrome/Application/chrome.exe",),
        "chromium": ("Chromium/Application/chrome.exe",),
    }.get(name, ())
    return tuple(root / suffix for root in roots for suffix in suffixes)


def browser_prerequisite(browser_name: str | None) -> dict[str, Any]:
    name = (browser_name or "chromium").lower()
    command_names = {"msedge": ("msedge.exe", "msedge"), "chrome": ("chrome.exe", "chrome", "google-chrome"),
                     "chromium": ("chromium.exe", "chromium", "chromium-browser")}.get(name, (name,))
    found = next((executable(item) for item in command_names if executable(item)), None)
    if os.name == "nt" and found is None:
        found = next((str(path) for path in _windows_browser_candidates(name) if path.is_file()), None)
    next_command = None
    if found is None:
        next_command = ("winget install Microsoft.Edge" if name == "msedge" else
                        f"npx.cmd playwright install {'chrome' if name == 'chrome' else 'chromium'}")
    return {"requested_browser": name, "available": found is not None,
            "status": "browser_available_not_yet_tested" if found else "browser_unavailable",
            "next_command": next_command}


def configured_browser(args: tuple[str, ...]) -> str | None:
    try: return args[args.index("--browser") + 1]
    except (ValueError, IndexError): return None


def playwright_mcp_prerequisite(args: tuple[str, ...], root: Path | None = None) -> dict[str, Any]:
    requested = next((item for item in args if item.startswith("@playwright/mcp")), None)
    package = (root or Path.cwd()) / "node_modules" / "@playwright" / "mcp" / "package.json"
    available = package.is_file(); installed_version = None
    if available:
        try:
            import json
            installed_version = str(json.loads(package.read_text(encoding="utf-8")).get("version"))
        except (OSError, ValueError, TypeError): available = False
    requested_version = requested.rsplit("@", 1)[-1] if requested and "@" in requested[1:] else None
    version_match = available and (requested_version is None or installed_version == requested_version)
    return {"requested_package": requested, "installed_version": installed_version,
            "project_local_available": available, "version_match": version_match,
            "status": "available" if version_match else "dependency_missing",
            "next_command": None if available else
                "npm.cmd install --no-save --package-lock=false @playwright/mcp@0.0.83"}


def project_install_status(project_root: Path) -> dict[str, Any]:
    distribution = None
    try:
        from importlib.metadata import distribution
        package = distribution("jean-grey")
        direct_url = package.read_text("direct_url.json") or ""
        editable = '"editable": true' in direct_url.lower()
        distribution = {"installed": True, "version": package.version, "editable": editable}
    except Exception:
        distribution = {"installed": False, "version": None, "editable": False}
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    return {"venv_exists": venv_python.is_file(), "package": distribution,
            "next_command": None if distribution["editable"] else
                r".\.venv\Scripts\python.exe -m pip install -e ."}
