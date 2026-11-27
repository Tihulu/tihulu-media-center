# TIHULU Radio · UX and sync review (2026-11-08)

This is native Qt / Kaffeine code, not a screenshot prototype.

## One window, five radio modes

The Radio page now has a compact station readout and five modes:
- DAB+: real block/service selection, Favorites, library, actual SNR, DLS, slideshow and original live caption canvas. Station library and programme info stack vertically when the window is narrow.
- Internet radio: worldwide country/station search, favourites, stream test and alternate URL; no antenna or USB needed.
- Vintage FM/AM/LW: authentic analogue dial and frequency, volume/mute, PCM VU (not fake RF strength), controlled RTL-SDR. An independent readout shows the selected DAB or Internet station without pretending it is the FM frequency.
- AI subtitles / lyrics: auto/manual speech language, selected translations, singing detection, available language packs, buffer and offset, local/online TXT/LRC and audio-driven LyricSync.
- RF Lab: FFT, spectrum, constellation, waterfall, multiview and advanced decoder options.

The chosen radio mode persists across app launches. Smaller layouts use multi-row controls and resizable RF charts instead of clipped horizontal rows. Existing TV, Hardware, local media, recording, favourites and AI model panels remain in the application.

## Buffer / offset facts

The earlier radio buffer was capped at 20,000 milliseconds. The UI and the actual libVLC per-media network-caching setting now both allow 0–60,000 milliseconds (a finite safety ceiling).

Recommendation = 6,000 ms captured audio + observed p80 Whisper processing + sentence carry delay + 3,000 ms safety margin, rounded to 500 ms. This is a compute estimate, NOT a measurement of audio actually reaching the speakers.

An auto recommendation saves a requested value for NEXT station tune. The active stream has a separately recorded applied value, used for subtitle scheduling and the progress bar. No automatic audio restart by default. If users explicitly allow auto audio restart, it is limited to at most once per 180 seconds and at least 5,000 ms of meaningful increased demand. Manual Apply restarts the live DAB audio and resets the AI worker to prevent using the previous timeline. An interruption is possible.

The 300 ms caption UI tick and periodic buffer estimation do not themselves restart or retune the radio. The regular spoken ASR/translation offset is separate from music lyric offset.

## Singing and lyrics

- Show original plus target-language translations when installed translation models can produce them and Whisper identifies the current vocal language reliably.
- Lyrics-source language is now separately selectable from spoken programme language. Choosing DE / EN / TR / other known song source enables immediate text translation of available LRC lyrics; Auto waits for confident live audio recognition and avoids leaking a presenter's language into the next song.
- A real bug: timed LRC with plain text for audio matching was falsely tagged untimed. Now a retrieved LRC with timestamps stays in timed_lrc mode.
- Plain lyrics remain without fictional timestamps; they appear only after actual ASR matches the line. A verified matching line can carry its own translation back to the player, and timed LRC may reuse that translation only for that exact line.
- LyricSync is now rate-limited: two consistent ≥92% matches, 30 second cooldown and at most 250 ms per change. Outliers over 15 seconds are rejected.
- Unchanged lyrics are not repainted every caption polling tick, reducing visible flicker.

## Testing limitations

Passing source tests and compiling Qt proves these code paths build; it does NOT prove speaker-output sample-accurate lip sync or reliable translations on a physical GPU. Test 800px viewport, real DAB speech/music language changes, manual offsets, cache application and all 5 radio pages on the actual host before calling the PR production-ready. Retain PR #38 in DRAFT.


## User-reported regression triage: subtitle canvas, source failure and licensing

The DAB live cue loop previously called `radioCanvas_->setText(cue.text)`,
replacing the radio's central artwork/status display with large unrelated
transcription text. It now renders in a compact permanent banner near the
selected station label and the detailed AI caption label. The station image,
RF plot, slideshow, teletext and other player components remain independent.

The 60-second `libVLC network-caching` value was a *requested option* at media
open, and earlier progress counted wall-clock time since opening as if it
were verified PCM playback-buffer fill. That visual cannot measure the
actual decoder queue or speaker DAC timestamps. The large cyan 100%-Ready
indicator was removed in favor of an explicit **UNVERIFIED** indeterminate
state; cue countdowns are labeled *estimates*. Independent clock capture,
libVLC media timestamps and audio-to-text cue timestamps remain needed for
calibrated lip synchronization.

Lyrics lookup is explicit and sequential. First LRCLIB exact track and a
metadata-checked catalog retry, then (only with a user-supplied officially
licensed `TIHULU_MUSIXMATCH_API_KEY`) the Musixmatch official plain-text
API, then the keyless lyrics.ovh plain-text source. Any ambiguous metadata,
preview-only/limited lyrics or nonmatching song is rejected. **No unofficial
Musixmatch mobile API, embedded client token, scraping or login bypass.**
The official API has licensing requirements; access is not free/open just
because the SDK code is visible. Public metadata (artist/title only) is
sent only when the user clicks Find or explicitly enables new-song lookup;
private audio is never uploaded to the lyrics services. Plain lyrics are
not assigned fabricated timing or treated as verified *heard* words without
Whisper audio matching. The fetched service's provenance remains visible
in the UI.

When lyric lookup fails or a DLS artist/title isn't available, the
user-requested **Listen & transcribe vocals offline** action uses the same
local welle-cli audio and an installed Whisper model in *singing/music*
mode. An additional checked-by-default option starts this path when an
authorized lyrics lookup returns no match. The result is a *heard ASR guess*,
not externally verified lyrics and not a copyright-licensed song text.
Stop lyrics releases only a lyric-owned AI job; independent manual AI use
is restored when it existed. The explicit **Apply caption settings** action
restarts ASR/translator sidecar without retuning radio, touching VLC playback,
or changing the buffer. Process exits now provide a diagnostic.

### Remaining limits / not claimed solved

- Actual libVLC audio output latency and Qt native DVB video compositor
  behavior on this user's COSMIC / NVIDIA equipment are not hardware
  verified by CI, and word-level alignment is not established from 5–6s
  broadcast chunks.
- LRCLIB and lyrics.ovh may have no rights-cleared lyrics for the current
  station; they are Internet sources, not offline catalogs. Official
  Musixmatch availability depends on the user's own licensing contract.
- Streaming Spotify/YouTube/other protected services and Internet-radio
  streams are not automatically captured by the local welle DAB-only
  ASR worker. Their audio paths need separate verified routing.
- UI fixes target radio/DAB subtitle panel; broadcaster TV Teletext,
  DVB native libVLC output and legacy Qt overlay have separate controls
  and require physical device testing. Do not claim this patch fixes all
  possible TV subtitle failures or restores sample-accurate sync.
