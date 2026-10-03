import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parent.parent


class DistributionTest(unittest.TestCase):
    def test_stdio_smoke_accepts_an_empty_confirmation_database(self):
        code = ('import asyncio,tempfile; from pathlib import Path; '
                'from tools.check_package import exercise\n'
                'with tempfile.TemporaryDirectory() as folder:\n'
                '    names=asyncio.run(exercise(Path(folder)))\n'
                '    assert "list_library_associations" in names\n')
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code],
                                cwd=ROOT, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace')[-1800:])

    def test_config_uses_selected_ysup_and_relocated_python_entrypoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'installed package'
            (root / 'tools').mkdir(parents=True)
            shutil.copy2(ROOT / 'tools/generate_mcp_config.py', root / 'tools/generate_mcp_config.py')
            ysup = Path(folder) / 'YSUP'
            (ysup / 'System').mkdir(parents=True)
            (ysup / 'System/YwOptimizer.exe').write_bytes(b'test installation marker')
            output = root / 'client.json'
            result = subprocess.run([
                sys.executable, str(root / 'tools/generate_mcp_config.py'),
                '--ysup-root', str(ysup), '--output', str(output),
            ], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            self.assertTrue(output.is_file(), 'CLI must honor --output')
            config = json.loads(output.read_text(encoding='utf-8'))['mcpServers']['yamaha-program-builder']
            self.assertEqual(config['command'], sys.executable)
            self.assertEqual(config['args'], [str(root / 'run_mcp.py')])
            self.assertEqual(config['env']['YAMAHA_YSUP_ROOT'], str(ysup.resolve()))
            self.assertEqual(config['env']['YAMAHA_ASSOCIATIONS_DB'], str(root / 'data/confirmed_associations.sqlite3'))
            self.assertEqual(config['env']['YAMAHA_OPTIMIZER_WORK'], str(root / 'data/optimization'))

    def test_config_rejects_missing_optimizer_without_writing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tools').mkdir()
            shutil.copy2(ROOT / 'tools/generate_mcp_config.py', root / 'tools/generate_mcp_config.py')
            output = root / 'client.json'
            result = subprocess.run([
                sys.executable, str(root / 'tools/generate_mcp_config.py'),
                '--ysup-root', str(root / 'missing'), '--output', str(output),
            ], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_package_allowlist_excludes_customer_runtime_and_local_configuration(self):
        script = ROOT / 'tools/package_mcp.py'
        self.assertTrue(script.is_file(), 'portable source package builder is missing')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            shutil.copytree(ROOT / 'builder', root / 'builder', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT / 'web', root / 'web')
            shutil.copytree(ROOT / 'assets', root / 'assets')
            (root / 'tools').mkdir()
            (root / 'tests').mkdir()
            for name in ('run_mcp.py', 'requirements.txt', 'README.md', 'Start-MCP.cmd', 'Start-Builder.cmd', '.gitignore', '.gitattributes', 'DEPLOYMENT.md', 'LICENSE'):
                (root / name).write_text('test', encoding='utf-8')
            for name in ('generate_mcp_config.py', 'check_package.py', 'package_mcp.py'):
                (root / 'tools' / name).write_text('test', encoding='utf-8')
            for name in ('__init__.py', 'test_optimizer.py', 'test_distribution.py'):
                (root / 'tests' / name).write_text('test', encoding='utf-8')
            for name in ('data/private.sqlite3', 'tests/fixtures/customer.csv', 'validation/YSUP/System/native.exe', 'mcp_config.local.json', 'builder/leaked.env', 'assets/private.db'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'PRIVATE_DATA_MUST_NOT_BE_PUBLISHED')
            (root / 'web/images/ysup').mkdir(parents=True, exist_ok=True)
            (root / 'web/images/ysup/vendor.png').write_bytes(b'PRIVATE_DATA_MUST_NOT_BE_PUBLISHED')
            (root / 'web/images/ysup/catalog.json').write_text('[{"file":"vendor.png"}]', encoding='utf-8')
            output = Path(folder) / 'release'
            result = subprocess.run([
                sys.executable, str(script), '--source', str(root), '--output', str(output),
            ], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            with zipfile.ZipFile(output / 'yamaha-program-builder-mcp.zip') as archive:
                names = set(archive.namelist())
                for required in ('builder/mcp_server.py', 'builder/optimizer.py', 'assets/ysup_base.ygx', 'web/index.html', 'tools/generate_mcp_config.py'):
                    self.assertIn('yamaha-program-builder-mcp/' + required, names)
                self.assertFalse(any('PRIVATE_DATA_MUST_NOT_BE_PUBLISHED' in archive.read(name).decode('utf-8', 'ignore') for name in names))
                manifest = json.loads(archive.read('yamaha-program-builder-mcp/PACKAGE_MANIFEST.json'))
                self.assertIn('builder/mcp_server.py', manifest['files'])
                self.assertEqual(json.loads(archive.read('yamaha-program-builder-mcp/web/images/ysup/catalog.json')), [])
                self.assertFalse(any('..' in Path(name).parts or Path(name).is_absolute() for name in names))


if __name__ == '__main__':
    unittest.main()
