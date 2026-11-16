'use strict';
function setupTimelineEditor(viewer,bridge) {
 const C=Cesium,T=EarthTimeline,S=EarthShots,A=EarthCameraActions,$=id=>document.getElementById(id),copy=x=>JSON.parse(JSON.stringify(x));
 const testName=new URLSearchParams(location.search).get('test');
 const STORAGE='earthstudio.timeline.editor.v1'+(testName?'.test.'+testName:''),output={width:1920,height:1080};
 let project={schema:'earthstudio.timeline.v1',earthModel:'WGS84',fps:30,duration:20,output,weather:null,activeTrack:'take1',tracks:[{id:'take1',name:'分镜 A',easing:'linear',keys:[]}]};
 let restored=false;
 try{const stored=localStorage.getItem(STORAGE)??(testName==='native-20261020'?localStorage.getItem('earthstudio.timeline.editor.v1.test'):null);if(stored){project=T.validate(JSON.parse(stored),S);restored=true;}}catch(e){console.warn('Timeline restore skipped:',e.message);}
 const restoredEditor=project.editorState??null;delete project.editorState;
 let active=project.tracks.some(t=>t.id===project.activeTrack)?project.activeTrack:project.tracks[0].id,time=0,playing=false,preparing=false,playRequest=0,started=0,startTime=0,parameterTimer,timeInputTimer,lastControlsUpdate=0,lastOverviewUpdate=0;
 let currentOrbit={targetLon:130,targetLat:20,heading:0,pitch:-25,rangeKm:4500,roll:0,fov:40},currentPose=null,dirty=false,saveTimer,sceneDrag=null,keyDrag=null,curveDrag=null,curveSelected=1,overviewReady=false,overviewTarget=null;
 let planner=null,music=null,library=null,layout=null,lastTick=0;
 let montageRow=null,montageTransition=false;
 const orbitIds=['targetLon','targetLat','heading','pitch','rangeKm','roll','fov'];
 const defaults=()=>({targetLon:130,targetLat:20,heading:0,pitch:-90,rangeKm:4500,roll:0,fov:40,...bridge.defaultView?.()});
 const history=new EarthEditorHistory.History();let editRevision=0,historyGroup=null,gestureSerial=0,editorRestoredAfterMaterial=false;
 project.effects??={blueAtmosphere:true,nightAirglow:true};EarthShotLibrary.migrate(project);
 const track=()=>project.tracks.find(t=>t.id===active);
 bridge.previewWeatherTime=()=>T.weatherTime(project,time,active);
 bridge.bindWeatherRange=range=>{const hadWeather=!!project.weather;if(project.weather&&JSON.stringify(project.weather)!==JSON.stringify(range))for(const t of project.tracks)t.weather??=copy(project.weather);project.weather=range;if(project.sourcePlayback)project.sourcePlayback.intervalSeconds=bridge.weatherIntervalSeconds();if(!restored||!hadWeather)project.sourcePlayback={mode:'sequence',intervalSeconds:bridge.weatherIntervalSeconds()};planner?.render();library?.render();};
 bridge.shotWeatherRange=()=>T.isSequence(project,active)?{startUtc:(track().weather??project.weather)?.startUtc,endUtc:project.weather?.endUtc,observationFps:project.fps,intervalSeconds:project.sourcePlayback.intervalSeconds}:track().weather??project.weather;
 bridge.projectFrameRate=()=>project.fps;
 bridge.setProjectFrameRate=value=>{ $('projectFps').value=value;$('applyProjectFps').click();};
 const length=()=>T.duration(project,active);
 const selectedKey=()=>track().keys.find(k=>Math.abs(k.time-time)<1e-5);
 const snap=v=>Math.round(v*project.fps)/project.fps;
 const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
 function message(text,error=false){$('feedback').textContent=text;$('feedback').classList.toggle('error',error);}
 function snapshot(){const data=copy(project);data.activeTrack=active;return {project:data,active,time,orbit:currentOrbit?copy(currentOrbit):null,pose:currentPose?capture():null,dirty,mouseMode:$('mouseMode').value};}
 function historyButtons(){$('undo').disabled=!history.past.length;$('redo').disabled=!history.future.length;}
 function record(before,group=null){EarthShotLibrary.revise(before.project,project,T);history.record(before,snapshot(),group);historyButtons();library?.render();}
 const guard=fn=>()=>{const before=snapshot(),revision=editRevision;try{fn();if(revision!==editRevision||JSON.stringify(before.project)!==JSON.stringify(project))record(before,historyGroup);}catch(e){message(e.message,true);}};
 function syncEffects(){project.effects={...EarthAirglowTransport.defaults,...project.effects};bridge.setEffects(project.effects);for(const key of ['blueAtmosphere','nightAirglow','newAirglow'])$(key).checked=project.effects[key];}
 function restore(value){if(!value)return;halt();clearTimeout(parameterTimer);clearTimeout(timeInputTimer);project=copy(value.project);active=value.active;time=value.time;currentOrbit=value.orbit;dirty=value.dirty;$('mouseMode').value=value.mouseMode;syncEffects();if(value.pose)applyPose(value.pose);picker();fit();renderTimeline();$('duration').value=length();bridge.durationChanged?.(length(),true);overviewReady=false;drawPath();controls(true);persist();historyButtons();}
 $('undo').onclick=()=>{restore(history.undo());message('已撤回上一步编辑。');};
 $('redo').onclick=()=>{restore(history.redo());message('已恢复上一步编辑。');};
 window.addEventListener('keydown',e=>{if(!(e.ctrlKey||e.metaKey)||e.altKey)return;const key=e.key.toLowerCase();if(!['z','y'].includes(key))return;const target=e.target;if(target?.isContentEditable||target?.tagName==='TEXTAREA'||(target?.tagName==='INPUT'&&!['number','range','checkbox'].includes(target.type)))return;const button=key==='y'||e.shiftKey?$('redo'):$('undo');if(button.disabled)return;e.preventDefault();e.stopPropagation();button.click();},true);
 window.addEventListener('keydown',e=>{
  if(e.key!=='Delete'||e.repeat||e.isComposing||e.ctrlKey||e.metaKey||e.altKey||keyDrag||curveDrag||sceneDrag)return;
  const target=e.target;
  if(target?.isContentEditable||['INPUT','TEXTAREA','SELECT'].includes(target?.tagName)||!selectedKey())return;
  e.preventDefault();e.stopPropagation();$('deleteKey').click();
 },true);
 $('ruler').tabIndex=0;
 for(const id of ['blueAtmosphere','nightAirglow','newAirglow'])$(id).onchange=guard(()=>{halt();project.effects[id]=$(id).checked;syncEffects();persist();message('大气与两套气辉已独立更新，可用撤回恢复。');});
 function serializeProject(){return {...copy(project),activeTrack:active,editorState:{track:active,time,orbit:currentOrbit?copy(currentOrbit):null,pose:currentPose?capture():null,dirty,mouseMode:$('mouseMode').value}};}
 function persist(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>{try{project.activeTrack=active;const saved=serializeProject();localStorage.setItem(STORAGE,JSON.stringify(saved));bridge.persistEditor?.(saved);}catch(e){message('自动保存失败，请点击“保存工程”下载备份。',true);}},200);}
 function halt(){music?.stop();playRequest++;playing=false;preparing=false;montageRow=null;$('montagePlay').textContent='播放连续成片';bridge.pausePlayback?.();$('play').textContent='播放运镜＋云图';}
 bridge.pauseCamera=halt;
 bridge.editBrightness=value=>{const oldGroup=historyGroup;historyGroup='brightness';guard(()=>{const p=capture();p.brightness=value;changePose(p,currentOrbit);})();historyGroup=oldGroup;};
 function fit(){
  const stage=$('stage'),box=$('earth'),aspect=project.output.width/project.output.height;
  const width=Math.min(stage.clientWidth,stage.clientHeight*aspect),height=width/aspect;
  Object.assign(box.style,{width:width+'px',height:height+'px',left:(stage.clientWidth-width)/2+'px',top:(stage.clientHeight-height)/2+'px'});
  viewer.resize();viewer.camera.frustum.aspectRatio=aspect;
  if(currentPose)setFrustum(currentPose.verticalFov);viewer.scene.requestRender();
 }
 function setFrustum(vertical){const aspect=project.output.width/project.output.height;viewer.camera.frustum.aspectRatio=aspect;viewer.camera.frustum.fov=aspect>1?2*Math.atan(Math.tan(vertical/2)*aspect):vertical;}
 function capture(){const arr=v=>[v.x,v.y,v.z];return {position:arr(viewer.camera.positionWC),direction:arr(viewer.camera.directionWC),up:arr(viewer.camera.upWC),verticalFov:viewer.camera.frustum.fovy,aspect:project.output.width/project.output.height,width:project.output.width,height:project.output.height,utc:bridge.utc(),brightness:bridge.brightness()};}
 function applyPose(p){
  currentPose=copy(p);viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
  viewer.camera.position=C.Cartesian3.fromArray(p.position);viewer.camera.direction=C.Cartesian3.fromArray(p.direction);viewer.camera.up=C.Cartesian3.fromArray(p.up);viewer.camera.right=C.Cartesian3.cross(viewer.camera.direction,viewer.camera.up,new C.Cartesian3());
  setFrustum(p.verticalFov);bridge.setWeather(T.weatherTime(project,time,active),p.brightness??1);viewer.scene.requestRender();updateOverviewCamera(p);
 }
 function controls(force=false){
  const now=performance.now();if(playing&&!force&&now-lastControlsUpdate<100)return;lastControlsUpdate=now;
  if(currentOrbit)for(const id of orbitIds){if(force||document.activeElement!==$(id))$(id).value=Number(currentOrbit[id].toFixed(id.startsWith('target')?4:2));$(id).removeAttribute('aria-invalid');}
  else{$('fov').value=C.Math.toDegrees(currentPose?.verticalFov??.7);}
  for(const id of orbitIds)$(id+'Slider').value=currentOrbit?.[id]??$(id).value;
  rollReference=Number($('roll').value);
  $('cameraFeedback').textContent=currentOrbit?'参数会即时改变画面。俯看 −90°为垂直向下，接近0°为低角度侧看。':'当前是自由相机。旋转/画角仍可直接改；绕目标控制会重新朝向目标。';
 }
 function renderTime(){ $('addKey').textContent=selectedKey()?'更新 '+time.toFixed(2)+'秒关键帧':'＋关键帧';$('keyAt').value=Number(time.toFixed(3));$('playhead').max=length();$('playhead').value=time;$('viewTime').textContent=time.toFixed(2)+'秒';if(document.activeElement!==$('duration'))$('duration').value=length();$('outputLabel').textContent=project.output.width+'×'+project.output.height;bridge.durationChanged?.(length());planner?.render();music?.render();library?.render();layout?.render();music?.sync(time,project.fps); }
 function seek(value){
  clearTimeout(parameterTimer);clearTimeout(timeInputTimer);
  time=clamp(value,0,length());dirty=false;
  if(track().keys.length){const p=T.sample(project,active,time,C,S);currentOrbit=p.orbit?copy(p.orbit):null;applyPose(p);}
  else bridge.setWeather(T.weatherTime(project,time,active),bridge.brightness());
  renderTime();controls();renderSelection();renderSpeed();
 }
 bridge.seekWeather=utc=>{
  if(!project.weather)return;
  const weather=bridge.shotWeatherRange(),start=Date.parse(weather.startUtc),span=Date.parse(weather.endUtc)-start;
  const target=span>0?clamp((Date.parse(utc)-start)/span,0,1):0;let fraction=target;
  if(weather.curve){let lo=0,hi=1;for(let i=0;i<40;i++){const mid=(lo+hi)/2;if(T.progress(weather.curve,mid)<target)lo=mid;else hi=mid;}fraction=(lo+hi)/2;}
  const value=clamp(Math.ceil(fraction*(weather.observationFps!==undefined?span/1000/weather.intervalSeconds/weather.observationFps:length())*project.fps-1e-7)/project.fps,0,length());
  halt();if(dirty){time=value;renderTime();renderSelection();renderSpeed();}else seek(value);
  persist();
 };
 function restoreEditor(state){
  if(!state?.pose)return;
  if(!project.tracks.some(t=>t.id===state.track)||!Number.isFinite(state.time))throw new Error('工程预览状态无效');
  S.validate({schema:'earthstudio.shots.v1',earthModel:'WGS84',shots:[{name:'draft',duration:1,pose:state.pose}]});
  if(state.pose.width!==project.output.width||state.pose.height!==project.output.height)throw new Error('预览画幅与工程不一致');
  if(state.orbit)T.orbitPose(state.orbit,project.output,C);
  active=state.track;time=clamp(state.time,0,length());currentOrbit=state.orbit?copy(state.orbit):null;applyPose(state.pose);dirty=!!state.dirty;
  if(['globe','orbit','look','roll'].includes(state.mouseMode))$('mouseMode').value=state.mouseMode;
  picker();renderTimeline();drawPath();controls(true);
 }
 function changePose(p,orbit){
  halt();editRevision++;currentOrbit=orbit?copy(orbit):null;applyPose(p);dirty=true;
  const key=selectedKey();
  if(key&&$('autoKey').checked){project=T.upsert(project,active,{...copy(key),pose:capture(),orbit:currentOrbit?copy(currentOrbit):null},S);dirty=false;persist();renderTimeline();drawPath();message(`已更新 ${time.toFixed(2)}秒关键帧。`);}
  else message(`画面已调整。点击“＋关键帧”保存到 ${time.toFixed(2)}秒。`);
  controls();persist();
 }
 function readOrbit(){
  const o={};for(const id of orbitIds){if($(id).value.trim()===''||!Number.isFinite(Number($(id).value))){$(id).setAttribute('aria-invalid','true');throw new Error('请填写有效的'+({targetLon:'目标经度',targetLat:'目标纬度',rangeKm:'距离'}[id]||id));}o[id]=Number($(id).value);}
  const normalized=T.wrap(o.targetLon),changed=Math.abs(normalized-o.targetLon)>1e-8;o.targetLon=normalized;if(document.activeElement!==$('targetLon'))$('targetLon').value=normalized;
  const p=T.orbitPose(o,project.output,C);p.brightness=bridge.brightness();p.utc=bridge.utc();changePose(p,o);
  if(changed)message(`经度已换算为 ${normalized}°。300°东经等价于−60°，不是无效参数。`);
  const bounds=bridge.bounds?.();
  if(bounds){const[w,s,e,n]=bounds,insideLon=w<=e?normalized>=w&&normalized<=e:normalized>=w||normalized<=e;if(!insideLon||o.targetLat<s||o.targetLat>n)message(`参数已生效；目标在当前素材范围之外（${bounds.join(', ')}），灰色表示未制作区域。`);}
 }
 let rollReference=0;
 function applyParameter(id){
  const field=$(id),value=Number(field.value);
  if(!field.value.trim()||!Number.isFinite(value)||!field.checkValidity())throw new Error('请输入范围内的有效数值（'+field.min+' ～ '+field.max+'）');
  if(id==='roll'&&!currentOrbit){const p=A.rotate(capture(),'roll',-(value-rollReference),C);changePose(p,null);}
  else if(id==='fov'&&!currentOrbit){const p=capture();p.verticalFov=C.Math.toRadians(value);changePose(p,null);}
  else readOrbit();
 }
 for(const id of orbitIds){
  const field=$(id),slider=$(id+'Slider');
  field.onfocus=()=>{halt();historyGroup='number:'+id+':'+(++gestureSerial);};
  field.oninput=()=>{halt();if(field.value.trim()&&Number.isFinite(Number(field.value))&&field.checkValidity())guard(()=>applyParameter(id))();};
  field.onblur=()=>{controls(true);historyGroup=null;};
  slider.onpointerdown=()=>{halt();historyGroup='slider:'+id+':'+(++gestureSerial);};
  slider.onpointerup=()=>{historyGroup=null;};
  field.onchange=guard(()=>{clearTimeout(parameterTimer);applyParameter(id);});
  field.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();clearTimeout(parameterTimer);guard(()=>applyParameter(id))();}};
  slider.oninput=guard(()=>{clearTimeout(parameterTimer);field.value=slider.value;applyParameter(id);});
  slider.ondblclick=guard(()=>{clearTimeout(parameterTimer);field.value=defaults()[id];applyParameter(id);message('该参数已恢复默认值。');});
 }
 $('resetTyphoon').onclick=guard(()=>{
  clearTimeout(parameterTimer);halt();editRevision++;currentOrbit={...defaults(),heading:0,pitch:-90,roll:0};
  const p=T.orbitPose(currentOrbit,project.output,C);p.brightness=bridge.brightness();p.utc=bridge.utc();applyPose(p);dirty=true;controls();
  persist();message('已回到素材默认垂直俯视；已有关键帧未改。点“＋关键帧”保存此构图。');
 });
 function preset(heading,pitch){$('heading').value=heading;$('pitch').value=pitch;readOrbit();}
 $('presetSide').onclick=guard(()=>preset(0,-25));$('presetTop').onclick=guard(()=>preset(0,-90));$('presetDiagonal').onclick=guard(()=>preset(-60,-40));
 bridge.setTarget=(lon,lat)=>{
  project.weather=bridge.weatherRange?.()??project.weather;
  if(!restored&&track().keys.length===0){currentOrbit={...defaults(),...(bridge.defaultView?.()??{targetLon:lon,targetLat:lat})};const p=T.orbitPose(currentOrbit,project.output,C);p.utc=bridge.utc();applyPose(p);controls(true);addKey();message('已建立0秒起点。将时间条移到10秒，调整构图，再点“＋关键帧”。');}
  else if(track().keys.length)seek(time);
  if(restoredEditor&&!editorRestoredAfterMaterial){restoreEditor(restoredEditor);editorRestoredAfterMaterial=true;}
  controls();persist();
 };
 bridge.regionOverview=guard(()=>{currentOrbit={...(currentOrbit??{targetLon:130,targetLat:20,heading:0,pitch:-90,roll:0,fov:40}),rangeKm:18000};changePose(T.orbitPose(currentOrbit,project.output,C),currentOrbit);});
 function addKey(){
  halt();clearTimeout(parameterTimer);clearTimeout(timeInputTimer);
  const requested=Number($('keyAt').value);if(!Number.isFinite(requested)||requested<0||requested>length())throw new Error('关键帧时间超出范围');time=snap(requested);
  for(const id of orbitIds)if(!$(id).value.trim()||!Number.isFinite(Number($(id).value))||!$(id).checkValidity())throw new Error('请先完成有效的相机参数输入');
  if(currentOrbit)readOrbit();
  const old=selectedKey();project=T.upsert(project,active,{...(old?copy(old):{}),time,pose:capture(),orbit:currentOrbit?copy(currentOrbit):null},S);dirty=false;delete track().editorDraft;renderTimeline();drawPath();persist();message(`已${old?'更新':'添加'} ${time.toFixed(2)}秒关键帧；移动播放头到另一秒可继续添加。`);
 }
 $('addKey').onclick=guard(addKey);
 $('deleteKey').onclick=guard(()=>{halt();const key=selectedKey();if(!key)throw new Error('先点击时间轴上的钻石，选中要删除的关键帧。');track().keys=track().keys.filter(k=>k!==key);renderTimeline();drawPath();persist();message('关键帧已删除。');});
 $('playhead').ondblclick=()=>{halt();seek(0);};
 $('playhead').oninput=guard(()=>{halt();seek(snap(Number($('playhead').value)));});
 function commitTime(){if(!$('keyAt').value.trim())return;const value=Number($('keyAt').value);if(!Number.isFinite(value)||value<0||value>length())throw new Error('当前秒应位于0与总时长之间');halt();if(dirty){time=snap(value);renderTime();renderSelection();renderSpeed();message('已保留整套当前构图，点击关键帧按钮保存到此时间。');}else seek(snap(value));}
 $('keyAt').onfocus=halt;
 $('duration').onfocus=halt;
 $('curvePointTime').onfocus=halt;$('curvePointProgress').onfocus=halt;
 $('keyAt').onchange=guard(commitTime);
 $('keyAt').oninput=()=>{halt();clearTimeout(timeInputTimer);timeInputTimer=setTimeout(guard(commitTime),250);};
 $('keyAt').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();guard(commitTime)();}};
 $('goStart').onclick=()=>{halt();seek(0);};
 $('play').onclick=async()=>{
  if(playing||preparing){halt();return;}if(dirty){message('当前构图尚未保存为关键帧；请点＋关键帧后播放。',true);return;}
  bridge.stopWeather();if(time>=length()-1e-5)time=0;
  const request=++playRequest;preparing=true;tick.stall=0;tick.fallback=false;tick.mediaTime=undefined;tick.mediaStamp=performance.now();$('play').textContent='准备连续云图 · 点击取消';
  try{await music?.prepare();if(request!==playRequest)return;try{await Promise.race([bridge.preparePlayback?.(length(),time),new Promise((_,reject)=>setTimeout(()=>reject(Error('连续云图准备超时')),12000))]);}catch(e){tick.fallback=true;bridge.fallbackPlayback?.();message(e.message+'；已切换逐帧天气预览，相机继续。');}if(request!==playRequest)return;
   startTime=time;started=performance.now();lastTick=started;preparing=false;playing=true;music?.sync(time,project.fps);$('play').textContent='暂停运镜＋云图';
   const poses=track().keys.map(k=>JSON.stringify(k.orbit??[k.pose.position,k.pose.direction,k.pose.up,k.pose.verticalFov]));
   message(new Set(poses).size<2?'关键帧构图相同，相机保持静止；云图仍按延时播放。调整另一秒的构图并保存关键帧即可产生运镜。':'正在同步播放运镜和云图；源图按项目帧率播放；相机按关键帧运动。');
  }catch(error){if(request===playRequest){halt();message(error.message,true);}}
 };
 function retime(){halt();const old=length(),next=Number($('duration').value);if(next===old)return;const all=$('retimeScope').value==='all';project=all?T.retime(project,project.duration*next/old,S):T.retimeTrack(project,active,next,S);time*=next/old;renderTimeline();drawPath();seek(time);persist();message(`${all?'全部分镜同比缩放':'当前分镜'}时长改为 ${next}秒；路径和速度曲线形状保留，源图播放继续使用项目帧率。`);}
 $('retime').onclick=guard(retime);$('duration').onchange=guard(retime);
 $('duration').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();guard(retime)();}};
 bridge.retimeFromWeather=seconds=>{const before=snapshot();$('duration').value=seconds;retime();record(before);};
 function picker(){ $('trackSelect').replaceChildren(...project.tracks.map(t=>new Option(t.name,t.id)));$('trackSelect').value=active;$('takeName').value=track().name;planner?.render();music?.render();library?.render();layout?.render();music?.sync(time,project.fps); }
 function switchTrack(id){if(dirty)track().editorDraft={time,orbit:currentOrbit?copy(currentOrbit):null,pose:capture()};halt();layout?.selectShot();overviewReady=false;active=id;project.activeTrack=id;picker();renderTimeline();drawPath();if(track().editorDraft){const d=track().editorDraft;time=clamp(d.time,0,length());currentOrbit=d.orbit?copy(d.orbit):null;applyPose(d.pose);dirty=true;renderTime();controls(true);message("已恢复这个镜头尚未保存为关键帧的构图，请点＋关键帧保存。");}else seek(time);persist();}
 $('trackSelect').onchange=()=>switchTrack($('trackSelect').value);
 function newTake(duplicate){if(project.tracks.length>=50)throw new Error('每个工程最多50条分镜');halt();const id='take_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,6);const t=duplicate?copy(track()):{easing:'linear',keys:[],duration:length(),weather:copy(track().weather??project.weather)};t.id=id;t.asset={id:EarthMusic.id(),revision:1,createdUtc:new Date().toISOString()};if(duplicate&&project.music?.shots[active])project.music.shots[id]=copy(project.music.shots[active]);t.name=duplicate?track().name+' 副本':'分镜 '+String.fromCharCode(65+project.tracks.length);project.tracks.push(t);switchTrack(id);message('新分镜继承当前天气范围；可独立调整起止、时长和构图。');}
 $('takeAdd').onclick=guard(()=>newTake(false));$('takeClone').onclick=guard(()=>newTake(true));
 $('takeRename').onclick=guard(()=>{const name=$('takeName').value.trim();if(!name)throw new Error('请输入分镜名称');track().name=name;picker();persist();});
 $('takeDelete').onclick=guard(()=>{if(project.tracks.length===1)throw new Error('至少保留一条分镜');project.tracks=project.tracks.filter(t=>t.id!==active);if(project.music)delete project.music.shots[active];switchTrack(project.tracks[0].id);});
 $('newDemo').onclick=guard(()=>{
  if(track().keys.length>1)newTake(false);
  const base=currentOrbit??{targetLon:130,targetLat:20,rangeKm:4500,fov:40};
  track().keys=[{time:0,heading:0,pitch:-25,rangeKm:4500,roll:0,fov:40},{time:length()/2,heading:0,pitch:-90,rangeKm:3000,roll:0,fov:32},{time:length(),heading:-60,pitch:-40,rangeKm:2500,roll:30,fov:45}].map(k=>{const o={...base,...k};delete o.time;const p=T.orbitPose(o,project.output,C);p.utc=bridge.utc();return {time:k.time,pose:p,orbit:o};});
  track().name='示范：侧视 → 俯视 → 斜视';track().easing='smooth';delete track().curve;picker();renderTimeline();drawPath();seek(0);persist();message('示范已就绪：点击播放，或拖动播放头观察三个关键帧之间的连续变化。');
 });
 $('projectSave').onclick=guard(()=>{T.validate(project,S);bridge.save(serializeProject(),'plan-export','earth-keyframes.json');message('关键帧工程已下载，包含全部分镜、时间和速度曲线。');});
 $('projectOpenButton').onclick=()=>$('projectOpen').click();
 $('projectOpen').onchange=async()=>{halt();try{const file=$('projectOpen').files[0];if(!file)return;if(file.size>20*1024*1024)throw new Error('工程文件过大');let value=JSON.parse(await file.text());if(value.schema==='earthstudio.shots.v1')value=T.fromLegacy(S.validate(value),project.output);const editorState=value.editorState??null;project=T.validate(value,S);delete project.editorState;project.effects??={blueAtmosphere:true,nightAirglow:true};EarthShotLibrary.migrate(project);syncEffects();active=project.tracks.some(t=>t.id===project.activeTrack)?project.activeTrack:project.tracks[0].id;restored=true;time=0;fit();picker();renderTimeline();drawPath();seek(0);restoreEditor(editorState);persist();history.clear();historyButtons();message('工程已打开，所有分镜和曲线已恢复。');}catch(e){message(e.message,true);}$('projectOpen').value='';};
 $('exportActive').onclick=guard(()=>{const data=bridge.annotateTrack(T.bake(project,active,C,S));bridge.save(data,'camera-export','keyframe-camera.json');message('已导出当前分镜可编辑相机；天气材质尚未包含在此导出中。');});
 $('exportAll').onclick=guard(()=>{if(dirty||project.tracks.some(t=>t.editorDraft))throw Error('存在尚未保存为关键帧的构图，请切回对应镜头并点＋关键帧，再导出。');const valid=project.tracks.filter(t=>t.keys.length);if(valid.length!==project.tracks.length)throw Error('请为所有分镜添加关键帧，或删除空分镜，再导出连续成片');if(valid.reduce((count,t)=>count+Math.ceil(T.duration(project,t.id)*project.fps)+1,0)>S.MAX_SAMPLES)throw new Error('全部分镜合计超过100万点，请分别导出或分段');const tracks=valid.map(t=>bridge.annotateTrack(T.bake(project,t.id,C,S)));if(!tracks.length)throw new Error('没有可导出的关键帧');bridge.save({schema:'earthstudio.camera_bundle.v1',tracks,timelineProject:project},'camera-export','all-take-cameras.json');message(`已导出 ${tracks.length}条独立分镜相机，项目帧率一致，天气起点独立。`);});
 // Direct 3D manipulation updates the same parameters shown in the inspector.
 viewer.scene.screenSpaceCameraController.enableInputs=false;
 viewer.canvas.style.touchAction='none';
 viewer.canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;halt();sceneDrag={before:snapshot(),x:e.clientX,y:e.clientY,orbit:currentOrbit?copy(currentOrbit):null,pose:capture(),mode:$('mouseMode').value};viewer.canvas.setPointerCapture(e.pointerId);});
 viewer.canvas.addEventListener('pointermove',e=>{
  if(!sceneDrag)return;const dx=e.clientX-sceneDrag.x,dy=e.clientY-sceneDrag.y;
  try{
   if(sceneDrag.mode==='globe'){const rect=viewer.canvas.getBoundingClientRect(),p=EarthGlobeDrag.rotate(sceneDrag.pose,[sceneDrag.x-rect.left,sceneDrag.y-rect.top],[e.clientX-rect.left,e.clientY-rect.top],[rect.width,rect.height],C);changePose(p,EarthGlobeDrag.orbit(p,C));}
   else if(sceneDrag.mode==='orbit'){
    const o=sceneDrag.orbit??{targetLon:Number($('targetLon').value),targetLat:Number($('targetLat').value),heading:0,pitch:-45,rangeKm:4500,roll:0,fov:C.Math.toDegrees(sceneDrag.pose.verticalFov)};
    const next={...o,heading:o.heading-dx*.25,pitch:clamp(o.pitch+dy*.2,-179.9,-.1)};changePose(T.orbitPose(next,project.output,C),next);
   }else if(sceneDrag.mode==='look'){const p=A.rotate(A.rotate(sceneDrag.pose,'yaw',-dx*.15,C),'pitch',-dy*.15,C);changePose(p,null);}
   else if(sceneDrag.orbit){const o={...sceneDrag.orbit,roll:sceneDrag.orbit.roll+dx*.25};changePose(T.orbitPose(o,project.output,C),o);}
   else changePose(A.rotate(sceneDrag.pose,'roll',-dx*.25,C),null);
  }catch(error){message(error.message,true);}
 });
 function finishSceneDrag(){if(sceneDrag){record(sceneDrag.before);sceneDrag=null;}}
 viewer.canvas.addEventListener('pointerup',finishSceneDrag);viewer.canvas.addEventListener('pointercancel',finishSceneDrag);
 viewer.canvas.addEventListener('wheel',e=>{e.preventDefault();const before=snapshot();try{if(currentOrbit){const o={...currentOrbit,rangeKm:clamp(currentOrbit.rangeKm*Math.exp(e.deltaY*.001),100,50000)};changePose(T.orbitPose(o,project.output,C),o);}else {const p=capture(),position=C.Cartesian3.fromArray(p.position),d=C.Cartesian3.fromArray(p.direction),altitude=C.Cartographic.fromCartesian(position).height;C.Cartesian3.add(position,C.Cartesian3.multiplyByScalar(d,-e.deltaY*Math.max(altitude,100000)*.0005,new C.Cartesian3()),position);if(C.Cartographic.fromCartesian(position).height<1000)throw new Error('相机已接近地表，不能继续推进');p.position=[position.x,position.y,position.z];changePose(p,null);}record(before,'wheel');}catch(error){message(error.message,true);}},{passive:false});
 viewer.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
 viewer.screenSpaceEventHandler.setInputAction(e=>{const point=viewer.camera.pickEllipsoid(e.position,viewer.scene.globe.ellipsoid);if(!point)return;const g=C.Cartographic.fromCartesian(point);$('targetLon').value=C.Math.toDegrees(g.longitude);$('targetLat').value=C.Math.toDegrees(g.latitude);guard(readOrbit)();},C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
 // Keyframe diamonds and parameter tracks.
 function renderSelection(){for(const button of $('ruler').querySelectorAll('.key'))button.classList.toggle('selected',Math.abs(Number(button.dataset.time)-time)<1e-5);}
 function renderTimeline(){
  const ruler=$('ruler');ruler.replaceChildren();
  for(const key of track().keys){const b=document.createElement('button');b.className='key';b.textContent='◆';b.dataset.time=key.time;b.style.left=(key.time/length()*100)+'%';b.setAttribute('aria-label',key.time.toFixed(2)+'秒关键帧');const small=document.createElement('small');small.textContent=key.time.toFixed(1)+'s';b.appendChild(small);
   b.onclick=e=>{e.stopPropagation();halt();seek(key.time);};
   b.onpointerdown=e=>{e.preventDefault();e.stopPropagation();halt();b.setPointerCapture(e.pointerId);keyDrag={before:snapshot(),key,button:b,startX:e.clientX,original:key.time,rect:ruler.getBoundingClientRect()};};
   b.onkeydown=guard(()=>{});b.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const before=snapshot(),value=clamp(snap(key.time+(e.key==='ArrowRight'?1:-1)*(e.shiftKey?1:1/project.fps)),0,length());if(track().keys.some(k=>k!==key&&Math.abs(k.time-value)<1e-5)){message('该时间已有关键帧，请换一个时间。',true);return;}key.time=value;track().keys.sort((a,b)=>a.time-b.time);renderTimeline();drawPath();seek(value);persist();record(before);});ruler.appendChild(b);
  }
  const rows=$('curveRows');rows.replaceChildren();
  const list=[['heading','绕行'],['pitch','俯看'],['rangeKm','推进'],['roll','旋转'],['fov','透视']];
  const values=track().keys.length?Array.from({length:51},(_,i)=>T.sample(project,active,length()*i/50,C,S)):[];
  for(const [id,label]of list){const row=document.createElement('div');row.className='parameterRow';const text=document.createElement('span');text.textContent=label;row.appendChild(text);const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 600 24');svg.setAttribute('preserveAspectRatio','none');const numbers=values.map(p=>p.orbit?.[id]);
   if(numbers.length&&numbers.every(Number.isFinite)){const min=Math.min(...numbers),max=Math.max(...numbers),path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',numbers.map((v,i)=>(i?'L':'M')+(i*12)+','+(max-min<1e-9?12:21-(v-min)/(max-min)*18)).join(' '));path.setAttribute('stroke','#6eb8eb');path.setAttribute('fill','none');path.setAttribute('stroke-width','1.4');svg.appendChild(path);}
   row.appendChild(svg);rows.appendChild(row);
  }
  renderTime();renderSelection();renderSpeed();
 }
 $('ruler').onclick=guard(()=>{ });
 $('ruler').addEventListener('click',e=>{if(e.target!==$('ruler'))return;const r=$('ruler').getBoundingClientRect();halt();seek(snap(clamp((e.clientX-r.left)/r.width,0,1)*length()));});
 window.addEventListener('pointermove',e=>{
  if(keyDrag){const {key,button,rect}=keyDrag,value=clamp(snap((e.clientX-rect.left)/rect.width*length()),0,length());if(track().keys.some(k=>k!==key&&Math.abs(k.time-value)<1e-5))return;key.time=value;button.style.left=(value/length()*100)+'%';button.querySelector('small').textContent=value.toFixed(1)+'s';button.dataset.time=value;track().keys.sort((a,b)=>a.time-b.time);time=value;currentOrbit=key.orbit?copy(key.orbit):null;applyPose(key.pose);controls();renderTime();}
  if(curveDrag)dragCurve(e);
 });
 window.addEventListener('pointerup',()=>{if(keyDrag){const before=keyDrag.before,dest=keyDrag.key.time,original=keyDrag.original;keyDrag=null;T.validate(project,S);renderTimeline();drawPath();seek(dest);$('ruler').focus({preventScroll:true});persist();if(Math.abs(dest-original)>1e-5)record(before);message(`已选中 ${dest.toFixed(2)}秒关键帧，可直接调整构图；按 Delete 删除。`);}if(curveDrag){const before=curveDrag.before;curveDrag=null;persist();record(before);}});
 // Speed editor: monotone time-to-path mapping, separately from the path itself.
 const presets=T.PRESETS;
 function interval(){const keys=track().keys;if(!keys.length)return null;let index=0;while(index<keys.length-2&&time>=keys[index+1].time)index++;return keys.length<2?null:{a:keys[index],b:keys[index+1]};}
 function speedPoints(){if($('curveScope').value==='weather')return copy(track().weather?.curve??presets.linear);const part=interval();return copy($('curveScope').value==='segment'&&part?.a.curve?part.a.curve:track().curve??(track().easing==='smooth'?presets.smooth:presets.linear));}
 function setSpeed(points){if(dirty)throw new Error('请先点“＋关键帧”保存当前构图，再调整速度。');T.validateCurve(points);if($('curveScope').value==='weather'){if(project.sourcePlayback||track().weather?.observationFps!==undefined)throw new Error('云图使用项目统一帧率；请切换到相机或关键帧区间编辑运镜速度曲线');track().weather={...copy(track().weather??project.weather),curve:copy(points)};}else if($('curveScope').value==='segment'){const part=interval();if(!part)throw new Error('先添加两个关键帧，再编辑区间速度。');part.a.curve=copy(points);}else {track().curve=copy(points);track().easing='linear';for(const key of track().keys)delete key.curve;}
  persist();renderTimeline();drawPath();seek(time);
 }
 let lastSpeedSignature='';
 function renderSpeed(){
  const partNow=interval(),signature=JSON.stringify([active,$('curveScope').value,partNow?.a.time,partNow?.b.time,speedPoints(),curveSelected]);
  if(playing&&signature===lastSpeedSignature)return;lastSpeedSignature=signature;
  const points=speedPoints(),svg=$('speedGraph');svg.replaceChildren();const ns='http://www.w3.org/2000/svg';
  const grid=document.createElementNS(ns,'path');grid.setAttribute('d','M20 10V110H300 M20 60H300 M160 10V110');grid.setAttribute('stroke','#39506a');grid.setAttribute('fill','none');svg.appendChild(grid);
  const path=document.createElementNS(ns,'path');path.setAttribute('d',Array.from({length:101},(_,i)=>(i?'L':'M')+(20+i*2.8)+','+(110-T.progress(points,i/100)*100)).join(' '));path.setAttribute('stroke','#76c6ff');path.setAttribute('stroke-width','2');path.setAttribute('fill','none');svg.appendChild(path);
  points.forEach((p,i)=>{const c=document.createElementNS(ns,'circle');c.setAttribute('cx',20+p[0]*280);c.setAttribute('cy',110-p[1]*100);c.setAttribute('r',i===0||i===points.length-1?4:5);c.dataset.index=i;c.classList.toggle('selected',i===curveSelected);c.onpointerdown=e=>{e.preventDefault();e.stopPropagation();svg.setPointerCapture(e.pointerId);curveSelected=i;curveDrag={index:i,before:snapshot()};$('curvePointTime').value=Math.round(p[0]*100);$('curvePointProgress').value=Math.round(p[1]*100);renderSpeed();};svg.appendChild(c);});
  curveSelected=Math.min(curveSelected,points.length-1);const selected=points[curveSelected];
  if(document.activeElement!==$('curvePointTime'))$('curvePointTime').value=Number((selected[0]*100).toFixed(1));
  if(document.activeElement!==$('curvePointProgress'))$('curvePointProgress').value=Number((selected[1]*100).toFixed(1));
  const part=interval();$('speedHint').textContent=($('curveScope').value==='segment'&&part?`${part.a.time.toFixed(1)}→${part.b.time.toFixed(1)}秒。`:'整条分镜的各区间。')+'横轴时间，纵轴路径进度；越陡越快。点击加点、拖点改速；端点不变。';
  if($('curveScope').value==='weather')$('speedHint').textContent='当前分镜的天气节奏：横轴是镜头时间，纵轴是天气区间进度。平段暂停天气，陡段加快；相机路径不变。';
  const preset=Object.keys(presets).find(k=>JSON.stringify(presets[k])===JSON.stringify(points));$('speedPreset').value=preset??'custom';
 }
 function graphCoords(e){const r=$('speedGraph').getBoundingClientRect();return [clamp((e.clientX-r.left)/r.width*320-20,0,280)/280,clamp(110-(e.clientY-r.top)/r.height*130,0,100)/100];}
 function dragCurve(e){const points=speedPoints(),i=curveDrag.index;if(i===0||i===points.length-1)return;const[x,y]=graphCoords(e);points[i]=[clamp(x,points[i-1][0]+.005,points[i+1][0]-.005),clamp(y,points[i-1][1],points[i+1][1])];try{setSpeed(points);$('curvePointTime').value=Math.round(points[i][0]*100);$('curvePointProgress').value=Math.round(points[i][1]*100);}catch(error){message(error.message,true);}}
 $('speedGraph').addEventListener('click',e=>{if(e.target.tagName.toLowerCase()==='circle'||curveDrag)return;const before=snapshot();try{const points=speedPoints(),[x,y]=graphCoords(e);if(x<.005||x>.995)return;let i=points.findIndex(p=>p[0]>x);if(i<1)return;if(x-points[i-1][0]<.005||points[i][0]-x<.005)return;points.splice(i,0,[x,clamp(y,points[i-1][1],points[i][1])]);curveSelected=i;setSpeed(points);record(before);}catch(error){message(error.message,true);}});
 $('speedPreset').onchange=guard(()=>{if(presets[$('speedPreset').value]){curveSelected=1;setSpeed(presets[$('speedPreset').value]);message('速度曲线已更新；回放区间内可以看到快慢变化，关键帧构图不变。');}});
 $('curveScope').onchange=renderSpeed;
 $('applyCurvePoint').onclick=guard(()=>{const points=speedPoints(),i=curveSelected;if(i===0||i>=points.length-1)throw new Error('首尾端点固定，请选择或添加内部控制点');points[i]=[Number($('curvePointTime').value)/100,Number($('curvePointProgress').value)/100];setSpeed(points);});
 $('removeCurvePoint').onclick=guard(()=>{const points=speedPoints();if(curveSelected===0||curveSelected>=points.length-1)throw new Error('首尾端点不能删除');points.splice(curveSelected,1);curveSelected=Math.max(0,curveSelected-1);setSpeed(points);});
 // Independent, rotatable 3D planning view.
 const overview=new C.Viewer('pathGlobe',{creditContainer:document.getElementById('overviewCredits'),creditViewport:document.body,baseLayer:C.ImageryLayer.fromProviderAsync(C.SingleTileImageryProvider.fromUrl('no-observation.png')),baseLayerPicker:false,geocoder:false,animation:false,timeline:false,homeButton:false,sceneModePicker:false,navigationHelpButton:false,fullscreenButton:false,selectionIndicator:false,infoBox:false,skyAtmosphere:false,skyBox:false,requestRenderMode:true});
 overview.scene.globe.showGroundAtmosphere=false;overview.scene.globe.enableLighting=false;overview.scene.backgroundColor=C.Color.fromCssColorString('#101e30');
 let overviewCamera=null,overviewDirection=null;
 function drawPath(){
  overview.entities.removeAll();overviewCamera=null;overviewDirection=null;
  if(!track().keys.length){overview.scene.requestRender();return;}
  const points=Array.from({length:81},(_,i)=>C.Cartesian3.fromArray(T.sample(project,active,length()*i/80,C,S).position));
  overview.entities.add({polyline:{positions:points,width:2,material:C.Color.fromCssColorString('#61c0ff'),arcType:C.ArcType.NONE}});
  for(const key of track().keys)overview.entities.add({id:'key:'+key.time,position:C.Cartesian3.fromArray(key.pose.position),point:{pixelSize:7,color:C.Color.LIGHTSKYBLUE,disableDepthTestDistance:Number.POSITIVE_INFINITY}});
  overviewCamera=overview.entities.add({position:points[0],point:{pixelSize:9,color:C.Color.ORANGE,disableDepthTestDistance:Number.POSITIVE_INFINITY}});
  overviewDirection=overview.entities.add({polyline:{positions:[points[0],points[0]],width:2,material:C.Color.ORANGE,arcType:C.ArcType.NONE}});
  const o=track().keys[0].orbit;
  if(!overviewReady||(o&&(!overviewTarget||Math.abs(T.wrap(o.targetLon-overviewTarget.lon))>10||Math.abs(o.targetLat-overviewTarget.lat)>10))){overview.camera.setView({destination:C.Cartesian3.fromDegrees(o?.targetLon??130,o?.targetLat??20,24000000)});overviewReady=true;overviewTarget={lon:o?.targetLon??130,lat:o?.targetLat??20};}
  if(currentPose)updateOverviewCamera(currentPose);overview.scene.requestRender();
 }
 function updateOverviewCamera(p){if(!overviewCamera)return;const now=performance.now();if(playing&&now-lastOverviewUpdate<100)return;lastOverviewUpdate=now;const a=C.Cartesian3.fromArray(p.position),b=C.Cartesian3.add(a,C.Cartesian3.multiplyByScalar(C.Cartesian3.fromArray(p.direction),1500000,new C.Cartesian3()),new C.Cartesian3());overviewCamera.position=a;overviewDirection.polyline.positions=[a,b];overview.scene.requestRender();}
 overview.screenSpaceEventHandler.setInputAction(e=>{const hit=overview.scene.pick(e.position),id=hit?.id?.id;if(typeof id==='string'&&id.startsWith('key:')){halt();seek(Number(id.slice(4)));}},C.ScreenSpaceEventType.LEFT_CLICK);
 $('pathPane').ontoggle=()=>overview.resize();
 window.addEventListener('resize',fit);
 new ResizeObserver(fit).observe($('stage'));
 planner=EarthStoryboard.createUi({project:()=>project,active:()=>active,time:()=>time,actualWeather:()=>bridge.actualWeatherUtc?bridge.actualWeatherUtc():bridge.utc(),select:switchTrack,edit:guard,currentWeather:()=>T.weatherTime(project,time,active),intervalSeconds:()=>bridge.weatherIntervalSeconds(),replace:(value,options={})=>{if(dirty)throw new Error('当前构图尚未保存，请先点＋关键帧，再修改分镜时间');halt();project=value;time=clamp(time*(options.timeScale??1),0,length());picker();renderTimeline();drawPath();seek(time);persist();message('已更新当前设置；分镜独立，裁切保留原始关键帧。');}});
 async function montageAt(frame,play){
  if(dirty){message('请先保存当前构图关键帧。',true);return;}
  try{const row=EarthMontage.locate(project,frame,T);if(!project.tracks.find(t=>t.id===row.id).keys.length)throw Error('连续成片中的分镜尚未添加关键帧');switchTrack(row.id);seek(row.sourceFrame/project.fps);
   $('montageSeek').value=frame;$('montageState').textContent=`成片 ${(frame/project.fps).toFixed(3)}秒 · ${row.name} · 源镜头 ${time.toFixed(3)}秒`;
   if(play){const pending=$('play').onclick(),request=playRequest;await pending;if(playing&&request===playRequest){montageRow=row;$('montagePlay').textContent='暂停连续成片';}}
  }catch(error){halt();message(error.message,true);}
 }
 $('exportMapping').onclick=guard(()=>{if(!bridge.mappingFrames?.().length)throw Error('请先载入素材');if(project.tracks.some(t=>!t.keys.length))throw Error('请先完成或删除空分镜');bridge.save(EarthFrameMapping.receipt(project,bridge.mappingFrames(),T,EarthMontage,bridge.mappingHold()),'plan-export','frame-mapping.json');message('已导出成片每帧的镜头、源帧、UTC、实际扫描与缺档显示记录。');});
 $('montageSeek').oninput=()=>{montageAt(Number($('montageSeek').value),false);};
 $('montagePlay').onclick=()=>{if(montageRow||preparing){halt();return;}montageAt(Number($('montageSeek').value),true);};
 music=EarthMusicUI.create({project:()=>project,active:()=>active,time:()=>time,length,playing:()=>playing,halt,seek,persist,edit:guard,
  align:value=>guard(()=>{const key=selectedKey();if(!key)throw Error('先在相机轨道选中一个关键帧，再点击对齐');const next=snap(value);if(next<0||next>length()||track().keys.some(k=>k!==key&&Math.abs(k.time-next)<1e-5))throw Error('标记超出镜头或目标帧已有关键帧');const index=track().keys.indexOf(key);if((index>0&&next<=track().keys[index-1].time)||(index<track().keys.length-1&&next>=track().keys[index+1].time))throw Error('对齐不能跨过相邻关键帧，以免改变路径顺序');halt();key.time=next;track().keys.sort((a,b)=>a.time-b.time);renderTimeline();drawPath();seek(next);persist();})()});
 library=EarthLibraryUI.create({project:()=>project,active:()=>active,frames:()=>bridge.mappingFrames?.()??[],select:switchTrack,halt,edit:guard,save:bridge.save,message,
  utc:()=>bridge.actualWeatherUtc?.()??bridge.utc(),localUTC:()=>T.weatherTime(project,time,active),
  changeWeather:(id,weather)=>{if(dirty)throw Error('当前构图尚未保存，请先保存关键帧');halt();project=EarthStoryboard.setWeather(project,id,weather,T,S);if(id===active)seek(time);renderTimeline();persist();},
  browse:index=>{const field=$('weatherScrub');field.value=index;field.dispatchEvent(new Event('input'));},
  create:weather=>{const probe=copy(project),original=probe.tracks.find(t=>t.id===active);original.weather=weather;T.validate(probe,S);newTake(false);track().weather=copy(weather);renderTimeline();persist();}});
 layout=EarthWorkspaceLayout.create({project:()=>project,active:()=>active,time:()=>time,length,halt});
 syncEffects();historyButtons();picker();fit();renderTimeline();if(track().keys.length){drawPath();seek(0);}else controls();if(restoredEditor)restoreEditor(restoredEditor);
 message(restored?'已恢复本机关键帧工程。可切换分镜继续编辑。':'先点击“示范”，或在0秒摆好画面后添加关键帧。');
 function tick(now){if(playing){const delta=now-lastTick;lastTick=now;if(!tick.fallback&&(bridge.weatherReady?.()===false||bridge.playbackBuffered?.())){if(!tick.stall)tick.stall=now;if(now-tick.stall<2000){started+=delta;music?.stop();requestAnimationFrame(tick);return;}tick.fallback=true;bridge.fallbackPlayback?.();message('天气预览缓冲超时，已切换逐帧预览；相机继续按关键帧运动。');}else tick.stall=0;let media=bridge.playbackTime?.(length());if(media!==null&&media!==undefined&&!tick.fallback){if(tick.mediaTime===undefined||media>tick.mediaTime+1e-5){tick.mediaTime=media;tick.mediaStamp=now;}else if(now-tick.mediaStamp>2000){tick.fallback=true;bridge.fallbackPlayback?.();started=now-(time-startTime)*1000;media=null;message('连续预览时钟停滞，已恢复逐帧预览，相机继续运动。');}}const next=Math.min(length(),Math.max(time,media??(startTime+(now-started)/1000)));const loop=music?.loop(next);if(loop!==null&&loop!==undefined){halt();seek(loop);$('play').click();requestAnimationFrame(tick);return;}
  if(montageRow){const row=montageRow,frame=Math.floor(next*project.fps+1e-5);
   if(frame>=row.outFrame&&!montageTransition){const target=row.endFrame,total=EarthMontage.layout(project,T).at(-1).endFrame;halt();if(target<total){montageTransition=true;montageAt(target,true).finally(()=>montageTransition=false);}else{$('montageSeek').value=total-1;seek((row.outFrame-1)/project.fps);$('montageState').textContent='连续成片播放结束';}}
   else{seek(next);$('montageSeek').value=row.startFrame+Math.max(0,frame-row.inFrame);$('montageState').textContent=`成片 ${(Number($('montageSeek').value)/project.fps).toFixed(3)}秒 · ${row.name}`;}
  }else{seek(next);if(next>=length()-1e-5&&bridge.playbackFinished?.()!==false){halt();seek(length());}}}requestAnimationFrame(tick);}requestAnimationFrame(tick);
 persist();
 return {stop:halt};
}
