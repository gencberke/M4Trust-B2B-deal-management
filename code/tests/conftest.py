import sys
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parent.parent

# İki kaynak kökü: offline parser `scripts/`, uygulama paketi `code/` (backend.app...).
sys.path.insert(0, str(_CODE_ROOT / "scripts"))
sys.path.insert(0, str(_CODE_ROOT))
