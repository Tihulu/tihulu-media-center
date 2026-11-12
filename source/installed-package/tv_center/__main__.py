"""Launch native TV Center or inspect its dependencies without touching hardware."""
import json
import sys
from .core import receiver_status, discover_channels
from .satellite import SATELLITES, satellite_hardware_note
from .ai_settings import AISettings
from .whisper_engine import WhisperRuntime
from .runtime import AIRuntime

def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "ai-check":
        from .ai_diagnostics import main as diagnose_ai
        return diagnose_ai()
    if len(sys.argv) >= 2 and sys.argv[1] == "ai-radio-languages":
        # TV and radio share this same read-only installed-model catalog.
        # Discover output targets without downloading models or accessing RF.
        from .installed_languages import catalog
        from textcenter.compute import LANGUAGES
        from .installed_languages import NAMES
        info=catalog(scan_argos=True)
        selected=AISettings().values
        info["selected_translator"]=selected.get("translation_model","argos")
        info["selected_speech_backend"]=selected.get("backend","auto")
        info["speech_enabled"]=bool(selected.get("asr_enabled"))
        # Whisper multilingual weights cover MANY speech languages without
        # separate per-language installations. Report real local model
        # inventory, not imaginary language packs. Explicit .en-only CPU
        # weights cannot reliably recognize other source languages.
        from pathlib import Path
        from .model_market import ModelLibrary
        from .cuda_faster_whisper import FasterWhisperCUDA
        model_path=str(selected.get("model_path") or "")
        speech_inventory=[
            row["name"] for row in ModelLibrary().installed()
            if row["installed"]]
        cuda_available=FasterWhisperCUDA().installed()
        if cuda_available:
            speech_inventory.append("Faster-Whisper Large-v3 Turbo multilingual")
        active_on_disk=bool(model_path and Path(model_path).is_file())
        speech_model_present=active_on_disk or cuda_available or bool(speech_inventory)
        english_only=(bool(model_path) and
                      Path(model_path).stem.lower().endswith(".en")
                      and not cuda_available)
        info["speech_model_present"]=speech_model_present
        info["speech_model_selected"]=(
            Path(model_path).name if model_path else
            "CUDA Faster-Whisper" if cuda_available else
            "No speech model explicitly selected")
        info["speech_models_installed"]=speech_inventory[:25]
        info["speech_languages"]=[
            {"code":code,"label":NAMES.get(code,code.upper()),
             "source":"Whisper multilingual speech support, not a separate language pack",
             "requires_local_model":True}
            for code in LANGUAGES if not english_only or code=="en"]
        print(json.dumps(info,ensure_ascii=False))
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "ai-pairs":
        # Read-only installed language directions; consumed by native DAB
        # selector. No model inference, download, USB or network access.
        from .ai_provision import StarterAI
        ai = AISettings()
        state = StarterAI(ai).status()
        print(json.dumps({
            "installed_pairs": state["installed_pairs"],
            "selected_translator": ai.values.get("translation_model", "argos"),
        }, ensure_ascii=False))
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "ai-market":
        from .settings_ui import open_ai_settings
        from PyQt5.QtWidgets import QApplication
        import os
        if os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
        app = QApplication.instance() or QApplication(["TIHULU Whisper / Translator Market"])
        ai = AISettings()
        ai.configure_environment()
        open_ai_settings(None, ai)
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "media-captions":
        from .media_ai import main as local_media
        return local_media(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "media-captions-ui":
        from .media_ui import main as local_media_gui
        return local_media_gui(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] in ("radio-captions","lyrics-lookup","lyrics-import"):
        from .radio_ai import main as radio
        return radio(sys.argv[1:])
    if len(sys.argv) >= 2 and sys.argv[1] == "hardware-status":
        from .hardware_status import main as hardware_main
        return hardware_main(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "remote-hub":
        from .remote_hub import main as remote_main
        return remote_main(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "kaffeine-doctor":
        from kaffeine_next.diagnostics import main as diagnose
        return diagnose(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "kaffeine-captions":
        from kaffeine_next.captions_overlay import main as captions_main
        return captions_main(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "ai":
        from .ai_provision import main as ai_main
        return ai_main(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "doctor":
        ai = AISettings()
        print(json.dumps({
            "receiver": receiver_status(),
            "channels": [{"name": c.name, "frequency": c.frequency,
                          "service_id": c.service_id} for c in discover_channels()],
            "satellite_profiles": SATELLITES,
            "satellite_hardware_note": satellite_hardware_note(),
            "satellite_hardware_verified": False,
            "optional_ai": {
                "asr_enabled": ai.values["asr_enabled"],
                "translation_enabled": ai.values["translation_enabled"],
                "requested_backend": ai.values["backend"],
                "whisper_cpu_engine_installed": WhisperRuntime().ready(),
                "argos_runtime": AIRuntime().status()["installed"],
                "starter_bundle": __import__("tv_center.ai_provision", fromlist=["StarterAI"]).StarterAI(ai).status()
            }
        }, indent=2, ensure_ascii=False))
        return 0
    # Kaffeine owns normal TV, scanning and playback. Python only supplies
    # AI, Teletext decoding and optional mobile access.
    if len(sys.argv) >= 2 and sys.argv[1] == "legacy-player":
        from .desktop import main as desktop
        return desktop()
    if len(sys.argv) == 1 or sys.argv[1] in ("tv", "watch"):
        from pathlib import Path
        import os
        launcher = Path.home() / ".local/bin/tihulu-kaffeine"
        if not launcher.is_file():
            print("Kaffeine core not installed: run kaffeine_next/install.sh. "
                  "No fallback scanner will start.", file=sys.stderr)
            return 2
        arguments = sys.argv[2:] if len(sys.argv) > 1 else []
        os.execv(str(launcher), [str(launcher), "--lastchannel", *arguments])
    print("Unknown command. Use: tv, ai-market, ai, doctor, "
          "kaffeine-captions, kaffeine-doctor, ai-check, media-captions, "
          "media-captions-ui, radio-captions, lyrics-lookup, lyrics-import, remote-hub, legacy-player", file=sys.stderr)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
