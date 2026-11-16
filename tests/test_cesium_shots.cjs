const fs=require('node:fs'),assert=require('node:assert/strict');
try {
  const C=Function(fs.readFileSync('native/EarthStudio.App/Cesium/vendor/Cesium.js','utf8')+';return Cesium;')();
  const S=require('../native/EarthStudio.App/Cesium/shots.js');
  const array=v=>[v.x,v.y,v.z];
  function shot(lon,roll,duration=5) {
    const position=C.Cartesian3.fromDegrees(lon,20,3000000),direction=C.Cartesian3.normalize(C.Cartesian3.negate(position,new C.Cartesian3()),new C.Cartesian3());
    let up=C.Cartesian3.normalize(C.Cartesian3.cross(C.Cartesian3.cross(direction,C.Cartesian3.UNIT_Z,new C.Cartesian3()),direction,new C.Cartesian3()),new C.Cartesian3());
    up=C.Matrix3.multiplyByVector(C.Matrix3.fromQuaternion(C.Quaternion.fromAxisAngle(direction,roll)),up,new C.Cartesian3());
    return {name:'test',duration,pose:{position:array(position),direction:array(direction),up:array(up),verticalFov:Math.PI/4,aspect:16/9,width:1920,height:1080,utc:'2022-08-31T17:00:00Z',brightness:1}};
  }
  const plan={schema:'earthstudio.shots.v1',earthModel:'WGS84',shots:[shot(125,0),shot(140,.5,130)]};
  assert.equal(S.duration(S.validate(plan)),130);
  const baked=S.bake(plan,C);assert.equal(baked.samples.length,3901);assert.equal(baked.samples.at(-1).seconds,130);
  for(const p of baked.samples) {
    assert.ok(C.Cartographic.fromCartesian(C.Cartesian3.fromArray(p.position)).height>2999999);
    assert.ok(Math.abs(C.Cartesian3.dot(C.Cartesian3.fromArray(p.direction),C.Cartesian3.fromArray(p.up)))<1e-8);
  }
  for(const t of [0,65,130]) assert.deepEqual(S.sample(plan,t,C),baked.samples[Math.round(t*30)]);
  const end=S.sample(plan,130,C);for(let i=0;i<3;i++){assert.ok(Math.abs(end.position[i]-plan.shots[1].pose.position[i])<1e-4);assert.ok(Math.abs(end.up[i]-plan.shots[1].pose.up[i])<1e-9);}
  const cross={...plan,shots:[shot(179,0),shot(-179,.5)]};assert.ok(Math.abs(C.Math.toDegrees(C.Cartographic.fromCartesian(C.Cartesian3.fromArray(S.sample(cross,2.5,C).position)).longitude))>179);
  const cut={...plan,shots:[shot(125,0),{...shot(140,.5),transition:'cut'}]};assert.deepEqual(S.sample(cut,4,C).position,S.sample(cut,0,C).position);
  assert.throws(()=>S.validate({...plan,shots:[{...shot(1,0),duration:NaN}]}));
  const resize=shot(1,0);resize.pose.width=960;assert.throws(()=>S.validate({...plan,shots:[shot(1,0),resize]}));
  fs.writeFileSync('reports/cesium_shots_130s.json',JSON.stringify(baked));
  console.log('PASS: 130s / 3901 samples; roll, geodesic altitude, antimeridian, hard cut, endpoint and preview/export equality; invalid duration/resize rejected.');
} catch(e) {console.error(e.message);process.exitCode=1;}
