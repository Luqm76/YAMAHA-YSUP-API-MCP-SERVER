"""Explicit program-coordinate assembly data; no machine or optical enum guessing."""
import copy
import math
import xml.etree.ElementTree as ET

from . import library, tables

TYPES={'local':0,'point':1,'four_main':2,'four_secondary':3}


def normalize(settings):
    if not isinstance(settings,dict):raise ValueError('assembly: 必须为对象')
    allowed={'repeats','profiles','block_fid','local_fids','bad_marks','assignments'}
    if set(settings)-allowed:raise ValueError('assembly: 未知配置字段')
    data=copy.deepcopy(settings)
    defaults={'repeats':[{'x':0,'y':0,'rotation':0}], 'profiles':[], 'block_fid':[],
              'local_fids':[], 'bad_marks':{}, 'assignments':{}}
    for key,value in defaults.items():data.setdefault(key,value)
    for key in ('repeats','profiles','block_fid','local_fids'):
        if not isinstance(data[key],list):raise ValueError(f'assembly: {key} 必须为列表')
    if not isinstance(data['bad_marks'],dict) or not isinstance(data['assignments'],dict):
        raise ValueError('assembly: bad_marks/assignments 必须为对象')
    if not data['repeats']:raise ValueError('assembly_repeat: 至少一个拼板偏移')

    def obj(item,keys):
        if not isinstance(item,dict) or set(item)-set(keys):raise ValueError('assembly: 行类型或字段无效')
        for value in item.values():
            if isinstance(value,str) and any(not (ch in '\t\n\r' or '\x20'<=ch<='\ud7ff' or '\ue000'<=ch<='\ufffd' or '\U00010000'<=ch<='\U0010ffff') for ch in value):
                raise ValueError('assembly: 文本含 XML 不支持的字符')

    def xy(item):
        for key in ('x','y'):item[key]=tables.number(item.get(key,''))

    def ident(item,seen):
        value=item.get('id')
        if isinstance(value,bool) or not isinstance(value,int) or value<1 or value in seen:
            raise ValueError('assembly_id: 编号必须为不重复的正整数')
        seen.add(value)

    for row in data['repeats']:
        obj(row,('x','y','rotation','skip','comment'));xy(row)
        row['rotation']=tables.number(row.get('rotation',0))%360
        row.setdefault('skip',False)
        if not isinstance(row['skip'],bool):raise ValueError('assembly_skip: skip 必须为布尔值')
        if not isinstance(row.get('comment',''),str):raise ValueError('assembly: comment 必须为文本')
    profiles={}
    for row in data['profiles']:
        obj(row,('id','xml'))
        if not isinstance(row.get('id'),str) or not row['id'] or row['id'] in profiles:
            raise ValueError('assembly_profile: 模板编号重复或为空')
        if not isinstance(row.get('xml'),str):raise ValueError('assembly_profile: 需要完整 Mark XML')
        root=library.parse_xml(row['xml'].encode())
        if root.tag!='Mark' or root.find('Mark_001') is None:
            raise ValueError('assembly_profile: 缺少完整 Mark XML')
        bad=root.find('Mark_050') is not None
        if bad:
            required=('Mark_050','Mark_110','Mark_201')
            fields={'Mark_050':('MarkType','SearchAreaX','SearchAreaY'),
                    'Mark_110':('Surface','Threshold'),
                    'Mark_201':('LightingOuter','LightingInner','LightingDrop','LightingIROuter','LightingIRInner')}
            if root.find('Mark_050').get('MarkType','').strip()!='2':raise ValueError('assembly_profile: 坏标记 MarkType 必须为 2')
        else:
            required=('Mark_100','Mark_200')
            shape=next((n for n in root if n.tag in ('Mark_011','Mark_020')),None)
            if shape is None or shape.get('MarkType','').strip()!='1':
                raise ValueError('assembly_profile: 辅助基准目前支持已核对的圆形/矩形模板')
            expected='0' if shape.tag=='Mark_011' else '1'
            if shape.get('Shape','').strip()!=expected or shape.get('Exec','').strip() not in ('0','1'):
                raise ValueError('assembly_profile: 形状或 Exec 字段无效')
            fields={'Mark_100':('Surface','Threshold','Tolerance','SearchAreaX','SearchAreaY','Sequence'),
                    'Mark_200':('LightingOuter','LightingInner','LightingDrop','LightingIROuter','LightingIRInner','FilterInner','FilterOuter'),
                    shape.tag:('OutSize',) if shape.tag=='Mark_011' else ('OutSizeX','OutSizeY')}
        if any(root.find(tag) is None for tag in required):raise ValueError('assembly_profile: 模板缺少视觉/照明参数')
        if any(root.find(tag) is None or any(key not in root.find(tag).attrib for key in keys) for tag,keys in fields.items()):
            raise ValueError('assembly_profile: 模板缺少形状/视觉/照明字段')
        for tag in ('Mark_011','Mark_020','Mark_050','Mark_100','Mark_110','Mark_200','Mark_201'):
            node=root.find(tag)
            if node is None:continue
            for key,value in node.attrib.items():
                try:number=tables.number(value)
                except ValueError as exc:raise ValueError(f'assembly_profile: {tag}.{key} 数值无效') from exc
                if number<0 or (key in ('OutSize','OutSizeX','OutSizeY','SearchAreaX','SearchAreaY') and number==0):
                    raise ValueError(f'assembly_profile: {tag}.{key} 必须非负，尺寸/搜索区域必须大于 0')
        profiles[row['id']]=bad

    def mark(row,bad=False):
        xy(row)
        if not isinstance(row.get('profile'),str) or row['profile'] not in profiles or profiles[row['profile']]!=bad:
            raise ValueError('assembly_profile: 标记引用不存在或类型不符')

    def pair(rows):
        if not isinstance(rows,list) or len(rows) not in (2,3):raise ValueError('assembly_marks: 需要 2/3 个基准点')
        for row in rows:obj(row,('x','y','profile'));mark(row)
        if len({(float(f"{r['x']:.3f}"),float(f"{r['y']:.3f}")) for r in rows})!=len(rows):
            raise ValueError('assembly_marks: 基准点坐标在输出精度下重复')

    if data['block_fid']:pair(data['block_fid'])
    ids=set()
    for row in data['local_fids']:
        obj(row,('id','type','marks','comment'));ident(row,ids)
        if not isinstance(row.get('type'),str) or row['type'] not in TYPES:raise ValueError('assembly_type: 未知基准类型')
        if not isinstance(row.get('comment',''),str):raise ValueError('assembly: comment 必须为文本')
        pair(row.get('marks'))
        if row['type'].startswith('four_') and len(row['marks'])!=2:raise ValueError('assembly_pair: 四点基准每行两个点')
    rows=data['local_fids']
    if [r['id'] for r in rows]!=list(range(1,len(rows)+1)):
        raise ValueError('assembly_id: 局部基准编号需从 1 连续递增')
    for i,row in enumerate(rows):
        if row['type']=='four_main' and (i+1==len(rows) or rows[i+1]['type']!='four_secondary'):
            raise ValueError('assembly_pair: 四点主基准后需紧邻从基准')
        if row['type']=='four_secondary' and (i==0 or rows[i-1]['type']!='four_main'):
            raise ValueError('assembly_pair: 四点从基准前需紧邻主基准')
        if row['type']=='four_main':
            coords={(float(f"{m['x']:.3f}"),float(f"{m['y']:.3f}")) for r in rows[i:i+2] for m in r['marks']}
            if len(coords)!=4:raise ValueError('assembly_pair: 四点基准需要四个不同坐标')
    bad=data['bad_marks']
    if set(bad)-{'board','block','local'}:raise ValueError('assembly_bad: 未知坏板标记类型')
    for key in ('board','block'):
        if key in bad:
            obj(bad[key],('x','y','profile'));mark(bad[key],True)
    bad.setdefault('local',[])
    if not isinstance(bad['local'],list):raise ValueError('assembly_bad: local 必须为列表')
    badids=set()
    for row in bad['local']:
        obj(row,('id','x','y','profile','comment'));ident(row,badids);mark(row,True)
        if not isinstance(row.get('comment',''),str):raise ValueError('assembly: comment 必须为文本')
    if [r['id'] for r in bad['local']]!=list(range(1,len(bad['local'])+1)):
        raise ValueError('assembly_id: 局部坏板编号需从 1 连续递增')
    if (data['block_fid'] or bad.get('block')) and len(data['repeats'])<2:
        raise ValueError('assembly_repeat: 块标记需要多块拼板偏移')
    secondary={r['id'] for r in rows if r['type']=='four_secondary'}
    for ref,link in data['assignments'].items():
        if not isinstance(ref,str) or not ref:raise ValueError('assembly_ref: 位号为空')
        obj({'comment':ref},('comment',))
        obj(link,('fid','bad'))
        for key,valid in [('fid',ids-secondary),('bad',badids)]:
            value=link.get(key,0)
            if isinstance(value,bool) or not isinstance(value,int) or value not in valid|{0}:
                raise ValueError('assembly_link: 标记关联编号无效（四点关联主基准）')
    return data


def analyze(data,board,points,origin):
    errors=[]
    def error(code,message):errors.append({'code':code,'message':message})
    refs={p['ref'] for p in points}
    for ref in data['assignments']:
        if ref not in refs:error('assembly_ref',f'标记关联位号 {ref} 不在所选面贴装点中')
    for i,repeat in enumerate(data['repeats'],1):
        if repeat['skip']:continue
        angle=math.radians(repeat['rotation']);c,s=math.cos(angle),math.sin(angle)
        for p in points:
            x,y=p['x']-origin[0],p['y']-origin[1]
            x,y=x*c-y*s+repeat['x']+origin[0],x*s+y*c+repeat['y']+origin[1]
            if not (-.001<=x<=board['width']+.001 and -.001<=y<=board['height']+.001):
                error('assembly_outside',f'拼板 {i} 的 {p["ref"]} 超出整板尺寸');break
    if all(r['skip'] for r in data['repeats']):error('assembly_empty','全部拼板均已跳过')
    def check_marks(marks,label,repeated=True):
        for repeat in data['repeats'] if repeated else [{'x':0,'y':0,'rotation':0,'skip':False}]:
            if repeat['skip']:continue
            theta=math.radians(repeat['rotation']);c,s=math.cos(theta),math.sin(theta)
            for mark in marks:
                x=mark['x']*c-mark['y']*s+repeat['x']+origin[0]
                y=mark['x']*s+mark['y']*c+repeat['y']+origin[1]
                if not (0<=x<=board['width'] and 0<=y<=board['height']):
                    error('assembly_mark_outside',f'{label} 中心超出整板尺寸');return
    check_marks(data['block_fid'],'块基准')
    for row in data['local_fids']:
        if row['type']!='point':check_marks(row['marks'],f'局部基准 {row["id"]}')
        elif any(math.hypot(m['x'],m['y'])>math.hypot(board['width'],board['height']) for m in row['marks']):
            # A relative displacement longer than the board diagonal cannot fit at any mounting angle.
            error('assembly_mark_outside',f'点基准 {row["id"]} 偏移超过整板对角线')
    for key in ('board','block'):
        if data['bad_marks'].get(key):check_marks([data['bad_marks'][key]],f'{key} 坏标记',key=='block')
    check_marks(data['bad_marks']['local'],'局部坏标记')
    return errors


def warnings(data,points,origin):
    result=[];rows={r['id']:r for r in data['local_fids']}
    def contains(polygon,x,y):
        inside=False
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            ax,ay=a['x'],a['y'];bx,by=b['x'],b['y']
            cross=(x-ax)*(by-ay)-(y-ay)*(bx-ax)
            if abs(cross)<1e-7 and min(ax,bx)<=x<=max(ax,bx) and min(ay,by)<=y<=max(ay,by):return True
            if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:inside=not inside
        return inside
    for point in points:
        no=data['assignments'].get(point['ref'],{}).get('fid',0)
        row=rows.get(no)
        if row is None or row['type']!='four_main':continue
        polygon=row['marks']+list(reversed(rows[no+1]['marks']))
        if not contains(polygon,point['x']-origin[0],point['y']-origin[1]):
            result.append({'code':'four_fid_region','message':f'四点基准 {no} 未包围关联元件 {point["ref"]}；请核对坐标，此类测试样例曾导致 YSUP 优化失败'})
    return result


def emit(machine,data,global_count):
    offset=machine.find('Offset');offset.clear()
    for no,row in enumerate(data['repeats'],1):
        ET.SubElement(offset,'Repeat',{'No':str(no),'X':f"{row['x']:.3f}",'Y':f"{row['y']:.3f}",
                      'R':f"{row['rotation']:.3f}",'Exec':'1' if row['skip'] else '0',
                      'Comment':row.get('comment',''),'OrgBlk':'0','UnitNo':'0'})
    numbers={}
    for no,row in enumerate(data['profiles'],global_count+1):
        numbers[row['id']]=str(no);root=ET.fromstring(row['xml']);root.set('No',str(no))
        root.find('Mark_001').set('LibraryUse','0');machine.find('Marks').append(root)
    fid=machine.find('Fiducial')
    for node in list(fid):
        if node.tag in ('BlkFid','LclFid'):fid.remove(node)
    use=fid.find('FidUse')
    if use is None:use=ET.SubElement(fid,'FidUse')
    use.attrib.update(Pcb='0',Blk='0' if data['block_fid'] else '1',Local='0' if data['local_fids'] else '1')

    def fid_attrs(rows):
        attrs={f'{k}{i}':'0' for i in range(1,4) for k in ('X','Y','Mark')}
        attrs['Fid3']='1' if len(rows)==3 else '0'
        for i,row in enumerate(rows,1):
            attrs[f'X{i}']=f"{row['x']:.3f}";attrs[f'Y{i}']=f"{row['y']:.3f}"
            attrs[f'Mark{i}']='0' if i==2 and row['profile']==rows[0]['profile'] else numbers[row['profile']]
        return attrs
    ET.SubElement(fid,'BlkFid',fid_attrs(data['block_fid']))
    for row in data['local_fids']:
        ET.SubElement(fid,'LclFid',{**fid_attrs(row['marks']),'No':str(row['id']),
                      'Type':str(TYPES[row['type']]),'Skip':'0','OrgBlk':'0','Comment':row.get('comment','')})
    bad=machine.find('BadMark')
    if bad is None:bad=ET.SubElement(machine,'BadMark')
    bad.clear();settings=data['bad_marks']
    ET.SubElement(bad,'BadUse',{'Pcb':'0' if settings.get('board') else '1',
                  'Blk':'0' if settings.get('block') else '1','Local':'0' if settings['local'] else '1'})
    for key,tag in [('board','PcbBad'),('block','BlkBad')]:
        row=settings.get(key)
        ET.SubElement(bad,tag,{'X':f"{row['x']:.3f}" if row else '0.000',
                      'Y':f"{row['y']:.3f}" if row else '0.000','Mark':numbers[row['profile']] if row else '0'})
    for row in settings['local']:
        ET.SubElement(bad,'LclBad',{'No':str(row['id']),'X':f"{row['x']:.3f}",'Y':f"{row['y']:.3f}",
                      'Mark':numbers[row['profile']],'Skip':'0','OrgBlk':'0','View':'-1','Comment':row.get('comment','')})
    if settings.get('board') or settings.get('block') or settings['local']:
        node=machine.find('Board/Board_102')
        if node is None:raise ValueError('assembly_template: 缺少 Board_102')
        node.set('PrePick','1')
    for mount in machine.findall('Mounts/Mount'):
        link=data['assignments'].get(mount.get('Comment'),{})
        mount.set('Fid',str(link.get('fid',0)));mount.set('Bad',str(link.get('bad',0)))
        mount.set('OrgBlk','1' if len(data['repeats'])>1 else '0')
