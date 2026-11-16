'use strict';
const $ = id => document.getElementById(id);
window.addEventListener('error', e => { document.getElementById('status').textContent = String(e.message); });
window.addEventListener('unhandledrejection', e => { document.getElementById('status').textContent = String(e.reason); });
Cesium.buildModuleUrl.setBaseUrl(new URL('vendor/', location.href).href);
const viewer = new Cesium.Viewer('earth', {
  creditContainer: document.getElementById('cesiumCredits'), creditViewport: document.body,
  baseLayer: Cesium.ImageryLayer.fromProviderAsync(Cesium.SingleTileImageryProvider.fromUrl('no-observation.png')), baseLayerPicker: false, geocoder: false,
  terrainProvider: new Cesium.EllipsoidTerrainProvider(),
  animation: false, timeline: false, sceneModePicker: false,
  navigationHelpButton: false, skyAtmosphere: false, skyBox: false,
  requestRenderMode: true, maximumRenderTimeChange: Infinity
});
viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#44494e');
viewer.scene.globe.showGroundAtmosphere = false;
viewer.scene.globe.enableLighting = false;
viewer.scene.globe.maximumScreenSpaceError = 4;
viewer.scene.renderError.addEventListener((scene, error) => status('地球绘制失败：' + error.message));
viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#080d16');
viewer.camera.setView({destination: Cesium.Cartesian3.fromDegrees(130, 15, 18000000)});
const softRim=EarthSoftRim.create(viewer,Cesium);
let manifest, base, layer, current, generation = 0, weatherPlaying = false, weatherTimer, wantedIndex = -1;
let frameFallback=false;
let weatherVideo=null, videoMode=false, videoState='loading', renderTimes=[], videoIndices=new Set(), cameraDuration=20;
viewer.scene.postRender.addEventListener(()=>{
  const now=performance.now();renderTimes.push(now);while(renderTimes.length&&renderTimes[0]<now-1000)renderTimes.shift();
  if(weatherVideo&&videoMode){const m=weatherVideo.metrics(),label={preparing:'首次准备',ready:'就绪',paused:'已暂停',playing:'播放中',ended:'已结束',buffering:'缓冲中'}[videoState]??videoState;$('playbackMetrics').textContent=`连续纹理 · ${label} · 本次已显示${videoIndices.size}个时次（全段${manifest.frames.length}） · 渲染${renderTimes.length}帧/秒 · 解码丢帧${m.droppedFrames} · 视频${m.mediaTime.toFixed(3)}秒`;}
});
function videoFrame(value){
  if(!videoMode)return;
  const {index,frame,observation}=value;current=frame;wantedIndex=index;videoIndices.add(index);
  $('scan').value=index;$('weatherScrub').value=index;
  const label=(frame.label??frame.utc).replace(/ · 缺档$/,'');
  $('weatherLabel').textContent=frame.missing?`${label} 缺档；保持 ${observation?.label??observation?.utc} 的实测画面`:label;
  $('weatherState').textContent=frame.missing?'缺档节点：仅显示保持，不标为新观测；导出会保留缺测记录。':'连续云图 · 同一球面纹理更新；原生素材用于 Blender 最终渲染。';
  viewer.clock.currentTime=Cesium.JulianDate.fromIso8601(frame.utc);
  $('source').textContent=`${frame.source} · ${frame.recipe} · ${manifest.videoPreview.width}×${manifest.videoPreview.height}显示预览；${manifest.nativeShape?.join('×')??'原生'}最终素材独立保留。`;
  status(frame.missing?`${frame.utc} 缺档 · 保持前一实测帧（明确标注）`:`${frame.utc} · 连续云图 ${index+1}/${manifest.frames.length}`);
}
function videoStateChanged(state){videoState=state;if(state==='preparing')status('首次准备整段连续云图；完成后播放期间无需逐幅读取原生素材');if(state==='ended'&&weatherPlaying)stopWeather();}
const previewProviders=new Map();
function previewProvider(frame){
  const url=new URL(frame.previewPath,base).href;
  if(previewProviders.has(url)){const value=previewProviders.get(url);previewProviders.delete(url);previewProviders.set(url,value);return value;}
  const value=Cesium.SingleTileImageryProvider.fromUrl(url,{rectangle:Cesium.Rectangle.fromDegrees(...frame.previewBounds),credit:frame.source});
  previewProviders.set(url,value);value.catch(()=>previewProviders.delete(url));
  while(previewProviders.size>5)previewProviders.delete(previewProviders.keys().next().value);
  return value;
}
function status(text) { $('status').textContent = text; }
viewer.scene.globe.tileLoadProgressEvent.addEventListener(pending=>{
  if(videoMode)return;
  if(!current||current.missing)return;
  status(pending?`${current.utc} · 当前视口载入中（${pending}项）`:`${current.utc} · 当前视口影像已加载；其他区域按需读取`);
});
function post(message) { if (window.chrome?.webview) window.chrome.webview.postMessage(message); }
async function loadManifest(url) {
  bridge.pauseCamera?.();
  const resolved = new URL(url, location.href);
  if (![location.origin, 'https://materials.local'].includes(resolved.origin)) throw new Error('仅加载本地映射素材');
  const response = await fetch(resolved);
  if (!response.ok) throw new Error('素材索引不存在或读取失败');
  const next = EarthContract.validateManifest(await response.json());
  stopWeather();weatherVideo?.destroy();weatherVideo=null;videoMode=false;manifest = next; base = new URL('.', resolved); wantedIndex = -1;videoIndices.clear();
  if(manifest.videoPreview)weatherVideo=EarthWeatherVideo.create(viewer,Cesium,manifest,base,videoFrame,videoStateChanged);
  document.querySelector('#previewQuality option[value="fine"]').textContent=manifest.layeredSequence?'暂停显示帧 · 2048宽预览（正式素材11K）':'精细预览 · 原生瓦片按需读取';
  bridge.bindWeatherRange?.({startUtc:manifest.frames[0].utc,endUtc:manifest.frames.at(-1).utc});
  $('weatherPlay').disabled = manifest.frames.length < 2;
  $('weatherFps').disabled=manifest.frames.length<2;
  const observed=manifest.frames.filter(f=>!f.missing).length,gaps=manifest.frames.length-observed;
  $('weatherState').textContent = manifest.frames.length > 1 ? `${observed}幅真实观测${gaps?'，'+gaps+'个缺档节点明确标注':''}；连续视频纹理播放。` : '只有1幅真实观测：天气静止，可单独规划相机。';

  $('scan').replaceChildren(...manifest.frames.map((f,i) => new Option(f.label??f.utc, i)));
  $('scan').disabled = false;
  $('weatherScrub').max=manifest.frames.length-1;$('weatherScrub').disabled=false;
  const [w,s,e,n]=manifest.frames[0].bounds; bridge.setTarget(w<=e?(w+e)/2:((w+e+360)/2+180)%360-180,(s+n)/2);
  // Restore camera/playhead before the first asynchronous decode. A delayed
  // initial load must never overwrite a scan or pose the user just selected.
  const restoredIndex=EarthWeatherClock.indexAt(manifest.frames,bridge.previewWeatherTime?.());
  await showFrame(Math.max(0,restoredIndex));
}
async function showFrame(index) {
  const ticket = ++generation; wantedIndex = index; $('scan').value = index;
  $('weatherScrub').value=index;
  if(weatherVideo&&!frameFallback&&$('previewQuality').value==='fast'){
    videoMode=true;
    try{await weatherVideo.seek(index);if(ticket!==generation)return;weatherVideo.brightness(Number($('brightness').value));while(viewer.imageryLayers.length>1)viewer.imageryLayers.remove(viewer.imageryLayers.get(1));layer=null;}
    catch(error){if(ticket===generation)status('连续云图读取失败：'+error.message);}
    return;
  }
  const hadVideo=videoMode;
  if(hadVideo)weatherVideo.pause();
  // Keep the displayed observation while a new provider prepares. Its label is
  // changed only when that provider is actually shown.
  const frame = manifest.frames[index];
  $('weatherLabel').textContent=(frame.label??frame.utc)+(frame.missing?' · 缺少观测，灰色显示':'');
  $('weatherState').textContent='已选择 '+(frame.label??frame.utc)+(frame.missing?' · 缺档':' · 正在准备画面');
  if(frame.missing){
    if(hadVideo){weatherVideo.detach();videoMode=false;}
    while(viewer.imageryLayers.length>1)viewer.imageryLayers.remove(viewer.imageryLayers.get(1));layer=null;
    current=frame;viewer.clock.currentTime=Cesium.JulianDate.fromIso8601(frame.utc);
    $('source').textContent='该时次缺少真实观测；未复制相邻天气，灰色为缺测。';
    status('缺档 '+(frame.label??frame.utc)+'；无天气图像');viewer.scene.requestRender();return;
  }
  status('正在读取观测 ' + frame.utc);
  const rectangle = Cesium.Rectangle.fromDegrees(...frame.bounds);
  const url = new URL(frame.path.replaceAll('{','ESOPEN').replaceAll('}','ESCLOSE'), base).href.replaceAll('ESOPEN','{').replaceAll('ESCLOSE','}');
  let provider;
  const lightweight=$('previewQuality').value==='fast'&&!!frame.previewPath;
  try {
    provider = lightweight?await previewProvider(frame):frame.kind === 'single-image'
      ? await Cesium.SingleTileImageryProvider.fromUrl(url, {rectangle, credit:frame.source})
      : new Cesium.UrlTemplateImageryProvider({url, rectangle, tilingScheme:new Cesium.GeographicTilingScheme(), maximumLevel:$('previewQuality').value==='fast'?Math.min(2,frame.maximumLevel):frame.maximumLevel, tileWidth:frame.tileSize??256,tileHeight:frame.tileSize??256,credit:frame.source, enablePickFeatures:false});
    if(!lightweight&&frame.kind==='geographic-tiles'&&frame.bounds[0]===-180&&frame.bounds[2]===180){
      status('正在准备 '+(frame.label??frame.utc)+' 的基础画面；首次读取原生素材需要等待');
      // Prepare the two root tiles before detailed requests can occupy the read queue.
      await Promise.all([provider.requestImage(0,0,0),provider.requestImage(1,0,0)]);
    }
  } catch (error) { if (ticket === generation) status('观测读取失败：' + error.message); return; }
  if (ticket !== generation) return;
  const previousLayer=layer;
  layer = viewer.imageryLayers.addImageryProvider(provider); layer.brightness = Number($('brightness').value);
  if(previousLayer){const remove=viewer.scene.postRender.addEventListener(()=>{if(ticket!==generation||viewer.scene.globe.tilesLoaded){remove();if(viewer.imageryLayers.contains(previousLayer))viewer.imageryLayers.remove(previousLayer);}});}
  if(hadVideo){const remove=viewer.scene.postRender.addEventListener(()=>{if(ticket!==generation){remove();return;}if(viewer.scene.globe.tilesLoaded){remove();weatherVideo.detach();videoMode=false;status(frame.utc+' · 原生视口已加载');viewer.scene.requestRender();}});}
  current = frame;
  if(lightweight)for(const neighbor of [index+1,index-1]){const f=manifest.frames[neighbor];if(f&&!f.missing&&f.previewPath)previewProvider(f).catch(()=>{});}
  $('weatherState').textContent='当前天气 '+(frame.label??frame.utc)+'；'+($('previewQuality').value==='fast'?'流畅预览，最终原生素材未降采样':'精细预览，细节按需读取');
  provider.errorEvent.addEventListener(() => { if (current === frame) status('当前观测存在读取失败或缺失瓦片；灰色区域无可显示数据'); });
  viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(frame.utc);
  $('source').textContent = `${frame.source} · ${frame.recipe} · ${frame.detail === 'bounded-sample' ? '有界小样，不能证明原生交付' : '原生产品声明，完整性仍需验收'} · 范围 ${frame.bounds.join(', ')}`;
  $('source').textContent += frame.limits ? ' · '+frame.limits : '';
  status('已选择 ' + frame.utc + '；影像按视口加载，未作完整性验收'); viewer.scene.requestRender();
}
$('load').onclick = () => loadManifest($('manifest').value).catch(e => status(e.message));
$('demo').onchange = () => { $('manifest').value='/data/'+$('demo').value; loadManifest($('manifest').value).catch(e=>status(e.message)); };
if(window.chrome?.webview) $('sampleChoice').hidden=true;
$('overview').onclick = () => {
  if(bridge.regionOverview){bridge.regionOverview();return;}
  if (!current) return;
  const [w,s,e,n] = current.bounds;
  const longitude = w <= e ? (w+e)/2 : ((w+e+360)/2+180)%360-180;
  viewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(longitude,(s+n)/2,18000000)});
  viewer.scene.requestRender();
};
$('scan').onchange = () => { const index=Number($('scan').value);bridge.pauseCamera?.();stopWeather();bridge.seekWeather?.(manifest.frames[index].utc);if(wantedIndex!==index)showFrame(index); };
let weatherScrubTimer;
$('weatherScrub').oninput=()=>{
  const index=Number($('weatherScrub').value);
  bridge.pauseCamera?.();stopWeather();clearTimeout(weatherScrubTimer);
  $('weatherScrub').value=index;$('weatherLabel').textContent='准备 '+(manifest.frames[index].label??manifest.frames[index].utc)+'；载入前保留当前实测画面';
  weatherScrubTimer=setTimeout(()=>{ $('scan').value=index;$('scan').onchange(); },180);
};
$('weatherScrub').ondblclick=()=>{$('weatherScrub').value=0;$('weatherScrub').oninput();};
$('previewQuality').onchange=()=>{bridge.pauseCamera?.();stopWeather();viewer.scene.globe.maximumScreenSpaceError=$('previewQuality').value==='fast'?4:1;if(manifest)showFrame(Number($('scan').value));};
$('retryWeather').onclick=()=>{bridge.pauseCamera?.();stopWeather();if(manifest)showFrame(Number($('scan').value));};
$('brightness').ondblclick=()=>{ $('brightness').value=1; $('brightness').oninput(); };
$('brightness').oninput = () => { bridge.pauseCamera?.();$('brightnessNumber').value=$('brightness').value; if(bridge.editBrightness){bridge.editBrightness(Number($('brightness').value));return;} if (layer) layer.brightness = Number($('brightness').value); viewer.scene.requestRender(); };

let brightnessInputTimer;
function readBrightness(){
 clearTimeout(brightnessInputTimer);
 const field=$('brightnessNumber'),value=Number(field.value);
 if(!field.value.trim()||!field.checkValidity()){field.setAttribute('aria-invalid','true');status('亮度应为0.2～2之间的数字');return;}
 field.removeAttribute('aria-invalid');$('brightness').value=value;$('brightness').oninput();
}
$('brightnessNumber').onchange=readBrightness;
$('brightnessNumber').oninput=()=>{bridge.pauseCamera?.();clearTimeout(brightnessInputTimer);brightnessInputTimer=setTimeout(readBrightness,200);};

function stopWeather() { weatherPlaying=false; clearTimeout(weatherTimer);weatherVideo?.pause(); $('weatherPlay').textContent='播放云图（相机固定）'; }
async function weatherStep() {
  if(!weatherPlaying || !manifest) return;
  const index=Number($('scan').value);
  if(index>=manifest.frames.length-1) { stopWeather(); $('weatherState').textContent='已播放到最后一幅真实观测。'; return; }
  const next=index+1,previous=manifest.frames.slice(0,next).findLast(f=>!f.missing);
  const gap=previous?(Date.parse(manifest.frames[next].utc)-Date.parse(previous.utc))/60000:0;
  await showFrame(next);
  if(!weatherPlaying||wantedIndex!==next)return;
  bridge.seekWeather?.(manifest.frames[next].utc);
  if(!manifest.frames[next].missing){
    const ticket=generation;
    const ready=await EarthWeatherClock.waitVisible(viewer,()=>weatherPlaying&&ticket===generation);
    if(!ready&&weatherPlaying){stopWeather();$('weatherState').textContent='当前视口仍有未完成的读取，已暂停自动推进；可等待后重试或拉远视角。';return;}
  }
  $('weatherState').textContent=manifest.frames[next].missing?`当前 ${manifest.frames[next].utc} 缺档，显示灰色；未替代观测。`:`实际观测间隔 ${gap.toFixed(1)}分钟；当前 ${manifest.frames[next].utc}。缺档未补帧。`;
  if(weatherPlaying) weatherTimer=setTimeout(weatherStep,1000/Math.max(.001,Number($('weatherFps').value)||1));
}
$('weatherPlay').onclick=async()=>{
  if(weatherPlaying){stopWeather();return;}
  bridge.pauseCamera?.();
  if(!manifest || manifest.frames.length<2)return;
  if(weatherVideo){
    try{if($('previewQuality').value!=='fast'){$('previewQuality').value='fast';}videoMode=true;
      const start=Number($('scan').value)>=manifest.frames.length-1?0:Number($('scan').value);
      weatherPlaying=true;$('weatherPlay').textContent='暂停云图';
      videoIndices.clear();
      const duration=(manifest.frames.length-1)/(bridge.projectFrameRate?.()??30);await weatherVideo.play(duration,start/(manifest.frames.length-1)*duration,'weather');
    }catch(error){stopWeather();status(error.message);}return;
  }
  if(Number($('scan').value)===manifest.frames.length-1) {showFrame(0).then(()=>{weatherPlaying=true;$('weatherPlay').textContent='暂停天气';weatherTimer=setTimeout(weatherStep,1000);});}
  else {weatherPlaying=true;$('weatherPlay').textContent='暂停天气';weatherTimer=setTimeout(weatherStep,1000);}
};
function save(data,type,name) {
  if(window.chrome?.webview) post({type,data});
  else { const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000); }
}
const bridge={
  persistEditor:data=>{if(window.chrome?.webview)post({type:'editor-autosave',data});},
  weatherIntervalSeconds:()=>manifest?.frames.length>1?(Date.parse(manifest.frames.at(-1).utc)-Date.parse(manifest.frames[0].utc))/1000/(manifest.frames.length-1):600,
  durationChanged:(seconds,force=false)=>{cameraDuration=seconds;const fps=bridge.projectFrameRate?.()??30;if(force||document.activeElement!==$('weatherFps'))$('weatherFps').value=fps;$('weatherRateHint').textContent=`项目源图播放${fps}fps；修改分镜秒数不会改变源图速度。`;},
  preparePlayback:async(seconds,time)=>{frameFallback=false;cameraDuration=seconds;if(weatherVideo){$('previewQuality').value='fast';videoMode=true;videoIndices.clear();const range=bridge.shotWeatherRange?.(),first=Date.parse(manifest.frames[0].utc),span=Date.parse(manifest.frames.at(-1).utc)-first;const mapping=range&&span>0?{start:(Date.parse(range.startUtc)-first)/span,end:(Date.parse(range.endUtc)-first)/span,curve:range.curve,weatherSeconds:range.observationFps!==undefined?(Date.parse(range.endUtc)-Date.parse(range.startUtc))/1000/range.intervalSeconds/range.observationFps:undefined}:null;await weatherVideo.play(seconds,time,'camera',mapping);while(viewer.imageryLayers.length>1)viewer.imageryLayers.remove(viewer.imageryLayers.get(1));layer=null;}},
  playbackTime:seconds=>videoMode&&weatherVideo?.active()&&weatherVideo.mode()==='camera'?weatherVideo.movieTime(seconds):null,
  playbackFinished:()=>!videoMode||!weatherVideo||weatherVideo.finished(),
  fallbackPlayback:()=>{weatherVideo?.detach();frameFallback=true;videoMode=false;videoState="paused";wantedIndex=-1;},
  playbackBuffered:()=>videoMode&&videoState==='buffering',
  pausePlayback:stopWeather,
  weatherReady:()=>videoMode||!manifest||!!current&&(current.missing||viewer.scene.globe.tilesLoaded),
  effects:()=>softRim.get(),setEffects:value=>softRim.set(value),
  utc:()=>current?.utc??null,
  actualWeatherUtc:()=>manifest&&current?EarthFrameMapping.resolve(manifest.frames,current.utc,!!manifest.videoPreview).actualUtc:null,
  defaultView:()=>manifest?.defaultView??{targetLon:130,targetLat:20},
  bounds:()=>current?.bounds??manifest?.frames[0]?.bounds??null,
  mappingFrames:()=>manifest?.frames??[],
  mappingHold:()=>!!manifest?.videoPreview,
  weatherRange:()=>manifest?{startUtc:manifest.frames[0].utc,endUtc:manifest.frames.at(-1).utc}:null,
  brightness:()=>layer?.brightness??Number($('brightness').value),status,save,stopWeather,
  annotateTrack(track) {
    if(!manifest) return track;
    track.effects=softRim.get();track.materialManifest=manifest;
    if(manifest.videoPreview)track.weatherPlayback={gapPolicy:'hold-last-labeled',displayOnlyVideo:true};
    for(const sample of track.samples) {
      Object.assign(sample,EarthWeatherClock.annotate(manifest.frames,sample));
      if(manifest.videoPreview){const index=EarthWeatherClock.indexAt(manifest.frames,sample.timelineUtc??sample.utc);sample.displayedObservationUtc=index>=0?EarthWeatherVideo.displayed(manifest.frames,index).observation?.utc??null:null;}
    }
    return track;
  },
  setWeather(utc,brightness=1) {
    $('brightness').value=brightness;$('brightnessNumber').value=brightness;if(layer)layer.brightness=brightness;
    weatherVideo?.brightness(brightness);
    if(!manifest || !utc)return;
    if(weatherVideo?.active())return;
    const index=EarthWeatherClock.indexAt(manifest.frames,utc);
    if(index<0) { if(wantedIndex!==-1){++generation;while(viewer.imageryLayers.length>1)viewer.imageryLayers.remove(viewer.imageryLayers.get(1));current=null;layer=null;wantedIndex=-1;} $('weatherState').textContent='镜头时钟早于已载入观测，无可显示天气';return; }
    if(index!==wantedIndex)showFrame(index);
    if(weatherVideo&&$('previewQuality').value==='fast')return;
    $('weatherState').textContent=manifest.frames[index].missing?`镜头时钟 ${utc} · 当前节点缺档，未替代观测`:(manifest.frames.length===1?'单时次：天气静止，相机仍可播放。 ':'')+`镜头时钟 ${utc} · 显示实际扫描 ${manifest.frames[index].utc}（保持帧，不代表新的观测）`;
  }
};
setupTimelineEditor(viewer,bridge);
$('weatherFps').onchange=()=>bridge.setProjectFrameRate(Number($('weatherFps').value));
$('weatherFps').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('weatherFps').onchange();}};
window.chrome?.webview?.addEventListener('message', event => {
  if (event.data.manifestUrl) { $('manifest').value = event.data.manifestUrl; loadManifest(event.data.manifestUrl).catch(e => status(e.message)); }
});
status('Cesium 已就绪 · 本地几何 · 等待真实素材索引'); post({type:'ready'});
if(!window.chrome?.webview){
  const requested=new URLSearchParams(location.search).get('manifest');
  if(requested){$('manifest').value=requested;$('sampleChoice').hidden=true;}
  loadManifest($('manifest').value).catch(e=>status(e.message));
}
