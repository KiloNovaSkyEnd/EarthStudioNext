const fs=require('node:fs'),assert=require('node:assert/strict');
const C=Function(fs.readFileSync('native/EarthStudio.App/Cesium/vendor/Cesium.js','utf8')+';return Cesium;')();
const {History}=require('../native/EarthStudio.App/Cesium/editor-history.js'),D=require('../native/EarthStudio.App/Cesium/globe-drag.js'),R=require('../native/EarthStudio.App/Cesium/soft-rim.js'),T=require('../native/EarthStudio.App/Cesium/timeline.js');
const h=new History(3),a={project:{keys:[1]},pose:{fov:40,roll:0}},b={project:{keys:[1]},pose:{fov:40,roll:20}},c={project:{keys:[1]},pose:{fov:40,roll:40}};
h.record(a,b,'gesture');h.record(b,c,'gesture');assert.equal(h.past.length,1);assert.deepEqual(h.undo(),a);assert.deepEqual(h.redo(),c);h.undo();h.record(a,b);assert.equal(h.redo(),null);b.pose.roll=99;assert.equal(h.undo().pose.roll,0);
const o={targetLon:130,targetLat:20,heading:32,pitch:-50,rangeKm:4500,roll:23,fov:40},p=T.orbitPose(o,{width:1920,height:1080},C);
const q=D.rotate(p,[400,300],[600,550],[800,600],C);assert.ok(Math.abs(Math.hypot(...q.position)-Math.hypot(...p.position))<1e-7);assert.notDeepEqual(q.position,p.position);
for(const v of [q.direction,q.up])assert.ok(Math.abs(Math.hypot(...v)-1)<1e-12);assert.ok(Math.abs(q.direction.reduce((s,x,i)=>s+x*q.up[i],0))<1e-12);
const recovered=D.orbit(q,C);assert.ok(recovered);const round=T.orbitPose(recovered,{width:1920,height:1080},C);for(const name of ['position','direction','up'])for(let i=0;i<3;i++)assert.ok(Math.abs(round[name][i]-q[name][i])<(name==='position'?1e-5:1e-10),name);
let pole=p;for(let i=0;i<12;i++)pole=D.rotate(pole,[400,300],[400,550],[800,600],C);assert.ok(pole.position.every(Number.isFinite));
assert.deepEqual(R.weights(0,0,{blueAtmosphere:false,nightAirglow:false}),{blue:0,warm:0});
for(const flags of [{blueAtmosphere:true,nightAirglow:false},{blueAtmosphere:false,nightAirglow:true},{blueAtmosphere:true,nightAirglow:true}]){
 const day=R.weights(0,1,flags),night=R.weights(0,-1,flags);assert.equal(day.warm,0);assert.equal(night.blue,0);assert.equal(day.blue,flags.blueAtmosphere?.16:0);assert.equal(night.warm,flags.nightAirglow?.12:0);
 assert.ok(R.weights(-10000,1,flags).blue<=R.weights(18000,1,flags).blue);}
console.log('PASS: grouped undo/redo, redo invalidation, immutable snapshots; unconstrained globe rotation, orbit round-trip; independent UTC day/night rim switches.');
