from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile

os.umask(0o077)
root = Path('/var/tmp/m-local-kali-file-trace-01a1050e')
directory = Path(tempfile.mkdtemp(prefix='m-local-trace-environment-control-', dir='/var/tmp'))
os.chown(directory, 65534, 65534)
env = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8', LD_LIBRARY_PATH=str(root / 'root/usr/lib/x86_64-linux-gnu'))
trace = directory / 'file.trace'
subprocess.run([str(root / 'root/usr/bin/strace'), '-f', '-qq', '-e', 'trace=openat', '-E', 'LD_LIBRARY_PATH', '-o', str(trace),
                '/usr/bin/python3', '-B', '-c', 'import os; assert "LD_LIBRARY_PATH" not in os.environ'],
               env=env, user=65534, group=65534, extra_groups=[], check=True, timeout=20)
result = dict(status='passed', scope='Tracing client-only library environment removed from tracee', workspace=str(directory),
              trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(),
              executed_probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
(directory / 'executed-probe.py').write_bytes(Path(__file__).read_bytes())
print(json.dumps(result))
