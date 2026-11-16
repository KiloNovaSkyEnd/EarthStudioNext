/* Per-shot weather range, local duration and final order are independent. */
(function(root){
 const copy=x=>JSON.parse(JSON.stringify(x));
 function range(project,id){return project.tracks.find(t=>t.id===id)?.weather??project.weather;}
 function setWeather(project,id,weather,T,S){const next=copy(project),track=next.tracks.find(t=>t.id===id);if(!track)throw Error('分镜不存在');track.weather=copy(weather);T.validate(next,S);return next;}
 function move(project,id,delta){const next=copy(project),index=next.tracks.findIndex(t=>t.id===id),target=index+delta;if(index<0||target<0||target>=next.tracks.length)return next;[next.tracks[index],next.tracks[target]]=[next.tracks[target],next.tracks[index]];return next;}
 function layout(project,T){let start=0;return project.tracks.map(t=>{const seconds=T.duration(project,t.id),result={id:t.id,name:t.name,start,end:start+seconds,duration:seconds,weather:range(project,t.id)};start+=seconds;return result;});}
 function createUi(api){
  const $=id=>document.getElementById(id),T=root.EarthTimeline,S=root.EarthShots;
  const date=x=>x?.slice(0,19)??'',utc=x=>x.length===16?x+':00Z':x+'Z';
  let lastKey='';
  $('applyProjectFps').onclick=api.edit(()=>{const previous=api.project(),policy=$('fpsPolicy').value,p=root.EarthMontage.changeFps(previous,Number($('projectFps').value),T,S,policy);api.replace(p,{timeScale:policy==='frames'?previous.fps/p.fps:1});});
  $('shotClockMode').onchange=()=>{$('legacyShotWeather').hidden=$('shotClockMode').value!=='mapped';$('shotWeatherEnd').disabled=$('shotClockMode').value!=='mapped';};
  $('applyTrim').onclick=api.edit(()=>api.replace(root.EarthMontage.trim(api.project(),api.active(),Number($('trimIn').value),Number($('trimOut').value),T,S)));
  $('resetTrim').onclick=api.edit(()=>{const p=copy(api.project());delete p.tracks.find(t=>t.id===api.active()).clip;api.replace(p);});
  function rateHint(){const fixed=$('shotWeatherMode').value==='rate';$('shotObservationFps').disabled=!fixed;$('shotWeatherCurve').disabled=fixed;$('shotRateHint').textContent=fixed?'观测时次/秒独立于项目输出帧率；播完末帧保持，不循环。':'按天气端点映射镜头；曲线平段保持天气，相机继续移动，不生成插帧。';}
  $('shotWeatherMode').onchange=rateHint;
  function render(){const p=api.project(),id=api.active(),w=range(p,id),current=api.time?.()??0;
   $('shotClockReadout').textContent=`镜头 ${current.toFixed(3)}秒 · 映射UTC ${T.weatherTime(p,current,id)??'未载入'} · 实际扫描 ${api.actualWeather?.()??'未载入'}`;
   const key=JSON.stringify([id,p.fps,p.sourcePlayback,p.duration,p.weather,p.tracks.map(t=>[t.id,t.name,t.duration,t.weather,t.clip])]);if(key===lastKey)return;lastKey=key;
   if(document.activeElement!==$('projectFps'))$('projectFps').value=p.fps;$('fpsPolicy').value=p.fpsPolicy??'frames';
   $('projectClockState').textContent=p.sourcePlayback?'项目输出 '+p.fps+' fps；'+((p.fpsPolicy??'frames')==='frames'?'改帧率时天气与运镜整体同比变速。':'改帧率时保留镜头秒数与天气进度。')+' 音乐保持原速与原秒数位置。':'旧工程计时：可应用项目帧率，或保留独立天气曲线。';
   const sequence=T.isSequence(p,id);$('shotClockMode').value=sequence?'sequence':'mapped';
   $('legacyShotWeather').hidden=sequence;
   $('shotWeatherEnd').disabled=sequence;
   const clip=p.tracks.find(t=>t.id===id).clip;
   $('trimIn').value=(clip?.inFrame??0)/p.fps;$('trimOut').value=(clip?.outFrame??Math.round(T.duration(p,id)*p.fps))/p.fps;
   if(document.activeElement!==$('shotWeatherStart'))$('shotWeatherStart').value=date(w?.startUtc);
   if(document.activeElement!==$('shotWeatherEnd'))$('shotWeatherEnd').value=date(w?.endUtc);
   if(document.activeElement!==$('shotSeconds'))$('shotSeconds').value=T.duration(p,id);
   const curve=w?.curve??T.PRESETS.linear;let preset=Object.keys(T.PRESETS).find(k=>JSON.stringify(T.PRESETS[k])===JSON.stringify(curve));
   if(!preset){preset='custom';if(!$('shotWeatherCurve').querySelector('option[value="custom"]'))$('shotWeatherCurve').add(new Option('保留自定义曲线','custom'));}$('shotWeatherCurve').value=preset;
   $('shotWeatherMode').value=w?.observationFps!==undefined?'rate':'fit';if(document.activeElement!==$('shotObservationFps'))$('shotObservationFps').value=w?.observationFps??12;rateHint();
   const rows=layout(p,T),cards=rows.map((r,i)=>{
    const box=document.createElement('div');box.className='shotCard'+(r.id===id?' active':'');
    const title=document.createElement('button');title.textContent=`${i+1}. ${r.name} · ${r.duration.toFixed(2)}秒`;title.onclick=()=>api.select(r.id);box.append(title);
    const edit=root.EarthMontage.layout(p,T)[i];
    const info=document.createElement('small');info.textContent=`成片 ${(edit.startFrame/p.fps).toFixed(2)} → ${(edit.endFrame/p.fps).toFixed(2)}秒\n源镜头 ${(edit.inFrame/p.fps).toFixed(2)} → ${(edit.outFrame/p.fps).toFixed(2)}秒 · ${T.isSequence(p,r.id)?'逐张播放':'自定义映射'}\nUTC ${T.weatherTime(p,edit.inFrame/p.fps,r.id)??'未载入'} → ${T.weatherTime(p,(edit.outFrame-1)/p.fps,r.id)??'未载入'}`;box.append(info);
    for(const [text,delta] of [['前移',-1],['后移',1]]){const b=document.createElement('button');b.textContent=text;b.disabled=i+delta<0||i+delta>=rows.length;b.onclick=api.edit(()=>api.replace(move(api.project(),r.id,delta)));box.append(b);}
    return box;});$('shotCards').replaceChildren(...cards);const total=root.EarthMontage.layout(p,T).at(-1)?.endFrame??0;$('shotTotal').textContent=`按卡片顺序出片 · 共 ${(total/p.fps).toFixed(3)}秒 / ${total}帧。裁切不改源镜头。`;$('montageSeek').max=Math.max(0,total-1);
  }
  $('applyShotTime').onclick=api.edit(()=>{
   let p=api.project();const id=api.active(),start=utc($('shotWeatherStart').value),end=utc($('shotWeatherEnd').value);
   const sequence=$('shotClockMode').value==='sequence';
   if(sequence&&!p.sourcePlayback){p=copy(p);for(const t of p.tracks)t.weather={mode:'mapped',...(t.weather??p.weather)};p.sourcePlayback={mode:'sequence',intervalSeconds:api.intervalSeconds()};}
   const weather=sequence?{mode:'sequence',startUtc:start,endUtc:p.weather.endUtc}:{mode:'mapped',startUtc:start,endUtc:end};const preset=$('shotWeatherCurve').value;if(sequence){}else if($('shotWeatherMode').value==='rate'){weather.observationFps=Number($('shotObservationFps').value);weather.intervalSeconds=api.intervalSeconds();}else if(preset==='custom')weather.curve=copy(range(p,id).curve);else if(preset!=='linear')weather.curve=copy(T.PRESETS[preset]);
   p=setWeather(p,id,weather,T,S);p=T.retimeTrack(p,id,Number($('shotSeconds').value),S);api.replace(p);
  });
  $('shotUseAll').onclick=api.edit(()=>api.replace(setWeather(api.project(),api.active(),api.project().weather,T,S)));
  $('shotHoldWeather').onclick=api.edit(()=>{const stamp=api.actualWeather?.()??api.currentWeather();if(!stamp)throw Error('请先载入天气');api.replace(setWeather(api.project(),api.active(),{mode:'mapped',startUtc:stamp,endUtc:stamp},T,S));});
  return {render};
 }
 const api={range,setWeather,move,layout,createUi};if(typeof module!=='undefined')module.exports=api;root.EarthStoryboard=api;
})(globalThis);
