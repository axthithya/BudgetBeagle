#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


MIN_PYTHON = (3, 10)
MIN_NODE_MAJOR = 18

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
VENV_DIR = BACKEND_DIR / ".venv"
APP_URL = "http://localhost:5173"


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        current = ".".join(map(str, sys.version_info[:3]))
        required = ".".join(map(str, MIN_PYTHON))
        fail(f"Python {required}+ is required. Current version: {current}")


def require_command(command: str, install_hint: str) -> str:
    path = shutil.which(command)
    if not path:
        fail(install_hint)
    return path


def check_node_version() -> tuple[str, str]:
    node = require_command(
        "node",
        "Node.js 18+ is required. Install Node.js and run the launcher again.",
    )
    npm = require_command(
        "npm",
        "npm is required. Install Node.js with npm and run the launcher again.",
    )

    script = (
        "const major = Number(process.versions.node.split('.')[0]);"
        f"process.exit(major >= {MIN_NODE_MAJOR} ? 0 : 1);"
    )
    result = subprocess.run([node, "-e", script], stdout=subprocess.DEVNULL)
    if result.returncode != 0:
        version = subprocess.run(
            [node, "-v"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        fail(f"Node.js {MIN_NODE_MAJOR}+ is required. Current version: {version}")

    return node, npm


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run_command(command: list[str | Path], cwd: Path) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"$ {printable}", flush=True)
    subprocess.check_call([str(part) for part in command], cwd=cwd)


def setup_backend() -> Path:
    python = venv_python()

    if not python.exists():
        step("Creating backend virtual environment")
        run_command([sys.executable, "-m", "venv", VENV_DIR], BACKEND_DIR)

    step("Installing backend dependencies")
    run_command([python, "-m", "pip", "install", "--upgrade", "pip"], BACKEND_DIR)
    run_command([python, "-m", "pip", "install", "-r", BACKEND_DIR / "requirements.txt"], BACKEND_DIR)

    return python


def setup_frontend(npm: str) -> None:
    step("Installing frontend dependencies")
    run_command([npm, "install"], FRONTEND_DIR)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")

    return values


def ensure_backend_env() -> None:
    env_path = BACKEND_DIR / ".env"
    example_path = BACKEND_DIR / ".env.example"

    if not env_path.exists():
        shutil.copyfile(example_path, env_path)
        print(
            "\nCreated backend/.env.\n\n"
            "Fill in GROQ_API_KEY, JWT_SECRET, and AWS credentials if you are not using an\n"
            "existing AWS profile or IAM role, then run the launcher again."
        )
        raise SystemExit(0)

    values = parse_env_file(env_path)
    groq_api_key = values.get("GROQ_API_KEY", "")
    jwt_secret = values.get("JWT_SECRET", "")

    if not groq_api_key or not jwt_secret or jwt_secret.startswith("change-me"):
        print(
            "\nbackend/.env still has placeholder values.\n\n"
            "Set GROQ_API_KEY and replace JWT_SECRET with a long random string. Add AWS\n"
            "credentials here or use the standard AWS credential chain (~/.aws/credentials,\n"
            "environment variables, or an IAM role), then run the launcher again.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def process_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def start_process(command: list[str | Path], cwd: Path) -> subprocess.Popen[bytes]:
    printable = " ".join(str(part) for part in command)
    print(f"$ {printable}", flush=True)
    return subprocess.Popen([str(part) for part in command], cwd=cwd, **process_kwargs())


def signal_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError, ValueError):
        try:
            process.terminate()
        except OSError:
            pass


def force_stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def stop_processes(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    running = [(name, process) for name, process in processes if process.poll() is None]
    if not running:
        return

    print("\nStopping backend and frontend...", flush=True)
    for _, process in running:
        signal_process(process)

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if all(process.poll() is not None for _, process in running):
            return
        time.sleep(0.2)

    for _, process in running:
        force_stop_process(process)


def wait_for_processes(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> int:
    while True:
        for name, process in processes:
            return_code = process.poll()
            if return_code is not None:
                print(f"\n{name} exited with code {return_code}.", flush=True)
                return return_code
        time.sleep(0.5)


def start_app(python: Path, node: str) -> int:
    vite_bin = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_bin.exists():
        fail("Vite was not found in node_modules. Run the launcher again after npm install completes.")

    step("Starting backend and frontend")
    processes = [
        (
            "Backend",
            start_process(
                [python, "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
                BACKEND_DIR,
            ),
        ),
        (
            "Frontend",
            start_process([node, vite_bin, "--host", "0.0.0.0"], FRONTEND_DIR),
        ),
    ]

    try:
        time.sleep(2)
        webbrowser.open(APP_URL)
        print(f"\nApp is starting at {APP_URL}. Press Ctrl+C to stop.", flush=True)
        return wait_for_processes(processes)
    except KeyboardInterrupt:
        print("\nReceived Ctrl+C.", flush=True)
        return 0
    finally:
        stop_processes(processes)


def main() -> int:
    check_python_version()
    node, npm = check_node_version()
    backend_python = setup_backend()
    setup_frontend(npm)
    ensure_backend_env()
    return start_app(backend_python, node)


if __name__ == "__main__":
    raise SystemExit(main())
