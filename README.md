# Clintr

Clintr is a runnable edge compute **app in local demo mode** plus a GenLayer contract candidate. The browser app lets you submit jobs, follow proofs and settlements, inspect nodes, review activity, and view health. A separate edge worker registers, heartbeats, and processes jobs automatically. The API handles byte-exact independent verification, slashing, timeouts, and Prometheus/Grafana monitoring.

The public landing page is `/`. The workspace has five separate pages: `/app/overview`, `/app/jobs`, `/app/nodes`, `/app/activity`, and `/app/settings`. The SVG brand assets are `web/logo-mark.svg`, `web/logo-dark.svg`, and `web/logo-light.svg`.

## Hosted demo

The Netlify site at [clintr-grid.netlify.app](https://clintr-grid.netlify.app) serves the five pages and a small function-backed demo API. It stores uploaded bytes and job records in Netlify Blobs, recomputes deterministic byte histogram or fixed-weight integer neural inference, and exposes the output CID and proof hash. `/ipfs/{cid}` serves exact CID-checked bytes as a gateway-compatible **demo mirror**; Netlify Blobs are not IPFS pinning. The Netlify function acts as the demo processor; no GEN is staked or transferred there. The hosted demo does not use the Python edge worker, PostgreSQL, Kubo IPFS, or the GenLayer contract. Use Docker Compose below for those services locally.

The landing page and workspace have a Reown AppKit **Connect wallet** button for GenLayer Studionet. The default public project ID is shared with the DataTruth app on this machine; set `CLINTR_REOWN_PROJECT_ID` in Netlify or your local environment to use a dedicated Clintr project. In [Reown Dashboard](https://dashboard.reown.com/), allow `https://clintr-grid.netlify.app` as an origin if domain restrictions are enabled. On the hosted demo, a wallet message signature authorizes writes for one hour and binds new jobs to that wallet address. Wallet authentication does not send GEN or submit transactions; the Studionet contract is still undeployed.

Netlify wallet sessions are signed with `CLINTR_AUTH_SECRET`, falling back to the existing `CLINTR_DEMO_TOKEN` server secret. Neither secret is sent to the browser. Local Compose still uses `CLINTR_DEMO_TOKEN` for demo writes. To regenerate the wallet bundle and static documents after changing `web/`, run `npm ci`, `npm run build:wallet`, then `uv run python scripts/export_site.py` before pushing or deploying. Deploy with `netlify deploy --prod --dir public --functions netlify/functions --no-build`. Run `node scripts/smoke_netlify.mjs` to test wallet-signature login, upload, job creation, and proof on the live site with a disposable wallet.

The supplied specification's `genlayer.lockbond`, `callvalidator`, and validator-registry flow do not match the current GenLayer contract API. This project uses payable methods for escrow and GenLayer's [Equivalence Principle](https://docs.genlayer.com/developers/intelligent-contracts/equivalence-principle) for independent verification. The contract passes `genvm-lint check`, but has **not been deployed or live-tested**.

## Run the full local app

With Docker installed:

```bash
export CLINTR_DEMO_TOKEN=choose-a-long-local-secret
python3 scripts/setup_cluster_secret.py
docker compose up --build
```

The setup script stores one 64-character secret in the ignored `.env` file for all three Cluster peers. Do not commit that file.

Open **http://127.0.0.1:8000**. Open **Settings → Local demo access**, enter the same token, then submit a job from the Overview or Jobs page. The Compose worker automatically accepts and verifies it. Prometheus is at `http://127.0.0.1:9090`; Grafana is at `http://127.0.0.1:3000` (Grafana's first-run credentials are managed by Grafana). Docker Compose includes PostgreSQL, three Kubo nodes coordinated by three IPFS Cluster peers, the API, the worker, maintenance, Prometheus, and Grafana. Uploads return only after Cluster reports three pinned replicas. Set `CLINTR_POSTGRES_PASSWORD` to override the local-only database password.

For a lightweight install without Docker:

```bash
uv sync --extra dev
export CLINTR_DEMO_TOKEN=local-secret
uv run uvicorn clintr.api:app --host 127.0.0.1 --port 8000
```

In a second shell, run the automatic worker:

```bash
CLINTR_DEMO_TOKEN=local-secret uv run python -m clintr.worker_daemon
```

Run `uv run python -m clintr.maintenance` in a third shell for automatic timeout and heartbeat maintenance. The standalone mode uses the local content-addressed blob store; Docker Compose uses Kubo IPFS. You can use the browser app in both modes.

For a manual API call, register a node and upload input:

```bash
curl -X POST http://127.0.0.1:8000/nodes/register -H 'X-Demo-Token: local-secret' -H 'Content-Type: application/json' -d '{"address":"node-1","stake":50}'
curl -X POST http://127.0.0.1:8000/blobs -H 'X-Demo-Token: local-secret' --data-binary 'hello'
```

Use the returned `cid` to create a job:

```bash
curl -X POST http://127.0.0.1:8000/jobs -H 'X-Demo-Token: local-secret' -H 'Content-Type: application/json' -d '{"client":"alice","model_id":"byte_histogram_v1","input_cid":"<CID>","tip":3,"deadline_seconds":30}'
uv run python -m clintr.worker <JOB_ID> --node node-1 --token local-secret
```

Compose uses Kubo's private RPC API; it is not published to the host.

## Boundaries

- The browser app is a **local simulation**. Compose persists jobs and nodes in PostgreSQL; standalone mode uses SQLite. Neither ledger locks, transfers, or slashes real GEN. The shared demo token is for localhost use only, and Docker publishes the API on loopback. Production needs wallet-based authentication, TLS, and a contract-backed API adapter.
- `contracts/clintr.py` uses real payable stake and tip escrow. A funded reward pool reserves a stake-sized **bonus** when a node accepts a job, then pays it upon success; the node's original stake remains locked until withdrawal. Without pre-funding, assignment is rejected. Half of a dishonest node's stake goes into the pool; the client's tip is refunded. Requeued jobs retain the tip until completion or cancellation. After three missed deadline windows, the contract cancels and refunds automatically when a keeper calls `check_timeout`.
- GenLayer contract methods do not run on their own when a deadline passes. A deployed grid needs a keeper to submit `check_timeout(job_id)` and `prune_node(address)` transactions. The Compose maintenance process covers only the local demo.
- The supported models are `byte_histogram_v1` and `edge_mlp_v1`. The MLP is fixed-weight integer neural inference over eight features from -128 to 127, supplied as `{"features":[12,-5,3,8,0,1,-2,4]}`. The validator fetches both input and output from an HTTPS IPFS gateway, checks both exact raw CIDs and the output SHA-256, and recomputes the full deterministic transform. A hash alone does **not** prove ResNet or other arbitrary AI inference was correct. Larger workloads need an independently reproducible model, a cryptographic proof system, or a clearly stated weaker verification policy.
- Compose pins CIDv1 raw SHA-256 blocks through a three-peer IPFS Cluster and verifies all three pin statuses before accepting an upload. These peers share one host, so they do not survive host failure. The standalone mode uses a local file store with the same CIDs. The hosted Netlify demo still uses Netlify Blobs, so it does not yet use this cluster. A production deployment needs Cluster peers across independent hosts, persistent volumes, and a stable HTTPS gateway reachable by GenLayer validators. [IPFS Cluster API reference](https://ipfscluster.io/documentation/reference/api/).
- A 100 ms client-to-edge network round trip is an infrastructure target. No global latency or 500-client load result is claimed here.

## Validation and deployment

```bash
uv run --extra dev --extra contract-test pytest -q
uv run --extra contract-test genvm-lint check contracts/clintr.py
```

To deploy, follow GenLayer's [CLI deployment guide](https://docs.genlayer.com/developers/intelligent-contracts/deploying/cli-deployment): select a network, configure a funded account and fee profile, then run `genlayer deploy --contract contracts/clintr.py --args https://YOUR-GATEWAY/ipfs/`. For a hosted demo contract, `https://clintr-grid.netlify.app/ipfs/` can serve the Netlify-stored raw CIDs, but it is a centralized mirror rather than an IPFS pinning service. Fund `fund_rewards` before assigning successful jobs. Deployment, validator execution, fee behavior, and real GEN payouts require live-network validation; they are not asserted by this repository.
