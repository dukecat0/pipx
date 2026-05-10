import json
import logging
import sys
from collections.abc import Collection
from pathlib import Path
from typing import Any

from pipx import paths
from pipx.colors import bold
from pipx.commands.common import VenvProblems, get_venv_summary, venv_health_check
from pipx.commands.upgrade import _check_upgrade_available
from pipx.constants import EXIT_CODE_LIST_PROBLEM, EXIT_CODE_OK, ExitCode
from pipx.emojis import sleep
from pipx.pipx_metadata_file import JsonEncoderHandlesPath, PipxMetadata
from pipx.venv import Venv, VenvContainer

logger = logging.getLogger(__name__)

PIPX_SPEC_VERSION = "0.1"


def get_venv_metadata_summary(venv_dir: Path) -> tuple[PipxMetadata, VenvProblems, str]:
    venv = Venv(venv_dir)

    (venv_problems, warning_message) = venv_health_check(venv)
    if venv_problems.any_():
        return (PipxMetadata(venv_dir, read=False), venv_problems, warning_message)

    return (venv.pipx_metadata, venv_problems, "")


def list_short(venv_dirs: Collection[Path]) -> VenvProblems:
    all_venv_problems = VenvProblems()
    for venv_dir in venv_dirs:
        venv_metadata, venv_problems, warning_str = get_venv_metadata_summary(venv_dir)
        if venv_problems.any_():
            logger.warning(warning_str)
        else:
            print(
                venv_metadata.main_package.package,
                venv_metadata.main_package.package_version,
            )
        all_venv_problems.or_(venv_problems)

    return all_venv_problems


def list_text(venv_dirs: Collection[Path], include_injected: bool, venv_root_dir: str) -> VenvProblems:
    print(f"venvs are in {bold(venv_root_dir)}")
    print(f"apps are exposed on your $PATH at {bold(str(paths.ctx.bin_dir))}")
    print(f"manual pages are exposed at {bold(str(paths.ctx.man_dir))}")

    all_venv_problems = VenvProblems()
    for venv_dir in venv_dirs:
        package_summary, venv_problems = get_venv_summary(venv_dir, include_injected=include_injected)
        if venv_problems.any_():
            logger.warning(package_summary)
        else:
            print(package_summary)
        all_venv_problems.or_(venv_problems)

    return all_venv_problems


def list_json(venv_dirs: Collection[Path]) -> VenvProblems:
    warning_messages = []
    spec_metadata: dict[str, Any] = {
        "pipx_spec_version": PIPX_SPEC_VERSION,
        "venvs": {},
    }
    all_venv_problems = VenvProblems()
    for venv_dir in venv_dirs:
        (venv_metadata, venv_problems, warning_str) = get_venv_metadata_summary(venv_dir)
        all_venv_problems.or_(venv_problems)
        if venv_problems.any_():
            warning_messages.append(warning_str)
            continue

        spec_metadata["venvs"][venv_dir.name] = {}
        spec_metadata["venvs"][venv_dir.name]["metadata"] = venv_metadata.to_dict()

    print(json.dumps(spec_metadata, indent=4, sort_keys=True, cls=JsonEncoderHandlesPath))
    for warning_message in warning_messages:
        logger.warning(warning_message)

    return all_venv_problems


def list_pinned(venv_dirs: Collection[Path], include_injected: bool) -> VenvProblems:
    all_venv_problems = VenvProblems()
    for venv_dir in venv_dirs:
        venv_metadata, venv_problems, warning_str = get_venv_metadata_summary(venv_dir)
        if venv_problems.any_():
            logger.warning(warning_str)
        else:
            if venv_metadata.main_package.pinned:
                print(
                    venv_metadata.main_package.package,
                    venv_metadata.main_package.package_version,
                )
            if include_injected:
                for pkg, info in venv_metadata.injected_packages.items():
                    if info.pinned:
                        print(pkg, info.package_version, f"(injected in venv {venv_dir.name})")
        all_venv_problems.or_(venv_problems)

    return all_venv_problems


def list_outdated(
    venv_dirs: Collection[Path],
    pip_args: list[str],
    verbose: bool,
    include_injected: bool,
    backend: str | None = None,
    env_backend: str | None = None,
) -> VenvProblems:

    all_venv_problems = VenvProblems()
    found_any = False

    for venv_dir in venv_dirs:
        venv_metadata, venv_problems, warning_str = get_venv_metadata_summary(venv_dir)
        if venv_problems.any_():
            logger.warning(warning_str)
            all_venv_problems.or_(venv_problems)
            continue

        venv = Venv(venv_dir, verbose=verbose, backend=backend, env_backend=env_backend)
        effective_pip_args = pip_args or venv.pipx_metadata.main_package.pip_args

        package_name = venv.main_package_name
        package_metadata = venv.package_metadata[package_name]
        display_name = f"{package_metadata.package}{package_metadata.suffix}"

        if not package_metadata.pinned:
            new_version = _check_upgrade_available(venv, package_name, effective_pip_args)
            if new_version is not None:
                print(f"{display_name}: {package_metadata.package_version} < {new_version}")
                found_any = True

        if include_injected:
            for inj_name, inj_metadata in venv.package_metadata.items():
                if inj_name == venv.main_package_name:
                    continue
                inj_display = f"{inj_metadata.package}{inj_metadata.suffix}"
                inj_pip_args = effective_pip_args or inj_metadata.pip_args
                if not inj_metadata.pinned:
                    new_version = _check_upgrade_available(venv, inj_name, inj_pip_args)
                    if new_version is not None:
                        print(f"{inj_display}: {inj_metadata.package_version} < {new_version} (injected in {venv.name})")
                        found_any = True

    if not found_any:
        print(f"No packages have available upgrades {sleep}")

    return all_venv_problems


def list_packages(
    venv_container: VenvContainer,
    include_injected: bool,
    json_format: bool,
    short_format: bool,
    pinned_only: bool,
    outdated: bool = False,
    pip_args: list[str] | None = None,
    verbose: bool = False,
    backend: str | None = None,
    env_backend: str | None = None,
) -> ExitCode:
    """Returns pipx exit code."""
    venv_dirs: Collection[Path] = sorted(venv_container.iter_venv_dirs())
    if not venv_dirs:
        print(f"nothing has been installed with pipx {sleep}", file=sys.stderr)

    if json_format:
        all_venv_problems = list_json(venv_dirs)
    elif short_format:
        all_venv_problems = list_short(venv_dirs)
    elif pinned_only:
        all_venv_problems = list_pinned(venv_dirs, include_injected)
    elif outdated:
        if not venv_dirs:
            return EXIT_CODE_OK
        all_venv_problems = list_outdated(
            venv_dirs,
            pip_args=pip_args or [],
            verbose=verbose,
            include_injected=include_injected,
            backend=backend,
            env_backend=env_backend,
        )
    else:
        if not venv_dirs:
            return EXIT_CODE_OK
        all_venv_problems = list_text(venv_dirs, include_injected, str(venv_container))

    if all_venv_problems.bad_venv_name:
        logger.warning(
            "\nOne or more packages contain out-of-date internal data installed from a\n"
            "previous pipx version and need to be updated.\n"
            "    To fix, execute: pipx reinstall-all"
        )
    if all_venv_problems.invalid_interpreter:
        logger.warning(
            "\nOne or more packages have a missing python interpreter.\n    To fix, execute: pipx reinstall-all"
        )
    if all_venv_problems.missing_metadata:
        logger.warning(
            "\nOne or more packages have a missing internal pipx metadata.\n"
            "   They were likely installed using a pipx version before 0.15.0.0.\n"
            "   Please uninstall and install these package(s) to fix."
        )
    if all_venv_problems.not_installed:
        logger.warning(
            "\nOne or more packages are not installed properly.\n"
            "   Please uninstall and install these package(s) to fix."
        )

    if all_venv_problems.any_():
        print("", file=sys.stderr)
        return EXIT_CODE_LIST_PROBLEM

    return EXIT_CODE_OK
