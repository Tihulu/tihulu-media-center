# MEDIA-REAL-AI-RUNTIME-ACCEPTANCE-14 — independent PASS/HOLD plan

**Release HOLD.** Planning and disposable synthetic QA only; no owner GPU, tuner, model or private configuration access.

Pinned baseline: Draft PR #11 exact SHA `2f5699eeb47505468bf3327be4dbdd89fed3dff1`. Frozen source `7821769eb7aed576dd426ec18ffce3696d93a00d` untouched. PR #11 [CI](https://github.com/Tihulu/tihulu-media-center/actions/runs/43196547501) has 2/2 successful jobs and 151/151 reported synthetic/native installed test executions. This does NOT prove real AI inference. Security HOLD remains for unresolved adversarial same-UID filesystem races.

## Source architecture and inference evidence tiers

Source files: source/installed-package/tv_center/{ai_profiles,ai_settings,whisper_engine,cuda_faster_whisper,qwen_forced_aligner,translation_market,translation_madlad,runtime,translation_service,radio_karaoke_router,media_ai}.py and source/installed-package/textcenter/compute.py.

Evidence tiers: **source present → installed/discovered → runtime import → model loaded → actual inference on nontrivial test input → TV/Radio behavioral parity**. Never treat a marker, import, nvidia-smi output, mock or silence-only kernel selftest as multilingual quality PASS.

| Engine | Preserved path | Actual acceptance |
| --- | --- | --- |
| Whisper CPU | whisper.cpp pinned 1.9.5 user-owned CLI, GGML Tiny/Small | Real 16-kHz mono EN/DE/TR WAV decoding; reference WER; CPU-only fallback under GPU failure |
| whisper.cpp CUDA | Separate CUDA build requiring nvcc, arch 120 on RTX 50 | Separate actual kernel/audio inference; cannot infer success from build marker |
| Faster-Whisper CUDA | Isolated Python/CTranslate2 worker and pinned Large-v3 Turbo CT2 checkpoint | Installed-file check, CUDA device probe, real silence kernel selftest **and** genuine EN/DE/TR speech, word timing and recovery |
| Argos | Managed Python venv + individually installed directed language packs + persistent worker | Six EN/DE/TR translation directions, including pivot DE↔TR; real target-language content |
| NLLB 600M | Transformers >=4.44,<5 and PyTorch managed venv, persistent worker | Genuine checkpoint and tensor materialization, selftest and six directions, latency/memory |
| MADLAD 3B | Managed Transformers/PyTorch, real CUDA required | Genuine local checkpoint loads on GPU; valid translations, measured VRAM; may stay disabled |
| Qwen3 ForcedAligner | Independent optional worker | English/German 32-kHz audio/text word anchors; **Turkish unsupported**, Whisper fallback |
| TV/Radio | Shared backend choice; Auto NPU→GPU→CPU only when ready | Real subtitle quality and source switching; no playback interruption or fabricated lyrics |

RTX 5080 is NVIDIA Blackwell compute capability **12.0** (https://developer.nvidia.com/cuda/gpus). Faster-Whisper upstream requires **CUDA 12 cuBLAS and cuDNN 9** (https://github.com/SYSTRAN/faster-whisper); source pins CTranslate2 >=4.6.3,<5, nvidia-cublas-cu12 >=12.8,<13 and nvidia-cudnn-cu12 >=9,<10. **These requirements do not mean the driver/CUDA runtimes are installed or compatible.** Faster-Whisper CT2 does NOT require nvcc; optional whisper.cpp CUDA compilation does. Benchmark runtime and kernels, not just device detection.

Profile Performance minimum 12,000 MiB VRAM / 16,000 MiB RAM; Experimental minimum 24,000 MiB VRAM / 32,000 MiB RAM. An approx. 16,303 MiB RTX 5080 does NOT satisfy Experimental. Even the Performance profile must measure **free** VRAM under actual model load and avoid concurrent CUDA models until separately proven.

## Six-direction EN/DE/TR benchmark

Create licensed/consented, **nonprivate** fixture WAVs and references: at least 3 speakers/language, >=10 min clean speech and >=10 min broadcast/noisy speech per language, silence-only and music-only excerpts, presenter-over-music, overlap, channel-change and short DAB/TV snippets. Keep an exact local SHA-256 manifest of authorized fixture audio; never upload owner recordings or model hashes without separate consent.

Transcription: calculate Unicode-aware WER by **language and condition**; proposed clean threshold <=20%, broadcast/noisy <=35%, no speech hallucination on silence. For auto-language detection, require >=95% correct nontrivial clips. CPU whisper.cpp -l auto does not automatically deliver a verified recognized language code through this application, so test explicit -l en/de/tr as well. Count genuine word timestamps separately from CPU chunk timestamps. Run repeated cold/warm, model-reload, source-switch, worker-timeout and 60-min soak tests; report p50/p95 latency, RAM/VRAM, dropped chunks and fallback success.

Translation: run **en→de, de→en, en→tr, tr→en, de→tr, tr→de** for Argos, NLLB and MADLAD only when corresponding engines are genuinely available. For each supported engine/direction, >=100 utterances evaluated by independent bilingual reviewers. Proposed gates: >=90% meaning adequate, >=95% named entities preserved, zero critical omission or fabricated facts. For missing Argos packs, model unavailable, NLLB meta tensors or MADLAD OOM, return actionable error; original subtitle survives, no guessed language or fictitious successful translation. DE↔TR may require English pivot packages in Argos.

## TV and Radio live behavioral parity (not yet exercised)

Measure audio presentation and text display against the SAME monotonic clock; include configured audio buffer and user subtitle offset. Source modes: Off, Teletext-only, Whisper-only, Teletext→Whisper fallback, manual Teletext page. Test matching/mismatching Teletext, tuner-like audio interruptions, channel changes, speaker overlap, multilingual subtitles, Comfort Reading, stable half-sentences, non-flickering cues, and deliberate 0-s / 10-s buffer conditions.

Proposed timing gates: p95 cue arrival <= configured audio buffer + 3 s; p95 synchronization drift <=1.5 s; recovery within <=12 s after translation/ASR worker loss; zero **AI-caused** live playback dropouts during a 60-minute fixture-driven soak. A chosen 10-s playback buffer is intentional, not a failure. ASR translation runtime's combined live budget is 7 s; timeouts must not block original broadcast playback or inject errors as subtitle text.

Radio: TV/Radio share Whisper engine settings. Exercise welle/FFmpeg localhost input without connecting owner's live receiver, Live/Comfort/Relaxed/Adaptive reading modes, music-only vs presenter-over-music, valid/invalid lyrics match, unknown song, Karaoke Refresh and audio source stop/start. Do not accept DLS metadata as proof of sung lyrics. Qwen aligner supports en/de, not tr; Turkish lyrics use Whisper fallback. After presenter interruption, return to speech within <=2 AI chunks; preserve audio playback even when a model or translator times out.

## Failure taxonomy and fail-closed behavior

| Code | Differentiation | Safe fallback |
| --- | --- | --- |
| MISSING_MODEL | No local genuine weights, checkpoint or ready marker | No auto-download; separately verified CPU/Argos if available |
| MISSING_DEPENDENCY | Missing managed venv package, library or installed Argos pair | Report exact dependency, never mutate system Python |
| INSUFFICIENT_VRAM | Measured free GPU memory below declared workload requirement / OOM | Stop offending worker, keep CPU/audio unaffected |
| INCOMPATIBLE_GPU | CUDA device detected but driver/cuDNN/CT2/kernel unsupported | Prefer proven CPU, no guessed GPU readiness |
| UNSUPPORTED_LANGUAGE | Requested Qwen Turkish or unsupported tokenizer target | Whisper or original text, accurately label limitation |
| MODEL_LOADING_FAILURE | Corrupt safetensors, unmaterialized weights, bad revision | Fail closed without checkpoint repairs or private file writes |
| INFERENCE_FAILURE | Model loads, but hangs, errors or produces invalid content | Bound timeout, preserve original text, recover |
| EVIDENCE_HOLD | Synthetic fixtures, installed marker only or partial provenance | Never infer multilingual performance or release PASS |

New pure metadata assessor: `qa/media_real_ai_acceptance_14.py`. It never reads models, imports GPU packages, starts subprocesses or touches private profiles. It always reports **public release HOLD**, including for externally self-reported real inference. Report input JSON must be supplied explicitly and should contain no secrets, paths, recordings or identifiable data.

Run synthetic QA ONLY in disposable CI:

    python3 -m unittest discover -s tests -p 'test_media_real_ai_acceptance_14.py' -v
    python3 qa/media_real_ai_acceptance_14.py

## FUTURE owner-authorized isolated test commands — NOT EXECUTED

**Do not execute on the active owner profile or existing Media Center.** Require new explicit authorization for a specific disposable machine/account, nonprivate fixtures, read-only external SSD and (separately) GPU probe/model inference. Do not invoke legacy install scripts. These instructions are a plan, not consent.

In a disposable checkout, verify the pinned baseline before proceeding:

    cd /path/to/disposable/tihulu-media-center
    test "$(git rev-parse HEAD)" = 2f5699eeb47505468bf3327be4dbdd89fed3dff1

For a secure isolated TEST HOME (not the owner's real HOME), a new test account/VM is preferred:

    export ACCEPT_OWNER_HOME="$(mktemp -d /tmp/media-ai-accept14.XXXXXXXX)"
    chmod 700 "$ACCEPT_OWNER_HOME"
    export HOME="$ACCEPT_OWNER_HOME"
    export XDG_CONFIG_HOME="$HOME/.config"
    export XDG_DATA_HOME="$HOME/.local/share"
    export XDG_CACHE_HOME="$HOME/.cache"
    export XDG_STATE_HOME="$HOME/.local/state"
    bash installer/media-stable-first.sh --check --no-ai

The above is read-only installer preflight. The following is a **separate** consent-gated native build, NOT authorized by this PR and NOT guaranteed offline (pinned upstream Kaffeine clone):

    # ONLY after separately approved disposable build:
    # bash installer/media-stable-first.sh --install --no-ai

After a separately approved disposable native install, switch to its isolated preview profile and offline mode:

    export APP="$ACCEPT_OWNER_HOME/.local/opt/tihulu-media-stable"
    export RELEASE="$(readlink -f "$APP/current")"
    export PREVIEW="$APP/preview-home"
    test -d "$PREVIEW" && test -d "$RELEASE/py/tv_center"
    export HOME="$PREVIEW"
    export XDG_CONFIG_HOME="$PREVIEW/.config"
    export XDG_DATA_HOME="$PREVIEW/.local/share"
    export XDG_CACHE_HOME="$PREVIEW/.cache"
    export XDG_STATE_HOME="$PREVIEW/.local/state"
    export PYTHONPATH="$RELEASE/py"
    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
    export TOKENIZERS_PARALLELISM=false

After separate approval, *read-only hardware probing* of the authorized test machine only:

    /usr/bin/python3 -V
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv,noheader
    command -v nvcc || echo "nvcc absent; CT2 does not require it"

Source-aware runtime discovery (still no actual inference, model downloads or settings writes):

    /usr/bin/python3 - <<'PY'
    from tv_center.whisper_engine import WhisperRuntime
    from tv_center.runtime import AIRuntime
    from tv_center.cuda_faster_whisper import FasterWhisperCUDA
    from tv_center.qwen_forced_aligner import QwenForcedAlignerMarket
    from tv_center.translation_market import TranslationModelMarket
    from tv_center.translation_madlad import MadladMarket
    print("CPU:", WhisperRuntime().ready())
    print("Argos:", AIRuntime().status()["installed"])
    print("CT2 CUDA model:", FasterWhisperCUDA().installed())
    print("Qwen:", QwenForcedAlignerMarket().installed())
    print("NLLB:", TranslationModelMarket().status()["installed"])
    print("MADLAD:", MadladMarket().status()["installed"])
    PY

A fresh --no-ai install should report optional models/runtimes missing. NEVER copy original managed venvs/ready markers as substitutes. For a **read-only mounted, explicitly approved** SSD model folder, plan only:

    /usr/bin/python3 installer/media-ai-compat.py \
      --model-path /mnt/approved-read-only-models/ggml-small.bin \
      --model-dir /mnt/approved-read-only-models

Separate explicit opt-in can create only NEW isolated preview AI JSON; existing preview settings are never overwritten, ASR/translation remain OFF:

    # Not authorized by this task; optional AFTER separate owner approval:
    # /usr/bin/python3 installer/media-ai-compat.py \
    #   --model-path /mnt/approved-read-only-models/ggml-small.bin \
    #   --model-dir /mnt/approved-read-only-models \
    #   --apply --confirm-preview-only

**Actual CUDA inference** only when managed models/venvs already exist in isolated HOME and owner separately authorizes GPU/model use. This invokes the app's true CTranslate2 kernel selftest on **silence** only and will return MISSING_MODEL in a fresh --no-ai install:

    /usr/bin/python3 - <<'PY'
    from tv_center.cuda_faster_whisper import FasterWhisperCUDA
    f=FasterWhisperCUDA()
    print("installed:", f.installed())
    print("probe:", f.probe() if f.installed() else "MISSING_MODEL")
    print("silence-kernel-selftest:",
          f.inference_selftest() if f.installed() else "MISSING_MODEL")
    PY

**CPU real speech**, only with a separately approved, executable whisper.cpp CLI, genuine GGML weights and consented 16-kHz mono WAV files. Replace placeholders, execute for en/de/tr and score reference WER. Does not edit the owner's original configuration:

    export CPU_CLI="/path/to/approved-isolated/whisper-cli"
    export GGML="/mnt/approved-read-only-models/ggml-small.bin"
    export FIXTURE_WAV="/path/to/consented/16khz-mono-de.wav"
    test -x "$CPU_CLI" && test -r "$GGML" && test -r "$FIXTURE_WAV"
    "$CPU_CLI" -m "$GGML" -f "$FIXTURE_WAV" -l de -otxt

**Real translation** only with separately provisioned authorized local runtimes and real checkpoints; NO install/download calls here:

    /usr/bin/python3 - <<'PY'
    from tv_center.runtime import AIRuntime
    from tv_center.ai_provision import StarterAI
    from tv_center.translation_market import TranslationModelMarket
    from tv_center.translation_madlad import MadladMarket
    from tv_center.qwen_forced_aligner import QwenForcedAlignerMarket
    print("Argos runtime:", AIRuntime().status()["installed"])
    print("Argos 3-lang directed packs:", StarterAI().status()["translation_three_languages_ready"])
    n=TranslationModelMarket()
    print("NLLB selftest:", n.selftest() if n.status()["installed"] else "MISSING_MODEL")
    m=MadladMarket()
    print("MADLAD selftest:", m.selftest() if m.status()["installed"] else "MISSING_MODEL")
    print("Qwen status only:", QwenForcedAlignerMarket().status())
    PY

For six-direction content smoke, only after authorizing these locally installed models and using nonprivate text (never remote DeepL):

    /usr/bin/python3 - <<'PY'
    from tv_center.translation_service import translate_argos,translate_nllb,translate_madlad
    sample={"en":"Good morning everyone.","de":"Guten Morgen zusammen.",
            "tr":"Herkese günaydın."}
    for engine,func in (("argos",translate_argos),("nllb",translate_nllb),
                        ("madlad",translate_madlad)):
        for src in ("en","de","tr"):
            for dst in ("en","de","tr"):
                if src==dst: continue
                try:
                    print(engine,src,dst,repr(func(sample[src],src,dst)[:160]))
                except Exception as exc:
                    print(engine,src,dst,"HOLD",type(exc).__name__)
    PY

On an approx. 16 GB GPU, **skip MADLAD by default** until separate VRAM/latency/consent verification, and do not launch multiple large GPU models concurrently. A 32-kHz mono signed-16-bit short, explicitly approved EN/DE fixture is required for real Qwen word alignment; its --status command is not inference, and Turkish is unsupported.

Measure genuine TV/Radio playback/teletext/lyrics behavior only on a disposable fixture source without touching the owner's tuner or live installations. Benchmark outcomes must be independently reviewed against Sections above.

## Independent scoped PASS/HOLD matrix

| Gate | Available evidence | Decision |
| --- | --- | --- |
| Baseline PR #11 CI / source identity | 151/151 executions, 2 successful jobs | Scoped PASS |
| Source profile plans, defaults, synthetic errors | Source inspections and new synthetic tests | Scoped PASS only after new exact-head CI |
| RTX5080 real CT2/cuDNN/driver CUDA kernels and speech | No owner GPU tests | **HOLD** |
| CPU Whisper genuine EN/DE/TR fallback | No real speech/weights tested | **HOLD** |
| Argos 6 directions and installed directed packs | No real pairs tested | **HOLD** |
| NLLB/MADLAD real inference and VRAM/latency | No real checkpoint tests | **HOLD** |
| Qwen real EN/DE anchors and TR fallback | Source fallback known; no real alignment | **HOLD** |
| TV/Radio Teletext/Whisper/music/lyrics recovery and timing | No real receiver/fixture behavior | **HOLD** |
| Private SSD and saved AI parity | Only preview isolation reviewed; no private comparison | **HOLD** |
| Full security, licenses, owner approval | Same-UID race limits and model rights unresolved | **HOLD** |
| Public install/merge/release | Not authorized | **HOLD** |

## Licensing, privacy and release gate

NLLB-200 distilled 600M's publisher specifies **CC-BY-NC-4.0**, research-oriented/noncommercial and not released for production:
https://huggingface.co/facebook/nllb-200-distilled-600M .
Its model license is independent of GPL application code. Do not package for commercial deployment without legal review.

Qwen3 ForcedAligner and MADLAD advertise Apache-2.0, but verify exact model/revision and every dependency before distributing weights. Qwen language list (no tr) from https://qwen.ai/blog?id=qwen3asr . Argos language pack licenses require **per-pack** verification. Review KDE Kaffeine GPL, assets and any test-audio redistribution separately. Remote GPU/DeepL secrets are NOT part of offline acceptance; never auto-import credentials.

No downloads, owner GPU probes, private model inspection, original binary/settings access, service/tuner changes, merge or release in this task. The original stable installation remains untouched. Independent functional/security and owner release authorization remain prerequisites; **public release HOLD**.
