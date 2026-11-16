/* Read-only current production metadata audit; never decode/rewrite native images. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const T=require('../native/EarthStudio.App/Cesium/timeline.js'),S=require('../native/EarthStudio.App/Cesium/shots.js'),M=require('../native/EarthStudio.App/Cesium/montage.js'),F=require('../native/EarthStudio.App/Cesium/frame-mapping.js');
const queue=process.argv[2];if(!queue)throw Error('Queue path required');
const state=JSON.parse(fs.readFileSync(path.join(queue,'state.json'))),done=[...state.completed].sort(),available=new Set(done);
const first=Date.parse(done[0]),last=Date.parse(done.at(-1)),frames=[];
for(let ms=first;ms<=last;ms+=600000){const utc=new Date(ms).toISOString().replace('.000Z','Z');frames.push({utc,missing:!available.has(utc)});}
const p=JSON.parse(fs.readFileSync('reports/m14_editing/mixed_bundle.json')).timelineProject;
p.weather={startUtc:frames[0].utc,endUtc:frames.at(-1).utc};
for(const t of p.tracks)t.weather={mode:'sequence',startUtc:frames[0].utc,endUtc:p.weather.endUtc};
p.tracks[2].weather.startUtc=frames[30].utc;
T.validate(p,S);const receipt=F.receipt(p,frames,T,M,true),indices=new Set(receipt.frames.filter(r=>r.actualUtc).map(r=>r.actualUtc));
let assets=0;
for(const utc of indices){const folder=path.join(queue,'steps',utc.replaceAll('-','').replaceAll(':','')),commit=JSON.parse(fs.readFileSync(path.join(folder,'commit.json')));
 assert.equal(commit.utc,utc);assert.deepEqual(commit.grid.shape,[11000,11000]);
 for(const entry of commit.assets){assert.equal(fs.statSync(path.join(folder,entry.path)).size,entry.bytes);assets++;}
}
const output={observedUtc:new Date().toISOString(),queuePhase:state.phase,completed:done.length,outputFrames:receipt.frames.length,uniqueScans:indices.size,assetStatChecks:assets,reusedTimeRange:true,differentTimeRange:true,missingOutputFrames:receipt.frames.filter(r=>r.state==='missing').length,readOnly:true,pixelDecode:false,continuousPlaybackAccepted:false};
fs.writeFileSync('reports/m14_editing/live_mapping.json',JSON.stringify(output,null,2));console.log(JSON.stringify(output));
