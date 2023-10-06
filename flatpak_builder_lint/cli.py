import argparse
import importlib
import importlib.resources
import json
import pkgutil
import sys
from typing import Optional, Union

import requests

from . import __version__, builddir, checks, manifest, ostree, staticfiles

for plugin_info in pkgutil.iter_modules(checks.__path__):
    importlib.import_module(f".{plugin_info.name}", package=checks.__name__)


def get_local_exceptions(appid: str) -> set:
    with importlib.resources.open_text(staticfiles, "exceptions.json") as f:
        exceptions = json.load(f)
        ret = exceptions.get(appid)

    if ret:
        return set(ret)

    return set()


def get_remote_exceptions(
    appid: str, api_url: str = "https://flathub.org/api/v2/exceptions"
) -> set:
    try:
        r = requests.get(f"{api_url}/{appid}")
        r.raise_for_status()
        ret = set(r.json())
    except requests.exceptions.RequestException:
        ret = set()

    return ret


def run_checks(
    kind: str, path: str, enable_exceptions: bool = False, appid: Optional[str] = None
) -> dict:
    match kind:
        case "manifest":
            check_method_name = "check_manifest"
            infer_appid_func = manifest.infer_appid
            check_method_arg: Union[str, dict] = manifest.show_manifest(path)
        case "builddir":
            check_method_name = "check_build"
            infer_appid_func = builddir.infer_appid
            check_method_arg = path
        case "repo":
            check_method_name = "check_repo"
            infer_appid_func = ostree.infer_appid
            check_method_arg = path
        case _:
            raise ValueError(f"Unknown kind: {kind}")

    for checkclass in checks.ALL:
        check = checkclass()

        if check_method := getattr(check, check_method_name, None):
            if callable(check_method):
                check_method(check_method_arg)

    results = {}
    if errors := checks.Check.errors:
        results["errors"] = list(errors)
    if warnings := checks.Check.warnings:
        results["warnings"] = list(warnings)
    if jsonschema := checks.Check.jsonschema:
        results["jsonschema"] = list(jsonschema)

    if enable_exceptions:
        exceptions = None

        if appid:
            appid = appid[0]
        else:
            appid = infer_appid_func(path)

        if appid:
            exceptions = get_remote_exceptions(appid)
            if not exceptions:
                exceptions = get_local_exceptions(appid)

        if exceptions:
            if "*" in exceptions:
                return {}

            results["errors"] = list(errors - set(exceptions))
            if not results["errors"]:
                results.pop("errors")

            results["warnings"] = list(warnings - set(exceptions))
            if not results["warnings"]:
                results.pop("warnings")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="A linter for Flatpak builds and flatpak-builder manifests"
    )
    parser.add_argument(
        "--version", action="version", version=f"flatpak-builder-lint {__version__}"
    )
    parser.add_argument(
        "--exceptions", help="skip allowed warnings or errors", action="store_true"
    )
    parser.add_argument("--appid", help="override app ID", type=str, nargs=1)

    parser.add_argument(
        "type",
        help="type of artifact to lint",
        choices=["builddir", "repo", "manifest"],
    )
    parser.add_argument(
        "path",
        help="path to flatpak-builder manifest or Flatpak build directory",
        type=str,
        nargs=1,
    )

    args = parser.parse_args()

    exit_code = 0

    if results := run_checks(args.type, args.path[0], args.exceptions, args.appid):
        if "errors" in results:
            exit_code = 1

        output = json.dumps(results, indent=4)
        print(output)

        if args.exceptions and not args.json:
            print()
            print(
                "If you think problems listed above are a false positive, please report it here:"
            )
            print("  https://github.com/flathub/flatpak-builder-lint")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
