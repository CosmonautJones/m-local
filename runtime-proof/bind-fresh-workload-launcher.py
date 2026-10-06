#!/usr/bin/env python3
"""Bind the frozen workload launcher to the dropped test identity."""

import ast
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).absolute().parents[1]
SOURCE_RELATIVE = 'runtime-proof/kali-build-resources-v2.py'
SOURCE_SHA256 = '72fa698df809ec63c0d2cd7ce1c9d51bd5ee8a9e2b0bfba5bff979814217837b'
OLD_ARGV_PREFIX = ('/usr/sbin/runuser', '-u', 'nobody', '--')
NEW_ARGV_PREFIX = ('/usr/bin/setpriv', '--reuid=65534', '--regid=65534', '--clear-groups', '--')
BOOTSTRAP_FRAGMENT = 'ready.unlink(); os.execvpe('
IDENTITY_BOOTSTRAP_FRAGMENT = (
    'ready.unlink(); assert (os.getuid()==65534 and os.geteuid()==65534 and '
    'os.getgid()==65534 and os.getegid()==65534 and os.getgroups()==[]); os.execvpe('
)


def _fail(label):
    raise ValueError(label)


def _sha(raw):
    if type(raw) is not bytes:
        _fail('launcher source bytes')
    return hashlib.sha256(raw).hexdigest()


def _source_function(raw):
    if type(raw) is not bytes or not raw:
        _fail('launcher source bytes')
    try:
        tree = ast.parse(raw.decode('utf-8'))
    except (UnicodeError, SyntaxError, ValueError):
        _fail('launcher source syntax')
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'launch_scope']
    if len(functions) != 1:
        _fail('launcher launch_scope shape')
    return functions[0]


def _adapt_function(raw):
    function = _source_function(raw)
    prefix_matches = []
    for node in ast.walk(function):
        if not isinstance(node, ast.List):
            continue
        values = [item.value if isinstance(item, ast.Constant) and type(item.value) is str else None
                  for item in node.elts]
        width = len(OLD_ARGV_PREFIX)
        for index in range(len(values) - width + 1):
            if tuple(values[index:index + width]) == OLD_ARGV_PREFIX:
                prefix_matches.append((node, index))
    if len(prefix_matches) != 1:
        _fail('launcher runuser binding')
    argv, index = prefix_matches[0]
    argv.elts[index:index + len(OLD_ARGV_PREFIX)] = [ast.Constant(value=value) for value in NEW_ARGV_PREFIX]

    bootstrap_matches = [node for node in ast.walk(function)
                         if isinstance(node, ast.Constant) and type(node.value) is str and
                         BOOTSTRAP_FRAGMENT in node.value]
    if len(bootstrap_matches) != 1 or bootstrap_matches[0].value.count(BOOTSTRAP_FRAGMENT) != 1:
        _fail('launcher bootstrap binding')
    bootstrap_matches[0].value = bootstrap_matches[0].value.replace(BOOTSTRAP_FRAGMENT, IDENTITY_BOOTSTRAP_FRAGMENT)
    ast.fix_missing_locations(function)
    return function


def adapt_launch_source(raw):
    """Return the canonical adapted launch_scope source for the frozen helper."""
    if _sha(raw) != SOURCE_SHA256:
        _fail('launcher source pin')
    function = _adapt_function(raw)
    return (ast.unparse(function) + '\n').encode('utf-8')


def _commit(value):
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{40}', value) is None:
        _fail('launcher commit')


def bind_launcher(preflight, runner, expected_commit):
    """Install the adapted launcher into the verified runner helper namespace."""
    _commit(expected_commit)
    if type(preflight) is not dict or type(runner) is not dict:
        _fail('launcher bindings')
    checked_checkout = preflight.get('checked_checkout')
    committed_file = preflight.get('committed_file')
    resource_helper = runner.get('resource_helper')
    if not callable(checked_checkout) or not callable(committed_file) or not callable(resource_helper):
        _fail('launcher bindings')
    try:
        checked_checkout(ROOT, expected_commit)
        raw = committed_file(ROOT, expected_commit, SOURCE_RELATIVE)
    except (OSError, RuntimeError, ValueError, TypeError):
        _fail('launcher committed source')
    if type(raw) is not bytes or _sha(raw) != SOURCE_SHA256:
        _fail('launcher source pin')
    adapted_raw = adapt_launch_source(raw)
    try:
        helper = resource_helper()
    except (OSError, RuntimeError, ValueError, TypeError):
        _fail('launcher resource helper')
    if type(helper) is not dict:
        _fail('launcher resource helper')
    for name in ('launch_scope', 'sample_scope', 'stop_scope', 'e_root'):
        if name not in helper or (name != 'e_root' and not callable(helper[name])):
            _fail('launcher resource helper shape')
    try:
        adapted_tree = ast.parse(adapted_raw.decode('utf-8'))
        if len(adapted_tree.body) != 1 or not isinstance(adapted_tree.body[0], ast.FunctionDef) or \
                adapted_tree.body[0].name != 'launch_scope':
            _fail('launcher adapted function shape')
        namespace = dict(helper)
        exec(compile(adapted_tree, '<adapted-launch-scope>', 'exec'), namespace)
        adapted_launch = namespace.get('launch_scope')
    except (UnicodeError, SyntaxError, TypeError, ValueError):
        _fail('launcher adapted function')
    if not callable(adapted_launch) or adapted_launch.__globals__.get('sample_scope') is not helper['sample_scope'] or \
            adapted_launch.__globals__.get('stop_scope') is not helper['stop_scope'] or \
            adapted_launch.__globals__.get('e_root') is not helper['e_root']:
        _fail('launcher adapted bindings')
    helper['launch_scope'] = adapted_launch
    return {'status': 'prepared_not_executed', 'executed': False,
            'source_helper_sha256': SOURCE_SHA256, 'adapted_launch_sha256': _sha(adapted_raw),
            'uid': 65534, 'gid': 65534, 'supplementary_groups': []}


__all__ = ['adapt_launch_source', 'bind_launcher']
