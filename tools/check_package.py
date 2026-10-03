"""Check packaged files and a real stdio MCP session using disposable local data."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {'create_project', 'set_board', 'get_mark_defaults', 'get_assembly_defaults',
            'import_table', 'import_library', 'update_library_part', 'duplicate_library_part',
            'match_part', 'analyze_project', 'export_ygx', 'confirm_library_associations',
            'query_library_associations', 'apply_library_associations', 'revoke_library_association',
            'list_optimization_lines', 'start_line_optimization', 'get_line_optimization'}


async def exercise(folder):
    env = {**os.environ, 'YAMAHA_BUILDER_DATA': str(folder / 'data'),
           'YAMAHA_ASSOCIATIONS_DB': str(folder / 'confirmed.sqlite3'),
           'YAMAHA_OPTIMIZER_WORK': str(folder / 'optimization')}
    env.pop('YAMAHA_YSUP_ROOT', None)
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'run_mcp.py')],
                                   cwd=str(folder), env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            if not REQUIRED <= names:
                raise RuntimeError('Missing MCP tools: ' + ', '.join(sorted(REQUIRED - names)))

            async def call(name, arguments=None):
                result = await session.call_tool(name, arguments or {})
                if result.isError:
                    raise RuntimeError(f'{name}: {result.content}')
                return json.loads(result.content[0].text) if result.content else None

            project = await call('create_project', {'name': 'Package_Smoke_Test'})
            await call('set_board', {'project_id': project['id'], 'settings': {
                'width': 100, 'height': 80, 'thickness': 1.6, 'side': 'top',
                'ygx_origin_corner': 'custom', 'ygx_origin_x': 0, 'ygx_origin_y': 0}})
            await call('get_mark_defaults')
            await call('get_assembly_defaults')
            await call('import_ygx_template', {'project_id': project['id'], 'file_path': str(ROOT / 'assets/ysup_base.ygx')})
            saved = await call('get_project', {'project_id': project['id']})
            if saved['board']['width'] != 100:
                raise RuntimeError('Board data did not persist across MCP calls')
            await call('list_library_associations')
            lines = await call('list_optimization_lines')
            if lines['configured']:
                raise RuntimeError('Smoke test must use an unconfigured optimizer')
        await reader.aclose()
        await writer.aclose()
    return sorted(names)


def main():
    manifest = json.loads((ROOT / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Package checksum mismatch: ' + name)
    with tempfile.TemporaryDirectory(prefix='yamaha_mcp_smoke_') as folder:
        names = asyncio.run(exercise(Path(folder)))
    print(json.dumps({'status': 'passed', 'manifest_files': len(manifest['files']),
                      'transport': 'stdio', 'tool_count': len(names), 'tools': names}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
