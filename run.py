#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import signal
import socket
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
DEV_HOST = os.environ.get("BUDGETBEAGLE_DEV_HOST", "0.0.0.0")
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
PORT_SCAN_LIMIT = 100


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def configured_port(env_name: str, default: int, env_values: dict[str, str] | None = None) -> int:
    raw = os.environ.get(env_name, "") or (env_values or {}).get(env_name, "")
    if not raw:
        return default

    try:
        port = int(raw)
    except ValueError:
        fail(f"{env_name} must be a TCP port number. Current value: {raw}")

    if not 1 <= port <= 65535:
        fail(f"{env_name} must be between 1 and 65535. Current value: {raw}")

    return port


def is_port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
    except OSError:
        return False

    return True


def find_available_port(preferred: int, label: str, env_name: str) -> int:
    last_port = min(preferred + PORT_SCAN_LIMIT - 1, 65535)
    for port in range(preferred, last_port + 1):
        if is_port_available(DEV_HOST, port):
            if port != preferred:
                print(f"{label} port {preferred} is unavailable; using {port}.", flush=True)
            return port

    fail(f"No available {label.lower()} port found from {preferred} to {last_port}. Set {env_name} to an open port.")


def cors_origins_for(frontend_port: int, env_values: dict[str, str] | None = None) -> str:
    raw_origins = os.environ.get("BUDGETBEAGLE_CORS_ORIGINS", "") or (env_values or {}).get("BUDGETBEAGLE_CORS_ORIGINS", "")
    configured = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    launcher_origins = [f"http://localhost:{frontend_port}", f"http://127.0.0.1:{frontend_port}"]
    return ",".join(dict.fromkeys(configured + launcher_origins))


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


def start_process(command: list[str | Path], cwd: Path, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    printable = " ".join(str(part) for part in command)
    print(f"$ {printable}", flush=True)
    process_env = None
    if env is not None:
        process_env = os.environ.copy()
        process_env.update(env)
    return subprocess.Popen([str(part) for part in command], cwd=cwd, env=process_env, **process_kwargs())


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

    backend_env_values = parse_env_file(BACKEND_DIR / ".env")
    backend_port = find_available_port(
        configured_port("BUDGETBEAGLE_BACKEND_PORT", DEFAULT_BACKEND_PORT, backend_env_values),
        "Backend",
        "BUDGETBEAGLE_BACKEND_PORT",
    )
    frontend_port = find_available_port(
        configured_port("BUDGETBEAGLE_FRONTEND_PORT", DEFAULT_FRONTEND_PORT, backend_env_values),
        "Frontend",
        "BUDGETBEAGLE_FRONTEND_PORT",
    )
    app_url = f"http://localhost:{frontend_port}"
    api_url = f"http://localhost:{backend_port}"

    step("Starting backend and frontend")
    print(f"Backend API: {api_url}", flush=True)
    print(f"Frontend app: {app_url}", flush=True)

    processes = [
        (
            "Backend",
            start_process(
                [python, "-m", "uvicorn", "main:app", "--reload", "--host", DEV_HOST, "--port", str(backend_port)],
                BACKEND_DIR,
                env={"BUDGETBEAGLE_CORS_ORIGINS": cors_origins_for(frontend_port, backend_env_values)},
            ),
        ),
        (
            "Frontend",
            start_process(
                [node, vite_bin, "--host", DEV_HOST, "--port", str(frontend_port), "--strictPort"],
                FRONTEND_DIR,
                env={"VITE_API_URL": os.environ.get("VITE_API_URL", api_url)},
            ),
        ),
    ]

    try:
        time.sleep(2)
        webbrowser.open(app_url)
        print(f"\nApp is starting at {app_url}. Press Ctrl+C to stop.", flush=True)
        return wait_for_processes(processes)
    except KeyboardInterrupt:
        print("\nReceived Ctrl+C.", flush=True)
        return 0
    finally:
        stop_processes(processes)


def launcher_check() -> int:
    check_python_version()
    node, npm = check_node_version()
    env_path = BACKEND_DIR / ".env"
    example_path = BACKEND_DIR / ".env.example"
    env_values = parse_env_file(env_path if env_path.exists() else example_path)
    backend_port = configured_port("BUDGETBEAGLE_BACKEND_PORT", DEFAULT_BACKEND_PORT, env_values)
    frontend_port = configured_port("BUDGETBEAGLE_FRONTEND_PORT", DEFAULT_FRONTEND_PORT, env_values)
    node_version = subprocess.run([node, "-v"], capture_output=True, text=True, check=False).stdout.strip()
    npm_version = subprocess.run([npm, "-v"], capture_output=True, text=True, check=False).stdout.strip()
    print("BudgetBeagle launcher smoke check passed.")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Node: {node_version}")
    print(f"npm: {npm_version}")
    print(f"Backend env source: {'backend/.env' if env_path.exists() else 'backend/.env.example'}")
    print(f"Backend port: {backend_port}")
    print(f"Frontend port: {frontend_port}")
    return 0


def main() -> int:
    if "--check" in sys.argv or "--smoke" in sys.argv:
        return launcher_check()
    check_python_version()
    node, npm = check_node_version()
    backend_python = setup_backend()
    setup_frontend(npm)
    ensure_backend_env()
    return start_app(backend_python, node)


if __name__ == "__main__":
    raise SystemExit(main())
