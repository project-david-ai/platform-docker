# start_orchestration.py
#
# Deployment orchestrator for the Project David / Entities platform.
#
# VERSION: 1.23.4-Full-Fix (Restores 'app', Fixes Tests, Auto-Gen & Manifest)
#
from __future__ import annotations

import importlib.metadata
import importlib.resources
import logging
import os
import platform as _platform
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional
from urllib.parse import quote_plus

import typer

# ---------------------------------------------------------------------------
# FALLBACK TEMPLATES
# ---------------------------------------------------------------------------
_CONFIG_TEMPLATES = {
    "docker-compose.training.yml": """
services:
  training-api:
    image: thanosprime/projectdavid-training-api:latest
    container_name: training_api
    environment:
      - RAY_ADDRESS=${RAY_ADDRESS:-}
      - TRAINING_PROFILE=${TRAINING_PROFILE:-laptop}
      - DATABASE_URL=${DATABASE_URL}
    ports:
      - "9001:9001"
    volumes:
      - ${SHARED_PATH:-./shared_data}:/app/data
    networks:
      - default
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  training-worker:
    image: thanosprime/projectdavid-training-worker:latest
    container_name: training_worker
    environment:
      - RAY_ADDRESS=${RAY_ADDRESS:-}
    volumes:
      - ${SHARED_PATH:-./shared_data}:/app/data
    networks:
      - default
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
""",
}

# ---------------------------------------------------------------------------
# Container guard
# ---------------------------------------------------------------------------


def _running_in_docker() -> bool:
    return os.getenv("RUNNING_IN_DOCKER") == "1" or Path("/.dockerenv").exists()


if _running_in_docker():
    print("[error] This script manages the Docker Compose stack from the HOST machine only.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Optional third-party imports
# ---------------------------------------------------------------------------
try:
    import yaml
except ImportError:
    typer.echo("[error] PyYAML is required: pip install PyYAML", err=True)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    typer.echo("[error] python-dotenv is required: pip install python-dotenv", err=True)
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

PACKAGE_NAME = "projectdavid_platform"
BASE_COMPOSE_FILE = "docker-compose.yml"
TRAINING_COMPOSE_FILE = "docker-compose.training.yml"
API_SERVICE_NAME = "api"
API_CONTAINER_NAME = "fastapi_cosmic_catalyst"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class Orchestrator:

    _ENV_FILE = ".env"

    _GENERATED_SECRETS = [
        "SIGNED_URL_SECRET",
        "API_KEY",
        "MYSQL_ROOT_PASSWORD",
        "MYSQL_PASSWORD",
        "SECRET_KEY",
        "DEFAULT_SECRET_KEY",
        "SANDBOX_AUTH_SECRET",
        "SMBCLIENT_PASSWORD",
        "SEARXNG_SECRET_KEY",
        "ADMIN_API_KEY",
    ]

    _USER_REQUIRED = {
        "HF_TOKEN": ("HF_TOKEN", "HuggingFace access token.", True),
    }

    _INSECURE_VALUES = {
        "default",
        "changeme",
        "your_secret_key_here",
        "changeme_use_a_real_secret",
        "change_me_root",
        "change_me_password",
        "change_me_secret_key",
        "",
    }

    _DEFAULT_VALUES = {
        "TRAINING_PROFILE": "laptop",
        "RAY_ADDRESS": "",
        "RAY_DASHBOARD_PORT": "8265",
        "ASSISTANTS_BASE_URL": "http://localhost:80",
        "MYSQL_HOST": "db",
        "MYSQL_PORT": "3306",
        "MYSQL_DATABASE": "entities_db",
        "MYSQL_USER": "api_user",
    }

    _SUMMARY_KEYS = ["DATABASE_URL", "SHARED_PATH"]

    def __init__(self, args: SimpleNamespace) -> None:
        self.args = args
        self.is_windows = _platform.system() == "Windows"
        self.log = log

        self._ensure_config_files()
        self.base_compose = self._resolve_compose_file(BASE_COMPOSE_FILE)
        self.training_compose = self._resolve_compose_file(TRAINING_COMPOSE_FILE)

        self._check_for_required_env_file()
        self._configure_shared_path()
        self._configure_hf_cache_path()
        self._ensure_dockerignore()

        if getattr(self.args, "training", False):
            self._merge_env_for_overlay("training")

    def _resolve_compose_file(self, filename: str) -> str:
        local = Path.cwd() / filename
        if local.exists():
            return str(local)
        try:
            pkg_files = importlib.resources.files(PACKAGE_NAME)
            resource = pkg_files / filename
            if resource.exists():
                with importlib.resources.as_file(resource) as p:
                    return str(p)
        except Exception:
            pass
        return filename

    def _ensure_config_files(self) -> None:
        configs_to_check = ["docker-compose.yml", "docker-compose.training.yml"]
        for filename in configs_to_check:
            dest = Path.cwd() / filename
            if dest.exists():
                continue
            success = False
            try:
                pkg_files = importlib.resources.files(PACKAGE_NAME)
                resource = pkg_files / filename
                if resource.exists():
                    with importlib.resources.as_file(resource) as src:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
                        success = True
            except Exception:
                pass
            if not success and filename in _CONFIG_TEMPLATES:
                dest.write_text(_CONFIG_TEMPLATES[filename].strip(), encoding="utf-8")

    def _ensure_dockerignore(self):
        di = Path(".dockerignore")
        if not di.exists():
            di.write_text("__pycache__/\n.venv/\nnode_modules/\n*.log\n")

    def _validate_secrets(self):
        failed = False
        for key in self._GENERATED_SECRETS:
            val = os.environ.get(key, "").strip()
            if val in self._INSECURE_VALUES:
                self.log.error("Insecure value for '%s'.", key)
                failed = True
        if failed:
            sys.exit(1)

    def _generate_dot_env_file(self):
        self.log.info("Generating '%s' with secure defaults...", self._ENV_FILE)
        env_values = dict(self._DEFAULT_VALUES)
        for key in self._GENERATED_SECRETS:
            env_values[key] = (
                f"ad_{secrets.token_urlsafe(32)}" if "KEY" in key else secrets.token_hex(32)
            )
        db_pass = env_values.get("MYSQL_PASSWORD")
        escaped_pass = quote_plus(str(db_pass))
        env_values["DATABASE_URL"] = f"mysql+pymysql://api_user:{escaped_pass}@db:3306/entities_db"
        try:
            env_values["PDAVID_VERSION"] = importlib.metadata.version(PACKAGE_NAME)
        except Exception:
            env_values["PDAVID_VERSION"] = "latest"
        env_lines = [f"# Auto-generated by pdavid — {time.ctime()}", ""]
        for k, v in env_values.items():
            env_lines.append(f"{k}={v}")
        Path(self._ENV_FILE).write_text("\n".join(env_lines), encoding="utf-8")

    def _check_for_required_env_file(self):
        if not os.path.exists(self._ENV_FILE):
            self._generate_dot_env_file()
        load_dotenv(dotenv_path=self._ENV_FILE, override=True)

    def _merge_env_for_overlay(self, overlay: str) -> None:
        _OVERLAY_VARS = {
            "training": {
                "TRAINING_PROFILE": "laptop",
                "RAY_ADDRESS": "",
                "RAY_DASHBOARD_PORT": "8265",
            }
        }
        required = _OVERLAY_VARS.get(overlay, {})
        env_path = Path(self._ENV_FILE)
        content = env_path.read_text(encoding="utf-8")
        injected = False
        for key, default in required.items():
            if not re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
                content += f"\n{key}={default}"
                injected = True
        if injected:
            env_path.write_text(content, encoding="utf-8")

    def _run_command(self, cmd_list, check=True, capture_output=False, **kwargs):
        try:
            return subprocess.run(
                cmd_list,
                check=check,
                capture_output=capture_output,
                text=True,
                shell=self.is_windows,
                **kwargs,
            )
        except subprocess.CalledProcessError:
            raise

    def _compose_files(self) -> list:
        files = [
            "--project-directory",
            str(Path.cwd()),
            "--env-file",
            self._env_file_abs,
            "-f",
            self.base_compose,
        ]
        if getattr(self.args, "training", False):
            files += ["-f", self.training_compose]
        return files

    def _handle_up(self):
        self._validate_secrets()
        up_cmd = ["docker", "compose"] + self._compose_files() + ["up", "-d"]
        if getattr(self.args, "pull", False):
            up_cmd.extend(["--pull", "always"])
        self._run_command(up_cmd)

    def run(self):
        if getattr(self.args, "nuke", False):
            confirm = input("DANGER: Type 'confirm nuke': ")
            if confirm == "confirm nuke":
                self._run_command(["docker", "compose"] + self._compose_files() + ["down", "-v"])
            return
        if getattr(self.args, "mode", "up") == "up":
            self._handle_up()

    def _configure_shared_path(self):
        path = os.environ.get("SHARED_PATH", "./shared_data")
        Path(path).mkdir(parents=True, exist_ok=True)

    def _configure_hf_cache_path(self):
        pass

    def _load_compose_config(self):
        try:
            return yaml.safe_load(Path(self.base_compose).read_text())
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Typer App Initialization (THE MISSING BLOCK)
# ---------------------------------------------------------------------------
_TYPER_HELP = (
    "Deployment orchestrator for the Project David / Entities platform.\n\n"
    "Install:    pip install projectdavid-platform\n"
    "Base stack: pdavid --mode up\n"
    "Training:   pdavid --mode up --training\n"
    "Config:     pdavid configure --set HF_TOKEN=hf_abc123\n"
    "Admin:      pdavid bootstrap-admin"
)

app = typer.Typer(name="pdavid", help=_TYPER_HELP, add_completion=False)

# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    mode: str = typer.Option("up"),
    training: bool = typer.Option(False, "--training"),
    nuke: bool = typer.Option(False, "--nuke"),
    pull: bool = typer.Option(False, "--pull"),
    verbose: bool = typer.Option(False, "--verbose"),
):
    if ctx.invoked_subcommand:
        return
    args = SimpleNamespace(mode=mode, training=training, nuke=nuke, pull=pull, verbose=verbose)
    Orchestrator(args).run()


@app.command(name="bootstrap-admin")
def bootstrap_admin(db_url: Optional[str] = None):
    args = SimpleNamespace(training=False)
    o = Orchestrator(args)
    resolved_db_url = db_url or os.environ.get("DATABASE_URL")
    cmd = (
        ["docker", "compose"]
        + o._compose_files()
        + [
            "exec",
            API_SERVICE_NAME,
            "python",
            "/app/src/api/entities_api/cli/bootstrap_admin.py",
            "--db-url",
            resolved_db_url,
        ]
    )
    o._run_command(cmd)


@app.command()
def configure(set_var: List[str] = typer.Option(None, "--set")):
    env_path = Path(".env")
    content = env_path.read_text()
    for s in set_var:
        k, v = s.split("=")
        content = re.sub(rf"^{k}=.*", f"{k}={v}", content, flags=re.M)
    env_path.write_text(content)


if __name__ == "__main__":
    app()
