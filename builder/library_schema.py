"""Presentation vocabulary grounded in native Models enums and DATABASE.FDX examples."""
SHAPES={0:'未设置',1:'MELF',2:'特殊片式',3:'小型晶体管',4:'SOP',5:'QFP',6:'PLCC',7:'标准片式元件',
        8:'两端电极',9:'功率晶体管',10:'圆柱形',11:'裸芯片',12:'特殊外形',13:'简易BGA',14:'异形元件',
        15:'SOJ',16:'单侧连接器',17:'四侧连接器',18:'偏置引脚',19:'标记',20:'四边电极',21:'重心校正',
        22:'不校正',23:'倒装芯片',24:'特殊连接器',25:'BGA',26:'小型片式',27:'吸嘴',28:'标准倒装芯片',
        29:'SEM',30:'特殊类型 Toku'}
PACKAGES={0:'带式',1:'管式',2:'散料',3:'托盘式'}
# These particular IDs/names are paired in the user screenshot and native sample records.
FEEDERS={0:'8mm带式',4:'16mm压纹载带',12:'固定托盘送料器'}
TAPES={0:'8mm带式'}
NOZZLES={1:'1608芯片用',17:'QFP 20mm用',18:'QFP 30mm用',21:'SOP 10mm用'}
DIAGRAMS={1:'MelfChip',2:'SpChip',3:'MiniTr',4:'SOP',5:'QFP',6:'PLCC',7:'StdChip',8:'2Ends',9:'P-Tr',
          10:'Cylinder',11:'BareChip',12:'Special',13:'SimpleBGA',14:'OddChip',15:'SOJ',16:'ConE',17:'ConNSEW',
          18:'OffLead',19:'AsMark',20:'SpQuad',21:'Gravity',23:'FlipChip',24:'OddCon',25:'BGA',26:'SmallChip'}


def label(mapping,value):
    try:number=int(value)
    except (ValueError,TypeError):return '未设置' if value in (None,'') else f'未核对编号 {value}'
    return mapping.get(number,f'未核对编号 {number}')
