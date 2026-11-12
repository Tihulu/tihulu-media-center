# Experimental simultaneous TV speakers and independent sound labels

This is an optional, owner-controlled desktop AI path. Nothing new is
installed, downloaded or loaded during normal TV or Model Market startup.

## Two voices speaking at the same time

The standard **Resemblyzer** embedding/cluster process estimates that one
voice has changed to another. It does **not** unmix two superposed speakers.
For true simultaneous dialogue this experiment uses the local SpeechBrain
SepFormer **speechbrain/sepformer-wsj02mix** model (Apache-2.0, approximately
113 MB weights, potentially several GB of isolated torch/CUDA dependencies).

1. Open **Live Captions → Source & sync**. Select **Whisper/ASR**, configure
   managed Faster-Whisper CUDA and your desired spoken/output languages.
2. Check **Experimental · separate TWO simultaneous voices**. The model
   is OFF by default. Click **Install SepFormer** and explicitly approve the
   model/dependency downloads once. TV tuning is never modified.
3. Optionally check **Show speaker names/numbers**. It is OFF by default.
   **New subtitle line when Resemblyzer detects a different speaker** is a
   separate preference and can remain ON even with all names hidden.
4. Click **Apply** and test a real overlap recording. Each six-second
   audio clip passes through *one* source separator and *two independent*
   CUDA Whisper requests, plus the ordinary mixed-waveform ASR fallback.
   Each emitted subtitle source must actually contain timed recognized
   words and two distinct transcripts with concurrent timing; otherwise
   only the original mixed-source ASR is displayed.
5. The default TV playback buffer may not be enough for this heavy path,
   especially when translating both voices. Observe actual end-to-end
   caption delay and ASR queue overflow diagnostics. A 20-second FIFO cap
   is not a lip-sync guarantee, and additional CUDA model inference may
   take longer than the buffered playback window.

The SepFormer checkpoint was trained on **English WSJ0-2Mix clean 8-kHz
two-speaker audio**. Turkish, French, German, background TV music, voices
in dubbing, three concurrent speakers and RTX 5080 CUDA speed are **not
hardware-validated**. The isolated worker resamples back to 32 kHz
so the existing multilingual Faster-Whisper pipeline can accept it.
Audio is processed offline after initial authorized setup. There is no
claim of persistent real-world speaker identity: SepFormer output A/B may
swap between clips. **Source separation is imperfect and ASR hallucinations
are still possible**; conservative gating prevents many fabricated lines.

## Independent labels

The checkbox **Show speaker names/numbers** enables provisional
`[Speaker N]` / optional manual name overrides; leave it OFF to show
distinct voices without `[Adam 1]`. Resemblyzer detects voice changes
even when speaker labels are hidden. Short unknown/ambiguous words
may not be assigned reliably.

**Estimated voice category** uses a *separate* optional audEERING Wav2Vec2
six-layer model, with child/female/male **acoustic-class probabilities**.
This model is licensed **CC BY-NC-SA 4.0 for non-commercial use**; click
its separate installer and accept license conditions intentionally.
Only predictions with >= 0.82 confidence are considered. These are
**perceived voice traits, not verified age, gender or real speaker identity**.
The fallback is to omit the category. No classification is fabricated from
Resemblyzer pitch/embedding data. We deliberately do NOT assign a category
to a mixed recording unless diarization reports one unique voice.

**Show detected non-speech sound labels** is another independent
preference. Its optional MIT AudioSet/AST checkpoint (BSD-3-Clause, ~346 MB)
provides event scores for supported classes such as music, humming,
laughter, applause and noise. Only detector-backed high-score events
are displayed; no `[Müzik]` is fabricated from an empty Whisper clip.

The two optional acoustic classifiers each install into a separate
private user-owned virtual environment. Clicking the explicit installer
requests approval before downloading heavy CPU PyTorch dependencies.
Classifiers only run when their corresponding checkbox is enabled.

## Offline status tests

From an installed source checkout:

```bash
python3 -m tv_center.overlap_separation --status
python3 -m tv_center.audio_classifiers --status
python3 -m unittest tests.test_tv_dual_voice_separation tests.test_tv_acoustic_sound_voice_models
```

A weight-file marker confirms that files exist, **not** that the model
actually ran with your host CUDA/CPU stack. Real sample separation,
classification, translation quality, clip latency, screen placement
and TV buffer sync still require an acceptance test on the user's TV
receiver and GPU.

For Pi 5 8 GB, do not enable 3× Whisper plus SepFormer by default; this
is aimed at high-end NVIDIA GPU PCs. Use local CPU Tiny or an explicitly
authorized remote GPU host for lighter profiles instead.
