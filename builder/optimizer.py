"""Native YSUP optimization in disposable copies, with durable MCP job results."""
from collections import Counter
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def native_xml(data):
    # Yamaha's numeric attribute names are not legal XML; normalize only for reading.
    for encoding in ('utf-8-sig','gb18030'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('optimizer_xml: 无法读取原生文件编码')
    text = re.sub(r'(<\?xml[^>]*encoding=)["\'][^"\']+["\']',r'\1"utf-8"',text)
    def normalize_tag(match):
        pieces = re.split(r'("[^"]*"|\x27[^\x27]*\x27)',match[0])
        return ''.join(piece if index%2 else re.sub(r'(\s)([0-9][\w.]*)=',r'\1ysup_\2=',piece)
                       for index,piece in enumerate(pieces))
    text = re.sub(r'<(?:[^>"\x27]|"[^"]*"|\x27[^\x27]*\x27)*>',normalize_tag,text)
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f'optimizer_xml: {exc}') from exc


def prepare_settings(data, name, machines):
    tree = native_xml(data)
    if tree.tag != 'OptimizerSettingFile':
        raise ValueError('optimizer_settings: 不是优化设置文件')
    configured = [n.get('MachineName') for n in tree.findall('./Machine/Machine_00')]
    if configured != [m['name'] for m in machines]:
        raise ValueError('optimizer_settings_machine: 优化设置与线体机台顺序不一致')
    for block in ('TargetBoard','SaveBoard'):
        for suffix,attr,expected in (('03','Path',''),('04','Type','YGX')):
            node = tree.find(f'{block}/{block}_{suffix}')
            if node is None or node.get(attr) != expected:
                raise ValueError('optimizer_settings_path: 仅支持默认路径的单程序 YGX 设置')
    subtype = tree.find('SaveBoard/SaveBoard_05')
    if subtype is None or subtype.get('SubType') != 'Lane1':
        raise ValueError('optimizer_settings_lane: 当前仅支持 Lane1 输出')
    for node in tree.iter():
        for key,value in node.attrib.items():
            if ('Path' in key and value) or (key.endswith('FileName') and value and node.tag not in ('TargetBoard_02','SaveBoard_02')):
                raise ValueError('optimizer_settings_reference: 含外部文件引用，请先保存独立优化设置')
        if any(key.startswith('ReferSetup') and value != '0' for key,value in node.attrib.items()):
            raise ValueError('optimizer_settings_reference: 不能引用外部优化设置')
    for tag in (b'TargetBoard_02',b'SaveBoard_02'):
        pattern = rb'(<' + tag + rb'\s+FileName=")[^"]*(")'
        data,count = re.subn(pattern,lambda match: match[1]+name.encode('ascii')+match[2],data)
        if count != 1:
            raise ValueError('optimizer_settings: 输入/输出文件名不唯一')
    return data


def placements(path):
    tree = native_xml(path.read_bytes())
    if tree.tag != 'PcbDataFile':
        raise ValueError('optimizer_input: 输入必须是 YGX PcbDataFile')
    parts = {}
    for part in tree.findall('.//Parts/Part'):
        identity = part.find('Part_001')
        if identity is None or not identity.get('PartsName'):
            raise ValueError('optimizer_input: 元件缺少 PartsName')
        parts[str(part.get('No','')).strip()] = identity.get('PartsName')
    points = Counter()
    for mount in tree.findall('.//Mounts/Mount'):
        try:
            x,y,r = (Decimal(mount.get(k)) for k in ('X','Y','R'))
            if not all(n.is_finite() for n in (x,y,r)):
                raise ValueError('非有限坐标')
            reference = mount.get('Comment')
            if not reference:
                raise ValueError('缺少位号')
            points[(reference,x,y,(r%360+360)%360,parts[str(mount.get('Comp','')).strip()])] += 1
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
            raise ValueError(f'optimizer_input: 贴装点无效：{exc}') from exc
    return points


def inspect_result(input_path, line_path, name, machines, exit_code):
    report = line_path/'Opt'/f'{name}.rlt3'
    result = {'status':'failed','exit_code':exit_code,'native_result':'missing',
              'native_errors':[],'errors':[],'outputs':[],'cycle_times':[],
              'mounts_identical':False,'report_path':str(report)}
    if not report.is_file():
        result['errors'] = [{'code':'optimizer_report_missing','message':'未生成原生 .rlt3 结果'}]
        return result
    tree = native_xml(report.read_bytes())
    status = tree.find('OptResult')
    result['native_result'] = status.get('Result') if status is not None else 'missing'
    result['native_errors'] = [n.get('Message','') for n in tree.findall('.//ErrorMessage')]
    for machine in tree.findall('.//OptResult/Machine'):
        for summary in machine.findall('.//TableSummary'):
            result['cycle_times'].append({'machine':machine.get('No'),'table':summary.get('No'),'seconds':summary.get('CycleTime')})
    if exit_code != 0 or result['native_result'] != 'OK':
        result['errors'] = [{'code':'optimizer_native_failed','message':'; '.join(result['native_errors']) or f"exit={exit_code}, result={result['native_result']}"}]
        return result
    expected = placements(input_path)
    actual = Counter()
    for machine in machines:
        path = line_path/machine['folder']/f'{name}.ygx'
        if not path.is_file():
            result['errors'] = [{'code':'optimizer_output_missing','message':str(path)}]
            return result
        points = placements(path)
        actual.update(points)
        result['outputs'].append({**machine,'path':str(path),'mounts':sum(points.values()),'sha256':digest(path.read_bytes())})
    result.update(input_mounts=sum(expected.values()),output_mounts=sum(actual.values()),mounts_identical=actual==expected)
    if expected != actual:
        result['errors'] = [{'code':'optimizer_mounts_changed','message':'分机输出的位号、坐标、角度或物料名与输入不一致',
                             'missing':[list(map(str,k)) for k in (expected-actual).elements()],
                             'extra':[list(map(str,k)) for k in (actual-expected).elements()]}]
    else:
        result['status'] = 'succeeded'
    return result


def snapshot(root):
    records = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
            raise ValueError('optimizer_source_link: YSUP 来源含链接，不能隔离复制')
        if path.is_file() and path.suffix.lower() not in ('.ygx','.ygs','.rlt2','.rlt3'):
            records[str(path.relative_to(root))] = digest(path.read_bytes())
    return records


def alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        try:
            return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False


class OptimizerService:
    def __init__(self, source_root, work_root):
        self.source = Path(source_root).expanduser().resolve() if source_root else None
        self.work = Path(work_root).expanduser().resolve()
        if self.source and (self.work.is_relative_to(self.source) or self.source.is_relative_to(self.work)):
            raise ValueError('optimizer_work_path: 任务目录与 YSUP 来源目录不能互相包含')

    def list_lines(self):
        if not self.source:
            return {'configured':False,'lines':[],'message':'请配置 YAMAHA_YSUP_ROOT'}
        if not (self.source/'System/YwOptimizer.exe').is_file():
            raise ValueError('optimizer_installation: 缺少 System/YwOptimizer.exe')
        lines = []
        for line in sorted(self.source.iterdir()):
            info = line/'No0/MCH_INF.STS'
            if not line.is_dir() or not info.is_file():
                continue
            machines = []
            for index,name,status in re.findall(r'^No\.(\d+)\s+(\S+)\s+\d+,\s*\d+,\s*(\d+),',info.read_bytes().decode('gb18030'),re.M):
                if status == '1':
                    folder = f'No{int(index)+1}'
                    if not (line/folder).is_dir():
                        raise ValueError('optimizer_line: 机台目录缺失：'+folder)
                    machines.append({'folder':folder,'name':name})
            if not machines:
                continue
            settings = []
            for path in sorted((line/'Opt').glob('*.ygs')):
                try:
                    data = path.read_bytes()
                    prepare_settings(data,'MCP_CHECK',machines)
                    settings.append({'name':path.name,'usable':True,'sha256':digest(data)})
                except ValueError as exc:
                    settings.append({'name':path.name,'usable':False,'reason':str(exc)})
            lines.append({'name':line.name,'machines':machines,'settings':settings})
        return {'configured':True,'source_root':str(self.source),'work_root':str(self.work),'lines':lines}

    def start(self, file_path, line, settings_name, request_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request_id):
            raise ValueError('optimizer_request_id: 使用 1～100 位字母、数字、下划线或短横线')
        configured = next((item for item in self.list_lines()['lines'] if item['name']==line),None)
        if configured is None:
            raise ValueError('optimizer_line: 未配置此线体')
        setting = next((item for item in configured['settings'] if item['name']==settings_name),None)
        if setting is None or not setting.get('usable'):
            raise ValueError('optimizer_settings: 未找到可用的已保存设置；'+str(setting))
        path = Path(file_path).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != '.ygx' or path.stat().st_size>40_000_000:
            raise ValueError('optimizer_input: 需要 40MB 以内的本机 YGX 文件')
        source = path.read_bytes()
        if not placements(path):
            raise ValueError('optimizer_input: 输入没有贴装点')
        if path.read_bytes() != source:
            raise ValueError('optimizer_input_changed: 读取期间文件改变，请先保存后重试')
        settings = (self.source/line/'Opt'/settings_name).read_bytes()
        fingerprint = digest(json.dumps([str(self.source),line,digest(source),digest(settings)]).encode())
        job_id = uuid.uuid5(uuid.NAMESPACE_URL,request_id).hex
        folder = self.work/job_id
        self.work.mkdir(parents=True,exist_ok=True)
        if folder.exists():
            previous = self.get(job_id)
            if previous.get('fingerprint') != fingerprint:
                raise ValueError('optimizer_request_conflict: request_id 已用于其他内容，请使用新 request_id')
            return previous
        staging = Path(tempfile.mkdtemp(prefix=job_id+'_',dir=self.work))
        name = 'MCP_'+job_id[:20]
        (staging/'input.ygx').write_bytes(source)
        (staging/'settings.ygs').write_bytes(prepare_settings(settings,name,configured['machines']))
        job = {'job_id':job_id,'job_dir':str(folder),'status':'queued','fingerprint':fingerprint,
               'request_id':request_id,'source_root':str(self.source),'line':line,'settings_name':settings_name,
               'input_path':str(path),'input_sha256':digest(source),'settings_sha256':digest(settings),
               'program_name':name,'machines':configured['machines'],'errors':[]}
        save_json(staging/'job.json',job)
        try:
            staging.rename(folder)
        except OSError:
            if not folder.exists():
                raise
            shutil.rmtree(staging)
            previous = self.get(job_id)
            if previous.get('fingerprint') != fingerprint:
                raise ValueError('optimizer_request_conflict: request_id 已用于其他内容，请使用新 request_id')
            return previous
        try:
            with (folder/'worker.log').open('wb') as log:
                worker = subprocess.Popen([sys.executable,'-m','builder.optimizer','--job',str(folder)],
                                 cwd=Path(__file__).resolve().parent.parent,stdin=subprocess.DEVNULL,
                                 stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            save_json(folder/'launcher.json',{'pid':worker.pid})
        except OSError as exc:
            job.update(status='failed',errors=[{'code':'optimizer_launch','message':str(exc)}])
            save_json(folder/'job.json',job)
        return job

    def get(self, job_id):
        if not re.fullmatch(r'[a-f0-9]{32}',job_id):
            raise ValueError('optimizer_job: 无效任务 id')
        path = self.work/job_id/'job.json'
        if not path.is_file():
            raise ValueError('optimizer_job: 任务不存在或正在初始化，请稍后查询')
        job = json.loads(path.read_text(encoding='utf-8'))
        if job['status'] in ('queued','copying','running'):
            launch = path.parent/'launcher.json'
            pid = job.get('worker_pid') or (json.loads(launch.read_text())['pid'] if launch.exists() else None)
            if (pid and not alive(pid)) or (not pid and time.time()-path.stat().st_mtime>10):
                job.update(status='interrupted',errors=[{'code':'optimizer_interrupted','message':'后台执行进程已停止，请检查任务日志；不会自动重复优化'}])
        return job


@contextmanager
def optimization_lock(source):
    path = Path(tempfile.gettempdir())/('yamaha_optimizer_'+digest(str(source).lower().encode())[:24]+'.lock')
    with path.open('a+b') as handle:
        if handle.tell()==0:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('optimizer_busy: 此 YSUP 来源已有 MCP 优化任务，请等待完成') from exc
        yield


def redirect_configs(runtime, source):
    # INI/XML absolute root references can differ in case or slash style on Windows.
    pattern = r'[\\/]'.join(re.escape(piece) for piece in re.split(r'[\\/]',str(source)))
    for config in list(runtime.glob('*.ini'))+list(runtime.glob('*.xml')):
        data = config.read_bytes()
        if data.startswith((b'\xff\xfe',b'\xfe\xff')):
            text=data.decode('utf-16');encoding='utf-16'
        else:
            try:
                text = data.decode('utf-8-sig');encoding = 'utf-8-sig' if data.startswith(b'\xef\xbb\xbf') else 'utf-8'
            except UnicodeDecodeError:
                text = data.decode('gb18030');encoding = 'gb18030'
        text = re.sub(pattern,lambda match:str(runtime),text,flags=re.I)
        config.chmod(stat.S_IWRITE|stat.S_IREAD)
        config.write_bytes(text.encode(encoding))
        if re.search(pattern,text,re.I):
            raise ValueError('optimizer_root_redirect: 副本配置仍引用来源根')
    application = (runtime/'YgApplications.ini').read_bytes().decode('gb18030')
    configured = re.search(r'\[Enhanced YVOS DIR\]\s*PATH=([^\r\n]+)',application,re.I)
    if not configured or Path(configured[1]).resolve()!=runtime:
        raise ValueError('optimizer_root_redirect: 副本根路径未正确隔离')
    optimizer = (runtime/'YwOptimizer.ini').read_bytes().decode('gb18030')
    board = re.search(r'^Board Data Folder=([^\r\n]+)',optimizer,re.M|re.I)
    if not board or not Path(board[1]).resolve().is_relative_to(runtime):
        raise ValueError('optimizer_root_redirect: 优化器程序目录未正确隔离')


def protect_worker():
    """Keep native descendants in a Windows Job until the worker exits."""
    if os.name!='nt':
        return None
    import ctypes
    from ctypes import wintypes
    class Limits(ctypes.Structure):
        _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),
                  ('LimitFlags',wintypes.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),
                  ('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',wintypes.DWORD),
                  ('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
    class Counters(ctypes.Structure):
        _fields_=[(name,ctypes.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class Extended(ctypes.Structure):
        _fields_=[('BasicLimitInformation',Limits),('IoInfo',Counters),('ProcessMemoryLimit',ctypes.c_size_t),
                  ('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE,wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None,None)
    info = Extended();info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle,kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(),'无法隔离原生进程生命周期')
    # Do not close while this worker is alive: process exit closes it and kills children.
    return handle


def stop_native_descendants():
    """Drain this worker's job before releasing the source optimization lock."""
    handle = globals().get('worker_job_handle')
    if os.name!='nt' or not handle:
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE,wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    for attempt in range(5):
        size = 4096
        while True:
            buffer = ctypes.create_string_buffer(size)
            if kernel.QueryInformationJobObject(handle,3,buffer,size,None):
                break
            if ctypes.get_last_error()!=234 or size>=1048576:
                raise OSError(ctypes.get_last_error(),'无法核对原生进程树')
            size *= 2
        count = ctypes.c_ulong.from_buffer(buffer,4).value
        pids = list((ctypes.c_size_t*count).from_buffer(buffer,8))
        children = [pid for pid in pids if pid!=os.getpid()]
        if not children:
            return
        for pid in children:
            process = kernel.OpenProcess(0x100001,False,pid)  # SYNCHRONIZE | PROCESS_TERMINATE
            if process:
                try:
                    if kernel.WaitForSingleObject(process,0)!=0:
                        terminated = kernel.TerminateProcess(process,1)
                        error = ctypes.get_last_error()
                        if kernel.WaitForSingleObject(process,5000)!=0:
                            raise OSError(error if not terminated else 0,'无法停止原生后代进程')
                finally:
                    kernel.CloseHandle(process)
    raise OSError('原生后代进程未退出，不能完成优化任务')


def run_job(folder):
    folder = folder.resolve()
    path = folder/'job.json'
    job = json.loads(path.read_text(encoding='utf-8'))
    source = Path(job['source_root'])
    runtime = folder/'YSUP'
    try:
        with optimization_lock(source):
            job.update(status='copying',worker_pid=os.getpid())
            save_json(path,job)
            before = snapshot(source)
            save_json(folder/'source-config.json',before)
            shutil.copytree(source,runtime)
            if snapshot(source) != before:
                raise ValueError('optimizer_source_changed: 复制期间 YSUP 配置改变，请重新保存设置后提交新任务')
            job['source_config_sha256'] = digest(json.dumps(before,sort_keys=True).encode())
            redirect_configs(runtime,source)
            line = runtime/job['line']
            name = job['program_name']
            for item in (line/'Opt').iterdir():
                if item.suffix.lower() in ('.ygs','.rlt2','.rlt3','.ygl'):
                    item.unlink()
            target = line/job['machines'][0]['folder']/f'{name}.ygx'
            target.write_bytes((folder/'input.ygx').read_bytes())
            (line/'Opt'/f'{name}.ygs').write_bytes((folder/'settings.ygs').read_bytes())
            (line/'Opt/OptimizerDefault.ygl').write_bytes(b'<OptimizerSettingList><Version Version="0.00"/><ListData Number="0"><ListData_01 SaveFileName="'+name.encode()+b'"/><ListData_02 TakingOver="0"/></ListData></OptimizerSettingList>')
            job.update(status='running',input_snapshot_sha256=digest((folder/'input.ygx').read_bytes()))
            save_json(path,job)
            kwargs = {'cwd':runtime,'stdin':subprocess.DEVNULL,'timeout':300}
            if os.name=='nt':
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 0
                kwargs.update(startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW)
            with (folder/'native.log').open('wb') as log:
                try:
                    proc = subprocess.run([str(runtime/'System/YwOptimizer.exe'),'/_Optimize','/LINE='+job['line']],stdout=log,stderr=log,**kwargs)
                finally:
                    stop_native_descendants()
            result = inspect_result(folder/'input.ygx',line,name,job['machines'],proc.returncode)
            job.update(result)
            if job['status']=='succeeded':
                output = folder/'outputs'
                output.mkdir()
                for item in job['outputs']:
                    destination = output/(item['folder']+'_'+name+'.ygx')
                    shutil.copyfile(item['path'],destination)
                    item['path'] = str(destination)
            if Path(job.get('report_path','')).is_file():
                report = folder/'native.rlt3'
                shutil.copyfile(job['report_path'],report)
                job.update(report_path=str(report),report_sha256=digest(report.read_bytes()))
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        code,_,message = str(exc).partition(':')
        if isinstance(exc,subprocess.TimeoutExpired):
            code,message = 'optimizer_timeout','优化器超过 300 秒，已停止；请查看日志'
        job.update(status='failed',errors=[{'code':code,'message':message or str(exc)}])
    save_json(path,job)


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--job',required=True,type=Path)
    worker_job_handle = protect_worker()
    run_job(parser.parse_args().job)
