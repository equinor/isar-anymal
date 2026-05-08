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
- The [isar](https://github.com/equinor/isar) repository cloned as a sibling directory (`../isar/`)

### Installation

```
uv sync --extra dev
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
