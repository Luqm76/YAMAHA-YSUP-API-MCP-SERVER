import copy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import xml.etree.ElementTree as ET

from .library import clone_part
from . import assembly

ASSETS=Path(__file__).resolve().parent.parent/'assets'


def corner_position(board,corner,kind='corner',margin_x=5,margin_y=5):
    if corner not in ('bottom_left','bottom_right','top_left','top_right'):
        raise ValueError('origin_corner: 原点位置无效')
    if kind not in ('corner','hole'):raise ValueError('origin_kind: corner/hole')
    dx,dy=(margin_x,margin_y) if kind=='hole' else (0,0)
    return (dx if corner.endswith('left') else board['width']-dx,
            board['height']-dy if corner.startswith('top') else dy)


def output_origin_position(board):
    corner=board.get('ygx_origin_corner','custom')
    return (0,0) if corner=='custom' else corner_position(board,corner)


def board_origin(board):
    # Mount XY is relative to program origin; Board_000 origin is relative to locate datum.
    if board.get('ygx_origin_corner','custom')=='custom':
        return board.get('ygx_origin_x',-board['width']),board.get('ygx_origin_y',0)
    origin=output_origin_position(board)
    corner=('bottom' if board.get('rail_reference','front')=='front' else 'top')+'_'+('right' if board.get('board_flow','left_to_right')=='left_to_right' else 'left')
    datum=corner_position(board,corner,board.get('machine_origin_kind','corner'),
                          board.get('hole_margin_x',5),board.get('hole_margin_y',5))
    return origin[0]-datum[0],origin[1]-datum[1]


def transform_point(x,y,angle,board):
    factor={'mm':1,'inch':25.4,'mil':0.0254}[board.get('units','mm')]
    x,y=x*factor-board.get('offset_x',0),y*factor-board.get('offset_y',0)
    if board.get('input_origin_corner'):
        ox,oy=corner_position(board,board['input_origin_corner'],board.get('input_origin_kind','corner'),
                              board.get('hole_margin_x',5),board.get('hole_margin_y',5))
        x+=ox;y+=oy
    mode=board.get('transform','none')
    if mode in ('mirror_x','rotate_180'):x=board['width']-x
    if mode in ('mirror_y','rotate_180'):y=board['height']-y
    if mode=='mirror_x':angle=180-angle
    if mode=='mirror_y':angle=-angle
    if mode=='rotate_180':angle+=180
    return tuple(float(Decimal(str(v)).quantize(Decimal('0.001'),rounding=ROUND_HALF_UP)) for v in (x,y,angle%360))


def build(project,analysis,folder):
    root=ET.fromstring(project.get('ygx_template') or (ASSETS/'ysup_base.ygx').read_text(encoding='utf-8'))
    machine=root.find('Machine')
    if machine is None:raise ValueError('template: 缺少 Machine')
    board=project['board']
    origin_x,origin_y=board_origin(board)
    point_origin_x,point_origin_y=output_origin_position(board)
    pcb=machine.find('Board/Board_000')
    for k,v in {'SizeX':board['width'],'SizeY':board['height'],'SizeZ':board['thickness'],
                'OriginX':origin_x,'OriginY':origin_y,'BlockCount':0}.items():
        pcb.set(k,f'{v:.3f}')
    now=datetime.now()
    editing=root.find('LastEditing')
    editing.set('Date',now.strftime('%Y/%m/%d'));editing.set('Time',now.strftime('%H:%M:%S'))
    prop=machine.find('Property')
    prop.set('LastEditingDate',now.strftime('%Y/%m/%d'));prop.set('LastEditingTime',now.strftime('%H:%M:%S'))
    # Preserve template enum values, clear historical placement and auxiliary commands.
    for path in ('Programs/Program/Commands','Programs/Program/LocalPoints','Programs/Program/Watches',
                 'GlobalPoints','PreDispenses','DotDispenses','PosCorDispenses'):
        node=machine.find(path)
        if node is not None:node.clear()
    parts=machine.find('Parts');parts.clear()
    mounts=machine.find('Mounts');mounts.clear()
    material_root=ET.Element('PartsDatabaseFile')
    library={i['id']:i for i in project['library']}
    for no,group in enumerate(analysis['groups'],1):
        item=library[project['matches'][group['id']]]
        part=clone_part(item,no,group['program_name'])
        parts.append(part);material_root.append(copy.deepcopy(part))
        group['comp_no']=no
    groups={g['id']:g for g in analysis['groups']}
    mount_template=ET.parse(ASSETS/'mount.xml').getroot()
    for no,point in enumerate(analysis['points'],1):
        mount=copy.deepcopy(mount_template)
        mount.set('No',str(no));mount.set('Comp',str(groups[point['group_id']]['comp_no']))
        for key,field in [('X','x'),('Y','y'),('R','rotation')]:mount.set(key,f'{point[field]:.3f}')
        mount.set('X',f"{point['x']-point_origin_x:.3f}");mount.set('Y',f"{point['y']-point_origin_y:.3f}")
        for key,value in {'Comment':point['ref'],'Group':'0','GroupID':'0','GrpOrder':'0','SeqOrder':'-1',
                          'Head':'1','Nozzle':'0','Opt':'101','Opt2':'1','Fid':'0','Bad':'0','Exec':'0'}.items():mount.set(key,value)
        mounts.append(mount)
    marks=machine.find('Marks');marks.clear()
    fid=machine.find('Fiducial/PcbFid')
    for i in range(1,4):
        for key in ('X','Y'):fid.set(f'{key}{i}','0.000')
        fid.set(f'Mark{i}','0')
    fid.set('Fid3','1' if len(project['marks'])==3 else '0')
    for no,setting in enumerate(project['marks'],1):
        mark=ET.fromstring(setting['template_xml']) if setting.get('template_xml') else ET.parse(ASSETS/f"{setting['shape']}.xml").getroot()
        mark.set('No',str(no))
        identity=mark.find('Mark_001')
        identity.set('MarkName',f'MARK_{no}');identity.set('DatabaseNo','0');identity.set('LibraryUse','0')
        size=mark.find('Mark_011')
        if size is not None:size.set('OutSize',f"{setting['width']:.3f}")
        size=mark.find('Mark_020')
        if size is not None:
            size.set('OutSizeX',f"{setting['width']:.3f}");size.set('OutSizeY',f"{setting['height']:.3f}")
        for tag,key in [('Mark_200','lighting'),('Mark_100','vision')]:
            node=mark.find(tag)
            for k,v in setting.get(key,{}).items():node.set(k,str(v))
        marks.append(mark)
        x,y,_=transform_point(setting['x'],setting['y'],0,board)
        x-=point_origin_x;y-=point_origin_y
        fid.set(f'X{no}',f'{x:.3f}');fid.set(f'Y{no}',f'{y:.3f}');fid.set(f'Mark{no}',str(no))
    assembly.emit(machine,assembly.normalize(project.get('assembly',{})),len(project['marks']))
    path=folder/f"{project['name']}.ygx"
    ET.indent(root,space='\t');ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
    library_path=folder/f"{project['name']}.fdx"
    ET.indent(material_root,space='\t');ET.ElementTree(material_root).write(library_path,encoding='utf-8',xml_declaration=True)
    return path,library_path
