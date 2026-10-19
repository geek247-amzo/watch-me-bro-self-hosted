'use strict';
const $ = s => document.querySelector(s);
let workspace, active, dirty = false;
// Standard API price guide checked against official model pages, 2026-10-17.
const checkedPrices = { 'gpt-5': { input:1.25, output:10 }, 'gpt-5.4-mini': { input:.75, output:4.5 } };
$('#ai-editor h2').textContent = 'Make a catchy, truthful Short.';
$('#generate-storyboard').textContent = 'Generate title, subscribe card & moments';
$('#transcript').previousSibling.textContent = 'Timestamped transcript or scene notes (source seconds, JSON)';
$('#transcript').parentElement.nextElementSibling.textContent = 'Example: [{"start":12,"end":18,"text":"A player scores after an air dribble pop reset"}]. For gameplay without speech, describe what happens and when; the provider never sees the video.';
function notice(message, error = false) { $('#notice').textContent = message; $('#notice').className = error ? 'error' : ''; }
const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
async function api(path, body) {
  const r = await fetch(`api/${path}`, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-WMB-Request': 'studio' }, body: JSON.stringify(body) });
  const result = await r.json();
  if (!r.ok) throw Error(result.error || 'Request failed');
  return result;
}
async function guarded(action) { try { await action(); } catch (e) { notice(e.message, true); } }
$('#login-form').onsubmit = e => { e.preventDefault(); guarded(async () => { await api('login', { password: new FormData(e.target).get('password') }); e.target.reset(); await refresh(); notice('Welcome back! Start with My videos, or choose a video you have already added.'); }); };
$('#logout').onclick = () => guarded(async () => { await api('logout', {}); location.reload(); });
async function refresh(background = false) {
  try { workspace = await api('workspace'); } catch (e) { $('#workspace').hidden = true; $('#login-panel').hidden = false; throw e; }
  $('#workspace').hidden = false; $('#login-panel').hidden = true;
  if (!workspace.projects.some(p => p.id === active)) active = (workspace.projects.find(p => p.mode === 'gaming') || workspace.projects[0])?.id;
  $('#project-count').textContent = workspace.projects.length;
  $('#render-count').textContent = workspace.jobs.filter(x => x.state === 'review').length;
  $('#storage-free').textContent = `${Math.floor(workspace.storage.mediaFree / 1024 ** 3)} GB`;
  $('#project-list').replaceChildren();
  for (const p of workspace.projects) {
    const b = node('button', `${p.mode === 'gaming' ? '▶' : '◫'}  ${p.title}`, p.id === active ? 'selected' : '');
    b.dataset.project = p.id;
    b.onclick = () => { if (dirty && !confirm('Switch projects and leave your unsaved changes?')) return; dirty = false; active = p.id; showEditor(); refreshProjects(); showJobs(); };
    $('#project-list').append(b);
  }
  if (active && !dirty && !background) showEditor();
  showJobs();
  if (typeof showHighlights === 'function') showHighlights();
  if (!background && typeof showCreative === 'function') await showCreative();
}
function refreshProjects() { for (const b of $('#project-list').children) b.classList.toggle('selected', b.dataset.project === active); }
$('#project-form').onsubmit = e => { e.preventDefault(); guarded(async () => { const p = await api('projects', Object.fromEntries(new FormData(e.target))); active = p.id; dirty = false; e.target.reset(); $('#new-project').open = false; await refresh(); notice('Your project is ready. Add a gameplay video below.'); }); };
function sources() { return workspace.sources.filter(s => s.project === active); }
function ensurePackagingControls() {
  let panel = $('#packaging-controls');
  if (panel) return panel;
  panel = node('div'); panel.id = 'packaging-controls';
  panel.append(node('h3', 'Your opening and ending'));
  const captionLabel = node('label', 'Caption look'), captionStyle = node('select');
  captionStyle.id = 'caption-style';
  for (const [value, text] of [['studio','Studio · clean white'], ['gaming','Gaming · bold lime'], ['boxed','Boxed · high contrast']]) {
    const option = node('option', text); option.value = value; captionStyle.append(option);
  }
  captionStyle.onchange = () => { dirty = true; updateCaptionPreview(); };
  captionLabel.append(captionStyle); panel.append(captionLabel);
  const captionPreview = node('p', 'Your next great moment', 'caption-preview'); captionPreview.id = 'caption-preview';
  panel.append(captionPreview, node('p', 'This is a style sample, not a transcript. Spoken captions stay editable text with exact timing. Use AI artwork below for designed title cards and transparent title stickers.', 'muted'));
  const makeField = (id, title, tag, type, placeholder, max) => {
    const label = node('label', title);
    const control = node(tag); control.id = id;
    if (type) control.type = type;
    if (placeholder) control.placeholder = placeholder;
    if (max) control.maxLength = max;
    label.append(control); panel.append(label); control.oninput = () => { dirty = true; };
    return control;
  };
  makeField('overlay-intro', 'Opening screen · leave blank to skip', 'input', 'text', 'Watch Me Bro · My best moments', 100);
  const introSeconds = makeField('overlay-intro-seconds', 'How long is the opening? (seconds)', 'input', 'number', null);
  introSeconds.min = '2'; introSeconds.max = '8'; introSeconds.step = '1';
  makeField('overlay-headline', 'Title over the gameplay', 'input', 'text', 'Watch what happens next!', 120);
  const start = makeField('title-start', 'Show title at · gameplay seconds', 'input', 'number');
  const finish = makeField('title-end', 'Hide title at · gameplay seconds', 'input', 'number');
  for (const field of [start, finish]) { field.min = '0'; field.step = 'any'; }
  for (const [id,label,options] of [
    ['title-look','Title look',[['3d','3D · raised and outlined'],['flat','Flat · clean outline']]],
    ['title-size','Title size',[['small','Small'],['medium','Medium'],['large','Large']]],
    ['title-position','Title position',[['centre','Middle · recommended for Shorts'],['top','Upper safe area'],['bottom','Lower safe area']]]
  ]) {
    const select = makeField(id,label,'select');
    for (const [value,label] of options) { const option=node('option',label); option.value=value; select.append(option); }
  }
  const titlePreview=node('div',undefined,'title-layout-preview'); titlePreview.id='title-layout-preview';
  const titleSample=node('span'); titleSample.id='title-layout-text'; titlePreview.append(titleSample);
  panel.append(titlePreview,node('p','Layout guide only: export measures the real font and wraps/shrinks text to fit. Timings use your chosen gameplay before the opening screen; 0 is its beginning. Image-embedded lettering cannot be resized separately—use a text-free background and editable titles.','muted'));
  for (const id of ['overlay-headline','title-start','title-end','title-look','title-size','title-position']) panel.querySelector('#'+id).oninput=()=>{dirty=true; updateTitlePreview();};
  makeField('overlay-cta', 'Ending screen · your message to viewers', 'textarea', null, 'Thanks for watching! Like & subscribe for more.', 140);
  makeField('overlay-brand', 'Your channel name', 'input', 'text', 'Watch Me Bro', 60);
  const seconds = makeField('overlay-seconds', 'How long is the ending? (seconds)', 'input', 'number', null);
  seconds.min = '3'; seconds.max = '10'; seconds.step = '1';
  const more = node('details'); more.append(node('summary', 'Change opening and ending times'), introSeconds.parentElement, seconds.parentElement);
  panel.append(more, node('p', 'Your opening plays first. Your ending plays last. You can change the words above. Extra music is not added automatically.', 'muted'));
  $('#export-title').closest('label').after(panel);
  return panel;
}
function updateCaptionPreview() { $('#caption-preview').dataset.style = $('#caption-style').value; }
function updateTitlePreview() {
  const preview=$('#title-layout-preview'); if(!preview)return;
  preview.dataset.format=$('#format').value; preview.dataset.look=$('#title-look').value;
  preview.dataset.size=$('#title-size').value; preview.dataset.position=$('#title-position').value;
  $('#title-layout-text').textContent=$('#overlay-headline').value||'Your next great moment';
  const sample=$('#title-layout-text'); sample.style.fontSize='';
  let size=parseFloat(getComputedStyle(sample).fontSize);
  while(preview.clientHeight && sample.scrollHeight>preview.clientHeight*.23 && size>6){size--;sample.style.fontSize=size+'px';}
}
function addCut(cut) {
  const row = node('div', undefined, 'cut');
  const select = node('select'); select.setAttribute('aria-label', 'Source recording');
  for (const s of sources()) { const option = node('option', s.name); option.value = s.id; select.append(option); }
  if (cut) select.value = cut.source;
  if (cut?.crop) row.dataset.crop = JSON.stringify(cut.crop);
  const start = node('input'); start.type = 'number'; start.step = 'any'; start.min = '0'; start.value = cut?.start ?? 0; start.setAttribute('aria-label', 'Clip start in seconds');
  const end = node('input'); end.type = 'number'; end.step = 'any'; end.min = '0'; end.value = cut?.end ?? Math.min(60, sources()[0]?.duration || 0); end.setAttribute('aria-label', 'Clip finish in seconds');
  const remove = node('button', '×', 'quiet'); remove.setAttribute('aria-label', 'Remove clip'); remove.onclick = () => { row.remove(); dirty = true; updateEditSummary(); };
  row.append(select, start, end, remove); $('#cuts').append(row);
  row.oninput = event => { if (event.target === select) delete row.dataset.crop; dirty = true; updateEditSummary(); };
  updateEditSummary();
}
function updateEditSummary() {
  const clips = [...$('#cuts').children], duration = clips.reduce((sum, row) => sum + Math.max(0, Number(row.children[2].value) - Number(row.children[1].value)), 0);
  $('#edit-summary').textContent = clips.length ? `${clips.length} chosen clip${clips.length === 1 ? '' : 's'} · ${Math.floor(duration / 60)} min ${Math.round(duration % 60)} sec of gameplay. Add your opening and ending below.` : 'Choose a moment above, or add a video to get started.';
  $('#render').disabled = !clips.length;
  if (typeof updateTimeline === 'function') updateTimeline();
  updateTitlePreview();
}
function showEditor() {
  const p = workspace.projects.find(x => x.id === active); if (!p) return;
  $('#editor-title').textContent = p.title; $('#editor-body').hidden = false; $('#editor-empty').hidden = true;
  $('#short-candidates')?.remove();
  $('#source-preview').pause();
  $('#source-list').replaceChildren(); $('#source-preview').hidden = true;
  for (const s of sources()) {
    const item = node('div', undefined, 'source'); item.append(node('strong', s.name), node('small', `${Math.floor(s.duration / 60)} min ${Math.round(s.duration % 60)} sec · ${s.audio ? 'With game sound' : 'No sound'}`));
    const details = node('details'); details.append(node('summary', 'File details'), node('code', `SHA-256 ${s.sha256}`), node('small', `${(s.bytes / 1024 ** 2).toFixed(1)} MB`));
    const preview = node('button', 'Watch original', 'quiet'); preview.onclick = () => { $('#source-preview').src = `file/${s.id}`; $('#source-preview').hidden = false; };
    const use = node('button', 'Find moments in this video'); use.onclick = () => { chooseAnalysisSource(s.id); $('#highlights').scrollIntoView({ behavior:'smooth', block:'start' }); };
    const actions = node('div', undefined, 'row'); actions.append(use, preview); item.append(actions, details); $('#source-list').append(item);
  }
  const transcriptSource = $('#transcript-source');
  transcriptSource.replaceChildren(node('option', 'Choose a source recording'));
  transcriptSource.firstChild.value = '';
  for (const s of sources()) { const option = node('option', s.name); option.value = s.id; transcriptSource.append(option); }
  const saved = workspace.plans.find(x => x.project === active);
  const plan = saved ? JSON.parse(saved.body) : { title: p.title, format: 'landscape', resolution:'1080p', audio: 'original', captions: [], cuts: sources().slice(0, 1).map(s => ({ source: s.id, start: 0, end: Math.min(s.duration, 60) })) };
  const overlay = plan.overlay || { headline: '', cta: 'Thanks for watching! Like & subscribe for more.', brand: p.brand, outro_seconds: 5 };
  ensurePackagingControls();
  $('#caption-style').value = plan.caption_style || 'studio'; updateCaptionPreview();
  $('#format').value = plan.format; $('#audio').value = plan.audio; $('#export-title').value = plan.title; $('#captions').value = JSON.stringify(plan.captions, null, 2);
  $('#overlay-headline').value = overlay.headline || '';
  $('#overlay-intro').value = overlay.intro || '';
  $('#overlay-intro-seconds').value = overlay.intro_seconds || 3;
  $('#resolution').value = plan.resolution || '720p';
  $('#overlay-cta').value = overlay.cta || '';
  $('#overlay-brand').value = overlay.brand || p.brand;
  $('#overlay-seconds').value = overlay.outro_seconds || 5;
  $('#title-start').value = overlay.headline_start ?? 0;
  $('#title-end').value = overlay.headline_end ?? Math.min(3,plan.cuts.reduce((sum,c)=>sum+c.end-c.start,0));
  $('#title-look').value = overlay.title_style || '3d';
  $('#title-size').value = overlay.title_size || 'medium';
  $('#title-position').value = overlay.title_position || 'centre'; updateTitlePreview();
  $('#cuts').replaceChildren(); plan.cuts.forEach(addCut);
  if (typeof showHighlights === 'function') showHighlights();
  if (typeof showCreative === 'function') guarded(()=>showCreative(plan));
}
for (const id of ['format', 'audio', 'export-title', 'captions']) $(`#${id}`).oninput = () => { dirty = true; updateTitlePreview(); };
$('#add-cut').onclick = () => { if (!sources().length) return notice('Upload a recording first.', true); addCut(); dirty = true; };
function plan() { return { caption_style: $('#caption-style').value, design: typeof creativeDesign === 'function' ? creativeDesign() : {}, title: $('#export-title').value, format: $('#format').value, resolution: $('#resolution').value, audio: $('#audio').value,
  overlay: { headline: $('#overlay-headline').value, headline_start: Number($('#title-start').value), headline_end: Number($('#title-end').value), title_style: $('#title-look').value, title_size: $('#title-size').value, title_position: $('#title-position').value, intro: $('#overlay-intro').value, intro_seconds: Number($('#overlay-intro-seconds').value), cta: $('#overlay-cta').value, brand: $('#overlay-brand').value, outro_seconds: Number($('#overlay-seconds').value) },
  captions: JSON.parse($('#captions').value), cuts: [...$('#cuts').children].map(row => ({ source: row.children[0].value, start: Number(row.children[1].value), end: Number(row.children[2].value), ...(row.dataset.crop ? {crop:JSON.parse(row.dataset.crop)} : {}) })) }; }
$('#save-plan').onclick = () => guarded(async () => { await api('plan', { project: active, plan: plan() }); dirty = false; await refresh(); notice('Your edit is saved. You can come back to it later.'); });
$('#render').onclick = () => guarded(async () => {
  const button = $('#render'); button.disabled = true;
  try { await api('render', { project: active, plan: plan() }); dirty = false; await refresh(); notice('Your video is in line to be made. Watch its progress in Finished videos.'); $('#queue').scrollIntoView({ behavior:'smooth', block:'start' }); }
  finally { button.disabled = false; }
});
$('#shorts').onclick = () => guarded(async () => {
  const s = sources()[0]; if (!s || s.duration < 60) throw Error('A source of at least 60 seconds is needed for three 20-second candidates.');
  if (!confirm('Prepare three sequential Shorts candidates? Selecting one replaces your unsaved cut plan. These are not AI-selected highlights.')) return;
  const length = Math.min(60, s.duration / 3);
  let candidates = $('#short-candidates');
  if (!candidates) { candidates = node('div'); candidates.id = 'short-candidates'; $('#shorts').parentElement.after(candidates); }
  candidates.replaceChildren();
  for (let i = 0; i < 3; i++) {
    const b = node('button', `Edit Short ${i+1}: ${(i*length).toFixed(1)}–${((i+1)*length).toFixed(1)}s`, 'quiet');
    b.onclick = () => { $('#cuts').replaceChildren(); addCut({ source: s.id, start: i * length, end: (i + 1) * length }); $('#format').value = 'vertical'; $('#captions').value = '[]'; $('#export-title').value = `${workspace.projects.find(p=>p.id===active).title} · Short ${i+1}`; updateTitlePreview(); dirty = true; notice('Candidate loaded. Refine the crop/cut and add reviewed captions, then queue this Short.'); };
    candidates.append(b);
  }
  notice('Three candidate windows prepared. Select one to edit, caption and render separately.');
});
$('#upload-form').onsubmit = e => { e.preventDefault(); guarded(async () => {
  if (!active) throw Error('Choose a project above, or start a new one first.');
  const file = e.target.elements.video.files[0]; if (file.size > 2 * 1024 ** 3) throw Error('File exceeds the 2 GiB upload limit.');
  const button = e.target.querySelector('button'); button.disabled = true; $('#upload-progress').hidden = false; notice('Adding your video… Keep this page open until it finishes.');
  const findHighlights = $('#analyse-after-upload').checked;
  const uploadProject = active;
  try { const uploaded = await new Promise((resolve, reject) => { const xhr = new XMLHttpRequest(); xhr.open('POST', `api/upload/${uploadProject}`); xhr.setRequestHeader('X-WMB-Request', 'studio'); xhr.setRequestHeader('X-Filename', file.name.replace(/[^\x20-\x7e]/g, '_')); xhr.upload.onprogress = x => { if (x.lengthComputable) $('#upload-progress').value = x.loaded / x.total * 100; }; xhr.onload = () => { try { const r = JSON.parse(xhr.responseText); if (xhr.status >= 400) reject(Error(r.error)); else resolve(r); } catch { reject(Error('Upload failed.')); } }; xhr.onerror = () => reject(Error('Upload connection failed. Retry the file.')); xhr.send(file); });
    if (active === uploadProject) dirty = false;
    e.target.reset(); await refresh(active !== uploadProject); notice('Your video is ready. Next, find your favourite moments.');
    if (findHighlights && active === uploadProject) { chooseAnalysisSource(uploaded.id); await requestAnalysis(); }
  } finally { button.disabled = false; $('#upload-progress').hidden = true; }
}); };
function showJobs() {
  const root = $('#jobs');
  // Preserve forms and playing previews on automatic polling; rebuild only when job state changes.
  const jobs = workspace.jobs.filter(x => x.project === active);
  const signature = JSON.stringify([active, jobs.map(x => [x.id, x.state])]); if (root.dataset.signature === signature) { updateRenderProgress(jobs); return; }
  root.dataset.signature = signature; root.replaceChildren();
  if (!jobs.length) root.append(node('p', 'Your finished videos will appear here. First choose some moments, then press Make my video.', 'muted'));
  for (const j of jobs) {
    const p = JSON.parse(j.body); const box = node('article', undefined, 'job'); const heading = node('div', undefined, 'job-heading');
    box.dataset.job = j.id;
    const stateNames = { queued:'Waiting its turn', running:'Making your video…', review:'Ready to watch', approved:'Checked', failed:'Needs help' };
    heading.append(node('h3', p.title), node('span', stateNames[j.state] || j.state, 'pill')); box.append(heading, node('p', `${p.format === 'vertical' ? 'Tall Short' : 'Wide video'} · ${p.resolution || '720p'} · ${p.cuts.length} chosen clip${p.cuts.length === 1 ? '' : 's'}`, 'muted'));
    if (j.error) box.append(node('p', j.error, 'muted'));
    if (['queued','running','failed'].includes(j.state)) {
      const progress=node('div',undefined,'render-progress');
      progress.append(node('p',undefined,'render-stage'));
      const bar=node('progress');bar.max=100;bar.setAttribute('aria-label','Current processing step progress');progress.append(bar);
      progress.append(node('p',undefined,'render-eta'),node('small',undefined,'render-estimate-basis'),node('small',undefined,'render-checked'));
      box.append(progress);
    } else if (Number.isFinite(j.elapsed)) box.append(node('p',`Processed in ${renderDuration(j.elapsed)}.`, 'muted'));
    if (['review', 'approved'].includes(j.state)) {
      const v = node('video'); v.controls = true; v.preload = 'none'; v.src = `file/${j.id}/video.mp4`; box.append(v);
      const download = node('a', 'Save video to my device ↓', 'download-video'); download.href = `file/${j.id}/video.mp4`; download.download = 'video.mp4'; box.append(download);
      const extras = node('details'); extras.append(node('summary', 'Extra files'));
      const links = node('div', undefined, 'job-links'); for (const [name, label] of [['captions.srt', 'Caption file'], ['thumbnail.jpg', 'Cover picture'], ['manifest.json', 'Video details (JSON)']]) { const a = node('a', label); a.href = `file/${j.id}/${name}`; a.download = name; links.append(a); } extras.append(links); box.append(extras);
      if (j.state === 'review') {
        const checkPanel = node('details'); checkPanel.append(node('summary', 'Check with a grown-up before sharing'));
        const form = node('form', undefined, 'review'); form.append(node('h3', 'Watch the finished video together'));
        const checks = { privacy: 'No private chats, addresses, school names or other personal information are showing', child_safety: 'A grown-up has checked child safety and permission where needed', licensing: 'We have permission to use all the video, pictures and music', claims: 'The video shows what really happened', captions: 'The words, picture and sound look right', audience: 'We have checked the right audience and made-for-kids choice', disclosure: 'We have checked whether AI-made parts need to be labelled' };
        for (const [key, text] of Object.entries(checks)) { const label = node('label'); const input = node('input'); input.type = 'checkbox'; input.name = key; input.required = true; label.append(input, document.createTextNode(text)); form.append(label); }
        const note = node('textarea'); note.name = 'note'; note.placeholder = 'Your name and what you checked'; note.required = true; note.minLength = 5; note.maxLength = 2000; note.setAttribute('aria-label', 'Your name and review notes'); form.append(note, node('button', 'Save our check'));
        form.onsubmit = e => { e.preventDefault(); guarded(async () => { const data = new FormData(form); await api('review', { job: j.id, note: data.get('note'), checks: Object.fromEntries(Object.keys(checks).map(k => [k, data.has(k)])) }); await refresh(); notice('Your check is saved for this video. It has not been posted online.'); }); }; checkPanel.append(form); box.append(checkPanel);
      } else { const review = workspace.reviews.find(r => r.job === j.id); box.append(node('p', `Checked together · ${review?.note || ''}`, 'green')); }
    }
    if (j.state === 'failed') { const retry = node('button', 'Try making this video again', 'quiet'); retry.onclick = () => guarded(async () => { await api('render', { project: j.project, plan: p }); await refresh(); }); box.append(retry); }
    root.append(box);
  }
  updateRenderProgress(jobs);
}
function renderDuration(seconds) {
  if(seconds<60)return 'under a minute';
  const minutes=Math.ceil(seconds/60);
  return minutes<60?`${minutes} min`:`${Math.floor(minutes/60)} hr ${minutes%60} min`;
}
function renderRange(seconds){const low=renderDuration(seconds*.6),high=renderDuration(seconds*1.8);return low===high?low:`${low} – ${high}`;}
function updateRenderProgress(jobs) {
  for(const job of jobs){
    const box=[...$('#jobs').children].find(el=>el.dataset.job===job.id),panel=box?.querySelector('.render-progress');if(!panel)continue;
    const p=job.progress||{stage:job.state==='queued'?'Waiting its turn':'Preparing render',estimateBasis:'Detailed progress is not available for this render yet.'};
    const step=p.stageIndex?`Step ${p.stageIndex} of ${p.stageCount} · `:'';
    panel.querySelector('.render-stage').textContent=step+p.stage+(Number.isFinite(p.percent)?` · ${p.percent}% of this step`:'');
    const bar=panel.querySelector('progress');
    if(Number.isFinite(p.percent)&&job.state!=='failed'){bar.value=p.percent;bar.setAttribute('aria-valuetext',`${p.percent}% of the current step`);}else{bar.removeAttribute('value');bar.setAttribute('aria-valuetext',job.state==='failed'?'Processing stopped':'Measuring — percentage unknown');}
    bar.hidden=job.state==='failed';
    let eta='Time remaining: not known yet.';
    if(job.state==='failed')eta='Processing stopped. No completion estimate.';
    else if(job.state==='queued')eta=`${p.queueAhead||0} render${p.queueAhead===1?'':'s'} ahead. Waiting time is unknown.`+(Number.isFinite(p.etaSeconds)?` Estimated processing once started: ${renderRange(p.etaSeconds)}.`:' Processing estimate is not known yet.');
    else if(Number.isFinite(p.etaSeconds))eta=`Estimated total remaining: ${renderRange(p.etaSeconds)}.`;
    else if(Number.isFinite(p.stageEtaSeconds))eta=`This step: roughly ${renderRange(p.stageEtaSeconds)} remaining. Later steps: not known yet.`;
    if(Number.isFinite(p.elapsedSeconds))eta+=` Elapsed: ${renderDuration(p.elapsedSeconds)}.`;
    panel.querySelector('.render-eta').textContent=eta;
    panel.querySelector('.render-estimate-basis').textContent=p.estimateBasis||'Estimates change with real speed and server load; they are not deadlines.';
    panel.querySelector('.render-checked').textContent=`Refreshes every 30 seconds while this tab is visible. ${p.updated?'Checked '+new Date(p.updated*1000).toLocaleTimeString()+'.':''}${p.stale?' No recent encoder report — estimate unavailable.':''}`;
  }
}
$('#refresh').onclick = () => guarded(refresh);
$('#generate-storyboard').onclick = () => guarded(async () => {
  if (!active) throw Error('Choose a production first.');
  const routing = await api('creative/settings');
  const assignment = routing.routes.find(r=>r.feature==='titles');
  if (!assignment) throw Error('Choose a title-writing model in Settings first.');
  const provider = assignment.provider;
  const transcript = JSON.parse($('#transcript').value);
  const source = $('#transcript-source').value;
  const providers = await api('providers');
  const selected = providers.providers.find(p => p.id === provider);
  if (selected?.budget) { selected.budget.model = assignment.model; selected.budget.inputUsdPerMillion=assignment.input_rate; selected.budget.outputUsdPerMillion=assignment.output_rate; }
  if (!source || !Array.isArray(transcript) || !transcript.length) throw Error('Choose a source and add timestamped transcript excerpts.');
  if (!selected?.budget) throw Error('Save a verified model, its current rates and a monthly cap first.');
  const roughInput = new TextEncoder().encode(JSON.stringify(transcript)).length + 4096;
  const maxEstimate = (roughInput * selected.budget.inputUsdPerMillion + 1100 * selected.budget.outputUsdPerMillion) / 1e6;
  const remaining = selected.budget.monthlyUsdCap - selected.budget.spentUsd - selected.budget.reservedUsd;
  if (maxEstimate > remaining) throw Error('The conservative estimated request cost exceeds this provider budget’s remaining balance.');
  const local=provider==='lmstudio';
  const confirmation=local?`Send only these notes to LM Studio / ${selected.budget.model} at ${routing.localSettings?.base_url}?\n\nNo cloud API charge. Local compute/electricity costs apply. HTTP is not encrypted; the LM Studio host controls logs/retention. No cloud fallback. Continue?`:`Send only this transcript text to ${provider} / ${selected.budget.model}?\n\nEstimated maximum: about $${maxEstimate.toFixed(4)} USD. Monthly cap: $${selected.budget.monthlyUsdCap.toFixed(2)}; currently spent/reserved: $${(selected.budget.spentUsd + selected.budget.reservedUsd).toFixed(4)}.\n\nThe provider may process this data under its terms. This runs a paid model request. Continue?`;
  if (!confirm(confirmation)) return;
  const button = $('#generate-storyboard'); button.disabled = true;
  try {
    const result = await api('ai/storyboard', { provider, project: active, source, transcript, ...(local?{localUpdated:routing.localSettings?.updated,localModel:assignment.model}:{}) });
    const box = $('#storyboard-results'); box.replaceChildren(node('h3', `AI edit package · ${result.provider} / ${result.model} · ${local?'local inference, no cloud API charge':'estimated $'+result.estimatedCostUsd.toFixed(4)}`));
    const packageCard = node('article', undefined, 'job');
    packageCard.append(node('strong', result.creative.title), node('p', `Opening hook: ${result.creative.hook}`, 'muted'), node('p', `Subscribe card: ${result.creative.outro_cta}`, 'muted'));
    const usePackage = node('button', 'Use this title, hook & subscribe card');
    usePackage.onclick = () => {
      $('#export-title').value = result.creative.title;
      $('#overlay-headline').value = result.creative.hook;
      $('#overlay-cta').value = result.creative.outro_cta;
      updateTitlePreview();
      dirty = true;
      notice('AI package placed in the edit for review. Save or render to apply it; nothing was changed automatically.');
    };
    packageCard.append(usePackage); box.append(packageCard);
    box.append(node('h3', 'Candidate moments'));
    for (const suggestion of result.suggestions) {
      const article = node('article', undefined, 'job'); article.append(node('strong', `${suggestion.start.toFixed(1)}–${suggestion.end.toFixed(1)}s · ${suggestion.title}`), node('p', suggestion.reason, 'muted'));
      const add = node('button', 'Add as an editable source cut', 'quiet'); add.onclick = () => {
        const s = sources().find(item => item.id === source); if (!s) return notice('Source is no longer in this production.', true);
        addCut({ source, start: suggestion.start, end: suggestion.end }); dirty = true;
        $('#export-title').value = suggestion.title; notice('Candidate added as an unsaved cut. Review timing and transcript before rendering.');
      };
      article.append(add); box.append(article);
    }

    notice(result.note);
  } finally { button.disabled = false; }
});
