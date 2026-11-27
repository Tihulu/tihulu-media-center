# MEDIA-AI-RUNTIME-PARITY-05 — independent AI compatibility audit

**Release: HOLD.** Source baseline: Safety Draft PR #5 exact SHA
e772a7bde546de178339dfce4592b9a9ee743218.
Frozen snapshot 7821769eb7aed576dd426ec18ffce3696d93a00d
is read-only. This work is stacked on #5 without changing protected PRs,
owner installation, devices or private data.

## Evidence levels

A source module or profile is **definition**. A filesystem marker or an
installed package is **discovery**. Successful model loading and nontrivial
outputs from its real runtime is **inference**. Matching clean-installed
TV/Radio behavior on approved hardware is **behavioral parity**. These are
not equivalent. All tests added by this PR are synthetic/metadata-level.
None claims real inference.

## Independently inspected profile definitions

| Profile | Source-planned ASR / translation | Conditions |
| --- | --- | --- |
| pi5 | whisper.cpp Tiny CPU + Argos, 3 threads | Pi 5, 6 GB min RAM |
| pi5_hat2 | Tiny CPU fallback, optional Hailo-10H | HEF/NPY/HailoRT required; NPU inference unverified |
| normal | whisper.cpp Small CPU, Argos, voice and sound labels | 7.5 GB min RAM |
| performance | Faster-Whisper CUDA Turbo, Small CPU fallback, Argos, Qwen aligner | >=16 GB RAM / >=12 GB VRAM |
| experimental | CUDA Turbo, MADLAD 3B and NLLB alternatives, CPU fallback | >=32 GB RAM / >=24 GB VRAM |

Sources: source/installed-package/tv_center/ai_profiles.py and
settings_ui.py. GUI stages profile preview separately from Install all and
Select mode. The selection_patch routine requires hardware suitability,
discovered components and a local CPU fallback file; select_profile checks
before saving with AISettings.update. Preview is not activation. User-manual
changes can become Custom mode. Public source does not reveal owner's actual
selected profile.

## TV, Radio, speech/music routing

AISettings defaults both ASR and translation OFF. Its JSON is stored below
Path.home()/.config/tihulu-tv-center. PR #5 puts native and Python launchers
inside a separate preview HOME/XDG profile. No legacy setting is imported.

TV/Radio share media_ai._choose_model and textcenter.compute.choose_backend.
Auto picks a compatible ready NPU, GPU, then CPU; mere NVIDIA detection is
insufficient. Forced GPU may report unavailable rather than silently use CPU.

cuda_faster_whisper.py uses isolated Python/CTranslate2 and a persistent
worker. Its installed check is only a marker/file check, its probe checks CUDA
visibility, and selftest is the real inference gate. No driver, CUDA toolkit,
GPU model or actual TV/RF/audio runtime was exercised here.

qwen_forced_aligner.py is optional and separately installed. Turkish is not
supported for the Qwen aligner, so radio_karaoke_router conservatively falls
back to Whisper. MusicSpeechRouter requires real matched vocals for song
claims; generic music classification does not prove lyrics. Radio's ffmpeg
loopback/welle input and caption/translation calls were inspected in source,
not played on a tuner. TV/Radio parity remains HOLD.

## Translation dependency audit

- Argos: optional managed AI Python venv, directed language packages and a
  dedicated persistent worker. Python package alone cannot prove language-pair
  availability or translated output.
- NLLB-200 600M: separate Transformers/PyTorch worker, offline environment,
  pinned model revision, required real selftest; license CC-BY-NC-4.0,
  **non-commercial only**.
- MADLAD-400 3B: separate worker and offline model; real CUDA and substantial
  VRAM are required. Checkpoint marker alone cannot prove inference.
- Persistent workers prepend the installed Python package root to PYTHONPATH,
  inherit preview HOME, and set HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE. Missing
  optional runtimes should produce actionable failures; NLLB live failure
  has time-bounded Argos fallback, not guaranteed language support.
- No optional runtime, weight or language pack was downloaded, imported for
  inference, or installed as part of this agent task.

## Safe, explicitly opt-in local compatibility

Standalone tool: installer/media-ai-compat.py. The installer and applications
NEVER call it automatically. It NEVER searches or reads existing owner AI JSON,
recordings, tokens, radio QSettings or private models. The owner must supply
paths manually in a separately authorized local session.

Read-only plan:

    python3 installer/media-ai-compat.py --model-path /path/to/ggml-small.bin --model-dir /path/to/existing/ssd-models

Explicit creation of NEW isolated preview settings only:

    python3 installer/media-ai-compat.py --model-path /path/to/ggml-small.bin --model-dir /path/to/existing/ssd-models --backend auto --translator argos --apply --confirm-preview-only

Safety: absolute explicit paths, path component traversal/symlink refusal,
existing regular model file >1 KiB, existing model directory, metadata only.
Preview install/owner marker and non-root ownership are checked. Only a NEW
preview-home/.config/tihulu-tv-center/ai-settings.json is atomically created
with mode 0600. It will NEVER overwrite a previous preview JSON. No source
or target file contents are copied, hashed or moved; no models are loaded.
External SSD paths are references, not imports. ASR, translation, active
profile and remote GPU stay OFF/empty. The user must later perform Model Market
checks, real inference tests and independent explicit activation.

This tool does NOT migrate managed CUDA/Qwen/NLLB/MADLAD runtime markers, venvs,
DeepL tokens, remote endpoints, licenses, local Argos packs, recorded audio or
custom lyrics offsets. It does not silently make a private model available to
a different engine format. Symlinks and unknown preexisting files fail closed.

## What cannot be reproduced from public source

From source we can recreate: profile definitions, optional runtime routes,
default settings, backend and translator preference choices, language lists,
caption/Radio engine wiring and safe preview launcher boundaries.

Requires separate explicit owner-local authorization: existing installed
binary/profile/QSettings, SSD model layouts and model content hashes, current
runtime dependency versions, NVIDIA driver and actual CUDA kernels, Argos
installed language pairs, API credentials, recordings and measured live
translation/lyric/subtitle timing. Owner hardware is out of scope in this PR.

## Acceptance and remaining blockers

1. New isolated CI: original unmodified source/security tests, synthetic AI
   path and fallback tests, disposable native install Python import and
   subprocess missing-dependency smoke, without model downloads.
2. Separately authorized true CPU Whisper, CUDA Faster-Whisper, Argos,
   NLLB/MADLAD and Qwen real inference on approved hardware, not fixtures.
3. Direct TV/Radio/lyrics/music routing, multilingual caption and playback
   behavioral comparison with preserved installed Media Center.
4. Independent exact-head review and explicit owner approval before any
   merge, installer publication, deployment or release.

**HOLD** remains mandatory until steps 2–4 are proven, not inferred from CI.
