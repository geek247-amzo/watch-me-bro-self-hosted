'use strict';
const $ = s => document.querySelector(s);
// Standard API price guide checked against official model pages, 2026-10-17.
const checkedPrices = { 'gpt-5': { input:1.25, output:10 }, 'gpt-5.4-mini': { input:.75, output:4.5 } };
function notice(message, error = false) { $('#notice').textContent = message; $('#notice').className = error ? 'error' : ''; }
const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
async function api(path, body) {
  const r = await fetch(`api/${path}`, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-WMB-Request': 'studio' }, body: JSON.stringify(body) });
  const result = await r.json();
  if (!r.ok) throw Error(result.error || 'Request failed');
  return result;
}
async function guarded(action) { try { await action(); } catch (e) { notice(e.message, true); } }

$('#login-form').onsubmit=e=>{e.preventDefault();guarded(async()=>{await api('login',{password:new FormData(e.target).get('password')});e.target.reset();await loadSettings();});};
$('#logout').onclick=()=>guarded(async()=>{await api('logout',{});location.reload();});
async function loadSettings(){await api('workspace');$('#login-panel').hidden=true;$('#workspace').hidden=false;await refreshProviders();await loadRoutes();await loadLMStudio();}
let providerState;
async function refreshProviders() {
  try {
    providerState = await api('providers');
    const configured = providerState.providers.filter(p => p.configured&&!p.local);
    const selected = providerState.providers.find(p => p.id === $('#provider').value);
    $('#provider-state').textContent = selected?.configured ? `Encrypted key saved · ${new Date(selected.updated * 1000).toLocaleString()}` : 'No key saved for this provider.';
    if (selected?.budget) {
      $('#input-rate').value = selected.budget.inputUsdPerMillion;
      $('#output-rate').value = selected.budget.outputUsdPerMillion;
      $('#monthly-cap').value = selected.budget.monthlyUsdCap;
      if (![...$('#provider-model').options].some(o => o.value === selected.budget.model)) {
        const option = node('option', `${selected.budget.model} (saved)`); option.value = selected.budget.model; $('#provider-model').append(option);
      }
      $('#provider-model').value = selected.budget.model;
    }
    $('#provider-message').textContent = selected?.budget
      ? `Saved model: ${selected.budget.model} · this month spent $${selected.budget.spentUsd.toFixed(4)} + reserved $${selected.budget.reservedUsd.toFixed(4)} of $${selected.budget.monthlyUsdCap.toFixed(2)}. Rates are owner-entered estimates; also set a provider-side cap.`
      : configured.length ? `${configured.length} provider key(s) encrypted at rest. Check a provider catalogue and save verified model rates plus a monthly cap before generation.` : providerState.message;
    const guide=selected?.id === 'openai' && checkedPrices[selected?.budget?.model];
    if (guide && (selected.budget.inputUsdPerMillion !== guide.input || selected.budget.outputUsdPerMillion !== guide.output)) $('#provider-message').textContent += ' Saved prices differ from the checked standard prices for this model. Review them before relying on the cost estimate.';
  } catch (e) { $('#provider-state').textContent = e.message; }
}
$('#use-gpt5-prices').onclick = () => {
  const guide=checkedPrices[$('#provider-model').value];
  if ($('#provider').value !== 'openai' || !guide) return notice('A checked price guide is available for OpenAI GPT-5 and GPT-5.4-mini. Check the provider prices for other models.', true);
  $('#input-rate').value = guide.input; $('#output-rate').value = guide.output;
  notice('Checked model prices filled in. Your monthly spending limit has not changed. Press Save prices and limit to save.');
};
$('#provider').onchange = () => {
  $('#provider-key').value = '';
  $('#provider-model').replaceChildren(node('option', 'Check provider connection first'));
  $('#provider-model').firstChild.value = '';
  refreshProviders();
};
$('#provider-form').onsubmit = e => { e.preventDefault(); guarded(async () => {
  const button = $('#save-provider'); button.disabled = true;
  try {
    await api('provider-key', { provider: $('#provider').value, key: $('#provider-key').value });
    $('#provider-key').value = '';
    $('#provider-model').replaceChildren(node('option', 'Check provider connection first'));
    $('#provider-model').firstChild.value = '';
    notice('Provider key encrypted on the server. It will not be displayed again.');
    await refreshProviders();
  } finally { button.disabled = false; }
}); };
$('#verify-provider').onclick = () => guarded(async () => {
  $('#provider-state').textContent = 'Checking the provider model catalogue…';
  const result = await api(`providers/${encodeURIComponent($('#provider').value)}/models`);
  const modelSelect = $('#provider-model'); modelSelect.replaceChildren();
  modelSelect.append(node('option', 'Select a model from the verified catalogue')); modelSelect.firstChild.value = '';
  for (const model of result.models) { const option = node('option', model); option.value = model; modelSelect.append(option); }
  const saved = providerState?.providers.find(p => p.id === $('#provider').value)?.budget;
  if (saved && result.models.includes(saved.model)) modelSelect.value = saved.model;
  $('#provider-state').textContent = `Key accepted · ${result.models.length} models listed · no model was run`;
  notice(`Connection verified for ${$('#provider').value}. No generation or model charges were made.`);
  await loadRoutes();
});
$('#budget-form').onsubmit = e => { e.preventDefault(); guarded(async () => {
  const provider = $('#provider').value;
  const result = await api('provider-budget', { provider, model: $('#provider-model').value,
    inputUsdPerMillion: Number($('#input-rate').value), outputUsdPerMillion: Number($('#output-rate').value), monthlyUsdCap: Number($('#monthly-cap').value) });
  await refreshProviders();
  notice(`Cost guard saved for ${result.model}; requests remain individually confirmed.`);
}); };
$('#remove-provider').onclick = () => guarded(async () => {
  if (!confirm(`Permanently remove the saved ${$('#provider').value} key? This cannot be undone.`)) return;
  await api(`provider-key/remove/${encodeURIComponent($('#provider').value)}`, {});
  await refreshProviders(); notice('Saved provider key removed.');
});

async function loadRoutes(){
 const data=await api('creative/settings');$('#routes').replaceChildren();
 const names={analysis:'Find gaming moments',titles:'Write titles & ending messages',artwork:'Create opening / ending pictures',music:'Make background music · 30 seconds'};
 const supports=(feature,provider,model)=>provider==='lmstudio'?(feature==='titles'||feature==='analysis'&&(data.localModels||[]).some(m=>m.model===model&&m.vision)):feature==='music'?model==='lyria-3-clip-preview':feature==='artwork'?(provider==='openai'?model.startsWith('gpt-image-'):model.startsWith('gemini-')&&/image|nano-banana/.test(model)):(provider==='openai'?/^gpt-(4o|4\.1|5)/.test(model)&&!model.includes('image'):provider==='anthropic'?model.startsWith('claude-'):model.startsWith('gemini-')&&!/image|banana|tts|embedding/.test(model));
 for(const [feature,providers] of Object.entries(data.features)){
  const form=node('form',undefined,'route-form');form.append(node('h3',names[feature]));
  const provider=node('select'),model=node('select'),reserve=node('input'),inputRate=node('input'),outputRate=node('input');reserve.type='number';reserve.min='.000001';reserve.max='20';reserve.step='any';reserve.value='.25';
  for(const field of [inputRate,outputRate]){field.type='number';field.min='.000001';field.max='10000';field.step='any';field.value='1';field.required=true;}
  for(const p of providers){const o=node('option',p==='google'?'Google Gemini':p==='lmstudio'?'LM Studio · LAN models':p);o.value=p;provider.append(o);}
  const saved=data.routes.find(r=>r.feature===feature);if(saved){provider.value=saved.provider;reserve.value=saved.reserve_usd;inputRate.value=saved.input_rate;outputRate.value=saved.output_rate;}
  function prices(){
   if(!['analysis','titles'].includes(feature))return;
   const local=provider.value==='lmstudio';for(const field of [inputRate,outputRate]){field.disabled=local;field.min=local?'0':'.000001';}
   if(local){inputRate.value=0;outputRate.value=0;return;}
   const profile=providerState?.providers.find(p=>p.id===provider.value)?.budget;
   if(saved&&provider.value===saved.provider&&model.value===saved.model){inputRate.value=saved.input_rate;outputRate.value=saved.output_rate;}
   else if(profile?.model===model.value){inputRate.value=profile.inputUsdPerMillion;outputRate.value=profile.outputUsdPerMillion;}
   else{inputRate.value='';outputRate.value='';}
  }
  function options(){model.replaceChildren();for(const m of data.models.filter(m=>m.provider===provider.value&&supports(feature,m.provider,m.model))){const o=node('option',m.model);o.value=m.model;model.append(o);}if(saved&&provider.value===saved.provider)model.value=saved.model;prices();}
  model.onchange=prices;
  provider.onchange=options;options();
  for(const [title,input] of [['Provider',provider],['Verified model',model],['Per image / music request reserve · USD',reserve],['This model’s input USD per million tokens',inputRate],['This model’s output USD per million tokens',outputRate]]){const label=node('label',title);label.append(input);label.hidden=['analysis','titles'].includes(feature)?input===reserve:[inputRate,outputRate].includes(input);form.append(label);}
  const button=node('button','Save this AI job');form.append(button);
  form.onsubmit=e=>{e.preventDefault();guarded(async()=>{await api('creative/route',{feature,provider:provider.value,model:model.value,reserveUsd:Number(reserve.value),inputRate:Number(inputRate.value),outputRate:Number(outputRate.value)});notice('AI job saved. No generation request was made.');await loadRoutes();});};
  $('#routes').append(form);
 }
}
function buildLMStudio(){
 const section=node('section',undefined,'panel');section.id='lmstudio-section';section.innerHTML=`<h2>Local network models · LM Studio</h2><p>Connect LM Studio on a trusted LAN machine. You can choose different local models for titles and visual analysis. Vision needs a model advertised as vision-capable; text-only models cannot inspect footage. Image and music generation are not supported through this connection.</p><form id="lmstudio-form"><label>LM Studio API address<input id="lmstudio-url" type="url" required placeholder="http://10.0.0.12:1234/v1" maxlength="200"></label><label>Optional LM Studio API token<input id="lmstudio-token" type="password" autocomplete="new-password" maxlength="4096" placeholder="Blank keeps the saved token; never displayed again"></label><label><input id="lmstudio-clear" type="checkbox"> Remove any saved token / use no authentication</label><label><input id="lmstudio-trust" type="checkbox" required> I trust this LAN server. HTTP sends notes, pictures and tokens without encryption.</label><button>Save LAN connection</button></form><div class="row"><button id="lmstudio-check" class="quiet" type="button">Check LM Studio models</button><button id="lmstudio-remove" class="quiet" type="button">Disconnect LM Studio</button></div><p id="lmstudio-status" role="status"></p><div id="lmstudio-models"></div><p class="muted">In LM Studio, start the Developer server and enable Serve on Local Network. Allow its port only from this WMB server in your firewall. Use a private IPv4 address and explicit port (usually 1234), not localhost: localhost inside WMB means its container. Listing models runs no inference. Local inference records no cloud API charge, but uses your hardware/electricity. No automatic cloud fallback. Assign the discovered models below.</p>`;
 $('#routing').before(section);
 $('#lmstudio-form').onsubmit=e=>{e.preventDefault();guarded(async()=>{
  const token=$('#lmstudio-clear').checked?'':$('#lmstudio-token').value||null;
  await api('lmstudio',{baseUrl:$('#lmstudio-url').value,token,trustLan:$('#lmstudio-trust').checked});e.target.reset();await loadLMStudio();await refreshProviders();await loadRoutes();notice('LAN connection saved. Check its model catalogue, then assign the models below. No inference ran.');
 });};
 $('#lmstudio-check').onclick=()=>guarded(async()=>{const button=$('#lmstudio-check');button.disabled=true;try{const result=await api('lmstudio/models');await loadLMStudio();await loadRoutes();notice(`${result.models.length} local models discovered. Catalogue access is verified; inference/quality is not yet verified.`);}finally{button.disabled=false;}});
 $('#lmstudio-remove').onclick=()=>guarded(async()=>{if(!confirm('Disconnect LM Studio and remove its saved token? Local assignments will stop working until you reconnect or explicitly choose another provider.'))return;await api('provider-key/remove/lmstudio',{});$('#lmstudio-url').value='';await loadLMStudio();await refreshProviders();await loadRoutes();notice('LM Studio disconnected. No cloud fallback enabled.');});
}
async function loadLMStudio(){
 const state=await api('lmstudio');if(state.config)$('#lmstudio-url').value=state.config.base_url;
 $('#lmstudio-status').textContent=state.config?`Saved LAN endpoint · ${state.config.token_set?'encrypted token saved':'no authentication token'} · model inference not verified by this check`:'No local server configured.';
 $('#lmstudio-models').replaceChildren();for(const m of state.models){$('#lmstudio-models').append(node('p',`${m.model} · ${m.vision?'text + vision':'text; vision unavailable or unknown'}`));}
 $('#lmstudio-check').disabled=!state.config;$('#lmstudio-remove').disabled=!state.config;
}
buildLMStudio();
loadSettings().catch(()=>{$('#login-panel').hidden=false;$('#workspace').hidden=true;});
