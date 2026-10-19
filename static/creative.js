'use strict';
let creativeProject, creativeSignature;
function creativeDesign(){
 const value=id=>document.getElementById('design-'+id)?.value;
 return {intro:value('intro')||'',outro:value('outro')||'',overlay:value('overlay')||'',music:value('music')||'',position:value('position')||'bottom-right',overlay_size:Number(value('overlay_size')||.25),music_volume:Number(value('music_volume')??.15),music_scope:value('music_scope')||'all'};
}
function buildCreative(){
 if($('#creative-panel'))return;
 const panel=node('section');panel.id='creative-panel';panel.innerHTML=`<h3>Pictures & music</h3><p>Add your own pictures and music, or ask AI to make something. Nothing is added to your edit until you choose it below.</p>
 <form id="asset-form" class="creative-form"><label>Add a picture or music file<input id="asset-file" type="file" accept="image/png,image/jpeg,audio/mpeg,audio/wav,audio/x-wav,audio/mp4,.mp3,.wav,.m4a" required></label><label><input id="asset-rights" type="checkbox" required> I have permission to use this file</label><button>Add to my library</button><small>PNG/JPEG up to 10 MB · MP3/WAV/M4A up to 25 MB. Uploads stay here; pictures are normalised for safe editing.</small></form>
 <button id="capture-still" type="button" class="quiet">Save a picture from the video I am watching</button>
 <p class="muted">Pause Watch original at the frame you want, then save it here. Choose up to three library pictures as AI references. Capturing a still does not call AI.</p>
 <div id="asset-library" class="creative-library"></div><div id="creative-progress"></div>
 <details><summary>Ask AI to make a picture or music</summary><form id="creative-form" class="creative-form"><label>Make something<select id="creative-feature"><option value="artwork">A picture for my video</option><option value="music">Background music · 30 seconds</option></select></label><p id="creative-assignment" class="muted"></p><label>What should it look or sound like?<textarea id="creative-prompt" maxlength="4000" required placeholder="A bright gaming intro, space for my title in the middle, green and gold colours"></textarea></label><label id="creative-shape-label">Picture shape<select id="creative-shape"><option value="1536x1024">Wide</option><option value="1024x1536">Tall</option><option value="1024x1024">Square</option></select></label><label id="creative-alpha-label"><input id="creative-alpha" type="checkbox"> Transparent background (OpenAI artwork only)</label><p class="muted">Select reference pictures above for artwork. Music uses only your description. AI assets may require labelling; review rights and the result before sharing.</p><button>Review cost & make it</button></form></details>
 <h3>Put it in my video</h3><p>Pick a picture for each screen, an optional sticker over the gameplay, and music. Choose None to leave something out. Pictures fit inside the screen without cropping. Wide/tall is an aspect hint for Gemini, not an exact output-size guarantee.</p><div id="creative-placement" class="creative-placement"></div><p class="muted">A picture creates its opening/ending screen even if the text is blank. The sticker stays over the chosen gameplay. Music loops to fit and fades at the start and finish. Original sound follows your Game sound choice above.</p>`;
 $('#packaging-controls').after(panel);
 const presets=node('div',undefined,'row');
 for(const [kind,label] of [['intro','Design my opening'],['outro','Design my subscribe screen'],['overlay','Design a transparent title sticker']]){
  const button=node('button',label,'quiet');button.type='button';
  button.onclick=()=>guarded(async()=>{
   $('#creative-feature').value='artwork'; await updateCreativeAssignment();
   const title=$('#overlay-intro').value||$('#export-title').value||'My best moments';
   const brand=$('#overlay-brand').value||'Watch Me Bro';
   const text=kind==='intro'?title:kind==='outro'?($('#overlay-cta').value||'Like and subscribe'):($('#overlay-headline').value||title);
   if(kind==='intro'&&!$('#overlay-intro').value){$('#overlay-intro').value=title;dirty=true;}
   if(kind==='outro'&&!$('#overlay-cta').value){$('#overlay-cta').value=text;dirty=true;}
   $('#creative-prompt').value=`Professional gaming ${kind==='overlay'?'title sticker':kind==='intro'?'opening screen background':'subscribe end screen background'} for ${JSON.stringify(brand)}. Premium lime, charcoal and warm gold palette, crisp composition, strong contrast, generous safe margins, no watermark. ${kind==='overlay'?`Use the exact title ${JSON.stringify(text)} as bold, highly legible lettering on a transparent background. No extra words. The viewer must review spelling before use.`:'Do not draw letters or words: leave the centre clear for editable, accurately spelled title text added by the video editor.'} Do not invent gameplay, scores, achievements or affiliations.`;
   $('#creative-shape').value=$('#format').value==='vertical'?'1024x1536':'1536x1024';
   $('#creative-alpha').checked=kind==='overlay'&&!$('#creative-alpha').disabled;
   $('#creative-form').closest('details').open=true;
   $('#creative-prompt').focus();
   notice(kind==='overlay'&&$('#creative-alpha').disabled?'Transparent output needs an OpenAI artwork assignment in Settings. No generation has started.':'Design prompt prepared. Select reference stills, review it, then approve the cost. Nothing has been generated yet.');
  });presets.append(button);
 }
 $('#creative-form').closest('details').before(presets);
 for(const [id,title,choices] of [
  ['intro','Opening picture',null],['outro','Ending picture',null],['overlay','Sticker over the gameplay',null],['music','Background music',null],
  ['position','Sticker position',[['bottom-right','Bottom right'],['bottom-left','Bottom left'],['top-right','Top right'],['top-left','Top left'],['centre','Middle']]],
  ['overlay_size','Sticker size',[['.15','Small'],['.25','Medium'],['.45','Large']]],
  ['music_volume','Music volume',[['0','Silent'],['.08','Quiet'],['.15','Soft'],['.3','Louder'],['.6','Very loud']]],
  ['music_scope','Play music during',[['all','The whole video'],['cards','Opening and ending only'],['gameplay','Gameplay only']]]]){
  const label=node('label',title),select=node('select');select.id='design-'+id;select.onchange=()=>{dirty=true;};
  for(const [value,text] of choices||[['','None']]){const option=node('option',text);option.value=['music_volume','overlay_size'].includes(id)?String(Number(value)):value;select.append(option);}
  label.append(select);$('#creative-placement').append(label);
 }
 $('#asset-form').onsubmit=e=>{e.preventDefault();guarded(async()=>{const file=$('#asset-file').files[0];await uploadCreativeAsset(file,file.type.startsWith('image/')?'image':'audio');e.target.reset();});};
 $('#creative-form').onsubmit=e=>{e.preventDefault();guarded(generateCreative);};
 $('#creative-feature').onchange=()=>guarded(updateCreativeAssignment);
 $('#capture-still').onclick=()=>guarded(async()=>{
  const video=$('#source-preview');if(video.hidden||video.readyState<2)throw Error('Open Watch original, pause at your favourite picture, then try again.');
  const canvas=document.createElement('canvas');const scale=Math.min(1,1536/video.videoWidth);canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));await uploadCreativeAsset(new File([blob],`Video still at ${video.currentTime.toFixed(2)}s.png`,{type:'image/png'}),'image');
 });
}
async function uploadCreativeAsset(file,kind){
 if(!active||!file)throw Error('Choose a project and a file first.');
 if(file.size>(kind==='image'?10:25)*1024**2)throw Error('This file is too big for the asset library.');
 const response=await fetch(`api/asset-upload/${active}/${kind}`,{method:'POST',headers:{'X-WMB-Request':'studio','X-Filename':file.name.replace(/[^\x20-\x7e]/g,'_')},body:file});
 const result=await response.json();if(!response.ok)throw Error(result.error||'Asset upload failed.');
 workspace=await api('workspace');await showCreative();notice('Added to your library. Choose where to use it below.');
}
async function updateCreativeAssignment(){
 const data=await api('creative/settings'),feature=$('#creative-feature').value,route=data.routes.find(r=>r.feature===feature);
 $('#creative-assignment').textContent=route?`Assigned AI: ${route.provider} / ${route.model} · local estimate $${route.reserve_usd.toFixed(4)} per request. Change this in Settings.`:'Choose the provider and model for this job on the Settings page first.';
 $('#creative-shape-label').hidden=feature==='music';$('#creative-alpha-label').hidden=feature==='music';
 $('#creative-alpha').disabled=feature!=='artwork'||route?.provider!=='openai';if($('#creative-alpha').disabled)$('#creative-alpha').checked=false;
}
async function showCreative(savedPlan){
 if(!active||!$('#packaging-controls'))return;buildCreative();
 const previous=creativeProject===active?creativeDesign():{};
 const design=savedPlan?.design||previous;
 const assets=(workspace.assets||[]).filter(a=>a.project===active);
 for(const slot of ['intro','outro','overlay','music']){
  const select=$('#design-'+slot);select.replaceChildren();const none=node('option','None');none.value='';select.append(none);
  for(const a of assets.filter(a=>a.kind===(slot==='music'?'audio':'image'))){const option=node('option',a.name);option.value=a.id;select.append(option);}select.value=design[slot]||'';
 }
 for(const [id,fallback] of [['position','bottom-right'],['overlay_size',.25],['music_volume',.15],['music_scope','all']])$('#design-'+id).value=String(design[id]??fallback);
 const signature=JSON.stringify([active,assets.map(a=>a.id)]);
 if(signature!==creativeSignature){
  creativeSignature=signature;$('#asset-library').replaceChildren();
  for(const a of assets){
   const card=node('article',undefined,'asset-card');const media=node(a.kind==='image'?'img':'audio');media.src=`asset/${a.id}`;if(a.kind==='image'){media.alt=a.name;media.loading='lazy';}else{media.controls=true;media.preload='none';}
   const provenance=JSON.parse(a.provenance);card.append(media,node('strong',a.name),node('small',provenance.origin==='generated'?`AI-generated · ${provenance.provider} / ${provenance.model}`:'Your upload · review permission'));
   const download=node('a','Save this asset');download.href=`asset/${a.id}`;download.download=a.kind==='image'?'picture.png':'music.mp3';card.append(download);
   if(a.kind==='image'){
    const label=node('label'),check=node('input');check.type='checkbox';check.value=a.id;check.className='creative-reference';label.append(check,document.createTextNode('Use as AI reference'));card.append(label);
    const actions=node('div',undefined,'row');
    for(const [slot,title] of [['intro','Use as opening'],['outro','Use as ending'],['overlay','Use as sticker']]){
     const button=node('button',title,'quiet');button.type='button';button.onclick=()=>{$('#design-'+slot).value=a.id;dirty=true;notice('Selected for your next export. Save your edit or make a new video to see it.');};actions.append(button);
    }card.append(actions);
   }
   $('#asset-library').append(card);
  }
 }
 creativeProject=active;showCreativeProgress();await updateCreativeAssignment();
}
function showCreativeProgress(){
 if(!$('#creative-progress'))return;
 const root=$('#creative-progress');root.replaceChildren();
 for(const job of (workspace.creativeJobs||[]).filter(j=>j.project===active).slice(0,6)){
  const names={queued:'Waiting to create your asset',running:'AI is creating your asset…',complete:'Ready in your library — choose where it goes below',failed:'Could not finish',interrupted:'Stopped by a restart — not automatically retried'};
  root.append(node('p',`${names[job.state]||job.state}${job.error?' · '+job.error:''}`,'creative-pending'));
 }
}
async function creativeConsent(quote){
 const dialog=node('dialog');dialog.append(node('h2','Make this with AI?'),node('p',`${quote.spec.provider} / ${quote.spec.model} · local request estimate $${quote.spec.reserveUsd.toFixed(4)} USD. Remaining monthly budget $${quote.remainingUsd.toFixed(2)}.`),node('p',quote.disclosure));
 const cancel=node('button','Not now','quiet'),yes=node('button','Yes, create this asset');yes.disabled=!quote.affordable;dialog.append(cancel,yes);document.body.append(dialog);
 return await new Promise(resolve=>{cancel.onclick=()=>dialog.close('cancel');yes.onclick=()=>dialog.close('yes');dialog.addEventListener('close',()=>{const approved=dialog.returnValue==='yes';dialog.remove();resolve(approved);},{once:true});dialog.showModal();});
}
async function generateCreative(){
 const feature=$('#creative-feature').value;
 const body={project:active,feature,prompt:$('#creative-prompt').value,size:$('#creative-shape').value,transparent:feature==='artwork'&&$('#creative-alpha').checked,references:feature==='artwork'?[...document.querySelectorAll('.creative-reference:checked')].map(e=>e.value):[]};
 const quote=await api('creative/quote',body);if(!await creativeConsent(quote))return notice('Nothing was sent to AI.');
 await api('creative/generate',{...body,quote:quote.quote,consent:true,requestId:crypto.randomUUID()});workspace=await api('workspace');showCreativeProgress();notice('Your request is queued. You can keep editing. The asset will appear in this library.');
}
// Polling preserves in-progress edits; refresh only the library when a generation finishes.
setInterval(()=>{if(!workspace||!active)return;showCreativeProgress();const ids=(workspace.assets||[]).filter(a=>a.project===active).map(a=>a.id);if(creativeSignature!==JSON.stringify([active,ids]))guarded(()=>showCreative());},5000);
