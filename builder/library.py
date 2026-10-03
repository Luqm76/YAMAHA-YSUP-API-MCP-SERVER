import copy
import hashlib
import io
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from . import library_schema as schema


def parse_xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('xml_entity: 不支持含 DTD 的 XML')
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        # Some old FDX declares UTF-8 but actually contains GBK comments.
        try:
            text=data.decode('gb18030')
            return ET.fromstring(text)
        except (UnicodeError,ET.ParseError) as exc:
            raise ValueError(f'xml_invalid: {exc}') from exc


def import_parts(filename,data):
    documents=[]
    if Path(filename).suffix.lower()=='.zip':
        with ZipFile(io.BytesIO(data)) as z:
            total=0
            for info in z.infolist():
                if Path(info.filename).suffix.lower() in ('.fdx','.ygx','.xml'):
                    total+=info.file_size
                    if info.file_size>40_000_000 or total>100_000_000:
                        raise ValueError('library_size: 单库文件过大')
                    documents.append((info.filename,z.read(info)))
    else:
        documents=[(Path(filename).name,data)]
    items=[]
    for name,content in documents:
        root=parse_xml(content)
        parts=[root] if root.tag=='Part' else root.findall('.//Part')
        for index,part in enumerate(parts):
            identity=part.find('Part_001')
            if identity is None:continue
            key=hashlib.sha256((name+'\0'+str(index)+'\0'+ET.tostring(part,encoding='unicode')).encode()).hexdigest()[:20]
            items.append({'id':key,'source':name,'source_no':part.get('No','').strip(),
                          'name':identity.get('PartsName',''),'xml':ET.tostring(part,encoding='unicode')})
    if not items:raise ValueError('empty_library: 未找到含 Part_001 的元件参数')
    return items


def details(item):
    part=ET.fromstring(item['xml'])
    result={k:v for k,v in item.items() if k!='xml'}
    result['fields']={node.tag:dict(node.attrib) for node in part if node.attrib}
    result['xml']=item['xml']
    return result


def summary(item):
    part=ET.fromstring(item['xml'])
    def attrs(tag):
        node=part.find(tag);return node.attrib if node is not None else {}
    identity=attrs('Part_001');kind=attrs('Part_002');mount=attrs('Part_080')
    body=next((n.attrib for n in part if all(k in n.attrib for k in ('BodyX','BodyY','BodyZ'))),{})
    result={'comment':identity.get('Comment',''),
            'shape':schema.label(schema.SHAPES,kind.get('ShapeType')),
            'package':schema.label(schema.PACKAGES,kind.get('Package')),
            'feeder':schema.label(schema.FEEDERS,kind.get('FdrType')),
            'tape':schema.label(schema.TAPES,kind.get('CarrierTape')),
            'nozzle':schema.label(schema.NOZZLES,mount.get('Nozzle'))}
    for key in ('x','y','z'):
        value=body.get('Body'+key.upper(),'')
        try:result['body_'+key]=float(value)
        except ValueError:result['body_'+key]=None
    return result


def update(item,changes):
    part=ET.fromstring(item['xml'])
    for tag,attrs in changes.items():
        node=part.find(tag)
        if node is None:raise ValueError(f'unknown_field: {tag}')
        for key,value in attrs.items():
            if key not in node.attrib:raise ValueError(f'unknown_field: {tag}.{key}')
            node.set(key,str(value))
    item['xml']=ET.tostring(part,encoding='unicode')
    item['name']=part.find('Part_001').get('PartsName','')


def clone_part(item,no,name):
    part=copy.deepcopy(ET.fromstring(item['xml']))
    part.attrib.clear()
    part.set('No',str(no))
    identity=part.find('Part_001')
    identity.set('PartsName',name)
    for key in ('DatabaseNo','LibraryUse','LibraryFolder'):identity.set(key,'0')
    identity.set('LibraryPath','')
    feeder=part.find('Part_003')
    resets={'Setno':'0','XPos':'-999.999','YPos':'-999.999','FixCmp':'0'}
    # Tray position calculation must retain the library's teaching mode.
    if part.find('Part_002').get('Package')!='3':resets['Definition']='0'
    for key,value in resets.items():
        if key in feeder.attrib:feeder.set(key,value)
    return part
