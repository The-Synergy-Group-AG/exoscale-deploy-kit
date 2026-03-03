#!/usr/bin/env python3
"""fix_frontend_services.py
Creates main.py + config.json for the 11 frontend-only service dirs.
Uses string concatenation (not .format()) to avoid brace conflicts.
"""
import json, pathlib

SERVICES_DIR = pathlib.Path(__file__).parent / "service" / "services"

FRONTEND_SERVICES = [
    "ai-conversation-frontend",
    "credits-redemption-frontend",
    "frontend-api-gateway",
    "gamification-frontend",
    "interview-prep-frontend",
    "networking-frontend",
    "notifications-center-frontend",
    "onboarding-frontend",
    "payment-billing-frontend",
    "rav-compliance-frontend",
    "shared-components-library-frontend",
]

def make_main_py(name: str) -> str:
    title = name.replace("-", " ").title()
    lines = [
        '"""',
        name + " - Frontend Service (API Layer)",
        "Auto-generated backend API for frontend service.",
        '"""',
        "",
        "import json",
        "import logging",
        "from fastapi import FastAPI",
        "",
        "logging.basicConfig(level=logging.INFO)",
        "logger = logging.getLogger(__name__)",
        "",
        'with open("config.json", "r") as f:',
        "    config = json.load(f)",
        "",
        "SERVICE_NAME = config.get('service_name', '" + name + "')",
        "SERVICE_VERSION = config.get('version', '1.0.0')",
        "",
        "app = FastAPI(",
        "    title=SERVICE_NAME + ' API',",
        "    description='Frontend service API layer',",
        "    version=SERVICE_VERSION,",
        ")",
        "",
        "",
        '@app.get("/")',
        "async def root():",
        '    """Root endpoint."""',
        "    return {",
        '        "service": "' + name + '",',
        '        "type": "frontend",',
        '        "status": "running",',
        '        "version": SERVICE_VERSION,',
        '        "description": config.get("description", "Frontend service API layer"),',
        '        "endpoints": ["/", "/health", "/status"],',
        "    }",
        "",
        "",
        '@app.get("/health")',
        "async def health():",
        '    """Health check."""',
        "    return {",
        '        "service": "' + name + '",',
        '        "status": "healthy",',
        '        "type": "frontend",',
        '        "version": SERVICE_VERSION,',
        "    }",
        "",
        "",
        '@app.get("/status")',
        "async def status():",
        '    """Service status."""',
        "    return {",
        '        "service": "' + name + '",',
        '        "status": "operational",',
        '        "type": "frontend",',
        '        "config": config,',
        "    }",
        "",
    ]
    return "\n".join(lines)


created = skipped = errors = 0

print(f"Scanning {SERVICES_DIR}")
for name in FRONTEND_SERVICES:
    svc_dir = SERVICES_DIR / name
    if not svc_dir.exists():
        print(f"  [SKIP] {name} — directory not found")
        skipped += 1
        continue

    main_py = svc_dir / "main.py"
    config_json = svc_dir / "config.json"

    if main_py.exists():
        print(f"  [EXISTS] {name}/main.py")
        skipped += 1
        continue

    try:
        # config.json
        if not config_json.exists():
            cfg = {
                "service_name": name,
                "service_type": "frontend",
                "description": name.replace("-", " ").title() + " API service",
                "port": 8000,
                "version": "1.0.0",
                "auto_generated": True,
            }
            config_json.write_text(json.dumps(cfg, indent=2))

        # main.py
        main_py.write_text(make_main_py(name))
        print(f"  [OK]     {name}/main.py + config.json created")
        created += 1
    except Exception as e:
        print(f"  [ERROR]  {name}: {e}")
        errors += 1

print(f"\nDone: {created} created, {skipped} skipped, {errors} errors")

all_dirs    = sorted(d.name for d in SERVICES_DIR.iterdir() if d.is_dir())
with_main   = [n for n in all_dirs if (SERVICES_DIR / n / "main.py").exists()]
without_main= [n for n in all_dirs if not (SERVICES_DIR / n / "main.py").exists()]
print(f"\nService inventory:")
print(f"  Total dirs:      {len(all_dirs)}")
print(f"  With main.py:    {len(with_main)}")
print(f"  Without main.py: {len(without_main)}")
if without_main:
    print(f"  Still missing:   {without_main}")
else:
    print("  All 219 services have main.py — ready to build image :4")
