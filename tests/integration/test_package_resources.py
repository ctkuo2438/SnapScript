"""Opt-in checks of actual build artifacts, without editable-install fallbacks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest


ARTIFACT_DIR = os.getenv("SNAPSCRIPT_PACKAGE_ARTIFACT_DIR")
pytestmark = pytest.mark.skipif(not ARTIFACT_DIR, reason="Set SNAPSCRIPT_PACKAGE_ARTIFACT_DIR to built artifacts")
PROMPTS = {"system.txt", "retry.txt", "task_rewrite.txt"}


def test_wheel_and_sdist_include_all_runtime_prompts():
    root = Path(ARTIFACT_DIR)
    wheel, = root.glob("*.whl")
    sdist, = root.glob("*.tar.gz")
    with zipfile.ZipFile(wheel) as archive:
        present = {Path(name).name for name in archive.namelist() if "/prompts/" in name}
        assert PROMPTS <= present
    with tarfile.open(sdist) as archive:
        present = {Path(name).name for name in archive.getnames() if "/prompts/" in name}
        assert PROMPTS <= present


def test_wheel_install_loads_prompts_outside_repo(tmp_path):
    wheel, = Path(ARTIFACT_DIR).glob("*.whl")
    site = tmp_path / "installed"
    installed = subprocess.run(
        ["uv", "pip", "install", "--no-deps", "--target", str(site), str(wheel)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert installed.returncode == 0, installed.stderr
    check = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import snapscript
from snapscript.core import prompt_builder, retry_handler, schema_inspector, task_rewriter
assert Path(snapscript.__file__).is_relative_to(Path(sys.argv[1]))
source = Path("input.csv")
source.write_text("value\\n1\\n")
prompt = prompt_builder.build("Copy rows.", schema_inspector.inspect(source))
retry = retry_handler._build_retry_prompt(prompt, "fixture", "print('fixture')")
rewrite = task_rewriter._load_rewrite_prompt()
assert prompt.system_prompt and "Retry context" in retry.user_prompt and rewrite
print(json.dumps({"installed_package": True, "system": True, "retry": True, "rewrite": True}))
'''
    completed = subprocess.run(
        [sys.executable, "-I", "-c", check, str(site)], cwd=tmp_path,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert all(json.loads(completed.stdout).values())
