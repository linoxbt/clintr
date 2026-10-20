import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { Wallet } from 'ethers';
import { rawCid, runHistogram, runModel } from '../netlify/functions/api.mjs';

const base = process.env.CLINTR_SITE_URL || 'https://clintr-grid.netlify.app';
const wallet = Wallet.createRandom();
async function expectStatus(response, allowed = [200]) {
  if (!allowed.includes(response.status)) throw new Error(`${response.status}: ${await response.text()}`);
  return response;
}
const challengeResponse = await fetch(`${base}/auth/challenge?address=${wallet.address}`);
await expectStatus(challengeResponse);
const challenge = await challengeResponse.json();
const signature = await wallet.signMessage(challenge.message);
const sessionResponse = await fetch(`${base}/auth/session`, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ address: wallet.address, signature }),
});
await expectStatus(sessionResponse);
const { token } = await sessionResponse.json();
const replayResponse = await fetch(`${base}/auth/session`, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ address: wallet.address, signature }),
});
assert.equal(replayResponse.status, 401);
const legacyResponse = await fetch(`${base}/auth/check`, { method: 'POST', headers: { 'x-demo-token': 'retired-token' } });
assert.equal(legacyResponse.status, 401);
const headers = { authorization: `Bearer ${token}` };
const source = Buffer.from('Clintr signed-wallet smoke test');
const uploadResponse = await fetch(`${base}/blobs`, { method: 'POST', headers, body: source });
await expectStatus(uploadResponse);
const { cid } = await uploadResponse.json();
assert.equal(cid, rawCid(source));
const jobResponse = await fetch(`${base}/jobs`, {
  method: 'POST', headers: { ...headers, 'content-type': 'application/json' },
  body: JSON.stringify({ model_id: 'byte_histogram_v1', input_cid: cid, tip: 3, deadline_seconds: 30 }),
});
await expectStatus(jobResponse, [200, 202]);
const { job_id } = await jobResponse.json();
let job = await fetch(`${base}/jobs/${job_id}`).then(response => response.json());
if (job.status === 'pending_verification') {
  const verified = await fetch(`${base}/jobs/${job_id}/verify`, { method: 'POST', headers });
  await expectStatus(verified);
  job = await fetch(`${base}/jobs/${job_id}`).then(response => response.json());
}
assert.equal(job.client, wallet.address);
assert.equal(job.status, 'completed');
const outputResponse = await fetch(`${base}/blobs/${job.output_cid}`);
assert.equal(outputResponse.status, 200);
const output = Buffer.from(await outputResponse.arrayBuffer());
assert.deepEqual(output, runHistogram(source));
assert.deepEqual(Buffer.from(await (await expectStatus(await fetch(`${base}/ipfs/${job.output_cid}`))).arrayBuffer()), output);
assert.equal(job.proof_hash, createHash('sha256').update(output).digest('hex'));
console.log(JSON.stringify({ job_id, status: job.status, client: wallet.address, verified: true }));
const mlpSource = Buffer.from('{"features":[12,-5,3,8,0,1,-2,4]}');
const mlpUpload = await expectStatus(await fetch(`${base}/blobs`, { method: 'POST', headers, body: mlpSource }));
const mlpCid = (await mlpUpload.json()).cid;
const mlpCreated = await expectStatus(await fetch(`${base}/jobs`, {
  method: 'POST', headers: { ...headers, 'content-type': 'application/json' },
  body: JSON.stringify({ model_id: 'edge_mlp_v1', input_cid: mlpCid, tip: 3, deadline_seconds: 30 }),
}), [200, 202]);
const mlpId = (await mlpCreated.json()).job_id;
let mlpJob = await fetch(`${base}/jobs/${mlpId}`).then(response => response.json());
if (mlpJob.status === 'pending_verification') {
  await expectStatus(await fetch(`${base}/jobs/${mlpId}/verify`, { method: 'POST', headers }));
  mlpJob = await fetch(`${base}/jobs/${mlpId}`).then(response => response.json());
}
assert.equal(mlpJob.status, 'completed');
const mlpOutput = Buffer.from(await (await expectStatus(await fetch(`${base}/blobs/${mlpJob.output_cid}`))).arrayBuffer());
assert.deepEqual(mlpOutput, runModel('edge_mlp_v1', mlpSource));
assert.deepEqual(Buffer.from(await (await expectStatus(await fetch(`${base}/ipfs/${mlpJob.input_cid}`))).arrayBuffer()), mlpSource);
console.log(JSON.stringify({ job_id: mlpId, status: mlpJob.status, model: 'edge_mlp_v1', verified: true }));
