(function(root){
 function create(api){const $=id=>document.getElementById(id),T=root.EarthTimeline,utc=root.EarthUtcTimeline.create(api);let signature='';
  function render(){const p=api.project(),next=JSON.stringify([api.active(),p.fps,p.tracks.map(t=>[t.id,t.name,t.asset?.revision,t.keys.length,T.duration(p,t.id),t.weather]),p.weather]);
   if(next!==signature){signature=next;root.EarthShotLibrary.migrate(p);$('libraryCards').replaceChildren(...p.tracks.map((t,i)=>{const button=document.createElement('button');button.className='libraryCard'+(t.id===api.active()?' active':'');button.setAttribute('aria-pressed',String(t.id===api.active()));button.title=`${t.name}\nShot ${t.asset.id} · r${t.asset.revision}`;
    const number=document.createElement('span');number.className='shotNumber';number.textContent=String(i+1).padStart(2,'0');const title=document.createElement('strong');title.textContent=t.name;const info=document.createElement('small');info.textContent=`${T.duration(p,t.id).toFixed(1)}秒 · ${t.keys.length}个关键帧 · r${t.asset.revision}`;button.append(number,title,info);button.onclick=()=>api.select(t.id);return button;}));}
   utc.render();
  }
  $('exportRenderPlan').onclick=api.edit(()=>{const data=root.EarthShotLibrary.tasks(api.project(),T,api.frames());api.save(data,'render-plan-export','independent-shot-tasks.json');api.message(`已保存${data.tasks.length}个独立任务快照，正式输出无声；尚未启动渲染。`);});
  return {render};
 }
 root.EarthLibraryUI={create};
})(globalThis);
