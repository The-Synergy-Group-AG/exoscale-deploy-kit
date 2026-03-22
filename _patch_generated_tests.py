#!/usr/bin/env python3
"""
Patch generated test files — three code-generation bugs (L54).

Run automatically by prep_services.py after every service sync (L54 strategic fix).
Also callable directly: python3 _patch_generated_tests.py [services_dir]

Bug 1 — Wrong HTTP method on PUT endpoints (e2e + user_stories, ~105 services):
  Docstring says "PUT /resource/{id}" but code uses httpx.post → server returns 405.
  Fix: change httpx.post → httpx.put in methods whose docstring starts with PUT.

Bug 2 — Duplicate test method names (integration, ~6 services):
  Second definition silently overwrites first in Python class.
  Fix: rename duplicate methods by appending _put / _get / _v2 suffix.

Bug 3 — httpx.delete() called with json={} (~126 files):
  httpx.delete() does not accept a json keyword argument → TypeError.
  Fix: remove json={} from all httpx.delete() calls.
"""
import ast
import re
import sys
from pathlib import Path


def _resolve_services_dir() -> Path:
    """Resolve services dir: CLI arg → CURRENT pointer → fallback next to script."""
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).resolve()
    # Try reading CURRENT pointer from service engine outputs
    project_root = Path(__file__).parent.parent
    current_file = project_root / "engines" / "service_engine" / "outputs" / "CURRENT"
    if current_file.exists():
        generation = current_file.read_text().strip()
        candidate = project_root / "engines" / "service_engine" / "outputs" / generation / "services"
        if candidate.is_dir():
            return candidate
    # Fallback: services/ next to this script (old location)
    return Path(__file__).parent / "services"


SERVICES_DIR = _resolve_services_dir()

def http_method_from_docstring(docstring: str) -> str | None:
    """Extract HTTP method from first line of docstring, e.g. 'PUT /foo' → 'put'."""
    if not docstring:
        return None
    first_line = docstring.strip().split("\n")[0].strip()
    # Patterns: "E2E: PUT /foo", "Integration: PUT /foo", "PUT /foo"
    m = re.search(r'\b(GET|POST|PUT|PATCH|DELETE)\b', first_line, re.IGNORECASE)
    return m.group(1).lower() if m else None


def patch_file(path: Path) -> tuple[int, int]:
    """
    Patch a single test file.
    Returns (method_fixes, rename_fixes).
    """
    original = path.read_text()
    lines = original.splitlines(keepends=True)

    # ── Parse AST to find methods to fix ────────────────────────────────────
    try:
        tree = ast.parse(original)
    except SyntaxError:
        return 0, 0

    method_fixes = 0
    rename_fixes = 0
    replacements: list[tuple[int, int, str]] = []  # (lineno_start, lineno_end, new_source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Track method names to detect duplicates
        seen_names: dict[str, int] = {}  # name → count

        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue

            name = item.name
            lineno_start = item.lineno     # 1-based
            lineno_end   = item.end_lineno  # 1-based inclusive

            # Extract docstring
            docstring = ast.get_docstring(item) or ""
            declared_method = http_method_from_docstring(docstring)

            # ── Bug 2: duplicate method names ────────────────────────────────
            if name in seen_names:
                seen_names[name] += 1
                count = seen_names[name]
                suffix = f"_{declared_method}" if declared_method else f"_v{count}"
                new_name = f"{name}{suffix}"
                # Replace only the `def <name>(` line
                def_line_idx = lineno_start - 1
                original_def = lines[def_line_idx]
                patched_def = original_def.replace(f"def {name}(", f"def {new_name}(", 1)
                if patched_def != original_def:
                    lines[def_line_idx] = patched_def
                    rename_fixes += 1
            else:
                seen_names[name] = 1

            # ── Bug 1: wrong HTTP method ──────────────────────────────────────
            # Only fix if docstring declares a non-POST method but code uses httpx.post
            if declared_method and declared_method != "post":
                for i in range(lineno_start - 1, lineno_end):
                    line = lines[i]
                    # Match httpx.post( but not httpx.post_xxx or similar
                    if re.search(r'\bhttpx\.post\(', line):
                        patched = re.sub(
                            r'\bhttpx\.post\(',
                            f'httpx.{declared_method}(',
                            line
                        )
                        if patched != line:
                            lines[i] = patched
                            method_fixes += 1

    patched = "".join(lines)
    if patched != original:
        path.write_text(patched)

    return method_fixes, rename_fixes


def main():
    total_files = 0
    total_method_fixes = 0
    total_rename_fixes = 0
    patched_files = 0

    suites = ["e2e", "user_stories", "integration", "security"]

    delete_fixes = 0
    for service_dir in sorted(SERVICES_DIR.iterdir()):
        if not service_dir.is_dir():
            continue
        for suite in suites:
            suite_dir = service_dir / "tests" / suite
            if not suite_dir.is_dir():
                continue
            for test_file in suite_dir.glob("test_*.py"):
                total_files += 1
                mf, rf = patch_file(test_file)

                # Bug 3: httpx.delete() with json={} → TypeError
                original = test_file.read_text()
                patched = re.sub(r'(httpx\.delete\([^)]+?),\s*json=\{\}', r'\1', original)
                df = original.count('httpx.delete') - patched.count(', json={}') if patched != original else 0
                # Simpler: count replacements
                if patched != original:
                    count_before = original.count(', json={}')
                    df = count_before
                    test_file.write_text(patched)
                    delete_fixes += df
                else:
                    df = 0

                if mf or rf or df:
                    patched_files += 1
                    total_method_fixes += mf
                    total_rename_fixes += rf
                    print(f"  PATCHED {test_file.parent.parent.parent.name}/{suite}/{test_file.name}"
                          f" — {mf} method fixes, {rf} renames, {df} delete fixes")

    # Bug 4 (L63): test_us_endpoints_operational sends GET to POST/PUT/DELETE endpoints
    # Fix: filter the endpoints list to only include GET-reachable paths
    ep_op_fixes = 0
    for service_dir in sorted(SERVICES_DIR.iterdir()):
        if not service_dir.is_dir():
            continue
        us_test = service_dir / "tests" / "user_stories" / "test_user_stories.py"
        if not us_test.exists():
            continue
        content = us_test.read_text()
        if "test_us_endpoints_operational" not in content:
            continue
        # Find the endpoints list and the httpx.get loop
        # Replace: test all endpoints with GET → only test GET endpoints
        # The test sends httpx.get to each path; POST-only paths return 405
        # Fix: add method check — skip paths that aren't GET-able
        old_pattern = (
            '                r = httpx.get(f"{SERVICE_BASE}{path}", timeout=10.0)\n'
            '                assert r.status_code < 400, f"L63: {path} returned {r.status_code}"'
        )
        new_pattern = (
            '                r = httpx.get(f"{SERVICE_BASE}{path}", timeout=10.0)\n'
            '                if r.status_code == 405: continue  # L63 Bug4: POST-only endpoint\n'
            '                assert r.status_code < 400, f"L63: {path} returned {r.status_code}"'
        )
        if old_pattern in content and "Bug4" not in content:
            content = content.replace(old_pattern, new_pattern)
            us_test.write_text(content)
            ep_op_fixes += 1

    print()
    print(f"Files scanned : {total_files}")
    print(f"Files patched : {patched_files}")
    print(f"Method fixes  : {total_method_fixes}  (POST→correct method)")
    print(f"Rename fixes  : {total_rename_fixes}  (duplicate names)")
    print(f"Delete fixes  : {delete_fixes}  (json={{}} removed from httpx.delete)")
    print(f"Endpoint fixes: {ep_op_fixes}  (L63 Bug4: skip 405 in endpoints_operational)")


if __name__ == "__main__":
    main()
