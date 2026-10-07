#!/usr/bin/env python3
"""Report this repository's source-byte composition as informational evidence.

The mappings match GitHub's language API exactly for main at 9a2980e. Count Git
blobs, not Windows checkout bytes; retain tests and operational scripts. Recheck
the mapping against GitHub when introducing other languages or vendored sources.
"""
import argparse
from collections import Counter
import json
from pathlib import PurePosixPath
import subprocess


LANGUAGES = {
    '.jac': 'Jac', '.py': 'Python', '.pyi': 'Python',
    '.js': 'JavaScript', '.jsx': 'JavaScript', '.mjs': 'JavaScript',
    '.ts': 'TypeScript', '.tsx': 'TypeScript',
    '.ps1': 'PowerShell', '.sh': 'Shell', '.cmd': 'Batchfile',
    '.css': 'CSS', '.html': 'HTML',
}


def inventory(revision):
    tree = subprocess.check_output(['git', 'ls-tree', '-rlz', revision])
    totals = Counter()
    for record in tree.split(b'\0'):
        if not record:
            continue
        metadata, raw_path = record.split(b'\t', 1)
        path = raw_path.decode('utf-8')
        # Linguist's default generated-file handling excludes TS declarations.
        if path.endswith('.d.ts'):
            continue
        language = LANGUAGES.get(PurePosixPath(path).suffix)
        if language:
            totals[language] += int(metadata.split()[3])
    return dict(sorted(totals.items()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    args = parser.parse_args()
    languages = inventory(args.ref)
    total = sum(languages.values())
    share = 100 * languages.get('Jac', 0) / total if total else 0
    print(json.dumps(dict(revision=args.ref, language_bytes=languages,
                         total_bytes=total, jac_percent=round(share, 2),
                         policy='informational'), indent=2))
