"""Content addressed local store for the runnable demo; raw CIDs also work with Kubo."""
from pathlib import Path
import os
import tempfile
import time
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
            descriptor, pending = tempfile.mkstemp(prefix=".clintr-", dir=self.root)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(pending, target)
            finally:
                if os.path.exists(pending):
                    os.unlink(pending)
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


class ClusterStore:
    """Add raw blocks through IPFS Cluster and require full replication."""

    def __init__(self, cluster_api: str, kubo_apis: list[str], replicas: int = 3):
        self.cluster_api = cluster_api.rstrip("/")
        if not kubo_apis:
            raise ValueError("At least one Kubo read endpoint is required")
        self.kubos = [KuboStore(api) for api in kubo_apis]
        self.replicas = replicas

    def put(self, data: bytes) -> str:
        expected = raw_cid(data)
        response = httpx.post(
            self.cluster_api + "/add",
            params={
                "cid-version": 1,
                "raw-leaves": "true",
                "replication-min": self.replicas,
                "replication-max": self.replicas,
                "wait": "true",
                "wait-timeout": "30s",
                "stream-channels": "false",
            },
            files={"file": ("block", data, "application/octet-stream")},
            timeout=45,
        )
        response.raise_for_status()
        entries = response.json()
        if len(entries) != 1 or entries[0].get("cid") != expected:
            raise ValueError("IPFS Cluster returned an unexpected CID")
        for attempt in range(20):
            status = httpx.get(self.cluster_api + "/pins/" + expected, timeout=10)
            status.raise_for_status()
            peers = status.json().get("peer_map", {})
            pinned = sum(peer.get("status") == "pinned" for peer in peers.values())
            if pinned >= self.replicas:
                return expected
            if attempt < 19:
                time.sleep(0.5)
        raise RuntimeError(f"IPFS Cluster pinned only {pinned}/{self.replicas} replicas")

    def get(self, cid: str) -> bytes:
        if not CID_PATTERN.fullmatch(cid):
            raise ValueError("Invalid raw CID")
        last_error = None
        for kubo in self.kubos:
            try:
                return kubo.get(cid)
            except (FileNotFoundError, ValueError, httpx.HTTPError) as error:
                last_error = error
        raise last_error or FileNotFoundError(cid)


def configured_store():
    cluster = os.environ.get("CLINTR_CLUSTER_API")
    kubo = os.environ.get("CLINTR_IPFS_API")
    if cluster:
        if not kubo:
            raise ValueError("CLINTR_IPFS_API is required with CLINTR_CLUSTER_API")
        read_apis = [api.strip() for api in os.environ.get("CLINTR_IPFS_READ_APIS", kubo).split(",") if api.strip()]
        return ClusterStore(cluster, read_apis)
    return KuboStore(kubo) if kubo else BlobStore(os.environ.get("CLINTR_BLOBS", "/tmp/clintr-blobs"))
