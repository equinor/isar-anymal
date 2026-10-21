"""Subprocess scheduling helpers for background recording work."""

import asyncio


async def create_nice_subprocess(
    executable: str,
    *arguments: str,
    niceness: int = 10,
    stdout: int | None = None,
    stderr: int | None = None,
) -> asyncio.subprocess.Process:
    """Start a process with niceness increased relative to its inherited value."""
    if not 0 <= niceness <= 19:
        raise ValueError("Niceness adjustment must be between 0 and 19")
    return await asyncio.create_subprocess_exec(
        "nice",
        "-n",
        str(niceness),
        executable,
        *arguments,
        stdout=stdout,
        stderr=stderr,
    )
