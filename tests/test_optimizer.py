import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from builder.optimizer import OptimizerService, prepare_settings, inspect_result, run_job


YGX = b'<PcbDataFile><Parts><Part No="1"><Part_001 PartsName="R0603"/></Part></Parts><Mounts><Mount Comment="R1" X="1" Y="2" R="0" Comp="1"/></Mounts></PcbDataFile>'
SETTINGS = b'''<OptimizerSettingFile><ProductionMode ProductionMode="1"/>
<TargetBoard><TargetBoard_02 FileName="OLD"/><TargetBoard_03 Path=""/><TargetBoard_04 Type="YGX"/></TargetBoard>
<SaveBoard><SaveBoard_02 FileName="OLD"/><SaveBoard_03 Path=""/><SaveBoard_04 Type="YGX"/><SaveBoard_05 SubType="Lane1"/></SaveBoard>
<Machine Number="1"><Machine_00 MachineName="YSM20" MchType="40"/><Feeder 8mmType="0"/></Machine>
<Machine Number="2"><Machine_00 MachineName="YSM10" MchType="41"/></Machine></OptimizerSettingFile>'''
RESULT = b'<OptResultFile><OptResult Result="OK"><Machine No="1" 2StageAlternateMount="0"><TableSummary No="1" CycleTime="1.23"/></Machine></OptResult></OptResultFile>'


class OptimizerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.source = base/'installed'
        self.line = self.source/'Line1'
        for part in ('System','Line1/No0','Line1/No1','Line1/No2','Line1/Opt'):
            (self.source/part).mkdir(parents=True)
        (self.source/'System/YwOptimizer.exe').write_bytes(b'fake')
        (self.source/'YgApplications.ini').write_text('[Enhanced YVOS DIR]\nPATH='+str(self.source)+'\n')
        (self.source/'YwOptimizer.ini').write_text('[File]\nBoard Data Folder='+str(self.line)+'\n')
        (self.line/'No0/MCH_INF.STS').write_text('No.00 YSM20 0, 0, 1,\nNo.01 YSM10 0, 0, 1,\nNo.02 ######## 0, 0, 0,\n')
        (self.line/'Opt/saved.ygs').write_bytes(SETTINGS)
        (self.line/'Opt/OptimizerDefault.ygl').write_bytes(b'<OptimizerSettingList><ListData Number="0"><ListData_01 SaveFileName="OLD"/></ListData></OptimizerSettingList>')
        self.input = base/'customer.ygx'
        self.input.write_bytes(YGX)
        self.service = OptimizerService(self.source, base/'jobs')

    def start(self, request='request-1'):
        import os
        with patch('builder.optimizer.subprocess.Popen') as launch:
            launch.return_value.pid = os.getpid()
            return self.service.start(str(self.input),'Line1','saved.ygs',request)

    def test_discovery_uses_saved_machine_order_and_templates(self):
        lines = self.service.list_lines()['lines']
        self.assertEqual([m['name'] for m in lines[0]['machines']],['YSM20','YSM10'])
        self.assertEqual(lines[0]['settings'][0]['name'],'saved.ygs')
        self.assertFalse(OptimizerService(None,Path(self.tmp.name)/'disabled').list_lines()['configured'])

    def test_settings_rewrite_preserves_native_numeric_attributes(self):
        data = prepare_settings(SETTINGS,'MCP_ABC',[{'name':'YSM20'},{'name':'YSM10'}])
        self.assertIn(b'8mmType="0"',data)
        self.assertEqual(data.count(b'FileName="MCP_ABC"'),2)
        with self.assertRaisesRegex(ValueError,'optimizer_settings_machine'):
            prepare_settings(SETTINGS,'MCP_ABC',[{'name':'YSM10'}])
        with self.assertRaisesRegex(ValueError,'optimizer_settings_path'):
            prepare_settings(SETTINGS.replace(b'Path=""',b'Path="C:\\elsewhere"'),'MCP_ABC',[{'name':'YSM20'},{'name':'YSM10'}])

    def test_idempotent_request_and_changed_input_blocks(self):
        a = self.start()
        self.assertEqual(a['job_id'],self.start()['job_id'])
        self.input.write_bytes(YGX.replace(b'X="1"',b'X="9"'))
        with self.assertRaisesRegex(ValueError,'optimizer_request_conflict'):
            self.start()

    def test_paths_and_missing_line_block_before_launch(self):
        with self.assertRaisesRegex(ValueError,'optimizer_line'):
            self.service.start(str(self.input),'../System','saved.ygs','x')
        with self.assertRaisesRegex(ValueError,'optimizer_work_path'):
            OptimizerService(self.source,self.source/'jobs')
        with self.assertRaisesRegex(ValueError,'optimizer_settings'):
            self.service.start(str(self.input),'Line1','../saved.ygs','x')

    def test_result_requires_native_ok_exit_and_identical_points(self):
        (self.line/'No1/out.ygx').write_bytes(YGX)
        (self.line/'No2/out.ygx').write_bytes(YGX.replace(b'<Mount Comment="R1" X="1" Y="2" R="0" Comp="1"/>',b''))
        report = self.line/'Opt/out.rlt3'
        report.write_bytes(RESULT)
        machines = self.service.list_lines()['lines'][0]['machines']
        result = inspect_result(self.input,self.line,'out',machines,0)
        self.assertEqual(result['status'],'succeeded')
        self.assertTrue(result['mounts_identical'])
        self.assertEqual(inspect_result(self.input,self.line,'out',machines,1)['status'],'failed')
        (self.line/'No1/out.ygx').write_bytes(YGX.replace(b'X="1"',b'X="3"'))
        self.assertEqual(inspect_result(self.input,self.line,'out',machines,0)['errors'][0]['code'],'optimizer_mounts_changed')
        report.write_bytes(b'<OptResultFile><OptResult Result="NG"><ErrorMessage Message="Ea9999: tray error"/></OptResult></OptResultFile>')
        result = inspect_result(self.input,self.line,'out',machines,0)
        self.assertEqual(result['status'],'failed')
        self.assertIn('Ea9999',result['native_errors'][0])

    def test_native_padded_component_numbers_match(self):
        from builder.optimizer import placements
        self.input.write_bytes(YGX.replace(b'Comp="1"',b'Comp="  1"'))
        self.assertEqual(sum(placements(self.input).values()),1)

    def test_xml_normalization_preserves_all_attribute_values(self):
        from builder.optimizer import placements
        self.input.write_bytes(YGX.replace(b'R0603',b'R 1=2'))
        one = placements(self.input)
        self.input.write_bytes(YGX.replace(b'R0603',b'R ysup_1=2'))
        self.assertNotEqual(one,placements(self.input))

    def test_case_variant_ini_references_redirect(self):
        from builder.optimizer import redirect_configs
        import shutil
        runtime = Path(self.tmp.name)/'clone'
        (self.source/'YwOptimizer.ini').write_text('[File]\nBoard Data Folder='+str(self.line).lower()+'\n')
        (self.source/'EditorSettings.xml').write_text('<Path>'+str(self.line).lower()+'</Path>',encoding='utf-16')
        shutil.copytree(self.source,runtime)
        redirect_configs(runtime,self.source)
        self.assertIn(str(runtime),(runtime/'YwOptimizer.ini').read_text())
        self.assertIn(str(runtime),(runtime/'EditorSettings.xml').read_text(encoding='utf-16'))

    def test_dead_queued_worker_is_reported_interrupted(self):
        job = self.start()
        with patch('builder.optimizer.alive',return_value=False):
            self.assertEqual(self.service.get(job['job_id'])['status'],'interrupted')

    def test_concurrent_identical_requests_launch_once(self):
        import os
        from concurrent.futures import ThreadPoolExecutor
        with patch('builder.optimizer.subprocess.Popen') as launch:
            launch.return_value.pid = os.getpid()
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda n:self.service.start(str(self.input),'Line1','saved.ygs','parallel'),range(2)))
            self.assertEqual(results[0]['job_id'],results[1]['job_id'])
            self.assertEqual(launch.call_count,1)

    def test_worker_modifies_only_runtime_copy_and_saves_final_report(self):
        job = self.start()
        before = {str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        def native(args,**kwargs):
            root = Path(kwargs['cwd'])
            self.assertNotEqual(root,self.source)
            self.assertIn(str(root),(root/'YgApplications.ini').read_text())
            self.assertNotIn(str(self.source),(root/'YwOptimizer.ini').read_text())
            name = job['program_name']
            (root/f'Line1/No2/{name}.ygx').write_bytes(YGX.replace(b'<Mount Comment="R1" X="1" Y="2" R="0" Comp="1"/>',b''))
            (root/f'Line1/Opt/{name}.rlt3').write_bytes(RESULT)
            return type('Process',(),{'returncode':0})()
        with patch('builder.optimizer.subprocess.run',side_effect=native):
            run_job(Path(job['job_dir']))
        result = self.service.get(job['job_id'])
        self.assertEqual(result['status'],'succeeded',result)
        self.assertEqual(before,{str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()})
        self.assertEqual(result['input_sha256'],result['input_snapshot_sha256'])
        self.assertTrue(Path(result['outputs'][0]['path']).is_file())


if __name__ == '__main__': unittest.main()
