(() => {
  const state = {view: document.body.dataset.view || 'overview', jobs: [], nodes: [], events: [], counts: {}, search: '', filter: '', token: sessionStorage.getItem('clintr_token') || '', synced: null, error: '', output: null};
  const main = document.getElementById('main');
  const overlay = document.getElementById('overlay-root');
  const toastRoot = document.getElementById('toast-root');
  const icons = {
    arrow: '<svg viewBox="0 0 24 24"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path d="M12 4v16M4 12h16"/></svg>',
    cloud: '<svg viewBox="0 0 24 24"><path d="M7 18H6a4 4 0 0 1-.2-8A7 7 0 0 1 19 9a4.5 4.5 0 0 1-1 9h-3M12 12v9m-4-4 4 4 4-4"/></svg>',
    shield: '<svg viewBox="0 0 24 24"><path d="M12 2 20 5v6c0 5-3.6 8.5-8 11-4.4-2.5-8-6-8-11V5zM9 12l2 2 4-4"/></svg>',
    pulse: '<svg viewBox="0 0 24 24"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg>',
    server: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="8" rx="2"/><rect x="3" y="13" width="18" height="8" rx="2"/><path d="M7 7h.01M7 17h.01M11 7h6M11 17h6"/></svg>',
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M4 12l5 5L20 6"/></svg>',
    clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
  };
  function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function short(value, left = 8, right = 5) { value = String(value || '—'); return value.length > left + right + 2 ? value.slice(0,left) + '…' + value.slice(-right) : value; }
  function statusName(status) { return String(status || 'unknown').replaceAll('_',' '); }
  function live(node) { return Boolean(node.active) && Number(node.heartbeat) >= Math.floor(Date.now()/1000)-90; }
  function ago(epoch) { if (!epoch) return '—'; const diff = Math.max(0, Math.floor(Date.now()/1000)-Number(epoch)); return diff < 60 ? `${diff}s ago` : diff < 3600 ? `${Math.floor(diff/60)}m ago` : diff < 86400 ? `${Math.floor(diff/3600)}h ago` : new Date(epoch*1000).toLocaleDateString(); }
  function date(epoch) { return epoch ? new Date(Number(epoch)*1000).toLocaleString() : '—'; }
  function pill(status) { return `<span class="status-pill status-${esc(status)}">${esc(statusName(status))}</span>`; }
  function toast(message, bad = false) { const item = document.createElement('div'); item.className = 'toast' + (bad ? ' bad' : ''); item.textContent = message; toastRoot.append(item); setTimeout(() => item.remove(), 3900); }
  async function api(path, options = {}) {
    const headers = {...(options.headers || {})};
    if (state.token) headers['X-Demo-Token'] = state.token;
    if (options.json !== undefined) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.json); }
    const response = await fetch(path, {...options, headers});
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try { const data = await response.json(); message = typeof data.detail === 'string' ? data.detail : message; } catch {}
      throw new Error(message);
    }
    return options.binary ? response.blob() : response.json();
  }
  async function validateToken(token) { const response = await fetch('/auth/check',{method:'POST',headers:{'X-Demo-Token':token}}); if(!response.ok) throw new Error('That demo access token was not accepted'); }
  function needToken() { if (state.token) return true; openModal('access'); toast('Connect your local demo access first', true); return false; }
  async function loadData(force = false) {
    try {
      const [stats, jobs, events] = await Promise.all([api('/stats'), api('/jobs?limit=100'), api('/events?limit=80')]);
      state.counts = stats.jobs || {}; state.nodes = stats.nodes || []; state.jobs = jobs; state.events = events; state.synced = new Date(); state.error = '';
      if (force || !document.activeElement?.matches('input,textarea,select')) render();
      document.getElementById('footer-sync').textContent = `Synced ${state.synced.toLocaleTimeString()}`;
      document.getElementById('nav-job-count').textContent = String(Object.values(state.counts).reduce((sum, count) => sum + Number(count), 0));
    } catch (error) { state.error = error.message; if (force || !state.jobs.length) render(); }
  }
  function heading(kicker, title, subtitle, actions = '') { return `<div class="page-heading"><div><p class="eyebrow">${kicker}</p><h1>${title}</h1><p>${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`; }
  function stat(label, value, foot, icon, color='') { return `<div class="stat-card"><div class="stat-top"><span>${label}</span><span class="stat-icon ${color}">${icons[icon]}</span></div><div class="stat-value">${value}</div><div class="stat-foot">${foot}</div></div>`; }
  function jobRows(jobs, compact = false) {
    if (!jobs.length) return `<tr><td colspan="${compact ? 4 : 7}">${empty('No jobs yet', 'Submit a job to see it move through the compute grid.')}</td></tr>`;
    return jobs.map(job => `<tr data-job="${esc(job.id)}" data-search="${esc(`${job.id} ${job.client} ${job.model_id} ${job.status} ${job.assigned_node || ''}`.toLowerCase())}"><td><span class="job-id">${esc(short(job.id,8,4))}</span></td><td>${esc(job.model_id === 'byte_histogram_v1' ? 'Byte histogram' : job.model_id)}</td>${compact ? '' : `<td class="mono">${esc(short(job.input_cid,10,5))}</td><td>${esc(job.assigned_node ? short(job.assigned_node,12,4) : 'Unassigned')}</td>`}<td>${pill(job.status)}</td><td><strong>${esc(job.tip)} GEN</strong></td>${compact ? '' : `<td class="tiny-label">${esc(date(job.deadline))}</td>`}</tr>`).join('');
  }
  function empty(title, description) { return `<div class="empty-state"><div class="empty-icon">◇</div><strong>${title}</strong><p>${description}</p></div>`; }
  function recentBars() {
    const now = Math.floor(Date.now()/1000), buckets = Array(7).fill(0);
    state.events.filter(e => e.kind === 'job_created').forEach(e => { const age = now - e.created_at, index = 6 - Math.floor(age/600); if (index >= 0 && index < 7) buckets[index]++; });
    const max = Math.max(...buckets,1);
    return `<div class="mini-bars">${buckets.map((count, i) => `<div class="mini-bar-wrap"><div class="mini-bar" style="height:${Math.max(6,Math.round(count/max*91))}px" title="${count} jobs"></div><small>${i===6?'now':`${(6-i)*10}m`}</small></div>`).join('')}</div>`;
  }
  function overview() {
    const total = Object.values(state.counts).reduce((sum, count) => sum + Number(count), 0), completed = Number(state.counts.completed || 0), failed = Number(state.counts.failed || 0), decided = completed + failed;
    const rate = decided ? Math.round(completed/decided*100) : 0, active = state.nodes.filter(live).length;
    const stake = state.nodes.reduce((sum,n) => sum + Number(n.stake),0);
    return `${heading('GRID OVERVIEW','Compute you can verify.','A live look at the jobs, nodes, and proofs moving through your grid.',`<button class="secondary-btn" data-action="refresh">↻ &nbsp; Refresh</button><button class="primary-btn" data-action="new-job">${icons.plus} New job</button>`)}
      <section class="hero"><div class="hero-content"><p class="hero-kicker">✦ &nbsp; THE EDGE COMPUTE GRID</p><h1>Proof in. Confidence out.</h1><p>Send a job to an available edge node. Clintr records the output, checks it against the input, and settles the result.</p><button class="primary-btn btn-dark" data-action="new-job">Submit a compute job ${icons.arrow}</button></div><div class="hero-graphic"><div class="grid-orb"><i class="orb-dot one"></i><i class="orb-dot two"></i><i class="orb-dot three"></i></div><span class="orbit-label">DISTRIBUTED · VERIFIED</span></div></section>
      <div class="stats-grid">${stat('TOTAL JOBS',total,'Across all states','cloud')}${stat('SUCCESS RATE',`${rate}%`,`${decided} verified jobs`,'shield','blue')}${stat('ACTIVE NODES',active,`${state.nodes.length} registered`,'server','purple')}${stat('LOCKED STAKE',`${stake} GEN`,'Simulated in this environment','pulse','amber')}</div>
      <div class="content-grid"><section class="panel"><div class="panel-header"><div><h2>Recent jobs</h2><p>Latest work submitted to the grid</p></div><a class="text-link" href="/app/jobs">View all →</a></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Job ID</th><th>Workload</th><th>Status</th><th>Tip</th></tr></thead><tbody>${jobRows(state.jobs.slice(0,5),true)}</tbody></table></div></section>
      <section class="panel"><div class="panel-header"><div><h2>Grid health</h2><p>Services and node availability</p></div><span class="health-status">● LIVE</span></div><div class="panel-body"><div class="health-row"><span class="health-icon">${icons.pulse}</span><span><strong>API Gateway</strong><small>Accepting requests</small></span><span class="health-status">ONLINE</span></div><div class="health-row"><span class="health-icon">${icons.shield}</span><span><strong>Verification</strong><small>Deterministic recomputation</small></span><span class="health-status">READY</span></div><div class="health-row"><span class="health-icon">${icons.server}</span><span><strong>Edge nodes</strong><small>${active} of ${state.nodes.length} currently responsive</small></span><span class="health-status ${active ? '' : 'warn'}">${active ? 'HEALTHY' : 'IDLE'}</span></div></div></section></div>
      <div class="content-grid"><section class="panel"><div class="panel-header"><div><h2>How a job moves</h2><p>One continuous, verifiable flow</p></div></div><div class="pipeline"><div class="pipeline-step"><span class="step-number">1</span><span>Submit input</span></div><span class="pipeline-arrow">→</span><div class="pipeline-step"><span class="step-number">2</span><span>Edge compute</span></div><span class="pipeline-arrow">→</span><div class="pipeline-step"><span class="step-number">3</span><span>Pin output</span></div><span class="pipeline-arrow">→</span><div class="pipeline-step"><span class="step-number">4</span><span>Verify & settle</span></div></div></section><section class="panel"><div class="panel-header"><div><h2>Jobs submitted</h2><p>Past 70 minutes</p></div></div><div class="panel-body">${recentBars()}</div></section></div>`;
  }
  function jobsView() {
    let jobs = state.jobs.filter(job => !state.filter || job.status === state.filter);
    if (state.search) jobs = jobs.filter(job => `${job.id} ${job.client} ${job.model_id} ${job.status} ${job.assigned_node || ''}`.toLowerCase().includes(state.search));
    return `${heading('COMPUTE JOBS','Every job, accounted for.','Track work from submission through verification and settlement.',`<button class="primary-btn" data-action="new-job">${icons.plus} New job</button>`)}
      <div class="page-tools"><div class="search-wrap">${icons.search}<input class="search-input" id="job-search" placeholder="Search by job, client, node…" value="${esc(state.search)}" aria-label="Search jobs"></div><select id="job-filter" class="select-input" aria-label="Filter jobs"><option value="">All statuses</option>${['open','assigned','pending_verification','completed','failed','requeued','cancelled'].map(s=>`<option value="${s}" ${state.filter===s?'selected':''}>${statusName(s)}</option>`).join('')}</select></div>
      <section class="panel view-table"><div class="table-wrap"><table class="data-table"><thead><tr><th>Job ID</th><th>Workload</th><th>Input CID</th><th>Edge node</th><th>Status</th><th>Tip</th><th>Deadline</th></tr></thead><tbody>${jobRows(jobs)}</tbody></table></div></section><p class="small-note">Showing ${jobs.length} of ${state.jobs.length} recent jobs. Select a row for proof and settlement details.</p>`;
  }
  function nodesView() {
    const active = state.nodes.filter(live).length;
    return `${heading('EDGE NETWORK','Nodes at the ready.','Registered machines, live heartbeats, and staked collateral.',`<button class="primary-btn" data-action="register-node">${icons.plus} Register node</button>`)}
      <div class="stats-grid">${stat('REGISTERED',state.nodes.length,'Total nodes','server')}${stat('RESPONSIVE',active,'Heartbeat within 90 seconds','pulse','blue')}${stat('STAKE LOCKED',`${state.nodes.reduce((s,n)=>s+Number(n.stake),0)} GEN`,'Simulated stake','shield','purple')}${stat('MINIMUM STAKE','50 GEN','Required for registration','clock','amber')}</div>
      ${state.nodes.length ? `<div class="node-grid">${state.nodes.map(n=>`<article class="node-card"><div class="node-head"><span class="node-avatar">${icons.server}</span><span><strong>${esc(short(n.address,22,8))}</strong><small>Registered edge node</small></span><span class="status-pill ${live(n)?'status-completed':'status-failed'}">${live(n)?'Online':'Offline'}</span></div><div class="node-stats"><div><small>LOCKED STAKE</small><strong>${esc(n.stake)} GEN</strong></div><div><small>LAST HEARTBEAT</small><strong>${esc(ago(n.heartbeat))}</strong></div></div><div class="node-actions"><button class="small-btn" data-action="heartbeat" data-node="${esc(n.address)}">Send heartbeat</button><button class="small-btn danger-btn" data-action="withdraw" data-node="${esc(n.address)}">Withdraw stake</button></div></article>`).join('')}</div>` : `<section class="panel">${empty('No nodes registered','Start the worker service or register a node to accept jobs.')}</section>`}
      <div class="alert-box" style="margin-top:20px">The Docker worker registers itself and heartbeats automatically. A node that misses three 30-second heartbeats becomes inactive and loses half its simulated stake.</div>`;
  }
  function activityView() {
    const symbols = {job_created:'+',job_assigned:'↗',result_submitted:'◇',job_completed:'✓',job_failed:'!',job_requeued:'↺',job_cancelled:'×',node_registered:'●',node_pruned:'!',node_withdrew:'↘'};
    const labels = {job_created:'Job submitted',job_assigned:'Job assigned to node',result_submitted:'Proof submitted',job_completed:'Job verified',job_failed:'Invalid proof',job_requeued:'Job requeued',job_cancelled:'Job cancelled',node_registered:'Node registered',node_pruned:'Node pruned',node_withdrew:'Stake withdrawn'};
    return `${heading('EVENT STREAM','The grid, in motion.','A chronological record of work and node changes.',`<button class="secondary-btn" data-action="refresh">↻ &nbsp; Refresh</button>`)}<section class="panel">${state.events.length ? `<div class="activity-list">${state.events.map(e=>`<div class="event-row"><span class="event-symbol ${/failed|pruned/.test(e.kind)?'bad':/requeued|cancelled/.test(e.kind)?'warn':''}">${esc(symbols[e.kind] || '·')}</span><div><strong>${esc(labels[e.kind] || e.kind)}</strong><p>${esc(e.detail)}${e.job_id ? ` · <span class="mono">${esc(short(e.job_id,8,4))}</span>` : ''}${e.address ? ` · ${esc(short(e.address,12,5))}` : ''}</p></div><time title="${esc(date(e.created_at))}">${esc(ago(e.created_at))}</time></div>`).join('')}</div>` : empty('Nothing to report yet','Create a job or register a node to start the activity stream.')}</section>`;
  }
  function settingsView() {
    return `${heading('CONFIGURATION','A clear view of the setup.','Manage local access and inspect this deployment’s boundaries.')}
      <div class="settings-grid"><section class="panel setting-card"><h2>Local demo access</h2><p>Mutating API calls require the demo token configured in the server environment. It stays in this browser tab for the session.</p><label class="setting-label" for="settings-token">Access token</label><div class="setting-row"><input id="settings-token" class="form-input" type="password" autocomplete="off" placeholder="Enter CLINTR_DEMO_TOKEN" value="${esc(state.token)}"><button class="primary-btn" data-action="save-token">Save</button></div><p class="small-note">${state.token ? 'A token is connected for this tab.' : 'You can browse public data without a token.'}</p></section>
      <section class="panel setting-card"><h2>Grid configuration</h2><p>Current capabilities of this deployment.</p><div class="tech-list"><div><span>Environment</span><strong>Local demo</strong></div><div><span>Verifiable model</span><strong>Byte histogram v1</strong></div><div><span>Input limit</span><strong>64 KiB</strong></div><div><span>Minimum stake</span><strong>50 simulated GEN</strong></div><div><span>Heartbeat window</span><strong>90 seconds</strong></div></div></section>
      <section class="panel setting-card"><h2>Verification model</h2><p>The verifier retrieves input and output, checks their content IDs and the proof hash, then reruns the deterministic workload. A matching hash alone is not sufficient evidence that arbitrary AI inference was correct.</p><div class="callout">The contract candidate uses GenLayer consensus for this exact workload. This browser app currently operates against the local demo ledger.</div></section>
      <section class="panel setting-card"><h2>Observability</h2><p>Metrics are exported in Prometheus format. Docker Compose also provisions a Grafana dashboard for job success, verification latency, node health, and stake.</p><div class="setting-row"><a class="secondary-btn" href="/metrics" target="_blank" rel="noopener noreferrer">Open metrics ↗</a><a class="secondary-btn" href="http://localhost:3000" target="_blank" rel="noopener noreferrer">Open Grafana ↗</a></div></section></div>`;
  }
  function render() {
    const view = ['overview','jobs','nodes','activity','settings'].includes(state.view) ? state.view : 'overview';
    const titles = {overview:'Overview',jobs:'Jobs',nodes:'Nodes',activity:'Activity',settings:'Settings'};
    document.getElementById('crumb').textContent = titles[view];
    document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.getAttribute('href') === '/app/' + view));
    const button = document.getElementById('connection-button'); button.classList.toggle('connected', Boolean(state.token));
    document.getElementById('connection-label').textContent = state.token ? 'Access connected' : 'Connect access';
    if (state.error && !state.synced) { main.innerHTML = `<div class="view-error"><h2>Clintr API is unavailable</h2><p>${esc(state.error)}</p><button class="primary-btn" data-action="refresh">Try again</button></div>`; return; }
    main.innerHTML = ({overview,jobs:jobsView,nodes:nodesView,activity:activityView,settings:settingsView})[view]();
  }
  function navigate(view, message) { if (message) sessionStorage.setItem('clintr_flash', message); location.assign('/app/' + view); }
  function modalShell(title, desc, body) { return `<div class="overlay" data-action="close-overlay"><div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="modal-header"><div><h2>${title}</h2><p>${desc}</p></div><button class="close-button" aria-label="Close dialog" data-action="close-overlay">×</button></div><div class="modal-body">${body}</div></div></div>`; }
  function openModal(kind) {
    state.output = null;
    if (kind === 'access') overlay.innerHTML = modalShell('Connect local access','Use the CLINTR_DEMO_TOKEN set on the API server.',`<form id="access-form"><div class="field"><label for="access-token">Demo access token</label><input class="form-input" id="access-token" type="password" autocomplete="off" required placeholder="Enter your token" value="${esc(state.token)}"></div><div class="form-footer"><small>The token is stored only in this browser tab.</small><button class="primary-btn" type="submit">Connect</button></div></form>`);
    if (kind === 'new-job') { if (!needToken()) return; overlay.innerHTML = modalShell('Submit a compute job','The worker picks up open jobs automatically.',`<form id="job-form"><div class="form-grid"><div class="field"><label for="job-client">Client name</label><input class="form-input" id="job-client" name="client" value="client-demo" maxlength="100" required></div><div class="field"><label for="job-model">Workload</label><select id="job-model" class="form-input"><option value="byte_histogram_v1">Byte histogram v1</option></select></div></div><div class="field"><label for="job-file">Input data</label><label class="file-drop" for="job-file">${icons.cloud}<strong>Choose a file to process</strong><small>Up to 64 KiB · any file type</small><input id="job-file" type="file"></label><div class="or-divider">OR PASTE TEXT</div><textarea class="form-textarea" id="job-text" placeholder="Enter input text for the deterministic workload…"></textarea></div><div class="form-grid"><div class="field"><label for="job-tip">Tip · simulated GEN</label><input class="form-input" id="job-tip" type="number" min="1" step="1" value="3" required></div><div class="field"><label for="job-deadline">Deadline · seconds</label><input class="form-input" id="job-deadline" type="number" min="1" max="3600" step="1" value="30" required></div></div><div class="form-footer"><small>Input and output are stored by content ID. The result is independently recomputed.</small><button class="primary-btn" type="submit">Submit job ${icons.arrow}</button></div></form>`); }
    if (kind === 'register-node') { if (!needToken()) return; overlay.innerHTML = modalShell('Register an edge node','Lock simulated stake to join the local grid.',`<form id="node-form"><div class="field"><label for="node-address">Node address or name</label><input class="form-input" id="node-address" maxlength="100" placeholder="edge-node-02" required></div><div class="field"><label for="node-stake">Stake · simulated GEN</label><input class="form-input" id="node-stake" type="number" min="50" step="1" value="50" required><div class="field-help">The minimum is 50 GEN. A missed heartbeat or invalid proof can slash half.</div></div><div class="form-footer"><small>Manual nodes must send heartbeats and run the worker to process jobs.</small><button class="primary-btn" type="submit">Register node</button></div></form>`); }
    overlay.querySelector('input:not([type=file])')?.focus();
  }
  function closeOverlay() { overlay.innerHTML = ''; state.output = null; }
  function openJob(id) { const job = state.jobs.find(j => j.id === id); if (!job) return; state.output = null; renderJob(job); }
  function renderJob(job) {
    overlay.innerHTML = `<div class="drawer-backdrop" data-action="close-overlay"></div><aside class="detail-drawer" role="dialog" aria-modal="true" aria-label="Job details"><div class="drawer-top"><div><p class="eyebrow">JOB DETAIL</p><h2>${esc(short(job.id,15,6))}</h2></div><button class="close-button" data-action="close-overlay" aria-label="Close job details">×</button></div><div class="drawer-body"><div class="detail-status">${pill(job.status)}<strong>${esc(job.status==='completed'?'Computation verified':job.status==='failed'?'Verification failed':job.status==='requeued'?'Waiting for a new node':'Job in progress')}</strong><p>${esc(job.status==='completed'?'The verifier reproduced the result and released the tip.':job.status==='failed'?'The node was slashed and the tip refunded.':job.status==='requeued'?'The deadline passed without a valid result.':'Open this panel again to follow progress.')}</p></div><section class="detail-section"><h3>Job</h3><div class="detail-list"><div><span>Job ID</span><strong class="detail-code">${esc(job.id)}</strong></div><div><span>Client</span><strong>${esc(job.client)}</strong></div><div><span>Model</span><strong>${esc(job.model_id)}</strong></div><div><span>Tip</span><strong>${esc(job.tip)} GEN</strong></div><div><span>Deadline</span><strong>${esc(date(job.deadline))}</strong></div><div><span>Attempts</span><strong>${esc(job.attempts)}</strong></div></div></section><section class="detail-section"><h3>Proof & output</h3><div class="detail-list"><div><span>Input CID</span><strong class="detail-code">${esc(job.input_cid)}</strong></div><div><span>Output CID</span><strong class="detail-code">${esc(job.output_cid || 'Awaiting output')}</strong></div><div><span>Proof hash</span><strong class="detail-code">${esc(job.proof_hash || 'Awaiting proof')}</strong></div><div><span>Edge node</span><strong>${esc(job.assigned_node || 'Unassigned')}</strong></div></div></section><section class="detail-section"><h3>Actions</h3><div class="drawer-actions">${job.output_cid?`<button class="small-btn" data-action="view-output" data-job="${esc(job.id)}">View output</button><button class="small-btn" data-action="download-output" data-job="${esc(job.id)}">Download</button>`:''}${job.status==='pending_verification'?`<button class="small-btn" data-action="verify" data-job="${esc(job.id)}">Run verification</button>`:''}${job.status==='requeued'?`<button class="small-btn danger-btn" data-action="cancel-job" data-job="${esc(job.id)}">Cancel & refund</button>`:''}<button class="small-btn" data-action="copy" data-copy="${esc(job.id)}">Copy job ID</button></div><div id="output-preview">${state.output ? `<pre class="output-preview">${esc(state.output)}</pre>` : ''}</div></section><div class="alert-box">This is the local demonstration ledger. GEN amounts here are simulated and do not represent on-chain transfers.</div></div></aside>`;
  }
  async function action(action, el) {
    if (action === 'close-overlay') return closeOverlay();
    if (action === 'new-job' || action === 'register-node') return openModal(action);
    if (action === 'refresh') { await loadData(true); toast('Grid data refreshed'); return; }
    if (action === 'save-token') { const token=document.getElementById('settings-token').value.trim(); if(token)await validateToken(token); state.token=token; state.token ? sessionStorage.setItem('clintr_token',state.token) : sessionStorage.removeItem('clintr_token'); render(); toast(state.token?'Access token connected':'Access token cleared'); return; }
    if (action === 'copy') { await navigator.clipboard.writeText(el.dataset.copy); toast('Copied to clipboard'); return; }
    if (!needToken()) return;
    if (action === 'heartbeat') { await api(`/nodes/${encodeURIComponent(el.dataset.node)}/heartbeat`,{method:'POST'}); toast('Heartbeat sent'); await loadData(true); }
    if (action === 'withdraw') { if (!confirm(`Withdraw the remaining simulated stake for ${el.dataset.node}?`)) return; const result=await api(`/nodes/${encodeURIComponent(el.dataset.node)}/withdraw`,{method:'POST'}); toast(`${result.amount} GEN withdrawn`); await loadData(true); }
    if (action === 'verify') { const result=await api(`/jobs/${encodeURIComponent(el.dataset.job)}/verify`,{method:'POST'}); toast(result.valid?'Proof verified':'Proof rejected and node slashed',!result.valid); await loadData(true); const job=state.jobs.find(j=>j.id===el.dataset.job); if(job) renderJob(job); }
    if (action === 'cancel-job') { const job=state.jobs.find(j=>j.id===el.dataset.job); if(!job) return; if(!confirm('Cancel this requeued job and refund its simulated tip?')) return; await api(`/jobs/${encodeURIComponent(job.id)}/cancel`,{method:'POST',json:{client:job.client}}); toast('Job cancelled and tip refunded'); await loadData(true); renderJob(state.jobs.find(j=>j.id===job.id)); }
    if (action === 'view-output' || action === 'download-output') { const job=state.jobs.find(j=>j.id===el.dataset.job); if(!job?.output_cid) return; const blob=await api(`/blobs/${encodeURIComponent(job.output_cid)}`,{binary:true}); if(action==='download-output'){const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`clintr-${job.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),5000);return;} const text=await blob.text();try{state.output=JSON.stringify(JSON.parse(text),null,2);}catch{state.output=text;} renderJob(job); }
  }
  document.addEventListener('click', async event => {
    const job = event.target.closest('[data-job]'); if(job && job.tagName==='TR'){ openJob(job.dataset.job); return; }
    const target = event.target.closest('[data-action]'); if(!target) return;
    if(target.classList.contains('overlay') && event.target!==target) return;
    try { await action(target.dataset.action,target); } catch(error) { toast(error.message,true); }
  });
  document.getElementById('connection-button').addEventListener('click',()=>openModal('access'));
  document.getElementById('refresh-button').addEventListener('click',()=>loadData(true));
  document.getElementById('mobile-menu').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open'));
  document.addEventListener('input', event => { if(event.target.id==='job-search'){state.search=event.target.value.toLowerCase();document.querySelectorAll('tbody tr[data-search]').forEach(row=>row.hidden=!row.dataset.search.includes(state.search));} });
  document.addEventListener('change', event => { if(event.target.id==='job-filter'){state.filter=event.target.value;render();} if(event.target.id==='job-file'){const file=event.target.files[0];if(file){event.target.closest('.file-drop').querySelector('strong').textContent=file.name;}} });
  document.addEventListener('submit', async event => {
    if(!['access-form','job-form','node-form'].includes(event.target.id))return;
    event.preventDefault(); const button=event.target.querySelector('[type=submit]');button.disabled=true; const original=button.innerHTML;button.textContent='Working…';
    try {
      if(event.target.id==='access-form'){const token=document.getElementById('access-token').value.trim();await validateToken(token);state.token=token;sessionStorage.setItem('clintr_token',state.token);closeOverlay();render();toast('Access connected');}
      if(event.target.id==='node-form'){const address=document.getElementById('node-address').value.trim(),stake=Number(document.getElementById('node-stake').value);await api('/nodes/register',{method:'POST',json:{address,stake}});navigate('nodes','Node registered');return;}
      if(event.target.id==='job-form'){
        const file=document.getElementById('job-file').files[0],text=document.getElementById('job-text').value;
        const bytes=file?new Uint8Array(await file.arrayBuffer()):new TextEncoder().encode(text);
        if(!bytes.length)throw new Error('Choose a file or enter input text');if(bytes.length>65536)throw new Error('Input must be 64 KiB or smaller');
        const upload=await api('/blobs',{method:'POST',body:bytes});
        const payload={client:document.getElementById('job-client').value.trim(),model_id:'byte_histogram_v1',input_cid:upload.cid,tip:Number(document.getElementById('job-tip').value),deadline_seconds:Number(document.getElementById('job-deadline').value)};
        const result=await api('/jobs',{method:'POST',json:payload});navigate('jobs',`Job ${short(result.job_id,8,4)} submitted`);return;
      }
    } catch(error){toast(error.message,true);} finally{if(button.isConnected){button.disabled=false;button.innerHTML=original;}}
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeOverlay();});
  loadData(true).then(() => { const flash = sessionStorage.getItem('clintr_flash'); if (flash) { sessionStorage.removeItem('clintr_flash'); toast(flash); } });
  setInterval(()=>loadData(),5000);
})();
