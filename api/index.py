import sys
from pathlib import Path

# Ensure project root is on the path so `server` can be imported
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from server import app
