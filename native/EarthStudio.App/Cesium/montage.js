/* Non-destructive, frame-exact edit decisions; source camera/weather remain intact. */
(function(root){
 const copy=x=>JSON.parse(JSON.stringify(x));
 function layout(project,T){let cursor=0;return project.tracks.map(track=>{
  const sourceFrames=Math.round(T.duration(project,track.id)*project.fps),clip=track.clip??{inFrame:0,outFrame:sourceFrames};
  const result={id:track.id,name:track.name,inFrame:clip.inFrame,outFrame:clip.outFrame,startFrame:cursor,endFrame:cursor+clip.outFrame-clip.inFrame};
  cursor=result.endFrame;return result;
 });}
 function locate(project,frame,T){const rows=layout(project,T),total=rows.at(-1)?.endFrame??0;
  if(!Number.isInteger(frame)||frame<0||frame>=total)throw Error('成片帧超出范围');
  const row=rows.find(r=>frame<r.endFrame);return {...row,sourceFrame:row.inFrame+frame-row.startFrame};
 }
 function trim(project,id,start,end,T,S){const next=copy(project),track=next.tracks.find(t=>t.id===id);
  if(!track)throw Error('分镜不存在');
  track.clip={inFrame:Math.round(start*next.fps),outFrame:Math.round(end*next.fps)};T.validate(next,S);return next;
 }
 function changeFps(project,fps,T,S,policy=project.fpsPolicy??'frames'){
  if(!Number.isFinite(fps)||fps<1||fps>120)throw Error('项目帧率应为1至120');
  if(!['frames','seconds'].includes(policy))throw Error('请选择帧率联动方式');
  const next=copy(project),old=project.fps,scale=old/fps;next.fps=fps;next.fpsPolicy=policy;
  if(fps===old){T.validate(next,S);return next;}
  if(policy==='frames'){
   next.duration*=scale;
   for(const track of next.tracks){
    if(track.duration!==undefined)track.duration*=scale;
    for(const key of track.keys)key.time*=scale;
    if(track.weather?.observationFps!==undefined)track.weather.observationFps/=scale;
   }
   if(next.weather?.observationFps!==undefined)next.weather.observationFps/=scale;
   if(next.editorState)next.editorState.time*=scale;
  }else{
   for(const track of next.tracks){
    if(T.isSequence(project,track.id)){const weather=copy(track.weather??project.weather);if(weather)track.weather={mode:'mapped',startUtc:weather.startUtc,endUtc:project.weather.endUtc,observationFps:old,intervalSeconds:project.sourcePlayback.intervalSeconds};}
    if(track.clip){track.clip.inFrame=Math.round(track.clip.inFrame/scale);track.clip.outFrame=Math.round(track.clip.outFrame/scale);}
   }
  }
  // Music always keeps real seconds, source offsets, fades, placement and rate=1.
  T.validate(next,S);return next;
 }
 const api={layout,locate,trim,changeFps};if(typeof module!=='undefined')module.exports=api;root.EarthMontage=api;
})(globalThis);
