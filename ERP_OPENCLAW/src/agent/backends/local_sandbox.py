# src/agent/backends/local_sandbox.py
"""本地 WSL 沙箱后端 —— 无需部署 OpenSandbox 即可获得真实 Linux 执行环境。

设计要点
--------
* 通过 ``wsl -d <distro> -u <user> -- bash -lc "<command>"`` 执行命令，
  因此沙箱内的绝对路径（/skills、/analysis、/AGENTS.md、/opt/skills-venv）
  与 Linux 语义完全一致，**不需要做任何路径映射**。
* 文件上传/下载走 base64，保证二进制安全与 UTF-8 正确性。
* 与 :class:`OpenSandboxBackend` 实现同一套 ``BaseSandbox`` 协议，
  因此可以无缝替换（见 ``sandbox_setup.py``）。

安全提示
--------
该后端默认以 WSL 的 root 用户在**本机**执行任意命令，仅适合个人开发环境。
生产环境请使用 OpenSandbox（SANDBOX_MODE=opensandbox）。
"""
from __future__ import annotations

import base64
import logging
import shutil
import subprocess
from typing import Callable, cast

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

logger = logging.getLogger(__name__)

SyncPollingInterval = float | Callable[[float], float]


class LocalSandboxError(RuntimeError):
    """本地沙箱不可用（未安装 WSL / 发行版不存在等）。"""


class LocalWslSandboxBackend(BaseSandbox):
    """基于本机 WSL 发行版的沙箱后端。"""

    # 与 OpenSandbox 镜像保持一致的 PATH 注入策略：
    # 把 /opt/skills-venv/bin 放在最前面，使 python / pip 自动路由到 venv。
    SANDBOX_PATH = (
        "/opt/skills-venv/bin:"
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )

    def __init__(
        self,
        *,
        distro: str,
        user: str = "root",
        timeout: int = 60 * 60,
        sync_polling_interval: SyncPollingInterval = 0.1,
        sandbox_id: str | None = None,
    ) -> None:
        if shutil.which("wsl") is None:
            raise LocalSandboxError(
                "未找到 wsl.exe。请安装 WSL2 并至少安装一个发行版，"
                "或将 SANDBOX_MODE 改为 opensandbox 并部署 OpenSandbox 服务。"
            )

        self._distro = distro
        self._user = user
        self._default_timeout = timeout
        self._sandbox_id = sandbox_id or f"local-wsl:{distro}"

        # 处理轮询策略（保持与 OpenSandboxBackend 相同的接口形态）
        if callable(sync_polling_interval):
            polling_strategy = cast("Callable[[float], float]", sync_polling_interval)
        else:

            def polling_strategy(_elapsed: float) -> float:
                return float(sync_polling_interval)

        self._sync_polling_interval = polling_strategy

        if not self._distro_exists():
            raise LocalSandboxError(
                f"WSL 发行版 '{distro}' 不存在。可用发行版请执行 `wsl -l -v` 查看，"
                f"并通过环境变量 WSL_DISTRO 指定。"
            )

        logger.info("本地 WSL 沙箱就绪，发行版=%s 用户=%s", distro, user)

    # ------------------------------------------------------------------
    # 基础能力
    # ------------------------------------------------------------------
    @property
    def id(self) -> str:
        return self._sandbox_id

    def _distro_exists(self) -> bool:
        """检查发行版是否存在（wsl -l -q 输出为 UTF-16LE）。"""
        try:
            proc = subprocess.run(
                ["wsl", "-l", "-q"],
                capture_output=True,
                timeout=60,
            )
        except Exception as exc:  # pragma: no cover - 环境相关
            logger.warning("调用 wsl -l -q 失败: %s", exc)
            return False

        raw = proc.stdout or b""
        for enc in ("utf-16-le", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:  # pragma: no cover
            return False

        names = {line.strip().lstrip("\ufeff") for line in text.splitlines() if line.strip()}
        return self._distro in names

    def _run_wsl(
        self,
        command: str,
        *,
        timeout: int,
        stdin_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess:
        """执行一条 bash 命令。"""
        argv = [
            "wsl",
            "-d",
            self._distro,
            "-u",
            self._user,
            "--",
            "bash",
            "-lc",
            command,
        ]
        return subprocess.run(
            argv,
            input=stdin_bytes,
            capture_output=True,
            timeout=timeout,
            cwd=None,
        )

    # ------------------------------------------------------------------
    # SandboxBackendProtocol
    # ------------------------------------------------------------------
    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """在 WSL 沙箱内执行一条 shell 命令。"""
        effective_timeout = timeout if timeout is not None else self._default_timeout
        wrapped = f'export PATH="{self.SANDBOX_PATH}:$PATH" && {command}'
        logger.debug("WSL 执行: %s (timeout=%ss)", command[:120], effective_timeout)

        try:
            proc = self._run_wsl(wrapped, timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            logger.warning("命令在 %s 秒后超时", effective_timeout)
            return ExecuteResponse(
                output=f"命令在 {effective_timeout} 秒后超时",
                exit_code=124,
                truncated=False,
            )
        except Exception as exc:  # pragma: no cover - 环境相关
            logger.error("执行命令时发生错误: %s", exc, exc_info=True)
            return ExecuteResponse(
                output=f"执行命令时出错：{exc}",
                exit_code=1,
                truncated=False,
            )

        stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")

        output = stdout
        if stderr.strip():
            output += f"\n<stderr>{stderr.strip()}</stderr>"

        return ExecuteResponse(
            output=output,
            exit_code=proc.returncode,
            truncated=False,
        )

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """从沙箱下载文件（base64 传输，二进制安全）。"""
        responses: list[FileDownloadResponse] = []

        for path in paths:
            if not path.startswith("/"):
                responses.append(
                    FileDownloadResponse(path=path, content=None, error="invalid_path")
                )
                continue

            try:
                proc = self._run_wsl(
                    f"base64 -w0 -- {_sh_quote(path)}", timeout=120
                )
                if proc.returncode != 0:
                    responses.append(
                        FileDownloadResponse(
                            path=path, content=None, error="file_not_found"
                        )
                    )
                    continue

                encoded = (proc.stdout or b"").decode("ascii", errors="ignore").strip()
                content = base64.b64decode(encoded) if encoded else b""
                responses.append(
                    FileDownloadResponse(path=path, content=content, error=None)
                )
            except Exception as exc:  # pragma: no cover - 环境相关
                logger.warning("下载 %s 失败: %s", path, exc)
                responses.append(
                    FileDownloadResponse(path=path, content=None, error=str(exc))
                )

        return responses

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """上传文件到沙箱（base64 传输，二进制安全）。"""
        responses: list[FileUploadResponse] = []

        for path, content in files:
            if not path.startswith("/"):
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
                continue

            try:
                if isinstance(content, str):
                    content = content.encode("utf-8")
                encoded = base64.b64encode(content).decode("ascii")
                parent = path.rsplit("/", 1)[0] or "/"
                script = (
                    f"mkdir -p {_sh_quote(parent)} && "
                    f"printf '%s' {_sh_quote(encoded)} | base64 -d > {_sh_quote(path)}"
                )
                proc = self._run_wsl(script, timeout=120)
                if proc.returncode != 0:
                    err = (proc.stderr or b"").decode("utf-8", errors="replace")
                    responses.append(
                        FileUploadResponse(path=path, error=f"upload_failed: {err.strip()}")
                    )
                else:
                    responses.append(FileUploadResponse(path=path, error=None))
            except Exception as exc:  # pragma: no cover - 环境相关
                responses.append(FileUploadResponse(path=path, error=str(exc)))

        return responses


def _sh_quote(value: str) -> str:
    """安全地把字符串包成单引号 shell 参数。"""
    return "'" + value.replace("'", "'\"'\"'") + "'"
