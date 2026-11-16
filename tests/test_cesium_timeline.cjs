const fs=require('node:fs'),assert=require('node:assert/strict');
try {
 const C=Function(fs.readFileSync('native/EarthStudio.App/Cesium/vendor/Cesium.js','utf8')+';return Cesium;')();
 const T=require('../native/EarthStudio.App/Cesium/timeline.js'),S=require('../native/EarthStudio.App/Cesium/shots.js');
 const output={width:1920,height:1080},o={targetLon:130,targetLat:20,heading:0,pitch:-25,rangeKm:4500,roll:0,fov:40};
 const key=(time,changes)=>{const orbit={...o,...changes};return {time,orbit,pose:T.orbitPose(orbit,output,C)};};
 let project={schema:'earthstudio.timeline.v1',earthModel:'WGS84',fps:30,duration:20,output,weather:{startUtc:'2022-08-31T17:00:00Z',endUtc:'2022-08-31T17:20:00Z'},activeTrack:'A',tracks:[{id:'A',name:'A',easing:'linear',keys:[key(0,{}),key(10,{pitch:-90,rangeKm:3000}),key(20,{heading:-60,pitch:-40,roll:30,rangeKm:2500})]}]};
 T.validate(project,S);
 assert.equal(T.wrap(300),-60);assert.equal(T.wrap(-190),170);
 for(const key of project.tracks[0].keys){const p=T.sample(project,'A',key.time,C,S);for(const name of ['position','direction','up'])for(let i=0;i<3;i++)assert.ok(Math.abs(p[name][i]-key.pose[name][i])<1e-7);}
 const middle=T.sample(project,'A',5,C,S);assert.equal(middle.orbit.pitch,-57.5);assert.equal(middle.orbit.rangeKm,3750);
 const t60=T.retime(project,60,S);
 for(let i=0;i<=100;i++){const a=T.sample(project,'A',i/5,C,S),b=T.sample(t60,'A',i*3/5,C,S);for(const name of ['position','direction','up'])for(let j=0;j<3;j++)assert.ok(Math.abs(a[name][j]-b[name][j])<1e-6);}
 for(const points of Object.values(T.PRESETS)){T.validateCurve(points);let prev=-1;for(let i=0;i<=1000;i++){const p=T.progress(points,i/1000);assert.ok(p>=prev-1e-12&&p>=0&&p<=1);prev=p;}assert.equal(T.progress(points,0),0);assert.equal(T.progress(points,1),1);}
 const custom=[[0,0],[.2,.05],[.5,.9],[.85,.95],[1,1]];T.validateCurve(custom);
 const curved=JSON.parse(JSON.stringify(project));curved.tracks[0].keys[0].curve=custom;
 assert.notEqual(T.sample(curved,'A',5,C,S).orbit.pitch,middle.orbit.pitch);
 assert.deepEqual(T.sample(curved,'A',10,C,S).position,T.sample(project,'A',10,C,S).position);
 const retimedCurve=T.retime(curved,60,S);assert.deepEqual(retimedCurve.tracks[0].keys[0].curve,custom);
 for(const time of [0,2,5,10,15,20]){const a=T.sample(curved,'A',time,C,S),b=T.sample(retimedCurve,'A',time*3,C,S);assert.deepEqual(a.position,b.position);}
 const spinning={...project,tracks:[{id:'A',name:'spin',easing:'linear',keys:[key(0,{}),key(20,{heading:360,roll:360})]}]};
 assert.equal(T.sample(spinning,'A',10,C,S).orbit.heading,180);assert.equal(T.sample(spinning,'A',10,C,S).orbit.roll,180);
 const takes=JSON.parse(JSON.stringify(project));takes.tracks.push({...JSON.parse(JSON.stringify(takes.tracks[0])),id:'B',name:'B'});
 const updated=T.upsert(takes,'B',key(10,{pitch:-40}),S);assert.equal(updated.tracks[0].keys[1].orbit.pitch,-90);assert.equal(updated.tracks[1].keys[1].orbit.pitch,-40);
 assert.equal(T.sample(updated,'A',5,C,S).timelineUtc,T.sample(updated,'B',5,C,S).timelineUtc);
 const shortB=T.retimeTrack(updated,'B',10,S);
 assert.equal(T.duration(shortB,'A'),20);assert.equal(T.duration(shortB,'B'),10);
 assert.equal(shortB.tracks[0].keys[1].time,10);assert.equal(shortB.tracks[1].keys[1].time,5);
 for(const time of [0,2,5,10]){assert.deepEqual(T.sample(updated,'B',time*2,C,S).position,T.sample(shortB,'B',time,C,S).position);assert.equal(T.sample(shortB,'A',time*2,C,S).timelineUtc,T.sample(shortB,'B',time,C,S).timelineUtc);}
 assert.equal(T.bake(shortB,'B',C,S).samples.length,301);
 assert.throws(()=>T.validateCurve([[0,0],[.5,.9],[.6,.2],[1,1]]));assert.throws(()=>T.retime(project,0,S));
 const portrait={...key(0,{}).pose,width:1080,height:1920,aspect:1080/1920};
 assert.deepEqual(T.fromLegacy({shots:[{duration:1,pose:portrait}]},output).output,{width:1080,height:1920});
 const baked=T.bake(curved,'A',C,S);assert.equal(baked.samples.length,601);
 const cut=JSON.parse(JSON.stringify(project));cut.tracks[0].keys[1].transition='cut';
 assert.deepEqual(T.sample(cut,'A',9,C,S).position,T.sample(cut,'A',0,C,S).position);
 assert.ok(T.bake(cut,'A',C,S).samples[300].cut);
 for(let i=0;i<baked.samples.length;i+=17)assert.deepEqual(baked.samples[i].position,T.sample(curved,'A',i/30,C,S).position);
 fs.writeFileSync('reports/timeline_unit_camera.json',JSON.stringify(baked));
 console.log('PASS: absolute-time keys, exact endpoints, 3D orbit/roll/FOV interpolation, 360-degree turns, longitude normalization, independent takes, shared UTC, monotone custom speed, path-preserving retiming, preview/export equality.');
}catch(e){console.error(e.message);process.exitCode=1;}
