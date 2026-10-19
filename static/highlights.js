'use strict';
// Visual analysis, bounded previews and explicit selection into the existing edit plan.
const highlightSelection = new Map();
const analysisRequestIds = new Map();
let highlightProject, visibleHighlights = 40, scanBusy = false;
const highlightPanel = node('section', undefined, 'panel'); highlightPanel.id = 'highlights';
highlightPanel.append(node('div', 'STEP 2 / FIND MOMENTS', 'eyebrow'), node('h2', 'Find the cool moments.'),
  node('p', 'Choose your video. Let AI look for fun bits. Then watch the picks and choose your favourites.', 'highlight-flow'));
const analysisForm = node('form'); analysisForm.id = 'analysis-form';
function analysisField(id, labelText, tag = 'input') {
  const label = node('label', labelText), input = node(tag); input.id = id; label.append(input); return { label, input };
}
const sourceField = analysisField('analysis-source', 'Which video?', 'select');
const gameField = analysisField('analysis-game', 'Game (optional)'); gameField.input.maxLength = 80; gameField.input.placeholder = 'Rocket League, Fortnite, Minecraft…';
const focusField = analysisField('analysis-focus', 'What should we look for? (optional)', 'textarea');
focusField.input.maxLength = 600; focusField.input.rows = 2; focusField.input.placeholder = 'Skilled plays, funny fails, close finishes, surprising turns…';
const analysisRow = node('div', undefined, 'row');
for (const [id, label] of [['analysis-start', 'Start at (seconds)'], ['analysis-end', 'Finish at (seconds)']]) {
  const field = analysisField(id, label); field.input.type = 'number'; field.input.step = 'any'; field.input.min = '0'; field.input.required = true; analysisRow.append(field.label);
}
const spacing = analysisField('analysis-interval', 'How closely should AI look?', 'select');
for (const [value, label] of [['.5', 'Look extra carefully · costs more'], ['1', 'Normal · recommended'], ['2', 'Quick look · costs less']]) {
  const option = node('option', label); option.value = value; spacing.input.append(option);
} spacing.input.value = '1'; analysisRow.append(spacing.label);
const range = analysisField('analysis-range', 'How much of the video?', 'select');
for (const [value, label] of [['whole','The whole video'], ['minute','Try the first minute'], ['custom','Choose a part myself']]) { const option = node('option', label); option.value=value; range.input.append(option); }
const options = node('details'); options.id = 'analysis-options'; options.append(node('summary', 'More choices'), focusField.label, analysisRow);
const analyse = node('button', 'Find cool moments →'); analyse.id = 'analyse-gameplay';
const scanMessage = node('p', '', 'muted'); scanMessage.id='scan-message'; scanMessage.setAttribute('role','status');
analysisForm.append(sourceField.label, gameField.label, range.label, options, analyse, scanMessage);
highlightPanel.append(analysisForm, node('p', 'You will see the estimated cost before starting. AI checks pictures from your video, not the sound. It can miss fast moves, so watch the picks before using them.', 'muted'));
const previewWrap = node('div'); previewWrap.id = 'highlight-preview-wrap'; previewWrap.hidden = true;
const previewHeading = node('h3'); previewHeading.id = 'highlight-preview-title';
const previewPlayer = node('video'); previewPlayer.id = 'highlight-preview'; previewPlayer.controls = true; previewPlayer.preload = 'metadata';
previewWrap.append(previewHeading, previewPlayer, node('p', 'This plays just the chosen bit. Press play to watch it again.', 'muted'));
const results = node('div'); results.id = 'highlight-results'; results.setAttribute('aria-live', 'polite');
highlightPanel.append(previewWrap, results); $('#editor').before(highlightPanel);

// Match the editor's frame choice with an explicit export-quality control.
const quality = analysisField('resolution', 'Picture quality', 'select');
for (const [value, label] of [['1080p', 'Best HD · 1080p'], ['720p', 'Smaller file · 720p']]) {
  const option = node('option', label); option.value = value; quality.input.append(option);
} quality.input.onchange = () => { dirty = true; }; $('#format').parentElement.after(quality.label);
const uploadLabel = node('label', undefined, 'inline-check');
const uploadCheck = node('input'); uploadCheck.type = 'checkbox'; uploadCheck.id = 'analyse-after-upload'; uploadCheck.checked = true;
uploadLabel.append(uploadCheck, document.createTextNode('Help me find cool moments after adding this video'));
$('#upload-form button').before(uploadLabel);
$('#shorts').parentElement.nextElementSibling.textContent = 'This makes three simple practice clips. Use Find moments above for AI picks.';
$('.aside-bottom p').textContent = 'Originals stay on your server. Visual analysis shares sampled images only after your confirmation.';
$('#captions').parentElement.previousElementSibling.querySelector('small').textContent = 'Seconds in the selected gameplay, before the intro screen';

function timecode(seconds) {
  const n = Math.floor(seconds), hours = Math.floor(n / 3600);
  return `${hours ? `${hours}:` : ''}${String(Math.floor(n / 60) % 60).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`;
}
function chooseAnalysisSource(id) {
  $('#analysis-source').value = id;
  const source = sources().find(s => s.id === id);
  $('#analysis-start').value = 0; $('#analysis-end').value = source?.duration || '';
  range.input.value = 'whole'; options.open = false;
}
sourceField.input.onchange = () => chooseAnalysisSource(sourceField.input.value);
range.input.onchange = () => {
  const source = sources().find(s => s.id === sourceField.input.value);
  if (range.input.value === 'custom') { options.open=true; $('#analysis-start').focus(); return; }
  $('#analysis-start').value=0; $('#analysis-end').value=range.input.value === 'minute' ? Math.min(60,source?.duration || 0) : source?.duration || '';
  options.open=false;
};
for (const id of ['analysis-start','analysis-end']) $(`#${id}`).oninput = () => { range.input.value='custom'; };
function confirmScan(quote) {
  return new Promise(resolve => {
    const spec=quote.spec, dialog=node('dialog', undefined, 'scan-dialog'); dialog.id='scan-confirmation';
    dialog.setAttribute('aria-labelledby','scan-dialog-title');
    const title=node('h2','Ready to find cool moments?'); title.id='scan-dialog-title';
    const local=spec.provider==='lmstudio';
    const cost=node('p',local?'LM Studio · no cloud API charge':`Estimated budget hold: $${spec.upperCostUsd.toFixed(2)} USD`, 'scan-cost');
    const details=node('details'); details.append(node('summary','Cost and AI details'),
      node('p',`${quote.frameCount} pictures · ${spec.chunks.length} checks · ${spec.provider || 'openai'} / ${spec.model}`),
      node('p',local?'This runs on your configured LAN machine. Local compute/electricity costs apply. It can be slow, and its host controls logging/retention. No paid provider fallback.':`Exact estimate: $${spec.upperCostUsd.toFixed(4)} USD. Monthly limit: $${spec.cap.toFixed(2)}; available: $${quote.remainingUsd.toFixed(2)}. The estimate uses saved prices. Actual billing depends on provider usage.`), node('p',quote.disclosure));
    dialog.append(title,cost,node('p',local?'Confirm before sharing these sampled pictures with your LAN model server. HTTP is not encrypted.':'This is a budget estimate, not a payment already taken. Ask a grown-up before using AI credits.'),
      node('p',`AI will check ${timecode(spec.start)}–${timecode(spec.end)}. Pictures from this part of your video, the game name and your notes will be sent to ${local?spec.localEndpoint:spec.provider || 'openai'}. Your sound stays here.`),details);
    const guide=checkedPrices[spec.model];
    if (!local && guide && (spec.inputRate !== guide.input || spec.outputRate !== guide.output)) details.append(node('p','Your saved prices differ from the checked standard prices for this model. Ask a grown-up to review them in Grown-up settings; the estimate is not a provider bill.'));
    const actions=node('div',undefined,'row'), cancel=node('button','Not now','quiet'), start=node('button','Start looking');
    cancel.onclick=()=>dialog.close('cancel'); start.onclick=()=>dialog.close('start'); actions.append(cancel,start); dialog.append(actions);
    dialog.addEventListener('close',()=>{ const accepted=dialog.returnValue==='start'; dialog.remove(); resolve(accepted); },{once:true});
    document.body.append(dialog); dialog.showModal(); cancel.focus();
  });
}
analysisForm.onsubmit = e => { e.preventDefault(); guarded(requestAnalysis); };
async function requestAnalysis() {
  if (!active) throw Error('Choose a project and add a gameplay video first.');
  if (!sourceField.input.value) throw Error('Choose a video first.');
  if (scanBusy) return;
  const body = { project: active, source: $('#analysis-source').value, start: Number($('#analysis-start').value),
    end: Number($('#analysis-end').value), interval: Number($('#analysis-interval').value),
    game: $('#analysis-game').value, focus: $('#analysis-focus').value };
  const button = $('#analyse-gameplay'); scanBusy=true; button.disabled = true; button.textContent='Checking the cost…'; scanMessage.textContent='Checking the cost. This does not run the AI yet.';
  try {
    const quote = await api('analysis/quote', body), spec = quote.spec;
    if (!quote.affordable) throw Error(`This check needs an estimated $${spec.upperCostUsd.toFixed(2)} of budget, but $${quote.remainingUsd.toFixed(2)} is available. Try the first minute, or ask a grown-up to check the AI prices and spending limit.`);
    if (!await confirmScan(quote)) { scanMessage.textContent='No problem. Nothing was sent to the AI.'; return; }
    button.textContent='Starting…';
    const requestId = analysisRequestIds.get(quote.quote) || crypto.randomUUID(); analysisRequestIds.set(quote.quote, requestId);
    const response = await api('analysis', { ...body, quote: quote.quote, consent: true, requestId });
    analysisRequestIds.delete(quote.quote);
    await refresh(true);
    notice(response.duplicate ? 'AI is already looking at this video. Watch its progress below.' : 'AI is ready to look for moments. Watch its progress below; you can come back later.');
    scanMessage.textContent='Your video is in line. Cool moments will appear below as they are found.';
    $('#highlights').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch(error) { scanMessage.textContent=error.message; throw error; }
  finally { scanBusy=false; button.disabled = !sourceField.input.value; button.textContent='Find cool moments →'; }
}
function previewHighlight(source, h) {
  previewPlayer.pause();
  previewPlayer.dataset.start = h.start; previewPlayer.dataset.end = h.end;
  previewHeading.textContent = `${timecode(h.start)}–${timecode(h.end)} · ${h.title}`; previewWrap.hidden = false;
  const play = () => { previewPlayer.currentTime = h.start; previewPlayer.play().catch(() => notice('Press play to preview this section.')); };
  if (previewPlayer.dataset.source !== source || previewPlayer.readyState < 1) {
    previewPlayer.dataset.source = source;
    previewPlayer.onloadedmetadata = play;
    previewPlayer.src = `file/${source}`; previewPlayer.load();
  } else { play(); }
  previewWrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
previewPlayer.ontimeupdate = () => { if (previewPlayer.currentTime >= Number(previewPlayer.dataset.end)) previewPlayer.pause(); };
previewPlayer.onplay = () => {
  if (previewPlayer.currentTime >= Number(previewPlayer.dataset.end) || previewPlayer.currentTime < Number(previewPlayer.dataset.start)) previewPlayer.currentTime = Number(previewPlayer.dataset.start);
};
function loadHighlights(items, format) {
  if (!items.length) return notice('Select one or more highlights to build a compilation.', true);
  if (items.length > 30 || items.reduce((sum, item) => sum + item.h.end - item.h.start, 0) > 1800) return notice('Each export supports up to 30 selected clips and 30 minutes of gameplay. Split this selection into multiple videos.', true);
  if (dirty && !confirm('Replace the current unsaved edit with these selected highlights?')) return;
  ensurePackagingControls();
  const first = items[0], project = workspace.projects.find(p => p.id === active);
  $('#cuts').replaceChildren();
  for (const item of items) addCut({ source: item.source, start: item.h.start, end: item.h.end });
  $('#format').value = format; $('#resolution').value = '1080p'; $('#captions').value = '[]';
  const title = items.length === 1 ? first.h.title : `${project.brand} · Gaming highlights`;
  $('#export-title').value = title; $('#overlay-intro').value = title; $('#overlay-intro-seconds').value = 3;
  $('#overlay-headline').value = first.h.hook; $('#overlay-cta').value = first.h.cta;
  $('#overlay-brand').value = project.brand; $('#overlay-seconds').value = 5;
  if (typeof updateTimeline === 'function') updateTimeline(true);
  dirty = true; updateEditSummary(); $('#editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
  notice(`${items.length} clip${items.length === 1 ? '' : 's'} chosen! Change your opening and ending below, then press Make my video.`);
}
function showHighlights() {
  if (!workspace) return;
  const all = active ? sources() : [];
  const optionsSignature = JSON.stringify(all.map(s => s.id));
  if (sourceField.input.dataset.signature !== optionsSignature) {
    const previous = sourceField.input.value; sourceField.input.replaceChildren(node('option', 'Choose a recording')); sourceField.input.firstChild.value = '';
    for (const s of all) { const option = node('option', `${s.name} · ${timecode(s.duration)}`); option.value = s.id; sourceField.input.append(option); }
    sourceField.input.dataset.signature = optionsSignature;
    chooseAnalysisSource(all.some(s => s.id === previous) ? previous : all[0]?.id || '');
  }
  analyse.disabled = !all.length || scanBusy;
  if (highlightProject !== active) {
    highlightProject = active; highlightSelection.clear(); visibleHighlights = 40;
    previewPlayer.pause(); previewPlayer.removeAttribute('src'); previewPlayer.dataset.source = ''; previewPlayer.load(); previewWrap.hidden = true;
    gameField.input.value = ''; focusField.input.value = '';
  }
  const analyses = (workspace.analyses || []).filter(a => a.project === active);
  const signature = JSON.stringify([active, analyses.map(a => [a.id, a.state, a.completed, a.results, a.error, a.cancel_requested]), visibleHighlights]);
  if (results.dataset.signature === signature) return;
  results.dataset.signature = signature; results.replaceChildren();
  results.append(node('div','STEP 3 / WATCH & CHOOSE','eyebrow'),node('h2','Pick your favourite bits.'));
  if (!analyses.length) { results.append(node('p', 'Your picks will appear here. Choose a video above and press Find cool moments to get started.', 'muted')); return; }
  const toolbar = node('div', undefined, 'row');
  const selectedCount = node('span', `${highlightSelection.size} selected`, 'muted'); selectedCount.id = 'highlight-selected-count';
  const compilation = node('button', 'Make a video with my picks', 'quiet'); compilation.type = 'button';
  compilation.onclick = () => loadHighlights([...highlightSelection.values()].sort((a,b) => a.created-b.created || a.h.start-b.h.start), 'landscape');
  toolbar.append(compilation, selectedCount); results.append(toolbar);
  let shown = 0, total = 0;
  for (const analysis of analyses) {
    const spec = JSON.parse(analysis.spec), picks = JSON.parse(analysis.results), source = all.find(s => s.id === analysis.source);
    total += picks.length;
    const group = node('article', undefined, 'analysis-group');
    group.dataset.analysis=analysis.id;
    const stateNames={queued:analysis.completed ? 'Still looking' : 'Waiting its turn',running:'Looking for moments…',complete:'Ready to choose!',failed:'Needs help',cancelled:'Stopped',interrupted:'Stopped when the studio restarted'};
    group.append(node('h3', `${source?.name || 'Video'} · ${stateNames[analysis.state] || analysis.state}`),
      node('p', `${analysis.completed} of ${analysis.total} parts checked · ${picks.length} moment${picks.length === 1 ? '' : 's'} found`, 'muted'));
    const scanDetails=node('details'); scanDetails.append(node('summary','AI and cost details'),node('p',`${timecode(spec.start)}–${timecode(spec.end)} · estimated usage $${analysis.spent_usd.toFixed(4)}${analysis.reserved_usd > .000001 ? ` + $${analysis.reserved_usd.toFixed(4)} held for remaining checks` : ''} · ${spec.model}`,'muted')); group.append(scanDetails);
    const progress = node('progress'); progress.max = analysis.total; progress.value = analysis.completed; progress.setAttribute('aria-label', 'Visual analysis progress'); group.append(progress);
    if (['queued','running'].includes(analysis.state)) {
      const cancel = node('button', analysis.cancel_requested ? 'Stopping after this part…' : 'Stop looking', 'quiet'); cancel.disabled = !!analysis.cancel_requested;
      cancel.onclick = () => guarded(async () => { await api('analysis/cancel', { id: analysis.id }); await refresh(true); notice('Analysis cancellation requested. Any request already sent may finish and incur usage.'); }); group.append(cancel);
    }
    if (analysis.error) {
      group.append(node('p', 'AI stopped before it finished. Your saved moments are still here.', 'analysis-error'));
      const help=node('details'); help.append(node('summary','Help for a grown-up'),node('p',analysis.error,'muted')); group.append(help);
    }
    if (analysis.rejected_candidates) group.append(node('p',`AI left out ${analysis.rejected_candidates} suggestion${analysis.rejected_candidates === 1 ? '' : 's'} because the times or details could not be checked. Watch the remaining picks and decide for yourself.`,'muted'));
    if (analysis.completed < analysis.total && !['queued','running'].includes(analysis.state)) group.append(node('p', 'AI did not finish checking this video. You can still use the moments it found below.', 'analysis-error'));
    if (analysis.completed < analysis.total && !['queued','running'].includes(analysis.state) && source) {
      const resume=node('button','Finish checking the rest','quiet');
      resume.onclick=()=>guarded(async()=>{
        chooseAnalysisSource(analysis.source);
        const next=spec.chunks?.[analysis.completed];
        $('#analysis-start').value=next?.coreStart ?? spec.start;
        $('#analysis-end').value=spec.end; range.input.value='custom'; options.open=true;
        spacing.input.value=String(spec.interval || 1);
        gameField.input.value=spec.game || ''; focusField.input.value=spec.focus || '';
        await requestAnalysis();
      }); group.append(resume);
    }
    if (!picks.length && analysis.state === 'complete') group.append(node('p', analysis.rejected_candidates ? 'AI suggested clips with details it could not check. Those were left out. Ask a grown-up to try another AI model, or choose a clip by hand.' : 'AI did not spot a standout moment in these pictures. Try Look extra carefully under More choices, or watch the original and choose a clip yourself.', 'muted'));
    const list = node('div', undefined, 'highlight-grid');
    for (const h of picks) {
      if (shown >= visibleHighlights) break; shown++;
      const card = node('article', undefined, 'highlight-card');
      const key = `${analysis.id}:${h.event_time}`, item = { source: analysis.source, h, created: analysis.created };
      const label = node('label', undefined, 'inline-check'); const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = highlightSelection.has(key);
      label.append(checkbox, document.createTextNode(`${timecode(h.start)}–${timecode(h.end)} · ${h.category}`));
      checkbox.onchange = () => { if (checkbox.checked) highlightSelection.set(key, item); else highlightSelection.delete(key); $('#highlight-selected-count').textContent = `${highlightSelection.size} selected`; };
      const position = node('meter'); position.min = 0; position.max = source?.duration || spec.end; position.value = h.event_time; position.setAttribute('aria-label', 'Event position in the source');
      card.append(label, node('h3', h.title), node('p', `${Math.round(h.end-h.start)} seconds · best bit at ${timecode(h.event_time)}`, 'muted'), position, node('p', h.reason));
      const evidence = node('details'); evidence.append(node('summary', 'Why this moment was picked'));
      for (const frame of h.evidence) evidence.append(node('p', `${timecode(frame.timestamp)} · ${frame.observation}`, 'muted'));
      evidence.append(node('p',`AI score: ${h.score}/100. This is the AI's opinion; watch the clip and decide for yourself.`,'muted'));
      card.append(evidence);
      const controls = node('div', undefined, 'highlight-actions');
      const preview = node('button', '▶ Watch this bit', 'quiet'); preview.onclick = () => previewHighlight(analysis.source, h);
      const short = node('button', 'Make a Short'); short.onclick = () => loadHighlights([item], 'vertical');
      const video = node('button', 'Make a wide video', 'quiet'); video.onclick = () => loadHighlights([item], 'landscape');
      controls.append(preview, short, video); card.append(controls); list.append(card);
    }
    group.append(list); results.append(group);
  }
  if (total > shown) { const more = node('button', `Show more moments (${total-shown} remaining)`, 'quiet'); more.onclick = () => { visibleHighlights += 40; showHighlights(); }; results.append(more); }
}

// Start only after all editor controls exist, including the dynamic quality selector.
refresh().catch(() => {});
setInterval(() => { if (!document.hidden && workspace) refresh(true).catch(() => {}); }, 30000);
