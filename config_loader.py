#!/usr/bin/env python3
"""
Config Loader — Exoscale Deploy Kit
====================================
Loads configuration from config.yaml and merges with environment variables.

Security model:
  - Non-secret settings: config.yaml (committed to git)
  - Secrets/credentials: .env file or environment variables (NEVER committed)

Usage:
  from config_loader import load_config
  cfg = load_config()
  print(cfg["project_name"])

Environment variables required (set in .env or shell):
  EXO_API_KEY      — Exoscale API key (from Console → IAM → API Keys)
  EXO_API_SECRET   — Exoscale API secret
  DOCKER_HUB_TOKEN — Docker Hub personal access token (from hub.docker.com → Settings → PATs)
"""
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("❌ ERROR: pyyaml not installed. Run: pip install -r requirements.txt")
    sys.exit(1)


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """
    Load configuration from config.yaml and inject credentials from environment.

    Args:
        config_path: Path to config.yaml (relative to this file or absolute)

    Returns:
        Complete configuration dict with all settings and credentials

    Raises:
        FileNotFoundError: If config.yaml does not exist
        KeyError: If a required environment variable is missing
        ValueError: If config.yaml is missing required keys
    """
    # Resolve config path relative to this file
    cfg_file = Path(__file__).parent / config_path
    if not cfg_file.exists():
        raise FileNotFoundError(
            f"config.yaml not found at {cfg_file}\n"
            f"Copy config.yaml to {cfg_file.parent}/ and edit for your project."
        )

    # Load YAML configuration
    with open(cfg_file) as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    # Validate required config keys
    required_keys = [
        "project_name", "service_name", "service_version", "docker_hub_user",
        "exoscale_zone", "node_count", "node_disk_gb",
        "node_type_family", "node_type_size",
        "k8s_namespace", "k8s_replicas", "k8s_port", "k8s_nodeport",
        "sks_cni", "sks_level",
    ]
    missing = [k for k in required_keys if k not in cfg]
    if missing:
        raise ValueError(
            f"config.yaml is missing required keys: {missing}\n"
            f"Check config.yaml against the template."
        )

    # Load .env file if present (for local development)
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        _load_dotenv(env_file)

    # Inject credentials from environment (NEVER from config.yaml)
    required_env = {
        "exo_key":          "EXO_API_KEY",
        "exo_secret":       "EXO_API_SECRET",
        "docker_hub_token": "DOCKER_HUB_TOKEN",
    }
    missing_env = []
    for cfg_key, env_var in required_env.items():
        value = os.environ.get(env_var)
        if not value:
            missing_env.append(env_var)
        else:
            cfg[cfg_key] = value

    if missing_env:
        raise KeyError(
            f"Required environment variables not set: {missing_env}\n"
            f"Copy .env.example to .env and fill in your credentials."
        )

    # Derive convenience values
    cfg.setdefault("k8s_service_port", cfg["k8s_port"])

    return cfg


def _load_dotenv(env_file: Path) -> None:
    """Parse and load a .env file into os.environ (simple implementation)."""
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"\'')  # Remove surrounding quotes
            if key and key not in os.environ:  # Don't override actual env vars
                os.environ[key] = value


if __name__ == "__main__":
    """Quick validation — run: python3 config_loader.py"""
    try:
        cfg = load_config()
        print("✅ Configuration loaded successfully")
        print(f"   Project:   {cfg['project_name']}")
        print(f"   Service:   {cfg['service_name']}:{cfg['service_version']}")
        print(f"   Zone:      {cfg['exoscale_zone']}")
        print(f"   Namespace: {cfg['k8s_namespace']}")
        print(f"   Nodes:     {cfg['node_count']} x {cfg['node_type_family']}.{cfg['node_type_size']}")
        print(f"   EXO Key:   {cfg['exo_key'][:8]}... (redacted)")
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
