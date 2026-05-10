import logging
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from pipx import commands, paths
from pipx.colors import bold, red
from pipx.commands.common import expose_resources_globally
from pipx.constants import EXIT_CODE_OK, ExitCode
from pipx.emojis import sleep
from pipx.package_specifier import parse_specifier_for_upgrade
from pipx.shared_libs import shared_libs
from pipx.util import PipxError, pipx_wrap
from pipx.venv import Venv, VenvContainer

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


def _check_upgrade_available(
    venv: Venv,
    package_name: str,
    pip_args: list[str],
) -> str | None:
    """Return new version string if an upgrade is available, else None.

    Runs pip/uv install --upgrade --dry-run and parses the 'Would install'
    output to extract the new version for package_name.
    """
    package_metadata = venv.package_metadata[package_name]

    if package_metadata.package_or_url is None:
        raise PipxError(f"Internal Error: package {package_name} has corrupt pipx metadata.")

    if package_metadata.pinned:
        return None

    package_or_url = parse_specifier_for_upgrade(package_metadata.package_or_url)

    process = venv.backend.install(
        venv_root=venv.root,
        venv_python=venv.python_path,
        requirements=[package_or_url],
        pip_args=pip_args,
        upgrade=True,
        dry_run=True,
        log_pip_errors=False,
        verbose=venv.verbose,
    )

    combined = (process.stdout or "") + (process.stderr or "")
    match = re.search(r"(?i)would install (.+)", combined)
    if not match:
        return None

    canonical = re.sub(r"[-_.]+", "-", package_name).lower()
    for token in match.group(1).split():
        # tokens are "pkgname-version"; split on last hyphen before a digit
        m = re.match(r"^(.+)-([0-9][^-]*)$", token)
        if m and re.sub(r"[-_.]+", "-", m.group(1)).lower() == canonical:
            return m.group(2)
    return None


def _upgrade_package(
    venv: Venv,
    package_name: str,
    pip_args: list[str],
    is_main_package: bool,
    force: bool,
    upgrading_all: bool,
) -> int:
    """Returns 1 if package version changed, 0 if same version"""
    package_metadata = venv.package_metadata[package_name]

    if package_metadata.package_or_url is None:
        raise PipxError(f"Internal Error: package {package_name} has corrupt pipx metadata.")
    elif package_metadata.pinned:
        if package_metadata.package != venv.main_package_name:
            _LOGGER.warning(
                f"Not upgrading pinned package {package_metadata.package} in venv {venv.name}. "
                f"Run `pipx unpin {venv.name}` to unpin it."
            )
        else:
            _LOGGER.warning(f"Not upgrading pinned package {venv.name}. Run `pipx unpin {venv.name}` to unpin it.")
        return 0

    package_or_url = parse_specifier_for_upgrade(package_metadata.package_or_url)
    old_version = package_metadata.package_version

    venv.upgrade_package(
        package_name,
        package_or_url,
        pip_args,
        include_dependencies=package_metadata.include_dependencies,
        include_apps=package_metadata.include_apps,
        is_main_package=is_main_package,
        suffix=package_metadata.suffix,
    )

    package_metadata = venv.package_metadata[package_name]

    display_name = f"{package_metadata.package}{package_metadata.suffix}"
    new_version = package_metadata.package_version

    if package_metadata.include_apps:
        expose_resources_globally(
            "app",
            paths.ctx.bin_dir,
            package_metadata.app_paths,
            force=force,
            suffix=package_metadata.suffix,
        )
        expose_resources_globally("man", paths.ctx.man_dir, package_metadata.man_paths, force=force)

    if package_metadata.include_dependencies:
        for app_paths in package_metadata.app_paths_of_dependencies.values():
            expose_resources_globally(
                "app",
                paths.ctx.bin_dir,
                app_paths,
                force=force,
                suffix=package_metadata.suffix,
            )
        for man_paths in package_metadata.man_paths_of_dependencies.values():
            expose_resources_globally("man", paths.ctx.man_dir, man_paths, force=force)

    if old_version == new_version:
        if upgrading_all:
            pass
        else:
            print(
                pipx_wrap(
                    f"""
                    {display_name} is already at latest version {old_version}
                    (location: {venv.root!s})
                    """
                )
            )
        return 0
    else:
        print(
            pipx_wrap(
                f"""
                upgraded package {display_name} from {old_version} to
                {new_version} (location: {venv.root!s})
                """
            )
        )
        return 1


def _dry_run_venv(
    venv_dir: Path,
    pip_args: list[str],
    verbose: bool,
    *,
    include_injected: bool,
    backend: str | None = None,
    env_backend: str | None = None,
) -> list[str]:
    """Return list of package names that have available upgrades (dry run, no changes made)."""
    if not venv_dir.is_dir():
        raise PipxError(
            f"""
            Package is not installed. Expected to find {venv_dir!s}, but it
            does not exist.
            """
        )

    venv = Venv(venv_dir, verbose=verbose, backend=backend, env_backend=env_backend)

    if not venv.python_path.is_file():
        raise PipxError(
            f"Cannot check {red(bold(venv_dir.name))}: invalid python interpreter {venv.python_path}.\n"
            f"This usually happens after a system Python upgrade.\n"
            f"To fix, execute: pipx reinstall-all",
            wrap_message=False,
        )

    if not venv.package_metadata:
        raise PipxError(
            f"Cannot check {red(bold(venv_dir.name))}: missing internal pipx metadata.\n"
            f"It was likely installed using a pipx version before 0.15.0.0.\n"
            f"Please uninstall and install this package to fix.",
            wrap_message=False,
        )

    if not pip_args:
        pip_args = venv.pipx_metadata.main_package.pip_args

    upgradable: list[str] = []

    package_name = venv.main_package_name
    package_metadata = venv.package_metadata[package_name]
    display_name = f"{package_metadata.package}{package_metadata.suffix}"

    if package_metadata.pinned:
        _LOGGER.warning(
            f"Not checking pinned package {venv.name}. Run `pipx unpin {venv.name}` to unpin it."
        )
    else:
        new_version = _check_upgrade_available(venv, package_name, pip_args)
        if new_version is not None:
            print(f"{display_name}: {package_metadata.package_version} < {new_version}")
            upgradable.append(display_name)
        else:
            print(f"{display_name} is already at latest version {package_metadata.package_version} (location: {venv.root!s})")

    if include_injected:
        for inj_name in venv.package_metadata:
            if inj_name == venv.main_package_name:
                continue
            inj_metadata = venv.package_metadata[inj_name]
            inj_display = f"{inj_metadata.package}{inj_metadata.suffix}"
            inj_pip_args = pip_args or inj_metadata.pip_args
            if inj_metadata.pinned:
                _LOGGER.warning(
                    f"Not checking pinned package {inj_name} in venv {venv.name}. "
                    f"Run `pipx unpin {venv.name}` to unpin it."
                )
            else:
                new_version = _check_upgrade_available(venv, inj_name, inj_pip_args)
                if new_version is not None:
                    print(f"{inj_display}: {inj_metadata.package_version} < {new_version} (injected in {venv.name})")
                    upgradable.append(inj_display)
                else:
                    print(
                        f"{inj_display} is already at latest version {inj_metadata.package_version} "
                        f"(injected in {venv.name})"
                    )

    return upgradable


def _upgrade_venv(
    venv_dir: Path,
    pip_args: list[str],
    verbose: bool,
    *,
    include_injected: bool,
    upgrading_all: bool,
    force: bool,
    install: bool = False,
    venv_args: list[str] | None = None,
    python: str | None = None,
    python_flag_passed: bool = False,
    backend: str | None = None,
    env_backend: str | None = None,
    venv: Venv | None = None,
    shared_libs_already_checked: bool = False,
) -> int:
    """Return number of packages whose versions changed.

    ``upgrade-all`` passes ``venv`` and ``shared_libs_already_checked=True``
    after its own pre-checks to avoid re-running them per venv.
    """
    if not venv_dir.is_dir():
        if install:
            if venv_args is None:
                venv_args = []
            commands.install(
                venv_dir=None,
                venv_args=venv_args,
                package_names=None,
                package_specs=[str(venv_dir).split(os.path.sep)[-1]],
                local_bin_dir=paths.ctx.bin_dir,
                local_man_dir=paths.ctx.man_dir,
                python=python,
                pip_args=pip_args,
                verbose=verbose,
                force=force,
                reinstall=False,
                include_dependencies=False,
                preinstall_packages=None,
                python_flag_passed=python_flag_passed,
                backend=backend,
                env_backend=env_backend,
            )
            return 0
        else:
            raise PipxError(
                f"""
                Package is not installed. Expected to find {venv_dir!s}, but it
                does not exist.
                """
            )

    if venv_args and not install:
        _LOGGER.info(f"Ignoring {', '.join(venv_args)} as not combined with --install")

    if python and not install:
        _LOGGER.info("Ignoring --python as not combined with --install")

    if venv is None:
        venv = Venv(venv_dir, verbose=verbose, backend=backend, env_backend=env_backend)
    if not pip_args:
        pip_args = venv.pipx_metadata.main_package.pip_args
    if not shared_libs_already_checked:
        venv.check_upgrade_shared_libs(pip_args=pip_args, verbose=verbose)

    if not venv.python_path.is_file():
        raise PipxError(
            f"Not upgrading {red(bold(venv_dir.name))}. It has an invalid python interpreter {venv.python_path}.\n"
            f"This usually happens after a system Python upgrade.\n"
            f"To fix, execute: pipx reinstall-all",
            wrap_message=False,
        )

    if not venv.package_metadata:
        raise PipxError(
            f"Not upgrading {red(bold(venv_dir.name))}. It has missing internal pipx metadata.\n"
            f"It was likely installed using a pipx version before 0.15.0.0.\n"
            f"Please uninstall and install this package to fix.",
            wrap_message=False,
        )

    # Upgrade shared libraries (pip, setuptools and wheel)
    venv.upgrade_packaging_libraries(pip_args)

    versions_updated = 0

    package_name = venv.main_package_name
    versions_updated += _upgrade_package(
        venv,
        package_name,
        pip_args,
        is_main_package=True,
        force=force,
        upgrading_all=upgrading_all,
    )

    if include_injected:
        for package_name in venv.package_metadata:
            if package_name == venv.main_package_name:
                continue
            injected_pip_args = pip_args or venv.package_metadata[package_name].pip_args
            versions_updated += _upgrade_package(
                venv,
                package_name,
                injected_pip_args,
                is_main_package=False,
                force=force,
                upgrading_all=upgrading_all,
            )

    return versions_updated


def upgrade(
    venv_dirs: dict[str, Path],
    python: str | None,
    pip_args: list[str],
    venv_args: list[str],
    verbose: bool,
    *,
    include_injected: bool,
    force: bool,
    install: bool,
    dry_run: bool = False,
    python_flag_passed: bool = False,
    backend: str | None = None,
    env_backend: str | None = None,
) -> ExitCode:
    """Return pipx exit code."""

    if dry_run:
        for venv_dir in venv_dirs.values():
            _dry_run_venv(
                venv_dir,
                pip_args,
                verbose,
                include_injected=include_injected,
                backend=backend,
                env_backend=env_backend,
            )
        return EXIT_CODE_OK

    for venv_dir in venv_dirs.values():
        _ = _upgrade_venv(
            venv_dir,
            pip_args,
            verbose,
            include_injected=include_injected,
            upgrading_all=False,
            force=force,
            install=install,
            venv_args=venv_args,
            python=python,
            python_flag_passed=python_flag_passed,
            backend=backend,
            env_backend=env_backend,
        )

    # Any error in upgrade will raise PipxError (e.g. from venv.upgrade_package())
    return EXIT_CODE_OK


def upgrade_all(
    venv_container: VenvContainer,
    verbose: bool,
    *,
    pip_args: list[str],
    include_injected: bool,
    skip: Sequence[str],
    force: bool,
    dry_run: bool = False,
    python_flag_passed: bool = False,
    backend: str | None = None,
    env_backend: str | None = None,
) -> ExitCode:
    """Return pipx exit code."""

    if dry_run:
        failed: list[str] = []
        upgradable: list[str] = []
        for venv_dir in venv_container.iter_venv_dirs():
            if venv_dir.name in skip:
                continue
            venv = Venv(venv_dir, verbose=verbose, backend=backend, env_backend=env_backend)
            if "--editable" in venv.pipx_metadata.main_package.pip_args:
                continue
            try:
                found = _dry_run_venv(
                    venv_dir,
                    pip_args,
                    verbose=verbose,
                    include_injected=include_injected,
                    backend=backend,
                    env_backend=env_backend,
                )
                upgradable.extend(found)
            except PipxError as e:
                print(e, file=sys.stderr)
                failed.append(venv_dir.name)
        if not upgradable:
            print(f"No packages have available upgrades {sleep}")
        if failed:
            raise PipxError(f"The following package(s) could not be checked: {','.join(failed)}")
        return EXIT_CODE_OK

    failed_upgrade: list[str] = []
    upgraded: list[str] = []

    for venv_dir in venv_container.iter_venv_dirs():
        # Cheap skip-list check first so we don't pay metadata read +
        # cross-backend warning + shared-libs health check on excluded venvs.
        if venv_dir.name in skip:
            continue
        venv = Venv(venv_dir, verbose=verbose, backend=backend, env_backend=env_backend)
        if "--editable" in venv.pipx_metadata.main_package.pip_args:
            continue
        venv.check_upgrade_shared_libs(pip_args=pip_args, verbose=verbose)
        try:
            versions_updated = _upgrade_venv(
                venv_dir,
                pip_args,
                verbose=verbose,
                include_injected=include_injected,
                upgrading_all=True,
                force=force,
                python_flag_passed=python_flag_passed,
                backend=backend,
                env_backend=env_backend,
                venv=venv,
                shared_libs_already_checked=True,
            )
            if versions_updated > 0:
                upgraded.append(venv_dir.name)
        except PipxError as e:
            print(e, file=sys.stderr)
            failed_upgrade.append(venv_dir.name)
    if len(upgraded) == 0:
        print(f"No packages upgraded after running 'pipx upgrade-all' {sleep}")
    if len(failed_upgrade) > 0:
        raise PipxError(f"The following package(s) failed to upgrade: {','.join(failed_upgrade)}")
    # Any failure to install will raise PipxError, otherwise success
    return EXIT_CODE_OK


def upgrade_shared(
    verbose: bool,
    pip_args: list[str],
) -> ExitCode:
    # Always refreshes: the next pip-backed install needs a fresh shared-libs
    # venv even when all currently-installed venvs are uv-backed.
    shared_libs.upgrade(verbose=verbose, pip_args=pip_args, raises=True)
    return EXIT_CODE_OK


__all__ = [
    "upgrade",
    "upgrade_all",
    "upgrade_shared",
]
