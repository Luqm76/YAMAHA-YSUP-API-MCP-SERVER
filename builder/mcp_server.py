"""Real MCP transports; project state is shared with the local REST application."""
import argparse
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .config import data_dir, association_db, optimizer_paths
from .optimizer import OptimizerService
from .service import BuilderService


def create_mcp(folder=None,port=8766):
    service=BuilderService(folder or data_dir(),association_db=association_db(folder))
    optimizer=OptimizerService(*optimizer_paths(folder))
    mcp=FastMCP('Yamaha Program Builder',host='127.0.0.1',port=port,
                instructions='本机离线编程工具。先设置板及 MARK，再导入/整理 BOM 和 CAD，明确确认库匹配，校验后生成未优化 YGX。人工修改保存后可另行调用线体优化工具；须查询任务 succeeded 与点一致性，优化不等于工艺确认。尺寸单位 mm。不要猜测缺失工艺参数。')

    def read(path):
        p=Path(path).expanduser()
        if not p.is_file():raise ValueError('file_not_found: '+str(p))
        if p.stat().st_size>40_000_000:raise ValueError('file_size: 文件超过 40MB')
        return p.name,p.read_bytes()

    def call(function,*args):
        try:return function(*args)
        except (ValueError,OSError) as exc:
            text=str(exc)
            try:
                errors=json.loads(text)
                if not isinstance(errors,list):raise ValueError()
            except (ValueError,TypeError):
                code,_,message=text.partition(':')
                errors=[{'code':code,'message':message.strip() or text}]
            raise ToolError(json.dumps({'errors':errors},ensure_ascii=False)) from exc

    @mcp.tool()
    def list_optimization_lines():
        """读取本机 YSUP 已配置线体、机台顺序及已保存 .ygs 优化设置；不修改正式目录。"""
        return call(optimizer.list_lines)

    @mcp.tool()
    def start_line_optimization(file_path:str,line:str,settings_name:str,request_id:str):
        """对最终保存的 YGX 启动隔离线体优化。line/settings_name 必须来自 list_optimization_lines；request_id 唯一，同内容重复请求复用任务。返回 job_id 后调用 get_line_optimization，不能把 queued/running 当作成功。"""
        return call(optimizer.start,file_path,line,settings_name,request_id)

    @mcp.tool()
    def get_line_optimization(job_id:str):
        """查询持久优化任务。仅 status=succeeded 且 mounts_identical=true 可交付 outputs；failed/interrupted 返回原生报告和错误，不自动重试。优化结果仍须工艺/机台验证。"""
        return call(optimizer.get,job_id)

    @mcp.tool()
    def create_project(name:str):
        """建立编程项目，返回 project_id（id）。"""
        return call(service.create_project,name)

    @mcp.tool()
    def list_projects():
        """列出本机已保存项目。"""
        return service.list_projects()

    @mcp.tool()
    def get_project(project_id:str):
        """取得板/MARK/原表/列映射/库/匹配和项目版本。"""
        return call(service.public_project,project_id)

    @mcp.tool()
    def rename_project(project_id:str,name:str):
        """修改程序名称；名称用作 YGX 文件名。"""
        return call(service.rename_project,project_id,name)

    @mcp.tool()
    def set_board(project_id:str,settings:dict):
        """板宽 width、高 height、厚 thickness 为 mm；side=top/bottom；输入坐标 units=mm/inch/mil，transform=none/mirror_x/mirror_y/rotate_180；offset_x/y 为 mm。"""
        return call(service.set_board,project_id,settings)

    @mcp.tool()
    def get_mark_defaults():
        """读取已验证模板的原始光源和视觉字段，避免猜测枚举。"""
        return service.mark_defaults()

    @mcp.tool()
    def set_marks(project_id:str,marks:list[dict]):
        """设置 2/3 个 MARK：x/y 为输入坐标，width/height 为 mm，shape=circle/rectangle/template；lighting 和 vision 可用字段见 get_mark_defaults。"""
        return call(service.set_marks,project_id,marks)

    @mcp.tool()
    def get_assembly_defaults():
        """取得拼板默认结构和完整圆形/矩形/坏板 Mark XML。坏板示例来自已保存的 YSUP 测试程序，光学参数需按工艺设置。"""
        return service.assembly_defaults()

    @mcp.tool()
    def set_assembly(project_id:str,settings:dict):
        """配置 repeats(x/y/rotation/skip)、profiles(id/xml)、block_fid、local_fids(id/type/marks)、bad_marks(board/block/local)、assignments(位号:{fid,bad})。辅助坐标为程序原点 mm；point 为贴装中心偏移。type=local/point/four_main/four_secondary；四点主从相邻，贴装关联主编号。板尺寸为整板尺寸，不复制基础贴装点。"""
        return call(service.set_assembly,project_id,settings)

    @mcp.tool()
    def import_mark_templates(file_path:str):
        """从本机 YGX/XML 取得完整 MARK 模板，供 shape=template 使用。"""
        def run():return service.import_mark_templates(read(file_path)[1])
        return call(run)

    @mcp.tool()
    def import_table(project_id:str,kind:str,file_path:str):
        """导入本机 BOM/CAD 文件，kind=bom/cad，返回稳定行号和建议列绑定。重新导入清除旧匹配。"""
        def run():return service.import_table(project_id,kind,*read(file_path))
        return call(run)

    @mcp.tool()
    def configure_table(project_id:str,kind:str,mapping:dict[str,int],excluded_rows:list[int],header_row:int):
        """列编号和行号均从 0 开始。BOM ref 必需，name/spec/partno/qty/footprint 可选；CAD ref/x/y/rotation 必需，side/footprint 可选。header_row=-1 表示无表头。"""
        return call(service.configure_table,project_id,kind,mapping,excluded_rows,header_row)

    @mcp.tool()
    def import_library(project_id:str,file_path:str):
        """从 ZIP/FDX/YGX/XML 导入完整元件参数至项目副本。"""
        def run():return service.import_library(project_id,*read(file_path))
        return call(run)

    @mcp.tool()
    def save_library(project_id:str,file_path:str):
        """将项目完整元件库保存为原生 FDX，保留未编辑及嵌套参数。写入调用方明确提供的本机路径。"""
        def run():
            path=Path(file_path).expanduser();path.write_bytes(service.export_library_data(project_id))
            return {'path':str(path.resolve())}
        return call(run)

    @mcp.tool()
    def list_library(project_id:str,query:str=''):
        """按名称或来源检索，保留同名不同来源记录。"""
        return call(service.list_library,project_id,query)

    @mcp.tool()
    def get_library_part(project_id:str,part_id:str):
        """读取全部已保存 XML 字段和嵌套 XML。"""
        return call(service.get_library_part,project_id,part_id)

    @mcp.tool()
    def update_library_part(project_id:str,part_id:str,changes:dict):
        """按真实节点/属性编辑参数，例如 {Part_013:{BodyZ:0.45}}；不会修改正式 YSUP 库。"""
        return call(service.update_library,project_id,part_id,changes)

    @mcp.tool()
    def update_library_xml(project_id:str,part_id:str,xml:str):
        """保存完整 Part XML，保留嵌套视觉/照明等字段。"""
        return call(service.update_library_xml,project_id,part_id,xml)

    @mcp.tool()
    def duplicate_library_part(project_id:str,part_id:str,name:str):
        """复制现有元件参数，创建独立元件记录。"""
        return call(service.duplicate_library_part,project_id,part_id,name)

    @mcp.tool()
    def match_part(project_id:str,group_id:str,part_id:str|None=None):
        """明确确认物料和元件库记录的关联；part_id=null 取消。不同物料不因同封装被合并。"""
        return call(service.match_part,project_id,group_id,part_id)

    @mcp.tool()
    def confirm_library_associations(project_id:str,file_paths:list[str],group_ids:list[str],
                                     namespace:str,reviewer:str,evidence:str,confirmed:bool,
                                     line:str='',process_verified:bool=False):
        """人工确认并保存后归档明确的物料组。读取最终 YGX 的完整 Part，按位号对应；托盘需 line。confirmed 必须来自人工明确决定，保存/优化不等于确认。"""
        def run():
            files=[]
            for raw in file_paths:
                path=Path(raw).expanduser().resolve()
                before=path.stat()
                data=read(str(path))[1]
                after=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                    raise ValueError('association_source_changed: 读取期间文件发生变化，请重新保存并重试')
                files.append((str(path),data))
            return service.confirm_library_associations(project_id,files,group_ids,namespace,reviewer,
                                                        evidence,confirmed,line,process_verified)
        return call(run)

    @mcp.tool()
    def query_library_associations(identity:dict,context:dict):
        """精确查询人工确认库。identity=name/spec/partno/footprint；context=namespace/machine_type/package/feeder_type/carrier_tape，托盘额外 line/machine。返回 matched/not_found/conflict。"""
        return call(service.query_library_associations,identity,context)

    @mcp.tool()
    def list_library_associations(query:str='',include_revoked:bool=False):
        """列出确认记录及完整快照/来源/版本。默认有效记录；include_revoked 保留撤销历史。"""
        return call(service.list_library_associations,query,include_revoked)

    @mcp.tool()
    def apply_library_associations(project_id:str,requests:list[dict]):
        """requests=[{group_id,context}]；唯一适用且机型一致的非托盘快照导入项目并清旧位置，仍需 match_part。冲突、模板机型不符、已编辑快照和托盘机台配置均转人工。"""
        return call(service.apply_library_associations,project_id,requests)

    @mcp.tool()
    def revoke_library_association(record_id:str,reason:str):
        """明确撤销错误/过期确认记录并保存原因和历史，不删除原快照。"""
        return call(service.revoke_library_association,record_id,reason)

    @mcp.tool()
    def import_ygx_template(project_id:str,file_path:str):
        """导入已可用 YGX 作为程序结构/机型模板；生成时替换板信息、物料和贴装点。"""
        def run():return service.import_ygx_template(project_id,read(file_path)[1])
        return call(run)

    @mcp.tool()
    def analyze_project(project_id:str):
        """合并、预览并返回 errors/warnings/候选库/贴装点。errors 未清零不能导出。"""
        return call(service.analyze,project_id)

    @mcp.tool()
    def export_ygx(project_id:str):
        """校验后生成未优化 YGX、本项目 FDX 和清单，返回绝对路径与 SHA256。"""
        return call(service.export_ygx,project_id)

    @mcp.tool()
    def save_project(project_id:str,file_path:str):
        """将完整项目快照写入指定本机 JSON 文件，含原始表及修改。"""
        def run():
            p=service.get_project(project_id)
            path=Path(file_path).expanduser().resolve()
            path.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
            return {'path':str(path),'revision':p['revision']}
        return call(run)

    @mcp.tool()
    def load_project(file_path:str):
        """导入完整项目快照为新项目。"""
        def run():return service.import_project(read(file_path)[1])
        return call(run)

    return mcp


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--transport',choices=['stdio','streamable-http'],default='stdio')
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args()
    create_mcp(port=args.port).run(transport=args.transport)
