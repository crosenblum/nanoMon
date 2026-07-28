"""
statistics.py

nanoMon Docker statistics collector.

Purpose:
    Collect live Docker container statistics only.

This module does not:
    - create HTML
    - display information
    - store historical data
    - manage containers

It collects:
    Running containers:
        - name
        - status
        - CPU usage
        - memory usage
        - restart policy
        - uptime

    Stopped containers:
        - name
        - status
        - stop reason
        - restart policy

    Docker summary:
        - total containers
        - running containers
        - stopped containers
"""

from __future__ import annotations

import json
import re
import subprocess

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class RunningContainer:
    # Data structure representing a running container and its essential stats.
    name: str
    status: str
    cpu_percent: float
    memory_used_mib: float
    restart_policy: str
    uptime: str


@dataclass
class StoppedContainer:
    # Data structure representing a stopped container and its essential stats.
    name: str
    status: str
    reason: str
    restart_policy: str


class DockerStatistics:
    # Docker executable name / path used by this collector.
    DOCKER_COMMAND: str = "docker"

    def _run_command(self, command: list[str]) -> str:
        """
        Execute a Docker CLI command and return stdout.

        Args:
            command: A list of command arguments, e.g. ["docker", "ps", "-a"].

        Returns:
            The command stdout (stripped).

        Raises:
            TypeError: If `command` is not a list of strings.
            RuntimeError: If Docker returns a non-zero exit code.
        """
        # ---- Input validation section ----
        # Validate that command is a list.
        if not isinstance(command, list):
            raise TypeError("Command must be a list.")
        # Validate all items are strings.
        if not all(isinstance(item, str) for item in command):
            raise TypeError("Command items must be strings.")

        # ---- Subprocess execution section ----
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

        # ---- Error handling section ----
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())

        # ---- Result normalization section ----
        return result.stdout.strip()

    def _get_all_containers(self) -> list[dict[str, Any]]:
        """
        Retrieve all containers (running and stopped) with minimal fields.

        Uses a single `docker ps -a` call and parses output as JSON fields:
        - ID
        - Names
        - State

        Returns:
            A list of dicts, each containing:
              { "ID": <str>, "Names": <str>, "State": <str> }
        """
        # ---- Output definition section ----
        containers: list[dict[str, Any]] = []

        # ---- Docker command section ----
        # One command returns JSON fields for each container.
        output = self._run_command(
            [
                self.DOCKER_COMMAND,
                "ps",
                "-a",
                "--format",
                "{{json .ID}}|{{json .Names}}|{{json .State}}",
            ]
        )

        # ---- Early return section ----
        if not output:
            return containers

        # ---- Parsing section ----
        for line in output.splitlines():
            try:
                # Each line is: <json ID>|<json Names>|<json State>
                id_json, names_json, state_json = line.split("|", 2)

                # Append structured container entry.
                containers.append(
                    {
                        "ID": json.loads(id_json),
                        "Names": json.loads(names_json),
                        "State": json.loads(state_json),
                    }
                )
            except Exception:
                # Skip malformed lines rather than failing the whole collection.
                continue

        return containers

    def _get_running_resource_usage_by_name(self) -> dict[str, dict[str, float]]:
        """
        Retrieve live CPU and memory usage for running containers, keyed by container name.

        This matches the original implementation's approach:
        - `docker stats` uses `.Name`
        - resources are stored under that same name key
        - later, running containers are matched by `docker ps` `.Names`

        Returns:
            A dict keyed by container name where each value is:
              {
                "cpu_percent": <float>,
                "memory_used_mib": <float>
              }
        """
        # ---- Output definition section ----
        resources: dict[str, dict[str, float]] = {}

        # ---- Docker stats command section ----
        output = self._run_command(
            [
                self.DOCKER_COMMAND,
                "stats",
                "--no-stream",
                "--format",
                "{{json .Name}}|{{json .CPUPerc}}|{{json .MemUsage}}",
            ]
        )

        # ---- Early return section ----
        if not output:
            return resources

        # ---- Parsing and conversion section ----
        for line in output.splitlines():
            try:
                # Each line is: <json Name>|<json CPUPerc>|<json MemUsage>
                name_json, cpu_json, mem_json = line.split("|", 2)

                # Parse JSON values emitted by the format string.
                name = json.loads(name_json)
                if not isinstance(name, str):
                    continue

                cpu_raw = json.loads(cpu_json)
                mem_raw = json.loads(mem_json)

                # Convert raw string values to floats.
                cpu_percent = self._convert_cpu(cpu_raw)
                memory_used_mib = self._convert_memory(mem_raw)

                # Store by name.
                resources[name] = {
                    "cpu_percent": cpu_percent,
                    "memory_used_mib": memory_used_mib,
                }
            except Exception:
                # Skip malformed lines.
                continue

        return resources

    def _get_container_inspect_bulk_by_id(
        self,
        container_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """
        Inspect multiple containers in a single docker inspect call.

        Args:
            container_ids: List of container IDs to inspect.

        Returns:
            A dict keyed by the inspected container object's "Id" field, mapping to the
            full parsed inspect object for each container.
        """
        # ---- Input validation section ----
        if not isinstance(container_ids, list):
            raise TypeError("container_ids must be a list of strings.")
        if not all(isinstance(cid, str) for cid in container_ids):
            raise TypeError("container_ids must be a list of strings.")

        # ---- Output definition section ----
        by_id: dict[str, dict[str, Any]] = {}

        # ---- Early return section ----
        if not container_ids:
            return by_id

        # ---- Docker inspect command section ----
        # We use --format '{{json .}}' so the tool returns one JSON object per container.
        output = self._run_command(
            [
                self.DOCKER_COMMAND,
                "inspect",
                "--format",
                "{{json .}}",
                *container_ids,
            ]
        )

        # ---- Early return section ----
        if not output:
            return by_id

        # ---- Parsing section ----
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)

                # Try multiple casings defensively.
                cid = item.get("Id") or item.get("ID") or item.get("id")
                if isinstance(cid, str):
                    by_id[cid] = item
            except Exception:
                # Skip malformed JSON lines.
                continue

        return by_id

    def _convert_cpu(self, value: Any) -> float:
        """
        Convert Docker CPU percentage text into a float.

        Args:
            value: The value from docker stats, typically a string like "1.23%".

        Returns:
            CPU percent as float. Returns 0.0 if parsing fails.
        """
        # ---- Input validation section ----
        if not isinstance(value, str):
            return 0.0

        # ---- Normalization section ----
        v = value.strip()
        if v.endswith("%"):
            v = v[:-1]

        # ---- Parsing section ----
        try:
            return float(v)
        except ValueError:
            return 0.0

    def _convert_memory(self, value: Any) -> float:
        """
        Convert Docker memory usage into MiB (mebibytes).

        Docker stats format example:
            "12.34MiB / 1GiB" or "123B / 456B"

        This function converts only the LEFT side (used memory).
        Supported units: GiB, MiB, KiB, B.

        Args:
            value: The value from docker stats, typically a string.

        Returns:
            Memory used in MiB as float. Returns 0.0 if parsing fails.
        """
        # ---- Input validation section ----
        if not isinstance(value, str):
            return 0.0

        # ---- Extract used-memory portion section ----
        left = value.split("/", 1)[0].strip()

        # ---- Pattern matching section ----
        m = re.match(r"^([0-9]*\.?[0-9]+)\s*([A-Za-z]+)\s*$", left)
        if not m:
            return 0.0

        number = float(m.group(1))
        unit = m.group(2)

        # ---- Unit conversion section ----
        if unit == "GiB":
            return round(number * 1024.0, 2)
        if unit == "MiB":
            return round(number * 1.0, 2)
        if unit == "KiB":
            return round(number * (1.0 / 1024.0), 2)
        if unit == "B":
            return round(number * (1.0 / 1048576.0), 2)

        # ---- Fallback section ----
        return 0.0

    def _get_exit_reason(self, state: dict[str, Any]) -> str:
        """
        Determine a human-readable stopped reason from container inspect state.

        Args:
            state: The parsed inspect .State dictionary.

        Returns:
            A human-readable reason string.
        """
        # ---- Input validation section ----
        if not isinstance(state, dict):
            raise TypeError("state must be a dictionary.")

        # ---- Exit code extraction section ----
        exit_code = state.get("ExitCode", -1)

        # ---- Mapping section ----
        if exit_code == 0:
            return "Stopped normally"
        if exit_code == 137:
            return "Killed (possible memory issue)"
        if exit_code == 143:
            return "Graceful shutdown"

        # ---- Default formatting section ----
        return f"Error exit (code {exit_code})"

    def _format_uptime(self, started_at: str) -> str:
        """
        Calculate a human-readable uptime from an ISO started timestamp.

        Args:
            started_at: Container started-at timestamp string (e.g. "2026-07-28T...Z").

        Returns:
            A string like "X days, Y hours" or "unknown" if parsing fails.
        """
        # ---- Input validation section ----
        if not isinstance(started_at, str):
            raise TypeError("started_at must be a string.")

        # ---- Empty handling section ----
        if not started_at:
            return "unknown"

        try:
            # ---- Parse datetime section ----
            start_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))

            # ---- Current time section ----
            now = datetime.now(timezone.utc)

            # ---- Delta computation section ----
            delta = now - start_time
            days = delta.days
            hours = delta.seconds // 3600

            # ---- Formatting section ----
            return f"{days} days, {hours} hours"
        except Exception:
            # ---- Failure handling section ----
            return "unknown"

    def collect_all(self) -> dict[str, Any]:
        """
        Collect complete nanoMon Docker statistics in the expected output schema.

        Returns:
            A dict with:
              - "timestamp": ISO string
              - "summary": dict with total/running/stopped container counts
              - "running": list of running container dicts
              - "stopped": list of stopped container dicts
        """
        # ---- Fetch containers section ----
        containers = self._get_all_containers()
        if not isinstance(containers, list):
            # Defensive guard (should never happen).
            raise RuntimeError("Unexpected _get_all_containers result type.")

        # ---- Split running vs stopped section ----
        running_ps = [c for c in containers if c.get("State") == "running"]
        stopped_ps = [c for c in containers if c.get("State") != "running"]

        # ---- Fetch stats usage section ----
        resources_by_name = self._get_running_resource_usage_by_name()
        if not isinstance(resources_by_name, dict):
            raise RuntimeError("Unexpected _get_running_resource_usage_by_name result type.")

        # ---- Bulk inspect section ----
        all_ids: list[str] = [c["ID"] for c in containers if isinstance(c.get("ID"), str)]
        inspect_by_id = self._get_container_inspect_bulk_by_id(all_ids)
        if not isinstance(inspect_by_id, dict):
            raise RuntimeError("Unexpected _get_container_inspect_bulk_by_id result type.")

        # ---- Build running output list section ----
        running_out: list[dict[str, Any]] = []
        for c in running_ps:
            # Extract container identifiers and display name.
            cid = c["ID"]
            name = str(c.get("Names", ""))

            # Match usage by the original key: docker stats .Name vs docker ps .Names.
            usage = resources_by_name.get(
                name,
                {"cpu_percent": 0.0, "memory_used_mib": 0.0},
            )

            # Look up inspect information by container ID for uptime/restart policy.
            insp = inspect_by_id.get(cid, {})
            state = insp.get("State") if isinstance(insp.get("State"), dict) else {}

            # Extract restart policy.
            restart_policy_name = (
                insp.get("HostConfig", {})
                .get("RestartPolicy", {})
                .get("Name", "no")
            )

            # Compute uptime from StartedAt.
            started_at = state.get("StartedAt", "")
            uptime = self._format_uptime(str(started_at))

            # Assemble running container record.
            item = RunningContainer(
                name=name,
                status="running",
                cpu_percent=float(usage["cpu_percent"]),
                memory_used_mib=float(usage["memory_used_mib"]),
                restart_policy=str(restart_policy_name) if restart_policy_name else "no",
                uptime=uptime,
            )
            running_out.append(asdict(item))

        # ---- Build stopped output list section ----
        stopped_out: list[dict[str, Any]] = []
        for c in stopped_ps:
            cid = c["ID"]
            name = str(c.get("Names", ""))

            insp = inspect_by_id.get(cid, {})
            state = insp.get("State") if isinstance(insp.get("State"), dict) else {}

            # status comes from docker ps state (as in original behavior).
            status = str(c.get("State", "unknown"))

            # Extract restart policy.
            restart_policy_name = (
                insp.get("HostConfig", {})
                .get("RestartPolicy", {})
                .get("Name", "no")
            )

            # Compute human-readable exit reason from inspect state.
            reason = self._get_exit_reason(state)

            # Assemble stopped container record.
            item = StoppedContainer(
                name=name,
                status=status,
                reason=reason,
                restart_policy=str(restart_policy_name) if restart_policy_name else "no",
            )
            stopped_out.append(asdict(item))

        # ---- Compute summary section ----
        total = len(containers)
        running_count = len(running_out)
        stopped_count = total - running_count

        # ---- Final payload section ----
        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_containers": total,
                "running_containers": running_count,
                "stopped_containers": stopped_count,
            },
            "running": running_out,
            "stopped": stopped_out,
        }


if __name__ == "__main__":
    """
    Standalone testing.

    Run:
        python statistics.py
    """
    # ---- Execute collector and print results section ----
    docker_statistics = DockerStatistics()
    results = docker_statistics.collect_all()
    print(json.dumps(results, indent=4))
