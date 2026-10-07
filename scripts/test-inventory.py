#!/usr/bin/env python3
"""Bind named Jac test definitions to strict outcomes, without a count target."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

DECLARATION = re.compile(r'^test\s+("(?:[^"\\]|\\.)+")\s*\{', re.MULTILINE)
OUTCOME = re.compile(r'^(PASSED|FAILED|SKIPPED)\s+(.+?)\s+\[([^]]+)\]')
ANSI = re.compile(r'\x1b\[[0-9;]*m')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body_end(source: str, start: int) -> int:
    """Match braces while ignoring Jac comments and quoted string contents."""
    depth, position = 1, start
    while position < len(source):
        char = source[position]
        if char == '#':
            newline = source.find('\n', position)
            position = len(source) if newline < 0 else newline + 1
            continue
        if char in ('"', "'"):
            quote = char * 3 if source.startswith(char * 3, position) else char
            position += len(quote)
            while position < len(source):
                if source[position] == '\\':
                    position += 2
                elif source.startswith(quote, position):
                    position += len(quote)
                    break
                else:
                    position += 1
            continue
        depth += (char == '{') - (char == '}')
        position += 1
        if depth == 0:
            return position
    raise ValueError('Unclosed test body; inventory cannot certify this source.')


def declarations(root: Path) -> list[dict]:
    result = []
    for path in sorted((root / 'services').glob('*.test.jac')):
        source = path.read_text(encoding='utf-8')
        for match in DECLARATION.finditer(source):
            end = body_end(source, match.end())
            body = source[match.start():end]
            first_line = source.count('\n', 0, match.start()) + 1
            result.append({
                'name': json.loads(match.group(1)),
                'path': path.relative_to(root).as_posix(),
                'line': first_line,
                'body_sha256': hashlib.sha256(body.encode()).hexdigest(),
                'assertion_lines': [first_line + body.count('\n', 0, assertion.start())
                                    for assertion in re.finditer(r'\bassert\b', body)],
                'core_expected': path.name != 'business_ai.test.jac',
            })
    return result


def outcomes(path: Path) -> list[dict]:
    result = []
    for line in ANSI.sub('', path.read_text(encoding='utf-8')).splitlines():
        if match := OUTCOME.match(line):
            result.append({'result': match[1], 'name': match[2].strip(), 'entry': match[3]})
    return result


def git_value(root: Path, *arguments: str) -> str | None:
    reply = subprocess.run(['git', '-C', str(root), *arguments], text=True,
                           capture_output=True, check=False)
    return reply.stdout.strip() if reply.returncode == 0 else None


def source_manifest(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): digest(path)
            for path in sorted(root.rglob('*')) if path.is_file()
            and not any(part in {'.jac', '.git', 'node_modules', '.venv'} for part in path.relative_to(root).parts)
            and (path.suffix in {'.jac', '.py', '.pyi'} or path.name == 'jac.toml')}


def record_binding() -> int:
    operation, root_arg, workspace_arg, runtime_arg, output_arg, log_arg, *tail = sys.argv[1:]
    root, workspace = Path(root_arg).resolve(), Path(workspace_arg).resolve()
    output, log = Path(output_arg), Path(log_arg)
    if operation == 'record-start':
        binding = dict(run_id=str(uuid.uuid4()), suite='core',
            candidate_sha=git_value(root, 'rev-parse', 'HEAD'),
            git_status=git_value(root, 'status', '--porcelain'),
            runner_sha256=digest(root / 'scripts/test.sh'),
            source_manifest=source_manifest(workspace),
            runtime_version=subprocess.check_output([runtime_arg, '--version'], text=True).strip(),
            runtime_bin_sha256=digest(Path(runtime_arg)),
            invocation=['jac', 'test', '--verbose', *tail], strict=True, exit_code=None)
        output.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"Release test binding: {binding['run_id']}\n", encoding='utf-8')
        print(log.read_text(encoding='utf-8'), end='')
    else:
        binding = json.loads(output.read_text(encoding='utf-8'))
        binding['exit_code'] = int(tail[0])
        binding['source_unchanged'] = binding['source_manifest'] == source_manifest(workspace)
        binding['log_sha256'] = digest(log)
    output.write_text(json.dumps(binding, indent=2) + '\n', encoding='utf-8')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--core-log', type=Path, required=True)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--historical-base', type=Path)
    parser.add_argument('--historical-experience', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    definitions = declarations(root)
    actual = outcomes(args.core_log)
    binding = json.loads(args.binding.read_text(encoding='utf-8'))
    binding_errors = []
    log_text = ANSI.sub('', args.core_log.read_text(encoding='utf-8'))
    if f"Release test binding: {binding.get('run_id')}" not in log_text:
        binding_errors.append('Log does not identify this isolated test run.')
    if binding.get('suite') != 'core' or binding.get('exit_code') != 0:
        binding_errors.append('The bound core command did not complete successfully.')
    if binding.get('runner_sha256') != digest(root / 'scripts/test.sh'):
        binding_errors.append('Runner changed after the tested run.')
    if binding.get('candidate_sha') != git_value(root, 'rev-parse', 'HEAD'):
        binding_errors.append('Candidate revision differs from the tested run.')
    if binding.get('log_sha256') != digest(args.core_log) or not binding.get('source_unchanged'):
        binding_errors.append('Log mismatch or isolated source changed during execution.')
    if binding.get('git_status') or git_value(root, 'status', '--porcelain'):
        binding_errors.append('Coverage certification requires a clean frozen candidate.')
    if binding.get('source_manifest') != source_manifest(root):
        binding_errors.append('Current source inventory differs from the isolated test input.')
    for path, checksum in binding.get('source_manifest', {}).items():
        current = root / path
        if not current.is_file() or digest(current) != checksum:
            binding_errors.append(f'Tested source changed: {path}')
    if not binding.get('source_manifest') or '0.37.23' not in binding.get('runtime_version', ''):
        binding_errors.append('Missing source manifest or pinned runtime identity.')
    expected = {item['name'] for item in definitions if item['core_expected']}
    passed = {item['name'] for item in actual if item['result'] == 'PASSED'}
    missing = sorted(expected - passed)
    unsuccessful = [item for item in actual if item['result'] != 'PASSED']
    inventory = {
        'candidate_sha': git_value(root, 'rev-parse', 'HEAD'),
        'git_status': git_value(root, 'status', '--porcelain'),
        'runner_sha256': digest(root / 'scripts/test.sh'),
        'core_log_sha256': digest(args.core_log),
        'binding_sha256': digest(args.binding), 'tested_binding': binding,
        'binding_errors': binding_errors,
        'declarations': definitions, 'outcomes': actual,
        'expected_distinct': len(expected), 'passed_distinct': len(passed),
        'execution_count': len(actual), 'missing_expected': missing,
        'unsuccessful_outcomes': unsuccessful,
        'scope': 'Named definitions and lexical assertion locations, not branch coverage. '
                 'Assertion locations are lexical tokens and may include comments/strings; '
                 'they are not a semantic assertion or branch-coverage count. '
                 'The optional paid business_ai suite is excluded from core expectations.',
    }
    if args.historical_base and args.historical_experience:
        old = Counter(item['name'] for item in outcomes(args.historical_base))
        new = Counter(item['name'] for item in outcomes(args.historical_experience))
        inventory['historical'] = {
            'base_sha256': digest(args.historical_base),
            'experience_sha256': digest(args.historical_experience),
            'base_executions': sum(old.values()), 'base_distinct': len(old),
            'experience_executions': sum(new.values()), 'experience_distinct': len(new),
            'absent_names': sorted(old.keys() - new.keys()),
            'fewer_repetitions': sum((old - new).values()),
            'added_executions': sum((new - old).values()),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
    print(f'Core inventory: {len(passed)}/{len(expected)} expected names; '
          f'{len(actual)} executions; {len(unsuccessful)} non-pass outcomes.')
    if not actual or missing or unsuccessful or binding_errors:
        print('Inventory refused: missing/unsuccessful outcomes or mismatched source binding.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(record_binding() if len(sys.argv) > 1 and sys.argv[1] in
                     {'record-start', 'record-finish'} else main())
