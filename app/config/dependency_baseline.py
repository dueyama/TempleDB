"""Read-only dependency baseline checks, usable without Django or a database."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
import tomllib
from collections import deque
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

APP_ROOT = Path(__file__).resolve().parents[1]


def installed_distributions() -> dict[str, dict]:
    return {
        canonicalize_name(distribution.metadata["Name"]): {
            "version": distribution.version,
            "requires": distribution.requires or [],
        }
        for distribution in importlib.metadata.distributions()
    }


def load_constraints(paths: list[Path], environment: dict[str, str]) -> dict[str, str]:
    """Accept exact pins and platform markers; reject ambiguous pip directives."""
    pins: dict[str, str] = {}
    for path in paths:
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            specifiers = list(requirement.specifier)
            if (
                requirement.url or requirement.extras or len(specifiers) != 1
                or specifiers[0].operator != "==" or "*" in specifiers[0].version
            ):
                raise ValueError(f"{path.name}:{line_number}: exact version pin required")
            if requirement.marker and not requirement.marker.evaluate({**environment, "extra": ""}):
                continue
            name = canonicalize_name(requirement.name)
            version = str(Version(specifiers[0].version))
            if name in pins and pins[name] != version:
                raise ValueError(f"{path.name}:{line_number}: conflicting pin for {name}")
            pins[name] = version
    return pins


def check_dependencies(
    requirements: list[str],
    pins: dict[str, str],
    installed: dict[str, dict],
    environment: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Follow active runtime dependencies, including explicitly requested extras.

    Unrelated installed packages are ignored. An active dependency absent from the
    baseline fails even if pip would accept its installed version.
    """
    queue = deque((Requirement(text), "project", "") for text in requirements)
    visited: set[tuple[str, str]] = set()
    checked: set[str] = set()
    errors: set[str] = set()
    while queue:
        requirement, parent, parent_extra = queue.popleft()
        if requirement.marker and not requirement.marker.evaluate(
            {**environment, "extra": parent_extra}
        ):
            continue
        name = canonicalize_name(requirement.name)
        checked.add(name)
        if requirement.url:
            errors.add(f"{name}: URL dependency is outside the version baseline ({parent})")
            continue
        pin = pins.get(name)
        if pin is None:
            errors.add(f"{name}: active dependency has no pin ({parent})")
        distribution = installed.get(name)
        if distribution is None:
            errors.add(f"{name}: not installed ({parent})")
            continue
        version = Version(distribution["version"])
        if pin is not None and version != Version(pin):
            errors.add(f"{name}: installed {version}, baseline {pin}")
        if version not in requirement.specifier:
            errors.add(f"{name}: installed {version} does not satisfy {requirement} ({parent})")
        for extra in {"", *requirement.extras}:
            key = (name, extra)
            if key in visited:
                continue
            visited.add(key)
            queue.extend(
                (Requirement(text), name, extra)
                for text in distribution.get("requires", [])
            )
    return sorted(checked), sorted(errors)


def check_baseline(
    app_root: Path,
    scope: str,
    *,
    installed: dict[str, dict] | None = None,
    environment: dict[str, str] | None = None,
) -> dict:
    environment = environment or default_environment()
    if environment["sys_platform"] not in {"darwin", "linux"}:
        return {
            "scope": scope,
            "python": environment["python_full_version"],
            "platform": environment["sys_platform"],
            "checked": [],
            "errors": ["Unsupported platform for the Mac/Linux baseline; "
                       "Windows uses its existing launcher and needs a separately accepted baseline."],
            "ok": False,
        }
    installed = installed if installed is not None else installed_distributions()
    dependency_root = app_root / "config/dependencies"
    pyproject = tomllib.loads((app_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    paths = [dependency_root / ("build.txt" if scope == "build" else "runtime.txt")]
    requirements = list(project["dependencies"])
    if scope == "dev":
        paths.append(dependency_root / "dev.txt")
        requirements.extend(project["optional-dependencies"]["dev"])
    pins = load_constraints(paths, environment)
    if scope == "build":
        requirements = [f"{name}=={version}" for name, version in pins.items()]
        requirements.extend(pyproject["build-system"]["requires"])
    checked, errors = check_dependencies(requirements, pins, installed, environment)
    python_requirement = Requirement("python" + project["requires-python"])
    if Version(environment["python_full_version"]) not in python_requirement.specifier:
        errors.append(f"Python {environment['python_full_version']} does not satisfy {project['requires-python']}")
    return {
        "scope": scope,
        "python": environment["python_full_version"],
        "platform": environment["sys_platform"],
        "checked": checked,
        "errors": errors,
        "ok": not errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "inventory"))
    parser.add_argument("--app-root", type=Path, default=APP_ROOT)
    parser.add_argument("--scope", choices=("runtime", "dev", "build"), default="runtime")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.command == "inventory":
        inventory = installed_distributions()
        print(json.dumps({
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
            "machine": platform.machine(),
            "packages": {name: row["version"] for name, row in sorted(inventory.items())},
        }, indent=2))
        return 0
    try:
        result = check_baseline(arguments.app_root, arguments.scope)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    if arguments.json:
        print(json.dumps(result, indent=2))
    else:
        status = "OK" if result["ok"] else "MISMATCH"
        print(f"Dependency baseline {status}: {arguments.scope}, {len(result['checked'])} packages, "
              f"Python {result['python']}, {result['platform']}")
        for error in result["errors"]:
            print(f"  {error}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
