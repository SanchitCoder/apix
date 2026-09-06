"""Enforcement of guardrail one: ``apix_core.policy`` is the ONLY egress point.

This test walks the AST of every production module in the repository and fails if
anything outside ``apix_core.policy`` imports an HTTP client. It is the mechanism —
not documentation — that keeps ``PolicyEngine.request`` the single path to the
network, so it must stay green forever. If it is failing on your change, the fix is
to route the traffic through the PolicyEngine, never to touch this list.

Scope: production source trees (``packages/*/src`` and ``apps/*/src``). The test
suite itself is excluded because it exercises the engine against ``httpx.MockTransport``
fixtures; tests are separately barred from live traffic by the no-live-internet rule
in ``tests/conftest.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Any way of speaking HTTP. Extend this list; never shorten it.
BANNED_MODULES = frozenset(
    {"httpx", "requests", "aiohttp", "urllib3", "http.client", "pycurl", "treq"}
)

# The one package allowed to hold an HTTP client, as a path fragment.
EGRESS_PACKAGE = Path("apix_core") / "policy"


def production_modules(repo_root: Path) -> list[Path]:
    files = [
        path
        for pattern in ("packages/*/src", "apps/*/src")
        for src_root in repo_root.glob(pattern)
        for path in src_root.rglob("*.py")
    ]
    assert files, "no production modules found — the scan itself is broken"
    return files


def banned_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or node.module is None:
                continue  # relative imports cannot leave the package
            names = [node.module]
        else:
            continue
        for name in names:
            if name in BANNED_MODULES or name.split(".")[0] in BANNED_MODULES:
                found.append(f"{path}:{node.lineno}: imports {name}")
    return found


def test_no_module_outside_apix_core_policy_imports_an_http_client(repo_root: Path):
    offenders: list[str] = []
    scanned = 0
    for path in production_modules(repo_root):
        scanned += 1
        if str(EGRESS_PACKAGE) in str(path):
            continue
        offenders.extend(banned_imports(path))
    assert scanned > 10, "suspiciously few modules scanned — check the glob patterns"
    assert offenders == [], (
        "HTTP client imported outside apix_core.policy. All egress goes through "
        "PolicyEngine.request — route the traffic through it instead:\n" + "\n".join(offenders)
    )


def test_the_egress_package_itself_is_scanned_honestly(repo_root: Path):
    """Sanity check on the scanner: it does find httpx inside the policy package,
    proving a hit elsewhere would not be missed."""
    policy_files = [p for p in production_modules(repo_root) if str(EGRESS_PACKAGE) in str(p)]
    hits = [hit for path in policy_files for hit in banned_imports(path)]
    assert hits, "the scanner found no HTTP client even in apix_core.policy — it is broken"
