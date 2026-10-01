import os
from pathlib import Path

class Settings:
    MODEL_API_KEY: str = os.getenv("MODEL_API_KEY", "")
    MODEL_API_BASE_URL: str = os.getenv("MODEL_API_BASE_URL", "").rstrip("/")
    COMPOSIO_API_KEY: str = os.getenv("COMPOSIO_API_KEY", "")
    YDC_API_KEY: str = os.getenv("YDC_API_KEY", "").strip()
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gpt-5-mini")
    DATA_DIR: Path = Path(
        os.getenv("DATA_DIR", str(Path.home() / ".open-dots"))
    ).expanduser().resolve()
    WORKSPACE_ROOT: Path = Path(
        os.getenv("WORKSPACE_ROOT", str(Path(__file__).resolve().parents[2]))
    ).expanduser().resolve()
    WORKSPACE_MAX_FILE_BYTES: int = int(os.getenv("WORKSPACE_MAX_FILE_BYTES", "131072"))
    APPROVAL_TIMEOUT_SECONDS: int = int(os.getenv("APPROVAL_TIMEOUT_SECONDS", "120"))
    AUTH_SESSION_MAX_AGE: int = int(os.getenv("AUTH_SESSION_MAX_AGE", str(30 * 86400)))
    AUTH_COOKIE_SECURE: bool = os.getenv("AUTH_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
    # ``fake`` is retained for deterministic tests. Real deployments should
    # select ``docker`` or ``remote`` explicitly.
    COMPUTER_PROVIDER: str = os.getenv("COMPUTER_PROVIDER", "fake").strip().lower()
    COMPUTER_DOCKER_IMAGE: str = os.getenv(
        "COMPUTER_DOCKER_IMAGE", "open-dots-computer:1.62.1"
    ).strip()
    COMPUTER_DOCKER_BINARY: str = os.getenv("COMPUTER_DOCKER_BINARY", "docker").strip()
    COMPUTER_DOCKER_WORKSPACE_ROOT: Path = Path(
        os.getenv("COMPUTER_DOCKER_WORKSPACE_ROOT", str(DATA_DIR / "computers"))
    ).expanduser().resolve()
    COMPUTER_DOCKER_CPU_LIMIT: str = os.getenv("COMPUTER_DOCKER_CPU_LIMIT", "2.0").strip()
    COMPUTER_DOCKER_MEMORY_LIMIT: str = os.getenv("COMPUTER_DOCKER_MEMORY_LIMIT", "2g").strip()
    COMPUTER_DOCKER_PIDS_LIMIT: int = int(os.getenv("COMPUTER_DOCKER_PIDS_LIMIT", "512"))
    COMPUTER_DOCKER_START_TIMEOUT: float = float(
        os.getenv("COMPUTER_DOCKER_START_TIMEOUT", "20")
    )
    COMPUTER_DOCKER_COMMAND_TIMEOUT: float = float(
        os.getenv("COMPUTER_DOCKER_COMMAND_TIMEOUT", "30")
    )
    COMPUTER_DOCKER_RUNTIME_PORT: int = int(os.getenv("COMPUTER_DOCKER_RUNTIME_PORT", "3000"))
    COMPUTER_DOCKER_SECCOMP_PROFILE: Path = Path(
        os.getenv("COMPUTER_DOCKER_SECCOMP_PROFILE", "/nonexistent/open-dots-seccomp.json")
    ).expanduser().resolve()
    COMPUTER_REMOTE_BASE_URL: str = os.getenv("COMPUTER_REMOTE_BASE_URL", "").rstrip("/")
    COMPUTER_REMOTE_API_KEY: str = os.getenv("COMPUTER_REMOTE_API_KEY", "").strip()
    COMPUTER_REMOTE_AUTH_HEADER: str = os.getenv(
        "COMPUTER_REMOTE_AUTH_HEADER", "Authorization"
    ).strip()
    COMPUTER_REMOTE_AUTH_SCHEME: str = os.getenv(
        "COMPUTER_REMOTE_AUTH_SCHEME", "Bearer"
    ).strip()
    COMPUTER_REMOTE_TIMEOUT: float = float(os.getenv("COMPUTER_REMOTE_TIMEOUT", "30"))
    COMPUTER_REMOTE_START_TIMEOUT: float = float(
        os.getenv("COMPUTER_REMOTE_START_TIMEOUT", "60")
    )
    COMPUTER_REMOTE_WIDTH: int = int(os.getenv("COMPUTER_REMOTE_WIDTH", "1280"))
    COMPUTER_REMOTE_HEIGHT: int = int(os.getenv("COMPUTER_REMOTE_HEIGHT", "720"))
    COMPUTER_REMOTE_FPS: int = int(os.getenv("COMPUTER_REMOTE_FPS", "10"))
    # Other pages allowed to use the API from a browser. Pages this server serves
    # are always allowed (request_guard); `npm run dev` needs its own origin here.
    # No default: whatever runs on localhost:3000 is not Open Dots.
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    HOST: str = os.getenv("HOST", "127.0.0.1")
    # One address for the Mac page, the iPhone app and the API. Not 8000 or
    # 3000: many other tools use those. scripts/lib.sh passes OPEN_DOTS_PORT.
    PORT: int = int(os.getenv("PORT", "4747"))
    # Address linked phones use to reach this computer, e.g. a Tailscale
    # HTTPS name. Detected from the local network when empty.
    PUBLIC_URL: str = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    MOBILE_DIR: Path = Path(
        os.getenv("MOBILE_DIR", str(Path(__file__).resolve().parents[2] / "mobile"))
    ).expanduser().resolve()
    # The Mac page, exported by `next build` (client/next.config.mjs).
    WEB_DIR: Path = Path(
        os.getenv("WEB_DIR", str(Path(__file__).resolve().parents[2] / "client" / "out"))
    ).expanduser().resolve()
    DEVICE_SESSION_MAX_AGE: int = int(os.getenv("DEVICE_SESSION_MAX_AGE", str(400 * 86400)))
    PAIRING_CODE_TTL_SECONDS: int = int(os.getenv("PAIRING_CODE_TTL_SECONDS", "600"))
    # The Mac page on this computer, for links that open it signed in.
    WEB_URL: str = os.getenv("WEB_URL", f"http://localhost:{PORT}").strip().rstrip("/")
    # Updates: this computer follows a branch that CI moves only to tested
    # commits. Checks run while Open Dots is started by scripts/start-mac.sh.
    UPDATE_CHANNEL: str = os.getenv("UPDATE_CHANNEL", "stable").strip() or "stable"
    UPDATE_CHECK_MINUTES: float = float(os.getenv("UPDATE_CHECK_MINUTES", "5"))

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.COMPUTER_DOCKER_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

settings = Settings()
