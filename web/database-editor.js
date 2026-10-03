'use strict';
let dbPart=null,dbVocabulary=null,dbDiagramCatalog=null,dbDirty=false,dbView='recognition',dbPage=0,dbGroup=null;
const dbFieldNames={PartsName:'元件名',Comment:'备注',ShapeType:'校正类型',Package:'供料形态',FdrType:'送料器类型',CarrierTape:'料带种类',ReelDiameter:'卷盘直径（原值）',Nozzle:'所用吸嘴',
BodyX:'本体 X / mm',BodyY:'本体 Y / mm',BodyZ:'元件高度 / mm',MoldX:'塑封本体 X / mm',MoldY:'塑封本体 Y / mm',MoldZ:'塑封高度 / mm',Thicknesschk:'厚度检查（原值）',
LeadNumN:'N / S 侧引脚根数',LeadNumE:'E / W 侧引脚根数',LeadNumS:'S 侧引脚根数',LeadNumW:'W 侧引脚根数',LeadPitch:'引脚间距 / mm',LeadPitchE:'E 侧引脚间距 / mm',LeadWidth:'引脚宽度 / mm',LeadWidthE:'E 侧引脚宽度 / mm',LeadLength:'反光引脚长 / mm',LeadLengthE:'E 侧引脚长度 / mm',RlrOffset:'检查线偏移（原值）',RlrOffsetE:'E 侧检查线偏移（原值）',RlrWidth:'检查线宽度',RlrWidthE:'E 侧检查线宽度',BumpMask:'缓冲垫屏蔽（原值）',
BgaAmount:'焊球总数',BgaDotNumN:'焊球列数',BgaDotNumE:'焊球行数',BgaPitch:'焊球间距 / mm',BgaDiameter:'焊球直径 / mm',
FdrIdxStep:'送料步距（原值）',PitchEffect:'有效送料间距 / mm',FdrIdxSpeed:'走带速度（原值）',FdrIdxSpeedEx:'扩展走带速度（原值）',FeederTimerOffset:'送料延时补偿',TapeEndDetection:'料带尾部检测（原值）',FeederKnotSkip:'接料跳过（原值）',FeederKnotSpeed:'接料速度（原值）',Setno:'站位编号',FdrAngle:'供料角度（原值）',FixCmp:'固定分料（原值）',XPos:'供料 X / mm',YPos:'供料 Y / mm',
TrayXSize:'托盘排列数量 X',TrayYSize:'托盘排列数量 Y',TrayXpt:'托盘排列间距 X / mm',TrayYpt:'托盘排列间距 Y / mm',TrayXiSize:'元件个数 X',TrayYiSize:'元件个数 Y',TrayXipt:'元件间距 X / mm',TrayYipt:'元件间距 Y / mm',TrayThickness:'托盘厚度 / mm',TrayMaxThickness:'托盘最大厚度（原始 Z / mm）',TrayPickDir:'托盘吸取方向（原值）',CountStp:'计数停止（原值）',
Alignment:'识别校正方式（原值）',AutoThreshold:'自动阈值（原值）',Threshold:'识别阈值',Tolerance:'识别容差',SearchArea:'搜索范围 / mm',DatumAngle:'基准角度（原值）',OffsetRec:'偏移识别（原值）',RecognitionOffsetZ:'识别 Z 偏移 / mm',LightSetting:'光源设置（原值）',LightLevel:'光源等级',LightLaser:'激光光源',LightMode:'光源模式（原值）',MainLightLevel:'主光源',CoaxsLightLevel:'同轴光源',SideLightLevel:'侧光源',LaserLightLevel:'激光等级',
XYSpeed:'XY 移动速度（原值）',ConvYSpeed:'Y 轴传送速度（原值）',RotaryRoundSpeed:'旋转速度（原值）',VacChk:'真空检查（原值）',CorrectPos:'位置修正（原值）',Retry:'重试次数（原值）',Action:'贴装动作（原值）',HighAccMode:'高精度模式（原值）',PckTimer:'吸取停留时间（原值）',PckSpeed:'吸取速度（原值）',PckVLevel:'吸取真空等级',PckSingleDir:'吸取单方向（原值）',PckCtrlDown:'吸取下降控制（原值）',PckCtrlUp:'吸取上升控制（原值）',NozzleTouchHeight:'吸嘴接触高度 / mm',
MntHeight:'贴装高度 / mm',MntTimer:'贴装停留时间（原值）',MntSpeed:'贴装速度（原值）',MntPLevel:'贴装压力等级',MntSingleDir:'贴装单方向（原值）',MntCtrlDown:'贴装下降控制（原值）',MntCtrlUp:'贴装上升控制（原值）',MntInsertLength:'插入长度 / mm',MntInsertShortDistance:'插入短行程 / mm',FreeSpace1:'自由区 1',FreeSpace2:'自由区 2',
PackSizeX:'载带腔体 X / mm',PackSizeY:'载带腔体 Y / mm',PackOffsetX:'腔体偏移 X / mm',PackOffsetY:'腔体偏移 Y / mm',PolMark:'极性标记（原值）',PolMarkPos:'极性标记位置（原值）'};
function dbControl(tag,key,value){
  const dictionaries={ShapeType:'shapes',Package:'packages',FdrType:'feeders',CarrierTape:'tapes',Nozzle:'nozzles'},name=dictionaries[key],dict=dbVocabulary[name];
  const attrs=`data-tag="${esc(tag)}" data-attr="${esc(key)}" aria-label="${esc(dbFieldNames[key]||key)}"`;
  if(name){
    const current=String(value).trim(),known=Object.hasOwn(dict,current);
    return `<select ${attrs} ${key==='ShapeType'?'disabled title="校正类型决定原生参数结构；更换类型请复制对应元件模板"':''}>${Object.entries(dict).map(([v,label])=>`<option value="${esc(v)}" ${v===current?'selected':''}>${esc(label)}</option>`).join('')}${known?'':`<option value="${esc(current)}" selected>未核对编号 ${esc(current)}</option>`}</select>`;
  }
  const shown=tag==='Part_100'&&key==='TrayThickness'?-Number(value):String(value).trim();
  return `<input ${attrs} value="${esc(shown)}" ${['PartsName','Comment','FreeSpace1','FreeSpace2'].includes(key)?'':'inputmode="decimal"'}>`;
}
function dbParamTable(tags,title,extra=false){
  const rows=tags.flatMap(tag=>Object.entries(dbPart.fields[tag]||{}).filter(([key])=>extra?!dbFieldNames[key]:!!dbFieldNames[key]).map(([key,value])=>
    `<tr><th title="${esc(tag+'.'+key)}">${esc(dbFieldNames[key]||key)}</th><td>${dbControl(tag,key,value)}</td></tr>`)).join('');
  return rows?`<section class="db-section"><h3>${esc(title)}</h3><table class="db-params"><tbody>${rows}</tbody></table></section>`:'';
}
function dbReadChanges(){
  const changes={};if(!dbPart)return changes;
  $('databaseFields').querySelectorAll('[data-tag]:not(:disabled)').forEach(i=>{
    const tag=i.dataset.tag,key=i.dataset.attr,old=String(dbPart.fields[tag][key]).trim();
    let value=i.value;if(tag==='Part_100'&&key==='TrayThickness'){value=String(-Number(value));if(Number(value)===Number(old))return;}
    if(value!==old){changes[tag]??={};changes[tag][key]=value;}
  });return changes;
}
async function dbSelect(id){
  if(dbDirty){toast('当前元件有未保存修改，请先保存或撤销。');return;}
  dbPart=await api(path(`/library/${id}`));editingPart=dbPart;
  dbRenderList();dbRenderDetails();
}
function dbRenderList(){
  const q=$('databaseSearch').value.toLowerCase(),source=$('databaseSource').value;
  const filtered=lib.filter(p=>(!source||p.source===source)&&(p.name+' '+p.source+' '+(p.summary?.comment||'')).toLowerCase().includes(q));
  dbPage=Math.min(dbPage,Math.max(0,Math.ceil(filtered.length/200)-1));
  $('databaseRows').innerHTML=filtered.slice(dbPage*200,(dbPage+1)*200).map(p=>{
    const s=p.summary||{};return `<tr tabindex="0" data-db-part="${esc(p.id)}" class="${dbPart?.id===p.id?'selected':''}" aria-selected="${dbPart?.id===p.id}"><td>${esc(p.source_no)}</td><td title="${esc(p.source)}">${esc(p.name)}</td><td>${esc(s.comment)}</td><td>${esc(s.shape)}</td><td>${esc(s.package)}</td><td>${esc(s.feeder)}</td><td>${esc(s.tape)}</td><td>${esc(s.nozzle)}</td><td>${esc(s.body_x??'—')} × ${esc(s.body_y??'—')} × ${esc(s.body_z??'—')}</td></tr>`;
  }).join('');
  $('databaseCount').textContent=`${filtered.length} 条元件 · 第 ${dbPage+1} / ${Math.max(1,Math.ceil(filtered.length/200))} 页`;
  $('databasePrev').disabled=dbPage===0;$('databaseNext').disabled=(dbPage+1)*200>=filtered.length;
  $('databaseRows').querySelectorAll('[data-db-part]').forEach(row=>{
    row.onclick=run(()=>dbSelect(row.dataset.dbPart));row.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();row.click();}};
  });
}
function dbRenderDetails(){
  const empty=!dbPart;
  for(const id of ['databaseSave','databaseUndo','databaseCopy','databaseApply'])$(id).disabled=empty;
  if(empty){$('databaseFields').innerHTML='<p class="db-empty">选择上方元件，查看尺寸、供料、识别与贴装参数。</p>';$('databaseImage').innerHTML='';$('databaseReference').innerHTML='';$('databaseMeta').textContent='';return;}
  const all=Object.keys(dbPart.fields),shape=all.filter(t=>/^Part_0[1-6]\d$/.test(t)),recognition=all.filter(t=>/^Part_07\d$/.test(t));
  $('databaseFields').innerHTML=`<div class="db-columns"><div>${dbParamTable(['Part_001','Part_002'],'基本信息')}${dbParamTable(shape,'元件形状 · 本体与引脚')}${dbParamTable(recognition,'识别 · 光源与搜索')}</div><div>${dbParamTable(['Part_003','Part_100'],'供料 · 送料与托盘')}${dbParamTable(['Part_080','Part_082'],'吸取 · 吸嘴与动作')}${dbParamTable(['Part_083'],'贴装 · 高度与动作')}</div></div>
    <details class="db-expand"><summary>机器控制与扩展参数</summary><div class="db-columns">${all.filter(t=>!['Part_001','Part_002','Part_003','Part_004',...shape,...recognition,'Part_080','Part_082','Part_083','Part_100'].includes(t)).map(t=>dbParamTable([t],`扩展组 ${t}`)).join('')}</div></details>
    <details class="db-expand"><summary>其他 · 自由区与未核对字段</summary>${dbParamTable(['Part_004'],'自由区')}${all.filter(t=>!['Part_004'].includes(t)).map(t=>dbParamTable([t],t,true)).join('')}</details>
    <details class="db-expand"><summary>完整原生 XML（高级）</summary><p class="muted">保留嵌套参数；日常编辑使用上方中文参数表。</p><textarea class="db-xml" id="databaseXml" spellcheck="false">${esc(dbPart.xml)}</textarea><button type="button" id="databaseSaveXml">保存完整 XML</button></details>`;
  $('databaseFields').oninput=()=>{dbDirty=Object.keys(dbReadChanges()).length>0||$('databaseXml').value!==dbPart.xml;dbSetStatus();};
  $('databaseFields').onchange=$('databaseFields').oninput;
  $('databaseSaveXml').onclick=run(async()=>{
    if(Object.keys(dbReadChanges()).length)throw new Error('请先保存或撤销参数表修改，再编辑完整 XML。');
    dbPart=await api(path(`/library/${dbPart.id}`),'PUT',{xml:$('databaseXml').value});dbDirty=false;await refresh();dbRenderList();dbRenderDetails();
  });
  const diagramId=dbVocabulary.diagrams[dbPart.fields.Part_002?.ShapeType?.trim()];
  const diagram=dbDiagramCatalog.find(d=>d.id===diagramId);
  $('databaseReference').innerHTML=diagram?`<img src="images/ysup/${esc(diagram.file)}" alt="YSUP ${esc(dbVocabulary.shapes[dbPart.fields.Part_002.ShapeType.trim()])} 元件尺寸原图">`:'<p class="db-empty">此校正类型暂无已提取原图；完整参数仍可编辑。</p>';
  $('databaseMeta').textContent=`来源：${dbPart.source} · 原编号 ${dbPart.source_no}`;
  dbRenderImage();dbSetStatus();
}
function dbSetStatus(){
  $('databaseStatus').classList.toggle('db-dirty',dbDirty);
  $('databaseStatus').textContent=dbPart?`${dbPart.name} · ${dbDirty?'有未保存修改':'参数已保存到项目'}`:'请导入库或选择元件';
}
function dbRenderImage(){
  if(!dbPart)return;
  document.querySelectorAll('[data-db-view]').forEach(b=>b.classList.toggle('active',b.dataset.dbView===dbView));
  const shape=dbPart.fields.Part_002?.ShapeType?.trim(),diagram=dbDiagramCatalog.find(d=>d.id===dbVocabulary.diagrams[shape]);
  if(dbView==='recognition'){
    $('databaseImage').innerHTML=diagram?`<img src="images/ysup/${esc(diagram.file)}" alt="${esc(dbVocabulary.shapes[shape])} 识别尺寸参考图">`:'<p class="db-empty">暂无该类型原始图示</p>';
  }else{
    const fields=dbView==='supply'?['Part_002','Part_100']:['Part_080','Part_082','Part_083'];
    $('databaseImage').innerHTML=dbParamTable(fields,dbView==='supply'?'供料参数摘要':'吸取与贴装摘要').replaceAll('<input ','<input readonly ').replaceAll('<select ','<select disabled ');
  }
}
async function openDatabase(id=null,gid=null){
  requireProject();dbVocabulary??=await api('/library-vocabulary');dbDiagramCatalog??=await (await fetch('images/ysup/catalog.json')).json();
  if($('databaseDialog').open){if(id)await dbSelect(id);return;}
  dbPart=null;dbDirty=false;dbPage=0;dbGroup=gid;dbView='recognition';
  $('databaseSearch').value='';$('databaseSource').innerHTML='<option value="">全部库文件</option>'+[...new Set(lib.map(p=>p.source))].map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');
  $('databaseApply').hidden=!gid;$('databaseDownload').href='/api'+path('/library-export');$('databaseDownload').download=project.name+'.fdx';
  $('databaseHeading').textContent=`${project.name} — 元件数据库`;
  dbRenderList();dbRenderDetails();dbSetStatus();$('databaseDialog').showModal();
  if(id||lib.length)await dbSelect(id||lib[0].id);
}
function dbClose(){if(dbDirty){toast('请先保存或撤销当前元件修改。');return;}$('databaseDialog').close();if($('libraryDialog').open)renderChoices();}
$('databaseClose').onclick=dbClose;$('databaseDialog').oncancel=e=>{e.preventDefault();dbClose();};
$('databaseSearch').oninput=()=>{dbPage=0;dbRenderList();};$('databaseSource').onchange=()=>{dbPage=0;dbRenderList();};
$('databasePrev').onclick=()=>{dbPage--;dbRenderList();};$('databaseNext').onclick=()=>{dbPage++;dbRenderList();};
$('databaseUndo').onclick=()=>{dbDirty=false;dbRenderDetails();};
$('databaseSave').onclick=run(async()=>{
  if(!dbPart)return;if($('databaseXml').value!==dbPart.xml)throw new Error('完整 XML 有修改，请使用“保存完整 XML”或撤销修改。');dbPart=await api(path(`/library/${dbPart.id}`),'PUT',{changes:dbReadChanges()});
  dbDirty=false;await refresh();dbRenderList();dbRenderDetails();toast('元件参数已保存');
});
$('databaseCopy').onclick=run(async()=>{
  if(dbDirty)throw new Error('请先保存或撤销当前修改，再复制元件。');
  const name=prompt('复制为新元件名称',dbPart.name+'_copy');if(!name)return;
  await api(path(`/library/${dbPart.id}/duplicate`),'POST',{name});await refresh();
  await dbSelect(lib.findLast(p=>p.name===name).id);
});
$('databaseImport').onchange=run(async e=>{
  if(dbDirty)throw new Error('请先保存或撤销当前元件修改，再打开库。');
  await upload(path('/library'),e.target.files[0]);await refresh();e.target.value='';
  $('databaseSource').innerHTML='<option value="">全部库文件</option>'+[...new Set(lib.map(p=>p.source))].map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');
  dbRenderList();if(!dbPart&&lib.length)await dbSelect(lib[0].id);
});
$('databaseApply').onclick=run(async()=>{if(dbDirty)throw new Error('请先保存当前修改。');await api(path(`/matches/${dbGroup}`),'PUT',{part_id:dbPart.id});dbClose();if($('libraryDialog').open)$('libraryDialog').close();await refresh();});
document.querySelectorAll('[data-db-view]').forEach(b=>b.onclick=()=>{dbView=b.dataset.dbView;dbRenderImage();});
// Route existing browse/edit entry points into the native-style workbench.
const previousOpenLibrary=openLibrary;
openLibrary=function(gid){if(gid)return previousOpenLibrary(gid);run(()=>openDatabase())();};
openPart=async function(id){await openDatabase(id,$('libraryDialog').open?selectedGroup:null);};
run(async()=>{if(new URLSearchParams(location.search).get('database')==='1'){await openDatabase(lib.find(p=>p.name==='sample_QFP100-P0.65')?.id);}})();
