import re
import subprocess
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel
from settings.settings import settings
from starlette.responses import FileResponse

DATA_DIR: Path = Path(settings.ENVIRONMENT_FILE_WORKING_FOLDER)

ADS_BASE_ARGS: List[str] = [
    settings.ADS_COMMAND_PATH,
    "-s",
    settings.SERVER_URL,
    "--credentials-dir",
    settings.CREDENTIALS_DIR,
]

ALLOWED_ADS_ACTIONS = {"get", "put"}
ALLOWED_ADS_OPTIONS = {"-P"}

api: FastAPI = FastAPI()


class SendFileResponse(BaseModel):
    success: bool
    destination_path: str
    error_description: Optional[str] = None


class HealthResponse(BaseModel):
    ok: bool
    service: str


@api.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(
        ok=True,
        service="ads-api",
    )


@api.post("/send-file-to-robot-computer", response_model=SendFileResponse)
async def send_file_to_agent(
    computer: str = Form(...),
    destination_path: str = Form(...),
    robot_name: str = Form(...),
    prune: bool = Form(False),
    file: UploadFile = File(...),
):
    _sanitize_computer_input(computer)
    _sanitize_robot_name_input(robot_name)
    _sanitize_path(destination_path)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    src: Path = DATA_DIR / Path(file.filename).name

    try:
        data: bytes = await file.read()
        if not data:
            error_description: str = "File to upload was empty"
            logger.error(error_description)
            raise HTTPException(status_code=400, detail=error_description)

        src.write_bytes(data)

        success: bool = _send_file_to_agent(
            agent_pc=computer,
            src_path=str(src),
            dest_path=destination_path,
            robot_name=robot_name,
            prune=prune,
        )
        if not success:
            raise HTTPException(
                status_code=502,
                detail=f"File transfer reported failure from {computer} to {destination_path}",
            )

        return SendFileResponse(success=success, destination_path=destination_path)
    except Exception:
        error_message_send_file: str = f"Failed to send file {src} to agent"
        logger.exception(error_message_send_file)
        raise HTTPException(status_code=500, detail=error_message_send_file)
    finally:
        try:
            src.unlink(missing_ok=True)
        except Exception:
            error_message_delete_temp_file: str = (
                f"Failed to delete temporary file {src}"
            )
            logger.exception(error_message_delete_temp_file)
            raise HTTPException(status_code=500, detail=error_message_delete_temp_file)


@api.post("/get-file-from-robot-computer")
async def get_file_from_agent(
    computer: str = Form(...),
    robot_name: str = Form(...),
    file_path_on_robot: str = Form(...),
):
    _sanitize_computer_input(computer)
    _sanitize_robot_name_input(robot_name)
    _sanitize_path(file_path_on_robot)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    destination_path: str = settings.ENVIRONMENT_FILE_WORKING_FOLDER

    try:
        path: str = _get_file_from_agent(
            agent_pc=computer,
            src_path=file_path_on_robot,
            dest_path=destination_path,
            robot_name=robot_name,
        )

        logger.info(f"Downloaded file {file_path_on_robot} to {path}")

        p: Path = Path(path)
        if not p.exists() or not p.is_file():
            error_message_mission_file: str = (
                f"Download reported success but file missing: {path}"
            )
            logger.error(error_message_mission_file)
            raise HTTPException(
                status_code=502,
                detail=error_message_mission_file,
            )

        return FileResponse(
            path=str(p),
            media_type="application/octet-stream",
            filename=Path(file_path_on_robot).name,
        )
    except Exception:
        error_message_get_file: str = (
            f"Failed to get file {file_path_on_robot} from agent"
        )
        logger.exception(error_message_get_file)
        raise HTTPException(status_code=500, detail=error_message_get_file)


def _get_file_from_agent(
    agent_pc: str, src_path: str, dest_path: str, robot_name: str
) -> str:
    robot_ip_alias: str = f"anymal-{robot_name}-{agent_pc}"

    # Regex to verify if the file request was successful
    get_success_regex_pattern = "^[\\n\\r]*([1-9]+[0-9]*) files reported: manifest complete[\\n\\r]*.*[\\n\\r]*(.+) <- ([0-9A-F]{64}) \(.+\)[\\n\\r]*$"

    command: List[str] = _build_ads_get_command(
        robot_ip_alias=robot_ip_alias, src_path=src_path, dest_path=dest_path
    )

    match = _execute_ads_command_and_match_result(
        command=command, reg_match=get_success_regex_pattern
    )
    error_description: str
    if match:
        # We can only check one file. Verify that we only received one file
        nb_file_transmitted, filepath, _ = match.groups()
        if nb_file_transmitted == "1":
            logger.info(f"File successfully received ({filepath}) from {agent_pc}")
            return filepath
        else:
            error_description = (
                f"Error receiving file from {agent_pc}, "
                f"incorrect number of files transmitted: {nb_file_transmitted}"
            )
            logger.error(error_description)
            raise Exception(error_description)
    else:
        error_description = (
            f"Error receiving file from {agent_pc}, not match found, cmd = {command}"
        )
        logger.error(error_description)
        raise Exception(error_description)


def _send_file_to_agent(
    agent_pc: str, src_path: str, dest_path: str, robot_name: str, prune: bool = False
):
    robot_ip_alias: str = f"anymal-{robot_name}-{agent_pc}"

    # Regex to verify if the file request was successful
    put_success_regex_pattern: str = (
        f"^({re.escape(src_path)}.*) -> ([0-9A-F]{{64}})[\\n\\r]+({re.escape(robot_ip_alias)}):(.+) <- ([0-9A-F]{{64}})$"
    )

    command: List[str] = _build_ads_send_command(
        src_path=src_path,
        dest_path=dest_path,
        robot_ip_alias=robot_ip_alias,
        prune=prune,
    )

    logger.info(f"Command to be executed : {command}")
    match = _execute_ads_command_and_match_result(command, put_success_regex_pattern)
    if match:
        src_filename, hash_1, agent, dst_filename, hash_2 = match.groups()
        if hash_1 == hash_2:
            return True
        else:
            return False
    else:
        return False


def _build_ads_get_command(
    robot_ip_alias: str, src_path: str, dest_path: str
) -> List[str]:
    return [*ADS_BASE_ARGS, "get", robot_ip_alias, src_path, dest_path]


def _build_ads_send_command(
    src_path: str,
    dest_path: str,
    robot_ip_alias: str,
    prune: bool = False,
) -> List[str]:
    command: List[str] = [*ADS_BASE_ARGS, "put", robot_ip_alias, src_path, dest_path]
    if prune:
        command.append("-P")
    return command


def _execute_ads_command_and_match_result(command: List[str], reg_match: str):
    result: Optional[str] = _run_subprocess(command=command)
    if result:
        return re.search(reg_match, result)
    else:
        return None


def _validate_ads_command_structure(command: List[str]) -> None:
    if len(command) < len(ADS_BASE_ARGS) + 4:
        raise ValueError("Invalid ADS command: too few arguments")

    if command[: len(ADS_BASE_ARGS)] != ADS_BASE_ARGS:
        raise ValueError("Invalid ADS command: incorrect base arguments")

    action_index: int = len(ADS_BASE_ARGS)
    action: str = command[action_index]

    if action not in ALLOWED_ADS_ACTIONS:
        raise ValueError(f"Invalid ADS action: {action}")

    # Validate command length based on action
    expected_min_length = len(ADS_BASE_ARGS) + 4
    expected_max_length = len(ADS_BASE_ARGS) + 5  # for optional -P flag

    if not (expected_min_length <= len(command) <= expected_max_length):
        raise ValueError(f"Invalid ADS command length for action {action}")

    # Validate optional flags
    if len(command) == expected_max_length:
        if command[-1] not in ALLOWED_ADS_OPTIONS:
            raise ValueError(f"Invalid ADS option: {command[-1]}")


def _run_subprocess(command: List[str]) -> Optional[str]:
    try:
        _validate_ads_command_structure(command)
        result: subprocess.CompletedProcess = subprocess.run(
            command, shell=False, text=True, capture_output=True, check=True
        )
        output: str = result.stdout
        return output
    except subprocess.CalledProcessError as e:
        logger.error("ADS failed: exit={}", e.returncode)
        logger.error("cmd: {}", e.cmd)
        logger.error("stdout:\n{}", e.stdout or "")
        logger.error("stderr:\n{}", e.stderr or "")
        logger.exception(f"Error executing command: ´{command}´")
        return None
    except ValueError as e:
        logger.error("Rejected unsafe ADS command: {}", e)
        logger.error("cmd: {}", command)
        return None


def _sanitize_computer_input(computer: str) -> None:
    if computer.lower() != "npc" and computer.lower() != "lpc":
        error_message: str = f"Invalid computer name {computer} provided"
        logger.error(error_message)
        raise HTTPException(status_code=400, detail=error_message)


def _sanitize_robot_name_input(robot_name: str) -> None:
    if not robot_name:
        error_message_empty_name: str = "Invalid robot name: value is empty"
        logger.error(error_message_empty_name)
        raise HTTPException(status_code=400, detail=error_message_empty_name)

    if len(robot_name) > 20:
        error_message_long_name: str = f"Invalid robot name (too long): {robot_name}"
        logger.error(error_message_long_name)
        raise HTTPException(status_code=400, detail=error_message_long_name)

    if not re.fullmatch(r"[A-Za-z0-9_ÆæØøÅå-]+", robot_name):
        error_message_match_failed: str = f"Invalid robot name: {robot_name}"
        logger.error(error_message_match_failed)
        raise HTTPException(status_code=400, detail=error_message_match_failed)


def _sanitize_path(path: str) -> None:
    if not path:
        error_message_no_path: str = "Invalid path: value is empty"
        logger.error(error_message_no_path)
        raise HTTPException(status_code=400, detail=error_message_no_path)

    if not re.fullmatch(r"[A-Za-z0-9._/\-:]+", path):
        error_message_match_failed: str = f"Invalid path: {path}"
        logger.error(error_message_match_failed)
        raise HTTPException(status_code=400, detail=error_message_match_failed)

    if ".." in path:
        error_message_path_traversal: str = (
            f"Invalid path (path traversal not allowed): {path}"
        )
        logger.error(error_message_path_traversal)
        raise HTTPException(status_code=400, detail=error_message_path_traversal)
