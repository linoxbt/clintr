import assert from 'node:assert/strict';
import { test } from 'node:test';
import { auth, challengeMessage, createSession, rawCid, runHistogram, runModel, verifyStored } from '../netlify/functions/api.mjs';
import { Wallet, verifyMessage } from 'ethers';

test('hosted verifier recomputes output and checks both content IDs', async () => {
  const source = Buffer.from('clintr verifier input');
  const result = runHistogram(source);
  const blobs = new Map([[rawCid(source), source], [rawCid(result), result]]);
  const store = { get: async (cid) => blobs.get(cid) ?? null };
  const { createHash } = await import('node:crypto');
  const job = { model_id: 'byte_histogram_v1', input_cid: rawCid(source), output_cid: rawCid(result), proof_hash: createHash('sha256').update(result).digest('hex') };
  assert.equal(await verifyStored(job, store), true);
  assert.equal(await verifyStored({ ...job, proof_hash: '0'.repeat(64) }, store), false);
  blobs.set(job.output_cid, Buffer.from('wrong'));
  assert.equal(await verifyStored(job, store), false);
  blobs.delete(job.output_cid);
  await assert.rejects(verifyStored(job, store), /Content unavailable/);
});

test('wallet challenge binds the address and hosted sessions reject tampering', async () => {
  process.env.CLINTR_AUTH_SECRET = 'unit-test-secret';
  const wallet = Wallet.createRandom();
  const message = challengeMessage('https://clintr-grid.netlify.app', wallet.address, 'nonce-123', 123456789);
  assert.equal(verifyMessage(message, await wallet.signMessage(message)), wallet.address);
  const { token } = createSession(wallet.address);
  const request = (value) => new Request('https://clintr-grid.netlify.app/jobs', { headers: { authorization: `Bearer ${value}` } });
  assert.equal(auth(request(token)), wallet.address);
  assert.equal(auth(request(token.slice(0, -1) + (token.endsWith('a') ? 'b' : 'a'))), null);
  assert.equal(auth(request('')), null);
  delete process.env.CLINTR_AUTH_SECRET;
});

test('hosted integer MLP matches the Python and contract reference bytes', () => {
  const source = Buffer.from('{"features":[12,-5,3,8,0,1,-2,4]}');
  assert.equal(runModel('edge_mlp_v1', source).toString(), '{"class":0,"scores":[86,-3]}');
  assert.throws(() => runModel('edge_mlp_v1', Buffer.from('{"features":[1,2]}')), /eight integer features/);
});
