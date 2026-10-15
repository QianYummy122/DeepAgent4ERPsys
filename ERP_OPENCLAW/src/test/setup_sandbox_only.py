"""单独执行沙箱初始化（建目录 + 播种技能 + 建 venv 装依赖），便于观察进度。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.backends.sandbox_setup import setup_sandbox  # noqa: E402
from agent.config import SANDBOX_CONFIG  # noqa: E402

if __name__ == "__main__":
    print("开始沙箱初始化...", flush=True)
    backend = setup_sandbox(SANDBOX_CONFIG)
    print(f"沙箱初始化完成: {backend.id}", flush=True)
    r = backend.execute("python -c \"import numpy,pandas,matplotlib;print('numpy',numpy.__version__);print('pandas',pandas.__version__);print('matplotlib',matplotlib.__version__)\"")
    print("依赖自检 ->", r.exit_code, r.output[:500], flush=True)
