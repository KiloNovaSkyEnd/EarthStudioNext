'use strict';
function setupCameraTools(viewer, bridge) {
  const C=Cesium, $=id=>document.getElementById(id), vector=v=>[v.x,v.y,v.z];
  const controller=viewer.scene.screenSpaceCameraController;
  controller.zoomEventTypes=[C.CameraEventType.WHEEL,C.CameraEventType.PINCH];
  controller.inertiaSpin=controller.inertiaTranslate=controller.inertiaZoom=0;
  function mode() {
    controller.rotateEventTypes=$('mouseMode').value==='rotate'?[C.CameraEventType.LEFT_DRAG]:[];
    controller.tiltEventTypes=$('mouseMode').value==='tilt'?[C.CameraEventType.LEFT_DRAG]:[];
    controller.lookEventTypes=$('mouseMode').value==='look'?[C.CameraEventType.LEFT_DRAG]:[];
  }
  mode(); $('mouseMode').onchange=mode;
  let recording=false,samples=[],recordStart=0,lastCapture=0,shots=[],playing=false,replayStart=0,orbitApplied=false,lastRoll=0;
  viewer.canvas.addEventListener('pointerdown',()=>{orbitApplied=false;});
  const getPlan=()=>({schema:'earthstudio.shots.v1',earthModel:'WGS84',shots});
  function pose(seconds=0) {
    return {seconds,position:vector(viewer.camera.positionWC),direction:vector(viewer.camera.directionWC),up:vector(viewer.camera.upWC),
      verticalFov:viewer.camera.frustum.fovy,aspect:viewer.camera.frustum.aspectRatio,width:viewer.canvas.width,height:viewer.canvas.height,
      utc:bridge.utc(),brightness:bridge.brightness()};
  }
  function frustum(vertical) {
    const aspect=viewer.canvas.width/viewer.canvas.height;
    viewer.camera.frustum.fov=aspect>1?2*Math.atan(Math.tan(vertical/2)*aspect):vertical;
  }
  function setPose(p) {
    viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
    viewer.camera.position=C.Cartesian3.fromArray(p.position);
    viewer.camera.direction=C.Cartesian3.fromArray(p.direction);
    viewer.camera.up=C.Cartesian3.fromArray(p.up);
    viewer.camera.right=C.Cartesian3.cross(viewer.camera.direction,viewer.camera.up,new C.Cartesian3());
    frustum(p.verticalFov); bridge.setWeather(p.timelineUtc??p.utc,p.brightness); viewer.scene.requestRender();
    lastRoll=0;$('roll').value=0;$('rollValue').textContent='0°';
  }
  function halt() { playing=false; controller.enableInputs=true; $('replay').textContent='回放运镜'; }
  function orbit() {
    halt();
    const lon=Number($('targetLon').value),lat=Number($('targetLat').value),range=Number($('rangeKm').value);
    if(!Number.isFinite(lon)||Math.abs(lon)>180||!Number.isFinite(lat)||Math.abs(lat)>89||!Number.isFinite(range)||range<100||range>50000) throw new Error('目标经纬度或距离超出可用范围');
    viewer.camera.lookAt(C.Cartesian3.fromDegrees(lon,lat),new C.HeadingPitchRange(C.Math.toRadians(Number($('heading').value)),C.Math.toRadians(Number($('pitch').value)),range*1000));
    viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
    $('roll').value=0;$('rollValue').textContent='0°';
    frustum(C.Math.toRadians(Number($('fov').value))); viewer.scene.requestRender();
    orbitApplied=true;
    lastRoll=Number($('roll').value);
  }
  const guarded=fn=>()=>{try{fn();}catch(e){bridge.status(e.message);}};
  $('applyOrbit').onclick=guarded(orbit);
  for(const id of ['heading','pitch']) $(id).oninput=guarded(()=>{$(id+'Value').textContent=$(id).value+'°';orbit();});
  function turn(kind,degrees) {
    halt();viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
    const next=EarthCameraActions.rotate(pose(),kind,degrees,C);
    // Avoid setView's direction->HPR conversion at near-nadir angles.
    viewer.camera.direction=C.Cartesian3.fromArray(next.direction);
    viewer.camera.up=C.Cartesian3.fromArray(next.up);
    viewer.camera.right=C.Cartesian3.cross(viewer.camera.direction,viewer.camera.up,new C.Cartesian3());
    orbitApplied=false;viewer.scene.requestRender();
    if(kind!=='roll'){lastRoll=0;$('roll').value=0;$('rollValue').textContent='0°';}
    bridge.status(kind==='roll'?'只旋转画面：相机位置和观看方向保持不变。':'只原地转头：相机位置保持不变。');
  }
  $('roll').oninput=guarded(()=>{const next=Number($('roll').value);turn('roll',-(next-lastRoll));lastRoll=next;$('roll').value=next;$('rollValue').textContent=next+'°';});
  $('rollLeft').onclick=guarded(()=>{const next=lastRoll-15;turn('roll',15);lastRoll=next;$('roll').value=next;$('rollValue').textContent=next+'°';});
  $('rollRight').onclick=guarded(()=>{const next=lastRoll+15;turn('roll',-15);lastRoll=next;$('roll').value=next;$('rollValue').textContent=next+'°';});
  $('rollReset').onclick=guarded(()=>{turn('roll',lastRoll);lastRoll=0;$('roll').value=0;$('rollValue').textContent='0°';});
  $('lookLeft').onclick=guarded(()=>turn('yaw',5));$('lookRight').onclick=guarded(()=>turn('yaw',-5));
  $('lookUp').onclick=guarded(()=>turn('pitch',5));$('lookDown').onclick=guarded(()=>turn('pitch',-5));
  $('fov').oninput=guarded(()=>{halt();$('fovValue').textContent=$('fov').value+'°';frustum(C.Math.toRadians(Number($('fov').value)));viewer.scene.requestRender();});
  function preset(heading,pitch) { $('heading').value=heading;$('pitch').value=pitch;$('roll').value=0; for(const id of ['heading','pitch','roll']) $(id+'Value').textContent=$(id).value+'°';orbit(); }
  $('front').onclick=guarded(()=>preset(0,-90));
  $('leftOblique').onclick=guarded(()=>preset(-90,-25));
  $('lowerRight').onclick=guarded(()=>preset(135,-25));
  $('topOblique').onclick=guarded(()=>preset(0,-65));
  viewer.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
  viewer.screenSpaceEventHandler.setInputAction(click=>{
    const point=viewer.camera.pickEllipsoid(click.position,viewer.scene.globe.ellipsoid);
    if(!point) return;
    const geo=C.Cartographic.fromCartesian(point); $('targetLon').value=C.Math.toDegrees(geo.longitude).toFixed(4);$('targetLat').value=C.Math.toDegrees(geo.latitude).toFixed(4);guarded(orbit)();
  },C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
  bridge.setTarget=(lon,lat)=>{$('targetLon').value=lon;$('targetLat').value=lat;};
  function redraw(index=shots.length-1) {
    $('shotList').replaceChildren(...shots.map((shot,i)=>new Option(`${i+1}. ${shot.name} · ${i?shot.duration+'秒':'起点'}${shot.transition==='cut'?' · 切镜':''}`,i)));
    $('shotList').selectedIndex=index;
    $('shotSeek').max=Math.max(EarthShots.duration(getPlan()),0.001);
    $('shotState').textContent=`${shots.length}个机位 · 总长 ${EarthShots.duration(getPlan()).toFixed(2)}秒 · Blender导出为可编辑相机曲线`;
  }
  function readShot() { return {name:$('shotName').value||`机位${shots.length+1}`,duration:Number($('shotDuration').value),transition:$('transition').value,pose:pose(),
    orbit:orbitApplied?Object.fromEntries(['targetLon','targetLat','heading','pitch','rangeKm','roll','fov'].map(id=>[id,Number($(id).value)])):null}; }
  $('addShot').onclick=guarded(()=>{halt();const next=readShot();EarthShots.validate({...getPlan(),shots:[...shots,next]});shots.push(next);redraw();$('shotName').value=`机位${shots.length+1}`;});
  $('updateShot').onclick=guarded(()=>{halt();const i=$('shotList').selectedIndex;if(i<0)throw new Error('请先选中机位');const next=shots.map((x,j)=>i===j?readShot():x);EarthShots.validate({...getPlan(),shots:next});shots=next;redraw(i);});
  $('shotList').onchange=guarded(()=>{halt();const shot=shots[$('shotList').selectedIndex];if(!shot)return;setPose(shot.pose);$('shotName').value=shot.name;$('shotDuration').value=shot.duration;$('transition').value=shot.transition||'move';
    orbitApplied=!!shot.orbit;
    if(shot.orbit){for(const id of ['targetLon','targetLat','heading','pitch','rangeKm','fov']){if(Number.isFinite(shot.orbit[id]))$(id).value=shot.orbit[id];}for(const id of ['heading','pitch','fov'])$(id+'Value').textContent=$(id).value+'°';}
    bridge.status('已恢复选中画面。转头、横滚和画角可直接调整；换观察位置会重新朝向目标。');});
  $('removeShot').onclick=()=>{halt();const i=$('shotList').selectedIndex;if(i>=0){shots.splice(i,1);redraw(Math.min(i,shots.length-1));}};
  function reorder(delta){halt();const i=$('shotList').selectedIndex,j=i+delta;if(i>=0&&j>=0&&j<shots.length){[shots[i],shots[j]]=[shots[j],shots[i]];redraw(j);}}
  $('upShot').onclick=()=>reorder(-1);$('downShot').onclick=()=>reorder(1);
  function seek(seconds) { EarthShots.validate(getPlan());setPose(EarthShots.sample(getPlan(),seconds,C));$('shotSeek').value=seconds; }
  $('shotSeek').oninput=guarded(()=>{halt();seek(Number($('shotSeek').value));});
  $('replay').onclick=guarded(()=>{if(playing){halt();return;}if(recording)throw new Error('请先停止手动录制');EarthShots.validate(getPlan());if(shots.length<2)throw new Error('请至少添加两个机位');bridge.stopWeather();playing=true;controller.enableInputs=false;replayStart=performance.now();$('replay').textContent='停止回放';});
  $('savePlan').onclick=guarded(()=>{EarthShots.validate(getPlan());bridge.save(getPlan(),'plan-export','shot-plan.json');});
  $('importPlan').onchange=async()=>{try{const file=$('importPlan').files[0];if(!file)return;if(file.size>10*1024*1024)throw new Error('运镜工程文件过大');const plan=EarthShots.validate(JSON.parse(await file.text()));halt();shots=plan.shots;redraw(0);setPose(shots[0].pose);}catch(e){bridge.status(e.message);}$('importPlan').value='';};
  $('exportShots').onclick=guarded(()=>{halt();bridge.save(bridge.annotateTrack(EarthShots.bake(getPlan(),C)),'camera-export','shot-camera.json');bridge.status('方案已导出：位置、朝向、横滚、镜头曲线可在Blender继续修改。');});
  function stopRecord(){recording=false;$('record').textContent='重新录制机位';$('export').disabled=!samples.length;}
  $('record').onclick=()=>{if(recording){stopRecord();return;}halt();recording=true;recordStart=performance.now();lastCapture=recordStart;samples=[pose(0)];$('record').textContent='停止录制';$('export').disabled=true;};
  $('export').onclick=()=>bridge.save({schema:'earthstudio.camera.v1',earthModel:'WGS84',coordinates:'ECEF_METERS',fps:30,samples},'camera-export','camera.json');
  function tick(now) {
    if(playing) {try {const time=Math.min((now-replayStart)/1000,EarthShots.duration(getPlan()));seek(time);if(time>=EarthShots.duration(getPlan()))halt();} catch(e){halt();bridge.status(e.message);}}
    if(recording && now-lastCapture>=1000/30) {
      if(samples.length>=EarthShots.MAX_SAMPLES){stopRecord();bridge.status('已达到100万个采样点的内存保护阈值，请导出并分段录制。');}
      else {samples.push(pose(Math.max(0,(now-recordStart)/1000)));lastCapture=now;$('recordState').textContent=`已录制 ${((now-recordStart)/1000).toFixed(1)}秒 · ${samples.length}个采样 · 点击停止后导出。`;}
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
  return {stop:()=>{halt();stopRecord();}};
}
