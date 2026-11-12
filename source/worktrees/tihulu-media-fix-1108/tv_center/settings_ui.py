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
        QSizePolicy, QToolButton)

    from .model_market import (CATALOG, ModelLibrary, ModelError,
        argos_available_pairs, argos_installed_pairs, argos_install, argos_remove)
    from textcenter.compute import detect_devices, choose_backend
    from .runtime import AIRuntime, RuntimeErrorAI
    from .whisper_engine import WhisperRuntime, WhisperRuntimeError
    from .cuda_faster_whisper import FasterWhisperCUDA
    from .speaker_market import SpeakerMarket
    from .free_speakers import FreeSpeakerMarket
    from .ai_provision import StarterAI
    from .hardware_market import detect_hardware, model_fit
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
            self.hardware = detect_hardware()
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
                "language pairs. RTX GPU Turbo is installed separately.")
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
            self.backend.addItems(["auto", "gpu", "cpu"])
            if self.hardware["npu"]["detected"]:
                self.backend.addItem("npu")
            self.backend.setCurrentText(
                ai.values["backend"] if self.backend.findText(
                    ai.values["backend"]) >= 0 else "auto")
            self.backend.setToolTip(
                "RTX 5080 uses GPU CUDA, NOT NPU. NPU is shown only when "
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
                "Install / repair RTX CUDA · Faster-Whisper Turbo (no nvcc)")
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
                "Test RTX CUDA · real local model inference")
            self.verify_fast_cuda.clicked.connect(self.verify_cuda_inference)
            form.addRow(self.verify_fast_cuda)
            self.cuda_status = QLabel("")
            self.cuda_status.setWordWrap(True)
            form.addRow("GPU acceleration",self.cuda_status)
            self.model_path = QLineEdit(ai.values["model_path"])
            self.model_path.setPlaceholderText("No active Whisper model selected")
            form.addRow("Active model (CPU GGML or runtime-specific)", self.model_path)
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
                "RTX 5080 recommendation: prebuilt CUDA Large-v3 Turbo "
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
            for b in (update, install, remove): controls.addWidget(b)
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
            self.translation_choice.currentIndexChanged.connect(
                lambda *_: self.inspect_nllb())
            quality_layout.addWidget(self.translation_choice)
            self.translation_selected_label = QLabel("")
            self.translation_selected_label.setWordWrap(True)
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
                self.translation_choice.setCurrentIndex(0),
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
            self.inspect_nllb()

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
                "runs separately from the RTX 5080 Whisper GPU.")
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
            all_refresh.clicked.connect(self.refresh_all_models)
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
            self.timer.start(250)
            self.populate_models()
            self.inspect_compute()
            self.refresh_all_models()
            self.inspect_argos()
            self.inspect_runtime()
            self.inspect_starter()
            self.inspect_speaker()

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
                "Existing RTX 5080 GPU speech and translator models "
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
            try:
                cuda_ready=FasterWhisperCUDA().installed()
                nllb_ready=self.translation_market.status()["installed"]
                free_voice=FreeSpeakerMarket().status()["installed"]
                private_voice=SpeakerMarket().status()["installed"]
            except (OSError,RuntimeError,ValueError):
                cuda_ready=nllb_ready=free_voice=private_voice=False
            entries=[
                ("speech","Whisper GGML · CPU / CUDA · model library, official search and selectable weights"),
                ("cuda","Faster-Whisper CUDA Large-v3 Turbo · "+
                 ("INSTALLED" if cuda_ready else "NOT INSTALLED")+" · managed GPU inference"),
                ("argos","Argos Translate · installable source → target language packs"),
                ("nllb","NLLB-200 600M · "+
                 ("INSTALLED" if nllb_ready else "NOT INSTALLED")+
                 " · multilingual translator (noncommercial license)"),
                ("madlad","MADLAD-400 3B · Apache-2.0 · optional large CUDA offline translator"),
                ("deepl","DeepL API · proprietary online text-only translation; user API key needed"),
                ("speaker","Resemblyzer · "+("INSTALLED" if free_voice else "NOT INSTALLED")+
                 " · local voice clustering, no demographic labels"),
                ("speaker-private","pyannote · "+
                 ("INSTALLED" if private_voice else "NOT INSTALLED")+
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

        def open_all_model_category(self):
            item=self.all_model_list.currentItem()
            if item is None:
                return
            code=item.data(Qt.UserRole)
            self.model_tabs.setCurrentIndex(
                1 if code in ("argos","nllb") else
                2 if code in ("speaker","speaker-private") else 0)
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
                self.model_tabs.setCurrentIndex(0)
                self.online_query.setText(
                    self.all_model_query.text().strip() or "large")
                self.refresh_online_models()
            elif code=="argos":
                self.model_tabs.setCurrentIndex(1)
                self.refresh_argos_catalog()
            else:
                self.open_all_model_category()
                self.feedback.setText(
                    "This backend has a pinned verified model/runtime; "
                    "use its install, repair and real self-test controls. "
                    "Arbitrary online weights cannot safely be installed.")

        def inspect_starter(self):
            try:
                state = StarterAI(self.ai, self.library).status()
                self.starter_state.setText(
                    "Whisper engine: " + ("READY" if state["whisper_engine_ready"] else "missing") +
                    "  |  multilingual Tiny: " + ("READY" if state["tiny_model_ready"] else "missing") +
                    "  |  DE/EN/TR translation: " + (
                        "READY" if state["translation_three_languages_ready"] else "missing packs") +
                    "\nInstalled directions: " + (
                        ", ".join(state["installed_pairs"]) or "none") +
                    "\nASR: " + ("ENABLED" if state["enabled_asr"] else "OFF") +
                    "  /  Translation: " + ("ENABLED" if state["enabled_translation"] else "OFF"))
            except (ImportError, OSError, RuntimeError) as exc:
                self.starter_state.setText("Starter status unavailable: " + str(exc)[:160])

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
                    "For your RTX 5080 without nvcc, use the green-path "
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
                return "Real CUDA model inference self-test passed · RTX GPU ready."
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
            self.nllb_status.setText(
                ("INSTALLED" if state["installed"] else "NOT INSTALLED") +
                " · currently selected: " +
                str(self.translation_choice.currentData()).upper() +
                " · optional ~2.5 GB model + Python/PyTorch dependencies" +
                " · " + NLLB_LICENSE +
                " · CPU can be slow; requires ~6 GB+ RAM for practical use. "
                "Installed does NOT prove usable: click Test NLLB offline. "
                "If the model fails to load, live captions now try installed "
                "Argos packs automatically and keep original text visible.")
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
            if hasattr(self, "starter_state"):
                self.inspect_starter()

        def inspect_compute(self):
            try:
                self.hardware = detect_hardware()
                p = detect_devices(model_path=self.model_path.text().strip())
                gpu = self.hardware["gpu"]
                npu = self.hardware["npu"]
                ram = self.hardware["ram_mib"]
                self.install_cuda.setEnabled(bool(gpu["cuda_compile_possible"]))
                self.install_cuda.setToolTip(
                    "Optional source build requires nvcc (CUDA Toolkit >=12.8). "
                    "Use the highlighted Faster-Whisper button below without nvcc.")
                self.install_fast_cuda.setEnabled(bool(gpu["detected"]))
                self.verify_fast_cuda.setEnabled(FasterWhisperCUDA().installed())
                available = [key.upper() for key in ("cpu","gpu","npu")
                             if p["speech"].get("ready_"+key)]
                self.compute.setText(
                    "CPU: " + self.hardware["cpu"] +
                    (" · RAM ~"+str(round(ram/1024,1))+" GiB" if ram else "") +
                    "\nGPU: " + gpu["name"] +
                    (" · VRAM "+str(gpu["vram_mib"])+" MiB" if gpu["vram_mib"] else "") +
                    "\nNPU: " + (", ".join(npu["devices"]) if npu["detected"]
                                  else "not detected") +
                    "\nSpeech runtime READY: " + (", ".join(available) if available else "none") +
                    "\nDetected hardware is NOT proof of usable CUDA/NPU model.")
                self.cuda_status.setText(
                    "CUDA compiler: " + (gpu["cuda_version"] or "not installed") +
                    " · GPU whisper.cpp built: " +
                    ("YES" if WhisperRuntime().ready_gpu() else "NO") +
                    "\nManaged Faster-Whisper CUDA (no nvcc): " +
                    ("READY FOR GPU · use Auto/GPU" if (
                        FasterWhisperCUDA().installed() and p["speech"].get(
                            "gpu_engine") == "faster_whisper_managed") else
                     "INSTALLED BUT CUDA TEST NEEDED" if FasterWhisperCUDA().installed()
                     else "NOT INSTALLED · use installer above") +
                    "\nNPU: " + (
                        "Separate hardware detected · requires compatible model"
                        if npu["detected"] else
                        "No dedicated NPU found. RTX Tensor Cores are GPU, "
                        "not an OpenVINO/Hailo NPU.") +
                    "\nCompiler note (whisper.cpp ONLY): " + gpu["reason"])
            except (ImportError, OSError, ValueError) as exc:
                self.compute.setText("Hardware inference discovery failed: " + str(exc)[:140])

        def inspect_argos(self):
            try:
                if AIRuntime().status()["installed"]:
                    pairs = run_argos_market("installed")
                else:
                    pairs = []
                self.pairs.setText("Installed Argos packs (" + str(len(pairs)) +
                    "): " + (", ".join(
                    p["source"] + "→" + p["target"] for p in pairs) if pairs else
                    "none — install starter bundle or select a catalog pair"))
                self.installed_argos.clear()
                for pair in pairs:
                    item = QListWidgetItem(
                        pair["source"].upper()+" → "+pair["target"].upper()+
                        " · INSTALLED")
                    item.setData(Qt.UserRole,pair)
                    self.installed_argos.addItem(item)
            except (ImportError, OSError, ValueError) as exc:
                self.pairs.setText("Argos runtime unavailable: " + str(exc)[:100])

        def begin(self, label, fn):
            if self.running:
                QMessageBox.information(self, "Model operation", "A model operation is already running")
                return
            self.running = True
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
                if kind == "progress":
                    self.feedback.setText(str(data))
                elif kind == "done":
                    self.running = False
                    if isinstance(data,dict) and data.get("kind") == "argos_catalog":
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
                    self.inspect_argos()
                    self.inspect_runtime()
                    self.inspect_starter()
                    self.inspect_nllb()
                    self.inspect_speaker()
                    self.inspect_compute()
                    if after_save:
                        after_save()
                else:
                    self.running = False
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
                ai.update({
                    "asr_enabled": self.asr.isChecked(),
                    "translation_enabled": self.translator.isChecked(),
                    "backend": self.backend.currentText(),
                    "translation_model": self.translation_choice.currentData(),
                    "model_path": self.model_path.text().strip(),
                    "model_dir": str(self.library.root)
                })
                ai.configure_environment()
                self.populate_models()
                self.inspect_nllb()
                if after_save: after_save()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Settings failed", str(exc))
                return
            self.accept()

    return Manager().exec_()
