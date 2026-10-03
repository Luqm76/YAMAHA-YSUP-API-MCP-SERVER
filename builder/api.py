from pathlib import Path
import json

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import data_dir, association_db
from .service import BuilderService


def create_app(folder=None):
    service=BuilderService(folder or data_dir(),association_db=association_db(folder))
    app=FastAPI(title='Yamaha Program Builder API',version='0.1.0')
    app.state.service=service
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])

    @app.middleware('http')
    async def local_origin(request:Request,call_next):
        origin=request.headers.get('origin')
        if origin and origin!=str(request.base_url).rstrip('/'):
            return JSONResponse({'errors':[{'code':'origin','message':'请求来源必须与本机服务一致'}]},status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def bad_input(request,exc):
        text=str(exc)
        try:
            errors=json.loads(text)
            if not isinstance(errors,list):raise ValueError()
        except (ValueError,TypeError):
            code,_,message=text.partition(':')
            errors=[{'code':code,'message':message.strip() or text}]
        return JSONResponse({'errors':errors},status_code=400)

    async def content(file):
        data=await file.read(40_000_001)
        if len(data)>40_000_000:raise ValueError('file_size: 文件超过 40MB')
        return data

    @app.get('/api/health')
    def health():return {'status':'ok','version':'0.1.0','application':'yamaha-program-builder'}

    @app.get('/api/projects')
    def projects():return service.list_projects()

    @app.post('/api/projects')
    def create(body:dict):return service.create_project(body.get('name',''))

    @app.get('/api/projects/{pid}')
    def project(pid):return service.public_project(pid)

    @app.put('/api/projects/{pid}/name')
    def rename(pid,body:dict):return service.rename_project(pid,body.get('name',''))

    @app.get('/api/projects/{pid}/save')
    def save(pid):
        p=service.get_project(pid)
        return Response(json.dumps(p,ensure_ascii=False,indent=2),media_type='application/json')

    @app.post('/api/projects/load')
    async def load(file:UploadFile=File(...)):return service.import_project(await content(file))

    @app.get('/api/mark-defaults')
    def defaults():return service.mark_defaults()

    @app.get('/api/assembly-defaults')
    def assembly_defaults():return service.assembly_defaults()

    @app.put('/api/projects/{pid}/board')
    def board(pid,body:dict):return service.set_board(pid,body)

    @app.put('/api/projects/{pid}/marks')
    def marks(pid,body:list[dict]):return service.set_marks(pid,body)

    @app.put('/api/projects/{pid}/assembly')
    def assembly(pid,body:dict):return service.set_assembly(pid,body)

    @app.post('/api/projects/{pid}/tables/{kind}')
    async def table(pid,kind,file:UploadFile=File(...)):
        return service.import_table(pid,kind,file.filename,await content(file))

    @app.put('/api/projects/{pid}/tables/{kind}')
    def configure(pid,kind,body:dict):
        return service.configure_table(pid,kind,body.get('mapping',{}),body.get('excluded_rows',[]),body.get('header_row',-1))

    @app.post('/api/projects/{pid}/library')
    async def import_lib(pid,file:UploadFile=File(...)):
        return service.import_library(pid,file.filename,await content(file))

    @app.get('/api/projects/{pid}/library')
    def list_lib(pid,q:str=''):return service.list_library(pid,q)

    @app.get('/api/projects/{pid}/library-export')
    def export_library(pid):
        return Response(service.export_library_data(pid),media_type='application/xml',
                        headers={'Content-Disposition':'attachment; filename="PartsDatabase.fdx"'})

    @app.get('/api/library-vocabulary')
    def library_vocabulary():
        from . import library_schema as schema
        return {'shapes':schema.SHAPES,'packages':schema.PACKAGES,'feeders':schema.FEEDERS,
                'tapes':schema.TAPES,'nozzles':schema.NOZZLES,'diagrams':schema.DIAGRAMS}

    @app.get('/api/projects/{pid}/library/{part_id}')
    def get_part(pid,part_id):return service.get_library_part(pid,part_id)

    @app.put('/api/projects/{pid}/library/{part_id}')
    def edit_part(pid,part_id,body:dict):
        if 'xml' in body:return service.update_library_xml(pid,part_id,body['xml'])
        return service.update_library(pid,part_id,body.get('changes',{}))

    @app.post('/api/projects/{pid}/library/{part_id}/duplicate')
    def duplicate(pid,part_id,body:dict):return service.duplicate_library_part(pid,part_id,body.get('name',''))

    @app.put('/api/projects/{pid}/matches/{group_id}')
    def match(pid,group_id,body:dict):return service.match_part(pid,group_id,body.get('part_id'))

    @app.post('/api/projects/{pid}/template')
    async def template(pid,file:UploadFile=File(...)):return service.import_ygx_template(pid,await content(file))

    @app.post('/api/mark-templates')
    async def mark_templates(file:UploadFile=File(...)):return service.import_mark_templates(await content(file))

    @app.post('/api/projects/{pid}/analyze')
    def analyze(pid):return service.analyze(pid)

    @app.post('/api/projects/{pid}/export')
    def export(pid):return service.export_ygx(pid)

    @app.get('/api/projects/{pid}/exports/{export_id}/{kind}')
    def download(pid,export_id,kind):
        p=service.get_project(pid)
        item=next((e for e in p['exports'] if e['export_id']==export_id),None)
        if item is None or kind not in ('ygx','fdx'):raise ValueError('export_not_found: 文件不存在')
        if item.get('historical'):raise ValueError('export_historical: 恢复的项目仅保留历史记录，请重新生成文件')
        path=Path(item['path'] if kind=='ygx' else item['library_path'])
        if not path.resolve().is_relative_to((service.data_dir/pid/'exports').resolve()) or not path.is_file():
            raise ValueError('export_not_found: 文件不存在')
        return FileResponse(path,filename=path.name,media_type='application/octet-stream')

    app.mount('/',StaticFiles(directory=Path(__file__).resolve().parent.parent/'web',html=True),name='web')
    return app
