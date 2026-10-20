import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { getStore } from "@netlify/blobs";

const MODEL = "byte_histogram_v1";
const MAX_INPUT = 65536;
const NODE = "clintr-netlify-demo";
const now = () => Math.floor(Date.now() / 1000);
const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json", "cache-control": "no-store" },
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
const initial = () => ({
  nodes: [{ address: NODE, stake: 50, heartbeat: now(), active: true, assignments: 0 }],
  jobs: [], events: [],
});
const stateStore = () => getStore({ name: "clintr-demo-ledger", consistency: "strong" });
const dataStore = () => getStore({ name: "clintr-demo-blobs", consistency: "strong" });
const event = (state, kind, detail, extras = {}) => state.events.unshift({ kind, detail, ...extras, created_at: now() });
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
function auth(request) {
  const expected = process.env.CLINTR_DEMO_TOKEN || "";
  const actual = request.headers.get("x-demo-token") || "";
  if (!expected || Buffer.byteLength(actual) !== Buffer.byteLength(expected)) return false;
  return timingSafeEqual(Buffer.from(actual), Buffer.from(expected));
}
function visibleNodes(nodes) {
  return nodes.map((node) => node.address === NODE && node.active ? { ...node, heartbeat: now() } : node);
}
function counts(jobs) {
  const out = {};
  for (const job of jobs) out[job.status] = (out[job.status] || 0) + 1;
  return out;
}
function integer(value, min, max) {
  return Number.isSafeInteger(Number(value)) && Number(value) >= min && Number(value) <= max;
}

export default async function handler(request) {
  try {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/$/, "") || "/";
    const parts = path.split("/").filter(Boolean);
    const method = request.method;
    if (path === "/health" && method === "GET") return json({ status: "ok", mode: "netlify_demo" });
    if (path === "/wallet/config" && method === "GET") return json({ projectId: process.env.CLINTR_REOWN_PROJECT_ID || "" });
    if (path === "/auth/check" && method === "POST") return auth(request) ? json({ valid: true }) : error("Invalid demo access token", 401);
    if (method !== "GET" && !auth(request)) return error("Set X-Demo-Token for demo mutations", 401);

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
    if (parts[0] === "blobs" && parts.length === 2 && method === "GET") {
      const content = await dataStore().get(parts[1], { type: "arrayBuffer", consistency: "strong" });
      return content ? new Response(content, { headers: { "content-type": "application/octet-stream", "cache-control": "no-store" } }) : error("Content not found", 404);
    }
    if (path === "/blobs" && method === "POST") {
      const bytes = Buffer.from(await request.arrayBuffer());
      if (!bytes.length || bytes.length > MAX_INPUT) return error("Input must be 1..65536 bytes");
      const cid = rawCid(bytes);
      await dataStore().set(cid, bytes);
      return json({ cid });
    }
    if (path === "/nodes/register" && method === "POST") {
      const body = await request.json();
      if (typeof body.address !== "string" || !body.address.trim() || body.address.length > 100 || !integer(body.stake, 50, 1e9)) return error("Address and stake of at least 50 are required");
      const address = body.address.trim();
      await update((data) => {
        if (data.nodes.some((node) => node.address === address)) throw new Error("Node already registered");
        data.nodes.unshift({ address, stake: Number(body.stake), heartbeat: now(), active: true, assignments: 0 });
        event(data, "node_registered", "Demo stake locked", { address });
      });
      return json({ address, status: "registered" });
    }
    if (parts[0] === "nodes" && parts.length === 3 && method === "POST") {
      const address = decodeURIComponent(parts[1]), action = parts[2];
      const result = await update((data) => {
        const node = data.nodes.find((item) => item.address === address);
        if (!node) throw new Error("Node not found");
        if (address === NODE && action === "withdraw") throw new Error("Hosted demo node cannot withdraw");
        if (action === "heartbeat") {
          if (!node.active) throw new Error("Node inactive");
          node.heartbeat = now();
          return { status: "ok" };
        }
        if (action === "withdraw") {
          if (node.assignments) throw new Error("Node has assignments");
          const amount = node.stake;
          node.stake = 0; node.active = false;
          event(data, "node_withdrew", "Demo stake withdrawn", { address });
          return { amount };
        }
        throw new Error("Unknown node action");
      });
      return json(result);
    }
    if (path === "/jobs" && method === "POST") {
      const body = await request.json();
      if (typeof body.client !== "string" || !body.client.trim() || body.client.length > 100) return error("Client name required");
      if (body.model_id !== MODEL) return error("Unsupported model");
      if (!integer(body.tip, 1, 1e9) || !integer(body.deadline_seconds ?? 30, 1, 3600)) return error("Invalid tip or deadline");
      const source = await dataStore().get(body.input_cid, { type: "arrayBuffer", consistency: "strong" });
      if (!source) return error("Input CID not found", 404);
      const input = Buffer.from(source);
      if (rawCid(input) !== body.input_cid) return error("Input CID mismatch");
      const output = runHistogram(input);
      const outputCid = rawCid(output), proof = hex(output), id = randomUUID();
      await dataStore().set(outputCid, output);
      await update((data) => {
        const job = { id, client: body.client.trim(), model_id: MODEL, input_cid: body.input_cid,
          tip: Number(body.tip), deadline: now() + Number(body.deadline_seconds ?? 30),
          assigned_node: NODE, status: "completed", attempts: 0, output_cid: outputCid, proof_hash: proof,
          created_at: now() };
        data.jobs.unshift(job);
        event(data, "job_created", "Job submitted", { job_id: id });
        event(data, "job_assigned", "Hosted demo worker accepted job", { job_id: id, address: NODE });
        event(data, "result_submitted", "Output and SHA256 proof stored", { job_id: id, address: NODE });
        event(data, "job_completed", "Byte histogram independently recomputed", { job_id: id, address: NODE });
      });
      return json({ job_id: id, required_tip: Number(body.tip) });
    }
    if (parts[0] === "jobs" && parts.length === 3 && parts[2] === "verify" && method === "POST") {
      const { data } = await snapshot(stateStore());
      const job = data.jobs.find((item) => item.id === parts[1]);
      if (!job) return error("Job not found", 404);
      const input = await dataStore().get(job.input_cid, { type: "arrayBuffer", consistency: "strong" });
      const output = await dataStore().get(job.output_cid, { type: "arrayBuffer", consistency: "strong" });
      const valid = Boolean(input && output && rawCid(Buffer.from(input)) === job.input_cid && rawCid(Buffer.from(output)) === job.output_cid &&
        hex(Buffer.from(output)) === job.proof_hash && runHistogram(Buffer.from(input)).equals(Buffer.from(output)));
      return json({ valid, status: job.status });
    }
    if (path === "/metrics" && method === "GET") {
      const { data } = await snapshot(stateStore());
      return new Response(Object.entries(counts(data.jobs)).map(([status, count]) => `clintr_jobs_status{status="${status}"} ${count}\n`).join(""), { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    return error("Route not found", 404);
  } catch (cause) {
    console.error("Clintr demo API error", cause);
    return error(cause.message === "Concurrent update; please retry" ? cause.message : cause.message || "Internal error",
      cause.message === "Concurrent update; please retry" ? 409 : 400);
  }
}

export const config = {
  path: ["/health", "/wallet/config", "/auth/check", "/stats", "/nodes", "/nodes/*", "/events", "/jobs", "/jobs/*", "/blobs", "/blobs/*", "/metrics"],
};
