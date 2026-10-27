"""Destination readiness and commit errors must not escape the core contract."""
from unittest.mock import Mock

import pytest

from snapscript.config import AppConfig
from snapscript.core import _sandbox_files, code_generator, execution_backend, retry_handler
from snapscript.core.models import ExecutionResult, GeneratedScript, PromptPayload


def test_commit_catches_temporary_file_creation_failure(tmp_path, monkeypatch):
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n")
    monkeypatch.setattr(_sandbox_files.tempfile, "NamedTemporaryFile", Mock(side_effect=PermissionError("fixture")))
    error = _sandbox_files.commit_output(source, tmp_path / "out.csv", overwrite=True)
    assert isinstance(error, str)
    assert not (tmp_path / "out.csv").exists()


def test_destination_readiness_does_not_create_output_directories(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("value\n1\n")
    destination = tmp_path / "new" / "nested" / "out.csv"
    assert _sandbox_files.validate_destination(source, destination) is None
    assert not destination.parent.exists()
    assert not list(tmp_path.glob(".snapscript-check-*"))


@pytest.mark.parametrize("overwrite", [False, True])
def test_committed_outputs_remain_private(tmp_path, overwrite):
    source, destination = tmp_path / "input.csv", tmp_path / "out.csv"
    source.write_text("value\n1\n")
    source.chmod(0o644)
    if overwrite:
        destination.write_text("old\n2\n")
        destination.chmod(0o644)
    assert _sandbox_files.commit_output(source, destination, overwrite=overwrite) is None
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o600


def test_unwritable_destination_stops_before_generation(tmp_path, monkeypatch):
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n")
    generator = Mock(return_value=GeneratedScript("print('ok')", "", "fixture"))
    executor = Mock(return_value=ExecutionResult(True))
    monkeypatch.setattr(code_generator, "generate", generator)
    monkeypatch.setattr(execution_backend, "execute", executor)
    monkeypatch.setattr(_sandbox_files.tempfile, "NamedTemporaryFile", Mock(side_effect=PermissionError("fixture")))
    result = retry_handler.run(PromptPayload("system", "copy"), source, tmp_path / "out.csv", config=AppConfig(sandbox_backend="subprocess"))
    assert not result.success
    assert result.error_category == "input_validation"
    generator.assert_not_called()
    executor.assert_not_called()


def test_unwritable_upload_destination_records_no_provider_call(monkeypatch):
    from snapscript.interfaces import web_pipeline

    audit = {}
    generator = Mock(side_effect=AssertionError("No provider call is allowed"))
    monkeypatch.setattr(code_generator, "generate", generator)
    monkeypatch.setattr(_sandbox_files.tempfile, "NamedTemporaryFile", Mock(side_effect=PermissionError("fixture")))
    result, output, name = web_pipeline.run_uploaded_task(
        b"value\n1\n", ".csv", "Copy rows", audit_metadata=audit,
        config=AppConfig(sandbox_backend="subprocess"),
    )
    assert not result.success
    assert output is name is None
    assert audit["provider_called"] is False
    generator.assert_not_called()


@pytest.mark.parametrize("operation", ["mkdir", "unlink"])
def test_commit_directory_and_cleanup_failures_return_errors(tmp_path, monkeypatch, operation):
    source, output = tmp_path / "source.csv", tmp_path / "out.csv"
    source.write_text("value\n1\n")
    output.write_text("keep\n2\n")
    monkeypatch.setattr(type(source), operation, Mock(side_effect=PermissionError("fixture")))
    error = _sandbox_files.commit_output(source, output, overwrite=False)
    assert isinstance(error, str)
    assert output.read_text() == "keep\n2\n"


@pytest.mark.parametrize("contents,limit,category", [
    (b"", 100, "output_empty"), (b"value\n", 100, "output_empty"),
    (b"value\n1\n", 1, "output_limit"), (b'\xff\xfe\x00', 100, "output_validation"),
])
def test_output_errors_assign_categories_at_validation(tmp_path, contents, limit, category):
    path = tmp_path / "output.csv"
    path.write_bytes(contents)
    with pytest.raises(_sandbox_files.OutputValidationError) as captured:
        _sandbox_files.validate_output(path, limit)
    assert captured.value.category == category


def test_root_container_mapping_leaves_the_parent_private(tmp_path, monkeypatch):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    workspace = parent / "workspace"
    workspace.mkdir()
    script = workspace / "script.py"
    script.write_text("print('fixture')")
    chown = Mock()
    monkeypatch.setattr(_sandbox_files.os, "geteuid", lambda: 0)
    monkeypatch.setattr(_sandbox_files.os, "getegid", lambda: 0)
    monkeypatch.setattr(_sandbox_files.os, "chown", chown)
    _sandbox_files.prepare_container_permissions(workspace)
    assert _sandbox_files.container_identity() == (1000, 1000)
    assert {call.args[0] for call in chown.call_args_list} == {workspace, script}
    assert parent.stat().st_mode & 0o777 == 0o700
    assert workspace.stat().st_mode & 0o777 == 0o700
    assert script.stat().st_mode & 0o777 == 0o600
