/* Missing actual UTC is never replaced, including during labeled display holds. */
(function(root){
 function indexAt(frames,utc){
  const t=Date.parse(utc);if(!Number.isFinite(t))return -1;
  let index=-1;for(let i=0;i<frames.length;i++){if(Date.parse(frames[i].utc)<=t)index=i;else break;}
  return index;
 }
 function annotate(frames,sample){
  const requested=sample.timelineUtc??sample.utc,index=indexAt(frames,requested),frame=frames[index];
  return {...sample,utc:frame&&!frame.missing?frame.utc:null,
   observationState:frame?(frame.missing?'missing':'observed'):'outside-range',
   requestedObservationUtc:frame?.utc??null};
 }
 function waitVisible(viewer,isCurrent,timeoutMs=45000){
  return new Promise(resolve=>{
   let finished=false,remove;
   const finish=ok=>{if(finished)return;finished=true;clearTimeout(timer);remove?.();resolve(ok);};
   const timer=setTimeout(()=>finish(false),timeoutMs);
   remove=viewer.scene.postRender.addEventListener(()=>{
    if(!isCurrent())finish(false);else if(viewer.scene.globe.tilesLoaded)finish(true);
   });
   viewer.scene.requestRender();
  });
 }
 const api={indexAt,annotate,waitVisible};if(typeof module!=='undefined')module.exports=api;root.EarthWeatherClock=api;
})(globalThis);
