'use strict';
let assemblyDraft=null,assemblyDefaults=null;
const fidNames={local:'局部基准',point:'点基准（贴装中心偏移）',four_main:'四点主基准',four_secondary:'四点从基准'};
const numField=(name,value,label)=>`<label>${esc(label)}<input name="${name}" type="number" step="any" value="${esc(value)}" required></label>`;
function isBadProfile(p){return new DOMParser().parseFromString(p.xml,'application/xml').querySelector('Mark_050')!==null;}
function profileOptions(id,bad=false){return assemblyDraft.profiles.filter(p=>isBadProfile(p)===bad).map(p=>`<option value="${esc(p.id)}" ${p.id===id?'selected':''}>${esc(p.id)}</option>`).join('');}
function pointFields(m,bad=false){return `${numField('x',m.x,'X / mm')}${numField('y',m.y,'Y / mm')}<label>标记模板<select name="profile">${profileOptions(m.profile,bad)}</select></label>`;}
function defaultPair(y=5){const profile=assemblyDraft.profiles.find(p=>!isBadProfile(p))?.id||'';return [{x:5,y,profile},{x:15,y:y+10,profile}];}
function defaultBad(){return {x:5,y:5,profile:assemblyDraft.profiles.find(isBadProfile)?.id||''};}
function rowValues(node){return Object.fromEntries([...node.querySelectorAll('input[name],select[name]')].map(i=>[i.name,i.type==='checkbox'?i.checked:i.type==='number'?Number(i.value):i.value]));}
function readAssembly(){
  if(!assemblyDraft)return;
  assemblyDraft.repeats=[...$('repeatRows').children].map(row=>rowValues(row));
  assemblyDraft.profiles.forEach(p=>{
    const card=[...$('assemblyProfiles').children].find(n=>n.dataset.profile===p.id);
    const doc=new DOMParser().parseFromString(p.xml,'application/xml');
    card.querySelectorAll('[data-tag]').forEach(i=>doc.querySelector(i.dataset.tag).setAttribute(i.dataset.attr,i.value));
    p.xml=new XMLSerializer().serializeToString(doc.documentElement);
  });
  assemblyDraft.block_fid=$('blockFidEnabled').checked?[...$('blockFidRows').children].map(rowValues):[];
  assemblyDraft.local_fids=[...$('localFidRows').children].map((row,i)=>({id:i+1,type:row.querySelector('[name=type]').value,
    comment:row.querySelector('[name=comment]').value,marks:[...row.querySelector('.fid-points').children].map(rowValues)}));
  const bad={local:[...$('localBadRows').children].map((row,i)=>({id:i+1,...rowValues(row)}))};
  if($('badBoardEnabled').checked)bad.board=rowValues($('badBoardFields'));
  if($('badBlockEnabled').checked)bad.block=rowValues($('badBlockFields'));
  assemblyDraft.bad_marks=bad;
  $('assignmentRows').querySelectorAll('[data-ref]').forEach(row=>{
    const link={fid:Number(row.querySelector('[name=fid]').value),bad:Number(row.querySelector('[name=bad]').value)};
    if(link.fid||link.bad)assemblyDraft.assignments[row.dataset.ref]=link;else delete assemblyDraft.assignments[row.dataset.ref];
  });
}
async function openAssembly(){
  requireProject();assemblyDefaults??=await api('/assembly-defaults');
  assemblyDraft=structuredClone(project.assembly||assemblyDefaults);
  drawAssembly();
}
function profileDiagram(p){
  const doc=new DOMParser().parseFromString(p.xml,'application/xml'),circle=doc.querySelector('Mark_011'),rect=doc.querySelector('Mark_020');
  const bad=isBadProfile(p),width=Number(circle?.getAttribute('OutSize')||rect?.getAttribute('OutSizeX')||4.5),height=Number(rect?.getAttribute('OutSizeY')||width);
  const shape=circle?'<circle cx="50" cy="50" r="28"/>':'<rect x="22" y="22" width="56" height="56"/>';
  return `<svg viewBox="0 0 100 100" width="85" height="85" role="img" aria-label="${bad?'坏板搜索区域':'标记形状'}" style="fill:none;stroke:#fbbf24;stroke-width:2">${shape}<path d="M10 50H90M50 10V90" stroke-width=".5"/></svg><span class="muted">${bad?'坏板检测搜索区域':'形状尺寸'} ${width} × ${height} mm</span>`;
}
function drawAssembly(){
  const a=assemblyDraft,bad=a.bad_marks||{},w=$('workspace');
  w.innerHTML=`<h2>拼板与辅助标记</h2><p class="muted">板信息填写整板尺寸。下方坐标为相对 YGX 程序原点的 mm；不再套用 CAD 输入镜像。点基准坐标为相对贴装中心的偏移。拼板仅保存偏移，基础贴装点保留一份。</p>
    <form id="assemblyForm"><div class="toolbar"><button class="btn primary" id="saveAssembly">保存拼板与标记</button><label class="filelabel">从 YGX / XML 导入标记模板<input id="assemblyTemplateFile" type="file" accept=".ygx,.xml"></label></div>
    <section class="section"><h3>1. 拼板偏移</h3><div id="repeatRows">${a.repeats.map((r,i)=>`<div class="mark-card" data-repeat="${i}"><h4>拼板 ${i+1}</h4><div class="formgrid">${numField('x',r.x,'偏移 X / mm')}${numField('y',r.y,'偏移 Y / mm')}${numField('rotation',r.rotation||0,'角度 / °')}<label>备注<input name="comment" value="${esc(r.comment||'')}"></label><label><input name="skip" type="checkbox" ${r.skip?'checked':''}>跳过该拼板</label></div><button type="button" class="btn ghost" data-remove-repeat="${i}">删除</button></div>`).join('')}</div><button type="button" class="btn ghost" id="addRepeat">添加拼板</button><svg id="assemblyPreview" viewBox="0 0 350 200" role="img" aria-label="拼板贴装点预览" style="width:100%;height:240px"></svg><p class="muted">预览显示整板框和偏移后的贴装中心；不会推测子板外形。</p></section>
    <details class="section"><summary>2. 标记形状、尺寸、光源与识别参数</summary><p class="muted">模板保留完整 XML。修改字段会影响所有使用此模板的辅助标记；坏板模板与基准模板分别使用。</p><div id="assemblyProfiles">${a.profiles.map(p=>{
      const doc=new DOMParser().parseFromString(p.xml,'application/xml');
      return `<details class="section" data-profile="${esc(p.id)}" open><summary>${esc(p.id)} · ${isBadProfile(p)?'坏板检测':'基准识别'}</summary><div>${profileDiagram(p)}</div>${[...doc.documentElement.children].map(n=>`<details ${['Mark_001'].includes(n.tagName)?'':'open'}><summary>${esc(n.tagName)}</summary><div class="params">${[...n.attributes].filter(v=>!['MarkType','Shape','DatabaseNo','LibraryUse','LibraryFolder','LibraryPath'].includes(v.name)).map(v=>`<label>${esc(labels[v.name]||v.name)}<input data-tag="${esc(n.tagName)}" data-attr="${esc(v.name)}" value="${esc(v.value)}"></label>`).join('')}</div></details>`).join('')}</details>`;
    }).join('')}</div></details>
    <section class="section"><h3>3. 块与局部基准</h3><label><input id="blockFidEnabled" type="checkbox" ${a.block_fid.length?'checked':''}>使用块基准（需要至少两块）</label><div id="blockFidRows">${(a.block_fid.length?a.block_fid:defaultPair()).map(m=>`<div class="formgrid mark-card">${pointFields(m)}</div>`).join('')}</div>
    <div id="localFidRows">${a.local_fids.map((r,i)=>`<div class="mark-card"><h4>基准 ${i+1}</h4><div class="formgrid"><label>类型<select name="type">${Object.entries(fidNames).map(([k,v])=>`<option value="${k}" ${r.type===k?'selected':''}>${v}</option>`).join('')}</select></label><label>名称<input name="comment" value="${esc(r.comment||'')}"></label></div><div class="fid-points">${r.marks.map(m=>`<div class="formgrid">${pointFields(m)}</div>`).join('')}</div><button type="button" class="btn ghost" data-remove-fid="${i}">删除基准</button></div>`).join('')}</div><div class="toolbar"><button type="button" class="btn ghost" id="addLocalFid">添加局部 / 点基准</button><button type="button" class="btn ghost" id="addFourFid">添加四点主从基准</button></div><p class="muted">四点坐标应包围关联元件。四点主从行必须相邻，贴装点关联主基准编号；第二个点与第一个点模板相同，YGX 使用 Mark2=0。</p></section>
    <section class="section"><h3>4. 坏板标记</h3><p class="muted">板坏标记决定是否搜索块坏标记；块坏标记跳过对应子板；局部坏标记跳过关联贴装点。使用坏标记时，YGX 禁用提前取料。</p><label><input id="badBoardEnabled" type="checkbox" ${bad.board?'checked':''}>使用板坏标记</label><div id="badBoardFields" class="formgrid">${pointFields(bad.board||defaultBad(),true)}</div><label><input id="badBlockEnabled" type="checkbox" ${bad.block?'checked':''}>使用块坏标记</label><div id="badBlockFields" class="formgrid">${pointFields(bad.block||defaultBad(),true)}</div><div id="localBadRows">${(bad.local||[]).map((r,i)=>`<div class="mark-card"><h4>局部坏标记 ${i+1}</h4><div class="formgrid">${pointFields(r,true)}<label>名称<input name="comment" value="${esc(r.comment||'')}"></label></div><button type="button" class="btn ghost" data-remove-bad="${i}">删除坏标记</button></div>`).join('')}</div><button type="button" class="btn ghost" id="addLocalBad">添加局部坏标记</button></section>
    <section class="section"><h3>5. 贴装点关联</h3><label>搜索位号<input id="assemblyRefSearch" placeholder="例如 C1"></label><div class="preview"><table><thead><tr><th>位号</th><th>局部 / 点 / 四点主基准</th><th>局部坏标记</th></tr></thead><tbody id="assignmentRows"></tbody></table></div></section></form>`;
  renderAssignments();updateAssemblyEnabled();renderAssemblyPreview();
  $('assemblyForm').onsubmit=run(async()=>{readAssembly();await api(path('/assembly'),'PUT',assemblyDraft);await refresh();toast('拼板与标记已保存');});
  const mutate=fn=>()=>{readAssembly();fn();drawAssembly();};
  $('addRepeat').onclick=mutate(()=>a.repeats.push({x:0,y:0,rotation:0,skip:false}));
  $('addLocalFid').onclick=mutate(()=>a.local_fids.push({id:a.local_fids.length+1,type:'local',marks:defaultPair(),comment:''}));
  $('addFourFid').onclick=mutate(()=>a.local_fids.push({id:a.local_fids.length+1,type:'four_main',marks:defaultPair(),comment:''},{id:a.local_fids.length+2,type:'four_secondary',marks:defaultPair(25),comment:''}));
  $('addLocalBad').onclick=mutate(()=>a.bad_marks.local.push({id:a.bad_marks.local.length+1,...defaultBad(),comment:''}));
  w.querySelectorAll('[data-remove-repeat]').forEach(b=>b.onclick=mutate(()=>a.repeats.splice(Number(b.dataset.removeRepeat),1)));
  function removeIndexed(key,index,link){
    a[key].splice(index,1);a[key].forEach((r,i)=>r.id=i+1);
    for(const value of Object.values(a.assignments)){if(value[link]===index+1)value[link]=0;else if(value[link]>index+1)value[link]--;}
  }
  w.querySelectorAll('[data-remove-fid]').forEach(b=>b.onclick=mutate(()=>removeIndexed('local_fids',Number(b.dataset.removeFid),'fid')));
  w.querySelectorAll('[data-remove-bad]').forEach(b=>b.onclick=mutate(()=>{
    const index=Number(b.dataset.removeBad);a.bad_marks.local.splice(index,1);a.bad_marks.local.forEach((r,i)=>r.id=i+1);
    for(const link of Object.values(a.assignments)){if(link.bad===index+1)link.bad=0;else if(link.bad>index+1)link.bad--;}
  }));
  $('assemblyTemplateFile').onchange=run(async e=>{
    readAssembly();const templates=await upload('/mark-templates',e.target.files[0]);
    templates.forEach(t=>{let id=t.name||'template';while(a.profiles.some(p=>p.id===id))id+='_copy';a.profiles.push({id,xml:t.xml});});drawAssembly();
  });
  $('assemblyRefSearch').oninput=()=>{readAssembly();renderAssignments();};
  w.onchange=e=>{if(e.target.closest('#assemblyForm')){readAssembly();if(e.target.name==='type')renderAssignments();updateAssemblyEnabled();renderAssemblyPreview();}};
}
function updateAssemblyEnabled(){
  for(const [toggle,fields] of [['blockFidEnabled','blockFidRows'],['badBoardEnabled','badBoardFields'],['badBlockEnabled','badBlockFields']]){
    $(fields).querySelectorAll('input,select').forEach(n=>n.disabled=!$(toggle).checked);
    $(fields).style.opacity=$(toggle).checked?'1':'.5';
  }
}
function renderAssignments(){
  const a=assemblyDraft,q=($('assemblyRefSearch')?.value||'').toUpperCase();
  const refs=[...new Set([...(report.points||[]).map(p=>p.ref),...Object.keys(a.assignments)])].filter(r=>r.toUpperCase().includes(q));
  const options=(rows,id)=>'<option value="0">不使用</option>'+rows.map(r=>`<option value="${r.id}" ${r.id===id?'selected':''}>${r.id} · ${esc(r.comment||fidNames[r.type]||'局部坏标记')}</option>`).join('')+(id&&!rows.some(r=>r.id===id)?`<option value="${id}" selected>${id} · 关联已失效，请重新选择</option>`:'');
  $('assignmentRows').innerHTML=refs.map(ref=>{const link=a.assignments[ref]||{};return `<tr data-ref="${esc(ref)}"><td>${esc(ref)}</td><td><select name="fid" aria-label="${esc(ref)} 基准">${options(a.local_fids.filter(r=>r.type!=='four_secondary'),link.fid)}</select></td><td><select name="bad" aria-label="${esc(ref)} 坏标记">${options(a.bad_marks.local||[],link.bad)}</select></td></tr>`;}).join('');
}
function renderAssemblyPreview(){
  const b=project.board,svg=$('assemblyPreview');if(!b.width){svg.innerHTML='';return;}
  const origin=outputOrigin(b),colors=['#4ade80','#38bdf8','#c084fc','#fb7185'];
  svg.setAttribute('viewBox',`-10 -10 ${b.width+20} ${b.height+20}`);
  const dots=assemblyDraft.repeats.map((r,i)=>{
    const theta=r.rotation*Math.PI/180,c=Math.cos(theta),s=Math.sin(theta);
    return (report.points||[]).map(p=>{const x=p.x-origin.x,y=p.y-origin.y;const px=x*c-y*s+r.x+origin.x,py=x*s+y*c+r.y+origin.y;
      return `<circle cx="${px}" cy="${b.height-py}" r="1" opacity="${r.skip?.2:1}" fill="${colors[i%colors.length]}"><title>拼板 ${i+1} · ${esc(p.ref)} (${px.toFixed(3)}, ${py.toFixed(3)})</title></circle>`;}).join('');
  }).join('');
  svg.innerHTML=`<rect width="${b.width}" height="${b.height}" fill="#0b2523" stroke="#38bdf8" stroke-width=".5"/>${dots}`;
}
// Uses the same four-corner program origin convention as the board editor.
function outputOrigin(b){return {x:b.ygx_origin_corner?.endsWith('right')?b.width:0,y:b.ygx_origin_corner?.startsWith('top')?b.height:0};}
