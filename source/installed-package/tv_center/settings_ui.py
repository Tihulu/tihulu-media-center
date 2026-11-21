"""Optional TV AI engine/settings marketplace. No downloads on app startup."""
from __future__ import annotations
import queue
import threading
from pathlib import Path

def open_ai_settings(parent, ai, after_save=None):
    from PyQt5.QtCore import Qt, QTimer, QSettings
    from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
        QFormLayout, QCheckBox, QComboBox, QLabel, QListWidget, QPushButton,
        QFileDialog, QMessageBox, QLineEdit, QWidget, QScrollArea,
        QTabWidget, QListWidgetItem, QInputDialog, QFrame, QGridLayout,
        QSizePolicy, QToolButton, QProgressBar)

    from .model_market import (CATALOG, ModelLibrary, ModelError,
        argos_available_pairs, argos_installed_pairs, argos_install, argos_remove)
    from textcenter.compute import detect_devices, choose_backend
    from .runtime import AIRuntime, RuntimeErrorAI
    from .whisper_engine import WhisperRuntime, WhisperRuntimeError
    from .cuda_faster_whisper import FasterWhisperCUDA
    from .speaker_market import SpeakerMarket
    from .free_speakers import FreeSpeakerMarket
    from .ai_provision import StarterAI
    from .hardware_market import detect_hardware, quick_hardware, model_fit
    from .ai_profiles import (PROFILES, COMPONENTS, profile, local_status,
                              install_components, selection_patch, hardware_issue,
                              component_estimate, progress_fraction)
    from .remote_gpu import (validate_endpoint, save_token, read_token,
                             delete_token, test_connection)
    from .pi_hailo import readiness as hailo_readiness
    from .translation_market import TranslationModelMarket, LICENSE as NLLB_LICENSE
    from .translation_madlad import MadladMarket
    from .deepl_api import read_key, save_key, remove_key
    from .argos_market_bridge import run as run_argos_market

    class Manager(QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("Settings · Optional ASR & Translation Model Market")
            screen = self.screen().availableGeometry()
            self.setMinimumSize(620, 460)
            self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
            self.geometry_store = QSettings("TIHULU", "ModelMarketWindowGeometry")
            self.resize(min(900, max(620, screen.width()-90)),
                        min(730, max(480, screen.height()-90)))
            previous = self.geometry_store.value("geometry")
            if previous:
                try:
                    self.restoreGeometry(previous)
                except (TypeError, ValueError):
                    previous = None
            if not previous or not self.frameGeometry().intersects(screen):
                self.move(max(screen.left()+10, screen.right()-self.width()-18),
                          screen.top()+38)
            self.setStyleSheet("""
                QDialog { background:#0c151f; color:#deebf5; }
                QTabWidget::pane {
                    background:#111d28; border:1px solid #284052;
                    border-radius:8px; top:-1px;
                }
                QTabBar::tab {
                    background:#1c2d3b; color:#aec2d0;
                    border:1px solid #2d4658; padding:10px 14px;
                    border-top-left-radius:6px;
                    border-top-right-radius:6px;
                }
                QTabBar::tab:selected {
                    background:#164d63; color:white;
                    border-bottom:2px solid #42b3c8;
                }
                QScrollArea { background:#111d28; border:0; }
                QWidget#marketPage { background:#111d28; }
                QGroupBox {
                    border:1px solid #2b4355; border-radius:9px;
                    margin-top:15px; padding-top:6px;
                    background:#162430; color:#e6f0f7;
                }
                QGroupBox::title {
                    subcontrol-origin:margin; left:12px;
                    padding:0 5px; color:#b9d8ea;
                }
                QPushButton {
                    background:#20384c; color:#e8f0f6;
                    border:1px solid #36546b; border-radius:6px;
                    padding:7px 12px; min-height:24px;
                }
                QPushButton:hover { background:#2a526e; }
                QPushButton:disabled {
                    background:#192833; color:#6f8798; border-color:#2b3845;
                }
                QLineEdit, QComboBox, QListWidget {
                    background:#0f1a24; color:#ebf4fb;
                    border:1px solid #3a566d; border-radius:6px;
                    padding:5px; selection-background-color:#21678c;
                }
                QLabel, QCheckBox { color:#d9e8f2; }
            """)
            self.ai = ai
            self.work = queue.Queue()
            self.running = False
            self.library = ModelLibrary(ai.values["model_dir"] or None)
            self.hardware = quick_hardware()
            self._compute_busy = False
            self._argos_busy = False
            self._starter_busy = False
            self._profile_inventory_busy = False
            self._profile_scan_pending = False
            self._profile_status_cache = {}
            self._profile_row_widgets = {}
            self._all_status_cache = None
            self._all_status_busy = False
            self._lazy_loaded_tabs = set()
            self._applying_profile = False
            self._manual_custom = False
            self._active_profile = ai.values.get("active_profile","")
            self._custom_base = self._active_profile or "performance"
            self.translation_market = TranslationModelMarket()
            outer = QVBoxLayout(self)
            outer.setContentsMargins(12, 12, 12, 10)
            outer.setSpacing(9)
            # Stage existing sections before moving them to separate
            # independently scrolling tabs. The action footer is kept
            # OUTSIDE all scroll areas so Save is always visible.
            body = QWidget()
            root = QVBoxLayout(body)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(12)
            self.info = QLabel("AI Model Market · Ready-to-use offline Whisper and Translator suites. "
                               "No speech processing occurs until you select subtitles.")
            self.info.setWordWrap(True)
            outer.addWidget(self.info)
            quick = QGroupBox("STARTER BUNDLE  ·  Whisper + DE / EN / TR translator")
            quick_layout = QVBoxLayout(quick)
            self.starter_state = QLabel("Checking installed Whisper and translation packages…")
            self.starter_state.setWordWrap(True)
            quick_layout.addWidget(self.starter_state)
            self.install_starter = QPushButton("Install / repair starter bundle")
            self.install_starter.clicked.connect(self.setup_starter)
            quick_layout.addWidget(self.install_starter)
            starter_description = QLabel(
                "Optional CPU fallback: Whisper Tiny (~78 MB) and four Argos "
                "language pairs. NVIDIA CUDA Turbo is installed separately.")
            starter_description.setWordWrap(True)
            quick_layout.addWidget(starter_description)
            root.addWidget(quick)

            settings = QGroupBox("AI features & compute backend")
            root.addWidget(settings)
            form = QFormLayout(settings)
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            form.setSpacing(9)
            self.asr = QCheckBox("Enable offline live speech transcription")
            self.asr.setChecked(ai.values["asr_enabled"])
            form.addRow(self.asr)
            self.translator = QCheckBox("Enable offline translated subtitles")
            self.translator.setChecked(ai.values["translation_enabled"])
            form.addRow(self.translator)
            self.backend = QComboBox()
            self.backend.addItems(["auto", "gpu", "cpu", "remote"])
            if self.hardware["npu"]["detected"]:
                self.backend.addItem("npu")
            self.backend.setCurrentText(
                ai.values["backend"] if self.backend.findText(
                    ai.values["backend"]) >= 0 else "auto")
            self.backend.setToolTip(
                "NVIDIA CUDA is GPU, NOT NPU. Remote requires explicit TLS and token. NPU is shown only when "
                "a compatible discrete Intel/Hailo accelerator is detected.")
            form.addRow("Inference engine", self.backend)
            self.compute = QLabel("")
            self.compute.setWordWrap(True)
            form.addRow("Detected hardware", self.compute)
            refresh_compute = QPushButton("Refresh CPU / GPU / NPU readiness")
            refresh_compute.clicked.connect(self.inspect_compute)
            form.addRow(refresh_compute)
            self.install_cuda = QPushButton(
                "Advanced: build whisper.cpp CUDA (nvcc required)")
            self.install_cuda.clicked.connect(self.install_cuda_runtime)
            form.addRow(self.install_cuda)
            self.install_fast_cuda = QPushButton(
                "Install / repair NVIDIA CUDA · Faster-Whisper Turbo (no nvcc)")
            self.install_fast_cuda.setToolTip(
                "Isolated user-owned Python environment; verified CTranslate2 "
                "model and CUDA 12 cuBLAS/cuDNN wheels. Does not replace NVIDIA "
                "drivers, whisper.cpp or TV device control.")
            self.install_fast_cuda.clicked.connect(self.install_fast_cuda_runtime)
            self.install_fast_cuda.setStyleSheet(
                "QPushButton{background:#17775b;color:white;"
                "border-radius:7px;padding:11px;font-weight:700}"
                "QPushButton:hover{background:#219b75}"
                "QPushButton:disabled{background:#444;color:#999}")
            form.addRow(self.install_fast_cuda)
            self.verify_fast_cuda = QPushButton(
                "Test NVIDIA CUDA · real local model inference")
            self.verify_fast_cuda.clicked.connect(self.verify_cuda_inference)
            form.addRow(self.verify_fast_cuda)
            self.cuda_status = QLabel("")
            self.cuda_status.setWordWrap(True)
            form.addRow("GPU acceleration",self.cuda_status)
            self.model_path = QLineEdit(ai.values["model_path"])
            self.model_path.setPlaceholderText("No active Whisper model selected")
            form.addRow("CPU GGML model / fallback path", self.model_path)
            self.primary_speech_status = QLabel(
                "CPU model path is NOT proof of the active GPU model. "
                "Choose a profile and Select mode; see live ASR diagnostics "
                "for the engine actually processing audio.")
            self.primary_speech_status.setWordWrap(True)
            form.addRow("GPU primary / CPU fallback",self.primary_speech_status)
            whisper_buttons = QHBoxLayout()
            self.install_whisper = QPushButton("Install CPU Whisper engine (source build)")
            self.install_whisper.clicked.connect(self.install_whisper_runtime)
            self.delete_whisper = QPushButton("Remove managed Whisper engine")
            self.delete_whisper.clicked.connect(self.remove_whisper_runtime)
            whisper_buttons.addWidget(self.install_whisper)
            whisper_buttons.addWidget(self.delete_whisper)
            form.addRow(whisper_buttons)
            self.whisper_state = QLabel("")
            form.addRow("Whisper CPU engine", self.whisper_state)
            self.engine_state = QLabel("")
            form.addRow("Optional AI Python runtime", self.engine_state)
            engine_buttons = QHBoxLayout()
            self.install_engine = QPushButton("Install Argos engine (PyPI, optional)")
            self.install_engine.clicked.connect(self.install_engine_runtime)
            self.remove_engine = QPushButton("Remove managed AI runtime")
            self.remove_engine.clicked.connect(self.remove_engine_runtime)
            engine_buttons.addWidget(self.install_engine)
            engine_buttons.addWidget(self.remove_engine)
            form.addRow(engine_buttons)

            models = QGroupBox("Speech model library · offline + verified online")
            root.addWidget(models)
            models_layout = QVBoxLayout(models)
            search_row = QHBoxLayout()
            self.online_query = QLineEdit()
            self.online_query.setPlaceholderText(
                "Search official Whisper GGML models: turbo, large, medium…")
            self.search_online = QPushButton("Search online / refresh verified catalog")
            self.search_online.clicked.connect(self.refresh_online_models)
            search_row.addWidget(self.online_query,1)
            search_row.addWidget(self.search_online)
            models_layout.addLayout(search_row)
            self.online_state = QLabel(
                "Market lists local models immediately. Online search only on request; "
                "official Hugging Face GGML models with SHA-256 checksums.")
            self.online_state.setWordWrap(True)
            models_layout.addWidget(self.online_state)
            self.models = QListWidget()
            self.models.setMaximumHeight(290)
            models_layout.addWidget(self.models)
            self.active_speech_label = QLabel("Selected speech model: checking settings…")
            self.active_speech_label.setWordWrap(True)
            models_layout.addWidget(self.active_speech_label)
            self.model_path.textChanged.connect(lambda *_: self.populate_models())
            recommended = QLabel(
                "NVIDIA CUDA recommendation (min 12 GB VRAM): prebuilt Large-v3 Turbo "
                "(word-timed live captions). CPU fallback: Small → Medium. "
                "Browse the official verified catalog for other quality "
                "tiers and install/select them here.")
            recommended.setWordWrap(True)
            models_layout.addWidget(recommended)
            discover = QHBoxLayout()
            medium_models = QPushButton("Browse verified Medium GGML")
            medium_models.clicked.connect(
                lambda: self.search_quality_model("medium"))
            turbo_models = QPushButton("Browse verified Large-v3 Turbo GGML")
            turbo_models.clicked.connect(
                lambda: self.search_quality_model("large-v3-turbo"))
            discover.addWidget(medium_models)
            discover.addWidget(turbo_models)
            models_layout.addLayout(discover)
            line = QHBoxLayout()
            self.download = QPushButton("Download & install selected")
            self.download.clicked.connect(self.download_model)
            self.remove = QPushButton("Delete selected installed model")
            self.remove.clicked.connect(self.remove_model)
            self.choose = QPushButton("Use selected")
            self.choose.clicked.connect(self.use_model)
            for b in (self.download, self.remove, self.choose): line.addWidget(b)
            models_layout.addLayout(line)
            line2 = QHBoxLayout()
            browse = QPushButton("Choose an existing GGML model…")
            browse.clicked.connect(self.import_existing)
            storage = QPushButton("Choose storage folder / external SSD…")
            storage.clicked.connect(self.choose_storage)
            line2.addWidget(browse)
            line2.addWidget(storage)
            models_layout.addLayout(line2)
            self.storage_label = QLabel("")
            self.storage_label.setWordWrap(True)
            models_layout.addWidget(self.storage_label)

            langs = QGroupBox("Argos Translate language packs · download / remove")
            root.addWidget(langs)
            trans_layout = QVBoxLayout(langs)
            trans_row = QHBoxLayout()
            self.source = QComboBox()
            self.source.setEditable(True)
            self.source.addItems(["de", "en", "tr", "fr", "es", "pl", "ar", "ja"])
            self.target = QComboBox()
            self.target.setEditable(True)
            self.target.addItems(["tr", "de", "en", "fr", "es", "pl", "ar", "ja"])
            self.source.setToolTip("Type any real ISO 639-1/2 source language code")
            self.target.setToolTip("Type any real ISO 639-1/2 target language code")
            trans_row.addWidget(QLabel("From")); trans_row.addWidget(self.source)
            trans_row.addWidget(QLabel("To")); trans_row.addWidget(self.target)
            trans_layout.addLayout(trans_row)
            lang_info = QLabel(
                "Enter any supported language codes (es, pl, ar, ja, ru…). "
                "Installed pairs work offline; catalog refresh is optional.")
            lang_info.setWordWrap(True)
            trans_layout.addWidget(lang_info)
            self.available = QLabel(
                "Catalog not refreshed. Click Refresh to browse official language pairs.")
            self.available.setWordWrap(True)
            trans_layout.addWidget(self.available)
            self.argos_catalog_list = QListWidget()
            self.argos_catalog_list.setMinimumHeight(135)
            self.argos_catalog_list.setToolTip(
                "Click a language pair to fill From/To. Install and use "
                "without leaving this window; no network calls on startup.")
            self.argos_catalog_list.itemSelectionChanged.connect(
                self.select_argos_catalog_pair)
            trans_layout.addWidget(self.argos_catalog_list)
            controls = QHBoxLayout()
            update = QPushButton("Refresh Argos catalog (internet)")
            update.clicked.connect(self.refresh_argos_catalog)
            install = QPushButton("Install selected pair")
            install.clicked.connect(self.install_argos)
            remove = QPushButton("Uninstall selected pair")
            remove.clicked.connect(self.uninstall_argos)
            test_live = QPushButton("Test selected pair · live Argos runtime")
            test_live.setToolTip(
                "Actually translate a short offline sentence using the SAME "
                "managed Argos worker used by live TV. No receiver/network access.")
            test_live.clicked.connect(self.test_live_argos_pair)
            for b in (update, install, remove, test_live):
                controls.addWidget(b)
            trans_layout.addLayout(controls)
            self.pairs = QLabel("Installed pairs: not inspected")
            trans_layout.addWidget(self.pairs)
            self.installed_argos = QListWidget()
            self.installed_argos.setMaximumHeight(120)
            self.installed_argos.itemSelectionChanged.connect(
                self.select_installed_argos_pair)
            trans_layout.addWidget(self.installed_argos)
            quality = QGroupBox("Translation engines · Argos / NLLB / MADLAD / DeepL")
            quality_layout = QVBoxLayout(quality)
            self.translation_choice = QComboBox()
            self.translation_choice.addItem(
                "Auto · compatible installed offline model; per-language real fallback",
                "auto_offline")
            self.translation_choice.addItem(
                "Direct DE → TR · installed NLLB → MADLAD → Argos fallback (offline)",
                "de_tr_direct")
            self.translation_choice.addItem("Argos Translate · compact offline language packs","argos")
            self.translation_choice.addItem(
                "NLLB-200 600M · multilingual; enter ISO or NLLB codes", "nllb")
            self.translation_choice.addItem(
                "MADLAD-400 3B · Apache-2.0 · GPU · large offline model", "madlad")
            self.translation_choice.addItem(
                "DeepL API · PROPRIETARY online text only · explicit consent", "deepl")
            self.translation_choice.setCurrentIndex(
                max(0,self.translation_choice.findData(
                    ai.values.get("translation_model","argos"))))
            # Translation selection must never synchronously probe NLLB,
            # MADLAD or DeepL; those checks belong to the language tab.
            self.translation_choice.currentIndexChanged.connect(
                self.preview_translator)
            quality_layout.addWidget(self.translation_choice)
            self.translation_selected_label = QLabel("")
            self.translation_selected_label.setWordWrap(True)
            self.translation_choice.setToolTip(
                "Direct DE→TR uses installed NLLB or MADLAD without English. "
                "If neither succeeds, Argos may route through English; "
                "the actual engine is reported in captions diagnostics. "
                "No model is downloaded or cloud provider enabled automatically.")
            quality_layout.addWidget(self.translation_selected_label)
            self.nllb_status = QLabel("")
            self.nllb_status.setWordWrap(True)
            quality_layout.addWidget(self.nllb_status)
            nllb_buttons = QGridLayout()
            nllb_install = QPushButton("Download / repair NLLB")
            nllb_install.clicked.connect(self.install_nllb_model)
            self.nllb_test = QPushButton(
                "Test NLLB offline · real DE → EN translation")
            self.nllb_test.setToolTip(
                "Explicit opt-in: load installed 600M weights and check "
                "actual local translation; no TV or network access.")
            self.nllb_test.clicked.connect(self.test_nllb_model)
            nllb_remove = QPushButton("Remove managed NLLB model")
            nllb_remove.clicked.connect(self.remove_nllb_model)
            use_argos = QPushButton("Use Argos instead · faster backup")
            use_argos.clicked.connect(lambda: (
                self.translation_choice.setCurrentIndex(
                    self.translation_choice.findData("argos")),
                self.feedback.setText(
                    "Argos selected. Click Save settings to use installed packs.")))
            nllb_buttons.addWidget(nllb_install,0,0)
            nllb_buttons.addWidget(self.nllb_test,0,1)
            nllb_buttons.addWidget(use_argos,1,0)
            nllb_buttons.addWidget(nllb_remove,1,1)
            quality_layout.addLayout(nllb_buttons)
            madlad_actions=QGridLayout()
            self.madlad_state=QLabel("MADLAD state not inspected")
            self.madlad_state.setWordWrap(True)
            quality_layout.addWidget(self.madlad_state)
            madlad_install=QPushButton("Install MADLAD 3B · ~12GB CUDA")
            madlad_install.clicked.connect(self.install_madlad_model)
            madlad_test=QPushButton("Test MADLAD offline DE → EN")
            madlad_test.clicked.connect(self.test_madlad_model)
            madlad_remove=QPushButton("Remove managed MADLAD weights")
            madlad_remove.clicked.connect(self.remove_madlad_model)
            madlad_actions.addWidget(madlad_install,0,0)
            madlad_actions.addWidget(madlad_test,0,1)
            madlad_actions.addWidget(madlad_remove,1,0,1,2)
            quality_layout.addLayout(madlad_actions)
            quality_layout.addWidget(QLabel(
                "DeepL is NOT an open/offline model. It sends ONLY decoded text "
                "to its proprietary external API when you select it. "
                "Never enable it without permission from the content owner."))
            self.deepl_key=QLineEdit()
            self.deepl_key.setEchoMode(QLineEdit.Password)
            self.deepl_key.setPlaceholderText(
                "Own DeepL API key · saved locally with mode 0600 (never uploaded to GitHub)")
            quality_layout.addWidget(self.deepl_key)
            deepl_actions=QHBoxLayout()
            set_deepl=QPushButton("Save DeepL key · opt in")
            set_deepl.clicked.connect(self.save_deepl_api_key)
            remove_deepl=QPushButton("Remove local DeepL key")
            remove_deepl.clicked.connect(self.delete_deepl_api_key)
            deepl_actions.addWidget(set_deepl)
            deepl_actions.addWidget(remove_deepl)
            quality_layout.addLayout(deepl_actions)
            self.deepl_status=QLabel("")
            quality_layout.addWidget(self.deepl_status)
            trans_layout.addWidget(quality)
            # No NLLB/MADLAD/PyTorch inventory during widget construction.
            self.nllb_status.setText(
                "Status not loaded yet. Open Language packs to inspect.")
            self.madlad_state.setText("Model status available on Language packs tab.")

            # Keep one window but separate model selection, CUDA diagnostics
            # and translation catalogs into focused tabs, instead of a very
            # tall form where installed models are hard to find.
            tabs = QTabWidget()
            tabs.setDocumentMode(True)

            def scroll_tab(contents):
                area = QScrollArea()
                area.setWidgetResizable(True)
                # Large translated descriptions/buttons must remain reachable
                # on smaller screens instead of being clipped off-screen.
                area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                area.setFrameShape(QFrame.NoFrame)
                contents.setObjectName("marketPage")
                contents.setMinimumWidth(0)
                area.setWidget(contents)
                return area

            speech_page = QWidget()
            speech_stack = QVBoxLayout(speech_page)
            speech_stack.setContentsMargins(12, 16, 12, 12)
            speech_stack.setSpacing(14)
            for section in (quick, settings, models):
                root.removeWidget(section)
                speech_stack.addWidget(section)
            speech_stack.addStretch()
            language_page = QWidget()
            language_stack = QVBoxLayout(language_page)
            language_stack.setContentsMargins(12, 16, 12, 12)
            language_stack.setSpacing(14)
            root.removeWidget(langs)
            language_stack.addWidget(langs)
            language_stack.addStretch()
            profile_page = QWidget()
            profile_layout = QVBoxLayout(profile_page)
            profile_layout.setContentsMargins(12, 16, 12, 12)
            profile_layout.setSpacing(14)
            guided = QGroupBox("Recommended modes · install before selecting")
            guided_layout = QVBoxLayout(guided)
            self.profile_choice = QComboBox()
            self.profile_choice.addItem("Custom · manually adjusted", "custom")
            for key, spec in PROFILES.items():
                self.profile_choice.addItem(spec["name"], key)
            default_recommendation=(
                "pi5" if self.hardware["raspberry_pi_5"] else "performance")
            initial = ai.values.get("active_profile") or default_recommendation
            self._custom_base = (initial if initial in PROFILES
                                 else default_recommendation)
            self.profile_choice.setCurrentIndex(
                max(0, self.profile_choice.findData(initial)))
            guided_layout.addWidget(self.profile_choice)
            self.profile_description = QLabel("")
            self.profile_description.setWordWrap(True)
            guided_layout.addWidget(self.profile_description)
            self.profile_components = QLabel(
                "Checking installed models automatically · no downloads")
            self.profile_components.setWordWrap(True)
            guided_layout.addWidget(self.profile_components)
            self.profile_rows_host = QWidget()
            self.profile_rows_layout = QVBoxLayout(self.profile_rows_host)
            self.profile_rows_layout.setContentsMargins(0,0,0,0)
            self.profile_rows_layout.setSpacing(6)
            guided_layout.addWidget(self.profile_rows_host)
            self.profile_choice.currentIndexChanged.connect(
                self.profile_changed)
            buttons = QHBoxLayout()
            self.profile_inspect = QPushButton("Check installed")
            self.profile_inspect.clicked.connect(self.inspect_profile)
            self.profile_install = QPushButton("Install all")
            self.profile_install.clicked.connect(self.install_profile)
            self.profile_select = QPushButton("Select mode")
            self.profile_select.clicked.connect(self.select_profile)
            for btn in (self.profile_inspect, self.profile_install, self.profile_select):
                buttons.addWidget(btn)
            guided_layout.addLayout(buttons)
            profile_layout.addWidget(guided)
            # CPU tuning and optional real Hailo-10H, never automatic downloads.
            pi_group=QGroupBox("Raspberry Pi 5 · resource settings")
            pi_form=QFormLayout(pi_group)
            self.pi_threads=QComboBox()
            for count in (1,2,3,4):
                self.pi_threads.addItem(str(count)+" whisper.cpp CPU threads",count)
            self.pi_threads.setCurrentIndex(max(0,self.pi_threads.findData(
                ai.values.get("pi_cpu_threads",3))))
            pi_form.addRow("Keep one Pi CPU core for TV / Argos",self.pi_threads)
            profile_layout.addWidget(pi_group)
            self.hailo_group=QGroupBox("AI HAT+ 2 · Hailo-10H Whisper Base")
            hailo_form=QFormLayout(self.hailo_group)
            self.hailo_encoder=QLineEdit(ai.values.get("hailo_encoder_hef",""))
            self.hailo_decoder=QLineEdit(ai.values.get("hailo_decoder_hef",""))
            self.hailo_npy=QLineEdit(ai.values.get("hailo_npy_dir",""))
            def file_picker(field):
                filename,_=QFileDialog.getOpenFileName(
                    self,"Choose locally installed Hailo-10H model (.hef)",
                    str(Path.home()),"Hailo executable (*.hef)")
                if filename: field.setText(filename)
            for label,field in (
                ("Encoder HEF",self.hailo_encoder),
                ("Decoder HEF",self.hailo_decoder)):
                row=QHBoxLayout()
                row.addWidget(field)
                browse=QPushButton("Browse")
                browse.clicked.connect(
                    lambda _,target=field:file_picker(target))
                row.addWidget(browse)
                hailo_form.addRow(label,row)
            npy_row=QHBoxLayout()
            npy_row.addWidget(self.hailo_npy)
            npy_button=QPushButton("Browse")
            def choose_npy():
                folder=QFileDialog.getExistingDirectory(
                    self,"Select folder with Hailo Whisper .npy decoder files",
                    str(Path.home()))
                if folder:self.hailo_npy.setText(folder)
            npy_button.clicked.connect(choose_npy)
            npy_row.addWidget(npy_button)
            hailo_form.addRow("Decoder .npy folder",npy_row)
            self.hailo_fallback=QCheckBox(
                "Fall back to Whisper Tiny CPU when Hailo fails or Spoken=Auto")
            self.hailo_fallback.setChecked(ai.values.get("hailo_cpu_fallback",True))
            hailo_form.addRow(self.hailo_fallback)
            hailo_buttons=QHBoxLayout()
            save_hailo=QPushButton("Save model paths")
            save_hailo.clicked.connect(self.save_hailo_paths)
            inspect_hailo=QPushButton("Check Hailo-10H")
            inspect_hailo.clicked.connect(self.inspect_hailo)
            test_hailo=QPushButton("Test NPU · local silence")
            test_hailo.clicked.connect(self.test_hailo)
            for btn in (save_hailo,inspect_hailo,test_hailo):
                hailo_buttons.addWidget(btn)
            hailo_form.addRow(hailo_buttons)
            self.hailo_status=QLabel(
                "NPU OFF until valid HailoRT, encoder/decoder HEF and NPY paths "
                "are saved and device firmware identifies HAILO10H.")
            self.hailo_status.setWordWrap(True)
            hailo_form.addRow(self.hailo_status)
            hailo_note=QLabel(
                "Install official Raspberry Pi OS hailo-h10-all and Hailo Apps "
                "separately; vendor examples may auto-download missing files. "
                "TIHULU never downloads an NPU model during TV playback. "
                "Argos remains CPU-based; HAT's 8 GB is NOT extra Pi RAM.")
            hailo_note.setWordWrap(True)
            hailo_form.addRow(hailo_note)
            profile_layout.addWidget(self.hailo_group)
            remote_group = QGroupBox("Remote GPU · opt-in TLS speech processing")
            remote_layout = QFormLayout(remote_group)
            self.remote_enabled = QCheckBox(
                "Allow sending spoken TV audio to another GPU computer")
            self.remote_enabled.setChecked(ai.values.get("remote_gpu_enabled", False))
            remote_layout.addRow(self.remote_enabled)
            self.remote_endpoint = QLineEdit(ai.values.get("remote_gpu_url", ""))
            self.remote_endpoint.setPlaceholderText("https://gpu-host.example:8443")
            remote_layout.addRow("HTTPS GPU host", self.remote_endpoint)
            self.remote_fallback = QCheckBox(
                "Fall back to local Auto when remote server unavailable")
            self.remote_fallback.setChecked(ai.values.get("remote_gpu_fallback", True))
            remote_layout.addRow(self.remote_fallback)
            self.remote_token = QLineEdit()
            self.remote_token.setEchoMode(QLineEdit.Password)
            self.remote_token.setPlaceholderText("16–256 character shared private token")
            remote_layout.addRow("Shared secret", self.remote_token)
            remote_buttons = QHBoxLayout()
            save_remote = QPushButton("Save token")
            save_remote.clicked.connect(self.save_remote_token)
            probe = QPushButton("Test TLS · no audio")
            probe.clicked.connect(self.test_remote_gpu)
            remove_remote = QPushButton("Remove token")
            remove_remote.clicked.connect(self.remove_remote_token)
            for btn in (save_remote, probe, remove_remote):
                remote_buttons.addWidget(btn)
            remote_layout.addRow(remote_buttons)
            warning = QLabel(
                "Install and explicitly start the TLS CUDA service on the remote "
                "computer. Remote inference occurs ONLY when enabled here AND "
                "Inference engine = remote is saved. Voice audio leaves this "
                "device; TV video and DVB tuner never do. No automatic discovery.")
            warning.setWordWrap(True)
            remote_layout.addRow(warning)
            profile_layout.addWidget(remote_group)
            profile_layout.addStretch()
            tabs.addTab(scroll_tab(profile_page), "Ready modes · Install all")
            self.show_profile_description()
            tabs.addTab(scroll_tab(speech_page), "Speech models · GPU / NPU")
            tabs.addTab(scroll_tab(language_page), "Language packs · Translation")

            speaker_page = QWidget()
            speaker_layout = QVBoxLayout(speaker_page)
            speaker_layout.setContentsMargins(12, 16, 12, 12)
            speaker_layout.setSpacing(14)

            public_card = QGroupBox("Recommended · Token-free local voice tracking")
            public_layout = QVBoxLayout(public_card)
            overview = QLabel(
                "Resemblyzer · public Apache-2.0 model · NO Hugging Face "
                "account, token or access approval. Install once; all TV "
                "audio stays on this computer. Lightweight CPU inference "
                "runs separately from a compatible NVIDIA CUDA Whisper GPU.")
            overview.setWordWrap(True)
            public_layout.addWidget(overview)
            self.free_speaker_status = QLabel("Checking public model…")
            self.free_speaker_status.setWordWrap(True)
            public_layout.addWidget(self.free_speaker_status)
            free_buttons = QHBoxLayout()
            self.install_free_speaker_button = QPushButton(
                "Install / repair · no token required")
            self.install_free_speaker_button.setStyleSheet(
                "QPushButton{background:#147d65;color:white;font-weight:700;"
                "padding:9px;border:1px solid #319880;border-radius:7px}"
                "QPushButton:hover{background:#1a9577}"
                "QPushButton:disabled{background:#253c38;color:#999}")
            self.install_free_speaker_button.clicked.connect(
                self.install_free_speaker_model)
            self.remove_free_speaker_button = QPushButton(
                "Remove token-free model")
            self.remove_free_speaker_button.clicked.connect(
                self.remove_free_speaker_model)
            free_buttons.addWidget(self.install_free_speaker_button,2)
            free_buttons.addWidget(self.remove_free_speaker_button,1)
            public_layout.addLayout(free_buttons)
            guide = QLabel(
                "After installation: Live Captions → Detect separate voices "
                "→ Speaker model: Resemblyzer → Apply. Voice labels are "
                "estimates. Short/overlapping dialogue or background music "
                "can be mislabeled; age/gender are never inferred.")
            guide.setWordWrap(True)
            public_layout.addWidget(guide)
            speaker_layout.addWidget(public_card)

            advanced_button = QToolButton()
            advanced_button.setText(
                "Show advanced pyannote Community-1 (Hugging Face access required)")
            advanced_button.setCheckable(True)
            advanced_button.setChecked(False)
            advanced_button.setArrowType(Qt.RightArrow)
            advanced_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            speaker_layout.addWidget(advanced_button)

            advanced_box = QGroupBox("Advanced · pyannote Community-1")
            advanced_layout = QVBoxLayout(advanced_box)
            terms = QLabel(
                'Community-1 has separate access conditions and requires '
                'a Hugging Face token. See the '
                '<a href="https://huggingface.co/pyannote/'
                'speaker-diarization-community-1">model page</a>. '
                'The token is used only during installation and not saved. '
                'The token-free Resemblyzer option above works independently.')
            terms.setWordWrap(True)
            terms.setOpenExternalLinks(True)
            advanced_layout.addWidget(terms)
            self.speaker_status = QLabel("")
            self.speaker_status.setWordWrap(True)
            advanced_layout.addWidget(self.speaker_status)
            advanced_buttons = QHBoxLayout()
            install_speaker = QPushButton(
                "Install gated pyannote model")
            install_speaker.clicked.connect(self.install_speaker_model)
            advanced_buttons.addWidget(install_speaker)
            remove_speaker = QPushButton("Remove gated model")
            remove_speaker.clicked.connect(self.remove_speaker_model)
            advanced_buttons.addWidget(remove_speaker)
            advanced_layout.addLayout(advanced_buttons)
            advanced_box.setVisible(False)
            speaker_layout.addWidget(advanced_box)
            advanced_button.toggled.connect(lambda checked: (
                advanced_box.setVisible(checked),
                advanced_button.setArrowType(
                    Qt.DownArrow if checked else Qt.RightArrow)))
            speaker_layout.addStretch()
            tabs.addTab(scroll_tab(speaker_page), "Speaker separation · optional")
            # A searchable entry point across EXISTING compatible engines.
            # Arbitrary Hugging Face models are not automatically compatible:
            # each backend has its own verified weights/runtime/format.
            all_page=QWidget()
            all_layout=QVBoxLayout(all_page)
            all_layout.setContentsMargins(12,16,12,12)
            all_intro=QLabel(
                "All model components · search, inspect, install, repair or upgrade "
                "using the compatible engine tabs. Speech GGML and Argos offer "
                "online catalogs. CUDA, NLLB and speaker models use verified "
                "pinned packages; do not assume every public model is runnable.")
            all_intro.setWordWrap(True)
            all_layout.addWidget(all_intro)
            self.all_model_query=QLineEdit()
            self.all_model_query.setPlaceholderText(
                "Find Whisper, GPU, NPU, Argos, NLLB, speaker, lyric alignment…")
            all_layout.addWidget(self.all_model_query)
            self.all_model_list=QListWidget()
            self.all_model_list.setMinimumHeight(280)
            all_layout.addWidget(self.all_model_list)
            all_actions=QHBoxLayout()
            all_open=QPushButton("Open selected model category")
            all_open.clicked.connect(self.open_all_model_category)
            all_refresh=QPushButton("Refresh installed model status")
            all_refresh.clicked.connect(self.inspect_all_status)
            all_search=QPushButton("Search compatible online catalog")
            all_search.clicked.connect(self.search_selected_model_catalog)
            all_actions.addWidget(all_open)
            all_actions.addWidget(all_refresh)
            all_actions.addWidget(all_search)
            all_layout.addLayout(all_actions)
            hardware_note=QLabel(
                "Lyrics: time-coded LRC needs no ASR. Plain lyrics use matching "
                "to the actually transcribed radio/file vocals; compatible "
                "larger Whisper models can improve recognition. Approximate "
                "word matching is not WhisperX-style forced alignment. "
                "NPU runs only with a VERIFIED matching model/runtime.")
            hardware_note.setWordWrap(True)
            all_layout.addWidget(hardware_note)
            all_layout.addStretch()
            tabs.addTab(scroll_tab(all_page), "All models · search")
            self.all_model_query.textChanged.connect(self.refresh_all_models)
            self.all_model_list.itemDoubleClicked.connect(
                lambda *_:self.open_all_model_category())
            # Word-wrap long model explanations; retain explicit scrollbars
            # for code names and controls wider than the available viewport.
            for label in self.findChildren(QLabel):
                if len(label.text()) > 105 and not label.text().startswith("<"):
                    label.setWordWrap(True)
            outer.addWidget(tabs,1)
            self.model_tabs = tabs

            self.feedback = QLabel("No active downloads.")
            self.feedback.setWordWrap(True)
            self.feedback.setMinimumHeight(18)
            outer.addWidget(self.feedback)
            finish = QHBoxLayout()
            save = QPushButton("Save settings")
            save.clicked.connect(self.save)
            cancel = QPushButton("Close")
            cancel.clicked.connect(self.reject)
            finish.addWidget(save)
            finish.addWidget(cancel)
            outer.addLayout(finish)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.process_events)
            self.timer.start(120)
            # First paint: lightweight widgets and local file labels only.
            # Expensive NVIDIA, Argos, NLLB, speaker and CUDA probes are
            # *lazy*: open their tab to inspect. Only the selected bundle
            # gets an async inventory after the window is visible.
            self.populate_models()
            self.refresh_all_models()
            self.model_tabs.currentChanged.connect(self.on_model_tab_changed)
            # These are *user model-setting* changes, never page navigation.
            # Connect after widget initialization so default assignments
            # cannot incorrectly convert an existing preset to Custom.
            self.asr.toggled.connect(self.mark_manual_custom)
            self.translator.toggled.connect(self.mark_manual_custom)
            self.backend.currentIndexChanged.connect(self.mark_manual_custom)
            self.model_path.textChanged.connect(self.mark_manual_custom)
            self.translation_choice.currentIndexChanged.connect(
                self.mark_manual_custom)
            self.pi_threads.currentIndexChanged.connect(self.mark_manual_custom)
            self.hailo_fallback.toggled.connect(self.mark_manual_custom)
            self.remote_enabled.toggled.connect(self.mark_manual_custom)
            self.remote_fallback.toggled.connect(self.mark_manual_custom)
            self.remote_endpoint.textEdited.connect(self.mark_manual_custom)
            for field in (self.hailo_encoder,self.hailo_decoder,self.hailo_npy):
                field.textEdited.connect(self.mark_manual_custom)
            QTimer.singleShot(180, self.inspect_profile)

        def on_model_tab_changed(self,index):
            # Four tabs are created up front, but none needs to import a
            # model, probe CUDA, or spawn Argos until explicitly opened.
            if index in self._lazy_loaded_tabs:
                return
            self._lazy_loaded_tabs.add(index)
            if index==1:  # speech/compute models
                self.inspect_runtime()
                self.inspect_compute()
                self.inspect_starter()
            elif index==2:  # language packs
                self.inspect_nllb()
                self.inspect_argos()
            elif index==3:  # speaker models
                self.inspect_speaker()
            elif index==4:  # all models
                self.inspect_all_status()

        def preview_translator(self, *_):
            # Status text follows the pending choice immediately, but none
            # of these UI events import a model or spawn an Argos worker.
            if hasattr(self,"translation_selected_label"):
                selected=self.translation_choice.currentData()
                self.translation_selected_label.setText(
                    "Pending translator: "+str(selected).upper()+
                    " · Save settings to apply")
 
        def mark_manual_custom(self, *_):
            if self._applying_profile or not hasattr(self,"profile_choice"):
                return
            # Preserve all manual control values; change ONLY mode identity.
            current=self.profile_choice.currentData()
            if current in PROFILES:
                self._custom_base=current
            self._manual_custom=True
            self.profile_choice.blockSignals(True)
            self.profile_choice.setCurrentIndex(
                self.profile_choice.findData("custom"))
            self.profile_choice.blockSignals(False)
            self.show_profile_description()
            self.feedback.setText(
                "Custom · other model settings edited. Save settings to keep "
                "your adjustments, or choose a preset and Select mode to reset.")

        def profile_changed(self, *_):
            key=self.profile_choice.currentData()
            if key=="custom":
                # Preserve the user's current manual controls, never reset
                # them to the previous preset when navigating tabs.
                self._manual_custom=True
            elif key in PROFILES:
                self.preview_profile_controls(key)
            self.show_profile_description()
            # A pending preset choice is not applied until Select mode.
            QTimer.singleShot(80, self.inspect_profile)

        def preview_profile_controls(self,key):
            """Mirror pending mode across ALL model tabs without activation.

            Merely choosing a combo item must never download a model, start
            speech processing or persist settings. A manual edit subsequently
            converts the pending choice into Custom with that edit intact.
            """
            spec=profile(key)
            self._applying_profile=True
            try:
                if self.backend.findText(spec["backend"])<0:
                    self.backend.addItem(spec["backend"])
                self.backend.setCurrentText(spec["backend"])
                self.model_path.setText(str(self.library._path(spec["speech"])))
                index=self.translation_choice.findData(spec["translator"])
                if index>=0:
                    self.translation_choice.setCurrentIndex(index)
                self.asr.setChecked(True)
                self.translator.setChecked(True)
                self.pi_threads.setCurrentIndex(max(
                    0,self.pi_threads.findData(3)))
            finally:
                self._applying_profile=False
            self.populate_models()
            self.preview_translator()
            self.primary_speech_status.setText(
                ("PENDING · Faster-Whisper Large-v3 Turbo on NVIDIA GPU; "
                 "Whisper Small is CPU fallback, NOT the active GPU model."
                 if key in ("performance","experimental") else
                 "PENDING · "+spec["speech"].title()+
                 " CPU model. Press Select mode to activate."))
            self.feedback.setText(
                "PREVIEW ONLY · "+spec["name"]+
                ". Speech, compute and translation tabs now reflect this "
                "pending mode. Check installed, then Select mode to verify "
                "and activate; no downloads or settings changes were saved.")

        def _display_profile_key(self):
            key=self.profile_choice.currentData()
            return key if key in PROFILES else self._custom_base

        def show_profile_description(self, *_):
            chosen=self.profile_choice.currentData()
            key=self._display_profile_key()
            if key not in PROFILES:
                return
            self.profile_select.setEnabled(chosen in PROFILES and not self.running)
            self.profile_install.setEnabled(chosen in PROFILES and not self.running)
            spec=profile(key)
            issue=hardware_issue(key,self.hardware)
            if self.hardware["gpu"]["name"].startswith("Checking"):
                issue="Hardware scan deferred; Select mode verifies requirements"
            custom=(chosen=="custom")
            selected=("Custom · modified from "+spec["name"]
                      if custom else
                      ("Active · "+spec["name"] if
                       self.ai.values.get("active_profile")==key and
                       not self._manual_custom else
                       "Preview · "+spec["name"]+" (Select mode to activate)"))
            self.profile_description.setText(
                ("Manual settings · suggested model bundle below is for "
                 "comparison only. Choose a preset + Select mode to apply it.\n"
                 if custom else "")+
                spec["description"]+"\nEstimated disk: "+
                spec["disk_gb_estimate"]+
                "\nMinimum host RAM: "+str(round(spec["min_ram_mib"]/1024,1))+
                " GiB · NVIDIA VRAM: "+
                (str(round(spec["min_vram_mib"]/1024,1))+" GiB"
                 if spec["min_vram_mib"] else "not required")+
                "\nHardware: "+
                (issue or "Meets minimum estimates; inference still untested")+
                "\nSelected: "+selected+
                ("\nManual values: "+self.backend.currentText()+
                 " · "+str(self.translation_choice.currentData())+
                 " · "+self.model_path.text().strip()
                 if custom else ""))
            self.hailo_group.setVisible(key=="pi5_hat2")
            current_view=("custom:" if custom else "")+key
            if getattr(self,"_visible_profile_key",None)==current_view:
                return
            self._visible_profile_key=current_view
            self._profile_row_widgets={}
            while self.profile_rows_layout.count():
                child=self.profile_rows_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            status_cache=self._profile_status_cache.get(key,{})
            for code in spec["components"]:
                widget=QWidget()
                row=QVBoxLayout(widget)
                row.setContentsMargins(3,3,3,3)
                row.setSpacing(3)
                header=QHBoxLayout()
                name=QLabel(COMPONENTS[code][0])
                name.setWordWrap(True)
                name.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
                estimate=QLabel(component_estimate(code))
                estimate.setWordWrap(True)
                estimate.setStyleSheet("color:#a4bdd0;font-size:11px")
                estimate.setMaximumWidth(320)
                header.addWidget(name,3)
                header.addWidget(estimate,2)
                row.addLayout(header)
                state=QLabel("Not inspected yet")
                state.setStyleSheet("color:#bdd6e5;font-size:11px")
                row.addWidget(state)
                bar=QProgressBar()
                bar.setMaximumHeight(12)
                bar.setRange(0,1000)
                bar.setValue(0)
                bar.setTextVisible(False)
                bar.hide()
                row.addWidget(bar)
                self.profile_rows_layout.addWidget(widget)
                self._profile_row_widgets[code]={"state":state,"bar":bar}
                if code in status_cache:
                    self._set_component_state(
                        code,"installed" if status_cache[code] else "missing")
            self.profile_components.setText(
                ("Custom settings · recommended components shown for reference. "
                 if custom else "Installed status checked automatically, offline. ")+
                "Download sizes are estimates, not actual transfer totals.")

        def _set_component_state(self,code,status,*,message="",received=None,total=None):
            row=self._profile_row_widgets.get(code)
            if row is None:
                return
            lbl,bar=row["state"],row["bar"]
            if status in ("installed","already installed"):
                lbl.setText("✓ INSTALLED · verified local files")
                bar.hide()
            elif status=="missing":
                lbl.setText("○ NOT INSTALLED · Install all downloads when approved")
                bar.hide()
            elif status=="checking":
                lbl.setText("Checking local installation…")
                bar.hide()
            elif status in ("installing","downloading","verifying"):
                if status=="verifying":
                    lbl.setText("Verifying installed files…")
                elif status=="downloading" and isinstance(received,int):
                    count=f"{received / 1048576:.1f} MiB received"
                    lbl.setText("Downloading · "+count+
                                (f" / {total / 1048576:.1f} MiB"
                                 if isinstance(total,int) and total>0 else
                                 " · total not reported by server"))
                else:
                    lbl.setText(str(message or "Installing / preparing dependencies…")[:150])
                fraction=progress_fraction(received,total)
                if fraction is None or status!="downloading":
                    bar.setRange(0,0)  # honest indeterminate progress
                else:
                    bar.setRange(0,1000)
                    bar.setValue(fraction)
                bar.show()
            elif status=="failed":
                lbl.setText("✕ FAILED · "+str(message)[:180])
                bar.hide()

        def inspect_profile(self):
            key=self._display_profile_key()
            if key not in PROFILES:
                return
            if self._profile_inventory_busy:
                self._profile_scan_pending=True
                return
            self._profile_inventory_busy=True
            self._profile_scan_pending=False
            self.profile_components.setText(
                "Checking installed components for "+profile(key)["name"]+"…")
            for code in profile(key)["components"]:
                self._set_component_state(code,"checking")
            def scan():
                # Local only; Argos may run an installed-pairs child process.
                # None of it blocks the Qt event loop or downloads models.
                statuses={}
                failures={}
                for code in profile(key)["components"]:
                    try:
                        statuses[code]=bool(local_status(code,library=self.library))
                    except Exception as exc:
                        failures[code]=str(exc)[:140]
                self.work.put(("profile_inventory",{
                    "profile":key,"status":statuses,"errors":failures}))
            threading.Thread(target=scan,daemon=True,
                             name="tihulu-profile-inventory").start()

        def _show_profile_inventory(self,data):
            self._profile_inventory_busy=False
            key=data["profile"]
            self._profile_status_cache[key]=data.get("status",{})
            if key==self._display_profile_key():
                status=data.get("status",{})
                errors=data.get("errors",{})
                for code in profile(key)["components"]:
                    if code in errors:
                        self._set_component_state(
                            code,"failed",message="Status unavailable: "+errors[code])
                    elif code in status:
                        self._set_component_state(
                            code,"installed" if status[code] else "missing")
                installed=sum(bool(v) for v in status.values())
                self.profile_components.setText(
                    f"{installed}/{len(profile(key)['components'])} installed · "+
                    ("Some checks failed; use Check installed to retry."
                     if errors else
                     "No downloads were started. Install all only if needed."))
            if self._profile_scan_pending or key!=self._display_profile_key():
                self._profile_scan_pending=False
                QTimer.singleShot(0,self.inspect_profile)

        def install_profile(self):
            key=self.profile_choice.currentData()
            if key not in PROFILES:
                return
            spec=profile(key)
            warning=(
                "\nNLLB: CC-BY-NC-4.0 non-commercial license; MADLAD "
                "downloads ~12 GB weights, CUDA requires >=24GB VRAM."
                if key=="experimental" else "")
            caveat=(
                "\nInstalls Tiny CPU + Argos fallback; Hailo-10H Whisper "
                "Base must be installed and configured separately using "
                "official vendor HEF/NPY assets. Argos remains CPU-based."
                if key=="pi5_hat2" else "")
            if self.running:
                QMessageBox.information(self,"Install all",
                    "Another model operation is running.")
                return
            # Display each planned transfer BEFORE downloading. Existing
            # components will be reverified by the worker, not trusted from
            # stale UI cache. Counts include variable runtime dependencies.
            known=self._profile_status_cache.get(key,{})
            details="\n".join(
                ("✓ Installed · " if known.get(code) else
                 "• Check/install · ")+COMPONENTS[code][0]+
                " — "+component_estimate(code)
                for code in spec["components"])
            if QMessageBox.question(self,"Install all · "+spec["name"],
                "Review components BEFORE any download:\n\n"+
                details+"\n\nEstimated total DISK: "+
                spec["disk_gb_estimate"]+warning+caveat+
                "\n\nActual transferred bytes may differ, and shared "
                "dependencies are installed once. The installation is "
                "owner-approved and resumable; the mode is NOT selected. "
                "Continue?"
                ) != QMessageBox.Yes:
                return
            self.begin("Installing "+spec["name"]+"…",
                lambda: {"kind":"profile_install","profile":key,
                         "steps":install_components(
                             key,library=self.library,
                             progress=lambda msg:self.work.put(("progress",msg)),
                             events=lambda event:self.work.put((
                                 "model_event",{"profile":key,**event})))})

        def select_profile(self):
            key=self.profile_choice.currentData()
            if key not in PROFILES:
                return
            def verify():
                statuses={name:local_status(name,library=self.library)
                          for name in profile(key)["components"]}
                hardware=detect_hardware()
                npu_ready=False
                if key=="pi5_hat2":
                    npu_ready=hailo_readiness(
                        self.ai.values,hardware=hardware)["ready"]
                patch=selection_patch(key,library=self.library,
                                      hardware=hardware,status=statuses,
                                      hailo_ready=npu_ready)
                return {"kind":"profile_selection","profile":key,
                        "patch":patch,"npu_ready":npu_ready}
            self.begin("Verifying selected mode…",verify)

        def _hailo_input(self):
            return {
                "hailo_encoder_hef":self.hailo_encoder.text().strip(),
                "hailo_decoder_hef":self.hailo_decoder.text().strip(),
                "hailo_npy_dir":self.hailo_npy.text().strip(),
                "hailo_cpu_fallback":self.hailo_fallback.isChecked(),
                "pi_cpu_threads":self.pi_threads.currentData(),
            }

        def save_hailo_paths(self):
            from .pi_hailo import model_files_ready
            payload=self._hailo_input()
            if not model_files_ready(payload):
                QMessageBox.warning(
                    self,"Hailo model files missing",
                    "Choose existing Hailo-10H compatible encoder and decoder "
                    ".hef files, and a folder containing actual .npy assets. "
                    "Only official models that match your installed HailoRT "
                    "and Hailo Apps versions are suitable.")
                return
            try:
                self.ai.update(payload)
                self.ai.configure_environment()
                self.hailo_status.setText(
                    "HEF/NPY paths saved; firmware and inference NOT YET tested. "
                    "Use Check Hailo-10H and Test NPU, then Select mode.")
            except (OSError,ValueError) as exc:
                QMessageBox.warning(self,"Cannot save Hailo model paths",str(exc))

        def inspect_hailo(self):
            def inspect():
                hardware=detect_hardware()
                return {"kind":"hailo_status",
                        "status":hailo_readiness(self.ai.values,
                                                  hardware=hardware)}
            self.begin("Checking Hailo-10H firmware/runtime/files (offline)…",inspect)

        def test_hailo(self):
            def verify():
                hardware=detect_hardware()
                ready=hailo_readiness(self.ai.values,hardware=hardware)
                if not ready["ready"]:
                    raise RuntimeError(ready["reason"])
                # Owner-started model load and *real* inference on silence.
                # No microphone / TV / network is opened.
                from textcenter.speech import transcribe_pcm
                settings=self.ai.values
                sample={"speech":{
                    "ready_npu":True,
                    "npu_engine":"hailo_whisper",
                    "hailo_encoder_hef":settings["hailo_encoder_hef"],
                    "hailo_decoder_hef":settings["hailo_decoder_hef"],
                    "hailo_npy_dir":settings["hailo_npy_dir"]}}
                transcription=transcribe_pcm(
                    bytes(64000),"de","npu",sample)
                return {"kind":"hailo_test","text":transcription}
            self.begin("Loading Hailo-10H Whisper and checking silence inference…",
                       verify)

        def save_remote_token(self):
            try:
                save_token(self.remote_token.text())
                self.remote_token.clear()
                self.feedback.setText(
                    "Token saved privately. Remote remains OFF until explicitly selected.")
            except (OSError,ValueError) as exc:
                QMessageBox.warning(self,"Remote token",str(exc))

        def remove_remote_token(self):
            try:
                delete_token()
                self.feedback.setText("Remote GPU token removed.")
            except (OSError,ValueError) as exc:
                QMessageBox.warning(self,"Remove token",str(exc))

        def test_remote_gpu(self):
            try:
                endpoint=validate_endpoint(self.remote_endpoint.text())
                read_token()
            except (OSError,ValueError) as exc:
                QMessageBox.warning(self,"Remote GPU",str(exc))
                return
            self.begin("Testing TLS GPU endpoint (no audio uploaded)…",
                lambda: {"kind":"remote_probe",
                         "status":test_connection(endpoint)})

        def inspect_speaker(self):
            free = FreeSpeakerMarket().status()
            self.free_speaker_status.setText(
                ("INSTALLED & SELF-TESTED · select in Live Captions" if
                 free["installed"] else
                 "NOT INSTALLED · ready for owner-triggered public download") +
                "\nStorage: " + free["path"] +
                "\nDevice: " + free["backend"] +
                "\nNo token needed · Approximate voice clusters only.")
            self.install_free_speaker_button.setText(
                "Reinstall / repair public voice model" if free["installed"]
                else "Install public voice model · no token")
            self.remove_free_speaker_button.setEnabled(free["installed"])
            state = SpeakerMarket().status()
            self.speaker_status.setText(
                ("INSTALLED · offline model ready for opt-in testing" if
                 state["installed"] else "NOT INSTALLED · no speaker inference") +
                "\nLocation: " + state["path"] +
                "\nLabels are local to each 6-second clip; no demographic "
                "or permanent person identity recognition is asserted.")

        def install_free_speaker_model(self):
            if QMessageBox.question(
                self, "Install token-free speaker model",
                "Download public Apache-2.0 Resemblyzer weights packaged "
                "with the Python library, plus separate CPU PyTorch "
                "dependencies? This uses disk space and a private venv, "
                "but NO Hugging Face account, token or live audio upload. "
                "Existing NVIDIA CUDA speech and translator models "
                "remain untouched.") != QMessageBox.Yes:
                return
            self.begin("Installing public token-free Resemblyzer runtime…",
                       FreeSpeakerMarket().install)

        def remove_free_speaker_model(self):
            if QMessageBox.question(
                self, "Remove public speaker model",
                "Delete only TIHULU-owned Resemblyzer runtime and its model? "
                "GPU Whisper, Argos, NLLB and pyannote remain untouched."
                ) != QMessageBox.Yes:
                return
            self.begin("Removing token-free speaker runtime…",
                       FreeSpeakerMarket().remove)

        def install_speaker_model(self):
            if QMessageBox.question(
                self, "Opt-in speaker separation",
                "Community-1 requires accepting the Hugging Face model "
                "conditions and a read access token. Downloading separate "
                "PyTorch cu128 and pyannote dependencies may use several GB. "
                "No audio is sent to the network during live TV. Continue?"
                ) != QMessageBox.Yes:
                return
            token, ok = QInputDialog.getText(
                self, "Gated Community-1 model",
                "Enter your Hugging Face read token (used now; never saved):",
                QLineEdit.Password)
            if not ok or not token.strip():
                return
            self.begin("Installing separate offline speaker runtime…",
                       lambda owner_token=token: SpeakerMarket().install(owner_token))
            token = ""

        def remove_speaker_model(self):
            if QMessageBox.question(
                self,"Remove speaker model",
                "Remove the TIHULU-owned pyannote runtime and its cached "
                "speaker model? Whisper, NLLB and Argos remain unchanged."
                ) != QMessageBox.Yes:
                return
            self.begin("Removing optional speaker runtime…",
                       SpeakerMarket().remove)

        def refresh_all_models(self, *_):
            if not hasattr(self,"all_model_list"):
                return
            key=self.all_model_query.text().casefold().strip()
            selected=(self.all_model_list.currentItem().data(Qt.UserRole)
                      if self.all_model_list.currentItem() else None)
            self.all_model_list.clear()
            # No runtime probes for text filtering/first-paint.
            checked=self._all_status_cache or {}
            def availability(code):
                state=checked.get(code)
                return ("INSTALLED" if state is True else
                        "NOT INSTALLED" if state is False else
                        "not checked yet")
            entries=[
                ("speech","Whisper GGML · CPU / CUDA · model library, official search and selectable weights"),
                ("cuda","Faster-Whisper CUDA Large-v3 Turbo · "+
                 availability("cuda")+" · managed GPU inference"),
                ("argos","Argos Translate · installable source → target language packs"),
                ("nllb","NLLB-200 600M · "+
                 availability("nllb")+
                 " · multilingual translator (noncommercial license)"),
                ("madlad","MADLAD-400 3B · Apache-2.0 · optional large CUDA offline translator"),
                ("deepl","DeepL API · proprietary online text-only translation; user API key needed"),
                ("speaker","Resemblyzer · "+availability("speaker")+
                 " · local voice clustering, no demographic labels"),
                ("speaker-private","pyannote · "+
                 availability("speaker-private")+
                 " · separately licensed, token-gated diarization"),
                ("lyrics","Plain lyric alignment · existing Whisper ASR + conservative text matcher"),
                ("npu","Dedicated NPU · runtime/model compatibility must be verified")]
            for code,label in entries:
                if key and key not in label.casefold():
                    continue
                row=QListWidgetItem(label)
                row.setData(Qt.UserRole,code)
                self.all_model_list.addItem(row)
                if code==selected:
                    self.all_model_list.setCurrentItem(row)


        def inspect_all_status(self):
            if self._all_status_busy:
                return
            self._all_status_busy=True
            def scan():
                try:
                    results={
                        "cuda":FasterWhisperCUDA().installed(),
                        "nllb":self.translation_market.status()["installed"],
                        "speaker":FreeSpeakerMarket().status()["installed"],
                        "speaker-private":SpeakerMarket().status()["installed"],
                        "madlad":MadladMarket().status()["installed"],
                    }
                    self.work.put(("all_status",{"status":results}))
                except Exception as exc:
                    self.work.put(("all_status",{"error":str(exc)[:160]}))
            threading.Thread(target=scan,daemon=True,
                             name="tihulu-all-model-inventory").start()

        def open_all_model_category(self):
            item=self.all_model_list.currentItem()
            if item is None:
                return
            code=item.data(Qt.UserRole)
            self.model_tabs.setCurrentIndex(
                2 if code in ("argos","nllb") else
                3 if code in ("speaker","speaker-private") else 1)
            self.feedback.setText(
                "Opened the compatible model controls for "+str(code)+
                ". Online downloads occur only after explicit approval.")

        def search_selected_model_catalog(self):
            item=self.all_model_list.currentItem()
            if item is None:
                self.feedback.setText("Select a model category first.")
                return
            code=item.data(Qt.UserRole)
            if code in ("speech","lyrics"):
                self.model_tabs.setCurrentIndex(1)
                self.online_query.setText(
                    self.all_model_query.text().strip() or "large")
                self.refresh_online_models()
            elif code=="argos":
                self.model_tabs.setCurrentIndex(2)
                self.refresh_argos_catalog()
            else:
                self.open_all_model_category()
                self.feedback.setText(
                    "This backend has a pinned verified model/runtime; "
                    "use its install, repair and real self-test controls. "
                    "Arbitrary online weights cannot safely be installed.")

        def inspect_starter(self):
            if self._starter_busy:
                return
            self._starter_busy=True
            def read():
                try:
                    result={"state":StarterAI(self.ai,self.library).status()}
                except Exception as exc:
                    result={"error":str(exc)[:160]}
                self.work.put(("starter_state",result))
            threading.Thread(target=read,daemon=True,
                             name="tihulu-starter-status").start()

        def _show_starter(self,result):
            self._starter_busy=False
            if "error" in result:
                self.starter_state.setText(
                    "Starter readiness check failed: "+result["error"])
                return
            state=result["state"]
            self.starter_state.setText(
                "Whisper engine: "+("READY" if state["whisper_engine_ready"] else "missing")+
                " | Tiny: "+("READY" if state["tiny_model_ready"] else "missing")+
                " | DE/EN/TR: "+("READY" if state["translation_three_languages_ready"]
                               else "missing packs")+
                "\nInstalled directions: "+(", ".join(state["installed_pairs"]) or "none")+
                "\nASR: "+("ENABLED" if state["enabled_asr"] else "OFF")+
                " | Translation: "+("ENABLED" if state["enabled_translation"] else "OFF"))

        def setup_starter(self):
            if QMessageBox.question(self, "Install complete offline AI starter",
                "Download Whisper Tiny multilingual (~78 MB), build whisper.cpp CPU, "
                "install user-owned Argos engine and translation models for "
                "German, English and Turkish? Internet and disk are required now; "
                "the models work offline afterward and remain removable.") != QMessageBox.Yes:
                return
            def task():
                bundle = StarterAI(self.ai, self.library)
                return bundle.install(progress=lambda value: self.work.put(("progress", value)))
            self.begin("Provisioning the complete offline starter bundle…", task)

        def inspect_runtime(self):
            runtime = AIRuntime()
            status = runtime.status()
            self.engine_state.setText("Installed in " + status["path"] if status["installed"]
                                      else "Not installed. Argos package downloads need an engine.")
            whisper = WhisperRuntime()
            self.whisper_state.setText("CPU whisper-cli ready: " + str(whisper.binary) if whisper.ready()
                                       else "Not installed. Requires git, cmake, C++ compiler when built.")

        def install_cuda_runtime(self):
            capability = self.hardware["gpu"]
            if not capability["detected"]:
                QMessageBox.warning(self,"CUDA Whisper","No NVIDIA GPU was detected. "
                   "Check NVIDIA driver and nvidia-smi before installing.")
                return
            if not capability["cuda_compile_possible"]:
                QMessageBox.information(
                    self,"Optional source compiler unavailable",
                    "You pressed the whisper.cpp source-build button. "
                    "For NVIDIA GPUs without nvcc, use the prebuilt CUDA "
                    "'Install CUDA Faster-Whisper Large-v3 Turbo' button "
                    "below instead. It requires no CUDA Toolkit compiler.\n\n" +
                    capability["reason"])
                return
            if QMessageBox.question(self,"Build CUDA Whisper",
                f"Build separate GPU-accelerated whisper.cpp for {capability['name']}?\n"
                "This requires a compatible CUDA toolkit and may compile for several minutes. "
                "The original CPU motor, models and TV tuner remain unchanged.") != QMessageBox.Yes:
                return
            self.begin("Building NVIDIA CUDA Whisper engine…",WhisperRuntime().install_gpu)

        def verify_cuda_inference(self):
            if not FasterWhisperCUDA().installed():
                QMessageBox.information(
                    self, "GPU self-test",
                    "Install the managed CUDA Faster-Whisper model first.")
                return
            def check():
                verified = FasterWhisperCUDA().inference_selftest()
                if not verified["ready"]:
                    raise RuntimeError(str(verified.get("reason") or "GPU test failed"))
                return "Real CUDA model inference self-test passed · NVIDIA GPU ready."
            self.begin("Loading model and testing real CUDA kernels…", check)

        def install_fast_cuda_runtime(self):
            if not self.hardware["gpu"]["detected"]:
                QMessageBox.warning(self, "CUDA Faster-Whisper",
                    "An NVIDIA GPU driver and nvidia-smi are required.")
                return
            if QMessageBox.question(self, "Install NVIDIA Faster-Whisper",
                "Install Faster-Whisper, CUDA 12 cuBLAS/cuDNN runtime wheels "
                "and a SHA-256 checked Large-v3 Turbo model (~1.62 GB) into "
                "user-owned storage? No nvcc or system GPU driver replacement. "
                "Python packages may take additional disk space. Model download "
                "is only performed after this confirmation. Save external-SSD "
                "model storage settings first if you want them used."
                ) != QMessageBox.Yes:
                return
            self.begin("Installing local CUDA Faster-Whisper and Turbo model…",
                       FasterWhisperCUDA().install)

        def inspect_nllb(self):
            state = self.translation_market.status()
            if hasattr(self, "nllb_test"):
                self.nllb_test.setEnabled(state["installed"])
            active = ai.values.get("translation_model", "argos")
            pending = self.translation_choice.currentData()
            for index in range(self.translation_choice.count()):
                key = self.translation_choice.itemData(index)
                name = {
                    "auto_offline":"Auto · installed offline models; per-target live fallback; no cloud",
                    "de_tr_direct":"Direct DE → TR · installed NLLB first, MADLAD second, "
                                   "Argos possible EN pivot fallback · offline only",
                    "argos":"Argos Translate · compact offline language packs",
                    "nllb":"NLLB-200 600M · multilingual; ISO / NLLB codes",
                    "madlad":"MADLAD-400 3B · Apache-2.0 · GPU · large offline model",
                    "deepl":"DeepL API · PROPRIETARY online text only · explicit consent",
                }.get(key,"Unknown translator")
                self.translation_choice.setItemText(
                    index, ("✓ SELECTED · " if key == active else "") + name)
            self.translation_selected_label.setText(
                "Active translator: " + active.upper() +
                (" · Pending: " + pending.upper() + " (Save settings to switch)"
                 if pending != active else " ✓ SELECTED"))
            # This row describes NLLB itself, NOT the currently selected
            # MADLAD/DeepL/Argos engine. Previously an active MADLAD label
            # appeared next to NLLB's unrelated disk size and license.
            self.nllb_status.setText(
                "NLLB-200 distilled 600M: " +
                ("INSTALLED" if state["installed"] else "NOT INSTALLED") +
                " · optional ~2.5 GB offline weights + PyTorch" +
                " · " + NLLB_LICENSE +
                " · CPU may be slower than compact Argos packs. "
                "Installed does not prove usable; run Test NLLB offline. "
                "Live subtitles can fall back to installed Argos and keep "
                "the original captions if neural translation fails.")
            try:
                active_deepl=bool(read_key())
            except (OSError,ValueError,RuntimeError):
                active_deepl=False
            self.deepl_status.setText(
                "DeepL key: "+("present locally (not validated)" if active_deepl
                              else "NOT configured · no network request made"))
            self.madlad_state.setText(
                "MADLAD 3B: "+("INSTALLED (run GPU selftest)"
                  if MadladMarket().status()["installed"] else
                  "NOT INSTALLED")+
                " · ~12 GB weights, CUDA needed · model is not bundled.")

        def save_deepl_api_key(self):
            if QMessageBox.question(self,"Enable DeepL online translation?",
                "Only recognized TEXT phrases will be sent to the official "
                "DeepL HTTPS API if you select DeepL as your translator. "
                "Audio and RF data stay local. This is not offline/private "
                "translation. Continue?") != QMessageBox.Yes:
                return
            try:
                save_key(self.deepl_key.text())
                self.deepl_key.clear()
                self.inspect_nllb()
            except (RuntimeError,ValueError,OSError) as error:
                QMessageBox.warning(self,"DeepL key rejected",str(error))

        def delete_deepl_api_key(self):
            try:
                remove_key()
                self.inspect_nllb()
            except (RuntimeError,OSError) as error:
                QMessageBox.warning(self,"DeepL key removal",str(error))

        def install_madlad_model(self):
            if QMessageBox.question(self,"Large Apache-2.0 GPU model",
                "Download Google MADLAD-400 3B (Apache-2.0)? "
                "~12 GB real model files plus PyTorch dependencies, "
                "at least 16 GB free disk, large RAM and CUDA GPU. "
                "Actual GPU inference must pass before usable. "
                "This may not meet real-time subtitle latency. Continue?"
                ) != QMessageBox.Yes:
                return
            self.begin("Installing and verifying real MADLAD weights…",
                       MadladMarket().install)

        def test_madlad_model(self):
            def check():
                outcome=MadladMarket().selftest()
                if not outcome.get("ready"):
                    raise RuntimeError("MADLAD offline self-test failed: "+
                                       str(outcome.get("reason"))[:220])
                return "MADLAD offline GPU test PASS: "+str(outcome.get("translated"))
            self.begin("Running MADLAD real GPU translation…",check)

        def remove_madlad_model(self):
            if QMessageBox.question(self,"Remove MADLAD weights",
                "Delete only user-managed MADLAD weights? "
                "NLLB, Argos and Whisper remain untouched.") != QMessageBox.Yes:
                return
            self.begin("Removing MADLAD only…",MadladMarket().remove)

        def install_nllb_model(self):
            if QMessageBox.question(self, "Optional NLLB license and large download",
                "Download NLLB-200 distilled 600M from Meta/Hugging Face?\n"
                "License: CC-BY-NC-4.0 — NON-COMMERCIAL USE only.\n"
                "Approximately 2.5 GB of model weights, plus substantial "
                "PyTorch/Transformers dependencies. Model may be slower than Argos "
                "for live subtitles, especially on Raspberry Pi 5.\n"
                "Do you agree to install this optional model?") != QMessageBox.Yes:
                return
            self.begin("Installing larger NLLB multilingual translation model…",
                       self.translation_market.install)

        def test_nllb_model(self):
            if not self.translation_market.status()["installed"]:
                QMessageBox.information(
                    self, "Offline NLLB test",
                    "NLLB files are missing. Download / repair the model first.")
                return
            def verify():
                outcome = TranslationModelMarket().selftest()
                if not outcome.get("ready"):
                    raise RuntimeError(
                        "NLLB self-test failed: " +
                        str(outcome.get("reason") or "unknown")[:240] +
                        " · Select Argos or repair NLLB dependencies.")
                return ("NLLB real offline translation PASSED on " +
                        str(outcome.get("device")) + ": Guten Morgen → " +
                        str(outcome.get("translated")))
            self.begin("Testing actual local NLLB model weights…", verify)

        def remove_nllb_model(self):
            if QMessageBox.question(self,"Remove NLLB",
                "Remove only TIHULU-managed NLLB model files? "
                "Argos packs and Whisper models are preserved.") != QMessageBox.Yes:
                return
            self.begin("Removing NLLB weights…",self.translation_market.remove)

        def search_quality_model(self, query):
            self.online_query.setText(query)
            self.refresh_online_models()

        def select_installed_argos_pair(self):
            selected = self.installed_argos.currentItem()
            if selected is None:
                return
            pair = selected.data(Qt.UserRole)
            if not isinstance(pair, dict):
                return
            self.source.setCurrentText(pair["source"])
            self.target.setCurrentText(pair["target"])
            self.available.setText(
                "Installed pack selected: " + pair["source"] +
                " → " + pair["target"] + ". "
                "Choose Argos translator and Save settings to use it.")

        def test_live_argos_pair(self):
            from .language_codes import language_code
            try:
                src=language_code(self.source.currentText())
                dst=language_code(self.target.currentText())
            except (ValueError,TypeError) as exc:
                QMessageBox.warning(self,"Invalid translation direction",str(exc))
                return
            if src==dst:
                QMessageBox.information(self,"Translation test",
                    "Choose two different source and target languages.")
                return
            samples={
                "de":"Guten Morgen, wie geht es Ihnen?",
                "en":"Hello, how are you?",
                "tr":"Merhaba, nasılsınız?",
                "fr":"Bonjour, comment allez-vous?",
                "es":"Buenos días, ¿cómo está?",
                "pl":"Dzień dobry, jak się masz?",
                "ar":"مرحبا، كيف حالك؟",
                "ja":"こんにちは、お元気ですか？",
            }
            if src not in samples:
                QMessageBox.information(self,"Translation test",
                    "No locally validated sample for "+src.upper()+
                    ". Use a supported common language or test from live speech.")
                return
            def verify():
                from .runtime import AIRuntime
                if not AIRuntime().status()["installed"]:
                    raise RuntimeError("Managed Argos venv unavailable; install Argos first")
                from .translation_service import translate_argos
                result=translate_argos(samples[src],src,dst)
                if not isinstance(result,str) or not result.strip():
                    raise RuntimeError("Live Argos worker returned no translation")
                return ("Managed live-worker "+src.upper()+" → "+dst.upper()+
                        " PASS: "+result[:180])
            self.begin("Testing installed Argos "+src.upper()+" → "+
                       dst.upper()+" in real live worker…",verify)

        def refresh_online_models(self):
            query = self.online_query.text().strip()
            self.begin("Searching official online Whisper GGML model catalog…",
                       lambda: "Verified model entries: " +
                       ", ".join(self.library.refresh_online(query)))

        def install_whisper_runtime(self):
            if QMessageBox.question(self, "Build optional Whisper CPU engine",
                "Download the pinned whisper.cpp v1.9.5 source from GitHub and "
                "compile CPU-only on this device? Requires git/cmake/g++; it may "
                "use significant CPU, time and storage. Nothing installs globally.") != QMessageBox.Yes:
                return
            self.begin("Compiling optional Whisper CPU engine…", WhisperRuntime().install)

        def remove_whisper_runtime(self):
            if QMessageBox.question(self, "Remove managed Whisper CPU runtime",
                "Delete only the user-owned whisper.cpp build folder? "
                "GGML models and other TV settings are preserved.") != QMessageBox.Yes:
                return
            self.begin("Removing CPU Whisper engine…", WhisperRuntime().remove)

        def install_engine_runtime(self):
            if QMessageBox.question(self, "Install optional translator runtime",
                "Create a user-owned Python virtualenv and download Argos Translate "
                "from PyPI? This may use storage/network resources. Restart TV Center "
                "after installation. No changes are made to system Python.") != QMessageBox.Yes:
                return
            self.begin("Installing optional Argos engine…", AIRuntime().install_argos)

        def remove_engine_runtime(self):
            if QMessageBox.question(self, "Remove translator runtime",
                "Remove only the app-owned optional Python virtualenv? Whisper model "
                "files and saved channel lists remain intact.") != QMessageBox.Yes:
                return
            self.begin("Removing app-owned AI runtime…", AIRuntime().uninstall)

        def selected_model(self):
            selected = self.models.currentItem()
            return selected.data(Qt.UserRole) if selected else None

        def populate_models(self):
            old = self.selected_model()
            pending_path = self.model_path.text().strip()
            saved_path = ai.values.get("model_path", "")
            self.models.clear()
            from PyQt5.QtWidgets import QListWidgetItem
            for model in self.library.installed():
                key = model["id"]
                path = str(self.library._path(key))
                state = "INSTALLED" if model["installed"] else "download available"
                selected = path == saved_path and model["installed"]
                pending = path == pending_path and pending_path != saved_path
                label = ("✓ SELECTED · " if selected else
                         "◉ PENDING SAVE · " if pending else "")
                fit = model_fit(key,model["size_mb"],self.hardware)
                item = QListWidgetItem(
                    f"{label}{model['name']} · ~{model['size_mb']} MB · {state}\n   {fit}")
                item.setData(Qt.UserRole, key)
                self.models.addItem(item)
                if key == old:
                    self.models.setCurrentItem(item)
            self.active_speech_label.setText(
                "✓ Selected Whisper model: " + (saved_path or "None") +
                ("\nPending model (not yet saved): " + pending_path
                 if pending_path != saved_path else ""))
            self.storage_label.setText("Managed models: " + str(self.library.root))
            # Avoid blocking the Qt event thread on a child Python/Argos
            # import each time the installed-model selection is refreshed.

        def inspect_compute(self):
            if self._compute_busy:
                return
            self._compute_busy=True
            self.compute.setText("Scanning CUDA / CPU / NPU after first paint…")
            source_model=self.model_path.text().strip()
            def worker():
                try:
                    hardware=detect_hardware()
                    runtime=detect_devices(model_path=source_model)
                    result={"hardware":hardware,"runtime":runtime}
                except Exception as exc:
                    result={"error":str(exc)[:180]}
                self.work.put(("hardware",result))
            threading.Thread(target=worker,daemon=True,
                             name="tihulu-compute-scan").start()

        def _show_compute(self,result):
            self._compute_busy=False
            if "error" in result:
                self.compute.setText("Compute scan unavailable: "+result["error"])
                return
            self.hardware=result["hardware"]
            p=result["runtime"]
            gpu=self.hardware["gpu"]
            npu=self.hardware["npu"]
            ram=self.hardware["ram_mib"]
            self.install_cuda.setEnabled(bool(gpu["cuda_compile_possible"]))
            self.install_fast_cuda.setEnabled(bool(gpu["detected"]))
            self.verify_fast_cuda.setEnabled(FasterWhisperCUDA().installed())
            available=[key.upper() for key in ("cpu","gpu","npu")
                       if p["speech"].get("ready_"+key)]
            self.compute.setText(
                "CPU: "+self.hardware["cpu"]+
                (" · RAM "+str(round(ram/1024,1))+" GiB" if ram else "")+
                "\nGPU: "+gpu["name"]+
                (" · VRAM "+str(gpu["vram_mib"])+" MiB"
                 if gpu["vram_mib"] else "")+
                "\nNPU: "+(", ".join(npu["devices"]) if npu["detected"]
                              else "not detected")+
                "\nSpeech runtimes: "+(", ".join(available) if available
                                         else "none detected")+
                "\nHardware detection never proves model compatibility.")
            self.cuda_status.setText(
                "CUDA compiler: "+(gpu["cuda_version"] or "not installed")+
                " · GPU whisper.cpp compiled: "+
                ("YES" if WhisperRuntime().ready_gpu() else "NO")+
                "\nFaster-Whisper CUDA installed: "+
                ("YES" if FasterWhisperCUDA().installed() else "NO")+
                "\n"+gpu["reason"])
            self.show_profile_description()
            self.populate_models()

        def inspect_argos(self):
            if self._argos_busy:
                return
            self._argos_busy=True
            self.pairs.setText("Reading installed Argos packs in background…")
            def worker():
                try:
                    pairs=(run_argos_market("installed",installed_timeout=9)
                           if AIRuntime().status()["installed"] else [])
                    result={"pairs":pairs}
                except Exception as exc:
                    result={"error":str(exc)[:160]}
                self.work.put(("argos_state",result))
            threading.Thread(target=worker,daemon=True,
                             name="tihulu-argos-scan").start()

        def _show_argos(self,result):
            self._argos_busy=False
            if "error" in result:
                self.pairs.setText("Argos inventory unavailable: "+result["error"])
                return
            pairs=result["pairs"]
            self.pairs.setText("Installed Argos packs ("+str(len(pairs))+"): "+
                (", ".join(p["source"]+"→"+p["target"] for p in pairs)
                 if pairs else "none"))
            self.installed_argos.clear()
            for pair in pairs:
                item=QListWidgetItem(pair["source"].upper()+" → "+
                                     pair["target"].upper()+" · INSTALLED")
                item.setData(Qt.UserRole,pair)
                self.installed_argos.addItem(item)

        def begin(self, label, fn):
            if self.running:
                QMessageBox.information(self, "Model operation", "A model operation is already running")
                return
            self.running = True
            self.profile_install.setEnabled(False)
            self.profile_select.setEnabled(False)
            self.profile_inspect.setEnabled(False)
            self.feedback.setText(label)
            def worker():
                try:
                    result = fn()
                    self.work.put(("done", result))
                except Exception as exc:
                    self.work.put(("error", str(exc)[:250]))
            threading.Thread(target=worker, daemon=True, name="tihulu-model-manager").start()

        def process_events(self):
            for _ in range(3):
                try: kind, data = self.work.get_nowait()
                except queue.Empty: break
                if kind == "hardware":
                    self._show_compute(data)
                elif kind == "argos_state":
                    self._show_argos(data)
                elif kind == "starter_state":
                    self._show_starter(data)
                elif kind == "profile_inventory":
                    self._show_profile_inventory(data)
                elif kind == "all_status":
                    self._all_status_busy=False
                    if "status" in data:
                        self._all_status_cache=data["status"]
                        self.refresh_all_models()
                    else:
                        self.feedback.setText(
                            "Optional model inventory failed: "+data["error"])
                elif kind == "model_event":
                    if data.get("profile")==self._display_profile_key():
                        self._set_component_state(
                            data["component"],data["state"],
                            message=data.get("message",""),
                            received=data.get("received"),
                            total=data.get("total"))
                    if data["state"] in ("installed","already installed"):
                        self._profile_status_cache.setdefault(
                            data["profile"],{})[data["component"]]=True
                    elif data["state"]=="failed":
                        self._profile_status_cache.setdefault(
                            data["profile"],{})[data["component"]]=False
                elif kind == "progress":
                    self.feedback.setText(str(data))
                elif kind == "done":
                    self.running = False
                    self.profile_install.setEnabled(True)
                    self.profile_select.setEnabled(True)
                    self.profile_inspect.setEnabled(True)
                    if isinstance(data,dict) and data.get("kind") == "profile_selection":
                        try:
                            self.ai.update(data["patch"])
                            self.ai.configure_environment()
                            self._applying_profile=True
                            try:
                                backend=data["patch"]["backend"]
                                if self.backend.findText(backend)<0:
                                    self.backend.addItem(backend)
                                self.backend.setCurrentText(backend)
                                self.model_path.setText(data["patch"]["model_path"])
                                translator_id=data["patch"]["translation_model"]
                                self.translation_choice.setCurrentIndex(
                                    max(0,self.translation_choice.findData(translator_id)))
                                self.asr.setChecked(data["patch"]["asr_enabled"])
                                self.translator.setChecked(data["patch"]["translation_enabled"])
                                cpu_index=self.pi_threads.findData(
                                    data["patch"].get("pi_cpu_threads",3))
                                if cpu_index>=0:
                                    self.pi_threads.setCurrentIndex(cpu_index)
                                self._manual_custom=False
                                self._active_profile=data["profile"]
                                self._custom_base=data["profile"]
                                self.profile_choice.setCurrentIndex(
                                    self.profile_choice.findData(data["profile"]))
                            finally:
                                self._applying_profile=False
                            selected_profile=data["profile"]
                            primary=(
                                "Faster-Whisper Large-v3 Turbo GPU (if runtime ready) "
                                "+ CPU Whisper Small fallback"
                                if selected_profile in ("performance","experimental")
                                else "Hailo-10H GPU/NPU with Tiny CPU fallback"
                                if data.get("npu_ready") else
                                "CPU Whisper "+profile(selected_profile)["speech"].title())
                            self.primary_speech_status.setText(
                                "SAVED · "+primary+" · RUNNING worker may still "
                                "use previous model until AI Caption Refresh.")
                            self.feedback.setText(
                                "SAVED: "+profile(selected_profile)["name"]+
                                " · "+primary+
                                ". Use AI Caption Refresh in TV/Radio to apply "
                                "to a running worker; real active model is shown "
                                "in live diagnostics.")
                            self.populate_models()
                            self.preview_translator()
                            self.refresh_all_models()
                            self.show_profile_description()
                            if after_save: after_save()
                        except (OSError,RuntimeError,ValueError) as exc:
                            self.feedback.setText("Profile activation FAILED: "+str(exc))
                    elif isinstance(data,dict) and data.get("kind")=="profile_install":
                        self.feedback.setText(
                            "Install all completed but NOT activated. "
                            "Click Select mode. Components: "+
                            ", ".join(name for name,_ in data["steps"]))
                        self.inspect_profile()
                    elif isinstance(data,dict) and data.get("kind")=="hailo_status":
                        self.hailo_status.setText(
                            ("Hailo-10H CONFIGURED · " if data["status"]["ready"]
                             else "NPU NOT READY · ")+data["status"]["reason"])
                        self.feedback.setText(self.hailo_status.text())
                    elif isinstance(data,dict) and data.get("kind")=="hailo_test":
                        self.hailo_status.setText(
                            "Hailo-10H Whisper model loaded and processed silence "
                            "without an exception. Real spoken-language speed, "
                            "accuracy, and live subtitle timing remain untested.")
                        self.feedback.setText(self.hailo_status.text())
                    elif isinstance(data,dict) and data.get("kind")=="remote_probe":
                        self.feedback.setText(
                            "Remote TLS connection passed · CUDA installed marker: "+
                            str(data["status"]["cuda_installed"])+
                            " · no audio uploaded, actual inference untested.")
                    elif isinstance(data,dict) and data.get("kind") == "argos_catalog":
                        self.argos_catalog_list.clear()
                        for pair in data["items"]:
                            item = QListWidgetItem(
                                pair["source"].upper()+" → "+pair["target"].upper()+
                                " · "+str(pair.get("name") or "Argos pack"))
                            item.setData(Qt.UserRole,pair)
                            self.argos_catalog_list.addItem(item)
                        self.available.setText(
                            f"{len(data['items'])} official translation pairs available. "
                            "Select one, install it, then save your engine.")
                        self.feedback.setText("Argos language catalog refreshed.")
                    else:
                        self.feedback.setText("Completed: " + str(data))
                    self.populate_models()
                    # Don't fan out many Argos/GPU/translator probes after
                    # every completed model operation. Refresh only the
                    # currently visible tab, and background expensive status.
                    self._all_status_cache=None
                    current=self.model_tabs.currentIndex()
                    if current==0:
                        self.inspect_profile()
                    elif current==4:
                        self.inspect_all_status()
                    elif current==1:
                        self.inspect_starter()
                    elif current==2:
                        self.inspect_argos()
                else:
                    self.running = False
                    self.profile_install.setEnabled(True)
                    self.profile_select.setEnabled(True)
                    self.profile_inspect.setEnabled(True)
                    self.feedback.setText("Failed: " + str(data))

        def download_model(self):
            key = self.selected_model()
            if key not in self.library.catalog: return
            desc = self.library.catalog[key]
            if QMessageBox.question(self, "Download model",
                  f"Download {desc['name']} (~{desc['size_mb']} MB) to {self.library.root}?\n"
                  "Model file is verified using SHA-256. No background download.") != QMessageBox.Yes:
                return
            def work():
                path = self.library.download(key, progress=lambda n, limit: self.work.put(
                    ("progress", f"Downloading {key}: {n/(1024*1024):.0f} MiB received")))
                return "Installed model " + str(path)
            self.begin("Downloading verified model…", work)

        def use_model(self):
            key = self.selected_model()
            if key in self.library.catalog and self.library._path(key).is_file():
                self.model_path.setText(str(self.library._path(key)))
                self.feedback.setText("Model selected. Click Save settings to activate.")
            else:
                self.feedback.setText("Install selected model first.")

        def remove_model(self):
            key = self.selected_model()
            if key not in self.library.catalog: return
            path = self.library._path(key)
            if not path.is_file(): return
            if QMessageBox.question(self, "Delete managed model",
                "Permanently delete " + str(path) + "?") != QMessageBox.Yes:
                return
            if self.model_path.text() == str(path):
                self.model_path.clear()
            self.library.remove(key)
            self.populate_models()
            self.feedback.setText("Managed model deleted; Save settings to update selection.")

        def import_existing(self):
            path, _ = QFileDialog.getOpenFileName(self, "Use locally installed Whisper GGML model",
                                                  str(Path.home()), "GGML model (*.bin);;All files (*)")
            if path:
                self.model_path.setText(path)
                self.feedback.setText("External model selected (not owned or deleted by this app).")

        def choose_storage(self):
            folder = QFileDialog.getExistingDirectory(self, "Choose app-managed model directory or SSD",
                                                       str(self.library.root))
            if folder:
                self.library = ModelLibrary(folder)
                self.populate_models()
                self.feedback.setText("Storage folder selected; current models remain in their original location.")

        def refresh_argos_catalog(self):
            def load_catalog():
                return {"kind":"argos_catalog",
                        "items":run_argos_market("catalog")}
            self.begin("Browsing official Argos language pair catalog…",
                       load_catalog)

        def select_argos_catalog_pair(self):
            selected = self.argos_catalog_list.currentItem()
            if selected is None:
                return
            pair = selected.data(Qt.UserRole)
            if not isinstance(pair,dict):
                return
            self.source.setCurrentText(pair["source"])
            self.target.setCurrentText(pair["target"])
            self.available.setText(
                "Selected official package: " + str(pair.get("name") or
                pair["source"]+" → "+pair["target"]) + " · install below.")

        def install_argos(self):
            a, b = self.source.currentText(), self.target.currentText()
            if a == b: return
            if QMessageBox.question(self, "Download language pack",
                  f"Download and install Argos {a} → {b} from its configured package index?") != QMessageBox.Yes:
                return
            self.begin("Installing Argos " + a + " → " + b,
                       lambda: run_argos_market("install", a, b))

        def uninstall_argos(self):
            a, b = self.source.currentText(), self.target.currentText()
            if a == b: return
            if QMessageBox.question(self, "Uninstall language pack",
                  f"Uninstall local Argos {a} → {b}?") != QMessageBox.Yes:
                return
            self.begin("Removing Argos language pack",
                       lambda: run_argos_market("remove", a, b))

        def done(self, result):
            self.geometry_store.setValue("geometry", self.saveGeometry())
            super().done(result)

        def save(self):
            if self.running:
                QMessageBox.warning(self, "Model operation running", "Finish the active install/removal first.")
                return
            chosen=self.translation_choice.currentData()
            if chosen=="deepl":
                try:
                    if not read_key():
                        QMessageBox.warning(self,"DeepL API key required",
                            "Save your own key before selecting the proprietary online translator.")
                        return
                except (OSError,RuntimeError) as error:
                    QMessageBox.warning(self,"DeepL key unsafe",str(error))
                    return
                if QMessageBox.question(self,"External text transfer",
                    "Selected DeepL is ONLINE; decoded subtitle text will be sent "
                    "over HTTPS to DeepL. No audio or video is uploaded. "
                    "Do you consent to online text translation?") != QMessageBox.Yes:
                    return
            if chosen=="madlad" and not MadladMarket().status()["installed"]:
                QMessageBox.warning(self,"MADLAD unavailable",
                    "Install and real-GPU-test MADLAD before selecting.")
                return
            try:
                remote_enabled=self.remote_enabled.isChecked()
                remote_url=(validate_endpoint(self.remote_endpoint.text())
                            if remote_enabled else self.remote_endpoint.text().strip())
                if remote_enabled:
                    read_token()
                # A manual model/backend change is a Custom mode rather
                # than silently claiming the old verified preset is active.
                old_profile=ai.values.get("active_profile","")
                spec=PROFILES.get(old_profile)
                allowed=(
                    ("cpu","npu") if old_profile=="pi5_hat2"
                    else (spec["backend"],) if spec else ())
                still_profile=bool(
                    not self._manual_custom and spec
                    and self.asr.isChecked()
                    and self.translator.isChecked()
                    and self.backend.currentText() in allowed
                    and self.translation_choice.currentData()==spec["translator"]
                    and self.model_path.text().strip()==str(
                        self.library._path(spec["speech"])))
                ai.update({
                    "active_profile":old_profile if still_profile else "",
                    "remote_gpu_enabled": remote_enabled,
                    **self._hailo_input(),
                    "remote_gpu_url": remote_url,
                    "remote_gpu_fallback": self.remote_fallback.isChecked(),
                    "asr_enabled": self.asr.isChecked(),
                    "translation_enabled": self.translator.isChecked(),
                    "backend": self.backend.currentText(),
                    "translation_model": self.translation_choice.currentData(),
                    "model_path": self.model_path.text().strip(),
                    "model_dir": str(self.library.root)
                })
                ai.configure_environment()
                self.populate_models()
                # Saving must not run large NLLB/Argos/PyTorch inventory on
                # the UI thread; the language tab refreshes when opened.
                if after_save: after_save()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Settings failed", str(exc))
                return
            self.accept()

    return Manager().exec_()
