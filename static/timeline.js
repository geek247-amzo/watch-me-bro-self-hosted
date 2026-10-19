'use strict';
// Source-relative trims and normalised framing; no AI or server mutation until save/export.
let timelineRow=null,timelineProject=null,timelineSource='',timelineEpoch=0,timelineFrame=0;
let timelineWindow={start:0,end:1},timelineView='clip',timelineDrag=null;
const timelineClamp=(n,lo,hi)=>Math.max(lo,Math.min(hi,n));
const timelineTime=n=>`${Math.floor(Math.max(0,n)/60)}:${(Math.max(0,n)%60).toFixed(2).padStart(5,'0')}`;
function timelineRows(){return [...$('#cuts').children];}
function timelineCuts(){return timelineRows().map(row=>({row,source:row.children[0].value,start:Number(row.children[1].value),end:Number(row.children[2].value)}));}
function timelineCut(){return timelineCuts().find(c=>c.row===timelineRow);}
function timelineCaptionsBefore(){return {cuts:timelineCuts(),captions:JSON.parse($('#captions').value)};}
function rebaseTimelineCaptions(before){
 let oldOffset=0,newOffset=0;const old=before.cuts.map(c=>{const segment={...c,offset:oldOffset};oldOffset+=c.end-c.start;return segment;}),captions=[];
 for(const next of timelineCuts()){
  const previous=old.find(c=>c.row===next.row&&c.source===next.source);
  if(previous)for(const caption of before.captions){
   const a=Math.max(previous.start,previous.start+caption.start-previous.offset,next.start);
   const b=Math.min(previous.end,previous.start+caption.end-previous.offset,next.end);
   if(b>a)captions.push({start:newOffset+a-next.start,end:newOffset+b-next.start,text:caption.text});
  }
  newOffset+=next.end-next.start;
 }
 $('#captions').value=JSON.stringify(captions.sort((a,b)=>a.start-b.start),null,2);
}
function buildTimeline(){
 if($('#visual-editor'))return;
 const panel=node('section');panel.id='visual-editor';panel.innerHTML=`<div class="eyebrow">TRIM & CROP / YOU CHOOSE THE FINAL CUT</div><h3>Make the clip just right.</h3><p>Choose a clip. Drag the green ends to shorten it, or drag the green middle to move the whole selection. Move the playhead to find the exact moment.</p><div id="timeline-clips" class="timeline-clips" aria-label="Chosen clips"></div><p id="timeline-empty" class="muted">Choose an AI moment or add a clip to start editing.</p><div id="timeline-tools" hidden>
 <div class="timeline-previews"><div><h4>Original · drag the crop box to follow the action</h4><div id="crop-stage"><video id="timeline-video" playsinline preload="metadata"></video><div id="crop-box" role="button" tabindex="0" aria-label="Move crop box. Arrow keys move the framing."><span>KEEP THIS PART</span></div></div></div><div><h4>Your export framing</h4><canvas id="crop-preview" width="640" height="360" aria-label="Preview of the selected crop"></canvas><p class="muted">Gameplay preview only. Your titles, pictures and music are added in the export.</p></div></div>
 <div class="row timeline-playback"><button id="timeline-play" type="button">▶ Play my trim</button><button id="timeline-back" class="quiet" type="button" aria-label="Back one thirtieth of a second">− 1/30s</button><button id="timeline-forward" class="quiet" type="button" aria-label="Forward one thirtieth of a second">+ 1/30s</button><output id="timeline-time" aria-live="off"></output></div>
 <div id="timeline-track" aria-label="Source timeline. Click to seek."><canvas id="timeline-filmstrip" width="960" height="90" aria-hidden="true"></canvas><div id="timeline-selection"><button id="trim-start" type="button" class="trim-handle" role="slider" aria-label="Clip start handle">❮</button><span id="timeline-region-label">DRAG TO MOVE CLIP</span><button id="trim-end" type="button" class="trim-handle" role="slider" aria-label="Clip finish handle">❯</button></div><div id="timeline-playhead"></div></div>
 <label>Move the playhead<input id="timeline-scrub" type="range" step="any" min="0" max="1" value="0"></label><div class="timeline-ruler"><span id="timeline-view-start"></span><span id="timeline-view-end"></span></div>
 <div class="row"><button id="trim-at-playhead" class="quiet" type="button">Start here</button><button id="finish-at-playhead" class="quiet" type="button">Finish here</button><label>Timeline view<select id="timeline-view"><option value="clip">Around this clip</option><option value="whole">Whole recording</option></select></label></div><p id="trim-summary" class="edit-summary"></p>
 <div class="row"><label>Picture framing<select id="crop-mode"><option value="fit">Keep the whole picture · may have bars</option><option value="crop">Move a crop · fill the screen</option></select></label><label>Zoom the crop<input id="crop-zoom" type="range" min="1" max="4" step="0.01" value="1"></label><button id="crop-reset" type="button" class="quiet">Centre / reset framing</button></div>
 <div class="row"><button id="timeline-earlier" type="button" class="quiet">Move clip earlier</button><button id="timeline-later" type="button" class="quiet">Move clip later</button><button id="timeline-remove" type="button" class="quiet">Remove this clip</button></div><div class="row"><button id="timeline-style" type="button">Add my styles ↓</button><button id="timeline-export" type="button" class="quiet">Export this clip only</button></div><p class="muted">Changes are kept in your edit. Save my edit keeps them for later. Export this clip only uses your current titles, pictures and music, and keeps your multi-clip edit saved. Originals are never changed.</p></div>`;
 $('#export-title').closest('label').before(panel);
 const video=$('#timeline-video');video.onloadedmetadata=()=>{loadCropControls();syncTimeline();seekTimeline(timelineCut()?.start||0);makeFilmstrip();};
 video.onseeked=()=>{paintTimeline();};video.onloadeddata=paintTimeline;video.oncanplay=paintTimeline;video.ontimeupdate=()=>{boundTimelinePlayback();syncPlayhead();};
 video.onplay=()=>{const cut=timelineCut();if(cut&&(video.currentTime<cut.start||video.currentTime>=cut.end-.005))video.currentTime=cut.start;$('#timeline-play').textContent='❚❚ Pause';tickTimeline();};
 video.onpause=()=>{cancelAnimationFrame(timelineFrame);$('#timeline-play').textContent='▶ Play my trim';paintTimeline();};
 video.onerror=()=>notice('This browser could not play the source. Try Chrome or a supported MP4 recording.',true);
 $('#timeline-play').onclick=()=>guarded(async()=>{if(video.paused)await video.play();else video.pause();});
 $('#timeline-back').onclick=()=>seekTimeline(video.currentTime-1/30);$('#timeline-forward').onclick=()=>seekTimeline(video.currentTime+1/30);
 $('#timeline-scrub').oninput=e=>{video.pause();seekTimeline(Number(e.target.value));};
 $('#timeline-view').onchange=e=>{timelineView=e.target.value;setTimelineWindow();syncTimeline();makeFilmstrip();};
 $('#trim-at-playhead').onclick=()=>guarded(()=>setTimelineTrim(video.currentTime,null));$('#finish-at-playhead').onclick=()=>guarded(()=>setTimelineTrim(null,video.currentTime));
 for(const id of ['trim-start','trim-end','timeline-selection']){
  const control=$('#'+id);control.onpointerdown=e=>guarded(()=>{
   if(e.button!==0)return;e.preventDefault();e.stopPropagation();video.pause();
   const cut=timelineCut();if(!cut)return;timelineDrag={id,clientX:e.clientX,start:cut.start,end:cut.end,before:timelineCaptionsBefore()};control.setPointerCapture(e.pointerId);
  });
  control.onpointermove=e=>{
   if(!timelineDrag||!control.hasPointerCapture(e.pointerId))return;
   const cut=timelineCut();if(!cut)return;const delta=(e.clientX-timelineDrag.clientX)/$('#timeline-track').getBoundingClientRect().width*(timelineWindow.end-timelineWindow.start),min=Math.min(1/30,cut.end-cut.start);
   if(timelineDrag.id==='trim-start')setTimelineTrim(timelineClamp(timelineDrag.start+delta,timelineWindow.start,cut.end-min),null,true);
   else if(timelineDrag.id==='trim-end')setTimelineTrim(null,timelineClamp(timelineDrag.end+delta,cut.start+min,timelineWindow.end),true);
   else{const start=timelineClamp(timelineDrag.start+delta,timelineWindow.start,timelineWindow.end-(timelineDrag.end-timelineDrag.start));setTimelineTrim(start,start+timelineDrag.end-timelineDrag.start,true);}
  };
  control.onpointerup=e=>{if(control.hasPointerCapture(e.pointerId))control.releasePointerCapture(e.pointerId);timelineDrag=null;};control.onpointercancel=()=>{timelineDrag=null;};
 }
 for(const id of ['trim-start','trim-end'])$('#'+id).onkeydown=e=>{
  if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();e.stopPropagation();const cut=timelineCut(),delta=(e.key==='ArrowRight'?1:-1)*(e.shiftKey?1:1/30);
  guarded(()=>setTimelineTrim(id==='trim-start'?cut.start+delta:null,id==='trim-end'?cut.end+delta:null));
 };
 $('#timeline-track').onpointerdown=e=>{const rect=e.currentTarget.getBoundingClientRect();video.pause();seekTimeline(timelineWindow.start+timelineClamp((e.clientX-rect.left)/rect.width,0,1)*(timelineWindow.end-timelineWindow.start));};
 $('#crop-mode').onchange=()=>{setCropFromControls(true);};$('#crop-zoom').oninput=()=>setCropFromControls(false);
 $('#crop-reset').onclick=()=>{$('#crop-zoom').value=1;setCropFromControls(true);};
 const box=$('#crop-box');let pan=null;
 box.onpointerdown=e=>{e.preventDefault();const crop=currentCrop();pan={x:e.clientX,y:e.clientY,crop};box.setPointerCapture(e.pointerId);};
 box.onpointermove=e=>{if(!pan||!box.hasPointerCapture(e.pointerId))return;const rect=sourceDisplayRect();saveCrop({...pan.crop,x:timelineClamp(pan.crop.x+(e.clientX-pan.x)/rect.width,0,1-pan.crop.width),y:timelineClamp(pan.crop.y+(e.clientY-pan.y)/rect.height,0,1-pan.crop.height)});};
 box.onpointerup=()=>{pan=null;};box.onpointercancel=()=>{pan=null;};
 box.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const crop=currentCrop(),step=e.shiftKey?.05:.01;saveCrop({...crop,x:timelineClamp(crop.x+(e.key==='ArrowLeft'?-step:e.key==='ArrowRight'?step:0),0,1-crop.width),y:timelineClamp(crop.y+(e.key==='ArrowUp'?-step:e.key==='ArrowDown'?step:0),0,1-crop.height)});};
 for(const [id,delta] of [['timeline-earlier',-1],['timeline-later',1]])$('#'+id).onclick=()=>guarded(()=>{
  const before=timelineCaptionsBefore(),rows=timelineRows(),index=rows.indexOf(timelineRow),other=rows[index+delta];if(!other)return;
  if(delta<0)other.before(timelineRow);else other.after(timelineRow);rebaseTimelineCaptions(before);dirty=true;updateEditSummary();
 });
 $('#timeline-remove').onclick=()=>guarded(()=>{const before=timelineCaptionsBefore();timelineRow?.remove();timelineRow=null;rebaseTimelineCaptions(before);dirty=true;updateEditSummary();});
 $('#timeline-style').onclick=()=>{$('#packaging-controls').scrollIntoView({behavior:'smooth',block:'start'});notice('Your trim and crop are in the edit. Add your styles, then Make my video.');};
 $('#timeline-export').onclick=()=>guarded(exportTimelineClip);
 $('#format').addEventListener('change',()=>{
  // Reframe explicit crops around their existing centre for the new output shape.
  if(timelineRow&&timelineRow.dataset.crop){loadCropControls();if($('#crop-mode').value==='crop')setCropFromControls(false);}else loadCropControls();paintTimeline();
 });
 window.addEventListener('resize',paintTimeline);
}
function updateTimeline(reset=false){
 if(!workspace||!active||!$('#editor-body')||$('#editor-body').hidden)return;buildTimeline();
 const rows=timelineRows(),oldRow=timelineRow;if(reset||timelineProject!==active||!rows.includes(timelineRow))timelineRow=rows[0]||null;
 if(reset||oldRow!==timelineRow)timelineSource='';
 timelineProject=active;$('#timeline-empty').hidden=!!timelineRow;$('#timeline-tools').hidden=!timelineRow;
 const list=$('#timeline-clips');list.replaceChildren();
 rows.forEach((row,i)=>{const b=node('button',`Clip ${i+1} · ${timelineTime(Number(row.children[2].value)-Number(row.children[1].value))}`,row===timelineRow?'selected':'quiet');b.type='button';b.setAttribute('aria-pressed',String(row===timelineRow));b.onclick=()=>{timelineRow=row;timelineView='clip';$('#timeline-view').value='clip';timelineSource='';updateTimeline();};list.append(b);});
 const video=$('#timeline-video');if(!timelineRow){video.pause();timelineSource='';return;}
 const cut=timelineCut();if(!cut||!Number.isFinite(cut.start)||!Number.isFinite(cut.end)||cut.end<=cut.start)return;
 const key=active+':'+cut.source+':'+rows.indexOf(timelineRow);
 if(timelineSource!==key){timelineSource=key;timelineView='clip';$('#timeline-view').value='clip';video.pause();setTimelineWindow();loadCropControls();
  if(video.dataset.source!==cut.source){video.dataset.source=cut.source;video.src=`file/${cut.source}`;video.load();}
  else{seekTimeline(cut.start);makeFilmstrip();}
 }
 syncTimeline();
}
function setTimelineWindow(){const cut=timelineCut(),source=sources().find(s=>s.id===cut?.source);if(!source)return;const margin=Math.max(3,Math.min(15,(cut.end-cut.start)*.2));timelineWindow=timelineView==='whole'?{start:0,end:source.duration}:{start:Math.max(0,cut.start-margin),end:Math.min(source.duration,cut.end+margin)};}
function syncTimeline(){
 const cut=timelineCut();if(!cut)return;
 // Numeric advanced edits can fall outside the current window: keep them reachable.
 if(cut.start<timelineWindow.start||cut.end>timelineWindow.end)setTimelineWindow();
 const range=timelineWindow.end-timelineWindow.start,pct=t=>100*timelineClamp((t-timelineWindow.start)/range,0,1);
 $('#timeline-selection').style.left=pct(cut.start)+'%';$('#timeline-selection').style.width=(pct(cut.end)-pct(cut.start))+'%';
 const scrub=$('#timeline-scrub');scrub.min=timelineWindow.start;scrub.max=timelineWindow.end;
 $('#timeline-view-start').textContent=timelineTime(timelineWindow.start);$('#timeline-view-end').textContent=timelineTime(timelineWindow.end);
 $('#trim-summary').textContent=`Keep ${timelineTime(cut.start)} → ${timelineTime(cut.end)} · ${(cut.end-cut.start).toFixed(2)} seconds`;
 for(const [id,value] of [['trim-start',cut.start],['trim-end',cut.end]])for(const [attr,val] of [['aria-valuemin',0],['aria-valuemax',sources().find(s=>s.id===cut.source)?.duration||0],['aria-valuenow',value],['aria-valuetext',timelineTime(value)]])$('#'+id).setAttribute(attr,String(val));
 const index=timelineRows().indexOf(timelineRow);$('#timeline-earlier').disabled=index===0;$('#timeline-later').disabled=index===timelineRows().length-1;
 syncPlayhead();paintTimeline();
}
function setTimelineTrim(start,end,dragging=false){
 const cut=timelineCut(),source=sources().find(s=>s.id===cut?.source);if(!cut||!source)return;
 start=start===null?cut.start:start;end=end===null?cut.end:end;
 if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end>source.duration||end-start<1/30-1e-8){if(!dragging)notice('Keep the finish after the start, inside the original recording.',true);return;}
 const before=dragging&&timelineDrag?.before?timelineDrag.before:timelineCaptionsBefore();timelineRow.children[1].value=start;timelineRow.children[2].value=end;rebaseTimelineCaptions(before);dirty=true;
 updateEditSummary();syncTimeline();
}
function seekTimeline(seconds){const video=$('#timeline-video'),source=sources().find(s=>s.id===timelineCut()?.source);if(!video||!source||video.readyState<1)return;video.currentTime=timelineClamp(seconds,0,Math.max(0,source.duration-.001));syncPlayhead();}
function boundTimelinePlayback(){const video=$('#timeline-video'),cut=timelineCut();if(!cut||video.paused)return;if(video.currentTime>=cut.end){video.pause();video.currentTime=cut.end;}}
function tickTimeline(){boundTimelinePlayback();paintTimeline();if(!$('#timeline-video').paused)timelineFrame=requestAnimationFrame(tickTimeline);}
function syncPlayhead(){const video=$('#timeline-video'),cut=timelineCut();if(!video||!cut)return;$('#timeline-scrub').value=video.currentTime;$('#timeline-playhead').style.left=100*timelineClamp((video.currentTime-timelineWindow.start)/(timelineWindow.end-timelineWindow.start),0,1)+'%';$('#timeline-time').textContent=`Source ${timelineTime(video.currentTime)} · clip ${timelineTime(video.currentTime-cut.start)}`;}
function baseCrop(zoom=1,centre={x:.5,y:.5}){
 const video=$('#timeline-video'),aspect=$('#format').value==='vertical'?9/16:16/9,sourceAspect=(video?.videoWidth||16)/(video?.videoHeight||9);
 const width=Math.min(1,aspect/sourceAspect)/zoom,height=Math.min(1,sourceAspect/aspect)/zoom;
 return {mode:'crop',x:timelineClamp(centre.x-width/2,0,1-width),y:timelineClamp(centre.y-height/2,0,1-height),width,height};
}
function currentCrop(){if(timelineRow?.dataset.crop)return JSON.parse(timelineRow.dataset.crop);return $('#format').value==='vertical'?baseCrop():{mode:'fit'};}
function loadCropControls(){if(!timelineRow)return;const crop=currentCrop();$('#crop-mode').value=crop.mode;const base=baseCrop();$('#crop-zoom').value=crop.mode==='crop'?timelineClamp(Math.min(base.width/crop.width,base.height/crop.height),1,4):1;$('#crop-zoom').disabled=crop.mode==='fit';paintTimeline();}
function setCropFromControls(centre){
 const crop=currentCrop(),point=centre||crop.mode==='fit'?{x:.5,y:.5}:{x:crop.x+crop.width/2,y:crop.y+crop.height/2};
 saveCrop($('#crop-mode').value==='fit'?{mode:'fit'}:baseCrop(Number($('#crop-zoom').value),point));$('#crop-zoom').disabled=$('#crop-mode').value==='fit';
}
function saveCrop(crop){if(!timelineRow)return;timelineRow.dataset.crop=JSON.stringify(crop);dirty=true;paintTimeline();}
function sourceDisplayRect(){const stage=$('#crop-stage'),video=$('#timeline-video'),width=stage.clientWidth,height=stage.clientHeight,ratio=(video.videoWidth||16)/(video.videoHeight||9),w=Math.min(width,height*ratio),h=w/ratio;return {x:(width-w)/2,y:(height-h)/2,width:w,height:h};}
function paintTimeline(){
 const video=$('#timeline-video'),canvas=$('#crop-preview');if(!video||!canvas||!timelineRow)return;syncPlayhead();
 const vertical=$('#format').value==='vertical';if(canvas.width!==(vertical?360:640)){canvas.width=vertical?360:640;canvas.height=vertical?640:360;}
 const ctx=canvas.getContext('2d'),crop=currentCrop(),box=$('#crop-box');box.hidden=crop.mode!=='crop'||video.readyState<1;
 if(video.readyState<2)return;
 ctx.fillStyle='#000';ctx.fillRect(0,0,canvas.width,canvas.height);
 if(crop.mode==='crop'){const rect=sourceDisplayRect();box.style.left=rect.x+crop.x*rect.width+'px';box.style.top=rect.y+crop.y*rect.height+'px';box.style.width=crop.width*rect.width+'px';box.style.height=crop.height*rect.height+'px';
  const scale=Math.min(canvas.width/(video.videoWidth*crop.width),canvas.height/(video.videoHeight*crop.height)),w=video.videoWidth*crop.width*scale,h=video.videoHeight*crop.height*scale;
  ctx.drawImage(video,video.videoWidth*crop.x,video.videoHeight*crop.y,video.videoWidth*crop.width,video.videoHeight*crop.height,(canvas.width-w)/2,(canvas.height-h)/2,w,h);
 }else{const scale=Math.min(canvas.width/video.videoWidth,canvas.height/video.videoHeight),w=video.videoWidth*scale,h=video.videoHeight*scale;ctx.drawImage(video,(canvas.width-w)/2,(canvas.height-h)/2,w,h);}
}
async function makeFilmstrip(){
 const epoch=++timelineEpoch,source=timelineCut()?.source,window={...timelineWindow};if(!source)return;
 const canvas=$('#timeline-filmstrip'),ctx=canvas.getContext('2d');ctx.fillStyle='#111914';ctx.fillRect(0,0,canvas.width,canvas.height);
 const video=document.createElement('video');video.muted=true;video.preload='auto';video.src=`file/${source}`;
 const wait=(event)=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>{cleanup();reject(Error('Preview timeout'));},12000);const done=()=>{cleanup();resolve();},fail=()=>{cleanup();reject(Error('Unsupported preview'));};function cleanup(){clearTimeout(timer);video.removeEventListener(event,done);video.removeEventListener('error',fail);}video.addEventListener(event,done,{once:true});video.addEventListener('error',fail,{once:true});});
 try{await wait('loadedmetadata');for(let i=0;i<8&&epoch===timelineEpoch;i++){const t=window.start+(i+.5)/8*(window.end-window.start);const ready=wait('seeked');video.currentTime=Math.min(video.duration-.001,t);await ready;if(epoch!==timelineEpoch)break;ctx.drawImage(video,i*120,0,120,90);}}
 catch{/* Filmstrip is optional; scrub/playback and saved trims remain available. */}
 finally{video.pause();video.removeAttribute('src');video.load();}
}
async function exportTimelineClip(){
 const cut=timelineCut();if(!cut)return;const full=plan(),index=timelineRows().indexOf(timelineRow),offset=full.cuts.slice(0,index).reduce((sum,c)=>sum+c.end-c.start,0),duration=cut.end-cut.start;
 const captions=full.captions.map(c=>({...c,start:Math.max(0,c.start-offset),end:Math.min(duration,c.end-offset)})).filter(c=>c.end>c.start);
 const overlay={...full.overlay};
 if(overlay.headline){
  const start=Math.max(0,(overlay.headline_start??0)-offset),end=Math.min(duration,(overlay.headline_end??3)-offset);
  if(end>start){overlay.headline_start=start;overlay.headline_end=end;}else{overlay.headline='';overlay.headline_start=0;overlay.headline_end=Math.min(3,duration);}
 }
 const single={...full,title:full.title+` · Clip ${index+1}`,cuts:[full.cuts[index]],captions,overlay};
 const button=$('#timeline-export');button.disabled=true;
 try{await api('plan',{project:active,plan:full});await api('render',{project:active,plan:single,preservePlan:true});dirty=false;await refresh(true);notice('This trimmed clip is being made with your current styles. Your full edit is saved and unchanged.');$('#queue').scrollIntoView({behavior:'smooth',block:'start'});}
 finally{button.disabled=false;}
}
if(typeof workspace!=='undefined'&&workspace)updateTimeline();
