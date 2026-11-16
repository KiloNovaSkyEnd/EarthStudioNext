const assert=require('node:assert/strict'),fs=require('node:fs');
const C=Function(fs.readFileSync('native/EarthStudio.App/Cesium/vendor/Cesium.js','utf8')+';return Cesium;')();
const T=require('../native/EarthStudio.App/Cesium/timeline.js'),S=require('../native/EarthStudio.App/Cesium/shots.js');
const p=JSON.parse(fs.readFileSync('reports/m6_continuity/fixture_storyboard_bundle.json')).timelineProject;
// Two ten-minute intervals, one second each; camera still lasts ten seconds.
p.tracks[0].weather={startUtc:'2026-10-20T13:00:00Z',endUtc:'2026-10-20T13:20:00Z',observationFps:1,intervalSeconds:600};
p.tracks[1].weather={...p.tracks[0].weather,observationFps:.05};
T.validate(p,S);
assert.equal(T.weatherTime(p,1,'A'),'2026-10-20T13:10:00.000Z');
assert.equal(T.weatherTime(p,8,'A'),'2026-10-20T13:20:00.000Z');
assert.equal(T.weatherTime(p,10,'B'),'2026-10-20T13:05:00.000Z');
const next=T.retimeTrack(p,'A',30,S);
assert.equal(T.weatherTime(next,1,'A'),T.weatherTime(p,1,'A'));
assert.equal(T.duration(next,'B'),25);
assert.notDeepEqual(T.sample(p,'A',2,C,S).position,T.sample(p,'A',8,C,S).position);
for(const bad of [0,-1,NaN,121]){const q=structuredClone(p);q.tracks[0].weather.observationFps=bad;assert.throws(()=>T.validate(q,S));}
const conflict=structuredClone(p);conflict.tracks[0].weather.curve=T.PRESETS.smooth;assert.throws(()=>T.validate(conflict,S));
fs.mkdirSync('reports/weather_fps',{recursive:true});
fs.writeFileSync('reports/weather_fps/bundle.json',JSON.stringify({schema:'earthstudio.camera_bundle.v1',timelineProject:p,tracks:p.tracks.map(t=>T.bake(p,t.id,C,S))}));
console.log('PASS: independent observation rates, endpoint hold, short-shot crop, retime invariance, moving camera, invalid/conflicting rate rejection.');
