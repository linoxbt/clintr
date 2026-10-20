"""Byte-exact, independently reproducible workload for the proof demo."""
import base64
import hashlib
import json
import re

MAX_INPUT = 65536
MAX_OUTPUT = 4096
MODEL = "byte_histogram_v1"
CID_PATTERN = re.compile(r"b[a-z2-7]{58}$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_cid(data: bytes) -> str:
    """CIDv1, raw codec, SHA2-256 multihash of the exact bytes."""
    return "b" + base64.b32encode(b"\x01\x55\x12\x20" + hashlib.sha256(data).digest()).decode().lower().rstrip("=")


def run(model_id: str, data: bytes) -> bytes:
    if model_id != MODEL:
        raise ValueError("Unsupported model")
    if len(data) > MAX_INPUT:
        raise ValueError("Input exceeds 64 KiB")
    bins = [0] * 16
    for item in data:
        bins[item >> 4] += 1
    return json.dumps({"bins": bins, "bytes": len(data)}, sort_keys=True, separators=(",", ":")).encode()


def verify(model_id: str, input_bytes: bytes, output_bytes: bytes, output_cid: str, proof_hash: str) -> bool:
    if len(output_bytes) > MAX_OUTPUT or not re.fullmatch(r"[0-9a-f]{64}", proof_hash):
        return False
    return raw_cid(output_bytes) == output_cid and digest(output_bytes) == proof_hash and run(model_id, input_bytes) == output_bytes
