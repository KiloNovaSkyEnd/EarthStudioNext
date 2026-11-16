/* Non-destructive music decisions. All coordinates stay in real seconds across FPS changes. */
(function(root){
 'use strict';
 const copy=x=>JSON.parse(JSON.stringify(x)),check=(v,m)=>{if(!v)throw Error(m);};
 const id=()=>globalThis.crypto?.randomUUID?.()??('m_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2));
 const empty=()=>({schema:'earthstudio.music.v1',assets:[],shots:{}});
 function validate(music){
  if(music===undefined)return;
  check(music?.schema==='earthstudio.music.v1'&&Array.isArray(music.assets)&&music.assets.length<=100,'音乐工程格式无效');
  check(music.shots&&typeof music.shots==='object'&&!Array.isArray(music.shots),'音乐方案无效');
  const ids=new Set();
  for(const a of music.assets){check(typeof a.id==='string'&&/^[a-zA-Z0-9_-]{1,100}$/.test(a.id)&&!ids.has(a.id),'音乐身份无效或重复');ids.add(a.id);
   check(typeof a.name==='string'&&a.name.length<=250&&Number.isFinite(a.duration)&&a.duration>0&&a.duration<=7200,'音乐时长或名称无效');
   check(a.url===undefined||/^\/music-assets\/[a-f0-9]{64}\.(wav|mp3)$/i.test(a.url),'音乐地址无效');
   if(a.peaks)check(Array.isArray(a.peaks)&&a.peaks.length<=2048&&a.peaks.every(x=>Number.isFinite(x)&&x>=0&&x<=1),'波形缓存无效');
  }
  check(Object.keys(music.shots).length<=100,'音乐方案数量过多');
  for(const plan of Object.values(music.shots)){
   check(Array.isArray(plan.clips)&&plan.clips.length<=100&&Array.isArray(plan.markers)&&plan.markers.length<=500,'音乐片段或标记过多');
   const clips=[...plan.clips].sort((a,b)=>a.start-b.start),clipIds=new Set();let end=0;
   for(const c of clips){const a=music.assets.find(a=>a.id===c.assetId);
    check(typeof c.id==='string'&&!clipIds.has(c.id)&&a,'音乐片段身份或源文件无效');clipIds.add(c.id);
    check(['start','in','out','gain','fadeIn','fadeOut'].every(k=>Number.isFinite(c[k])),'音乐参数必须是有限数值');
    check(c.start>=0&&c.in>=0&&c.out>c.in&&c.out<=a.duration+1e-6&&c.gain>=0&&c.gain<=2&&c.fadeIn>=0&&c.fadeOut>=0&&c.fadeIn+c.fadeOut<=c.out-c.in+1e-6,'音乐区间、音量或淡变超出范围');
    check(c.start>=end-1e-6,'单音乐轨片段不能重叠');end=c.start+c.out-c.in;
   }
   const markers=new Set();for(const m of plan.markers){check(typeof m.id==='string'&&!markers.has(m.id)&&typeof m.name==='string'&&m.name.length<=100&&Number.isFinite(m.time)&&m.time>=0,'音乐标记无效');markers.add(m.id);}
  }
  return music;
 }
 const plan=(music,shot)=>music?.shots?.[shot]??{clips:[],markers:[]};
 function edit(music,shot,fn){const next=copy(music??empty());next.shots[shot]??={clips:[],markers:[]};fn(next.shots[shot],next);validate(next);return next;}
 function envelope(c,time){const elapsed=time-c.start,length=c.out-c.in;if(elapsed<0||elapsed>=length)return 0;return (c.muted?0:c.gain)*Math.min(1,c.fadeIn?elapsed/c.fadeIn:1,c.fadeOut?(length-elapsed)/c.fadeOut:1);}
 function at(music,shot,time){const c=plan(music,shot).clips.find(c=>time>=c.start&&time<c.start+c.out-c.in);return c?{clip:c,source:c.in+time-c.start,gain:envelope(c,time)}:null;}
 function peaks(buffer,count=1024){const result=[],step=Math.max(1,Math.ceil(buffer.length/count));for(let i=0;i<buffer.length;i+=step){let v=0;for(let channel=0;channel<buffer.numberOfChannels;channel++){const data=buffer.getChannelData(channel);for(let j=i;j<Math.min(i+step,data.length);j++)v=Math.max(v,Math.abs(data[j]));}result.push(Math.min(1,v));}return result;}
 const api={empty,validate,id,plan,edit,envelope,at,peaks};if(typeof module!=='undefined')module.exports=api;root.EarthMusic=api;
})(globalThis);
