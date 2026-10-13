"""Mirror only generated application source; never touch the runtime .jac store."""
from pathlib import Path
import shutil
import sys


_WINDOWS_REPARSE_POINT = 0x400


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT
    )


def _reject_reparse_ancestors(path: Path) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    ancestors = []
    current = absolute
    while True:
        ancestors.append(current)
        if current.parent == current:
            break
        current = current.parent
    for ancestor in reversed(ancestors):
        if _is_reparse_point(ancestor):
            raise ValueError("Source and runtime paths must not contain symlinks or reparse points")


def _reject_reparse_tree(tree: Path) -> None:
    if _is_reparse_point(tree):
        raise ValueError("Application source must not contain symlinks or reparse points")
    if not tree.exists():
        return
    pending = [tree]
    while pending:
        current = pending.pop()
        for child in current.iterdir():
            if _is_reparse_point(child):
                raise ValueError("Application source must not contain symlinks or reparse points")
            if child.is_dir():
                pending.append(child)


def _sync_tree(origin: Path, destination: Path, preserved_children: tuple[str, ...] = ()) -> None:
    if not origin.exists() and not destination.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for old in sorted(destination.rglob("*"), reverse=True):
        relative = old.relative_to(destination)
        if relative.parts and relative.parts[0] in preserved_children:
            continue
        candidate = origin / relative
        if old.is_file() and not candidate.is_file():
            old.unlink()
        elif old.is_dir() and not any(old.iterdir()):
            old.rmdir()
    if origin.exists():
        for child in origin.iterdir():
            if child.name in preserved_children:
                continue
            destination_child = destination / child.name
            if child.is_dir():
                shutil.copytree(child, destination_child, dirs_exist_ok=True)
            else:
                shutil.copy2(child, destination_child)


def sync(source: Path, target: Path) -> None:
    _reject_reparse_ancestors(source)
    _reject_reparse_ancestors(target)
    source, target = source.resolve(), target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Source checkout and phone runtime must not overlap")
    if not (source / "main.jac").is_file():
        raise ValueError("Expected distinct source checkout and phone runtime")
    # Validate both trees before deleting or copying any generated source.
    directories = ("services", "client", "data", "public", "assets")
    for root in (source, target):
        for name in directories:
            _reject_reparse_tree(root / name)
    # These directories contain application source/resources, never runtime .jac.
    for name in directories:
        _sync_tree(
            source / name,
            target / name,
            preserved_children=("photos",) if name == "assets" else (),
        )


if __name__ == "__main__":
    sync(Path(sys.argv[1]), Path(sys.argv[2]))
