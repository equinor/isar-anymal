import os
from pathlib import Path

import pytest
from azure.storage.blob import ContainerClient, BlobClient

TEST_DATA_DIR = Path(__file__).parent / "robot" / "test_data"

TEST_DATA_BLOBS = [
    "concentration_monitoring_example.json",
    "environment.yaml",
    "inspection_visual_example.json",
    "waypoints.json",
]


def _download_test_data() -> None:
    sas_url: str = os.environ["AZURE_TEST_DATA_SAS_URL"]
    container_client: ContainerClient = ContainerClient.from_container_url(sas_url)

    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

    for blob_name in TEST_DATA_BLOBS:
        blob_client: BlobClient = container_client.get_blob_client(blob_name)
        target_path = TEST_DATA_DIR / blob_name
        with open(target_path, "wb") as f:
            f.write(blob_client.download_blob().readall())


def pytest_collection_modifyitems(config, items):
    sas_url: str = os.environ.get("AZURE_TEST_DATA_SAS_URL")

    if sas_url:
        _download_test_data()
        return

    skip_marker = pytest.mark.skip(
        reason="AZURE_TEST_DATA_SAS_URL not set; private test data unavailable"
    )
    for item in items:
        if "requires_private_test_data" in item.keywords:
            item.add_marker(skip_marker)
