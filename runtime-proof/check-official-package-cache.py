#!/usr/bin/env python3
"""Verify the official extracted payload before patched compiler imports.

This runs the exact two cache functions from the pinned recipe under the
verified bundled interpreter, without importing Jac or executing the recipe.
"""
from pathlib import Path, PurePosixPath
import ast
import hashlib
import io
import json
import stat
import sys
import tarfile


RECIPE_SHA = 'ec820c414d5a83d498f894eddcee105d5eb3e287a030c2d6b87045fe7d32129f'
OFFICIAL_SHA = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'


def verified_functions(raw):
    if hashlib.sha256(raw).hexdigest() != RECIPE_SHA:
        raise ValueError('official cache recipe pin')
    tree = ast.parse(raw)
    names = ('inventory', 'verify_official_cache')
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if [node.name for node in functions] != list(names):
        raise ValueError('official cache function inventory')
    module = ast.Module(body=functions, type_ignores=[])
    namespace = dict(Path=Path, PurePosixPath=PurePosixPath, hashlib=hashlib,
                     io=io, json=json, stat=stat, tarfile=tarfile,
                     OFFICIAL_BINARY_SHA256=OFFICIAL_SHA)
    exec(compile(module, '<pinned-official-cache-functions>', 'exec'), namespace)
    return namespace


def main():
    assert sys.version_info[:2] == (3, 14) and len(sys.argv) == 5
    recipe, official, original, output = map(Path, sys.argv[1:])
    for path in (recipe, official, original):
        assert path.is_absolute() and path.resolve() == path and not path.is_symlink()
    functions = verified_functions(recipe.read_bytes())
    payload_hash = functions['verify_official_cache'](official, original)
    inventory_hash = hashlib.sha256(json.dumps(functions['inventory'](original),
                                                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    receipt = dict(status='passed', scope='official extracted payload byte match before patched compiler imports',
                   official_binary_sha256=OFFICIAL_SHA, official_payload_sha256=payload_hash,
                   extracted_inventory_sha256=inventory_hash, recipe_sha256=RECIPE_SHA,
                   executed_precheck_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with output.open('x') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
