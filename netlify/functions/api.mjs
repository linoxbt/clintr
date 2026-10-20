import { createHash, createHmac, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { getStore } from "@netlify/blobs";
import { getAddress, verifyMessage } from "ethers";

const MODEL = "byte_histogram_v1";
const MLP_MODEL = "edge_mlp_v1";
const MAX_INPUT = 65536;
const NODE = "clintr-netlify-demo";
const now = () => Math.floor(Date.now() / 1000);
const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json", "cache-control": "no-store", "x-content-type-options": "nosniff" },
});
const error = (detail, status = 400) => json({ detail }, status);
const digest = (bytes) => createHash("sha256").update(bytes).digest();
const hex = (bytes) => digest(bytes).toString("hex");
const b32 = (bytes) => {
  const abc = "abcdefghijklmnopqrstuvwxyz234567";
  let bits = 0, value = 0, out = "";
  for (const byte of bytes) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) { bits -= 5; out += abc[(value >>> bits) & 31]; }
  }
  if (bits) out += abc[(value << (5 - bits)) & 31];
  return out;
};
export const rawCid = (bytes) => "b" + b32(Buffer.concat([Buffer.from([1, 0x55, 0x12, 0x20]), digest(bytes)]));
export const runHistogram = (bytes) => {
  const bins = Array(16).fill(0);
  for (const byte of bytes) bins[byte >>> 4]++;
  return Buffer.from(JSON.stringify({ bins, bytes: bytes.length }));
};
export const runModel = (model, bytes) => {
  if (model === MODEL) return runHistogram(bytes);
  if (model !== MLP_MODEL) throw new Error("Unsupported model");
  let features;
  try { features = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)).features; }
  catch { throw new Error("MLP input must be JSON with eight integer features"); }
  if (!Array.isArray(features) || features.length !== 8 || features.some(value => !Number.isInteger(value) || value < -128 || value > 127)) {
    throw new Error("MLP input needs eight integer features from -128 to 127");
  }
  const hiddenWeights = [[2,-1,0,1,2,-2,1,0],[-1,2,1,0,-1,1,2,-2],[1,1,-2,2,0,-1,1,1],[0,-1,2,1,1,2,-1,1]];
  const hiddenBias = [1,-2,0,3];
  const outputWeights = [[2,-1,1,0],[-1,2,0,1]];
  const outputBias = [0,1];
  const hidden = hiddenWeights.map((row, index) => Math.max(0, row.reduce((sum, weight, i) => sum + weight * features[i], hiddenBias[index])));
  const scores = outputWeights.map((row, index) => row.reduce((sum, weight, i) => sum + weight * hidden[i], outputBias[index]));
  return Buffer.from(JSON.stringify({ class: scores[0] >= scores[1] ? 0 : 1, scores }));
};
const initial = () => ({
  nodes: [{ address: NODE, stake: 50, heartbeat: now(), active: true, assignments: 0 }],
  jobs: [], events: [],
});
const stateStore = () => getStore({ name: "clintr-demo-ledger", consistency: "strong" });
const dataStore = () => getStore({ name: "clintr-demo-blobs", consistency: "strong" });
const challengeStore = () => getStore({ name: "clintr-auth-challenges", consistency: "strong" });
const event = (state, kind, detail, extras = {}) => {
  state.events.unshift({ kind, detail, ...extras, created_at: now() });
  state.events.length = Math.min(state.events.length, 500);
};
async function snapshot(store) {
  const entry = await store.getWithMetadata("state", { type: "json", consistency: "strong" });
  return entry ? { data: entry.data, etag: entry.etag } : { data: initial(), etag: null };
}
async function update(change) {
  const store = stateStore();
  for (let i = 0; i < 8; i++) {
    const { data, etag } = await snapshot(store);
    const result = await change(data);
    const saved = await store.setJSON("state", data, etag ? { onlyIfMatch: etag } : { onlyIfNew: true });
    if (saved.modified) return result;
  }
  throw new Error("Concurrent update; please retry");
}
function secret() { return process.env.CLINTR_AUTH_SECRET || process.env.CLINTR_DEMO_TOKEN || ""; }
function mac(value) { return createHmac("sha256", secret()).update(value).digest("base64url"); }
function safeEqual(a, b) {
  return Buffer.byteLength(a) === Buffer.byteLength(b) && timingSafeEqual(Buffer.from(a), Buffer.from(b));
}
export function auth(request) {
  if (!secret()) return null;
  const token = (request.headers.get("authorization") || "").replace(/^Bearer /i, "");
  const [payload, signature, extra] = token.split(".");
  if (!payload || !signature || extra || !safeEqual(signature, mac(payload))) return null;
  try {
    const session = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    return session.exp > now() && session.exp <= now() + 3600 && getAddress(session.address) === session.address ? session.address : null;
  } catch { return null; }
}
export function challengeMessage(origin, address, nonce, expires) {
  return `Clintr sign in\nOrigin: ${origin}\nAddress: ${address}\nNonce: ${nonce}\nExpires: ${expires}`;
}
export function createSession(address) {
  const expires = now() + 3600;
  const payload = Buffer.from(JSON.stringify({ address, exp: expires })).toString("base64url");
  return { token: `${payload}.${mac(payload)}`, address, expires };
}
function visibleNodes(nodes) {
  return [{ address: NODE, stake: 0, heartbeat: null, active: true, simulated: true }];
}
function counts(jobs) {
  const out = {};
  for (const job of jobs) out[job.status] = (out[job.status] || 0) + 1;
  return out;
}
function integer(value, min, max) {
  return Number.isSafeInteger(Number(value)) && Number(value) >= min && Number(value) <= max;
}
export async function verifyStored(job, store = dataStore()) {
  const input = await store.get(job.input_cid, { type: "arrayBuffer", consistency: "strong" });
  const output = await store.get(job.output_cid, { type: "arrayBuffer", consistency: "strong" });
  if (!input || !output) throw new Error("Content unavailable; verification can be retried");
  const source = Buffer.from(input), result = Buffer.from(output);
  return rawCid(source) === job.input_cid && rawCid(result) === job.output_cid &&
    hex(result) === job.proof_hash && runModel(job.model_id, source).equals(result);
}
async function settleHosted(id) {
  const { data } = await snapshot(stateStore());
  const job = data.jobs.find((item) => item.id === id);
  if (!job) throw new Error("Job not found");
  if (job.status !== "pending_verification") throw new Error("Job is not awaiting verification");
  const valid = await verifyStored(job);
  await update((state) => {
    const current = state.jobs.find((item) => item.id === id);
    if (!current || current.status !== "pending_verification") throw new Error("Job is not awaiting verification");
    current.status = valid ? "completed" : "failed";
    current.latency_ms = Date.now() - (current.created_ms || current.created_at * 1000);
    event(state, valid ? "job_completed" : "job_failed", valid ? "Deterministic workload recomputed and matched" : "Output failed independent recomputation", { job_id: id, address: current.assigned_node });
  });
  return { valid, status: valid ? "completed" : "failed" };
}

export default async function handler(request) {
  try {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/$/, "") || "/";
    const parts = path.split("/").filter(Boolean);
    const method = request.method;
    if (path === "/health" && method === "GET") return json({ status: "ok", mode: "netlify_demo" });
    if (path === "/wallet/config" && method === "GET") return json({ projectId: process.env.CLINTR_REOWN_PROJECT_ID || "f0d6f8162be1beccf221b4e2f8bd7026" });
    if (path === "/auth/challenge" && method === "GET") {
      if (!secret()) return error("Wallet authentication is not configured", 503);
      let address;
      try { address = getAddress(url.searchParams.get("address") || ""); } catch { return error("Invalid wallet address"); }
      const nonce = randomBytes(16).toString("hex"), expires = now() + 300;
      await challengeStore().setJSON(address, { nonce, expires, origin: url.origin });
      return json({ message: challengeMessage(url.origin, address, nonce, expires), expires });
    }
    if (path === "/auth/session" && method === "POST") {
      if (!secret()) return error("Wallet authentication is not configured", 503);
      const body = await request.json();
      let address;
      try { address = getAddress(body.address || ""); } catch { return error("Invalid wallet address"); }
      const entry = await challengeStore().getWithMetadata(address, { type: "json", consistency: "strong" });
      if (!entry || entry.data.expires <= now() || entry.data.origin !== url.origin) return error("Challenge expired", 401);
      const message = challengeMessage(entry.data.origin, address, entry.data.nonce, entry.data.expires);
      try { if (verifyMessage(message, body.signature || "") !== address) return error("Invalid wallet signature", 401); }
      catch { return error("Invalid wallet signature", 401); }
      const used = await challengeStore().setJSON(address, { ...entry.data, expires: 0 }, { onlyIfMatch: entry.etag });
      if (!used.modified) return error("Challenge already used", 409);
      return json(createSession(address));
    }
    if (path === "/auth/check" && method === "POST") return auth(request) ? json({ valid: true, address: auth(request) }) : error("Wallet session expired", 401);
    const actor = auth(request);
    if (method !== "GET" && !actor) return error("Connect and sign with a wallet to continue", 401);

    if (path === "/stats" && method === "GET") {
      const { data } = await snapshot(stateStore());
      return json({ jobs: counts(data.jobs), nodes: visibleNodes(data.nodes) });
    }
    if (path === "/nodes" && method === "GET") {
      const { data } = await snapshot(stateStore());
      return json(visibleNodes(data.nodes));
    }
    if (path === "/events" && method === "GET") {
      const { data } = await snapshot(stateStore());
      return json(data.events.slice(0, Math.min(Number(url.searchParams.get("limit")) || 40, 100)));
    }
    if (path === "/jobs" && method === "GET") {
      const { data } = await snapshot(stateStore());
      const status = url.searchParams.get("status");
      return json(data.jobs.filter((job) => !status || job.status === status).slice(0, Math.min(Number(url.searchParams.get("limit")) || 40, 100)));
    }
    if (parts[0] === "jobs" && parts.length === 2 && method === "GET") {
      const { data } = await snapshot(stateStore());
      const job = data.jobs.find((item) => item.id === parts[1]);
      return job ? json(job) : error("Job not found", 404);
    }
    if (["blobs", "ipfs"].includes(parts[0]) && parts.length === 2 && method === "GET") {
      if (!/^b[a-z2-7]{58}$/.test(parts[1])) return error("Invalid CID", 400);
      const content = await dataStore().get(parts[1], { type: "arrayBuffer", consistency: "strong" });
      if (!content) return error("Content not found", 404);
      const bytes = Buffer.from(content);
      if (rawCid(bytes) !== parts[1]) return error("Stored content failed CID check", 503);
      return new Response(bytes, { headers: { "content-type": "application/octet-stream", "cache-control": "public, max-age=3600", "x-content-type-options": "nosniff", "content-disposition": "attachment" } });
    }
    if (path === "/blobs" && method === "POST") {
      const bytes = Buffer.from(await request.arrayBuffer());
      if (!bytes.length || bytes.length > MAX_INPUT) return error("Input must be 1..65536 bytes");
      const cid = rawCid(bytes);
      await dataStore().set(cid, bytes);
      return json({ cid });
    }
    if (path === "/nodes/register" && method === "POST") {
      return error("Hosted demo has no node staking; run the local worker or deploy the contract", 501);
    }
    if (parts[0] === "nodes" && parts.length === 3 && method === "POST") {
      return error("Hosted demo has no node heartbeat or stake withdrawal", 501);
    }
    if (path === "/jobs" && method === "POST") {
      const body = await request.json();
      if (![MODEL, MLP_MODEL].includes(body.model_id)) return error("Unsupported model");
      if (!integer(body.tip, 1, 1e9) || !integer(body.deadline_seconds ?? 30, 1, 3600)) return error("Invalid tip or deadline");
      const source = await dataStore().get(body.input_cid, { type: "arrayBuffer", consistency: "strong" });
      if (!source) return error("Input CID not found", 404);
      const input = Buffer.from(source);
      if (rawCid(input) !== body.input_cid) return error("Input CID mismatch");
      let output;
      try { output = runModel(body.model_id, input); }
      catch (cause) { return error(cause.message); }
      const outputCid = rawCid(output), proof = hex(output), id = randomUUID();
      await dataStore().set(outputCid, output);
      await update((data) => {
        if (data.jobs.length >= 1000) throw new Error("Hosted demo capacity reached");
        const job = { id, client: actor, model_id: body.model_id, input_cid: body.input_cid,
          tip: Number(body.tip), deadline: now() + Number(body.deadline_seconds ?? 30),
          assigned_node: NODE, status: "pending_verification", attempts: 0, output_cid: outputCid, proof_hash: proof,
          created_at: now(), created_ms: Date.now() };
        data.jobs.unshift(job);
        event(data, "job_created", "Job submitted", { job_id: id });
        event(data, "job_assigned", "Hosted demo worker accepted job", { job_id: id, address: NODE });
        event(data, "result_submitted", "Output and SHA256 proof stored", { job_id: id, address: NODE });
      });
      try {
        const verdict = await settleHosted(id);
        return json({ job_id: id, required_tip: Number(body.tip), status: verdict.status });
      } catch (cause) {
        console.error("Clintr hosted verification pending", cause);
        return json({ job_id: id, required_tip: Number(body.tip), status: "pending_verification" }, 202);
      }
    }
    if (parts[0] === "jobs" && parts.length === 3 && parts[2] === "verify" && method === "POST") {
      return json(await settleHosted(parts[1]));
    }
    if (path === "/metrics" && method === "GET") {
      const { data } = await snapshot(stateStore());
      const completed = data.jobs.filter(job => job.status === "completed").length;
      const failed = data.jobs.filter(job => job.status === "failed").length;
      const measured = data.jobs.filter(job => Number.isFinite(job.latency_ms));
      const lines = Object.entries(counts(data.jobs)).map(([status, count]) => `clintr_jobs_status{status="${status}"} ${count}\n`);
      lines.push(`clintr_jobs_success ${completed}\nclintr_jobs_failed ${failed}\nclintr_hosted_job_latency_ms_sum ${measured.reduce((sum, job) => sum + job.latency_ms, 0)}\nclintr_hosted_job_latency_ms_count ${measured.length}\nclintr_node_up{address="${NODE}"} 0\nclintr_node_stake{address="${NODE}"} 0\n`);
      return new Response(lines.join(""), { headers: { "content-type": "text/plain; charset=utf-8", "x-content-type-options": "nosniff" } });
    }
    return error("Route not found", 404);
  } catch (cause) {
    console.error("Clintr demo API error", cause);
    if (cause.message === "Concurrent update; please retry") return error(cause.message, 409);
    if (cause.message === "Hosted demo capacity reached") return error(cause.message, 429);
    if (cause.message === "Content unavailable; verification can be retried") return error(cause.message, 503);
    if (cause.message === "Job not found") return error(cause.message, 404);
    if (cause.message === "Job is not awaiting verification") return error(cause.message, 409);
    return error("Internal server error", 500);
  }
}

export const config = {
  path: ["/health", "/wallet/config", "/auth/challenge", "/auth/session", "/auth/check", "/stats", "/nodes", "/nodes/*", "/events", "/jobs", "/jobs/*", "/blobs", "/blobs/*", "/ipfs/*", "/metrics"],
  rateLimit: { windowLimit: 120, windowSize: 60, aggregateBy: ["ip", "domain"] },
};
