#!/usr/bin/env python3
"""
Remove --timeout=N from pytest command in run_service_tests.py.
pytest-timeout is not installed in the docker image, so this arg causes
all tests to fail with 'unrecognized arguments' error.
kubectl exec timeout handles overall time bounding.
"""
from pathlib import Path
import subprocess

f = Path(__file__).parent / "run_service_tests.py"
original = f.read_text()

old_line = '        f"--timeout={timeout - 10}",  # pytest-timeout if available\n'
new_line = ''  # remove entirely

if old_line in original:
    patched = original.replace(old_line, new_line)
    f.write_text(patched)
    print("[OK] Removed --timeout arg from pytest command")
else:
    print("[WARN] Target line not found — checking for variations...")
    # Try with different whitespace
    import re
    patched = re.sub(r'\s+f"--timeout=\{timeout - 10\}",.*?\n', '\n', original)
    if patched != original:
        f.write_text(patched)
        print("[OK] Removed --timeout arg (regex match)")
    else:
        print("[FAIL] Could not find --timeout line — manual fix needed")
        print("File contents around line 127:")
        lines = original.splitlines()
        for i, l in enumerate(lines[122:132], 123):
            print(f"  {i}: {repr(l)}")

result = subprocess.run(["wc", "-l", str(f)], capture_output=True, text=True)
print(f"Line count: {result.stdout.strip()}")
result2 = subprocess.run(["python3", "-m", "py_compile", str(f)], capture_output=True, text=True)
if result2.returncode == 0:
    print("[OK] Syntax check PASS")
else:
    print(f"[FAIL] Syntax error: {result2.stderr}")

# Verify the fix
if '--timeout=' not in f.read_text().split('pytest-timeout')[0]:
    print("[OK] --timeout arg successfully removed from pytest command")
