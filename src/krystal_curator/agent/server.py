"""llama-server lifecycle: attach to one you run yourself (`agent.base_url`) or spawn one
from the configured GGUF on first use and stop it when the process ends. Only the health
endpoint is touched here; completions live in `llm.py`.
"""

from __future__ import annotations

import atexit
import logging
import shutil
import subprocess
import time
from pathlib import Path

from .. import net
from ..config import Agent, data_dir

log = logging.getLogger("krystal_curator.agent")


class AgentError(RuntimeError):
    """The addon cannot run: not enabled, no model, no binary, server never came up."""


class LlamaServer:
    def __init__(self, cfg: Agent) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._base = cfg.base_url.rstrip("/")

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def spawned(self) -> bool:
        return self._proc is not None

    def healthy(self, timeout: float = 2.0) -> bool:
        if not self._base:
            return False
        try:
            r = net.get(f"{self._base}/health", timeout=timeout, retries=0)
        except net.HttpError:
            return False
        return r.status_code == 200 and (r.json() or {}).get("status") == "ok"

    def ensure(self, *, wait_s: float = 120.0) -> str:
        """Base URL of a healthy server; spawns one when none is configured or reachable."""
        if not self.cfg.enabled:
            raise AgentError("agent addon is off: set [agent] enabled = true in config.toml")
        if self._base and self.healthy():
            return self._base
        if self.cfg.base_url:
            raise AgentError(f"agent: no llama-server answering at {self.cfg.base_url}/health")
        if self._proc is not None and self._proc.poll() is None:
            return self._wait(wait_s)
        self._spawn()
        return self._wait(wait_s)

    def _spawn(self) -> None:
        if not self.cfg.model:
            raise AgentError("agent: [agent] model = path to a GGUF is required to spawn a server")
        model = Path(self.cfg.model).expanduser()
        if not model.is_file():
            raise AgentError(f"agent: model not found: {model}")
        binary = shutil.which(self.cfg.llama_server) or self.cfg.llama_server
        if not shutil.which(binary) and not Path(binary).is_file():
            raise AgentError(
                f"agent: {self.cfg.llama_server!r} not found; brew install llama.cpp or set "
                "[agent] llama_server = /path/to/llama-server"
            )
        logs = data_dir() / "agent"
        logs.mkdir(parents=True, exist_ok=True)
        out = (logs / "llama-server.log").open("ab")
        cmd = [
            binary,
            "-m", str(model),
            "--host", "127.0.0.1",
            "--port", str(self.cfg.port),
            "-c", str(self.cfg.ctx),
            "-ngl", str(self.cfg.gpu_layers),
            "--jinja",
        ]  # fmt: skip
        if self.cfg.reasoning_budget > 0:
            cmd += ["--reasoning-budget", str(self.cfg.reasoning_budget)]
        log.info("agent: spawning %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
        )
        self._base = f"http://127.0.0.1:{self.cfg.port}"
        atexit.register(self.stop)

    def _wait(self, wait_s: float) -> str:
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise AgentError(
                    f"agent: llama-server exited with {self._proc.returncode}; see "
                    f"{data_dir() / 'agent' / 'llama-server.log'}"
                )
            if self.healthy():
                return self._base
            time.sleep(0.5)
        raise AgentError(f"agent: llama-server not healthy after {wait_s:.0f}s")

    def stop(self) -> None:
        p = self._proc
        if p is None:
            return
        self._proc = None
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
