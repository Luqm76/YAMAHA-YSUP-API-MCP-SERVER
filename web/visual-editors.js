'use strict';
const cornerNames={top_left:'左上',top_right:'右上',bottom_left:'左下',bottom_right:'右下'};
function formCornerPosition(corner,hole=false){
  const f=$('boardForm').elements,w=Number(f.width.value)||0,h=Number(f.height.value)||0;
  const mx=hole?Number(f.hole_margin_x.value):0,my=hole?Number(f.hole_margin_y.value):0;
  return [corner.endsWith('left')?mx:w-mx,corner.startsWith('top')?h-my:my];
}
function formMachineDatum(){
  const f=$('boardForm').elements;
  const corner=(f.rail_reference.value==='front'?'bottom':'top')+'_'+(f.board_flow.value==='left_to_right'?'right':'left');
  return {corner,position:formCornerPosition(corner,f.machine_origin_kind.value==='hole')};
}
function updateBoardEditor(){
  const f=$('boardForm').elements,corner=f.ygx_origin_corner.value,datum=formMachineDatum();
  if(corner!=='custom'){
    const p=formCornerPosition(corner);f.ygx_origin_x.value=p[0]-datum.position[0];f.ygx_origin_y.value=p[1]-datum.position[1];
  }
  $('originPicker').querySelectorAll('[data-origin]').forEach(b=>{
    const selected=b.dataset.origin===corner;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));
    b.classList.toggle('datum',b.dataset.origin===datum.corner);
  });
  $('originBoardSize').textContent=`${f.width.value||'—'} × ${f.height.value||'—'} mm`;
  $('originSummary').textContent=`程序原点：${cornerNames[corner]||'自定义'}\n机台基准：${cornerNames[datum.corner]}${f.machine_origin_kind.value==='hole'?'基准孔':'板角'}\n传板：${f.board_flow.value==='left_to_right'?'左 → 右':'右 → 左'}\nYGX X = ${f.ygx_origin_x.value||0}，Y = ${f.ygx_origin_y.value||0} mm`;
  $('originAdvanced').open=corner==='custom';
}
function renderBoardEditor(){
  const f=$('boardForm').elements,b=project.board;
  if(!b.width){
    f.ygx_origin_corner.value='bottom_left';
  }else if(!b.ygx_origin_corner){
    const x=b.ygx_origin_x??-(b.width||0),y=b.ygx_origin_y??0;
    const datum=formMachineDatum();
    f.ygx_origin_corner.value=Object.keys(cornerNames).find(c=>{const p=formCornerPosition(c);return p[0]-datum.position[0]===x&&p[1]-datum.position[1]===y;})||'custom';
  }
  updateBoardEditor();
}
$('originPicker').onclick=e=>{const button=e.target.closest('[data-origin]');if(button){$('boardForm').elements.ygx_origin_corner.value=button.dataset.origin;updateBoardEditor();}};
$('boardForm').addEventListener('input',e=>{
  if(['ygx_origin_x','ygx_origin_y'].includes(e.target.name))$('boardForm').elements.ygx_origin_corner.value='custom';
  updateBoardEditor();
});
$('boardForm').addEventListener('change',updateBoardEditor);

const diagramLabels={StdChip:'标准芯片',SmallChip:'小型芯片',SOP:'SOP',SOJ:'SOJ',QFP:'QFP',PLCC:'PLCC',BGA:'BGA',SimpleBGA:'简单 BGA',MiniTr:'小型三极管 / SOT',Cylinder:'圆柱形',MelfChip:'MELF',Con:'连接器',ConE:'单侧连接器',ConNSEW:'四侧连接器',Special:'特殊外形',SpChip:'特殊芯片'};
let diagramCatalog=[];
fetch('images/ysup/catalog.json').then(r=>r.json()).then(items=>{diagramCatalog=items;if(editingPart&&$('partDialog').open)renderPartDiagram();}).catch(()=>{});
function bodyFields(){return Object.entries(editingPart.fields).find(([,a])=>['BodyX','BodyY','BodyZ'].every(k=>k in a));}
function focusDimension(attr){
  const body=bodyFields();if(!body)return;
  const input=$('partFields').querySelector(`[data-tag="${body[0]}"][data-attr="${attr}"]`);
  if(input){input.closest('details').open=true;input.scrollIntoView({block:'center',behavior:'smooth'});input.focus();input.select();}
}
function livePartDimensions(){
  const body=bodyFields(),box=$('partDimensions');if(!body||!box)return;
  const values=Object.fromEntries(['BodyX','BodyY','BodyZ'].map(k=>[k,$('partFields').querySelector(`[data-tag="${body[0]}"][data-attr="${k}"]`)?.value??body[1][k]]));
  const x=Number(values.BodyX),y=Number(values.BodyY),z=Number(values.BodyZ);
  if(![x,y,z].every(v=>Number.isFinite(v)&&v>0)){box.innerHTML='<p class="warn">请填写有效的本体 X / Y / Z 尺寸。</p>';return;}
  const scale=Math.min(180/x,145/y),w=x*scale,h=y*scale,left=(260-w)/2,top=(210-h)/2;
  box.innerHTML=`<svg viewBox="0 0 310 260" role="img" aria-label="元件本体尺寸示意"><defs><marker id="dimensionArrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 Z" fill="#38bdf8"/></marker></defs><rect x="${left}" y="${top}" width="${w}" height="${h}" rx="3" fill="#1d4d57" stroke="#67e8f9"/><path d="M${left},${top+h+18}H${left+w} M${left+w+18},${top}V${top+h}" stroke="#38bdf8" marker-start="url(#dimensionArrow)" marker-end="url(#dimensionArrow)"/><text x="130" y="${top+h+37}" text-anchor="middle" fill="#bae6fd">A · X ${esc(values.BodyX.trim())} mm</text><text x="${left+w+32}" y="${top+h/2}" text-anchor="middle" transform="rotate(-90 ${left+w+32} ${top+h/2})" fill="#bae6fd">B · Y ${esc(values.BodyY.trim())} mm</text><text x="130" y="248" text-anchor="middle" fill="#bae6fd">C · Z ${esc(values.BodyZ.trim())} mm</text></svg>`;
}
function renderPartDiagram(){
  const name=editingPart.name.toUpperCase();
  const guess=/BGA|CSP/.test(name)?'BGA':/QFP|LQFP|TQFP/.test(name)?'QFP':/SOJ/.test(name)?'SOJ':/SOP|SOIC|SSOP/.test(name)?'SOP':editingPart.fields.Part_002?.ShapeType==='7'?'StdChip':'';
  $('partDiagram').innerHTML=`<h3>元件参数图示</h3><div class="part-visual-grid"><div><label>YSUP 原始参考图<select id="partDiagramChoice"><option value="">通用尺寸示意</option>${diagramCatalog.map(d=>`<option value="${esc(d.id)}" ${d.id===guess?'selected':''}>${esc(diagramLabels[d.id]||d.id)}</option>`).join('')}</select></label><figure id="partReferenceImage"></figure><p class="muted">参考图可手动切换，仅用于查看；不修改元件形状或视觉参数。</p></div><div><div id="partDimensions"></div><div class="dimension-buttons"><button type="button" class="btn ghost" data-dimension="BodyX">A · 本体 X</button><button type="button" class="btn ghost" data-dimension="BodyY">B · 本体 Y</button><button type="button" class="btn ghost" data-dimension="BodyZ">C · 高度 Z</button></div><p class="muted">尺寸图随输入更新；引脚布局请按左侧原图与具体参数核对。</p></div></div>`;
  function reference(){const item=diagramCatalog.find(d=>d.id===$('partDiagramChoice').value);$('partReferenceImage').innerHTML=item?`<img src="images/ysup/${esc(item.file)}" alt="YSUP ${esc(diagramLabels[item.id]||item.id)} 参数尺寸图">`:'<p class="muted">通用图只显示本体尺寸。可选择左侧参考图查看相应外形。</p>';}
  $('partDiagramChoice').onchange=reference;reference();livePartDimensions();
  $('partDiagram').querySelectorAll('[data-dimension]').forEach(b=>b.onclick=()=>focusDimension(b.dataset.dimension));
  $('partFields').oninput=livePartDimensions;
}
