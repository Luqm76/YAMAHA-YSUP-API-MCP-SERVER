"""Build a source-only MCP distribution from an explicit redistribution allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


NAME = 'yamaha-program-builder-mcp'
ROOT_FILES = ('README.md', 'DEPLOYMENT.md', 'requirements.txt', 'run_mcp.py',
              'Start-MCP.cmd', 'Start-Builder.cmd', '.gitignore', '.gitattributes', 'LICENSE')
ASSETS = ('ysup_base.ygx', 'circle.xml', 'rectangle.xml', 'bad.xml', 'mount.xml', 'provenance.md')
TOOLS = ('generate_mcp_config.py', 'check_package.py', 'package_mcp.py')
TESTS = ('__init__.py', 'test_optimizer.py', 'test_distribution.py')


def build(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    files = [source / name for name in ROOT_FILES]
    files += sorted((source / 'builder').glob('*.py'))
    files += sorted(path for path in (source / 'web').rglob('*')
                    if path.is_file() and path.suffix in {'.html', '.js', '.css', '.json', '.md'}
                    and 'images' not in path.relative_to(source / 'web').parts)
    files += [source / 'assets' / name for name in ASSETS]
    files += [source / 'tools' / name for name in TOOLS]
    files += [source / 'tests' / name for name in TESTS]
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'package_source_missing_or_link: {path.relative_to(source)}')
    if not (source / 'builder/mcp_server.py') in files or not (source / 'web/index.html') in files:
        raise ValueError('package_source_missing: MCP server or web entry point')
    staging = output / NAME
    staging.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for path in files:
        relative = path.relative_to(source)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        hashes[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    catalog = staging / 'web/images/ysup/catalog.json'
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text('[]\n', encoding='utf-8')
    hashes['web/images/ysup/catalog.json'] = hashlib.sha256(catalog.read_bytes()).hexdigest()
    manifest = {'format_version': 1, 'package': NAME, 'python': '3.12',
                'files': hashes, 'excluded': ['customer inputs and fixtures', 'runtime databases',
                'local client configuration', 'deliveries and recordings', 'YSUP installation, binaries and vendor help images']}
    (staging / 'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = output / f'{NAME}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                bundle.write(path, f'{NAME}/{path.relative_to(staging).as_posix()}')
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / f'{NAME}.zip.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'staging': str(staging),
                      'files': len(hashes) + 1, 'sha256': checksum}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--output', type=Path, required=True, help='New release directory; staging must not already exist')
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == '__main__':
    main()
