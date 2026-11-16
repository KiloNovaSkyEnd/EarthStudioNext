const fs=require('node:fs'),assert=require('node:assert/strict');
try {
 const C=Function(fs.readFileSync('native/EarthStudio.App/Cesium/vendor/Cesium.js','utf8')+';return Cesium;')();
 const A=require('../native/EarthStudio.App/Cesium/camera-actions.js');
 const pose={position:[-6000000,7000000,3000000],direction:[0,0,-1],up:[0,1,0],verticalFov:.5};
 const roll=A.rotate(pose,'roll',30,C);
 assert.deepEqual(roll.position,pose.position);assert.deepEqual(roll.direction,pose.direction);
 assert.ok(Math.abs(C.Cartesian3.dot(C.Cartesian3.fromArray(roll.up),C.Cartesian3.fromArray(pose.up))-Math.cos(Math.PI/6))<1e-12);
 for(const kind of ['roll','yaw','pitch']) {
  const p=A.rotate(pose,kind,35,C), restored=A.rotate(p,kind,-35,C);
  assert.deepEqual(p.position,pose.position);assert.equal(p.verticalFov,pose.verticalFov);
  assert.ok(Math.abs(C.Cartesian3.dot(C.Cartesian3.fromArray(p.direction),C.Cartesian3.fromArray(p.up)))<1e-12);
  for(const key of ['direction','up'])for(let i=0;i<3;i++)assert.ok(Math.abs(restored[key][i]-pose[key][i])<1e-12);
 }
 assert.ok(A.rotate(pose,'yaw',5,C).direction[0]<0);
 assert.ok(A.rotate(pose,'pitch',5,C).direction[1]>0);
 assert.throws(()=>A.rotate(pose,'orbit',5,C));assert.throws(()=>A.rotate(pose,'roll',NaN,C));
 console.log('PASS: roll preserves position/direction; yaw/pitch preserve position; rotations reversible and orthonormal; frustum unchanged.');
} catch(e){console.error(e.message);process.exitCode=1;}
