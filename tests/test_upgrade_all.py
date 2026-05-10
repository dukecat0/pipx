import pytest

from helpers import PIPX_METADATA_LEGACY_VERSIONS, mock_legacy_venv, run_pipx_cli
from package_info import PKG
from pipx import paths
from pipx.pipx_metadata_file import PipxMetadata


def test_upgrade_all(pipx_temp_env, capsys):
    assert run_pipx_cli(["upgrade", "pycowsay"])
    assert not run_pipx_cli(["install", "pycowsay"])
    assert not run_pipx_cli(["upgrade-all"])


def test_upgrade_all_none(pipx_temp_env, capsys):
    assert not run_pipx_cli(["install", "pycowsay"])
    assert not run_pipx_cli(["upgrade-all"])
    captured = capsys.readouterr()
    assert "No packages upgraded after running 'pipx upgrade-all'" in captured.out


def test_upgrade_all_with_pip_args(pipx_temp_env, capsys):
    assert not run_pipx_cli(["install", "pycowsay"])
    assert not run_pipx_cli(["upgrade-all", "--pip-args=--no-cache-dir"])


@pytest.mark.parametrize("metadata_version", PIPX_METADATA_LEGACY_VERSIONS)
def test_upgrade_all_legacy_venv(pipx_temp_env, capsys, metadata_version):
    assert run_pipx_cli(["upgrade", "pycowsay"])
    assert not run_pipx_cli(["install", "pycowsay"])
    mock_legacy_venv("pycowsay", metadata_version=metadata_version)
    if metadata_version is None:
        capsys.readouterr()
        assert run_pipx_cli(["upgrade-all"])
        assert "The following package(s) failed to upgrade: pycowsay" in capsys.readouterr().err
    else:
        assert not run_pipx_cli(["upgrade-all"])


def test_upgrade_all_dry_run_none(pipx_temp_env, capsys):
    assert not run_pipx_cli(["install", "pycowsay"])
    capsys.readouterr()

    assert not run_pipx_cli(["upgrade-all", "--dry-run"])
    captured = capsys.readouterr()
    assert "No packages have available upgrades" in captured.out
    assert "upgraded package" not in captured.out


def test_upgrade_all_dry_run_reports_upgrades(pipx_temp_env, capsys):
    pylint_initial = PKG["pylint"]["spec"].split("==")[-1]
    assert not run_pipx_cli(["install", "pycowsay"])
    assert not run_pipx_cli(["install", PKG["pylint"]["spec"]])
    capsys.readouterr()

    assert not run_pipx_cli(["upgrade-all", "--dry-run"])
    captured = capsys.readouterr()
    assert f"pylint: {pylint_initial} <" in captured.out
    assert "pycowsay is already at latest version" in captured.out
    assert "upgraded package" not in captured.out

    # nothing on disk should have changed
    metadata = PipxMetadata(paths.ctx.home / "venvs" / "pylint")
    assert metadata.main_package.package_version == pylint_initial
