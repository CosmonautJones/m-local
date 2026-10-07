"""Offline sample fixture using the native application's registered Jac types.

Run only after the disposable API writer has stopped. Preparing the unchanged
main entry supplies its model namespace without executing a fixture entry as a
different application or adding a setup endpoint to the product.
"""
import json
import os
from pathlib import Path
import time
import uuid


def validate_fixture_store():
    app = Path.cwd()
    cache_name = os.environ.get("JAC_CACHE_HOME", "")
    cache = Path(cache_name) if cache_name else None
    owned_directories = (app.parent, app, cache)
    if (app.parent.parent != Path("/var/tmp")
            or not app.parent.name.startswith("m-local-release-browser.")
            or app.name != "app"
            or os.environ.get("MLOCAL_RELEASE_BROWSER_FIXTURE") != "1"
            or not cache or not cache.is_absolute()
            or cache.resolve() != app.parent / "cache"
            or any(path.is_symlink() or not path.is_dir()
                   or path.stat().st_uid != os.geteuid()
                   or path.stat().st_mode & 0o777 != 0o700 for path in owned_directories)
            or any(os.environ.get(name) for name in ("JAC_DB_URL", "JAC_DATA_PATH", "JAC_DEV_SOURCE", "JACPATH"))):
        raise RuntimeError("Sample fixture refuses a non-disposable application store")
    return app


def main():
    app = validate_fixture_store()
    from jaclang.cli.commands.execution import _discover_config_from_file
    from jaclang.compiler.driver.application import prepare_application
    from jaclang.runtime.constants import Constants as Con
    from jaclang.runtime.prepared import application_namespace, load_prepared_module
    from jaclang.runtime.runtime import JacRuntime as Jac
    from jaclang.server.identity.user_manager import UserManager

    entry = str(app / "main.jac")
    _discover_config_from_file(entry)
    Jac.set_base_path(str(app))
    Jac.set_full_target_path(entry)
    context = Jac.create_j_context(user_root=None, base_path_dir=str(app), full_target_path=entry)
    Jac.set_context(context)
    try:
        prepared = prepare_application(entry, Jac.get_program(), str(app), [], False, False)
        models = load_prepared_module(str(app / "services/models.jac"))
        if models.Restaurant.__module__ != application_namespace(prepared) + ".services.models":
            raise RuntimeError("Sample fixture did not load the native model namespace")
        manager = UserManager(base_path=str(app))
        guest_root = manager.get_root_id(Con.GUEST.value)
        if not guest_root:
            raise RuntimeError("Sample fixture requires the existing initialized native guest root")
        Jac.set_shared_root_resolver(lambda: guest_root)
        shared = Jac.get_shared_root()
        now, suffix = time.time(), uuid.uuid4().hex
        sample_parent = models.Restaurant(slug="sample-parent-" + suffix, name="Disposable sample parent",
                                          source="release-fixture", is_demo=True)
        real_parent = models.Restaurant(slug="real-parent-" + suffix, name="Disposable real parent",
                                        source="release-fixture", is_demo=False)
        Jac.connect(shared, sample_parent)
        Jac.connect(shared, real_parent)
        unmarked = models.Offer(title="Unmarked child of sample parent", price_cents=400,
            regular_price_cents=600, quantity=1, start_ts=now - 60, end_ts=now + 3600,
            status="active", is_demo=False, qr_ready=True)
        marked = models.Offer(title="Sample child of real parent", price_cents=400,
            regular_price_cents=600, quantity=1, start_ts=now - 60, end_ts=now + 3600,
            status="active", is_demo=True, qr_ready=True)
        Jac.connect(sample_parent, unmarked, models.Publishes())
        Jac.connect(real_parent, marked, models.Publishes())
        Jac.commit()
        path = app / ".jac/release-sample-fixture.json"
        path.write_text(json.dumps({"sample_parent": sample_parent.slug, "real_parent": real_parent.slug,
            "unmarked_offer": Jac.object_ref(unmarked), "marked_offer": Jac.object_ref(marked)}))
        path.chmod(0o600)
    finally:
        context.close()


if __name__ == "__main__":
    main()
