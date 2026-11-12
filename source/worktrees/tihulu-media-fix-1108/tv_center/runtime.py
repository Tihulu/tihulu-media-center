"""Optional isolated Argos translation runtime for the native TV application.

No import/install side effects. Installation is a confirmed user action and
never runs as root. The system interpreter and default non-AI TV playback
remain usable if this optional environment is absent.
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path.home() / ".local/share/tihulu-tv-center/ai-runtime"
MARKER = ".tihulu-owned-ai-runtime"
ARGOS_READY = ".tihulu-argos-ready"

class RuntimeErrorAI(RuntimeError):
    pass

class AIRuntime:
    def __init__(self, root=None):
        self.root = Path(root or ROOT).expanduser()
        self.marker = self.root / MARKER

    def status(self):
        py = self.root / "bin/python3"
        return {"installed": self.marker.is_file() and py.is_file()
                and (self.root / ARGOS_READY).is_file(),
                "python": str(py), "path": str(self.root)}

    def _guard(self):
        if self.root.is_symlink():
            raise RuntimeErrorAI("Refusing symlinked AI runtime directory")
        if not self.root.resolve().is_relative_to(Path.home().resolve()):
            raise RuntimeErrorAI("AI runtime path must be within user's home")
        if self.root.exists() and not self.root.is_dir():
            raise RuntimeErrorAI("AI runtime path is not a directory")
        if self.root.exists() and any(self.root.iterdir()) and not self.marker.is_file():
            raise RuntimeErrorAI("Refusing to overwrite unowned runtime directory")

    def install_argos(self):
        if os.geteuid() == 0:
            raise RuntimeErrorAI("Do not install optional Python AI packages as root")
        self._guard()
        self.root.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("TIHULU TV Center managed optional runtime\n")
        try:
            subprocess.run([sys.executable, "-m", "venv", "--system-site-packages",
                            str(self.root)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           check=True, timeout=180)
            python = self.root/"bin/python3"
            result = subprocess.run([str(python), "-m", "pip", "install",
                                     "--disable-pip-version-check",
                                     "argostranslate>=1.10,<2.0"],
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    timeout=1200, check=False)
            if result.returncode != 0:
                raise RuntimeErrorAI("Argos installation failed: " +
                    result.stderr.decode("utf-8", "replace")[-600:])
            # The directory marker alone does not mean an interrupted pip
            # installation is usable. Mark readiness only after success.
            (self.root / ARGOS_READY).write_text("argos installed\n", encoding="utf-8")
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeErrorAI("Optional runtime installation failed: " + str(exc)[:300]) from exc
        return "Argos installed in "+str(self.root)+". Restart TV Center to activate."

    def uninstall(self):
        self._guard()
        if not self.marker.is_file():
            return "No owned optional runtime to remove"
        if Path(sys.executable).resolve().is_relative_to(self.root.resolve()):
            raise RuntimeErrorAI("Runtime currently active: close TV Center and use 'tihulu-tv-center remove-runtime'")
        shutil.rmtree(self.root)
        return "Optional AI Python runtime removed (TV Center and model files preserved)"

def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    runtime = AIRuntime()
    if command == "status":
        print(runtime.status())
    elif command == "remove":
        print(runtime.uninstall())
    elif command == "install-argos":
        print(runtime.install_argos())
    else:
        raise SystemExit("Usage: python -m tv_center.runtime [status|install-argos|remove]")

if __name__ == "__main__":
    main()
