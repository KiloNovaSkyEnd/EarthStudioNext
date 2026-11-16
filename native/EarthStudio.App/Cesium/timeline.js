/* Absolute-time keyframes and independent takes of one weather interval. */
(function(root) {
 const clone=x=>JSON.parse(JSON.stringify(x));
 const check=(v,m)=>{if(!v)throw new Error(m);};
 const wrap=lon=>((lon+180)%360+360)%360-180;
 const lerp=(a,b,t)=>a+(b-a)*t;
 const duration=(project,id)=>project.tracks.find(t=>t.id===id)?.duration??project.duration;
 const isSequence=(project,id)=>!!project.sourcePlayback&&project.tracks.find(t=>t.id===id)?.weather?.mode!=='mapped';
 const PRESETS={linear:[[0,0],[1,1]],smooth:[[0,0],[.2,.07],[.8,.93],[1,1]],fastSlow:[[0,0],[.25,.65],[.6,.9],[1,1]],slowFast:[[0,0],[.4,.1],[.75,.35],[1,1]],ramp:[[0,0],[.3,.06],[.65,.94],[1,1]]};
 function validateCurve(points) {
  check(Array.isArray(points)&&points.length>=2&&points.length<=32,'速度曲线需要2至32个控制点');
  let x=-1,y=-1;
  for(const p of points){check(Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)&&p[0]>x&&p[1]>=y&&p.every(v=>v>=0&&v<=1),'速度曲线时间须递增，路径进度不能倒退');[x,y]=p;}
  check(points[0][0]===0&&points[0][1]===0&&points.at(-1)[0]===1&&points.at(-1)[1]===1,'速度曲线端点必须为0→0、1→1');return points;
 }
 function progress(points,t) {
  if(!points)return t;
  const n=points.length,h=[],d=[],m=[];
  for(let i=0;i<n-1;i++){h[i]=points[i+1][0]-points[i][0];d[i]=(points[i+1][1]-points[i][1])/h[i];}
  m[0]=d[0];m[n-1]=d[n-2];
  for(let i=1;i<n-1;i++)m[i]=d[i-1]*d[i]<=0?0:3*(h[i-1]+h[i])/((2*h[i]+h[i-1])/d[i-1]+(h[i]+2*h[i-1])/d[i]);
  let j=0;while(j<n-2&&t>points[j+1][0])j++;
  const u=Math.max(0,Math.min(1,(t-points[j][0])/h[j]));
  return Math.max(points[j][1],Math.min(points[j+1][1],(2*u*u*u-3*u*u+1)*points[j][1]+(u*u*u-2*u*u+u)*h[j]*m[j]+(-2*u*u*u+3*u*u)*points[j+1][1]+(u*u*u-u*u)*h[j]*m[j+1]));
 }
 function orbitPose(o,output,C) {
  for(const k of ['targetLon','targetLat','heading','pitch','rangeKm','roll','fov'])check(Number.isFinite(o[k]),'相机参数必须是有效数字');
  check(Math.abs(o.targetLat)<=89 && o.rangeKm>=100 && o.rangeKm<=50000 && o.pitch>=-179.9 && o.pitch<=-.1 && o.fov>=1 && o.fov<=150,'纬度、距离、俯看角或画角超出范围');
  const target=C.Cartesian3.fromDegrees(wrap(o.targetLon),o.targetLat),enu=C.Transforms.eastNorthUpToFixedFrame(target);
  const h=C.Math.toRadians(o.heading),p=C.Math.toRadians(o.pitch),r=o.rangeKm*1000;
  const offset=new C.Cartesian3(-Math.sin(h)*Math.cos(p)*r,-Math.cos(h)*Math.cos(p)*r,-Math.sin(p)*r);
  const direction=C.Cartesian3.normalize(C.Cartesian3.negate(offset,new C.Cartesian3()),new C.Cartesian3());
  const right=new C.Cartesian3(Math.cos(h),-Math.sin(h),0);
  const up=C.Cartesian3.cross(right,direction,new C.Cartesian3());
  const world=v=>C.Matrix4.multiplyByPointAsVector(enu,v,new C.Cartesian3());
  const d=world(direction),u=world(up);
  const rotated=C.Matrix3.multiplyByVector(C.Matrix3.fromQuaternion(C.Quaternion.fromAxisAngle(d,-C.Math.toRadians(o.roll))),u,new C.Cartesian3());
  const position=C.Matrix4.multiplyByPoint(enu,offset,new C.Cartesian3()),array=v=>[v.x,v.y,v.z];
  return {position:array(position),direction:array(d),up:array(rotated),verticalFov:C.Math.toRadians(o.fov),aspect:output.width/output.height,width:output.width,height:output.height,utc:null,brightness:1};
 }
 function validate(project,S) {
  check(project?.schema==='earthstudio.timeline.v1' && project.earthModel==='WGS84','不支持的关键帧工程');
  if(project.effects)check(['blueAtmosphere','nightAirglow'].every(k=>typeof project.effects[k]==='boolean'),'大气开关必须为布尔值');
  if(project.effects?.newAirglow!==undefined)check(typeof project.effects.newAirglow==='boolean','新版气辉开关必须为布尔值');
  for(const [key,lo,hi] of [['newGlowDensity',0,2.5],['newGlowThickness',.5,2],['newGlowHue',-180,180],['newGlowSaturation',0,2],['newGlowBrightness',0,3]])if(project.effects?.[key]!==undefined)check(Number.isFinite(project.effects[key])&&project.effects[key]>=lo&&project.effects[key]<=hi,'新版气辉参数超出范围');
  check(Number.isFinite(project.fps)&&project.fps>=1&&project.fps<=120 && Number.isFinite(project.duration) && project.duration>=.1 && project.duration<=86400,'时长应为0.1秒到24小时');
  check(project.output && [project.output.width,project.output.height].every(x=>Number.isInteger(x)&&x>0&&x<=8192),'输出画幅无效');
  check(Array.isArray(project.tracks)&&project.tracks.length>=1&&project.tracks.length<=50,'分镜数量须为1至50条');
  check(new Set(project.tracks.map(t=>t.id)).size===project.tracks.length,'分镜标识重复');
  for(const track of project.tracks) {
   const end=duration(project,track.id);check(Number.isFinite(end)&&end>=.1&&end<=86400,'分镜时长无效');
   check(typeof track.id==='string'&&typeof track.name==='string'&&track.name.length<=100,'分镜名称无效');
   check(['linear','smooth'].includes(track.easing),'插值方式无效');
   if(track.curve)validateCurve(track.curve);
   if(track.clip)check(Number.isInteger(track.clip.inFrame)&&Number.isInteger(track.clip.outFrame)&&track.clip.inFrame>=0&&track.clip.outFrame>track.clip.inFrame&&track.clip.outFrame<=Math.round(end*project.fps),'裁切入出点必须在镜头内（出点不包含）');
   if(track.weather){const w=track.weather;if(w.mode!==undefined)check(['sequence','mapped'].includes(w.mode),'未知卫星时间模式');check([w.startUtc,w.endUtc].every(x=>typeof x==='string'&&x.endsWith('Z')&&Number.isFinite(Date.parse(x)))&&Date.parse(w.endUtc)>=Date.parse(w.startUtc),'分镜天气范围无效');if(w.curve)validateCurve(w.curve);
    if(w.observationFps!==undefined)check(Number.isFinite(w.observationFps)&&w.observationFps>=.000001&&w.observationFps<=120&&Number.isFinite(w.intervalSeconds)&&w.intervalSeconds>0&&!w.curve,'固定云图帧率需要有效观测间隔；切换为铺满分镜后可编辑速度曲线');
    if(project.weather)check(Date.parse(w.startUtc)>=Date.parse(project.weather.startUtc)&&Date.parse(w.endUtc)<=Date.parse(project.weather.endUtc),'分镜天气超出已载入素材范围');}
   check(Array.isArray(track.keys)&&track.keys.length<=1000,'每条分镜最多1000个关键帧');
   let prev=-1;
   for(const key of track.keys){
    check(Number.isFinite(key.time)&&key.time>=0&&key.time<=end&&key.time>prev,'关键帧必须按时间递增，且位于片段时长内');prev=key.time;
    if(key.curve)validateCurve(key.curve);
    if(key.transition)check(['move','cut'].includes(key.transition),'关键帧衔接方式无效');
    S.validate({schema:'earthstudio.shots.v1',earthModel:'WGS84',shots:[{name:'key',duration:1,pose:key.pose}]});
    check(key.pose.width===project.output.width&&key.pose.height===project.output.height,'关键帧画幅与工程不同');
    if(key.orbit){for(const k of ['targetLon','targetLat','heading','pitch','rangeKm','roll','fov'])check(Number.isFinite(key.orbit[k]),'关键帧参数无效');
     check(Math.abs(key.orbit.targetLat)<=89&&key.orbit.rangeKm>=100&&key.orbit.rangeKm<=50000&&key.orbit.pitch>=-179.9&&key.orbit.pitch<=-.1&&key.orbit.fov>=1&&key.orbit.fov<=150,'关键帧参数超出范围');}
   }
  }
  if(project.editorState){const e=project.editorState;check(project.tracks.some(t=>t.id===e.track)&&Number.isFinite(e.time)&&e.time>=0&&e.time<=duration(project,e.track),'草稿时间或分镜无效');
   if(e.pose)S.validate({schema:'earthstudio.shots.v1',earthModel:'WGS84',shots:[{name:'draft',duration:1,pose:e.pose}]});
  }
  if(project.sourcePlayback)check(project.sourcePlayback.mode==='sequence'&&Number.isFinite(project.sourcePlayback.intervalSeconds)&&project.sourcePlayback.intervalSeconds>0,'项目源图采样间隔无效');
  const weather=project.weather;
  if(weather){check([weather.startUtc,weather.endUtc].every(x=>typeof x==='string'&&x.endsWith('Z')&&Number.isFinite(Date.parse(x))),'天气区间必须为UTC');check(Date.parse(weather.endUtc)>=Date.parse(weather.startUtc),'天气区间倒置');}
  if(project.fpsPolicy!==undefined)check(['frames','seconds'].includes(project.fpsPolicy),'未知帧率联动方式');
  if(project.music!==undefined){check(!!root.EarthMusic,'音乐模块未载入');root.EarthMusic.validate(project.music);}
  return project;
 }
 function weatherTime(project,time,id) {
  const key=id??project.activeTrack,track=project.tracks.find(t=>t.id===key),weather=track?.weather??project.weather;
  if(!weather)return null;
  if(isSequence(project,key)){const start=Date.parse(weather.startUtc),end=Date.parse(project.weather.endUtc);return new Date(Math.min(end,start+Math.max(0,time)*project.fps*project.sourcePlayback.intervalSeconds*1000)).toISOString();}
  const seconds=weather.observationFps!==undefined?(Date.parse(weather.endUtc)-Date.parse(weather.startUtc))/1000/weather.intervalSeconds/weather.observationFps:duration(project,key);
  const t=seconds>0?Math.max(0,Math.min(1,time/seconds)):0;
  return new Date(lerp(Date.parse(weather.startUtc),Date.parse(weather.endUtc),progress(weather.curve,t))).toISOString();
 }
 function sample(project,trackId,time,C,S) {
  const track=project.tracks.find(t=>t.id===trackId);check(track&&track.keys.length,'请先添加关键帧');
  const keys=track.keys;
  let a=keys[0],b=a;
  for(let i=0;i<keys.length;i++){if(keys[i].time<=time)a=keys[i];if(keys[i].time>=time){b=keys[i];break;}b=keys[i];}
  const raw=a.time===b.time?0:Math.max(0,Math.min(1,(time-a.time)/(b.time-a.time)));
  let t=progress(a.curve||track.curve||(track.easing==='smooth'?PRESETS.smooth:PRESETS.linear),raw);
  if(b.transition==='cut')t=raw>=1?1:0;
  let pose,orbit=null;
  if(a.orbit&&b.orbit){
   orbit={};for(const name of ['targetLat','heading','pitch','rangeKm','roll','fov'])orbit[name]=lerp(a.orbit[name],b.orbit[name],t);
   orbit.targetLon=wrap(a.orbit.targetLon+wrap(b.orbit.targetLon-a.orbit.targetLon)*t);
   pose=orbitPose(orbit,project.output,C);
  } else if(a===b)pose=clone(a.pose);
  else {
   const pair={schema:'earthstudio.shots.v1',earthModel:'WGS84',shots:[{name:'a',duration:1,pose:a.pose},{name:'b',duration:1,pose:b.pose}]};
   pose=S.sample(pair,t,C);
  }
  return {...pose,seconds:time,orbit,utc:null,timelineUtc:weatherTime(project,time,trackId)};
 }
 function upsert(project,trackId,key,S) {
  const next=clone(project),track=next.tracks.find(t=>t.id===trackId);check(track,'分镜不存在');
  const index=track.keys.findIndex(k=>Math.abs(k.time-key.time)<1e-5);
  if(index<0)track.keys.push(clone(key));else track.keys[index]=clone(key);
  track.keys.sort((a,b)=>a.time-b.time);validate(next,S);return next;
 }
 function bake(project,id,C,S) {
  validate(project,S);const end=duration(project,id);check(Math.ceil(end*project.fps)+1<=S.MAX_SAMPLES,'导出采样过多，请缩短或分段导出');
  const track=project.tracks.find(t=>t.id===id);check(track?.keys.length,'分镜没有关键帧');
  const samples=[];for(let i=0;i<=Math.ceil(end*project.fps);i++){const p=sample(project,id,Math.min(i/project.fps,end),C,S);delete p.orbit;if(i&&track.keys.some(k=>k.transition==='cut'&&samples[i-1].seconds<k.time&&p.seconds>=k.time))p.cut=true;samples.push(p);}
  return {schema:'earthstudio.camera.v1',earthModel:'WGS84',coordinates:'ECEF_METERS',fps:project.fps,name:track.name,samples,keyframeTrack:clone(track),timelineProject:clone(project)};
 }
 function fromLegacy(plan,output) {
  output={width:plan.shots[0].pose.width,height:plan.shots[0].pose.height};
  let time=0;const keys=plan.shots.map((s,i)=>{if(i)time+=s.duration;const pose=clone(s.pose);pose.width=output.width;pose.height=output.height;pose.aspect=output.width/output.height;return {time,pose,orbit:s.orbit?clone(s.orbit):null,transition:s.transition??'move'};});
  return {schema:'earthstudio.timeline.v1',earthModel:'WGS84',fps:30,duration:Math.max(1,time),output,weather:null,activeTrack:'take1',tracks:[{id:'take1',name:'导入分镜',easing:'linear',keys}]};
 }
 function retime(project,duration,S) {
  check(Number.isFinite(duration)&&duration>=.1&&duration<=86400,'片段时长无效');
  const next=clone(project),scale=duration/project.duration;next.duration=duration;
  for(const track of next.tracks){if(track.duration!==undefined)track.duration*=scale;for(const key of track.keys)key.time*=scale;if(track.clip){track.clip.inFrame=Math.round(track.clip.inFrame*scale);track.clip.outFrame=Math.round(track.clip.outFrame*scale);}}
  validate(next,S);return next;
 }
 function retimeTrack(project,id,end,S){check(Number.isFinite(end)&&end>=.1&&end<=86400,'分镜时长无效');const next=clone(project),track=next.tracks.find(t=>t.id===id);check(track,'分镜不存在');const scale=end/duration(project,id);track.duration=end;for(const key of track.keys)key.time*=scale;if(track.clip){track.clip.inFrame=Math.round(track.clip.inFrame*scale);track.clip.outFrame=Math.round(track.clip.outFrame*scale);}validate(next,S);return next;}
 const api={wrap,orbitPose,validate,sample,upsert,bake,weatherTime,isSequence,fromLegacy,validateCurve,progress,retime,retimeTrack,duration,PRESETS};
 if(typeof module!=='undefined')module.exports=api;root.EarthTimeline=api;
})(globalThis);
