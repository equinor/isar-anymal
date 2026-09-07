# isar-anymal

[ISAR](https://github.com/equinor/isar) - Integration and Supervisory control of Autonomous Robots - is a tool for
integrating robot applications into Equinor systems. Through the ISAR API you can send commands to a robot to do
missions and collect results from the missions.

Running the full ISAR system requires an installation of a robot which satisfies the required
[interface](https://github.com/equinor/isar/blob/main/src/robot_interface/robot_interface.py). isar-anymal is an
implementation for the ANYmal robot.

## Local development

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

### Installation

```
uv sync --extra dev
```

This installs the registry version of ISAR from `uv.lock`; a sibling checkout is not required.

### Developing against a local ISAR checkout (optional)

To work on ISAR and this integration together, clone the [isar](https://github.com/equinor/isar)
repository as a sibling directory (`../isar/`). After syncing, replace the registry package with
an editable installation:

```
uv sync --locked --extra dev
uv pip install --python .venv/bin/python --no-deps --editable ../isar
uv run --no-sync pytest
```

Use `uv run --no-sync` for all commands while using the local checkout (including the lint commands
below). A normal `uv run` or `uv sync` can replace the editable installation with the locked registry
version; repeat the editable install after syncing. `--frozen` alone does not prevent syncing.

The `--no-deps` option keeps the integration's locked dependencies installed. Use an ISAR checkout
compatible with those dependencies; if its requirements change, reconcile them before continuing.
`uv pip check --python .venv/bin/python` can detect missing or incompatible installed dependencies.
Python source edits in the sibling checkout are picked up without reinstalling, but metadata or
dependency changes may require reinstalling and adjusting the environment. These local installs do not change
`pyproject.toml` or `uv.lock`.

To return to the locked registry version:

```
uv sync --locked --extra dev
```

### Running tests

```
uv run pytest
```

Some tests require proprietary test data stored in Azure Blob Storage. These tests are marked with `@pytest.mark.requires_private_test_data` and will be automatically skipped unless the `AZURE_TEST_DATA_SAS_URL` environment variable is set.

The test data is stored in the `flotillatestsstorage` storage account in the [isar-anymal container](https://portal.azure.com/?feature.msaljs=true#view/Microsoft_Azure_Storage/ContainerMenuBlade/~/overview/storageAccountId/%2Fsubscriptions%2Fc389567b-2dd0-41fa-a5da-d86b81f80bda%2FresourceGroups%2FFlotillaIntegrationTests%2Fproviders%2FMicrosoft.Storage%2FstorageAccounts%2Fflotillatestsstorage/path/isar-anymal/etag/%220x8DEAAA1009A3DBC%22/defaultId//publicAccessVal/None). To run the full test suite, generate a SAS URL for this container and set it as an environment variable or include it in your .env file.

```
uv run pytest
```

### Linting and formatting

```
uv run black --check .
uv run ruff check .
uv run mypy .
```

## Dependencies

The dependencies used for this package are listed in `pyproject.toml` and locked in `uv.lock`. This ensures our builds
are predictable and deterministic. This project uses [uv](https://docs.astral.sh/uv/) for dependency management:

```
uv lock
```

To update all dependencies to the latest versions:

```
uv lock --upgrade
```

The committed configuration and lockfile use registry packages, so `--no-sources` is not needed.
Keep local editable installations in the development environment rather than committing a sibling
path in `tool.uv.sources`: Dependabot and standalone checkouts cannot retrieve that external directory.
