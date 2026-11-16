/* Real Cesium evaluator is the numerical oracle, including independent retiming. */
const fs=require('node:fs');
const C=Function(fs.readFileSync('native/EarthStudio.App/Cesium/vendor/Cesium.js','utf8')+';return Cesium;')();
const T=require('../native/EarthStudio.App/Cesium/timeline.js'),S=require('../native/EarthStudio.App/Cesium/shots.js');
const output={width:1920,height:1080},base={targetLon:130.7,targetLat:18,heading:0,pitch:-30,rangeKm:4500,roll:0,fov:40};
function key(time,changes={},extra={}){const orbit={...base,...changes};return {time,orbit,pose:T.orbitPose(orbit,output,C),...extra};}
let project={schema:'earthstudio.timeline.v1',earthModel:'WGS84',fps:30,duration:20,output,activeTrack:'A',
 weather:{startUtc:'2026-10-20T22:40:00Z',endUtc:'2026-10-20T22:40:00Z'},tracks:[
 {id:'A',name:'A · 侧视到垂直俯视',duration:20,easing:'smooth',keys:[key(0),key(10,{pitch:-90,rangeKm:3000}),key(20,{heading:-70,pitch:-40,roll:25,rangeKm:2500})]},
 {id:'B',name:'B · 推进与整圈旋转',duration:12,easing:'linear',curve:[[0,0],[.2,.05],[.5,.9],[.85,.95],[1,1]],keys:[key(0,{rangeKm:6000}),key(12,{heading:360,roll:360,rangeKm:1800,fov:55})]},
 {id:'D',name:'D · 切换与停顿测试',duration:6,easing:'linear',keys:[key(0,{}, {curve:[[0,0],[.3,.4],[.7,.4],[1,1]]}),key(3,{heading:40}),key(6,{heading:-60,pitch:-80},{transition:'cut'})]},
 {id:'E',name:'E · 跨日期线测试',duration:4,easing:'smooth',keys:[key(0,{targetLon:179,targetLat:-30}),key(2,{targetLon:-179,targetLat:-15}),key(4,{targetLon:-175,targetLat:10})]},
 ]};
project.tracks.push({...JSON.parse(JSON.stringify(project.tracks[1])),id:'C',name:'C · B同路径延长到30秒'});
project=T.retimeTrack(project,'C',30,S);
const freeKeys=[key(0),key(3,{heading:40,roll:20})];for(const k of freeKeys)delete k.orbit;
project.tracks.push({id:'F',name:'F · 自由姿态兼容',duration:3,easing:'smooth',keys:freeKeys});
const tracks=project.tracks.map(t=>T.bake(project,t.id,C,S));
for(const t of tracks)for(const sample of t.samples)sample.utc='2026-10-20T22:40:00Z';
fs.writeFileSync('reports/editable_camera_test_bundle.json',JSON.stringify({schema:'earthstudio.camera_bundle.v1',timelineProject:project,tracks}));
console.log('Prepared 6 independent takes: 5 sparse rigs and 1 free-pose fallback.');
