# src/backends/sandbox_setup.py
"""
OpenSandbox 沙箱的初始化与文件播种模块。

职责:
1. 获取或创建 OpenSandbox 沙箱，包装为 OpenSandboxBackend。
2. 播种技能文件（技能包 SKILL.md）。

注意：AGENTS.md 已迁移到 StoreBackend（全局共享），不经过沙箱。
用户长期记忆（/memories/）由 CompositeBackend 路由到 StoreBackend 持久化。
运行时的增量技能同步由 SkillsSyncMiddleware 负责。
"""
from datetime import timedelta
from pathlib import Path
from typing import List, Tuple

from agent.backends.custom_opensandbox import OpenSandboxBackend
from agent.config import (
    LOCAL_SKILLS_DIR, SANDBOX_SKILLS_ROOT,
)


def setup_sandbox(config, sandbox_id=None, image=None):
    """
    获取或创建沙箱，播种基础文件。

    根据环境变量 ``SANDBOX_MODE`` 选择实现：

    * ``opensandbox`` —— 连接独立部署的 OpenSandbox 服务（需要 ``config``）。
    * ``local``       —— 使用本机 WSL 发行版作为 Linux 沙箱，无需外部依赖。

    Args:
        config: OpenSandbox 的 ConnectionConfigSync 配置（仅 opensandbox 模式使用）。
        sandbox_id: 可选，要连接的现有沙箱 ID（仅 opensandbox 模式使用）。
        image: 可选，创建新沙箱时使用的镜像（仅 opensandbox 模式使用）。

    Returns:
        实现了 ``BaseSandbox`` 协议的沙箱后端实例。
    """
    sandbox = _create_sandbox(config, sandbox_id=sandbox_id, image=image)

    backend = sandbox

    # 预创建 skills 需要的目录，避免 Agent 运行时遇到 FileNotFoundError
    _ensure_dirs(backend)

    # 播种基础文件（AGENTS.md、Skills）
    _seed_files(backend)

    # 创建 Python venv + 预装第三方依赖
    _create_venv(backend)

    return backend


def _create_sandbox(config, sandbox_id=None, image=None):
    """按 SANDBOX_MODE 创建/连接具体的沙箱后端。"""
    # 延迟导入，避免在 local 模式下也强制依赖 opensandbox-sdk
    from agent.env_utils import (
        OPENSANDBOX_IMAGE,
        SANDBOX_MODE,
        WSL_DISTRO,
        WSL_USER,
    )

    if SANDBOX_MODE == "local":
        from agent.backends.local_sandbox import LocalWslSandboxBackend

        print(f"[INFO] 沙箱模式=local，使用 WSL 发行版 '{WSL_DISTRO}'（用户 {WSL_USER}）")
        backend = LocalWslSandboxBackend(distro=WSL_DISTRO, user=WSL_USER)
        print(f"[INFO] 本地 WSL 沙箱就绪，ID: {backend.id}")
        return backend

    if SANDBOX_MODE != "opensandbox":
        raise ValueError(
            f"未知的 SANDBOX_MODE='{SANDBOX_MODE}'，"
            f"可选值：local / opensandbox"
        )

    return _create_opensandbox(config, sandbox_id=sandbox_id, image=image)


def _create_opensandbox(config, sandbox_id=None, image=None) -> OpenSandboxBackend:
    """连接或创建 OpenSandbox 沙箱。"""
    from opensandbox import SandboxSync

    from agent.env_utils import OPENSANDBOX_IMAGE

    if sandbox_id:
        print(f"[INFO] 正在连接到现有沙箱: {sandbox_id}")
        try:
            sandbox = SandboxSync.connect(sandbox_id, connection_config=config)
            print(f"[INFO] 成功连接到沙箱: {sandbox_id}")
        except Exception as e:
            print(f"[WARNING] 连接沙箱失败: {e}，将创建新沙箱")
            sandbox_id = None

    if not sandbox_id:
        if not image:
            image = OPENSANDBOX_IMAGE

        print(f"[INFO] 正在创建新沙箱，使用镜像: {image}")
        sandbox = SandboxSync.create(
            image,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
            env={"PYTHON_VERSION": "3.11"},
            resource={"cpu": "2", "memory": "4Gi"},
            timeout=timedelta(hours=2),
            connection_config=config,
            # network_policy=NetworkPolicy(  # 沙箱网络路由限制策略
            #     defaultAction="deny",
            #     egress=[
            #         NetworkRule(action="allow", target="pypi.org"),
            #         NetworkRule(action="allow", target="*.github.com"),
            #     ]
            # )
        )

    backend = OpenSandboxBackend(sandbox=sandbox)
    print(f"[INFO] 沙箱就绪，ID: {sandbox.id}")
    return backend


# skills 运行时依赖的目录（需在沙箱中预创建）
_SKILL_DIRS = ["/analysis/temp", "/data", "/skills"]

# 所有 Python 依赖统一安装到此 venv，避开系统 Python 的 externally managed 限制
_VENV_PATH = "/opt/skills-venv"
_VENV_PIP = f"{_VENV_PATH}/bin/pip"
# skills 运行时需要的 Python 第三方包
_PREINSTALL_PACKAGES = ["numpy", "pandas", "matplotlib", "requests", "beautifulsoup4"]


def _ensure_dirs(backend) -> None:
    """预创建 skills 运行所需的目录，避免 FileNotFoundError。"""
    for d in _SKILL_DIRS:
        backend.execute(f"mkdir -p {d}")


def _pip_install_args() -> str:
    """pip install 通用参数（索引镜像可通过 SANDBOX_PYPI_INDEX 覆盖）。"""
    from agent.env_utils import SANDBOX_PYPI_INDEX

    return f"-i {SANDBOX_PYPI_INDEX} --default-timeout=60 --no-input -q"


def _create_venv(backend) -> None:
    """创建沙箱级 Python venv，并预装 skills 所需的第三方包。

    系统 Python 设置了 externally managed 限制（PEP 668），--system 安装会被拒绝。
    因此创建一个统一的 venv，并将 /opt/skills-venv/bin 注入 SANDBOX_PATH 最前面，
    所有 skill 的 python/pip 命令自动路由到 venv，无需改任何脚本。

    可通过 SANDBOX_SETUP_VENV=0 跳过（离线环境或不需要 Python 分析时）。
    """
    from agent.env_utils import SANDBOX_SETUP_VENV

    if not SANDBOX_SETUP_VENV:
        print("[INFO] SANDBOX_SETUP_VENV=0，跳过 Python venv 预装")
        return

    pip_args = _pip_install_args()

    # 1. 创建 venv（幂等：已存在则跳过）
    result = backend.execute(f"python3 -m venv {_VENV_PATH}", timeout=180)
    if result.exit_code != 0:
        print(f"[WARNING] venv 创建失败: {result.output[:200]}")
        return
    print(f"[INFO] Python venv 就绪: {_VENV_PATH}")

    # 2. 升级 pip（镜像加速，120s 超时）
    backend.execute(f"{_VENV_PIP} install --upgrade pip {pip_args}", timeout=180)

    # 3. 预装依赖（sentinel 避免重复安装）
    #    sentinel 放在 venv 内部而非 /tmp —— WSL 重启会清空 /tmp，
    #    放在 /tmp 会导致每次冷启动都重新走一遍 pip 解析。
    sentinel_dir = f"{_VENV_PATH}/.installed"
    backend.execute(f"mkdir -p {sentinel_dir}")
    for pkg in _PREINSTALL_PACKAGES:
        sentinel = f"{sentinel_dir}/{pkg}"
        check = backend.execute(f"test -f {sentinel}")
        if check.exit_code == 0:
            continue
        # 若包已就绪（例如上次装完但 sentinel 丢失），直接补 sentinel，跳过联网安装
        probe = backend.execute(f"{_VENV_PIP} show {pkg} >/dev/null 2>&1")
        if probe.exit_code == 0:
            backend.execute(f"touch {sentinel}")
            print(f"[INFO]   {pkg} 已存在，跳过安装")
            continue
        print(f"[INFO] 正在安装 Python 依赖: {pkg}...（首次安装较慢，请耐心等待）")
        result = backend.execute(
            f"{_VENV_PIP} install {pkg} {pip_args}",
            timeout=600,
        )
        if result.exit_code == 0:
            backend.execute(f"touch {sentinel}")
            print(f"[INFO]   {pkg} 安装成功")
        else:
            print(f"[WARNING] {pkg} 安装失败: {result.output[:300]}")


def _seed_files(backend) -> None:
    """
    将本地技能文件上传到沙箱。

    AGENTS.md 已迁移到 StoreBackend（全局共享，不经过沙箱）。
    仅上传在沙箱中尚不存在的文件，避免覆盖已更新的内容。
    """
    file_mapping: List[Tuple[Path, str]] = []

    # 遍历 skills 目录，添加所有技能文件
    skills_base = Path(LOCAL_SKILLS_DIR)
    if skills_base.exists():
        for skill_dir in skills_base.iterdir():
            if not skill_dir.is_dir():
                continue
            for local_file in skill_dir.rglob("*"):
                if local_file.is_file():
                    rel = local_file.relative_to(skills_base).as_posix()
                    sandbox_path = f"{SANDBOX_SKILLS_ROOT}/{rel}"
                    file_mapping.append((local_file, sandbox_path))

    # 收集需要上传的文件
    to_upload: List[Tuple[str, bytes]] = []
    for local_path, sandbox_path in file_mapping:
        if not local_path.exists():
            continue
        local_content = local_path.read_bytes()
        # 用 test -f 检测文件是否存在（无 ERROR 日志），避免 download_files 对 404 打 ERROR
        check = backend.execute(f"test -f {sandbox_path}")
        if check.exit_code == 0:
            try:
                results = backend.download_files([sandbox_path])
                if results and results[0].content and not results[0].error:
                    remote_content = results[0].content
                    if isinstance(remote_content, str):
                        remote_content = remote_content.encode("utf-8")
                    if remote_content == local_content:
                        continue
            except Exception:
                pass
        to_upload.append((sandbox_path, local_content))

    if to_upload:
        print(f"[INFO] 正在上传 {len(to_upload)} 个基础文件...")
        backend.upload_files(to_upload)
        print("[INFO] 基础文件上传完成。")
    else:
        print("[INFO] 所有基础文件已就绪，无需上传。")