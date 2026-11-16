/* Persistent globe material: buffered video in motion, decoded still on pause. */
(function(root){
 const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
 function fpsForDuration(count,seconds){if(count<2||!Number.isFinite(seconds)||seconds<=0)throw new Error('天气区间或时长无效');return (count-1)/seconds;}
 function durationForFps(count,fps){if(!Number.isFinite(fps)||fps<.000001||fps>120)throw new Error('云图速度须为0.000001至120观测帧/秒');return (count-1)/fps;}
 function displayed(frames,index){let i=index;while(i>=0&&frames[i].missing)i--;return {index,frame:frames[index],observation:i>=0?frames[i]:null};}
 function mediaBounds(info,mapping){return [(mapping?.start??0)*info.lastFrameTime,(mapping?.end??1)*info.lastFrameTime];}
 function create(viewer,C,manifest,base,onFrame,onState){
  const info=manifest.videoPreview,video=document.createElement('video'),stills=new Map(),retired=new Set();
  video.muted=true;video.playsInline=true;video.preload='auto';
  let ready,disposed=false,material=null,mode=null,last=-1,url=null,frames=0,playEpoch=0,stillEpoch=0,stepped=false,clockStart=0,clockOffset=0,clockDuration=0,stepIndex=-1,segmentStart=0,segmentEnd=info.lastFrameTime,shotOffset=0,mappingCurve=null,weatherSeconds=null;
  const waitEvent=(name,operation)=>new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>finish(new Error('连续云图准备超时，请重新加载天气')),30000);
   const ok=()=>finish(),bad=()=>finish(new Error('浏览器无法解码云图视频'));
   function finish(error){clearTimeout(timer);video.removeEventListener(name,ok);video.removeEventListener('error',bad);error?reject(error):resolve();}
   video.addEventListener(name,ok,{once:true});video.addEventListener('error',bad,{once:true});operation?.();
  });
  function notify(index,mediaTime,force=false){
   if(force||index!==last){last=index;onFrame({...displayed(manifest.frames,index),mediaTime,presentedFrames:frames,mode});}
   viewer.scene.requestRender();
  }
  function attach(){
   if(!material)material=new C.Material({translucent:false,fabric:{type:'EarthWeatherVideo',uniforms:{image:C.Material.DefaultImageId,brightness:1.0},source:`
    czm_material czm_getMaterial(czm_materialInput inputValue){
     czm_material m=czm_getDefaultMaterial(inputValue);
     vec3 p=(czm_inverseView*vec4(-inputValue.positionToEyeEC,1.0)).xyz;
     vec3 n=normalize(p*vec3(1.0,1.0,1.0067394967422765));
     vec2 uv=vec2(atan(n.y,n.x)/6.283185307179586+0.5,atan(n.z,length(n.xy))/3.141592653589793+0.5);
     vec4 pixel=texture(image,uv);
     m.diffuse=mix(vec3(0.2666666667,0.2862745098,0.3058823529),pixel.rgb,pixel.a)*brightness;
     m.alpha=1.0;return m;
    }`}});
   viewer.scene.globe.material=material;
  }
  function frameCallback(now,metadata){
   if(disposed)return;frames++;
   if(mode&&!stepped){attach();material.uniforms.image=video;notify(clamp(Math.floor(metadata.mediaTime*info.fps+1e-4),0,manifest.frames.length-1),metadata.mediaTime);}
   video.requestVideoFrameCallback?.(frameCallback);
  }
  if(video.requestVideoFrameCallback)video.requestVideoFrameCallback(frameCallback);
  else video.addEventListener('timeupdate',()=>{if(mode&&!stepped){attach();material.uniforms.image=video;notify(clamp(Math.floor(video.currentTime*info.fps),0,manifest.frames.length-1),video.currentTime);}});
  video.addEventListener('ended',()=>{if(mode&&weatherSeconds===null){onState('ended');showStill(manifest.frames.length-1,true).catch(()=>{});}});
  video.addEventListener('waiting',()=>{if(mode)onState('buffering');});
  async function prepare(){
   if(!ready)ready=(async()=>{
    onState('preparing');
    const response=await fetch(new URL(info.path,base));if(!response.ok)throw new Error('连续云图文件读取失败');
    const blob=await response.blob();if(blob.size!==info.bytes)throw new Error('连续云图文件不完整');
    url=URL.createObjectURL(blob);
    await waitEvent('loadeddata',()=>{video.src=url;video.load();});onState('ready');
   })().catch(error=>{ready=null;if(url){URL.revokeObjectURL(url);url=null;}throw error;});
   await ready;
  }
  function bitmap(frame){
   const path=new URL(frame.previewPath,base).href;
   if(stills.has(path)){const value=stills.get(path);stills.delete(path);stills.set(path,value);return value;}
   // WebGL UNPACK_FLIP_Y does not apply to ImageBitmap. Match Cesium's
   // HTML-video texture orientation explicitly at decode time.
   const value=fetch(path).then(r=>{if(!r.ok)throw new Error('观测显示图读取失败');return r.blob();}).then(blob=>createImageBitmap(blob,{imageOrientation:'flipY',premultiplyAlpha:'none',colorSpaceConversion:'none'}));
   stills.set(path,value);value.catch(()=>stills.delete(path));
   while(stills.size>3){const first=stills.keys().next().value,old=stills.get(first);stills.delete(first);old.then(b=>{retired.add(b);releaseRetired();}).catch(()=>{});}
   return value;
  }
  function releaseRetired(){setTimeout(()=>{for(const b of retired)if(disposed||material?.uniforms.image!==b){b.close();retired.delete(b);}},1000);}
  async function showStill(index,allowDuringPlayback=false){
   const ticket=++stillEpoch,node=displayed(manifest.frames,clamp(index,0,manifest.frames.length-1));
   const image=await bitmap(node.observation);if(disposed||ticket!==stillEpoch||(mode&&!stepped&&!allowDuringPlayback))return;
   attach();material.uniforms.image=image;releaseRetired();
   // Cesium queues bitmap uploads; schedule subsequent animation frames even
   // when the camera and decoder are paused.
   let budget=3;const draw=()=>{if(disposed)return;viewer.scene.requestRender();if(--budget)requestAnimationFrame(draw);};requestAnimationFrame(draw);
   notify(node.index,node.index/info.fps,true);
  }
  async function seek(index){
   // Immediate still display is independent of the initial full-video buffer.
   // Use the prepared still for precise paused selection, keeping exactly the
   // same world-space UV/material without waiting for the movie buffer.
   prepare().catch(()=>onState('error'));
   if(mode&&!stepped)return;
   await showStill(index);
  }
  function pause(){
   const wasActive=!!mode,index=last;playEpoch++;if(wasActive)stillEpoch++;mode=null;stepped=false;video.pause();viewer.scene.requestRenderMode=true;
   if(wasActive&&index>=0)showStill(index).catch(()=>{});
   onState('paused');viewer.scene.requestRender();
  }
  let bufferStarted=null,bufferElapsed=0;
  video.addEventListener('waiting',()=>{if(mode&&!stepped&&bufferStarted===null)bufferStarted=performance.now();});
  video.addEventListener('playing',()=>{if(bufferStarted!==null){bufferElapsed+=performance.now()-bufferStarted;bufferStarted=null;}});
  function localTime(){return clamp(shotOffset+((bufferStarted??performance.now())-clockStart-bufferElapsed)/1000,0,clockDuration);}
  function time(){const t=weatherSeconds!==null?(weatherSeconds>0?Math.min(1,localTime()/weatherSeconds):0):(clockDuration?localTime()/clockDuration:0);return stepped?segmentStart+(segmentEnd-segmentStart)*(mappingCurve?root.EarthTimeline.progress(mappingCurve,t):t):video.currentTime;}
  function step(epoch){
   if(disposed||!mode||epoch!==playEpoch)return;
   const index=clamp(Math.floor(time()*info.fps+1e-5),0,manifest.frames.length-1);
   if(index!==stepIndex){stepIndex=index;showStill(index).catch(error=>{pause();onState('error');});}
   if(time()>=info.lastFrameTime&&mode==='weather'){pause();onState('ended');showStill(manifest.frames.length-1).catch(()=>{});return;}
   requestAnimationFrame(()=>step(epoch));
  }
  function holdAtEnd(epoch){
   if(disposed||!mode||epoch!==playEpoch)return;
   if(video.currentTime>=segmentEnd-1e-5){video.pause();showStill(clamp(Math.floor(segmentEnd*info.fps+1e-4),0,manifest.frames.length-1),true).catch(()=>onState('error'));return;}
   requestAnimationFrame(()=>holdAtEnd(epoch));
  }
  async function play(seconds,startSeconds=0,kind='camera',mapping=null){
   pause();const epoch=playEpoch;await prepare();if(epoch!==playEpoch)return;
   bitmap(displayed(manifest.frames,manifest.frames.length-1).observation).catch(()=>{});
   [segmentStart,segmentEnd]=mediaBounds(info,mapping);mappingCurve=mapping?.curve??null;weatherSeconds=mapping?.weatherSeconds??null;shotOffset=startSeconds;clockDuration=seconds;
   const progress=weatherSeconds!==null?(weatherSeconds>0?Math.min(1,startSeconds/weatherSeconds):0):startSeconds/seconds,target=clamp(segmentStart+(segmentEnd-segmentStart)*(mappingCurve?root.EarthTimeline.progress(mappingCurve,progress):progress),0,info.lastFrameTime);
   if(Math.abs(video.currentTime-target)>.0001)await waitEvent('seeked',()=>{video.currentTime=target;});
   if(epoch!==playEpoch)return;
   await showStill(clamp(Math.floor(target*info.fps+1e-4),0,manifest.frames.length-1));if(epoch!==playEpoch)return;
   const rate=(segmentEnd-segmentStart)/(weatherSeconds??seconds);mode=kind;viewer.scene.requestRenderMode=false;clockStart=performance.now();bufferStarted=null;bufferElapsed=0;
   if(!Number.isFinite(rate)||mappingCurve||rate<.0625||rate>16){stepped=true;clockOffset=target;stepIndex=-1;requestAnimationFrame(()=>step(epoch));}
   else{video.playbackRate=rate;if(weatherSeconds!==null&&startSeconds>=weatherSeconds){stepped=true;stepIndex=-1;requestAnimationFrame(()=>step(epoch));}else{await video.play();if(weatherSeconds!==null)requestAnimationFrame(()=>holdAtEnd(epoch));}}
   if(epoch!==playEpoch){video.pause();return;}onState('playing');
  }
  return {prepare,seek,play,pause,active:()=>!!mode,mode:()=>mode,attach,
   finished:()=>stepped||weatherSeconds!==null?localTime()>=clockDuration:video.currentTime>=segmentEnd,
   brightness:value=>{if(material)material.uniforms.brightness=value;},
   movieTime:seconds=>stepped||weatherSeconds!==null?localTime():clamp((time()-segmentStart)/(segmentEnd-segmentStart)*seconds,0,seconds),
   metrics:()=>({presentedFrames:frames,droppedFrames:video.getVideoPlaybackQuality?.().droppedVideoFrames??0,mediaTime:mode?time():Math.max(0,last)/info.fps,readyState:video.readyState,mode,paused:video.paused}),
   detach:()=>{pause();viewer.scene.globe.material=undefined;},
   destroy:()=>{disposed=true;pause();video.removeAttribute('src');video.load();if(url)URL.revokeObjectURL(url);viewer.scene.globe.material=undefined;material?.destroy();for(const value of stills.values())value.then(b=>b.close()).catch(()=>{});stills.clear();for(const b of retired)b.close();retired.clear();}
  };
 }
 const api={create,fpsForDuration,durationForFps,displayed,mediaBounds};if(typeof module!=='undefined')module.exports=api;root.EarthWeatherVideo=api;
})(globalThis);
