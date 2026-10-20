# GenLayer Portal project submission — Clintr

**Draft for Projects → Project, prepared 20 October 2026.** This copy describes the deployed demo and the checked-in contract candidate. Clintr has **no deployed Studionet contract, real GEN settlement, or validator transaction evidence yet**. Do not represent the demo's simulated GEN balances as on-chain funds. Review the current [audit status](AUDIT_STATUS.md) before submitting.

## 01 · Identity

- **Project name:** Clintr
- **Logo:** Upload [`submission-logo.png`](submission-logo.png) (512 × 512 PNG, 42 KB), exported from the existing Clintr mark.
- **Primary tag:** Choose the Portal's closest available Compute / Infrastructure category. If absent, choose AI / Intelligent Contracts. Use the exact label shown in the Portal; available choices may differ.
- **Additional tags:** Edge computing and verifiable computation, if offered.

## 02 · One-liner — 180-character field

> Clintr is an edge compute grid demo that runs deterministic workloads, publishes content-addressed outputs, and checks results before settlement.

## 03 · Description — 1,000-character field

> Clintr explores how an edge compute grid can make node work inspectable. Its multi-page app lets a client submit a byte histogram or fixed-weight integer neural inference job, then inspect the input CID, output CID, SHA-256 proof, verification result, node activity, and metrics. The live Netlify demo uses wallet-signature login and independently recomputes both supported workloads before marking a job complete. A Docker Compose stack runs a separate worker with heartbeats, PostgreSQL job records, a Kubo IPFS node, timeout maintenance, Prometheus, and Grafana. The repository also contains a GenLayer Intelligent Contract candidate for payable node stakes, client tips, reward funding, deterministic verification through an HTTPS gateway, slashing, and refunds. That contract passes direct GenVM tests and lint, but it is not deployed on Studionet or connected to the hosted app. Hosted GEN balances are simulated; the live demo does not transfer GEN or use a decentralized worker fleet.

## 04 · Demo video

Leave blank until a direct video of the deployed flow is available. Do not use a landing-page animation as evidence of live contract execution.

## 05 · How-to — enter these steps in order

| Heading | Instruction |
| --- | --- |
| 1. Open Clintr | Visit the website and select **Open app**. The Overview, Jobs, Nodes, Activity, and Settings views are separate pages. |
| 2. Connect a wallet | Select **Connect wallet**, connect a wallet through Reown, and sign the short message when submitting a hosted job. The signature starts a one-hour demo session; it does not send a transaction. |
| 3. Submit a workload | Select **New job**. For a byte histogram, upload a small file or paste text. For Edge MLP, paste `{"features":[12,-5,3,8,0,1,-2,4]}`. Set a simulated GEN tip and deadline, then submit. Inputs and outputs are public by CID; use non-sensitive data. |
| 4. Inspect verification | Open the created job in **Jobs**. Check its completed status, model, output CID, and SHA-256 proof. Download the output and compare it with the result expected for the chosen deterministic model. |
| 5. Inspect scope | Open **Nodes** and **Settings**. The hosted processor is identified as a demo Function with no staked GEN or node heartbeats. Review the repository for the separate Docker worker and GenLayer contract candidate. |

## 06 · Review verification — 500-character field

> Create a hosted job with `{"features":[12,-5,3,8,0,1,-2,4]}` and model `edge_mlp_v1`; the output should be `{"class":0,"scores":[86,-3]}`. The job page exposes its raw CID and SHA-256 proof; `/ipfs/{cid}` returns CID-checked bytes from Netlify Blobs. This is a centralized demo mirror, not IPFS pinning. The contract source and direct GenVM tests are in GitHub, but no Studionet deployment or real GEN payout is claimed.

**Contract link:** Leave blank. No verified deployment address exists.

## 07 · Project links

- **Website:** https://clintr-grid.netlify.app
- **GitHub repository:** https://github.com/linoxbt/clintr
- **Contract source:** https://github.com/linoxbt/clintr/blob/main/contracts/clintr.py
- **Audit status and known limits:** https://github.com/linoxbt/clintr/blob/main/AUDIT_STATUS.md
- **Local deployment instructions:** https://github.com/linoxbt/clintr#run-the-full-local-app

## Evidence & supporting information — add individually

1. **GitHub repository:** https://github.com/linoxbt/clintr
2. **Live multi-page demo:** https://clintr-grid.netlify.app/app/overview/
3. **Contract implementation and direct tests:** https://github.com/linoxbt/clintr/blob/main/contracts/clintr.py and https://github.com/linoxbt/clintr/blob/main/tests/test_contract_direct.py
4. **Passing CI checks:** https://github.com/linoxbt/clintr/actions/runs/39485782102
5. **Audit and outstanding production requirements:** https://github.com/linoxbt/clintr/blob/main/AUDIT_STATUS.md

### What GenLayer contributes, and what is still pending

The checked-in contract uses GenLayer's payable contract methods and Equivalence Principle to bind node stake, client tip, CIDs, proof hash, verification, reward, slash, and refund state. The direct GenVM test suite exercises success, invalid output, timeout, reward reservation, and the integer MLP. The live Netlify site currently verifies the same deterministic work off-chain without invoking that contract. A Portal submission that requires a live Intelligent Contract must wait for a funded deployment, a validator-reachable replicated gateway, and a transaction-backed end-to-end run.
