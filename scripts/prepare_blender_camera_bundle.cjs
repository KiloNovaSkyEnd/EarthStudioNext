/* Saved timeline -> importer payload, using the exact same Cesium evaluator.
   Usage: node scripts/prepare_blender_camera_bundle.cjs project.json bundle.json
   Does not convert an unsaved editor draft into a keyframe. */
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const staged=path.join(root,'reports/utc_workspace_m17/native/EarthStudio.App/Cesium');
const ui=fs.existsSync(staged)?staged:path.join(root,'native/EarthStudio.App/Cesium');
const C=Function(fs.readFileSync(path.join(ui,'vendor/Cesium.js'),'utf8')+';return Cesium;')();
const T=require(path.join(ui,'timeline.js')),S=require(path.join(ui,'shots.js'));
function prepare(project){
 T.validate(project,S);
 const tracks=project.tracks.filter(t=>t.keys.length).map(t=>T.bake(project,t.id,C,S));
 if(!tracks.length)throw new Error('工程中没有可导出的关键帧');
 for(const t of tracks){
  t.effects=structuredClone(project.effects??{blueAtmosphere:true,nightAirglow:true});
  // Only a frozen UTC can be resolved without the actual material manifest.
  if(project.weather && project.weather.startUtc===project.weather.endUtc)
   for(const sample of t.samples)sample.utc=project.weather.startUtc;
 }
 return {schema:'earthstudio.camera_bundle.v1',timelineProject:structuredClone(project),tracks};
}
module.exports={prepare};
if(require.main===module){
 if(process.argv.length!==4)throw new Error('Expected saved timeline JSON and output bundle JSON');
 const target=path.resolve(process.argv[3]);
 const relative=path.relative(root,target);
 if(relative.startsWith('..')||path.isAbsolute(relative))throw new Error('Output must stay within Next workspace');
 const result=prepare(JSON.parse(fs.readFileSync(process.argv[2],'utf8')));
 fs.writeFileSync(target,JSON.stringify(result));
 console.log(`Prepared ${result.tracks.length} independent camera tracks. Weather materials are not included.`);
}
