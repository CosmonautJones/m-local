from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys

task = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
origin = Path('/var/tmp/m-local-runtime-package-70g1w4vw')
directory = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/runtime-catalog-path-control-v3')
directory.mkdir()
probe = directory / 'executed-audit.py'
probe.write_bytes((task / 'work/runtime-catalog-path-audit.py').read_bytes())
(directory / 'executed-controls.py').write_bytes(Path(__file__).read_bytes())
data = (origin / 'stubcat.bin').read_bytes()
original_hash = hashlib.sha256(data).hexdigest()
header = list(struct.unpack_from('<8sI6I8QII', data))
rows = []
def run(name, body, expected_error=None):
    catalog = directory / (name + '.bin')
    catalog.write_bytes(body)
    output = directory / (name + '.json')
    process = subprocess.run([sys.executable, '-B', str(probe), str(catalog), str(origin / 'stage/site/jaclang'),
                              str(origin / 'classifier-roots.json'), str(output)], capture_output=True, text=True)
    assert process.returncode == (1 if expected_error else 0), (name, process.stdout, process.stderr)
    if expected_error:
        assert expected_error in process.stderr, (name, process.stderr)
    else:
        baseline = json.loads(output.read_text())
        assert baseline['status'] == 'passed' and baseline['all_records_fully_decoded']
    row = dict(name=name, status='passed', exit_code=process.returncode,
               expected_result='rejected' if expected_error else 'accepted',
               mutation_sha256=hashlib.sha256(body).hexdigest(), diagnostic=process.stderr.strip())
    rows.append(row)
    print(json.dumps(dict(name=name, status='passed')), flush=True)
run('complete-physical-catalog', data)
baseline = json.loads((directory / 'complete-physical-catalog.json').read_text())
target = next(row['encoded'] for row in baseline['physical_paths'] if row['role'] == 'module_type_path' and len(row['encoded']) > 20)
position = data.index(target.encode(), header[9], header[10])
absolute = bytearray(data)
absolute[position] = ord('/')
run('unknown-absolute-resolution-field', absolute, 'module_path')
missing = bytearray(data)
missing[position + len(target) - 1] = ord('q')
run('missing-relative-target', missing, 'missing catalog target')
escape = bytearray(data)
escape[position:position + len(target)] = b'../../../../' + b'x' * (len(target) - 12)
run('payload-containment-escape', escape, 'module_path')
python_escape = bytearray(data)
python_path = b'../../python/bin/python3.14'
assert len(python_path) <= len(target)
python_escape[position:position + len(target)] = python_path + b'/' * (len(target) - len(python_path))
run('python-payload-traversal', python_escape, 'module_path')
unknown = b'/unreferenced-build-folder/module.pyi'
new_header = header.copy()
new_header[2] += 1
new_header[9] += 8
for index in range(10, 16):
    new_header[index] += 8 + len(unknown)
new_entry = struct.pack('<II', header[10] - header[9], len(unknown))
unreferenced = (struct.pack('<8sI6I8QII', *new_header) + data[108:header[9]] + new_entry +
                data[header[9]:header[10]] + unknown + data[header[10]:])
run('unreferenced-absolute-string', unreferenced, '/unreferenced-build-folder/module.pyi')
assert hashlib.sha256((origin / 'stubcat.bin').read_bytes()).hexdigest() == original_hash
result = dict(status='passed', scope='Complete physical catalog audit and five controlled rejection cases, including traversal into Python; origin remains byte unchanged',
              cases=rows, catalog_sha256=original_hash, audit_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
              executed_controls_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
