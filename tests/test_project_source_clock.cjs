const assert=require('node:assert/strict'),fs=require('node:fs');
const C=Function(fs.readFileSync('native/EarthStudio.App/Cesium/vendor/Cesium.js','utf8')+';return Cesium;')();
const T=require('../native/EarthStudio.App/Cesium/timeline.js'),S=require('../native/EarthStudio.App/Cesium/shots.js');
const p=JSON.parse(fs.readFileSync('tests/fixtures/storyboard_timeline.json'));
p.fps=24;p.sourcePlayback={mode:'sequence',intervalSeconds:600};
p.weather={startUtc:'2026-10-20T13:00:00Z',endUtc:'2026-10-30T13:00:00Z'};
for(const track of p.tracks)track.weather={startUtc:p.weather.startUtc,endUtc:p.weather.endUtc};
T.validate(p,S);
const origin=Date.parse(p.weather.startUtc);
for(const fps of [24,30,23.976,48]){
 const q=structuredClone(p);q.fps=fps;T.validate(q,S);
 for(let n=0;n<241;n++)assert.ok(Math.abs(Date.parse(T.weatherTime(q,n/fps,'A'))-origin-n*600000)<1);
 assert.equal(Date.parse(T.weatherTime(q,10,'A'))-origin,Math.round(10*fps*600000));
 assert.equal(T.bake(q,'A',C,S).fps,fps);
}
const retimed=T.retimeTrack(p,'A',30,S);
assert.equal(T.weatherTime(retimed,5,'A'),T.weatherTime(p,5,'A'));
assert.equal(T.weatherTime(p,5,'A'),T.weatherTime(p,5,'B'));
const q=structuredClone(p);q.tracks[1].weather.startUtc='2026-10-20T14:00:00Z';
assert.equal(Date.parse(T.weatherTime(q,5,'B'))-Date.parse(T.weatherTime(q,5,'A')),3600000);
const keys=structuredClone(q.tracks.map(t=>t.keys));q.fps=30;T.validate(q,S);assert.deepEqual(q.tracks.map(t=>t.keys),keys);
fs.mkdirSync('reports/project_source_clock',{recursive:true});
// A small geographic fixture tests frame stepping and import independently of long science production.
const fixture=structuredClone(p);fixture.weather.endUtc='2026-10-20T13:20:00Z';
for(const track of fixture.tracks)track.weather={startUtc:fixture.weather.startUtc,endUtc:fixture.weather.endUtc};
fs.writeFileSync('reports/project_source_clock/bundle.json',JSON.stringify({schema:'earthstudio.camera_bundle.v1',timelineProject:fixture,tracks:fixture.tracks.map(t=>T.bake(fixture,t.id,C,S))}));
console.log('PASS: project24/30/23.976/48fps, source n at project frame n, independent shot duration/start, camera keys unchanged, project fps export.');
