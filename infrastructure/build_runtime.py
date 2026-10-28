"""Package the agent for Amazon Bedrock AgentCore Runtime: src/ plus pure-Python dependencies in one zip."""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(__file__).resolve().parent / "build"
SKIP = {"__pycache__"}


def build() -> Path:
    deps = BUILD / "deps"
    out = BUILD / "runtime.zip"
    if deps.exists():
        shutil.rmtree(deps)
    deps.mkdir(parents=True)
    # boto3 and botocore are pure Python, so the same files work on the Linux runtime
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--target", str(deps), "boto3>=1.40"],
                   check=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for base in (deps, ROOT / "src"):
            for path in sorted(base.rglob("*")):
                if path.is_file() and not (SKIP & set(path.parts)) and path.suffix != ".pyc":
                    zf.write(path, path.relative_to(base).as_posix())
    return out


if __name__ == "__main__":
    print(build())
