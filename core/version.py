"""Application version for deployment records and backup manifests (the git commit baked into the image)."""
import os
from pathlib import Path


def app_version() -> str:
    env = os.environ.get('APP_VERSION', '').strip()
    if env:
        return env
    marker = Path(__file__).resolve().parent.parent / 'VERSION'
    try:
        return marker.read_text().strip() or 'unknown'
    except OSError:
        return 'dev'
