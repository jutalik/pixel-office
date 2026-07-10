"""Env-adaptive deploy detection for the playbook (detection only).

Local-first means a phone can't reach the office until it's promoted. This
module detects what promotion paths the environment supports and recommends the
least-public option that makes the service reachable. It NEVER deploys — the
agent runs the chosen playbook step; this only informs the choice.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import List


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True,
                              timeout=4).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _tunnels() -> List[str]:
    found = []
    if shutil.which("cloudflared"):
        found.append("cloudflared")
    if shutil.which("tailscale"):
        found.append("tailscale")
    return found


@dataclass
class DeployPlan:
    localhost: bool
    docker: bool
    tunnels: List[str]
    recommendation: str
    reachable_from_phone: bool
    note: str


def detect() -> DeployPlan:
    docker = _docker_ok()
    tunnels = _tunnels()
    # least-public option that still lets the user watch remotely:
    if tunnels:
        rec = f"tunnel:{tunnels[0]}"
        reachable, note = True, f"expose the local port via {tunnels[0]}; record the URL in ops/URL"
    elif docker:
        rec = "docker"
        reachable, note = False, "containerized run; publish a port + add a tunnel for phone access"
    else:
        rec = "localhost"
        reachable = False
        note = "dev only (127.0.0.1) — install cloudflared/tailscale to watch from a phone"
    return DeployPlan(localhost=True, docker=docker, tunnels=tunnels,
                      recommendation=rec, reachable_from_phone=reachable, note=note)
