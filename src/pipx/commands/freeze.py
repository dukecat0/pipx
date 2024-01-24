import json
import sys
from pathlib import Path
from typing import Any, Collection, Dict, Tuple, Sequence

from pipx.venv import Venv, VenvContainer
from pipx.constants import EXIT_CODE_OK, ExitCode

PIPX_SPEC_VERSION = "0.1"

def freeze(
    venv_container: VenvContainer,
    output_path: Path,
    skip_pkgs: Sequence[str],
    ) -> ExitCode:
    spec_metadata: Dict[str, Any] = {
        "pipx_spec_version": PIPX_SPEC_VERSION,
        "venvs": {},
    }

    venv_dirs: Collection[Path] = sorted(venv_container.iter_venv_dirs())

    for venv_dir in venv_dirs:
        if venv_dir.name in skip_pkgs:
            continue

        venv = Venv(venv_dir)
        spec_metadata["venvs"][venv_dir.name] = {}
        metadata = venv.pipx_metadata.to_dict()
        
        not_required_keys = [
            "apps",
            "app_paths",
            "apps_of_dependencies",
            "app_paths_of_dependencies",
            "man_pages",
            "man_paths",
            "man_pages_of_dependencies",
            "man_paths_of_dependencies",
        ]

        # Remove not required info in the output
        for key in not_required_keys:
            metadata['main_package'].pop(key)

        if metadata['injected_packages']:
            for package in metadata['injected_packages']:
                for key in not_required_keys:
                    metadata['injected_packages'][package].pop(key)
        
        spec_metadata["venvs"][venv_dir.name]["metadata"] = metadata
    
    print(json.dumps(spec_metadata, indent=4, sort_keys=True))
