/* UTC source coordinates only. Shot-local camera seconds and music never enter this axis. */
(function(root){
 'use strict';
 const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
 function domain(frames){if(!frames.length)return null;return [Date.parse(frames[0].utc),Date.parse(frames.at(-1).utc)];}
 function nearest(frames,time){if(!frames.length)return -1;let lo=0,hi=frames.length;while(lo<hi){const mid=(lo+hi)>>1;if(Date.parse(frames[mid].utc)<time)lo=mid+1;else hi=mid;}if(!lo)return 0;if(lo===frames.length)return lo-1;return time-Date.parse(frames[lo-1].utc)<=Date.parse(frames[lo].utc)-time?lo-1:lo;}
 function fit(bounds){return bounds[1]>bounds[0]?[...bounds]:[bounds[0]-300000,bounds[1]+300000];}
 function viewWithin(start,span,bounds){const full=fit(bounds),size=clamp(span,Math.min(60000,full[1]-full[0]),full[1]-full[0]),left=clamp(start,full[0],full[1]-size);return [left,left+size];}
 function geometry(range,view){const span=view[1]-view[0];return {left:(range[0]-view[0])/span*100,width:(range[1]-range[0])/span*100};}
 function range(project,track,T){return [Date.parse(T.weatherTime(project,0,track.id)),Date.parse(T.weatherTime(project,T.duration(project,track.id),track.id))];}
 function change(range,action,delta,bounds,frames){
  let [start,end]=range;const snap=time=>Date.parse(frames[nearest(frames,clamp(time,...bounds))].utc);
  if(action==='move'){const length=end-start;start=snap(start+delta);start=clamp(start,bounds[0],Math.max(bounds[0],bounds[1]-length));end=Math.min(bounds[1],start+length);}
  else if(action==='left')start=Math.min(end,snap(start+delta));
  else if(action==='right')end=Math.max(start,snap(end+delta));
  else throw Error('未知UTC调整方式');
  return {mode:'mapped',startUtc:new Date(start).toISOString(),endUtc:new Date(end).toISOString()};
 }
 function create(api){
  const $=id=>document.getElementById(id),panel=$('utcPanel'),T=root.EarthTimeline;
  let view=null,bounds=null,selection=null,gesture=null,signature='',frameSignature='',suppressClickUntil=0,selectMode=false,pendingBrowse=null,browseFrame=0,queuedIndex=null;
  const frames=()=>api.frames(),pixelTime=(x,rect)=>view[0]+clamp((x-rect.left)/rect.width,0,1)*(view[1]-view[0]);
  const utc=time=>new Date(time).toISOString(),label=time=>utc(time).slice(5,16).replace('T',' ');
  function fields(){if(!selection)return;$('utcFrom').value=utc(selection[0]).slice(0,19);$('utcTo').value=utc(selection[1]).slice(0,19);$('utcCreate').disabled=false;
   const [a,b]=selection,from=nearest(frames(),a),to=nearest(frames(),b);$('utcSelectionLabel').textContent=`已选 ${label(a)} → ${label(b)} UTC · ${to-from+1}个扫描节点（含缺档）`;
  }
  function selectedOverlay(){const box=$('utcSelection');box.hidden=!selection;if(!selection||!view)return;const g=geometry(selection,view);box.style.left=g.left+'%';box.style.width=Math.max(.3,g.width)+'%';}
  function heads(){const actual=Date.parse(api.utc?.()??api.localUTC?.());
   if(pendingBrowse&&(actual===pendingBrowse.time||performance.now()>pendingBrowse.until)&&gesture?.type!=='scrub')pendingBrowse=null;
   const time=pendingBrowse?.time??actual,inside=view&&Number.isFinite(time)&&time>=view[0]&&time<=view[1];
   for(const e of panel.querySelectorAll('.utcHead')){e.hidden=!inside;if(inside)e.style.left=(time-view[0])/(view[1]-view[0])*100+'%';}
   if(gesture?.type!=='shot'&&Number.isFinite(time))$('utcReadout').textContent=utc(time).slice(0,19).replace('T',' ')+' UTC';
   if(frames().length&&Number.isFinite(time)){$('utcBaseLane').setAttribute('aria-valuenow',String(nearest(frames(),time)));$('utcBaseLane').setAttribute('aria-valuetext',utc(time));}
  }
  function flushBrowse(){if(browseFrame)cancelAnimationFrame(browseFrame);browseFrame=0;if(queuedIndex!==null){const index=queuedIndex;queuedIndex=null;api.browse(index);}}
  function scrub(x,rect){const index=nearest(frames(),pixelTime(x,rect));if(gesture.index===index)return;gesture.index=index;
   pendingBrowse={time:Date.parse(frames()[index].utc),until:performance.now()+2000};queuedIndex=index;heads();
   if(!browseFrame)browseFrame=requestAnimationFrame(flushBrowse);
  }
  $('utcSelectMode').onclick=()=>{selectMode=!selectMode;$('utcSelectMode').setAttribute('aria-pressed',String(selectMode));$('utcBaseLane').classList.toggle('selectRange',selectMode);};
  function axis(){const ruler=$('utcRuler');ruler.replaceChildren();if(!view)return;
   const intervals=[60000,300000,600000,900000,1800000,3600000,7200000,10800000,21600000,43200000,86400000,172800000,604800000,2592000000];
   const interval=intervals.find(n=>n>=(view[1]-view[0])/Math.max(3,Math.floor(ruler.clientWidth/140)))??intervals.at(-1);
   for(let time=Math.ceil(view[0]/interval)*interval;time<=view[1];time+=interval){const mark=document.createElement('span');mark.className='utcTick';mark.style.left=(time-view[0])/(view[1]-view[0])*100+'%';const text=document.createElement('small');text.textContent=label(time);mark.append(text);ruler.append(mark);}
   ruler.title=label(view[0])+' → '+label(view[1])+' UTC · 滚轮缩放，中键平移';
  }
  function observations(){const canvas=$('utcObservations'),lane=$('utcBaseLane'),ratio=Math.min(2,window.devicePixelRatio||1),width=lane.clientWidth,height=lane.clientHeight;
   canvas.width=Math.max(1,Math.round(width*ratio));canvas.height=Math.max(1,Math.round(height*ratio));const context=canvas.getContext('2d');context.scale(ratio,ratio);context.clearRect(0,0,width,height);if(!view)return;
   context.strokeStyle='#31475a';context.beginPath();context.moveTo(0,height/2);context.lineTo(width,height/2);context.stroke();const bins=new Map();
   for(const f of frames()){const time=Date.parse(f.utc);if(time<view[0]||time>view[1])continue;const x=Math.round((time-view[0])/(view[1]-view[0])*Math.max(1,width-2));bins.set(x,(bins.get(x)||false)||!!f.missing);}
   for(const [x,missing]of bins){context.fillStyle=missing?'#e6a54f':'#73bcb9';context.fillRect(x,missing?height*.25:height*.35,2,missing?height*.5:height*.3);}
   selectedOverlay();
  }
  function paint(){
   axis();observations();const p=api.project(),rows=[];
   for(const t of p.tracks){const times=range(p,t,T);if(!times.every(Number.isFinite))continue;
    const row=document.createElement('div');row.className='utcGridRow utcShot'+(t.id===api.active()?' selected':'');row.dataset.track=t.id;
    const name=document.createElement('button');name.className='utcRowLabel';name.textContent=t.name;name.title=t.name;name.onclick=()=>api.select(t.id);
    const lane=document.createElement('div');lane.className='utcLane';
    const button=document.createElement('button');button.className='utcClip';button.dataset.track=t.id;button.dataset.action='move';const g=geometry(times,view);
    button.style.left=g.left+'%';button.style.width=Math.max(.6,g.width)+'%';button.title=`${t.name}\n${utc(times[0])} → ${utc(times[1])}\n镜头 ${T.duration(p,t.id)}秒；拖动仅修改UTC范围`;
    const text=document.createElement('span');text.className='utcClipName';text.textContent=`${t.name} · ${T.duration(p,t.id).toFixed(1)}s`;
    for(const side of ['left','right']){const handle=document.createElement('span');handle.className='utcEdge '+side;handle.dataset.action=side;handle.dataset.track=t.id;handle.title=(side==='left'?'开始':'结束')+'UTC';button.append(handle);}
    button.append(text);button.onclick=()=>{if(performance.now()<suppressClickUntil)return;api.select(t.id);};
    const head=document.createElement('div');head.className='utcHead';lane.append(button,head);row.append(name,lane);rows.push(row);
   }
   const container=$('utcShots'),scroll=container.scrollTop;container.replaceChildren(...rows);container.scrollTop=scroll;heads();
  }
  function render(){const f=frames(),dataKey=f.length+':'+f[0]?.utc+':'+f.at(-1)?.utc;
   if(dataKey!==frameSignature){frameSignature=dataKey;bounds=domain(f);view=bounds?fit(bounds):null;selection=null;signature='';$('utcCreate').disabled=true;
    pendingBrowse=null;if(bounds){$('utcFrom').value=utc(bounds[0]).slice(0,19);$('utcTo').value=utc(bounds[1]).slice(0,19);$('utcSelectionLabel').textContent=`${f.length}个观测节点 · 左键拖动浏览天气；Shift＋拖动或“框选UTC”选择镜头范围。`;}
    $('utcBaseLane').setAttribute('aria-valuemin','0');$('utcBaseLane').setAttribute('aria-valuemax',String(Math.max(0,f.length-1)));
    $('utcBase').max=Math.max(0,f.length-1);$('utcBase').disabled=!f.length;
   }
   const p=api.project(),key=JSON.stringify([view,api.active(),p.fps,p.sourcePlayback,p.weather,p.tracks.map(t=>[t.id,t.name,t.duration,t.weather])]);
   if(key!==signature){signature=key;if(view)paint();else{$('utcRuler').textContent='载入卫星素材后显示UTC刻度';$('utcShots').replaceChildren();observations();}}else heads();
  }
  function zoom(factor,anchor=.5){if(!view)return;const time=view[0]+(view[1]-view[0])*anchor,span=(view[1]-view[0])*factor;view=viewWithin(time-span*anchor,span,bounds);signature='';render();}
  function pan(fraction){if(!view)return;view=viewWithin(view[0]+(view[1]-view[0])*fraction,view[1]-view[0],bounds);signature='';render();}
  $('utcFit').onclick=()=>{if(bounds){view=fit(bounds);signature='';render();}};$('utcZoomIn').onclick=()=>zoom(.5);$('utcZoomOut').onclick=()=>zoom(2);$('utcPanLeft').onclick=()=>pan(-.4);$('utcPanRight').onclick=()=>pan(.4);
  panel.addEventListener('wheel',e=>{if(!view||!e.target.closest('#utcRuler,#utcBaseLane'))return;e.preventDefault();const rect=$('utcBaseLane').getBoundingClientRect();zoom(Math.exp(clamp(e.deltaY,-100,100)*.006),clamp((e.clientX-rect.left)/rect.width,0,1));},{passive:false});
  panel.addEventListener('pointerdown',e=>{
   if(!view||!bounds||!frames().length)return;const lane=e.target.closest('.utcLane,#utcBaseLane,#utcRuler');if(!lane)return;
   if(e.button===1){e.preventDefault();api.halt();gesture={type:'pan',x:e.clientX,view:[...view],width:lane.clientWidth};panel.setPointerCapture(e.pointerId);return;}
   if(e.button!==0)return;
   const clip=e.target.closest('.utcClip');
   if(clip){e.preventDefault();api.halt();const t=api.project().tracks.find(t=>t.id===clip.dataset.track);gesture={type:'shot',x:e.clientX,width:lane.clientWidth,view:[...view],range:range(api.project(),t,T),track:t.id,action:e.target.dataset.action??'move',clip,moved:false};panel.setPointerCapture(e.pointerId);}
   else if(lane.id==='utcBaseLane'||lane.id==='utcRuler'){e.preventDefault();api.halt();lane.focus();const rect=lane.getBoundingClientRect();
    if(lane.id==='utcBaseLane'&&(selectMode||e.shiftKey)){const time=Date.parse(frames()[nearest(frames(),pixelTime(e.clientX,rect))].utc);gesture={type:'select',x:e.clientX,time,rect};selection=[time,time];selectedOverlay();fields();}
    else{gesture={type:'scrub',rect,index:null};scrub(e.clientX,rect);}
    panel.setPointerCapture(e.pointerId);
   }
  });
  panel.addEventListener('pointermove',e=>{
   if(!gesture){if(view&&e.target.closest('#utcBaseLane')){const i=nearest(frames(),pixelTime(e.clientX,$('utcBaseLane').getBoundingClientRect())),f=frames()[i];if(f)$('utcBaseLane').title=f.utc+(f.missing?' · 缺档':' · 真实观测');}return;}
   const g=gesture;
   if(g.type==='scrub')scrub(e.clientX,g.rect);
   if(g.type==='pan'){view=viewWithin(g.view[0]-(e.clientX-g.x)/g.width*(g.view[1]-g.view[0]),g.view[1]-g.view[0],bounds);signature='';render();}
   if(g.type==='select'){const time=Date.parse(frames()[nearest(frames(),pixelTime(e.clientX,g.rect))].utc);selection=[Math.min(g.time,time),Math.max(g.time,time)];selectedOverlay();fields();}
   if(g.type==='shot'){if(Math.abs(e.clientX-g.x)<3&&!g.moved)return;g.moved=true;g.candidate=change(g.range,g.action,(e.clientX-g.x)/g.width*(g.view[1]-g.view[0]),bounds,frames());const next=[Date.parse(g.candidate.startUtc),Date.parse(g.candidate.endUtc)],geometryNext=geometry(next,view);g.clip.style.left=geometryNext.left+'%';g.clip.style.width=Math.max(.6,geometryNext.width)+'%';$('utcReadout').textContent=label(next[0])+' → '+label(next[1])+' UTC';}
  });
  function finish(e){const g=gesture;if(!g)return;if(g.type==='scrub'){scrub(e.clientX,g.rect);flushBrowse();}gesture=null;
   if(g.type==='select'&&Math.abs(e.clientX-g.x)<3)api.browse(nearest(frames(),g.time));
   if(g.type==='shot'&&g.moved&&g.candidate){suppressClickUntil=performance.now()+120;api.edit(()=>api.changeWeather(g.track,g.candidate))();signature='';render();}
   else if(g.type==='shot')api.select(g.track);
  }
  panel.addEventListener('pointerup',finish);panel.addEventListener('pointercancel',()=>{flushBrowse();gesture=null;signature='';render();});
  $('utcBaseLane').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key)||!frames().length)return;e.preventDefault();const i=nearest(frames(),Date.parse(api.utc?.()??frames()[0].utc));api.halt();api.browse(clamp(i+(e.key==='ArrowRight'?1:-1),0,frames().length-1));});
  $('utcBase').oninput=()=>{api.halt();api.browse(Number($('utcBase').value));};
  for(const id of ['utcFrom','utcTo'])$(id).onchange=()=>{const start=Date.parse($('utcFrom').value+'Z'),end=Date.parse($('utcTo').value+'Z');if(!bounds||!Number.isFinite(start)||!Number.isFinite(end)||start>end||start<bounds[0]||end>bounds[1]){api.message('UTC范围必须位于已载入素材中，且起点不能晚于终点',true);return;}selection=[start,end];selectedOverlay();fields();};
  $('utcCreate').onclick=api.edit(()=>{if(!selection)throw Error('先在Satellite Base拖选UTC范围');api.create({mode:'mapped',startUtc:utc(selection[0]),endUtc:utc(selection[1])});});
  new ResizeObserver(()=>{if(view)paint();}).observe($('utcBaseLane'));
  return {render,getView:()=>view&&[...view],getSelection:()=>selection&&[...selection]};
 }
 const api={domain,nearest,fit,viewWithin,geometry,range,change,create};if(typeof module!=='undefined')module.exports=api;root.EarthUtcTimeline=api;
})(globalThis);
