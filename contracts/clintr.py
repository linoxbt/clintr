# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""Clintr on-chain escrow for a byte-exact demonstration workload.

Deploy only after reviewing the intended gateway, reward funding and chain fees.
No claim is made that a checksum proves arbitrary AI inference correct.
"""
from genlayer import *
import base64
import datetime
import hashlib
import json
import re

ATTO = 10**18
MIN_STAKE = 50 * ATTO
MODEL = "byte_histogram_v1"
MLP_MODEL = "edge_mlp_v1"
MAX_INPUT = 65536
MAX_OUTPUT = 4096
HIDDEN_WEIGHTS = ((2, -1, 0, 1, 2, -2, 1, 0), (-1, 2, 1, 0, -1, 1, 2, -2), (1, 1, -2, 2, 0, -1, 1, 1), (0, -1, 2, 1, 1, 2, -1, 1))
HIDDEN_BIAS = (1, -2, 0, 3)
OUTPUT_WEIGHTS = ((2, -1, 1, 0), (-1, 2, 0, 1))
OUTPUT_BIAS = (0, 1)
MAX_ATTEMPTS = 3


def _require(ok: bool, message: str):
    if not ok:
        raise gl.vm.UserError("[EXPECTED] " + message)


def _now() -> int:
    return int(datetime.datetime.fromisoformat(gl.message_raw["datetime"].replace("Z", "+00:00")).timestamp())


def _cid(data: bytes) -> str:
    return "b" + base64.b32encode(b"\x01\x55\x12\x20" + hashlib.sha256(data).digest()).decode().lower().rstrip("=")


def _run(model_id: str, data: bytes) -> bytes:
    if model_id == MLP_MODEL:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return b""
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list) or len(features) != 8 or any(type(value) is not int or not -128 <= value <= 127 for value in features):
            return b""
        hidden = [max(0, sum(weight * value for weight, value in zip(row, features)) + bias) for row, bias in zip(HIDDEN_WEIGHTS, HIDDEN_BIAS)]
        scores = [sum(weight * value for weight, value in zip(row, hidden)) + bias for row, bias in zip(OUTPUT_WEIGHTS, OUTPUT_BIAS)]
        return json.dumps({"class": 0 if scores[0] >= scores[1] else 1, "scores": scores}, sort_keys=True, separators=(",", ":")).encode()
    bins = [0] * 16
    for item in data:
        bins[item >> 4] += 1
    return json.dumps({"bins": bins, "bytes": len(data)}, sort_keys=True, separators=(",", ":")).encode()


@gl.evm.contract_interface
class _Recipient:
    class View:
        pass

    class Write:
        pass


class Clintr(gl.Contract):
    next_job_id: u256
    nodes: TreeMap[Address, str]
    jobs: TreeMap[u256, str]
    reward_pool: u256
    gateway: str

    def __init__(self, gateway: str):
        _require(re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]+)?/ipfs/", gateway) is not None, "HTTPS IPFS gateway required")
        self.gateway = gateway
        self.next_job_id = u256(1)
        self.reward_pool = u256(0)

    def _node(self, address: Address) -> dict:
        _require(address in self.nodes, "Node not registered")
        return json.loads(self.nodes[address])

    def _job(self, job_id: int) -> dict:
        key = u256(job_id)
        _require(key in self.jobs, "Job not found")
        return json.loads(self.jobs[key])

    def _save_node(self, address: Address, node: dict):
        self.nodes[address] = json.dumps(node, sort_keys=True)

    def _save_job(self, job_id: int, job: dict):
        self.jobs[u256(job_id)] = json.dumps(job, sort_keys=True)

    @gl.public.write.payable
    def register_node(self):
        addr = gl.message.sender_address
        old = self.nodes.get(addr)
        if old:
            previous = json.loads(old)
            _require(not previous["active"] and previous["stake"] == 0 and previous["assignments"] == 0, "Existing stake must be withdrawn first")
        _require(int(gl.message.value) >= MIN_STAKE, "Send at least 50 GEN as stake")
        self._save_node(addr, {"stake": int(gl.message.value), "heartbeat": _now(), "active": True, "assignments": 0})

    @gl.public.write
    def heartbeat(self):
        addr = gl.message.sender_address
        node = self._node(addr)
        _require(node["active"], "Inactive node")
        node["heartbeat"] = _now()
        self._save_node(addr, node)

    @gl.public.write
    def prune_node(self, address: Address):
        node = self._node(address)
        _require(node["active"] and _now() > node["heartbeat"] + 90, "Node is not stale")
        slash = node["stake"] // 2
        node["stake"] -= slash
        node["active"] = False
        self.reward_pool = u256(int(self.reward_pool) + slash)
        self._save_node(address, node)

    @gl.public.write.payable
    def fund_rewards(self):
        _require(int(gl.message.value) > 0, "Funding required")
        self.reward_pool = u256(int(self.reward_pool) + int(gl.message.value))

    @gl.public.write.payable
    def create_job(self, model_id: str, input_cid: str, deadline_seconds: int) -> int:
        _require(model_id in (MODEL, MLP_MODEL), "Unsupported model")
        _require(re.fullmatch(r"b[a-z2-7]{58}", input_cid) is not None, "Raw CIDv1 required")
        _require(1 <= deadline_seconds <= 3600, "Deadline must be 1..3600 seconds")
        _require(int(gl.message.value) > 0, "Fund the tip")
        job_id = int(self.next_job_id)
        self.next_job_id = u256(job_id + 1)
        self._save_job(job_id, {"client": str(gl.message.sender_address), "model_id": model_id, "input_cid": input_cid, "tip": int(gl.message.value), "deadline": _now() + deadline_seconds, "assigned_node": "", "status": "open", "attempts": 0, "reserved_bonus": 0, "output_cid": "", "proof_hash": ""})
        return job_id

    @gl.public.write
    def assign_node(self, job_id: int):
        addr = gl.message.sender_address
        node = self._node(addr)
        job = self._job(job_id)
        _require(node["active"] and _now() <= node["heartbeat"] + 90, "Node unavailable")
        _require(job["status"] in ("open", "requeued") and _now() < job["deadline"], "Job unavailable")
        bonus = node["stake"]
        _require(int(self.reward_pool) >= bonus, "Reward pool cannot cover this job")
        self.reward_pool = u256(int(self.reward_pool) - bonus)
        job["reserved_bonus"] = bonus
        job["assigned_node"] = str(addr)
        job["status"] = "assigned"
        node["assignments"] += 1
        self._save_node(addr, node)
        self._save_job(job_id, job)

    @gl.public.write
    def submit_result(self, job_id: int, output_cid: str, proof_hash: str):
        job = self._job(job_id)
        _require(str(gl.message.sender_address) == job["assigned_node"], "Not assigned node")
        _require(job["status"] == "assigned" and _now() <= job["deadline"], "Job expired")
        _require(re.fullmatch(r"b[a-z2-7]{58}", output_cid) is not None, "Raw CIDv1 required")
        _require(re.fullmatch(r"[0-9a-f]{64}", proof_hash) is not None, "SHA256 proof required")
        job["output_cid"] = output_cid
        job["proof_hash"] = proof_hash
        job["status"] = "pending_verification"
        self._save_job(job_id, job)

    @gl.public.write
    def verify_and_reward(self, job_id: int) -> bool:
        job = self._job(job_id)
        _require(job["status"] == "pending_verification", "No result to verify")
        addr = Address(job["assigned_node"])
        node = self._node(addr)
        gateway = self.gateway
        input_cid = job["input_cid"]
        output_cid = job["output_cid"]
        proof_hash = job["proof_hash"]

        def independently_verify():
            source = gl.nondet.web.get(gateway + input_cid)
            result = gl.nondet.web.get(gateway + output_cid)
            if source.status != 200 or result.status != 200:
                raise gl.vm.UserError("[EXTERNAL] IPFS content unavailable")
            input_bytes = source.body
            output_bytes = result.body
            if input_bytes is None or output_bytes is None:
                raise gl.vm.UserError("[EXTERNAL] IPFS content unavailable")
            if len(input_bytes) > MAX_INPUT or len(output_bytes) > MAX_OUTPUT:
                return False
            return (_cid(input_bytes) == input_cid and _cid(output_bytes) == output_cid
                    and hashlib.sha256(output_bytes).hexdigest() == proof_hash
                    and _run(job["model_id"], input_bytes) == output_bytes)

        valid = gl.eq_principle.strict_eq(independently_verify)
        node["assignments"] -= 1
        bonus = job["reserved_bonus"]
        _require(bonus > 0, "Job bonus was not reserved")
        job["reserved_bonus"] = 0
        if valid:
            job["status"] = "completed"
            self._save_node(addr, node)
            self._save_job(job_id, job)
            _Recipient(addr).emit_transfer(value=u256(job["tip"] + bonus))
        else:
            slash = node["stake"] // 2
            node["stake"] -= slash
            if node["stake"] < MIN_STAKE:
                node["active"] = False
            self.reward_pool = u256(int(self.reward_pool) + bonus + slash)
            job["status"] = "failed"
            self._save_node(addr, node)
            self._save_job(job_id, job)
            _Recipient(Address(job["client"])).emit_transfer(value=u256(job["tip"]))
        return valid

    @gl.public.write
    def check_timeout(self, job_id: int):
        job = self._job(job_id)
        _require(job["status"] in ("open", "assigned", "requeued") and _now() > job["deadline"], "Job is not overdue")
        if job["assigned_node"]:
            addr = Address(job["assigned_node"])
            node = self._node(addr)
            node["assignments"] -= 1
            self._save_node(addr, node)
            self.reward_pool = u256(int(self.reward_pool) + job["reserved_bonus"])
            job["reserved_bonus"] = 0
        job["assigned_node"] = ""
        job["attempts"] += 1
        if job["attempts"] >= MAX_ATTEMPTS:
            job["status"] = "cancelled"
            self._save_job(job_id, job)
            _Recipient(Address(job["client"])).emit_transfer(value=u256(job["tip"]))
            return
        job["status"] = "requeued"
        job["deadline"] = _now() + 30
        self._save_job(job_id, job)

    @gl.public.write
    def cancel_requeued(self, job_id: int):
        job = self._job(job_id)
        _require(str(gl.message.sender_address) == job["client"], "Only client may cancel")
        _require(job["status"] == "requeued", "Job is not requeued")
        job["status"] = "cancelled"
        self._save_job(job_id, job)
        _Recipient(Address(job["client"])).emit_transfer(value=u256(job["tip"]))

    @gl.public.write
    def cancel_unverifiable(self, job_id: int):
        """Escape a permanently unavailable IPFS proof after a one-hour grace period."""
        job = self._job(job_id)
        _require(str(gl.message.sender_address) == job["client"], "Only client may cancel")
        _require(job["status"] == "pending_verification" and _now() > job["deadline"] + 3600, "Verification grace period active")
        addr = Address(job["assigned_node"])
        node = self._node(addr)
        node["assignments"] -= 1
        self.reward_pool = u256(int(self.reward_pool) + job["reserved_bonus"])
        job["reserved_bonus"] = 0
        job["status"] = "cancelled"
        self._save_node(addr, node)
        self._save_job(job_id, job)
        _Recipient(Address(job["client"])).emit_transfer(value=u256(job["tip"]))

    @gl.public.write
    def withdraw_stake(self):
        addr = gl.message.sender_address
        node = self._node(addr)
        _require(node["stake"] > 0 and node["assignments"] == 0, "Stake locked by active jobs or already withdrawn")
        node["active"] = False
        amount = node["stake"]
        node["stake"] = 0
        self._save_node(addr, node)
        _Recipient(addr).emit_transfer(value=u256(amount))

    @gl.public.view
    def get_job(self, job_id: int) -> dict:
        return self._job(job_id)

    @gl.public.view
    def get_node(self, address: Address) -> dict:
        return self._node(address)
