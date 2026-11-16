/* Explicit per-output-frame provenance; repeated observations are not new data. */
(function(root){
 function resolve(frames,utc,hold=false){
  const stamp=Date.parse(utc);if(!Number.isFinite(stamp))throw Error('无效映射UTC');
  let lo=0,hi=frames.length;while(lo<hi){const mid=(lo+hi)>>1;if(Date.parse(frames[mid].utc)<=stamp)lo=mid+1;else hi=mid;}
  const index=lo-1,node=frames[index];let displayed=index;
  if(hold)while(displayed>=0&&frames[displayed].missing)displayed--;
  const actual=frames[displayed];
  return {requestedUtc:utc,scanIndex:index,nodeUtc:node?.utc??null,state:!node?'outside-range':node.missing?'missing':'observed',
   actualUtc:actual&&!actual.missing?actual.utc:null,displayIndex:actual&&!actual.missing?displayed:-1,
   held:!!node?.missing&&displayed>=0,texture:actual&&!actual.missing?(actual.previewPath??actual.path??null):null};
 }
 function receipt(project,frames,T,M,hold=false){const rows=M.layout(project,T),count=rows.at(-1)?.endFrame??0;
  if(count>1000000)throw Error('逐帧映射超过100万帧，请分段');
  const output=[];for(let frame=0;frame<count;frame++){const clip=M.locate(project,frame,T),sourceSeconds=clip.sourceFrame/project.fps;
   output.push({frame,shot:clip.id,sourceFrame:clip.sourceFrame,...resolve(frames,T.weatherTime(project,sourceSeconds,clip.id),hold)});}
  return {schema:'earthstudio.frame_mapping.v1',fps:project.fps,frames:output};
 }
 const api={resolve,receipt};if(typeof module!=='undefined')module.exports=api;root.EarthFrameMapping=api;
})(globalThis);
