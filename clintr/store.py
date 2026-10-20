"""Content addressed local store for the runnable demo; raw CIDs also work with Kubo."""
from pathlib import Path
import httpx
from .compute import CID_PATTERN, raw_cid


class BlobStore:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        cid = raw_cid(data)
        target = self.root / cid
        if not target.exists():
            target.write_bytes(data)
        return cid

    def get(self, cid: str) -> bytes:
        if not CID_PATTERN.fullmatch(cid):
            raise ValueError("Invalid raw CID")
        data = (self.root / cid).read_bytes()
        if raw_cid(data) != cid:
            raise ValueError("Content does not match CID")
        return data


class KuboStore:
    """Pin raw blocks through Kubo's private RPC API."""

    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")

    def put(self, data: bytes) -> str:
        cid = raw_cid(data)
        response = httpx.post(
            self.api_url + "/api/v0/block/put",
            params={"cid-codec": "raw", "mhtype": "sha2-256", "pin": "true"},
            files={"file": ("block", data, "application/octet-stream")},
            timeout=20,
        )
        response.raise_for_status()
        if response.json().get("Key") != cid:
            raise ValueError("Kubo returned an unexpected CID")
        return cid

    def get(self, cid: str) -> bytes:
        if not CID_PATTERN.fullmatch(cid):
            raise ValueError("Invalid raw CID")
        response = httpx.post(self.api_url + "/api/v0/block/get", params={"arg": cid}, timeout=20)
        if response.status_code == 500 and "not found" in response.text.lower():
            raise FileNotFoundError(cid)
        response.raise_for_status()
        if raw_cid(response.content) != cid:
            raise ValueError("Content does not match CID")
        return response.content
