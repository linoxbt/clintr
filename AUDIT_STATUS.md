# Clintr audit status — 2026-10-20

This tracks the original full-app requirements against verified behavior. A passing demo test does not make the production grid complete.

## Verified fixes

| Area | Current status | Evidence |
| --- | --- | --- |
| Hosted wallet authorization | Fixed for demo writes; one-time signed challenge, one-hour session, client bound to wallet | `tests/hosted_api.test.mjs`, live `scripts/smoke_netlify.mjs` |
| Hosted proof state | Fixed for supported deterministic models; output is recomputed before completion | Node tests and live smoke for histogram and MLP |
| PostgreSQL settlement races | Fixed; row locks and conditional transitions keep one payment per job | `scripts/check_pg_concurrency.py`, eight competing settlements |
| Deadline and pending-proof handling | Fixed for local demo; bounded retries and refunds; contract reserves reward bonus and has timeout escape methods | Python and direct GenVM tests |
| Worker and monitoring | Fixed for local stack; worker Prometheus metrics and maintenance proof retry | Compose smoke and Prometheus targets |
| CI and deploy reproducibility | Fixed; pinned GenVM artifact with SHA-256 check; Netlify build configuration | GitHub Actions CI run `39485348968` passed |
| Hosted CID reads | Fixed; stored bytes are checked against the requested CID | Live Netlify smoke `/blobs/{cid}` and `/ipfs/{cid}` |
| Local IPFS replication | Three Cluster peers pin every accepted raw CID on three Kubo nodes; reads fail over when the first Kubo node stops | Compose smoke completed histogram and MLP jobs; `ipfs-cluster-ctl status` showed `PINNED` on cluster0, cluster1, and cluster2; secondary-node read returned the exact output |

## Open production requirements

| Severity | Requirement / finding | Current limitation | Required closure |
| --- | --- | --- | --- |
| Critical | Real GEN staking, slashing, reward payout | Contract is not deployed on Studionet; hosted API uses no contract transactions. Dedicated deployer `0xaacfb80e036b9d8f2117dad053469565878896dd` returned `0x0` from the Studionet balance RPC on 2026-10-20. | Fund dedicated deployer, deploy and fund reward pool, connect wallet/API to contract, execute live success and failure transactions |
| High | Distributed edge execution | Netlify runs jobs in one Function; local Docker worker is not publicly deployed | Deploy persistent regional workers with authenticated assignment and result submission |
| High | Durable decentralized storage | Compose now has three IPFS Cluster peers and three Kubo replicas on one machine, verified with both workload outputs. Hosted Netlify Blobs remain a centralized CID mirror. | Host persistent Cluster peers across independent failure domains, move the hosted upload/read path to them, and expose a validator-reachable HTTPS gateway |
| High | Production identity and transport | Local demo uses a shared token and HTTP loopback; no node mTLS or wallet-bound node registration | Implement wallet-signed node operations and TLS/mTLS on deployed services |
| High | Automatic on-chain liveness | Contract timeout and prune methods require a transaction caller | Deploy a funded keeper and verify missed heartbeat/deadline behavior live |
| High | SLA and scale | No 100 ms geographic RTT or 500-client load evidence; hosted state is capped and serialized | Deploy regional infrastructure and run measured load/latency tests |
| High | Arbitrary AI proof | Only histogram and fixed-weight integer MLP have exact recomputation; hash alone cannot prove arbitrary AI inference | Specify and implement a verifiable model/proof policy for each supported workload |
| Medium | Hosted preview auth | Netlify preview contexts have not been given a wallet-session secret | Configure a preview-specific `CLINTR_AUTH_SECRET` and smoke-test preview |
| Medium | Browser wallet flow | API signature path is live-tested with a disposable wallet; actual Reown modal signing was not automated in a wallet-enabled browser | Run a browser test with a real wallet provider |

## Production verdict

**Not production-ready.** The hosted demo and local stack are functional for their stated scopes. The open Critical and High items require live chain funds and production infrastructure; they are not treated as passing requirements.
