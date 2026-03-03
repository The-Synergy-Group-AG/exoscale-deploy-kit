#!/usr/bin/env python3
"""
make_pull_secret.py
Extracts Docker Hub credentials from the credential store (docker-credential-desktop
or docker-credential-wincred) and creates a proper Kubernetes imagePullSecret.
"""
import json, subprocess, base64, os, sys, pathlib

KUBECONFIG = str(pathlib.Path(__file__).parent / "outputs" / "20260302_143353" / "kubeconfig.yaml")
NAMESPACE   = "exo-jtp-prod"
SECRET_NAME = "dockerhub-creds"
REGISTRY    = "https://index.docker.io/v1/"

# ---- Step 1: detect credential store ----
config_path = pathlib.Path.home() / ".docker" / "config.json"
try:
    cfg = json.loads(config_path.read_text())
except Exception as e:
    print(f"Cannot read docker config: {e}"); sys.exit(1)

creds_store = cfg.get("credsStore") or cfg.get("credStore")
print(f"Docker credsStore: {creds_store!r}")

username = password = None

# ---- Step 2: extract via credential helper ----
if creds_store:
    helper = f"docker-credential-{creds_store}"
    try:
        result = subprocess.run(
            [helper, "get"],
            input=REGISTRY.encode(),
            capture_output=True, timeout=10
        )
        if result.returncode == 0:
            cred = json.loads(result.stdout)
            username = cred.get("Username")
            password = cred.get("Secret")
            print(f"Got credentials for {username!r} from {helper}")
        else:
            print(f"Credential helper failed: {result.stderr.decode()}")
    except FileNotFoundError:
        print(f"Credential helper '{helper}' not found — trying inline auth")

# ---- Step 3: fallback to inline auth in config.json ----
if not (username and password):
    auth_b64 = cfg.get("auths", {}).get(REGISTRY, {}).get("auth", "")
    if auth_b64:
        decoded = base64.b64decode(auth_b64).decode()
        username, _, password = decoded.partition(":")
        print(f"Got inline auth for {username!r}")
    else:
        print("No credentials found — cannot create secret.")
        print("Please run: docker login")
        sys.exit(1)

# ---- Step 4: build the .dockerconfigjson ----
auth_token = base64.b64encode(f"{username}:{password}".encode()).decode()
docker_config = {
    "auths": {
        "https://index.docker.io/v1/": {"auth": auth_token},
        "registry-1.docker.io":        {"auth": auth_token},
    }
}
docker_config_b64 = base64.b64encode(json.dumps(docker_config).encode()).decode()

# ---- Step 5: create the secret via kubectl ----
env = {**os.environ, "KUBECONFIG": KUBECONFIG}

# Delete existing
subprocess.run(
    ["kubectl", "delete", "secret", SECRET_NAME, "-n", NAMESPACE, "--ignore-not-found"],
    env=env, capture_output=True
)

# Create new
secret_yaml = json.dumps({
    "apiVersion": "v1",
    "kind": "Secret",
    "metadata": {"name": SECRET_NAME, "namespace": NAMESPACE},
    "type": "kubernetes.io/dockerconfigjson",
    "data": {".dockerconfigjson": docker_config_b64}
})

result = subprocess.run(
    ["kubectl", "apply", "-f", "-"],
    input=secret_yaml.encode(),
    env=env, capture_output=True
)
print(result.stdout.decode(), result.stderr.decode())

# ---- Step 6: verify ----
r = subprocess.run(
    ["kubectl", "get", "secret", SECRET_NAME, "-n", NAMESPACE],
    env=env, capture_output=True
)
print(r.stdout.decode())
print("Done — secret created with real credentials.")
