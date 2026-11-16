(function(root){
 function create(api){const $=id=>document.getElementById(id),music=$('musicPanel');
  function musicState(){const open=music.open;$('musicBackdrop').hidden=!open;$('musicToggle').setAttribute('aria-expanded',String(open));}
  $('musicToggle').onclick=()=>{music.open=!music.open;musicState();};music.ontoggle=musicState;$('musicBackdrop').onclick=()=>{music.open=false;musicState();};
  window.addEventListener('keydown',e=>{if(e.key==='Escape'&&music.open){music.open=false;musicState();e.preventDefault();}});
  $('musicPreviewPlay').onclick=()=>$('play').click();$('musicPreviewStart').onclick=()=>$('goStart').click();
  for(const button of document.querySelectorAll('[data-inspector]'))button.onclick=()=>{for(const candidate of document.querySelectorAll('[data-inspector]')){const active=candidate===button;candidate.classList.toggle('active',active);candidate.setAttribute('aria-selected',String(active));$(candidate.dataset.inspector+'Inspector').hidden=!active;}};
  $('curvesToggle').onclick=e=>{e.preventDefault();e.stopPropagation();const expanded=!$('localEditor').classList.contains('advanced');$('localEditor').classList.toggle('advanced',expanded);document.querySelector('.workspaceTimeline').classList.toggle('advanced',expanded);$('curvesToggle').setAttribute('aria-pressed',String(expanded));};
  function render(){const p=api.project(),t=p.tracks.find(t=>t.id===api.active());$('localShotName').textContent=(t?.name??'当前镜头')+' · '+api.length().toFixed(2)+'s';$('shotCount').textContent=p.tracks.length+'个';$('musicToggle').classList.toggle('hasMusic',!!p.music?.shots?.[api.active()]?.clips.length);$('musicPreviewPlay').textContent=$('play').textContent.startsWith('暂停')?'暂停试听':'试听当前镜头';}
  musicState();return {render,selectShot:()=>{$('localEditor').open=true;}};
 }
 root.EarthWorkspaceLayout={create};
})(globalThis);
