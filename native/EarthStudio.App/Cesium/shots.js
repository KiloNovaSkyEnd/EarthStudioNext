/* Shot interpolation shared by preview and baked Blender export. */
(function(root) {
  const MAX_SAMPLES = 1000000;
  function check(v,m) { if (!v) throw new Error(m); }
  function validate(plan) {
    check(plan?.schema === 'earthstudio.shots.v1' && plan.earthModel === 'WGS84', '不支持的运镜工程');
    check(Array.isArray(plan.shots) && plan.shots.length >= 1 && plan.shots.length <= 1000, '需要1至1000个机位');
    let dimensions;
    for (const shot of plan.shots) {
      check(typeof shot.name === 'string' && shot.name.length <= 100, '机位名称无效');
      check(Number.isFinite(shot.duration) && shot.duration >= 0.1 && shot.duration <= 86400, '过渡时长应为0.1秒至24小时');
      const p = shot.pose;
      for (const key of ['position','direction','up']) check(Array.isArray(p?.[key]) && p[key].length === 3 && p[key].every(Number.isFinite), '机位坐标无效');
      const dot = (a,b) => a.reduce((s,x,i) => s+x*b[i],0);
      check(Math.abs(dot(p.direction,p.direction)-1)<1e-5 && Math.abs(dot(p.up,p.up)-1)<1e-5 && Math.abs(dot(p.direction,p.up))<1e-5, '机位朝向须正交');
      check(Number.isFinite(p.verticalFov) && p.verticalFov > 0 && p.verticalFov < Math.PI && Number.isFinite(p.aspect) && p.aspect > 0, '画角无效');
      check([p.width,p.height].every(x => Number.isInteger(x) && x > 0 && x <= 16384) && Math.abs(p.width/p.height-p.aspect)<1e-4, '画幅无效');
      check(p.utc === null || (typeof p.utc === 'string' && p.utc.endsWith('Z') && Number.isFinite(Date.parse(p.utc))), '天气时间无效');
      check(!dimensions || dimensions === `${p.width}x${p.height}`, '机位画幅不同，请保持窗口大小一致再添加'); dimensions = `${p.width}x${p.height}`;
      const scaled = p.position.map((v,i) => v/[6378137,6378137,6356752.314245][i]);
      check(dot(scaled,scaled)>1, '机位必须位于地球表面之外');
    }
    return plan;
  }
  function duration(plan) { return plan.shots.slice(1).reduce((s,x) => s+x.duration,0); }
  function quaternion(p,C) {
    const d=C.Cartesian3.fromArray(p.direction), u=C.Cartesian3.fromArray(p.up), r=C.Cartesian3.cross(d,u,new C.Cartesian3());
    const m=new C.Matrix3(r.x,u.x,-d.x,r.y,u.y,-d.y,r.z,u.z,-d.z);
    return C.Quaternion.fromRotationMatrix(m,new C.Quaternion());
  }
  function sample(plan,seconds,C) {
    let elapsed=0, index=0;
    while (index<plan.shots.length-1 && seconds>elapsed+plan.shots[index+1].duration) elapsed+=plan.shots[++index].duration;
    const a=plan.shots[index].pose, next=plan.shots[Math.min(index+1,plan.shots.length-1)], b=next.pose;
    let t=index===plan.shots.length-1?0:Math.max(0,Math.min(1,(seconds-elapsed)/next.duration));
    if (next.transition === 'cut') t=t>=1?1:0;
    // Interpolate over the ellipsoid, with positive altitude, rather than a chord through Earth.
    const ca=C.Cartographic.fromCartesian(C.Cartesian3.fromArray(a.position)), cb=C.Cartographic.fromCartesian(C.Cartesian3.fromArray(b.position));
    let geographic;
    if (Math.abs(ca.latitude-cb.latitude)+Math.abs(ca.longitude-cb.longitude)<1e-10) geographic=C.Cartographic.clone(ca);
    else geographic=new C.EllipsoidGeodesic(ca,cb).interpolateUsingFraction(t,new C.Cartographic());
    geographic.height=ca.height+(cb.height-ca.height)*t;
    const pos=C.Cartesian3.fromRadians(geographic.longitude,geographic.latitude,geographic.height);
    const q=C.Quaternion.slerp(quaternion(a,C),quaternion(b,C),t,new C.Quaternion());
    const rotation=C.Matrix3.fromQuaternion(q), d=C.Matrix3.multiplyByVector(rotation,new C.Cartesian3(0,0,-1),new C.Cartesian3()), u=C.Matrix3.multiplyByVector(rotation,C.Cartesian3.UNIT_Y,new C.Cartesian3());
    const array=v=>[v.x,v.y,v.z];
    return {...a,seconds,position:array(pos),direction:array(d),up:array(u),
      verticalFov:a.verticalFov+(b.verticalFov-a.verticalFov)*t,
      brightness:(a.brightness??1)+((b.brightness??1)-(a.brightness??1))*t,
      utc:a.utc, timelineUtc:a.utc && b.utc ? new Date(Date.parse(a.utc)+(Date.parse(b.utc)-Date.parse(a.utc))*t).toISOString() : a.utc};
  }
  function bake(plan,C) {
    validate(plan); const end=duration(plan), count=Math.ceil(end*30)+1;
    check(count<=MAX_SAMPLES, '此导出超过100万个采样点，请拆分为多个运镜工程');
    const samples=[];
    for(let i=0;i<count;i++) samples.push(sample(plan,Math.min(i/30,end),C));
    return {schema:'earthstudio.camera.v1',earthModel:'WGS84',coordinates:'ECEF_METERS',fps:30,samples,shotPlan:plan};
  }
  const api={validate,duration,sample,bake,MAX_SAMPLES};
  if(typeof module!=='undefined') module.exports=api;
  root.EarthShots=api;
})(globalThis);
