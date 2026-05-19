# Docker Sandbox

## Purpose

The SnapScript sandbox image runs generated pandas scripts inside Docker. It is a runtime sandbox image, not the SnapScript application image.

The image is designed for the Phase 3 Docker executor path:

- `docker_sandbox_executor.py` creates a temporary workspace.
- The workspace is mounted to `/workspace`.
- Generated `script.py` imports `INPUT_PATH` and `OUTPUT_PATH` from `_snapscript_paths.py`.
- Docker runs `python script.py` from `/workspace`.

The image does not contain the SnapScript source tree and does not need `script.py` at build time.

## Build

```bash
docker build -t snapscript-sandbox:local docker/sandbox
```

The tag `snapscript-sandbox:local` matches the current default Docker image configured by `AppConfig` and used by the Task 32 Docker executor.

## Basic Manual Run

Create a local workspace containing:

- `script.py`
- `_snapscript_paths.py`
- the copied input file

Then run:

```bash
docker run --rm \
  --network none \
  --memory 512m \
  --cpus 1.0 \
  --pids-limit 128 \
  -v "$PWD/tmp_workspace:/workspace" \
  -w /workspace \
  snapscript-sandbox:local \
  python script.py
```

Do not put provider credentials, `.env` files, or logs in the mounted workspace.

## Runtime Dependencies

The image includes only the runtime packages expected by generated data transformation scripts:

- `pandas`
- `openpyxl`
- `chardet`
- `xlrd`

`xlrd` is included for legacy `.xls` read support because SnapScript accepts `.xls` inputs and validates `.xls` outputs through pandas.

The image intentionally does not include:

- Anthropic SDK or other provider SDKs
- Streamlit
- Rich
- pytest
- SnapScript source code
- development tools

Generated scripts should not call LLM providers from inside the sandbox.

## Runtime Restrictions

The Docker executor adds runtime restrictions when it starts the sandbox container:

- `--network none` is used by default when `docker_network_disabled` is true.
- `--memory` uses `AppConfig.docker_memory_limit`.
- `--cpus` uses `AppConfig.docker_cpu_limit`.
- `--pids-limit 128` limits process fan-out inside the container.
- Host-side timeout is enforced through `subprocess.run(..., timeout=AppConfig.docker_timeout_seconds)`.
- Only the per-run temporary workspace is mounted into the container.
- The repository root and user home directory must never be mounted.

The mounted workspace is created for one run, populated only with the copied input file, `script.py`, `_snapscript_paths.py`, and the expected output path, then deleted after execution. Because the image runs as a non-root `snapscript` user, the executor prepares that per-run workspace before container startup:

- The workspace directory is made writable and traversable so generated scripts can create the output file.
- Copied files directly inside the workspace are made readable and writable so the container user can read the copied input file, `script.py`, and `_snapscript_paths.py`.

These permissions are narrowly scoped to the per-run `TemporaryDirectory` workspace. They do not apply to the repository root, the user home directory, or arbitrary paths outside the temporary workspace.

`--read-only` is deferred for now. Generated pandas and Excel workflows can need writable temporary locations, especially through pandas/openpyxl internals. A future hardening pass can revisit `--read-only` with explicit `--tmpfs` mounts after real CSV/XLSX/XLS smoke tests confirm compatibility.

## Security Notes

- The image does not include API keys.
- The image does not copy `.env` files.
- The image does not copy the SnapScript repository.
- Do not run generated scripts with provider credentials in the container environment.
- Do not mount the user's home directory or the repository root as `/workspace`.
- Mount only the temporary workspace created for the run.
- The container runs as a non-root `snapscript` user.

## Verification

Build the image:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
```

Run the Docker executor tests. These tests mock Docker and do not require a real Docker daemon:

```bash
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py
```

Run the focused config and Docker executor tests:

```bash
uv run pytest tests/test_config.py tests/test_docker_sandbox_executor.py
```

## Troubleshooting

### Docker daemon not running

Start Docker Desktop or the local Docker daemon, then rerun the build command.

### Image tag mismatch

The Docker executor default expects:

```text
snapscript-sandbox:local
```

If you build with a different tag, update the local Docker image setting before using the Docker executor.

### Missing Excel package

If generated scripts fail on Excel files, confirm the file format:

- `.xlsx` support is provided by `openpyxl`.
- `.xls` read support is provided by `xlrd`.

Add packages only when they are needed by generated scripts and after checking that they do not pull in unnecessary provider or UI dependencies.

### Permission issues with mounted workspace

The container runs as a non-root user. If a manually created mounted workspace is not writable by that user, Docker execution may fail when the generated script tries to write `OUTPUT_PATH`. If copied files inside a manual workspace are not readable by that user, execution may fail before output is written.

The SnapScript Docker executor prepares its own per-run temporary workspace automatically. For manual Docker runs, ensure the mounted workspace grants write permission to the container user and that copied input, `script.py`, and `_snapscript_paths.py` are readable by that user.
