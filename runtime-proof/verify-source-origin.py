#!/usr/bin/env python3
"""Authenticate the fixed GitHub source-proof job and its logged contract.

The expected commit must come from the reviewed producer checkout, not from an
artifact. The CLI reads GitHub directly using gh; the offline function assumes
its metadata and log were obtained through that same trusted API boundary.
This does not download, execute, or verify the contents of the source artifact.
"""
import argparse
from datetime import datetime, timedelta
import json
import os
import re
import subprocess
import sys
import threading


REPOSITORY = 'CosmonautJones/m-local'
REPOSITORY_ID = 1389740586
WORKFLOW_ID = 376097532
WORKFLOW_PATH = '.github/workflows/runtime-source-proof.yml'
BRANCH = 'codex/runtime-verification'
API_ROOT = 'repos/' + REPOSITORY + '/actions/'
MAX_METADATA_BYTES = 1024 ** 2
MAX_LOG_BYTES = 4 * 1024 ** 2
MAX_ARTIFACT_BYTES = 2 * 1024 ** 2
GH_SECONDS = 30
STEPS = (
    'Checkout public proof inputs',
    'Check source runner output and mount binding',
    'Check sanitized source handoff verifier',
    'Check source producer and export boundaries',
    'Check sanitized source failure context',
    'Check fresh matrix loader provenance binding',
    'Run fresh source/bootstrap/matrix proof',
    'Verify exported source handoff',
    'Retain verified public source handoff',
)
CHECKS = [
    'host-controls', 'fresh-64Gi-storage', 'public-app-revision',
    'public-pinned-downloads', 'postgres-distribution', 'dependency-priming-pillow',
    'fresh-forks-80fd-d363', 'cold-compile-before-after', 'bootstrap-53',
    'matrix-10-plus-2', 'scrubbed-36-file-contract',
]
SUMMARY_PINS = {
    'application_revision': 'b0f2321016ba004b3a77db6fe05828080c755cd3',
    'application_digest': '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42',
    'jac_base': '58cb97eb75cdff8b5ee78f4094ca2be16376601c',
    'jac_sha256': '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad',
    'jacpython_sha256': '198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542',
    'shim_sha256': '02f499e9becacf36161aa9f4b39a9f950f4dd8dbcb744acded0f04618652b4de',
    'typeshed_inventory_sha256': '1fd7fa02ccc83ad6a6a1fe7451231911a030a70d6f9d166c6d6b7d2715ce648a',
    'helper_sha256': '72fa698df809ec63c0d2cd7ce1c9d51bd5ee8a9e2b0bfba5bff979814217837b',
}


def fail(label):
    raise RuntimeError(label)


def integer(value, label):
    if type(value) is not int or value <= 0:
        fail(label)
    return value


def pattern(value, expression, label):
    if type(value) is not str or re.fullmatch(expression, value) is None:
        fail(label)
    return value


def timestamp(value):
    pattern(value, r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z', 'GitHub timestamp')
    stamp = value[:-1]
    if '.' in stamp:
        base, fraction = stamp.split('.', 1)
        stamp = base + '.' + (fraction + '000000')[:6]
    try:
        return datetime.fromisoformat(stamp + '+00:00')
    except ValueError:
        fail('GitHub timestamp')


def object_value(value, label):
    if type(value) is not dict:
        fail(label)
    return value


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail('duplicate JSON key')
        result[key] = value
    return result


def read_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError, RecursionError):
        fail('GitHub JSON response')


def verify_run(run, expected_commit, expected_run_id):
    pattern(expected_commit, r'[0-9a-f]{40}', 'expected source commit')
    pattern(expected_run_id, r'[1-9][0-9]{0,19}', 'expected source run')
    run = object_value(run, 'source run metadata')
    if integer(run.get('id'), 'source run ID') != int(expected_run_id) or \
            run.get('head_sha') != expected_commit or run.get('head_branch') != BRANCH or \
            integer(run.get('workflow_id'), 'source workflow ID') != WORKFLOW_ID or run.get('path') != WORKFLOW_PATH or \
            run.get('event') not in ('push', 'workflow_dispatch'):
        fail('source run identity')
    for key in ('repository', 'head_repository'):
        repository = object_value(run.get(key), 'source repository metadata')
        if integer(repository.get('id'), 'source repository ID') != REPOSITORY_ID or repository.get('full_name') != REPOSITORY:
            fail('source repository identity')
    if run.get('status') != 'completed' or run.get('conclusion') != 'success':
        fail('source run not successful')
    return integer(run.get('run_attempt'), 'source run attempt')


def one_entry(response, key):
    response = object_value(response, 'GitHub list response')
    rows = response.get(key)
    if type(response.get('total_count')) is not int or response['total_count'] != 1 or \
            type(rows) is not list or len(rows) != 1:
        fail('source ' + key + ' cardinality')
    return object_value(rows[0], 'source ' + key + ' metadata')


def verify_job(jobs, expected_commit, expected_run_id, attempt):
    job = one_entry(jobs, 'jobs')
    integer(job.get('id'), 'source job ID')
    if integer(job.get('run_id'), 'source job run ID') != int(expected_run_id) or \
            integer(job.get('run_attempt'), 'source job attempt') != attempt or \
            job.get('name') != 'source-proof' or job.get('head_sha') != expected_commit or \
            job.get('runner_group_name') != 'GitHub Actions' or job.get('labels') != ['ubuntu-24.04']:
        fail('source job identity')
    if job.get('status') != 'completed' or job.get('conclusion') != 'success':
        fail('source job not successful')
    start, end = timestamp(job.get('started_at')), timestamp(job.get('completed_at'))
    if end < start:
        fail('source job time order')
    steps = job.get('steps')
    if type(steps) is not list or not len(STEPS) <= len(steps) <= 20:
        fail('source job steps')
    by_name = {}
    previous_number, previous_end = 0, start
    for step in steps:
        step = object_value(step, 'source step metadata')
        name = step.get('name')
        number = integer(step.get('number'), 'source step number')
        if type(name) is not str or name in by_name or number <= previous_number or \
                step.get('status') != 'completed' or step.get('conclusion') != 'success':
            fail('source step identity or success')
        step_start, step_end = timestamp(step.get('started_at')), timestamp(step.get('completed_at'))
        if not previous_end <= step_start <= step_end <= end:
            fail('source step time order')
        by_name[name] = (number, step_start, step_end)
        previous_number, previous_end = number, step_end
    if any(name not in by_name for name in STEPS) or \
            [by_name[name][0] for name in STEPS] != sorted(by_name[name][0] for name in STEPS):
        fail('required source steps')
    return job, by_name


def verify_artifact(artifacts, expected_commit, expected_run_id, upload):
    artifact = one_entry(artifacts, 'artifacts')
    integer(artifact.get('id'), 'source artifact ID')
    name = 'm-local-source-handoff-' + expected_commit + '-' + expected_run_id
    size = integer(artifact.get('size_in_bytes'), 'source artifact size')
    pattern(artifact.get('digest'), r'sha256:[0-9a-f]{64}', 'source artifact digest')
    if artifact.get('name') != name or size > MAX_ARTIFACT_BYTES or artifact.get('expired') is not False:
        fail('source artifact identity or expiry')
    run = object_value(artifact.get('workflow_run'), 'source artifact run metadata')
    if integer(run.get('id'), 'source artifact run ID') != int(expected_run_id) or \
            integer(run.get('repository_id'), 'artifact repository ID') != REPOSITORY_ID or \
            integer(run.get('head_repository_id'), 'artifact head repository ID') != REPOSITORY_ID or \
            run.get('head_sha') != expected_commit or run.get('head_branch') != BRANCH:
        fail('source artifact run identity')
    created, updated = timestamp(artifact.get('created_at')), timestamp(artifact.get('updated_at'))
    expires = timestamp(artifact.get('expires_at'))
    # REST timestamps have second precision; logs may have subsecond precision.
    if not upload[1] <= created <= updated < upload[2] + timedelta(seconds=1) or expires <= updated:
        fail('source artifact upload window')
    return artifact


def verify_log(log, expected_commit, expected_run_id, native):
    if type(log) is not str or not 0 < len(log.encode('utf-8')) <= MAX_LOG_BYTES:
        fail('source job log size')
    candidates = []
    for line in log.splitlines():
        match = re.fullmatch(r'(\S+) (\{.*\})', line)
        if match is None:
            continue
        value = read_json(match[2])
        if type(value) is dict and ('handoff' in value or 'status_scope' in value):
            candidates.append((timestamp(match[1]), value))
    if len(candidates) != 1:
        fail('source summary cardinality')
    when, summary = candidates[0]
    if not native[1] <= when < native[2] + timedelta(seconds=1):
        fail('source summary native window')
    if summary.get('status') != 'passed' or summary.get('github_sha') != expected_commit or \
            summary.get('checks') != CHECKS or summary.get('external_jac_db_url') is not False or \
            summary.get('source_override') != 'leaf receipts only' or \
            summary.get('status_scope') != 'prepared source proof; no package/adoption/deployment' or \
            any(summary.get(key) != value for key, value in SUMMARY_PINS.items()):
        fail('source summary identity or scope')
    handoff = object_value(summary.get('handoff'), 'source summary handoff')
    verified = object_value(handoff.get('verification'), 'source summary verification')
    contract = pattern(handoff.get('contract_sha256'), r'[0-9a-f]{64}', 'source contract hash')
    total = integer(handoff.get('total_bytes'), 'source handoff bytes')
    if handoff.get('status') != 'prepared_not_uploaded' or type(handoff.get('member_count')) is not int or \
            handoff['member_count'] != 36 or total > 1024 ** 2 or \
            verified.get('status') != 'passed' or verified.get('scope') != 'sanitized commitment bundle verification' or \
            verified.get('contract_sha256') != contract or verified.get('commit_sha') != expected_commit or \
            verified.get('run_id') != expected_run_id or type(verified.get('member_count')) is not int or \
            verified['member_count'] != 36 or type(verified.get('total_bytes')) is not int or verified['total_bytes'] != total:
        fail('source handoff commitment')
    return contract


def verify_origin(run, jobs, artifacts, log, *, expected_commit, expected_run_id):
    attempt = verify_run(run, expected_commit, expected_run_id)
    job, steps = verify_job(jobs, expected_commit, expected_run_id, attempt)
    artifact = verify_artifact(artifacts, expected_commit, expected_run_id, steps[STEPS[-1]])
    contract = verify_log(log, expected_commit, expected_run_id, steps[STEPS[-3]])
    return {'status': 'passed', 'scope': 'successful source-proof origin commitment',
            'run_id': int(expected_run_id), 'job_id': job['id'], 'artifact_id': artifact['id'],
            'artifact_name': artifact['name'], 'artifact_digest': artifact['digest'],
            'artifact_size': artifact['size_in_bytes'], 'contract_sha256': contract}


def gh_read_bytes(endpoint, limit):
    env = dict(os.environ)
    env.pop('GH_DEBUG', None)
    command = ['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
               '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: 2026-03-10', endpoint]
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as process:
            timer = threading.Timer(GH_SECONDS, process.kill)
            timer.daemon = True
            timer.start()
            try:
                raw = process.stdout.read(limit + 1)
                if len(raw) > limit:
                    process.kill()
                    fail('GitHub response size')
                if process.wait() != 0:
                    fail('GitHub request failed')
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                    process.wait()
    except OSError:
        fail('GitHub client unavailable')
    return raw


def gh_read(endpoint, limit):
    raw = gh_read_bytes(endpoint, limit)
    try:
        return raw.decode('utf-8')
    except UnicodeError:
        fail('GitHub response encoding')


def authenticate_origin(expected_commit, expected_run_id):
    pattern(expected_commit, r'[0-9a-f]{40}', 'expected source commit')
    pattern(expected_run_id, r'[1-9][0-9]{0,19}', 'expected source run')
    run_endpoint = API_ROOT + 'runs/' + expected_run_id
    run = read_json(gh_read(run_endpoint, MAX_METADATA_BYTES))
    attempt = verify_run(run, expected_commit, expected_run_id)
    jobs = read_json(gh_read(run_endpoint + '/attempts/' + str(attempt) + '/jobs?per_page=100', MAX_METADATA_BYTES))
    job, steps = verify_job(jobs, expected_commit, expected_run_id, attempt)
    artifacts = read_json(gh_read(run_endpoint + '/artifacts?per_page=100', MAX_METADATA_BYTES))
    verify_artifact(artifacts, expected_commit, expected_run_id, steps[STEPS[-1]])
    log = gh_read(API_ROOT + 'jobs/' + str(job['id']) + '/logs', MAX_LOG_BYTES)
    result = verify_origin(run, jobs, artifacts, log,
                           expected_commit=expected_commit, expected_run_id=expected_run_id)
    latest = read_json(gh_read(run_endpoint, MAX_METADATA_BYTES))
    if verify_run(latest, expected_commit, expected_run_id) != attempt:
        fail('source run attempt changed')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--expected-run-id', required=True)
    args = parser.parse_args(argv)
    try:
        result = authenticate_origin(args.expected_commit, args.expected_run_id)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        print('source origin verification failed', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
