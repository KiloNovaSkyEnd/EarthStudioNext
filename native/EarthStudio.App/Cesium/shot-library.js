/* Asset revisions ignore names, music and editor-only state. Tasks are immutable snapshots, not rendered outputs. */
(function(root){
 const copy=x=>JSON.parse(JSON.stringify(x));
 function content(p,t,T){return {fps:p.fps,output:p.output,effects:p.effects,sourcePlayback:p.sourcePlayback,duration:T.duration(p,t.id),keys:t.keys,curve:t.curve,easing:t.easing,weather:t.weather??p.weather};}
 function migrate(project){for(const t of project.tracks){t.asset??={revision:1,createdUtc:new Date().toISOString()};t.asset.id??=root.EarthMusic.id();}return project;}
 function revise(before,after,T){migrate(after);for(const t of after.tracks){const old=before.tracks.find(x=>x.id===t.id);if(old&&JSON.stringify(content(before,old,T))!==JSON.stringify(content(after,t,T))){t.asset.revision=Math.max(old.asset?.revision??1,t.asset.revision??1)+1;t.asset.modifiedUtc=new Date().toISOString();}}return after;}
 function tasks(project,T,frames=[]){
  if(project.tracks.some(t=>!t.keys.length))throw Error('请先为每个镜头添加关键帧');
  return {schema:'earthstudio.render_plan.v1',createdUtc:new Date().toISOString(),status:'planned',audioPolicy:'silent',
   tasks:project.tracks.map(t=>({taskId:'task_'+root.EarthMusic.id(),shotId:t.asset?.id??t.id,editorTrackId:t.id,shotRevision:t.asset?.revision??1,name:t.name,status:'planned',
    frameCount:Math.round(T.duration(project,t.id)*project.fps),fps:project.fps,duration:T.duration(project,t.id),output:copy(project.output),
    outputStem:(t.asset?.id??t.id).replace(/[^a-zA-Z0-9_-]/g,'_')+'_r'+(t.asset?.revision??1),
    snapshot:{schema:project.schema,earthModel:project.earthModel,fps:project.fps,duration:T.duration(project,t.id),output:copy(project.output),effects:copy(project.effects??{}),weather:copy(project.weather),...(project.sourcePlayback?{sourcePlayback:copy(project.sourcePlayback)}:{}),activeTrack:t.id,tracks:[copy(t)]},
    observations:frames.map(f=>({utc:f.utc,missing:!!f.missing,path:f.path??f.previewPath??null}))}))};
 }
 const api={content,migrate,revise,tasks};if(typeof module!=='undefined')module.exports=api;root.EarthShotLibrary=api;
})(globalThis);
