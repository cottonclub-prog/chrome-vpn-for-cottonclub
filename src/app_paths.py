"""One per-user directory for installed files and native helper data."""
import os
from pathlib import Path

APP_NAME = 'cottonclub vpn for chrome'
APP_DIRECTORY = Path(os.environ.get('LOCALAPPDATA', str(Path(__file__).resolve().parent))) / APP_NAME
