"""验证 LocalWslSandboxBackend 的 execute / upload / download 三项核心能力。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.backends.local_sandbox import LocalWslSandboxBackend  # noqa: E402
from agent.env_utils import SANDBOX_MODE, WSL_DISTRO, WSL_USER  # noqa: E402


def main() -> int:
    print(f"SANDBOX_MODE = {SANDBOX_MODE}")
    backend = LocalWslSandboxBackend(distro=WSL_DISTRO, user=WSL_USER)
    print(f"sandbox id = {backend.id}")
    failures = []

    # 1. execute：基本 shell
    r = backend.execute("echo HELLO_FROM_SANDBOX && uname -s")
    print(f"[execute] exit={r.exit_code} out={r.output.strip()!r}")
    if r.exit_code != 0 or "HELLO_FROM_SANDBOX" not in r.output:
        failures.append("execute 基本命令失败")

    # 2. execute：python 可用性
    r = backend.execute("python3 --version")
    print(f"[execute] python3 -> exit={r.exit_code} out={r.output.strip()!r}")

    # 3. upload -> download 往返（含中文与二进制）
    payload = "中文内容测试\nline2\n".encode("utf-8") + bytes(range(256))
    target = "/analysis/temp/_roundtrip.bin"
    up = backend.upload_files([(target, payload)])
    print(f"[upload] {up[0].path} error={up[0].error}")
    if up[0].error:
        failures.append(f"upload 失败: {up[0].error}")

    down = backend.download_files([target])
    got = down[0].content
    print(f"[download] len={len(got) if got else 0} error={down[0].error}")
    if got != payload:
        failures.append("upload/download 往返内容不一致")
    else:
        print("       往返内容一致 ✅")

    # 4. BaseSandbox 继承的文件操作（依赖 execute 实现）
    try:
        w = backend.write("/analysis/temp/_base.txt", "hello-base\n")
        print(f"[BaseSandbox.write] {w}")
        rd = backend.read("/analysis/temp/_base.txt")
        text = getattr(rd, "content", None) or getattr(rd, "data", None) or str(rd)
        print(f"[BaseSandbox.read] {str(text)[:120]!r}")
        ls = backend.ls("/analysis/temp")
        print(f"[BaseSandbox.ls] {str(ls)[:200]}")
    except Exception as exc:
        print(f"[BaseSandbox] 文件操作异常: {type(exc).__name__}: {exc}")
        failures.append(f"BaseSandbox 文件操作失败: {exc}")

    # 5. 下载不存在的文件应返回 error 而非抛异常
    miss = backend.download_files(["/analysis/temp/_does_not_exist_xyz"])
    print(f"[download missing] error={miss[0].error}")
    if miss[0].error is None:
        failures.append("下载不存在文件未返回 error")

    print("\n===== 结果 =====")
    if failures:
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("  ✅ 本地 WSL 沙箱后端全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
