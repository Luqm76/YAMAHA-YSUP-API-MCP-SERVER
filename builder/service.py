import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

from . import library, tables, ygx, assembly, associations


class BuilderService:
    def __init__(self, data_dir, association_db=None):
        self.data_dir=Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True,exist_ok=True)
        self.db=self.data_dir/'projects.sqlite3'
        with self._connection() as con:
            con.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
        self.associations=associations.AssociationStore(association_db or self.data_dir/'confirmed_associations.sqlite3')

    @contextmanager
    def _connection(self):
        con=sqlite3.connect(self.db,timeout=30)
        try:
            with con:yield con
        finally:
            con.close()

    @staticmethod
    def _load(con,pid):
        row=con.execute('SELECT document FROM projects WHERE id=?',(pid,)).fetchone()
        if row is None:raise ValueError('project_not_found: 项目不存在')
        return json.loads(row[0])

    @contextmanager
    def _edit(self,pid):
        with self._connection() as con:
            con.execute('BEGIN IMMEDIATE')
            project=self._load(con,pid)
            yield project
            project['updated_at']=datetime.now(timezone.utc).isoformat()
            project['revision']+=1
            con.execute('UPDATE projects SET document=? WHERE id=?',(json.dumps(project,ensure_ascii=False),pid))

    @staticmethod
    def _name(name):
        name=str(name).strip()
        if not name or len(name)>80 or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith(('.', ' ')):
            raise ValueError('project_name: 名称为空、过长或包含文件名禁用字符')
        if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]',name,re.I):
            raise ValueError('project_name: Windows 保留文件名')
        return name

    def create_project(self,name):
        project={'schema_version':1,'id':str(uuid.uuid4()),'name':self._name(name),'revision':0,
                 'updated_at':datetime.now(timezone.utc).isoformat(),'board':{},'marks':[],
                 'tables':{},'library':[],'matches':{},'exports':[]}
        with self._connection() as con:
            con.execute('INSERT INTO projects VALUES (?,?)',(project['id'],json.dumps(project,ensure_ascii=False)))
        return project

    def get_project(self,pid):
        with self._connection() as con:return self._load(con,pid)

    def public_project(self,pid):
        project=self.get_project(pid)
        for table in project['tables'].values():table.pop('source_b64',None)
        project['library']=[{k:v for k,v in i.items() if k!='xml'} for i in project['library']]
        if project.get('ygx_template'):project['ygx_template']='imported'
        return project

    def list_projects(self):
        with self._connection() as con:
            projects=[json.loads(row[0]) for row in con.execute('SELECT document FROM projects')]
        return sorted([{'id':p['id'],'name':p['name'],'revision':p['revision'],'updated_at':p['updated_at']}
                       for p in projects],key=lambda p:p['updated_at'],reverse=True)

    def rename_project(self,pid,name):
        with self._edit(pid) as p:p['name']=self._name(name)
        return self.get_project(pid)

    def import_project(self,data):
        project=json.loads(data)
        if not isinstance(project,dict):raise ValueError('project_schema: 项目必须是对象')
        if project.get('schema_version')!=1:raise ValueError('project_version: 不支持此项目版本')
        try:self._check_snapshot(project)
        except (ValueError,TypeError,AttributeError) as exc:
            raise ValueError(f'project_schema: {exc}') from exc
        project['id']=str(uuid.uuid4());project['name']=self._name(project['name'])
        project['revision']=0
        project['updated_at']=datetime.now(timezone.utc).isoformat()
        project['exports']=[{**item,'historical':True} for item in project.get('exports',[])]
        with self._connection() as con:
            con.execute('INSERT INTO projects VALUES (?,?)',(project['id'],json.dumps(project,ensure_ascii=False)))
        return project

    @staticmethod
    def _check_snapshot(project):
        if 'assembly' in project:project['assembly']=assembly.normalize(project['assembly'])
        def check(condition,message):
            if not condition:raise ValueError(f'project_schema: {message}')
        def integer(value):return isinstance(value,int) and not isinstance(value,bool)
        for key,typ in [('board',dict),('tables',dict),('marks',list),('library',list),('matches',dict),('name',str)]:
            check(isinstance(project.get(key),typ),f'{key} 类型无效')
        board=project['board']
        if board:
            for key in ('width','height','thickness'):
                check(key in board and tables.number(board[key])>0,f'board.{key} 必须大于 0')
                board[key]=tables.number(board[key])
            check(board.get('units') in ('mm','inch','mil'),'board.units 无效')
            check(board.get('side') in ('top','bottom'),'board.side 无效')
            check(board.get('transform') in ('none','mirror_x','mirror_y','rotate_180'),'board.transform 无效')
            for key in ('offset_x','offset_y','ygx_origin_x','ygx_origin_y'):
                if key in board:board[key]=tables.number(board[key])
            BuilderService._check_board_reference(board)
            if 'ygx_origin_corner' in board:
                board['ygx_origin_x'],board['ygx_origin_y']=ygx.board_origin(board)
        check(len(project['marks']) in (0,2,3),'MARK 数量无效')
        for mark in project['marks']:
            check(isinstance(mark,dict),'MARK 必须是对象')
            check(mark.get('shape') in ('circle','rectangle','template'),'MARK 形状无效')
            for key in ('x','y','width','height'):
                check(key in mark,f'MARK 缺少 {key}')
                value=tables.number(mark[key]);check(key in ('x','y') or value>0,'MARK 尺寸无效');mark[key]=value
            root=library.parse_xml(mark.get('template_xml','').encode()) if mark['shape']=='template' else ET.parse(ygx.ASSETS/f"{mark['shape']}.xml").getroot()
            check(root.tag=='Mark' and root.find('Mark_001') is not None,'MARK XML 无效')
            for tag,key in [('Mark_200','lighting'),('Mark_100','vision')]:
                values=mark.get(key,{})
                check(isinstance(values,dict),f'MARK {key} 类型无效')
                node=root.find(tag);allowed=set(node.attrib) if node is not None else set()
                check(set(values)<=allowed,f'MARK {key} 未知字段')
                for value in values.values():check(tables.number(value)>=0,'MARK 参数不能为负')
        check(set(project['tables'])<= {'bom','cad'},'表格类型无效')
        for kind,table in project['tables'].items():
            check(isinstance(table,dict),f'{kind} 表格无效')
            for key,typ in [('rows',list),('mapping',dict),('excluded_rows',list),('filename',str),('encoding',str),('sha256',str)]:
                check(isinstance(table.get(key),typ),f'{kind}.{key} 类型无效')
            check(bool(table['rows']),f'{kind} 表格为空')
            for no,row in enumerate(table['rows']):
                check(isinstance(row,dict) and integer(row.get('id')) and row['id']==no,f'{kind} 原行号无效')
                check(isinstance(row.get('cells'),list) and all(isinstance(c,str) for c in row['cells']),f'{kind} 单元格无效')
            width=max(len(r['cells']) for r in table['rows'])
            allowed={'ref','name','spec','partno','qty','footprint'} if kind=='bom' else {'ref','x','y','rotation','side','footprint'}
            check(set(table['mapping'])<=allowed and all(integer(v) and 0<=v<width for v in table['mapping'].values()),f'{kind} 列映射无效')
            check(integer(table.get('header_row')) and -1<=table['header_row']<len(table['rows']),f'{kind} 表头无效')
            check(all(integer(v) and 0<=v<len(table['rows']) for v in table['excluded_rows']),f'{kind} 排除行无效')
        ids=set()
        for item in project['library']:
            check(isinstance(item,dict),'元件记录无效')
            check(all(isinstance(item.get(k),str) for k in ('id','name','source','source_no','xml')),'元件字段无效')
            check(bool(item['id']) and item['id'] not in ids,'元件编号重复或为空');ids.add(item['id'])
            root=library.parse_xml(item['xml'].encode())
            check(root.tag=='Part' and root.find('Part_001') is not None,'元件 XML 无效')
        check(all(isinstance(k,str) and isinstance(v,str) and v in ids for k,v in project['matches'].items()),'库匹配无效')
        check(isinstance(project.get('exports',[]),list),'导出历史无效')
        for item in project.get('exports',[]):
            check(isinstance(item,dict) and all(isinstance(item.get(k),str) for k in ('export_id','path','library_path','sha256')),'导出历史字段无效')
            check(all(integer(item.get(k)) and item[k]>=0 for k in ('mounts','parts','project_revision')),'导出历史数量无效')
        if project.get('ygx_template'):
            check(isinstance(project['ygx_template'],str),'YGX 模板无效')
            root=library.parse_xml(project['ygx_template'].encode());machine=root.find('Machine')
            check(root.tag=='PcbDataFile' and root.find('LastEditing') is not None and machine is not None,'YGX 模板结构无效')
            for path in ('Board/Board_000','Fiducial/PcbFid','Parts','Mounts','Marks','Offset/Repeat','Property'):
                check(machine.find(path) is not None,f'YGX 模板缺少 {path}')

    def set_board(self,pid,settings):
        board={'units':'mm','side':'bottom','transform':'none','offset_x':0,'offset_y':0,**settings}
        for k in ('width','height','thickness'):
            board[k]=tables.number(board.get(k,''))
            if board[k]<=0:raise ValueError(f'board_size: {k} 必须大于 0')
        for k in ('offset_x','offset_y','ygx_origin_x','ygx_origin_y'):
            if k in board:board[k]=tables.number(board[k])
        if board['units'] not in ('mm','inch','mil'):raise ValueError('units: mm/inch/mil')
        if board['transform'] not in ('none','mirror_x','mirror_y','rotate_180'):raise ValueError('transform: 不支持')
        board['side']=tables.side(board['side'])
        self._check_board_reference(board)
        if 'ygx_origin_corner' in board:
            board['ygx_origin_x'],board['ygx_origin_y']=ygx.board_origin(board)
        with self._edit(pid) as p:p['board']=board
        return board

    def set_assembly(self,pid,settings):
        checked=assembly.normalize(settings)
        with self._edit(pid) as p:p['assembly']=checked
        return checked

    def assembly_defaults(self):
        return {**assembly.normalize({}),'profiles':[
            {'id':shape,'xml':(ygx.ASSETS/f'{shape}.xml').read_text(encoding='utf-8')}
            for shape in ('circle','rectangle','bad')]}

    @staticmethod
    def _check_board_reference(board):
        for key,allowed in [('rail_reference',('front','rear')),('board_flow',('left_to_right','right_to_left')),
                            ('machine_origin_kind',('corner','hole')),('input_origin_kind',('corner','hole'))]:
            if key in board and board[key] not in allowed:raise ValueError(f'{key}: 配置无效')
        for key in ('hole_margin_x','hole_margin_y'):
            if board.get('machine_origin_kind')=='hole' or board.get('input_origin_kind')=='hole':
                board.setdefault(key,5)
            if key in board:
                board[key]=tables.number(board[key])
                size=board['width'] if key.endswith('x') else board['height']
                if not 0<=board[key]<=size/2:raise ValueError('hole_margin: 基准孔边距必须位于板内')
        if board.get('input_origin_corner'):
            ygx.corner_position(board,board['input_origin_corner'])

    def mark_defaults(self):
        result={}
        for shape in ('circle','rectangle'):
            root=ET.parse(ygx.ASSETS/f'{shape}.xml').getroot()
            result[shape]={k:dict(root.find(v).attrib) for k,v in [('lighting','Mark_200'),('vision','Mark_100')]}
        return result

    def set_marks(self,pid,marks):
        if len(marks) not in (2,3):raise ValueError('marks: 需要 2 或 3 个板基准点')
        checked=[]
        for item in marks:
            mark=dict(item)
            if mark.get('shape') not in ('circle','rectangle','template'):raise ValueError('mark_shape: 不支持')
            for k in ('x','y','width','height'):mark[k]=tables.number(mark.get(k,mark.get('width','')))
            if mark['width']<=0 or mark['height']<=0:raise ValueError('mark_size: 尺寸必须大于 0')
            if mark['shape']=='template':
                root=library.parse_xml(mark.get('template_xml','').encode())
                if root.tag!='Mark' or root.find('Mark_001') is None:raise ValueError('mark_template: 缺少完整 Mark')
            else:root=ET.parse(ygx.ASSETS/f"{mark['shape']}.xml").getroot()
            for tag,key in [('Mark_200','lighting'),('Mark_100','vision')]:
                node=root.find(tag)
                allowed=set(node.attrib) if node is not None else set()
                if set(mark.get(key,{}))-allowed:raise ValueError(f'mark_field: {key} 含未知字段')
                for field,value in mark.get(key,{}).items():
                    number=tables.number(value)
                    if number<0:raise ValueError(f'mark_field: {field} 不能为负')
            checked.append(mark)
        with self._edit(pid) as p:p['marks']=checked
        return checked

    def import_mark_templates(self,data):
        root=library.parse_xml(data)
        marks=[root] if root.tag=='Mark' else root.findall('.//Mark')
        return [{'name':m.find('Mark_001').get('MarkName',''),'xml':ET.tostring(m,encoding='unicode')}
                for m in marks if m.find('Mark_001') is not None]

    def import_ygx_template(self,pid,data):
        root=library.parse_xml(data)
        if root.tag!='PcbDataFile':raise ValueError('ygx_template: 需要 PcbDataFile')
        machine=root.find('Machine')
        for path in ('Board/Board_000','Fiducial/PcbFid','Parts','Mounts','Marks','Offset/Repeat','Property'):
            if machine is None or machine.find(path) is None:raise ValueError(f'ygx_template: 缺少 {path}')
        if root.find('LastEditing') is None:raise ValueError('ygx_template: 缺少 LastEditing')
        with self._edit(pid) as p:p['ygx_template']=ET.tostring(root,encoding='unicode')
        return dict(machine.attrib)

    def import_table(self,pid,kind,filename,data):
        if kind not in ('bom','cad'):raise ValueError('table_kind: bom/cad')
        table=tables.read_table(filename,data)
        table['sha256']=hashlib.sha256(data).hexdigest()
        table['source_b64']=base64.b64encode(data).decode()
        with self._edit(pid) as p:
            p['tables'][kind]=table
            p['matches']={}
        return table

    def configure_table(self,pid,kind,mapping,excluded_rows,header_row):
        with self._edit(pid) as p:
            if kind not in p['tables']:raise ValueError('table_missing: 请先导入表格')
            table=p['tables'][kind]
            width=max(len(r['cells']) for r in table['rows'])
            if any(not isinstance(v,int) or isinstance(v,bool) or v<0 or v>=width for v in mapping.values()):
                raise ValueError('column: 列索引超出范围')
            if not isinstance(header_row,int) or not -1<=header_row<len(table['rows']):raise ValueError('header_row: 无效')
            ids={r['id'] for r in table['rows']}
            if not set(excluded_rows)<=ids:raise ValueError('excluded_row: 行号超出范围')
            table.update(mapping=mapping,excluded_rows=sorted(set(excluded_rows)),header_row=header_row)
        return self.get_project(pid)['tables'][kind]

    def import_library(self,pid,filename,data):
        items=library.import_parts(filename,data)
        with self._edit(pid) as p:
            current={i['id']:i for i in p['library']}
            for item in items:current.setdefault(item['id'],item)
            p['library']=list(current.values())
        return {'imported':len(items),'total':len(self.list_library(pid))}

    def list_library(self,pid,query=''):
        items=self.get_project(pid)['library']
        return [{**{k:v for k,v in i.items() if k!='xml'},'summary':library.summary(i)} for i in items
                if query.casefold() in (i['name']+' '+i['source']).casefold()]

    def export_library_data(self,pid):
        project=self.get_project(pid);root=ET.Element('PartsDatabaseFile')
        ET.SubElement(root,'LastEditing',{'Date':datetime.now().strftime('%Y/%m/%d'),'Time':datetime.now().strftime('%H:%M:%S'),'VersionNo':'2'})
        for no,item in enumerate(project['library'],1):
            part=ET.fromstring(item['xml']);part.set('No',str(no));root.append(part)
        return ET.tostring(root,encoding='utf-8',xml_declaration=True)

    def get_library_part(self,pid,part_id):
        for item in self.get_project(pid)['library']:
            if item['id']==part_id:return library.details(item)
        raise ValueError('library_not_found: 元件不存在')

    def update_library(self,pid,part_id,changes):
        with self._edit(pid) as p:
            item=next((i for i in p['library'] if i['id']==part_id),None)
            if item is None:raise ValueError('library_not_found: 元件不存在')
            library.update(item,changes)
        return self.get_library_part(pid,part_id)

    def update_library_xml(self,pid,part_id,xml):
        root=library.parse_xml(xml.encode())
        if root.tag!='Part' or root.find('Part_001') is None:raise ValueError('part_xml: 缺少 Part_001')
        with self._edit(pid) as p:
            item=next((i for i in p['library'] if i['id']==part_id),None)
            if item is None:raise ValueError('library_not_found: 元件不存在')
            item['xml']=ET.tostring(root,encoding='unicode');item['name']=root.find('Part_001').get('PartsName','')
        return self.get_library_part(pid,part_id)

    def duplicate_library_part(self,pid,part_id,name):
        item=self.get_library_part(pid,part_id)
        root=ET.fromstring(item['xml']);root.find('Part_001').set('PartsName',name)
        return self.import_library(pid,name+'.xml',ET.tostring(root))

    def match_part(self,pid,group_id,part_id):
        with self._edit(pid) as p:
            if part_id is None:p['matches'].pop(group_id,None)
            else:
                if not any(i['id']==part_id for i in p['library']):raise ValueError('library_not_found: 元件不存在')
                p['matches'][group_id]=part_id
        return {'group_id':group_id,'part_id':part_id}

    def analyze(self,pid):
        return self._analyze(self.get_project(pid))

    def confirm_library_associations(self,pid,files,group_ids,namespace,reviewer,evidence,confirmed,
                                     line='',process_verified=False):
        if confirmed is not True or not reviewer.strip() or not evidence.strip():
            raise ValueError('association_confirmation: 需要明确人工确认、确认人和依据')
        if not isinstance(process_verified,bool):
            raise ValueError('association_confirmation: process_verified 必须为布尔值')
        if not namespace.strip():
            raise ValueError('association_context: 必须明确物料命名空间')
        project=self.get_project(pid)
        analysis=self._analyze(project)
        problems=[item for item in analysis['errors'] if item['code']!='unmatched']
        if problems:raise ValueError(json.dumps(problems,ensure_ascii=False))
        groups={group['id']:group for group in analysis['groups']}
        if not group_ids or any(gid not in groups for gid in group_ids):
            raise ValueError('association_group: 请指定有效的已确认物料组范围')
        snapshots=associations.capture(project,[groups[gid] for gid in dict.fromkeys(group_ids)],files,
                                       namespace,reviewer,evidence,line,process_verified)
        return self.associations.archive(snapshots)

    def query_library_associations(self,identity,context):
        return self.associations.query(identity,context)

    def list_library_associations(self,query='',include_revoked=False):
        return self.associations.list(query,include_revoked)

    def revoke_library_association(self,record_id,reason):
        return self.associations.revoke(record_id,reason)

    @staticmethod
    def _target_machine_type(project):
        root=ET.fromstring(project.get('ygx_template') or (ygx.ASSETS/'ysup_base.ygx').read_text(encoding='utf-8'))
        return root.find('Machine').get('MachineType','').strip()

    def apply_library_associations(self,pid,requests):
        results=[]
        with self._edit(pid) as project:
            groups={group['id']:group for group in self._analyze(project)['groups']}
            ids=[request.get('group_id') for request in requests]
            if len(ids)!=len(set(ids)) or any(gid not in groups for gid in ids):
                raise ValueError('association_group: 物料组不存在或重复')
            current={item['id']:item for item in project['library']}
            for request in requests:
                gid=request['group_id']
                result=self.associations.query(groups[gid],request.get('context'))
                if result['status']=='matched' and result['record']['context']['machine_type']!=self._target_machine_type(project):
                    record=result['record']
                    results.append({'group_id':gid,'status':'incompatible_template','record_id':record['id'],
                        'context':record['context'],
                        'message':'确认参数的机型与本项目输出模板不同，请先导入目标机型已验证的 YGX 模板'})
                    continue
                if result['status']=='matched' and result['record']['context']['package']=='3':
                    record=result['record']
                    results.append({'group_id':gid,'status':'needs_machine_setup','record_id':record['id'],
                        'version':record['version'],'parameter_hash':record['parameter_hash'],
                        'context':record['context'],
                        'message':'托盘快照含机台取料、载盘范围和运行状态；请在本项目重新核对示教及载盘配置，再明确关联'})
                    continue
                if result['status']=='matched':
                    record=result['record']
                    part=associations.clean_part(record['xml'])
                    xml=ET.tostring(part,encoding='unicode')
                    part_id=hashlib.sha256((record['id']+'\0'+xml).encode()).hexdigest()[:20]
                    if part_id in current and current[part_id]['xml']!=xml:
                        results.append({'group_id':gid,'status':'snapshot_modified','record_id':record['id'],
                            'part_id':part_id,'message':'项目中的历史快照已修改；请人工确认当前参数，或导入独立的确认快照'})
                        continue
                    current.setdefault(part_id,{'id':part_id,'name':part.find('Part_001').get('PartsName',''),
                        'source':'confirmed:'+record['id'],'source_no':'0','xml':xml,
                        'association_record_id':record['id'],'association_version':record['version'],
                        'association_parameter_hash':record['parameter_hash'],'association_context':record['context'],
                        'association_process_verified':record['process_verified']})
                    result={'status':'matched','part_id':part_id,'record_id':record['id'],
                            'version':record['version'],'parameter_hash':record['parameter_hash'],
                            'xml_sha256':record['xml_sha256'],'context':record['context'],
                            'process_verified':record['process_verified']}
                elif result['status']=='conflict':
                    result={'status':'conflict','record_ids':[record['id'] for record in result['records']]}
                results.append({'group_id':gid,**result})
            project['library']=list(current.values())
        return {'results':results}

    def _analyze(self,p):
        errors=[];warnings=[];points=[];groups={};excluded=[]
        def issue(code,message,**extra):return {'code':code,'message':message,**extra}
        board=p['board']
        if not board:errors.append(issue('board_missing','请设置板尺寸'))
        if len(p['marks']) not in (2,3):errors.append(issue('marks_missing','请设置 2 或 3 个 MARK'))
        for kind,required in [('bom',('ref',)),('cad',('ref','x','y','rotation'))]:
            table=p['tables'].get(kind)
            if table is None:errors.append(issue('table_missing',f'请导入 {kind}'));continue
            for field in required:
                if field not in table['mapping']:errors.append(issue('column_missing',f'{kind} 缺少 {field} 列'))
        if not board or any(e['code'] in ('table_missing','column_missing') for e in errors):
            return {'errors':errors,'warnings':warnings,'points':[],'groups':[],'excluded':[],
                    'summary':{'mounts':0,'groups':0,'matched':0,'excluded':0}}
        def active(kind):
            t=p['tables'][kind]
            return [r for r in t['rows'] if r['id']>t['header_row'] and r['id'] not in t['excluded_rows'] and any(c.strip() for c in r['cells'])]
        bom={};mapping=p['tables']['bom']['mapping']
        for row in active('bom'):
            try:
                refs=tables.references(tables.cell(row['cells'],mapping,'ref'))
                if not refs:raise ValueError('empty_ref: 位号为空')
                if 'qty' in mapping and tables.cell(row['cells'],mapping,'qty'):
                    if tables.number(tables.cell(row['cells'],mapping,'qty'))!=len(refs):
                        errors.append(issue('quantity_mismatch','BOM 数量与位号数不符',table='bom',row=row['id']))
                record={'row':row['id'],'name':tables.cell(row['cells'],mapping,'name'),
                        'spec':tables.cell(row['cells'],mapping,'spec'),'partno':tables.cell(row['cells'],mapping,'partno'),
                        'footprint':tables.cell(row['cells'],mapping,'footprint')}
                for ref in refs:
                    if ref in bom:errors.append(issue('duplicate_bom_ref',f'BOM 重复位号 {ref}',row=row['id']))
                    else:bom[ref]=record
            except ValueError as e:errors.append(issue('bom_row',str(e),table='bom',row=row['id']))
        cadmap=p['tables']['cad']['mapping'];seen=set()
        for row in active('cad'):
            cells=row['cells']
            try:
                face=tables.side(tables.cell(cells,cadmap,'side',board['side']))
                if face!=board['side']:continue
                refs=tables.references(tables.cell(cells,cadmap,'ref'))
                if len(refs)!=1:raise ValueError('cad_ref: 每个 CAD 行必须有一个位号')
                ref=refs[0]
                if ref in seen:errors.append(issue('duplicate_cad_ref',f'CAD 重复位号 {ref}',row=row['id']));continue
                seen.add(ref)
                if ref not in bom:excluded.append({'ref':ref,'row':row['id'],'reason':'不在 BOM 中'});continue
                x,y,angle=[tables.number(tables.cell(cells,cadmap,k)) for k in ('x','y','rotation')]
                x,y,angle=ygx.transform_point(x,y,angle,board)
                if 'assembly' not in p and not (0<=x<=board['width'] and 0<=y<=board['height']):
                    errors.append(issue('outside_board',f'{ref} 超出板框',row=row['id'],x=x,y=y))
                record=bom[ref]
                footprint=tables.cell(cells,cadmap,'footprint',record['footprint'])
                signature=json.dumps([record['row'],record['name'],record['spec'],record['partno'],footprint],ensure_ascii=False)
                gid=hashlib.sha256(signature.encode()).hexdigest()[:16]
                if gid not in groups:
                    groups[gid]={'id':gid,**record,'footprint':footprint,'refs':[],
                                 'program_name':f"B{record['row']:04d}_{gid[:6]}"}
                groups[gid]['refs'].append(ref)
                points.append({'ref':ref,'x':x,'y':y,'rotation':angle,'group_id':gid,'source_row':row['id']})
            except ValueError as e:errors.append(issue('cad_row',str(e),table='cad',row=row['id']))
        if not points:errors.append(issue('empty_program','没有可贴装点'))
        lib={i['id']:i for i in p['library']}
        matched=0
        for group in groups.values():
            part_id=p['matches'].get(group['id']);group['part_id']=part_id
            group['candidates']=self._candidates(group,p['library'])
            if part_id not in lib:
                errors.append(issue('unmatched',f"{group['program_name']} 尚未匹配元件库",group_id=group['id']));continue
            matched+=1
            part=ET.fromstring(lib[part_id]['xml']);group['library_name']=lib[part_id]['name']
            item=lib[part_id]
            if item.get('association_record_id'):
                group['association']={'record_id':item['association_record_id'],'version':item['association_version'],
                    'parameter_hash':item['association_parameter_hash'],'context':item.get('association_context'),
                    'process_verified':item.get('association_process_verified',False)}
                scope=item.get('association_context') or {}
                if scope.get('machine_type')!=self._target_machine_type(p):
                    errors.append(issue('association_context','历史确认参数机型与当前输出模板不一致',group_id=group['id']))
                complete=all(part.find(tag) is not None for tag in ('Part_001','Part_002','Part_003'))
                group['association']['modified']=not complete or associations.parameter_hash(item['xml'])!=item['association_parameter_hash']
                if group['association']['modified']:group['association']['process_verified']=False
            for tag in ('Part_001','Part_002','Part_003','Part_080'):
                if part.find(tag) is None:errors.append(issue('part_field',f'{lib[part_id]["name"]} 缺少 {tag}',group_id=group['id']))
            body=next((node for node in part if all(k in node.attrib for k in ('BodyX','BodyY','BodyZ'))),None)
            feeder=part.find('Part_003')
            try:
                if body is None or any(tables.number(body.get(k,''))<=0 for k in ('BodyX','BodyY','BodyZ')):
                    errors.append(issue('part_size','元件长宽高需完整且大于 0',group_id=group['id']))
                supply=part.find('Part_002')
                if supply is not None and supply.get('CarrierTape')=='1' and (feeder is None or
                    (tables.number(feeder.get('FdrIdxStep','0'))<=0 and tables.number(feeder.get('PitchEffect','0'))<=0)):
                    errors.append(issue('feeder_pitch','带式送料缺少有效间距',group_id=group['id']))
            except ValueError as e:errors.append(issue('part_number',str(e),group_id=group['id']))
        coords=set()
        for i,mark in enumerate(p['marks'],1):
            x,y,_=ygx.transform_point(mark['x'],mark['y'],0,board)
            rx=mark['width']/2;ry=(mark['width'] if mark['shape']=='circle' else mark['height'])/2
            if not (rx<=x<=board['width']-rx and ry<=y<=board['height']-ry):
                errors.append(issue('mark_outside_board',f'MARK{i} 图形超出板框'))
            if (x,y) in coords:errors.append(issue('duplicate_mark','MARK 坐标重复'))
            coords.add((x,y))
        missing=sorted(set(bom)-seen)
        if missing:warnings.append(issue('bom_without_selected_cad',f'{len(missing)} 个 BOM 位号不在所选面 CAD 中',refs=missing))
        if excluded:warnings.append(issue('excluded_not_in_bom',f'{len(excluded)} 个 CAD 位号不在 BOM，已排除'))
        if 'assembly' in p:
            config=assembly.normalize(p['assembly']);origin=ygx.output_origin_position(board)
            errors.extend(assembly.analyze(config,board,points,origin))
            warnings.extend(assembly.warnings(config,points,origin))
        return {'errors':errors,'warnings':warnings,'groups':list(groups.values()),'points':points,'excluded':excluded,
                'summary':{'mounts':len(points),'groups':len(groups),'matched':matched,'excluded':len(excluded)}}

    @staticmethod
    def _candidates(group,items):
        exact={group['partno'],group['name'],group['spec'],group['footprint']}-{''}
        result=[{'id':i['id'],'name':i['name'],'reason':'名称精确候选（需确认）'} for i in items if i['name'] in exact]
        names={'SR0603':['R1608','R1608-0.45H'],'RC0603':['R1608','R1608-0.45H'],
               'SC0603':['C1608'],'SR0805':['R2125'],'SC0805':['C2125_t0.6'],
               'SR1206':['R3216'],'SC1210':['C3225'],'SC1808':['C4520'],'SC1812':['C4532']}
        candidates=names.get(group['footprint'].upper(),[])
        prefix='R' if group['footprint'].upper().startswith(('SR','RC')) else 'C'
        if all(r.startswith(prefix) for r in group['refs']):
            result.extend({'id':i['id'],'name':i['name'],'reason':'封装尺寸候选（高度/工艺需确认）'}
                          for i in items if i['name'] in candidates and i['name'] not in exact)
        return result

    def export_ygx(self,pid):
        # Hold database transaction through generation so UI and MCP cannot mix revisions.
        with self._edit(pid) as p:
            analysis=self._analyze(p)
            if analysis['errors']:raise ValueError(json.dumps(analysis['errors'],ensure_ascii=False))
            folder=self.data_dir/pid/'exports'/uuid.uuid4().hex[:12]
            folder.mkdir(parents=True)
            path,libpath=ygx.build(p,analysis,folder)
            manifest={'project_id':pid,'project_revision':p['revision'],'path':str(path),'library_path':str(libpath),
                      'mounts':len(analysis['points']),'parts':len(analysis['groups']),
                      'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'export_id':folder.name}
            evidence={**manifest,'board':p['board'],'marks':p['marks'],'assembly':p.get('assembly',{}),'material_mapping':analysis['groups'],
                      'inputs':{k:{'filename':v['filename'],'sha256':v['sha256'],'mapping':v['mapping'],
                                  'excluded_rows':v['excluded_rows'],'header_row':v['header_row']} for k,v in p['tables'].items()}}
            (folder/'manifest.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            p['exports'].append(manifest)
        return manifest
