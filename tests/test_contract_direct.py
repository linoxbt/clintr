"""GenLayer VM checks. Run with: uv run --extra contract-test pytest tests/test_contract_direct.py"""
import datetime
import hashlib
import sys

import pytest

pytest.importorskip("gltest")

from clintr.compute import MODEL, raw_cid, run

ATTO = 10**18
NOW = 1792500000


def warp(vm, timestamp):
    iso = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()
    vm.warp(iso)
    if "genlayer.gl" in sys.modules:
        sys.modules["genlayer.gl"].message_raw["datetime"] = iso


def start(direct_vm, direct_deploy, alice, bob, *, fund=True):
    vm = direct_vm
    warp(vm, NOW)
    vm.sender, vm.value = alice, 0
    contract = direct_deploy("contracts/clintr.py")
    vm.sender, vm.value = bob, 50 * ATTO
    contract.register_node()
    if fund:
        vm.sender, vm.value = alice, 50 * ATTO
        contract.fund_rewards()
    vm.sender, vm.value = alice, 3 * ATTO
    source = b"Clintr proof input"
    job_id = contract.create_job(MODEL, raw_cid(source), 60)
    vm.sender, vm.value = bob, 0
    contract.assign_node(job_id)
    return contract, vm, job_id, source


def test_contract_valid_result_pays_funded_bonus(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract, vm, job_id, source = start(direct_vm, direct_deploy, direct_alice, direct_bob)
    from genlayer import Address
    output = run(MODEL, source)
    cid = raw_cid(output)
    contract.submit_result(job_id, cid, hashlib.sha256(output).hexdigest())
    vm.mock_web(".*" + raw_cid(source), {"status": 200, "body": source})
    vm.mock_web(".*" + cid, {"status": 200, "body": output})
    assert contract.verify_and_reward(job_id) is True
    assert contract.get_job(job_id)["status"] == "completed"
    assert contract.get_node(Address(direct_bob))["stake"] == 50 * ATTO
    assert int(contract.reward_pool) == 0


def test_contract_rejects_wrong_computation(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract, vm, job_id, source = start(direct_vm, direct_deploy, direct_alice, direct_bob, fund=False)
    from genlayer import Address
    output = b"wrong answer"
    cid = raw_cid(output)
    contract.submit_result(job_id, cid, hashlib.sha256(output).hexdigest())
    vm.mock_web(".*" + raw_cid(source), {"status": 200, "body": source})
    vm.mock_web(".*" + cid, {"status": 200, "body": output})
    assert contract.verify_and_reward(job_id) is False
    assert contract.get_job(job_id)["status"] == "failed"
    assert contract.get_node(Address(direct_bob))["stake"] == 25 * ATTO
    assert contract.get_node(Address(direct_bob))["active"] is False


def test_contract_timeout_requeues_and_client_can_cancel(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract, vm, job_id, _ = start(direct_vm, direct_deploy, direct_alice, direct_bob)
    warp(vm, NOW + 61)
    vm.sender = direct_alice
    contract.check_timeout(job_id)
    assert contract.get_job(job_id)["status"] == "requeued"
    assert contract.get_job(job_id)["attempts"] == 1
    contract.cancel_requeued(job_id)
    assert contract.get_job(job_id)["status"] == "cancelled"
