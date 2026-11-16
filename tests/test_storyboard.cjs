const assert=require('node:assert/strict'),fs=require('node:fs');
const C=Function(fs.readFileSync('native/EarthStudio.App/Cesium/vendor/Cesium.js','utf8')+';return Cesium;')();
const T=require('../native/EarthStudio.App/Cesium/timeline.js'),S=require('../native/EarthStudio.App/Cesium/shots.js');
const B=require('../native/EarthStudio.App/Cesium/storyboard.js'),V=require('../native/EarthStudio.App/Cesium/weather-video.js');
const orbit={targetLon:130,targetLat:18,heading:0,pitch:-45,rangeKm:4500,roll:0,fov:40},output={width:1920,height:1080};
let p={schema:'earthstudio.timeline.v1',earthModel:'WGS84',fps:30,duration:10,output,activeTrack:'A',
 weather:{startUtc:'2026-10-20T00:00:00Z',endUtc:'2026-10-21T00:00:00Z'},
 tracks:['A','B','C'].map(id=>({id,name:id,easing:'linear',keys:[{time:0,orbit,pose:T.orbitPose(orbit,output,C)},{time:10,orbit:{...orbit,heading:90},pose:T.orbitPose({...orbit,heading:90},output,C)}]}))};
const window={startUtc:'2026-10-20T12:00:00Z',endUtc:'2026-10-20T18:00:00Z'};
p=B.setWeather(p,'A',window,T,S);p=B.setWeather(p,'B',window,T,S);p=T.retimeTrack(p,'B',25,S);
assert.equal(T.weatherTime(p,5,'A'),'2026-10-20T15:00:00.000Z');assert.equal(T.weatherTime(p,12.5,'B'),'2026-10-20T15:00:00.000Z');
for(let i=0;i<=10;i++)assert.deepEqual(T.sample(p,'A',i,C,S).position,T.sample(p,'B',i*2.5,C,S).position);
p=B.setWeather(p,'C',{startUtc:'2026-10-20T15:00:00Z',endUtc:'2026-10-20T15:00:00Z'},T,S);p=T.retimeTrack(p,'C',8,S);
assert.equal(T.weatherTime(p,0,'C'),T.weatherTime(p,8,'C'));assert.notDeepEqual(T.sample(p,'C',0,C,S).position,T.sample(p,'C',8,C,S).position);
assert.deepEqual(B.layout(p,T).map(r=>[r.start,r.end]),[[0,10],[10,35],[35,43]]);
const reordered=B.move(p,'C',-1);assert.equal(reordered.tracks[1].id,'C');assert.deepEqual(reordered.tracks.find(t=>t.id==='A'),p.tracks[0]);
assert.throws(()=>B.setWeather(p,'A',{startUtc:'2026-10-19T12:00:00Z',endUtc:window.endUtc},T,S));
p=B.setWeather(p,'B',{...window,curve:[[0,0],[.25,.7],[1,1]]},T,S);
assert.notEqual(T.weatherTime(p,6.25,'B'),T.weatherTime(p,2.5,'A'));
assert.deepEqual(V.mediaBounds({lastFrameTime:100},{start:.5,end:.75}),[50,75]);
const baked=p.tracks.map(t=>T.bake(p,t.id,C,S));
assert.equal(baked[1].samples[0].timelineUtc,'2026-10-20T12:00:00.000Z');assert.equal(baked[1].samples.at(-1).timelineUtc,'2026-10-20T18:00:00.000Z');
fs.mkdirSync('reports/m6_continuity',{recursive:true});fs.writeFileSync('reports/m6_continuity/storyboard_bundle.json',JSON.stringify({schema:'earthstudio.camera_bundle.v1',timelineProject:p,tracks:baked}));
const fixture=structuredClone(p);fixture.weather={startUtc:'2026-10-20T13:00:00Z',endUtc:'2026-10-20T13:20:00Z'};
for(const t of fixture.tracks)t.weather={...t.weather,startUtc:'2026-10-20T13:00:00Z',endUtc:'2026-10-20T13:10:00Z'};
fixture.tracks[2].weather={startUtc:'2026-10-20T13:05:00Z',endUtc:'2026-10-20T13:05:00Z'};
fs.writeFileSync('reports/m6_continuity/fixture_storyboard_bundle.json',JSON.stringify({schema:'earthstudio.camera_bundle.v1',timelineProject:fixture,tracks:fixture.tracks.map(t=>T.bake(fixture,t.id,C,S))}));
console.log('PASS: per-shot UTC, independent10/25/8s durations, frozen weather with moving camera, retiming path equality, reorder, bounds, nonlinear weather and video segment mapping.');
