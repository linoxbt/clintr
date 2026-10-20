"""Byte-exact, independently reproducible workload for the proof demo."""
import base64
import hashlib
import json
import re

MAX_INPUT = 65536
MAX_OUTPUT = 4096
MODEL = "byte_histogram_v1"
MLP_MODEL = "edge_mlp_v1"
MODELS = (MODEL, MLP_MODEL)
CID_PATTERN = re.compile(r"b[a-z2-7]{58}$")
HIDDEN_WEIGHTS = ((2, -1, 0, 1, 2, -2, 1, 0), (-1, 2, 1, 0, -1, 1, 2, -2), (1, 1, -2, 2, 0, -1, 1, 1), (0, -1, 2, 1, 1, 2, -1, 1))
HIDDEN_BIAS = (1, -2, 0, 3)
OUTPUT_WEIGHTS = ((2, -1, 1, 0), (-1, 2, 0, 1))
OUTPUT_BIAS = (0, 1)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_cid(data: bytes) -> str:
    """CIDv1, raw codec, SHA2-256 multihash of the exact bytes."""
    return "b" + base64.b32encode(b"\x01\x55\x12\x20" + hashlib.sha256(data).digest()).decode().lower().rstrip("=")


def run(model_id: str, data: bytes) -> bytes:
    if model_id not in MODELS:
        raise ValueError("Unsupported model")
    if len(data) > MAX_INPUT:
        raise ValueError("Input exceeds 64 KiB")
    if model_id == MLP_MODEL:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("MLP input must be JSON") from exc
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list) or len(features) != 8 or any(type(value) is not int or not -128 <= value <= 127 for value in features):
            raise ValueError("MLP input needs eight integer features from -128 to 127")
        hidden = [max(0, sum(weight * value for weight, value in zip(row, features)) + bias) for row, bias in zip(HIDDEN_WEIGHTS, HIDDEN_BIAS)]
        scores = [sum(weight * value for weight, value in zip(row, hidden)) + bias for row, bias in zip(OUTPUT_WEIGHTS, OUTPUT_BIAS)]
        return json.dumps({"class": 0 if scores[0] >= scores[1] else 1, "scores": scores}, sort_keys=True, separators=(",", ":")).encode()
    bins = [0] * 16
    for item in data:
        bins[item >> 4] += 1
    return json.dumps({"bins": bins, "bytes": len(data)}, sort_keys=True, separators=(",", ":")).encode()


def verify(model_id: str, input_bytes: bytes, output_bytes: bytes, output_cid: str, proof_hash: str) -> bool:
    if len(output_bytes) > MAX_OUTPUT or not re.fullmatch(r"[0-9a-f]{64}", proof_hash):
        return False
    return raw_cid(output_bytes) == output_cid and digest(output_bytes) == proof_hash and run(model_id, input_bytes) == output_bytes
