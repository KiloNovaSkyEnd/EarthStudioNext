/* Bounded editor transactions; a pointer gesture or focused numeric edit is one step. */
(function(root){
 const clone=x=>JSON.parse(JSON.stringify(x));
 class History{
  constructor(limit=60,budget=24*1024*1024){this.limit=limit;this.budget=budget;this.past=[];this.future=[];}
  record(before,after,group=null){
   if(JSON.stringify(before)===JSON.stringify(after))return;
   const last=this.past.at(-1),now=Date.now();
   if(group&&last?.group===group&&now-last.at<1500){last.after=clone(after);last.at=now;}
   else this.past.push({before:clone(before),after:clone(after),group,at:now});
   this.future=[];
   while(this.past.length>1&&(this.past.length>this.limit||JSON.stringify(this.past).length>this.budget))this.past.shift();
  }
  clear(){this.past=[];this.future=[];}
  undo(){const e=this.past.pop();if(!e)return null;this.future.push(e);return clone(e.before);}
  redo(){const e=this.future.pop();if(!e)return null;this.past.push(e);return clone(e.after);}
 }
 const api={History};if(typeof module!=='undefined')module.exports=api;root.EarthEditorHistory=api;
})(globalThis);
