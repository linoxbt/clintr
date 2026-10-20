"""GenLayer VM checks. Run with: uv run --extra contract-test pytest tests/test_contract_direct.py"""
import datetime
import hashlib
import sys

import pytest

pytest.importorskip("gltest")

from clintr.compute import MODEL, MLP_MODEL, raw_cid, run

ATTO = 10**18
NOW = 1792500000


def warp(vm, timestamp):
    iso = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()
    vm.warp(iso)
    if "genlayer.gl" in sys.modules:
        sys.modules["genlayer.gl"].message_raw["datetime"] = iso


def start(direct_vm, direct_deploy, alice, bob, *, fund=True, assign=True):
    vm = direct_vm
    warp(vm, NOW)
    vm.sender, vm.value = alice, 0
    contract = direct_deploy("contracts/clintr.py", "https://gateway.example.com/ipfs/")
    vm.sender, vm.value = bob, 50 * ATTO
    contract.register_node()
    if fund:
        vm.sender, vm.value = alice, 50 * ATTO
        contract.fund_rewards()
    vm.sender, vm.value = alice, 3 * ATTO
    source = b"Clintr proof input"
    job_id = contract.create_job(MODEL, raw_cid(source), 60)
    vm.sender, vm.value = bob, 0
    if assign:
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
    assert contract.get_job(job_id)["reserved_bonus"] == 0


def test_contract_rejects_wrong_computation(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract, vm, job_id, source = start(direct_vm, direct_deploy, direct_alice, direct_bob)
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
    assert int(contract.reward_pool) == 75 * ATTO


def test_contract_timeout_requeues_and_client_can_cancel(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract, vm, job_id, _ = start(direct_vm, direct_deploy, direct_alice, direct_bob)
    warp(vm, NOW + 61)
    vm.sender = direct_alice
    contract.check_timeout(job_id)
    assert contract.get_job(job_id)["status"] == "requeued"
    assert contract.get_job(job_id)["attempts"] == 1
    contract.cancel_requeued(job_id)
    assert contract.get_job(job_id)["status"] == "cancelled"


def test_contract_reserves_bonus_before_assignment_and_releases_on_timeout(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract, vm, job_id, _ = start(direct_vm, direct_deploy, direct_alice, direct_bob, fund=False, assign=False)
    with pytest.raises(Exception, match="Reward pool cannot cover"):
        contract.assign_node(job_id)
    assert contract.get_job(job_id)["status"] == "open"
    vm.sender, vm.value = direct_alice, 50 * ATTO
    contract.fund_rewards()
    vm.sender, vm.value = direct_bob, 0
    contract.assign_node(job_id)
    assert int(contract.reward_pool) == 0
    assert contract.get_job(job_id)["reserved_bonus"] == 50 * ATTO
    warp(vm, NOW + 61)
    contract.check_timeout(job_id)
    assert int(contract.reward_pool) == 50 * ATTO
    assert contract.get_job(job_id)["reserved_bonus"] == 0


def test_contract_verifies_integer_mlp_result(direct_vm, direct_deploy, direct_alice, direct_bob):
    vm = direct_vm
    warp(vm, NOW)
    vm.sender, vm.value = direct_alice, 0
    contract = direct_deploy("contracts/clintr.py", "https://gateway.example.com/ipfs/")
    vm.sender, vm.value = direct_bob, 50 * ATTO
    contract.register_node()
    vm.sender, vm.value = direct_alice, 50 * ATTO
    contract.fund_rewards()
    source = b'{"features":[12,-5,3,8,0,1,-2,4]}'
    vm.value = 3 * ATTO
    job_id = contract.create_job(MLP_MODEL, raw_cid(source), 60)
    vm.sender, vm.value = direct_bob, 0
    contract.assign_node(job_id)
    output = run(MLP_MODEL, source)
    assert output == b'{"class":0,"scores":[86,-3]}'
    cid = raw_cid(output)
    contract.submit_result(job_id, cid, hashlib.sha256(output).hexdigest())
    vm.mock_web(".*" + raw_cid(source), {"status": 200, "body": source})
    vm.mock_web(".*" + cid, {"status": 200, "body": output})
    assert contract.verify_and_reward(job_id) is True
    assert contract.get_job(job_id)["status"] == "completed"
