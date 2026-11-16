/* Local camera rotation: location stays fixed; no target/orbit reconstruction. */
(function(root) {
  function rotate(pose,kind,degrees,C) {
    if (!['roll','yaw','pitch'].includes(kind) || !Number.isFinite(degrees)) throw new Error('无效的镜头旋转');
    const d=C.Cartesian3.fromArray(pose.direction),u=C.Cartesian3.fromArray(pose.up);
    const axis=kind==='roll'?d:kind==='yaw'?u:C.Cartesian3.cross(d,u,new C.Cartesian3());
    C.Cartesian3.normalize(axis,axis);
    const m=C.Matrix3.fromQuaternion(C.Quaternion.fromAxisAngle(axis,C.Math.toRadians(degrees)));
    const array=v=>[v.x,v.y,v.z];
    return {...pose,position:[...pose.position],direction:array(C.Matrix3.multiplyByVector(m,d,new C.Cartesian3())),up:array(C.Matrix3.multiplyByVector(m,u,new C.Cartesian3()))};
  }
  const api={rotate};if(typeof module!=='undefined')module.exports=api;root.EarthCameraActions=api;
})(globalThis);
