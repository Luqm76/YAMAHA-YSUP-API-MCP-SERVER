"""Explicitly confirmed, scoped Part snapshots. Never infer confirmation from a save."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
import xml.etree.ElementTree as ET

from . import library, tables


IDENTITY_FIELDS = ('name', 'spec', 'partno', 'footprint')
CONTEXT_FIELDS = ('namespace', 'machine_type', 'package', 'feeder_type', 'carrier_tape')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def identity_key(identity):
    return {key: str(identity.get(key) or '').strip().casefold() for key in IDENTITY_FIELDS}


def normalize_context(context):
    if not isinstance(context, dict):
        raise ValueError('association_context: 适用范围必须是对象')
    keys = CONTEXT_FIELDS + (('line', 'machine') if str(context.get('package', '')).strip() == '3' else ())
    result = {}
    for key in keys:
        value = context.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
            raise ValueError(f'association_context: 缺少明确的 {key}')
        result[key] = str(value).strip()
    return result


def clean_part(xml):
    part = library.parse_xml(xml.encode('utf-8'))
    part.find('Part_002').set('Package', part.find('Part_002').get('Package', '').strip())
    item = {'xml': ET.tostring(part, encoding='unicode')}
    # Reuse the exporter's established reset rules; a saved station is not a new assignment.
    return library.clone_part(item, 0, part.find('Part_001').get('PartsName', ''))


def parameter_hash(xml):
    part = clean_part(xml)
    part.find('Part_001').set('PartsName', '')

    def canonical(node):
        return [node.tag, sorted((key, value.strip()) for key, value in node.attrib.items()),
                (node.text or '').strip(), [canonical(child) for child in node]]
    return _hash(_json(canonical(part)))


def validate_part(part):
    for tag in ('Part_001', 'Part_002', 'Part_003', 'Part_080'):
        if part.find(tag) is None:
            raise ValueError(f'association_part: 缺少 {tag}')
    body = next((node for node in part if all(key in node.attrib for key in ('BodyX', 'BodyY', 'BodyZ'))), None)
    if body is None or any(tables.number(body.get(key, '')) <= 0 for key in ('BodyX', 'BodyY', 'BodyZ')):
        raise ValueError('association_part: 元件长宽高必须完整且大于 0')
    supply, feeder = part.find('Part_002'), part.find('Part_003')
    if supply.get('CarrierTape', '').strip() == '1' and (
        tables.number(feeder.get('FdrIdxStep', '0')) <= 0 and tables.number(feeder.get('PitchEffect', '0')) <= 0
    ):
        raise ValueError('association_part: 带式送料缺少有效间距')


def capture(project, groups, files, namespace, reviewer, evidence, line, process_verified):
    by_ref = {}
    selected = {ref for group in groups for ref in group['refs']}
    for path, data in files:
        root = library.parse_xml(data)
        if root.tag != 'PcbDataFile':
            raise ValueError('association_source: 必须读取人工保存的原生 YGX')
        source = {'path': str(Path(path).resolve()), 'sha256': hashlib.sha256(data).hexdigest()}
        for machine in root.findall('Machine'):
            parts = {}
            for part in machine.findall('Parts/Part'):
                no = part.get('No', '').strip()
                if not no or no in parts:
                    raise ValueError('association_reference: 元件编号为空或重复')
                parts[no] = part
            for mount in machine.findall('Mounts/Mount'):
                ref = mount.get('Comment', '').strip().upper()
                if ref not in selected:
                    continue
                if ref in by_ref:
                    raise ValueError(f'association_reference: 保存文件重复位号 {ref}')
                part = parts.get(mount.get('Comp', '').strip())
                if part is None:
                    raise ValueError(f'association_reference: {ref} 找不到完整 Part')
                validate_part(part)
                supply = part.find('Part_002')
                context = normalize_context({
                    'namespace': namespace, 'machine_type': machine.get('MachineType'),
                    'package': supply.get('Package'), 'feeder_type': supply.get('FdrType'),
                    'carrier_tape': supply.get('CarrierTape'), 'line': line, 'machine': machine.get('No')})
                xml = ET.tostring(part, encoding='unicode')
                by_ref[ref] = {'xml': xml, 'context': context, 'source': source,
                               'parameter_hash': parameter_hash(xml)}
    missing = sorted(selected - by_ref.keys())
    if missing:
        raise ValueError(f'association_reference: 保存文件缺少位号 {", ".join(missing)}')
    snapshots = {}
    for group in groups:
        for ref in group['refs']:
            item = by_ref[ref]
            identity = {key: group.get(key, '') for key in IDENTITY_FIELDS}
            key = _json([identity_key(identity), item['context']])
            if key in snapshots and snapshots[key]['parameter_hash'] != item['parameter_hash']:
                raise ValueError(f'association_conflict: 同一物料及适用范围参数矛盾（{ref}）')
            if key not in snapshots:
                snapshots[key] = {**item, 'identity': identity, 'identity_key': identity_key(identity),
                                  'xml_sha256': _hash(item['xml']), 'sources': [], 'group_ids': [], 'refs': [],
                                  'project_id': project['id'], 'project_revision': project['revision'],
                                  'reviewer': reviewer.strip(), 'evidence': evidence.strip(),
                                  'process_verified': process_verified,
                                  'eligible': bool(identity_key(identity)['partno'] and identity_key(identity)['footprint'])}
                snapshots[key].pop('source')
            record = snapshots[key]
            for field, value in (('sources', item['source']), ('group_ids', group['id']), ('refs', ref)):
                if value not in record[field]:
                    record[field].append(value)
    return list(snapshots.values())


class AssociationStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS associations (
                id TEXT PRIMARY KEY, lookup_key TEXT NOT NULL, version INTEGER NOT NULL,
                capture_key TEXT UNIQUE NOT NULL, document TEXT NOT NULL)''')
            con.execute('CREATE INDEX IF NOT EXISTS association_lookup ON associations(lookup_key)')

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path, timeout=30)
        try:
            with con:
                yield con
        finally:
            con.close()

    def archive(self, snapshots):
        records, stored = [], 0
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            for snapshot in snapshots:
                capture_key = _hash(_json(snapshot))
                previous = con.execute('SELECT document FROM associations WHERE capture_key=?', (capture_key,)).fetchone()
                # Reconfirming a revoked capture creates a new version. Retries then find
                # that active successor; repeated revoke/reconfirm cycles stay idempotent.
                while previous and json.loads(previous[0])['status'] == 'revoked':
                    capture_key = _hash(capture_key + '\0' + json.loads(previous[0])['id'])
                    previous = con.execute('SELECT document FROM associations WHERE capture_key=?', (capture_key,)).fetchone()
                if previous:
                    records.append(json.loads(previous[0]))
                    continue
                key = _json([snapshot['identity_key'], snapshot['context']])
                version = con.execute('SELECT COALESCE(MAX(version),0)+1 FROM associations WHERE lookup_key=?', (key,)).fetchone()[0]
                record = {**snapshot, 'id': str(uuid.uuid4()), 'version': version, 'status': 'active',
                          'confirmed_at': datetime.now(timezone.utc).isoformat()}
                con.execute('INSERT INTO associations VALUES (?,?,?,?,?)',
                            (record['id'], key, version, capture_key, _json(record)))
                records.append(record)
                stored += 1
        return {'stored': stored, 'records': records, 'database_path': str(self.path)}

    def query(self, identity, context):
        context = normalize_context(context)
        identity = identity_key(identity)
        if not identity['partno'] or not identity['footprint']:
            return {'status': 'not_found', 'reason': 'insufficient_identity'}
        key = _json([identity, context])
        with self.connection() as con:
            records = [json.loads(row[0]) for row in con.execute(
                'SELECT document FROM associations WHERE lookup_key=? ORDER BY version DESC', (key,))]
        records = [record for record in records if record['status'] == 'active']
        if not records:
            return {'status': 'not_found'}
        if len({record['parameter_hash'] for record in records}) > 1:
            return {'status': 'conflict', 'records': records}
        return {'status': 'matched', 'record': records[0]}

    def list(self, query='', include_revoked=False):
        with self.connection() as con:
            records = [json.loads(row[0]) for row in con.execute('SELECT document FROM associations ORDER BY rowid DESC')]
        return [record for record in records if (include_revoked or record['status'] == 'active')
                and query.casefold() in _json({key: value for key, value in record.items() if key != 'xml'}).casefold()]

    def revoke(self, record_id, reason):
        if not reason.strip():
            raise ValueError('association_revocation: 必须提供撤销原因')
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT document FROM associations WHERE id=?', (record_id,)).fetchone()
            if row is None:
                raise ValueError('association_not_found: 确认记录不存在')
            record = json.loads(row[0])
            if record['status'] != 'revoked':
                record.update(status='revoked', revocation_reason=reason.strip(),
                              revoked_at=datetime.now(timezone.utc).isoformat())
                con.execute('UPDATE associations SET document=? WHERE id=?', (_json(record), record_id))
        return record
