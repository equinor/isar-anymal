# isar-anymal

[ISAR](https://github.com/equinor/isar) - Integration and Supervisory control of Autonomous Robots - is a tool for
integrating robot applications into Equinor systems. Through the ISAR API you can send commands to a robot to do
missions and collect results from the missions.

Running the full ISAR system requires an installation of a robot which satisfies the required
[interface](https://github.com/equinor/isar/blob/main/src/robot_interface/robot_interface.py). isar-anymal is an
implementation for the ANYmal robot.

## Mission preparation

Ad-hoc missions use the [Environment API](https://anymal.docs.anymal.com/openapi/environment-api.html)
instead of transferring files through ADS. The integration reads the map's waypoint
graph, projects observation poses onto its edges, and creates navigation goals,
inspection actions with environment items, and an ordered mission. All mission tasks
are submitted in one request. Undocking and the last inspection abort on failure;
intermediate inspections continue on failure, as before.

The Environment API is served at `ANYMAL_SERVER_URL/environment-api`, alongside
the existing robot-control and Data Navigator APIs. It uses the same server and
bearer token, authenticated with `ANYMAL_API_EMAIL` and `ANYMAL_API_PASSWORD`;
no separate API URL is needed.
Configure `ANYMAL_ENVIRONMENT_MAP_ID` with the server's map ID.
`ANYMAL_MAP_NAME` still selects the local coordinate alignment and must correspond
to the configured server map. The map ID is required for ad-hoc missions,
not for executing stored missions.

ANYbotics synchronizes server changes to connected robots automatically, normally
within a few seconds. `ANYMAL_MISSION_SYNC_DELAY` (default 5 seconds) allows resources
to settle before starting. A newly created mission that returns
`CMS_ERROR_MISSION_UNKNOWN` is retried every `ANYMAL_MISSION_SYNC_RETRY_INTERVAL`
(default 5 seconds), for up to `ANYMAL_MISSION_SYNC_TIMEOUT` (default 60 seconds).
Other failures, including ambiguous HTTP timeouts, are not retried. There is no
robot-readiness endpoint in the supplied Environment API contract: a successful
server write alone does not prove the full mission has synchronized.

Generated resources reserve the label prefix `ISAR-<robot-name-length>-<robot-name>-`.
Do not use that prefix for manually authored resources or run multiple mission
planners for the same robot and map. Before the next ad-hoc mission, old resources
in that namespace are deleted in dependency order, without forcing deletion of
referenced resources. Partial creation failures trigger the same cleanup; remaining
resources are discoverable after a restart. Stored missions and other labels are
not modified.

Server-generated task IDs are mapped back to ISAR tasks. Inspection events are
matched against the returned action configuration name, or the navigation goal's
served `name` for CO2 measurements. A CO2 goal without a served name fails preparation
explicitly rather than starting a mission whose results cannot be correlated.
Robot-backed acceptance must verify these IDs/names, undocking, failure semantics,
and synchronization for the deployed ANYmal version before rollout.

ADS containers, CLI credentials, file mounts, and image publishing are no longer
needed. Existing deployments in `equinor/robotics-infrastructure` must separately
remove the ADS workload and obsolete configuration and add the Environment API
settings before deploying this version. Inspection retrieval still uses
Data Navigator; migration to Shift is a separate change.

## Video inspections

`take_video` and `take_thermal_video` record normal-camera and thermal-camera video,
respectively. Both tasks require a robot pose, target position, and a finite, positive
`duration` in seconds. Optional zoom dimensions control the target size.

The integration creates `visual_inspection_video_recording` actions and executes
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

### Container builds

Production uses ISAR from `uv.lock`. To use a local checkout (including worktrees):

```bash
docker build -f Dockerfile.Local --build-context isar_source=../isar -t isar-anymal:local .
```

Local builds resolve source dependencies without changing `uv.lock`, include media
forwarding support, and run as UID 1001 with writable `/data`. Rebuild after source edits.

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
