/* One audition track, local media, Web Audio scheduling tied to the editor playhead. */
(function(root){
 'use strict';
 function create(api){
  const M=root.EarthMusic,$=id=>document.getElementById(id),copy=x=>JSON.parse(JSON.stringify(x));
  let selected=null,signature='',context=null,source=null,gain=null,anchor=null,epoch=0,drag=null,loading=0;
  const buffers=new Map(),pending=new Map();
  const status=(text,error=false)=>{$('musicStatus').textContent=text;$('musicStatus').classList.toggle('error',error);};
  const audio=()=>context??=(new AudioContext());
  const current=()=>M.plan(api.project().music,api.active());
  const clip=()=>current().clips.find(c=>c.id===selected);
  function stop(){epoch++;try{source?.stop();}catch{}source?.disconnect();gain?.disconnect();source=null;gain=null;anchor=null;}
  function db(){return new Promise((resolve,reject)=>{const r=indexedDB.open('earthstudio.music.assets.v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('files');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
  async function stored(id,value){const d=await db();try{return await new Promise((resolve,reject)=>{const tx=d.transaction('files',value?'readwrite':'readonly'),r=value?tx.objectStore('files').put(value,id):tx.objectStore('files').get(id);let result;r.onsuccess=()=>{result=r.result;};tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error??Error('音乐本地存储失败'));});}finally{d.close();}}
  async function decode(asset,bytes){
   // Probe duration before expanding compressed music into a potentially multi-GB PCM buffer.
   const probe=new Audio(),url=URL.createObjectURL(new Blob([bytes]));
   let duration;
   try{duration=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('音乐时长读取超时')),10000);probe.onloadedmetadata=()=>{clearTimeout(timer);resolve(probe.duration);};probe.onerror=()=>{clearTimeout(timer);reject(Error('无法读取音乐，请使用有效WAV/MP3'));};probe.preload='metadata';probe.src=url;});}
   finally{probe.removeAttribute('src');probe.load();URL.revokeObjectURL(url);}
   if(!Number.isFinite(duration)||duration<=0||duration>7200||duration*audio().sampleRate*2*4>256*1024*1024)throw Error('音乐超出当前试听内存预算，请先选取较短的音乐文件（立体声解码预算256MiB）');
   const buffer=await audio().decodeAudioData(bytes);
   if(buffer.length*buffer.numberOfChannels*4>256*1024*1024)throw Error('音乐解码超过256MiB，请选取较短文件');
   buffers.delete(asset.id);buffers.set(asset.id,buffer);while(buffers.size>2){const first=buffers.keys().next().value;if(first===anchor?.assetId)break;buffers.delete(first);}
   return buffer;
  }
  function load(asset){
   if(buffers.has(asset.id))return Promise.resolve(buffers.get(asset.id));
   if(pending.has(asset.id))return pending.get(asset.id);
   const task=(async()=>{let bytes;if(asset.url){const response=await fetch(asset.url);if(!response.ok)throw Error('本机音乐副本缺失，请重新导入同一文件');bytes=await response.arrayBuffer();}else{const file=await stored(asset.id);if(!file)throw Error('音乐未在此设备找到，请重新导入');bytes=await file.arrayBuffer();}return decode(asset,bytes);})();
   pending.set(asset.id,task);task.finally(()=>pending.delete(asset.id)).catch(()=>{});return task;
  }
  async function imported(asset,bytes){
   const shot=api.active(),buffer=bytes?await decode(asset,bytes):await load(asset);
   asset={...asset,duration:buffer.duration,peaks:M.peaks(buffer)};
   api.edit(()=>{api.halt();api.project().music=M.edit(api.project().music,shot,(p,m)=>{const index=m.assets.findIndex(a=>a.id===asset.id);if(index<0)m.assets.push(asset);else m.assets[index]=asset;
    if(!p.clips.some(c=>c.assetId===asset.id)){const end=p.clips.reduce((v,c)=>Math.max(v,c.start+c.out-c.in),0),length=Math.min(asset.duration,Math.max(.01,api.length()-end));const c={id:M.id(),assetId:asset.id,start:end,in:0,out:length,gain:1,fadeIn:0,fadeOut:0,muted:false};p.clips.push(c);selected=c.id;}});api.persist();signature='';render();})();
   status('音乐已保存在本机。拖波形主体移动、两端裁切、上角淡变；所有参数保持真实秒数。');
  }
  $('musicImport').onclick=()=>{api.halt();if(window.chrome?.webview){loading++;status('请选择本地WAV或MP3…');window.chrome.webview.postMessage({type:'music-import'});}else $('musicFile').click();};
  window.chrome?.webview?.addEventListener('message',async event=>{const m=event.data;if(m?.type!=='music-imported')return;loading=Math.max(0,loading-1);try{if(m.cancelled){status('已取消音乐选择');return;}if(m.error)throw Error(m.error);await imported(m.asset);}catch(e){status(e.message,true);}});
  $('musicFile').onchange=async()=>{try{const file=$('musicFile').files[0];if(!file)return;if(!/\.(wav|mp3)$/i.test(file.name)||file.size>100*1024*1024)throw Error('请选择100MB以内WAV/MP3');const bytes=await file.arrayBuffer(),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');await stored(hash,file);await imported({id:hash,name:file.name},bytes);}catch(e){status(e.message,true);}finally{$('musicFile').value='';}};
  function change(fn){api.edit(()=>{api.halt();api.project().music=M.edit(api.project().music,api.active(),fn);signature='';api.persist();render();})();}
  $('musicClips').onchange=()=>{selected=$('musicClips').value;signature='';render();};
  $('musicApply').onclick=()=>change(p=>{const c=p.clips.find(c=>c.id===selected);if(!c)throw Error('先导入或选择音乐片段');for(const [id,key] of [['musicStart','start'],['musicIn','in'],['musicOut','out'],['musicFadeIn','fadeIn'],['musicFadeOut','fadeOut']]){if($(id).value.trim()==='')throw Error('请填写音乐参数');c[key]=Number($(id).value);}c.gain=Number($('musicGain').value)/100;});
  $('musicDelete').onclick=()=>change(p=>{p.clips=p.clips.filter(c=>c.id!==selected);selected=null;});
  $('musicAdd').onclick=()=>change((p,m)=>{const a=m.assets.find(a=>a.id===clip()?.assetId)??m.assets.at(-1);if(!a)throw Error('请先导入音乐');const start=p.clips.reduce((v,c)=>Math.max(v,c.start+c.out-c.in),0);const c={id:M.id(),assetId:a.id,start,in:0,out:Math.min(a.duration,Math.max(.01,api.length()-start)),gain:1,fadeIn:0,fadeOut:0,muted:false};p.clips.push(c);selected=c.id;});
  $('musicMute').onchange=()=>change(p=>{const c=p.clips.find(c=>c.id===selected);if(c)c.muted=$('musicMute').checked;});
  $('musicEnabled').onchange=()=>change((p,m)=>{m.enabled=$('musicEnabled').checked;});
  $('musicMark').onclick=()=>change(p=>{const marker={id:M.id(),time:api.time(),name:$('musicMarkerName').value.trim()||'标记 '+(p.markers.length+1)};p.markers.push(marker);});
  $('musicMarkerDelete').onclick=()=>change(p=>{p.markers=p.markers.filter(m=>m.id!==$('musicMarkers').value);});
  $('musicMarkers').onchange=()=>{const m=current().markers.find(m=>m.id===$('musicMarkers').value);if(m){api.halt();status('标记 '+m.name+' 位于 '+m.time.toFixed(3)+'秒；选择相机关键帧后点击对齐。');}};
  $('musicAlign').onclick=()=>{const m=current().markers.find(m=>m.id===$('musicMarkers').value);if(!m){status('请先选择音乐标记',true);return;}api.align(m.time);};
  for(const id of ['musicStart','musicIn','musicOut','musicGain','musicFadeIn','musicFadeOut','musicLoopIn','musicLoopOut'])$(id).onfocus=api.halt;
  function render(){
   const p=current(),m=api.project().music,key=JSON.stringify([api.active(),api.length(),p,m?.assets.map(a=>[a.id,a.name]),m?.enabled]);
   if(signature===key)return;signature=key;if(!p.clips.some(c=>c.id===selected))selected=p.clips[0]?.id;
   $('musicClips').replaceChildren(...p.clips.map((c,i)=>new Option((i+1)+'. '+(m.assets.find(a=>a.id===c.assetId)?.name??'缺失音乐'),c.id)));$('musicClips').value=selected??'';
   $('musicEnabled').disabled=!p.clips.length;$('musicEnabled').checked=!!p.clips.length&&m?.enabled!==false;
   const c=clip();for(const [id,key]of [['musicStart','start'],['musicIn','in'],['musicOut','out'],['musicFadeIn','fadeIn'],['musicFadeOut','fadeOut']]){$(id).value=c?Number(c[key].toFixed(4)):'';$(id).disabled=!c;}
   $('musicGain').value=c?c.gain*100:'';$('musicGain').disabled=!c;$('musicMute').checked=!!c?.muted;
   const marker=$('musicMarkers').value;$('musicMarkers').replaceChildren(...p.markers.map(m=>new Option(m.name+' · '+m.time.toFixed(3)+'秒',m.id)));if(p.markers.some(m=>m.id===marker))$('musicMarkers').value=marker;
   if(c&&c.start+c.out-c.in>api.length()+1e-5)status('音乐片段超出镜头；超出部分不播放，源区间和位置仍保留。');
   draw();
  }
  function svg(tag,attrs){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e;}
  function draw(preview){const wave=$('musicWave'),length=api.length(),music=api.project().music;wave.replaceChildren();
   for(let i=0;i<=10;i++){const text=svg('text',{x:i*99+2,y:74,fill:'#9caec2','font-size':10});text.textContent=(length*i/10).toFixed(1)+'s';wave.append(text);}
   for(const original of current().clips){const c=preview?.id===original.id?preview:original,a=music.assets.find(a=>a.id===c.assetId),x=c.start/length*1000,w=(c.out-c.in)/length*1000;
    wave.append(svg('rect',{x,y:12,width:w,height:43,class:'clipBody','data-clip':c.id,'data-action':'move'}));
    if(a?.peaks){const points=[];for(let i=0;i<=Math.min(800,Math.ceil(w));i++){const progress=i/Math.max(1,Math.min(800,Math.ceil(w))),t=c.in+progress*(c.out-c.in),v=a.peaks[Math.min(a.peaks.length-1,Math.floor(t/a.duration*a.peaks.length))]??0;points.push('M'+(x+w*progress)+','+(34-v*19)+'v'+v*38);}wave.append(svg('path',{d:points.join(' '),class:'wave'}));}
    for(const[action,position]of [['left',x],['right',x+w]])wave.append(svg('line',{x1:position,x2:position,y1:23,y2:55,class:'edge','data-clip':c.id,'data-action':action}));
    wave.append(svg('path',{d:`M${x},13 L${x+Math.max(8,c.fadeIn/length*1000)},13 L${x+Math.max(8,c.fadeIn/length*1000)},24 Z`,class:'fade','data-clip':c.id,'data-action':'fadeIn'}));
    wave.append(svg('path',{d:`M${x+w},13 L${x+w-Math.max(8,c.fadeOut/length*1000)},13 L${x+w-Math.max(8,c.fadeOut/length*1000)},24 Z`,class:'fade','data-clip':c.id,'data-action':'fadeOut'}));
   }
   for(const m of current().markers){wave.append(svg('line',{x1:m.time/length*1000,x2:m.time/length*1000,y1:0,y2:60,stroke:'#b698ed','stroke-dasharray':'3 2','pointer-events':'none'}));}
   wave.append(svg('line',{id:'musicHead',x1:api.time()/length*1000,x2:api.time()/length*1000,y1:0,y2:60,class:'head'}));
  }
  $('musicWave').onpointerdown=e=>{e.preventDefault();api.halt();const c=current().clips.find(c=>c.id===e.target.dataset.clip);if(!c){const r=$('musicWave').getBoundingClientRect();api.seek(Math.max(0,Math.min(api.length(),(e.clientX-r.left)/r.width*api.length())));return;}selected=c.id;drag={original:copy(c),candidate:copy(c),action:e.target.dataset.action,x:e.clientX,width:$('musicWave').getBoundingClientRect().width};$('musicWave').setPointerCapture(e.pointerId);};
  $('musicWave').onpointermove=e=>{if(!drag)return;const c=copy(drag.original),d=(e.clientX-drag.x)/drag.width*api.length(),a=api.project().music.assets.find(a=>a.id===c.assetId);
   if(drag.action==='move')c.start=Math.max(0,c.start+d);
   if(drag.action==='left'){const delta=Math.max(-Math.min(c.in,c.start),Math.min(d,c.out-c.in-.01));c.start+=delta;c.in+=delta;}
   if(drag.action==='right')c.out=Math.max(c.in+.01,Math.min(a.duration,c.out+d));
   if(drag.action==='fadeIn')c.fadeIn=Math.max(0,Math.min(c.out-c.in-c.fadeOut,drag.original.fadeIn+d));
   if(drag.action==='fadeOut')c.fadeOut=Math.max(0,Math.min(c.out-c.in-c.fadeIn,drag.original.fadeOut-d));
   if(c.fadeIn+c.fadeOut>c.out-c.in){const ratio=(c.out-c.in)/(c.fadeIn+c.fadeOut);c.fadeIn*=ratio;c.fadeOut*=ratio;}
   drag.candidate=c;draw(c);
  };
  $('musicWave').onpointerup=()=>{if(!drag)return;const c=drag.candidate;drag=null;change(p=>{p.clips[p.clips.findIndex(v=>v.id===c.id)]=c;});signature='';render();};
  $('musicWave').onpointercancel=()=>{drag=null;draw();};
  async function prepare(){const p=current();if(!p.clips.length||api.project().music?.enabled===false)return;audio();await context.resume();const active=M.at(api.project().music,api.active(),api.time()),c=active?.clip??p.clips.find(c=>c.start>=api.time());if(c){status('准备音乐试听…');await load(api.project().music.assets.find(a=>a.id===c.assetId));status('音乐就绪 · 原速播放；画面缓冲时同步等待。');}}
  function sync(time,fps){
   const head=$('musicHead');if(head){head.setAttribute('x1',time/api.length()*1000);head.setAttribute('x2',time/api.length()*1000);}
   if(!api.playing())return;if(api.project().music?.enabled===false){stop();return;}
   const value=M.at(api.project().music,api.active(),time);if(!value||value.gain===0&&value.clip.muted){stop();return;}
   const c=value.clip,a=api.project().music.assets.find(a=>a.id===c.assetId),buffer=buffers.get(a.id);
   if(!buffer){stop();load(a).catch(e=>{status(e.message,true);api.halt();});return;}
   if(anchor?.clip===c.id&&Math.abs((anchor.source+context.currentTime-anchor.clock)-value.source)<Math.max(.025,1/fps)){return;}
   stop();source=context.createBufferSource();source.buffer=buffer;source.playbackRate.value=1;gain=context.createGain();source.connect(gain);gain.connect(context.destination);
   const now=context.currentTime,end=c.start+c.out-c.in,remaining=Math.min(end,api.length())-time;
   if(remaining<=0){stop();return;}gain.gain.setValueAtTime(value.gain,now);
   const fadeInEnd=c.start+c.fadeIn,fadeOutStart=end-c.fadeOut;
   if(c.fadeIn&&time<fadeInEnd){const delta=Math.min(remaining,fadeInEnd-time);gain.gain.linearRampToValueAtTime(c.gain*Math.min(1,(time+delta-c.start)/c.fadeIn),now+delta);}
   if(c.fadeOut&&fadeOutStart>time&&fadeOutStart<time+remaining)gain.gain.setValueAtTime(c.gain,now+fadeOutStart-time);
   if(c.fadeOut&&time+remaining>fadeOutStart)gain.gain.linearRampToValueAtTime(c.gain*Math.max(0,(end-time-remaining)/c.fadeOut),now+remaining);
   anchor={clip:c.id,assetId:a.id,clock:now,source:value.source};source.start(now,value.source,remaining);
  }
  function loop(time){if(!$('musicLoop').checked)return null;const a=Number($('musicLoopIn').value),b=Number($('musicLoopOut').value);if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b<=a||b>api.length()){status('循环范围须位于当前镜头内，且终点大于起点',true);$('musicLoop').checked=false;return null;}return time>=b?a:null;}
  window.addEventListener('pagehide',()=>{stop();context?.close();});
  return {render,sync,stop,prepare,loop};
 }
 root.EarthMusicUI={create};
})(globalThis);
