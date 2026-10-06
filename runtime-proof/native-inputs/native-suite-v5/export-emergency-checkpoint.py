from pathlib import Path
import hashlib
import json
import shutil

task = Path(__file__).resolve().parents[1]
suite = Path('//wsl.localhost/Ubuntu/var/tmp/m-local-package-suite-r8r8tc8y')
fork = Path('//wsl.localhost/Ubuntu/var/tmp/m-local-runtime-fork-01a1050e')

def digest(root):
    paths = [root / '.jac-version', root / 'jac.toml']
    for name in ('services', 'client'):
        paths.extend(p for p in (root / name).rglob('*') if p.is_file()
            and p.suffix in ('.jac', '.py', '.mjs', '.js', '.jsx', '.css')
            and not p.name.endswith(('.test.jac', '.test.mjs', '.test.js')))
    paths.extend(p for p in root.glob('*.jac') if p.is_file() and not p.name.endswith('.test.jac'))
    paths.extend(p for p in (root / 'data').rglob('*') if p.is_file())
    result = hashlib.sha256()
    for path in sorted(set(paths), key=lambda p: p.relative_to(root).as_posix()):
        result.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return result.hexdigest()

receipt = json.loads((suite / 'result.json').read_text())
assert receipt['status'] == 'passed' and all(p['status'] == 'passed' and p['owned_process_stopped'] for p in receipt['phases'])
assert '451 passed' in (suite / 'core.log').read_text()
assert 'Ran 71 tests' in (suite / 'onboarding.log').read_text()
assert '# pass 126\n# fail 0' in (suite / 'browser.log').read_text()
assert receipt['artifact_sha256'] == hashlib.sha256((suite / 'app/dist/mobile-starter.jab').read_bytes()).hexdigest()
verified_digest = digest(suite / 'app')
current_digest = digest(task / 'work/m-local')
output = task / 'outputs/runtime-package-compatibility-v4'
assert not output.exists()
output.mkdir()
for name in ('result.json', 'app-input-files.json', 'executed-suite.py', 'check.log', 'onboarding.log',
             'analytics.log', 'runtime-cache.log', 'core.log', 'insights.log', 'python-tooling.log', 'build.log', 'browser.log'):
    shutil.copyfile(suite / name, output / name)
(output / 'summary.json').write_text(json.dumps(dict(status='passed',
    scope='Sealed ec4184 compatibility after request-local feed reuse; before existing-store guard and new runtime hash optimization',
    production_source_digest_sha256=verified_digest, current_unverified_windows_source_digest_sha256=current_digest,
    binary_sha256=receipt['binary_sha256'], runtime_patch_sha256=receipt['runtime_patch_sha256'],
    artifact_sha256=receipt['artifact_sha256'], checks=dict(onboarding=71, core=451, analytics=12,
        insights_backend=61, insights_javascript=11, compiled_ui=126),
    limitation='No capacity measurement after this change. Current operator-store guard is written but unverified; current runtime source patch differs from this sealed package.',
    runtime_installed_or_application_pin_changed=False), indent=2) + '\n')
(output / 'file-checksums.json').write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(output.iterdir())}, indent=2) + '\n')

output = task / 'outputs/runtime-materialization-regression-v1'
assert not output.exists()
output.mkdir()
for label, name in (('baseline', 'm-local-materialization-7_9uvn71'), ('passed', 'm-local-materialization-j6lkmfem')):
    path = Path('//wsl.localhost/Ubuntu/var/tmp') / name / 'result.json'
    value = json.loads(path.read_text())
    assert value['postgres_stopped'] and value['status'] == ('failed' if label == 'baseline' else 'passed')
    shutil.copyfile(path, output / (label + '-result.json'))
for name in ('runtime-materialization-probe.py', 'patch-runtime-materialization.py'):
    shutil.copyfile(task / 'work' / name, output / name)
for name in ('data/serializer.jac', 'data/impl/serializer.impl.jac', 'server/impl/session.impl.jac'):
    destination = output / 'runtime-source' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fork / 'jac/jaclang' / name, destination)
(output / 'summary.json').write_text(json.dumps(dict(status='passed_source_regression',
    scope='Eight source-fork cases; not sealed package, full lifecycle matrix, or capacity',
    runtime_patch_sha256='966f19c49173c3677ad93c944a5e9eaa2cc7eb0a60ebc00e038c0bfd2c0cf46b',
    limitations='The two-count baseline is retained. Baseline test script was not snapshotted; the exported current script removes a nonexistent Session._read_ids assertion which the failing baseline did not reach. A broader source regression runner was interrupted by emergency read-only WSL before producing a receipt.',
    installed_runtime_unchanged=True), indent=2) + '\n')
(output / 'file-checksums.json').write_text(json.dumps({p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(output.rglob('*')) if p.is_file()}, indent=2) + '\n')
print(json.dumps({'verified_app_sha256': verified_digest, 'current_unverified_app_sha256': current_digest,
    'compatibility': 'passed', 'runtime_source_regression': 'passed', 'environment': 'WSL emergency read-only; further verification interrupted'}))
