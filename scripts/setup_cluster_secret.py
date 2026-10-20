"""Persist one random IPFS Cluster swarm secret for the local Compose stack."""
from pathlib import Path
import os
import re
import secrets


env_file = Path(__file__).resolve().parent.parent / ".env"
contents = env_file.read_text() if env_file.exists() else ""
existing = [line.split("=", 1)[1] for line in contents.splitlines() if line.startswith("CLINTR_CLUSTER_SECRET=")]
if existing and (len(existing) != 1 or re.fullmatch(r"[0-9a-f]{64}", existing[0]) is None):
    raise ValueError("Existing CLINTR_CLUSTER_SECRET in .env must be 64 lowercase hex characters")
if not existing:
    with env_file.open("a") as stream:
        if contents and not contents.endswith("\n"):
            stream.write("\n")
        stream.write(f"CLINTR_CLUSTER_SECRET={secrets.token_hex(32)}\n")
os.chmod(env_file, 0o600)
print("Local IPFS Cluster secret is configured in .env")
