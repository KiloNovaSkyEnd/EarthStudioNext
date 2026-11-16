/* Shared, testable boundary for local observation manifests. */
(function (root) {
  function check(value, message) { if (!value) throw new Error(message); }
  function validateManifest(m) {
    check(m && m.schema === 'earthstudio.materials.v1', '不支持的素材索引版本');
    check(m.earthModel === 'WGS84', '此工作区要求 WGS84 椭球');
    check(['regional', 'global-nonpolar'].includes(m.scope), '范围必须明确');
    check(Array.isArray(m.frames) && m.frames.length > 0, '索引没有已提交观测');
    let previous = -Infinity;
    for (const f of m.frames) {
      check(f.missing===undefined || typeof f.missing==='boolean','缺测标记必须为布尔值');
      check(typeof f.utc === 'string' && f.utc.endsWith('Z') && Number.isFinite(Date.parse(f.utc)), '观测时间必须为 UTC');
      check(Date.parse(f.utc) > previous, '观测时间必须递增且不能重复'); previous = Date.parse(f.utc);
      check(typeof f.source === 'string' && f.source.length > 0 && typeof f.recipe === 'string' && f.recipe.length > 0, '缺少来源或配方记录');
      check(['bounded-sample', 'native-product'].includes(f.detail), '必须明确小样或原生产品');
      check(Array.isArray(f.bounds) && f.bounds.length === 4 && f.bounds.every(Number.isFinite), '缺少经纬范围');
      const [w,s,e,n] = f.bounds;
      check(w >= -180 && w <= 180 && e >= -180 && e <= 180 && w !== e && s >= -90 && n <= 90 && s < n, '经纬范围无效');
      check(['single-image', 'geographic-tiles'].includes(f.kind), '素材类型不支持');
      check(typeof f.path === 'string' && /^[A-Za-z0-9_./{}-]+$/.test(f.path) && !f.path.startsWith('/') && !f.path.split('/').includes('..'), '仅允许素材目录内的相对路径');
      if(f.previewPath!==undefined){
        check(typeof f.previewPath==='string'&&/^[A-Za-z0-9_./-]+$/.test(f.previewPath)&&!f.previewPath.startsWith('/')&&!f.previewPath.split('/').includes('..'),'预览必须位于本地素材目录');
        check(Array.isArray(f.previewBounds)&&f.previewBounds.length===4&&f.previewBounds.every(Number.isFinite),'预览缺少经纬范围');
        const [pw,ps,pe,pn]=f.previewBounds;check(pw>=-180&&pe<=180&&pw<pe&&ps>=-90&&pn<=90&&ps<pn,'预览经纬范围无效');
      }
      if (f.kind === 'geographic-tiles') {
        check(f.tileSize===undefined || [256,512,1024].includes(f.tileSize), '瓦片像素尺寸无效');
        check(Number.isInteger(f.maximumLevel) && f.maximumLevel >= 0 && f.maximumLevel <= 24, '需要真实最高瓦片级别');
        check(['{z}','{x}','{y}'].every(t => f.path.includes(t)), '瓦片路径缺少 z/x/y');
      }
    }
    if(m.videoPreview!==undefined){
      const v=m.videoPreview;
      check(v&&typeof v.path==='string'&&/^[A-Za-z0-9_./-]+\.mp4$/.test(v.path)&&!v.path.startsWith('/')&&!v.path.split('/').includes('..'),'连续云图必须位于本地素材目录');
      check(v.frames===m.frames.length&&v.frames>1&&Number.isFinite(v.fps)&&v.fps>0&&v.fps<=120,'连续云图帧数或帧率无效');
      check(v.lastFrameTime===(v.frames-1)/v.fps&&Number.isInteger(v.bytes)&&v.bytes>0,'连续云图时间映射无效');
      check(v.gapPolicy==='hold-last-labeled'&&!m.frames[0].missing,'连续云图缺档策略无效');
      check(m.frames.every(f=>f.missing||f.previewPath&&JSON.stringify(f.previewBounds)==='[-180,-90,180,90]'),'连续云图需要对应的全球投影显示帧');
      const step=Date.parse(m.frames[1].utc)-Date.parse(m.frames[0].utc);
      check(m.frames.every((f,i)=>Date.parse(f.utc)===Date.parse(m.frames[0].utc)+step*i),'连续云图要求包含缺档节点的等间隔时间轴');
    }
    return m;
  }
  const api = { validateManifest };
  if (typeof module !== 'undefined') module.exports = api;
  root.EarthContract = api;
})(globalThis);
