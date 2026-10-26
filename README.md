# isar-anymal

[ISAR](https://github.com/equinor/isar) - Integration and Supervisory control of Autonomous Robots - is a tool for
integrating robot applications into Equinor systems. Through the ISAR API you can send commands to a robot to do
missions and collect results from the missions.

Running the full ISAR system requires an installation of a robot which satisfies the required
[interface](https://github.com/equinor/isar/blob/main/src/robot_interface/robot_interface.py). isar-anymal is an
implementation for the ANYmal robot.

## Stored diagnostic missions

ISAR's `stored_mission` capability starts an existing robot-owned mission through
`Robot.initiate_stored_mission`. The request contains `tasks: []` and an explicit
`robot_mission_id`; the display name never selects a robot mission. For example:

```json
{
  "id": "diagnostic-execution-id",
  "name": "Diagnostic mission",
  "tasks": [],
  "robot_mission_id": "DiagnosticRoutine"
}
```

`DiagnosticRoutine` is an assumed **mission UID**, not a verified display name.
Configure Flotilla with the actual UID already installed on the target robot.
This integration forwards it as ANYmal's `missionDescription.missionUid`, using
the existing control lease, autonomous mode and protective-stop policy. It does
not create or transfer ADS mission files or enqueue inspection results. Status,
pause, resume and stop use the returned run UID. Completion follows robot task
summaries, or the explicit mission outcome when a stored run completes without
task summaries; an unavailable outcome is an error, not assumed success.

**Cross-repository dependency:** registry ISAR 2.7.0 does not support this contract.
This coordinated change pins [equinor/isar#1234](https://github.com/equinor/isar/pull/1234) to an immutable
Git commit in both the package dependency and `uv.lock`, so standalone installs
and production builds use the same contract without a sibling checkout. After
the ISAR changes are merged and released, replace the Git dependency with that
published registry minimum and regenerate `uv.lock`. Flotilla's stored-mission
scheduling changes and any deployment capability overrides must include
`stored_mission`.
Verify the installed UID and diagnostic progress/outcome events on the robot
before enabling scheduling; no live robot execution is part of these tests.

## Video inspections

`take_video` and `take_thermal_video` record normal-camera and thermal-camera video,
respectively. Both tasks require a robot pose, target position, and a finite, positive
`duration` in seconds. Optional zoom dimensions control the target size.

The integration generates `visual_inspection_video_recording` objects and executes
`visual_inspection_video_recording_behavior_plugins::Inspect`, which must be available
on the robot. Audio recording is disabled. Results are retrieved through data-navigator
and returned as ISAR `Video` or `ThermalVideo` inspections with the actual recorded
duration and the task's tag, description, and analysis types.

## Local development

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

### Installation

```
uv sync --extra dev
```

This installs the pinned ISAR dependency from `uv.lock`; a sibling checkout is not
required. Git must be available while the companion ISAR commit is pinned.

### Developing against a local ISAR checkout (optional)

To work on ISAR and this integration together, clone the [isar](https://github.com/equinor/isar)
repository as a sibling directory (`../isar/`). After syncing, replace the pinned package with
an editable installation:

```
uv sync --locked --extra dev
uv pip install --python .venv/bin/python --no-deps --editable ../isar
uv run --no-sync pytest
```

Use `uv run --no-sync` for all commands while using the local checkout (including the lint commands
below). A normal `uv run` or `uv sync` can replace the editable installation with the locked
dependency; repeat the editable install after syncing. `--frozen` alone does not prevent syncing.

The `--no-deps` option keeps the integration's locked dependencies installed. Use an ISAR checkout
compatible with those dependencies; if its requirements change, reconcile them before continuing.
`uv pip check --python .venv/bin/python` can detect missing or incompatible installed dependencies.
Python source edits in the sibling checkout are picked up without reinstalling, but metadata or
dependency changes may require reinstalling and adjusting the environment. These local installs do not change
`pyproject.toml` or `uv.lock`.

To return to the locked dependency:

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

The committed configuration uses registry packages plus the immutable companion ISAR
Git dependency; `--no-sources` is not needed.
Keep local editable installations in the development environment rather than committing a sibling
path in `tool.uv.sources`: Dependabot and standalone checkouts cannot retrieve that external directory.
