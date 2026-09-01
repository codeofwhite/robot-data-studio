from pathlib import Path

import pytest

from robot_data_studio.adapters.clothtwin import ClothTwinAdapter


@pytest.mark.parametrize("format_name", ["lerobot", "rlds", "robomimic"])
def test_export_format_is_allowlisted(format_name):
    command = ClothTwinAdapter().build_export_command(
        format_name, Path("/tmp/raw"), Path("/tmp/out"), repo_id="local/test"
    )
    assert command[1:3] == ["-m", "tools.export_dataset"]
    assert command[command.index("--format") + 1] == format_name


def test_unknown_export_is_rejected():
    with pytest.raises(ValueError, match="unsupported export format"):
        ClothTwinAdapter().build_export_command("unknown", Path("/tmp/raw"), Path("/tmp/out"))
