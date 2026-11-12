"""Launch native TV Center or inspect its dependencies without touching hardware."""
import json
import sys
from .core import receiver_status, discover_channels

def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "doctor":
        print(json.dumps({"receiver": receiver_status(),
                          "channels": [{"name": c.name, "frequency": c.frequency,
                                        "service_id": c.service_id}
                                       for c in discover_channels()]}, indent=2))
        return 0
    from .desktop import main as desktop
    return desktop()

if __name__ == "__main__":
    raise SystemExit(main())
