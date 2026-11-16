/* Unconstrained camera rotation around Earth's centre, with a virtual trackball. */
(function(root){
 function rotate(p,from,to,size,C){
  const point=xy=>{let x=(2*xy[0]-size[0])/Math.min(...size),y=(size[1]-2*xy[1])/Math.min(...size),r=x*x+y*y;return C.Cartesian3.normalize(new C.Cartesian3(x,y,r<=.5?Math.sqrt(1-r):.5/Math.sqrt(r)),new C.Cartesian3());};
  const a=point(from),b=point(to),axis=C.Cartesian3.cross(a,b,new C.Cartesian3()),angle=Math.acos(Math.max(-1,Math.min(1,C.Cartesian3.dot(a,b))));
  if(C.Cartesian3.magnitude(axis)<1e-10)return JSON.parse(JSON.stringify(p));
  C.Cartesian3.normalize(axis,axis);
  const d=C.Cartesian3.fromArray(p.direction),u=C.Cartesian3.fromArray(p.up),right=C.Cartesian3.cross(d,u,new C.Cartesian3());
  const world=C.Cartesian3.add(C.Cartesian3.add(C.Cartesian3.multiplyByScalar(right,axis.x,new C.Cartesian3()),C.Cartesian3.multiplyByScalar(u,axis.y,new C.Cartesian3()),new C.Cartesian3()),C.Cartesian3.multiplyByScalar(d,-axis.z,new C.Cartesian3()),new C.Cartesian3());
  const m=C.Matrix3.fromQuaternion(C.Quaternion.fromAxisAngle(C.Cartesian3.normalize(world,world),-angle));
  const apply=v=>{const r=C.Matrix3.multiplyByVector(m,C.Cartesian3.fromArray(v),new C.Cartesian3());return [r.x,r.y,r.z];};
  return {...p,position:apply(p.position),direction:apply(p.direction),up:apply(p.up)};
 }
 function orbit(p,C){
  const pos=C.Cartesian3.fromArray(p.position),d=C.Cartesian3.fromArray(p.direction),u=C.Cartesian3.fromArray(p.up),ray=new C.Ray(pos,d),hit=C.IntersectionTests.rayEllipsoid(ray,C.Ellipsoid.WGS84);
  if(!hit||hit.start<0)return null;
  const target=C.Ray.getPoint(ray,hit.start),geo=C.Cartographic.fromCartesian(target),enu=C.Transforms.eastNorthUpToFixedFrame(target),inverse=C.Matrix4.inverseTransformation(enu,new C.Matrix4());
  const offset=C.Matrix4.multiplyByPoint(inverse,pos,new C.Cartesian3()),r=C.Cartesian3.magnitude(offset),pitch=-Math.asin(Math.max(-1,Math.min(1,offset.z/r)))*180/Math.PI;
  const localUp=C.Matrix4.multiplyByPointAsVector(inverse,u,new C.Cartesian3());
  const heading=Math.hypot(offset.x,offset.y)<1?Math.atan2(-localUp.x,localUp.y):Math.atan2(-offset.x,-offset.y);
  const localD=C.Matrix4.multiplyByPointAsVector(inverse,d,new C.Cartesian3()),base=C.Cartesian3.normalize(C.Cartesian3.cross(new C.Cartesian3(Math.cos(heading),-Math.sin(heading),0),localD,new C.Cartesian3()),new C.Cartesian3());
  const roll=-Math.atan2(C.Cartesian3.dot(C.Cartesian3.cross(base,localUp,new C.Cartesian3()),localD),C.Cartesian3.dot(base,localUp))*180/Math.PI;
  const o={targetLon:geo.longitude*180/Math.PI,targetLat:geo.latitude*180/Math.PI,heading:heading*180/Math.PI,pitch:Math.max(-90,pitch),rangeKm:r/1000,roll,fov:p.verticalFov*180/Math.PI};
  return Math.abs(o.targetLat)<=89&&o.pitch<=-2&&o.rangeKm>=100&&o.rangeKm<=50000?o:null;
 }
 const api={rotate,orbit};if(typeof module!=='undefined')module.exports=api;root.EarthGlobeDrag=api;
})(globalThis);
