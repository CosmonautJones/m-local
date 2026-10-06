from pathlib import Path, PureWindowsPath
import hashlib
import json
import struct
import sys

catalog, package_root, roots_file, output = map(Path, sys.argv[1:])
data = catalog.read_bytes()
package_root = package_root.resolve()
site_root = package_root.parent
roots = json.loads(roots_file.read_text())
assert not any(data.count(value.encode()) for value in roots.values())
header = struct.unpack_from('<8sI6I8QII', data)
assert header[:2] == (b'JSCAT005', 5)
assert header[8] == 108 and list(header[8:16]) == sorted(header[8:16])
strings = []
for sid in range(header[2]):
    offset, length = struct.unpack_from('<II', data, header[8] + sid * 8)
    start = header[9] + offset
    assert header[9] <= start <= start + length <= header[10]
    strings.append(data[start:start + length].decode())
roles = {sid: [] for sid in range(len(strings))}
paths = []
modules = []
module_types = []
tables = [(name, header[count], header[offset]) for name, count, offset in
          [('module', 3, 10), ('scope', 4, 11), ('symbol', 5, 12), ('type', 6, 13), ('shared', 7, 14)]]
starts = {header[15] + struct.unpack_from('<I', data, table + index * 4)[0]
          for _, count, table in tables for index in range(count)}
assert min(starts) == header[15] and max(starts) < len(data)
bounds = dict(zip(sorted(starts), sorted(starts)[1:] + [len(data)]))

for table_name, count, table in tables:
    assert table + count * 4 <= header[15]
    for index in range(count):
        cursor = header[15] + struct.unpack_from('<I', data, table + index * 4)[0]
        end = bounds[cursor]
        def read():
            global cursor
            value, shift = 0, 0
            while True:
                assert cursor < end and shift < 64
                byte = data[cursor]
                cursor += 1
                value |= (byte & 127) << shift
                if byte < 128:
                    return value
                shift += 7
        def skip(number=1):
            for _ in range(number):
                read()
        def refs():
            number = read()
            assert number <= end - cursor
            skip(number)
        def string(role):
            sid = read()
            assert sid < len(strings)
            roles[sid].append(dict(table=table_name, index=index, role=role))
            return strings[sid]
        def path(role):
            value = string(role)
            if value:
                assert not Path(value).is_absolute() and not PureWindowsPath(value).is_absolute(), (table_name, index, role, value)
                assert '\\' not in value and '\0' not in value
                target = (package_root / value).resolve()
                assert target.is_relative_to(site_root), (role, value)
                assert target.exists(), ('missing catalog target', table_name, index, role, value, str(target))
                kind = 'directory' if value in ('.', '..') else 'file'
                assert target.is_dir() if kind == 'directory' else target.is_file(), (role, value, kind)
                paths.append(dict(table=table_name, index=index, role=role, encoded=value,
                                  resolved=str(target), target_kind=kind))
            return value
        def literal():
            kind = read()
            assert kind in (0, 1, 2, 3)
            if kind == 1:
                string('literal_value')
            elif kind:
                skip()
        if table_name == 'module':
            name, rel = string('name'), path('module_path')
            skip(2)
            string('decided_codespace')
            modules.append(dict(index=index, name=name, encoded=rel))
        elif table_name == 'scope':
            skip()
            string('name')
            skip(9)
            for _ in range(read()):
                string('member_name')
                skip()
            for _ in range(read()):
                string('overload_name')
                refs()
            for _ in range(read()):
                string('child_name')
                skip()
        elif table_name == 'symbol':
            string('name')
            string('symbol_type')
            skip(10)
            string('alias_name')
            skip(6)
        elif table_name == 'type':
            tag = read()
            skip()
            assert 0 <= tag <= 9
            if tag == 0:
                skip(2)
            elif tag == 1:
                pass
            elif tag == 2:
                skip()
                string('foreign_scalar')
            elif tag == 3:
                name, rel = string('module_name'), path('module_type_path')
                skip(2)
                module_types.append(dict(index=index, name=name, encoded=rel))
            elif tag == 4:
                string('typevar_name')
                skip(2)
                refs()
            elif tag == 5:
                skip()
                refs()
                string('alias_name')
                literal()
                string('distinct_key')
            elif tag == 6:
                string('function_name')
                skip(5)
                refs()
                for _ in range(read()):
                    string('parameter_name')
                    skip(4)
            elif tag in (7, 8):
                refs()
            elif tag == 9:
                skip()
                string('enum_member_name')
                skip()
                literal()
        elif table_name == 'shared':
            string('class_name')
            bits = read()
            if bits & 128:
                skip()
                string('dotted_name')
                path('shared_identity_path')
                skip(2)
            else:
                skip()
                refs()
                refs()
                refs()
                for _ in range(read()):
                    string('typed_dict_field_name')
                    skip()
                skip()
                for _ in range(read()):
                    string('enum_member_name')
                    skip()
                    literal()
                for _ in range(read()):
                    string('compile_time_parameter_name')
                for _ in range(read()):
                    string('derived_special_name')
                    skip()
                path('shared_identity_path')
                skip(2)
        assert cursor == end, (table_name, index, cursor, end)

for name, sid in [('key', header[16]), ('ambient_typing_names', header[17])]:
    assert sid < len(strings)
    roles[sid].append(dict(table='header', index=0, role=name))
absolute_strings = []
for sid, value in enumerate(strings):
    if Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
        uses = roles[sid]
        assert value in ('/', '\\/') and uses and all(row['role'] == 'literal_value' for row in uses), (sid, value, uses)
        absolute_strings.append(dict(string_id=sid, value=value, uses=uses))
assert sum(bool(row['encoded']) for row in modules) == 587
assert len(module_types) == 161
assert {row['value'] for row in absolute_strings} == {'/', '\\/'}
result = dict(status='passed', scope='Complete standalone catalog record decoding, relative resolution fields and existing contained physical targets',
              catalog_sha256=hashlib.sha256(data).hexdigest(), catalog_bytes=len(data),
              package_root=str(package_root), allowed_site_root=str(site_root),
              record_counts={name: count for name, count, _ in tables},
              string_count=len(strings), all_records_fully_decoded=True,
              module_path_records_verified=587, module_type_records_verified=161,
              module_records=modules, module_types=module_types, physical_paths=paths,
              absolute_literal_strings=absolute_strings,
              build_root_occurrences={name: data.count(value.encode()) for name, value in roots.items()},
              executed_audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: result[key] for key in ('status', 'catalog_sha256', 'record_counts', 'string_count', 'module_path_records_verified', 'module_type_records_verified')}))
