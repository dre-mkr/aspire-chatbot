"""A thin shim so the tracks can read the app's own persona label table."""
import os, sys
BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
from app.prompting.personas.names import display_name, every_label, all_labels  # noqa: F401,E402
