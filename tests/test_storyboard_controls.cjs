const assert=require('node:assert/strict'),fs=require('node:fs');
global.EarthTimeline=require('../native/EarthStudio.App/Cesium/timeline.js');global.EarthShots=require('../native/EarthStudio.App/Cesium/shots.js');global.EarthMontage=require('../native/EarthStudio.App/Cesium/montage.js');
const B=require('../native/EarthStudio.App/Cesium/storyboard.js');
class Element{constructor(){this.value='';this.children=[];}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}querySelector(){return null;}add(value){this.children.push(value);}}
const elements=new Map([...fs.readFileSync('native/EarthStudio.App/Cesium/index.html','utf8').matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
global.document={activeElement:null,getElementById:id=>{assert.ok(elements.has(id),id);return elements.get(id);},createElement:()=>new Element()};global.Option=function(name,value){this.text=name;this.value=value;};
let p=JSON.parse(fs.readFileSync('tests/fixtures/storyboard_timeline.json'));p.fps=24;p.sourcePlayback={mode:'sequence',intervalSeconds:600};const id=p.tracks[0].id;
const ui=B.createUi({project:()=>p,active:()=>id,time:()=>1,actualWeather:()=>p.weather.startUtc,currentWeather:()=>p.weather.startUtc,intervalSeconds:()=>600,select:()=>{},edit:fn=>fn,replace:value=>{p=value;ui.render();}});
const $=id=>elements.get(id);ui.render();assert.equal($('shotClockMode').value,'sequence');
$('shotClockMode').value='mapped';$('shotClockMode').onchange();assert.equal($('legacyShotWeather').hidden,false);
$('shotWeatherMode').value='fit';$('shotWeatherCurve').value='smooth';$('applyShotTime').onclick();assert.equal(p.tracks[0].weather.mode,'mapped');assert.ok(p.tracks[0].weather.curve);
$('shotHoldWeather').onclick();assert.equal(p.tracks[0].weather.startUtc,p.tracks[0].weather.endUtc);assert.equal(p.tracks[0].weather.mode,'mapped');
$('trimIn').value=1;$('trimOut').value=3;const keys=structuredClone(p.tracks[0].keys);$('applyTrim').onclick();assert.deepEqual(p.tracks[0].clip,{inFrame:24,outFrame:72});assert.deepEqual(p.tracks[0].keys,keys);
$('projectFps').value=30;$('fpsPolicy').value='seconds';$('applyProjectFps').onclick();assert.equal(p.tracks[0].weather.mode,'mapped');assert.deepEqual(p.tracks[0].clip,{inFrame:30,outFrame:90});
$('resetTrim').onclick();assert.equal(p.tracks[0].clip,undefined);
console.log('PASS actual HTML control IDs, explicit mode apply, hold, non-destructive trim, project fps keeps custom mode, restore trim');
