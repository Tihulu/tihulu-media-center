"""Subtitle word pacing against the source TV audio, never decoding completion.

Only use timestamps emitted by an actual local ASR backend. Translation word
alignment is NOT claimed; translation windows use coarse proportional reading
progress and are labelled as estimates. When timestamps are unavailable the
existing chunk queue remains the correct fallback.
"""
from __future__ import annotations


def _translation_window(text: str, first: int, last: int, total: int) -> str:
    """Non-overlapping estimated translation for a single source phrase.

    Repeating a rolling nine-word translation window created a fake
    'karaoke' effect in which the same words reappeared several times.
    We cannot pretend translation is word-aligned: distribute target words
    into disjoint partitions keyed to real source-word group boundaries.
    """
    tokens = str(text).split()
    if not tokens or total <= 0:
        return ""
    a = round(max(0, first) * len(tokens) / total)
    b = round(min(total, last) * len(tokens) / total)
    return " ".join(tokens[a:b])


def word_groups(result: dict, *, maximum_words: int = 7, maximum_span: float = 2.7):
    """Return (source-clip-relative start/end, partial caption result).

    Reject malformed or non-monotonic timestamps rather than presenting a
    guessed exact synchronization. Group word timings remain relative to the
    audio extracted from the *pre-playback-buffer* DVB capture.
    """
    words = result.get("words")
    if result.get("source") != "local_asr" or not isinstance(words, list):
        return []
    valid = []
    previous = -1.0
    for item in words[:240]:
        if not isinstance(item, dict):
            return []
        start, end, text = item.get("start"), item.get("end"), item.get("text")
        if (type(start) not in (int,float) or type(end) not in (int,float)
                or not isinstance(text,str) or not text.strip()
                or start < previous - 0.15 or start < 0 or end < start
                or end > 45 or len(text) > 100):
            return []
        previous = start
        valid.append((float(start), float(end), text.strip()))
    if not valid:
        return []
    turns = result.get("speaker_turns") or []
    def speaker_at(start, end):
        midpoint = (start+end)/2
        if not isinstance(turns,list):
            return None
        for turn in turns:
            if (isinstance(turn,dict) and type(turn.get("start")) in (int,float)
                    and type(turn.get("end")) in (int,float)
                    and turn["start"] <= midpoint <= turn["end"]):
                return str(turn.get("id") or "")[:40] or None
        return None

    groups = []
    index = 0
    while index < len(valid):
        first = index
        finish = index
        first_speaker = speaker_at(valid[first][0],valid[first][1])
        while finish + 1 < len(valid) and finish-first+1 < maximum_words:
            current = valid[finish]
            following = valid[finish+1]
            if current[2].endswith((".", "!", "?", "…")):
                break
            if following[1]-valid[first][0] > maximum_span:
                break
            # Prefer natural pauses and complete clauses instead of
            # flickering one- and two-word fragments every 0.3 seconds.
            if (following[0]-current[1] >= 0.55 and
                    current[1]-valid[first][0] >= 1.3):
                break
            next_speaker = speaker_at(following[0],following[1])
            if first_speaker and next_speaker and first_speaker != next_speaker:
                break
            finish += 1
        snippet = " ".join(x[2] for x in valid[first:finish+1])
        payload = dict(result)
        payload["original"] = snippet
        payload["words"] = []  # avoid nested accumulation in the UI queue
        payload["word_progress"] = {"start":first,"end":finish,"count":len(valid)}
        payload["caption_alignment"] = "ASR word timestamps"
        if first_speaker:
            # Community-1 assigns SPEAKER_00 ... only within each audio clip.
            # Keep that scope visible: do not imply stable person identity
            # or infer gender/age from voice characteristics.
            number = first_speaker.rsplit("_",1)[-1]
            speaker_number = int(number)+1 if number.isdigit() else number[:12]
            payload["speaker_label"] = f"[Speaker {speaker_number} · clip]"
            if type(speaker_number) is int:
                payload["speaker_index"] = speaker_number
        # Exact target-language word timing is not supplied by translation
        # engines. Show a short reading window rather than a 6s text dump.
        source_language = result.get("source_language")
        payload["translations"] = {
            lang:(_translation_window(
                str(result.get("original") or ""),first,finish+1,len(valid))
                if lang == source_language and
                   message.strip() == str(result.get("original") or "").strip()
                else _translation_window(message,first,finish+1,len(valid)))
            for lang,message in (result.get("translations") or {}).items()
            if isinstance(message,str)}
        payload["translations"] = {
            k:v for k,v in payload["translations"].items() if v.strip()}
        if payload["translations"]:
            payload["translation_alignment"] = (
                "distinct phrases divided proportionally; not exact word alignment")
        groups.append((valid[first][0], max(valid[finish][1],
                                           valid[first][0]+0.25), payload))
        index = finish+1
    return groups


def enqueue_word_cues(queue, result, config, captured_start, captured_end, finished):
    groups = word_groups(result)
    if not groups:
        return None
    # Audio extraction can strip leading TS packets. Never schedule past the
    # captured duration plus a small offset; fallback to the regular cue.
    duration = captured_end - captured_start
    if (duration <= 0 or any(start > duration+0.35 or
                                  end > duration+0.5 for start,end,_ in groups)):
        return None
    # When the decoder/translator finishes AFTER the source audio has
    # already played, do not burst several obsolete words in rapid
    # succession. Emit one coherent chunk with an honest late status.
    last_audio_due = captured_end + (
        config.playback_delay_ms + config.offset_ms) / 1000.0
    if finished >= last_audio_due - 0.45:
        return None
    prior = None
    for start,end,payload in groups:
        prior = queue.add(payload, config,
                          captured_start+start,
                          captured_start+max(start+0.25,end),
                          finished)
    return prior
