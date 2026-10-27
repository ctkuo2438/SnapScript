from helpers.streamlit_helpers import install_streamlit

import ast

from pathlib import Path

import pytest

from snapscript.interfaces import web, web_pipeline

from helpers.streamlit_helpers import FakeStreamlit, FakeUploadedFile

def test_app_entrypoint_only_delegates_to_web_main() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    ast.parse(source)

    assert "from snapscript.interfaces.web import main" in source
    assert 'if __name__ == "__main__":' in source
    assert "    main()" in source

def test_main_renders_remaining_runs_display(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    fake_st.session_state["run_count"] = 4
    install_streamlit(monkeypatch, fake_st)

    web.main()

    assert (
        "caption",
        ("Remaining runs this session: 6",),
        {},
    ) in fake_st.calls

def _sidebar_warnings(fake_st: FakeStreamlit) -> list[tuple[object, ...]]:
    return [args for name, args, _ in fake_st.calls if name == "sidebar.warning"]

def test_main_sidebar_shows_docker_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SNAPSCRIPT_SANDBOX_BACKEND", raising=False)
    fake_st = FakeStreamlit()
    install_streamlit(monkeypatch, fake_st)

    web.main()

    assert ("sidebar.subheader", ("Runtime",), {}) in fake_st.calls
    assert (
        "sidebar.write",
        ("Sandbox backend: docker",),
        {},
    ) in fake_st.calls
    assert (
        "sidebar.code",
        ("docker build -t snapscript-sandbox:local docker/sandbox",),
        {},
    ) in fake_st.calls
    assert _sidebar_warnings(fake_st) == []

def test_main_sidebar_warns_for_explicit_subprocess_backend(monkeypatch) -> None:
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "subprocess")
    fake_st = FakeStreamlit()
    install_streamlit(monkeypatch, fake_st)

    web.main()

    assert (
        "sidebar.write",
        ("Sandbox backend: subprocess",),
        {},
    ) in fake_st.calls
    assert _sidebar_warnings(fake_st) == [(web.SUBPROCESS_BACKEND_WARNING,)]
    assert ("sidebar.caption", ("Use Docker backend:",), {}) in fake_st.calls
    assert (
        "sidebar.code",
        ("SNAPSCRIPT_SANDBOX_BACKEND=docker uv run streamlit run app.py",),
        {},
    ) in fake_st.calls

def test_main_sidebar_shows_explicit_docker_backend_without_warning(monkeypatch) -> None:
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "docker")
    fake_st = FakeStreamlit()
    install_streamlit(monkeypatch, fake_st)

    web.main()

    assert (
        "sidebar.write",
        ("Sandbox backend: docker",),
        {},
    ) in fake_st.calls
    assert _sidebar_warnings(fake_st) == []

def test_default_web_config_uses_docker_unless_backend_is_explicit(monkeypatch) -> None:
    monkeypatch.delenv("SNAPSCRIPT_SANDBOX_BACKEND", raising=False)
    assert web.default_web_config().sandbox_backend == "docker"

    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "subprocess")
    assert web.default_web_config().sandbox_backend == "subprocess"

    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "docker")
    assert web.default_web_config().sandbox_backend == "docker"

def test_default_web_config_rejects_invalid_explicit_backend(monkeypatch) -> None:
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "podman")

    with pytest.raises(ValueError, match="SNAPSCRIPT_SANDBOX_BACKEND"):
        web.default_web_config()

def test_default_web_config_keeps_docker_network_disabled_and_other_settings(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SNAPSCRIPT_SANDBOX_BACKEND", raising=False)
    monkeypatch.setenv("SNAPSCRIPT_DOCKER_MEMORY_LIMIT", "256m")

    config = web.default_web_config()

    assert config.docker_network_disabled is True
    assert config.docker_memory_limit == "256m"

def test_main_generate_passes_docker_config_to_pipeline_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SNAPSCRIPT_SANDBOX_BACKEND", raising=False)
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True, uploaded_file=uploaded, task_text="Keep large orders.",
    )
    install_streamlit(monkeypatch, fake_st)
    backends: list[str] = []

    def fake_pipeline(
        _file_bytes, _suffix, _task_text, uploaded_file_name=None,
        audit_metadata=None, config=None, cache_state=None,
    ):
        backends.append(config.sandbox_backend)
        return web.ExecutionResult(success=True), b"ok\n1\n", "snapscript_output.csv"

    monkeypatch.setattr(web_pipeline, "run_uploaded_task", fake_pipeline)

    web.main()

    assert backends == ["docker"]

def test_main_renders_input_and_generate_controls(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    install_streamlit(monkeypatch, fake_st)

    web.main()

    call_names = [name for name, _args, _kwargs in fake_st.calls]
    assert "title" in call_names
    assert "file_uploader" in call_names
    assert "text_area" in call_names
    assert "button" in call_names
    assert "caption" in call_names

def test_web_composes_ui_without_calling_provider_or_sandbox() -> None:
    source = Path("src/snapscript/interfaces/web.py").read_text(encoding="utf-8")

    assert "import streamlit as st" in source
    assert "web_pipeline.run_uploaded_task(" in source
    assert "Anthropic" not in source
    assert "anthropic" not in source
    assert "code_generator" not in source
    assert "safety_checker" not in source
    assert "execution_backend" not in source
    assert "sandbox_executor" not in source
    assert ".generate(" not in source
    assert ".execute(" not in source
