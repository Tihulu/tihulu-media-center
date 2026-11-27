"""Bounded, punctuation-aware live radio sentence assembly.

Never discard the tail of an ASR chunk solely because the next chunk
started. This module does not invent speech or claim forced phoneme alignment.
"""
from __future__ import annotations
import re

_TERMINAL=re.compile(r"[.!?。！？]+(?=\s|$)")
_ABBREVIATIONS={"dr","mr","mrs","ms","prof","etc","z.b","bzw","u.a","ca"}


class LiveSentenceJoiner:
    def __init__(self, max_words=90, max_chunks=3):
        if not 15<=max_words<=250 or not 2<=max_chunks<=8:
            raise ValueError("Invalid bounded sentence joiner")
        self.max_words=max_words
        self.max_chunks=max_chunks
        self.pending=""
        self.chunks=0
        self.language=None
        self.was_split=False

    def reset(self):
        self.pending=""
        self.chunks=0
        self.language=None
        self.was_split=False

    @staticmethod
    def _cut_at_last_sentence(text):
        last=None
        for match in _TERMINAL.finditer(text):
            before=text[:match.start()].strip()
            token=(before.rsplit(" ",1)[-1]).casefold()
            if token in _ABBREVIATIONS:
                continue
            last=match.end()
        return last

    def push(self, phrase: str, *, language=None, silent=False):
        """Return a complete phrase or an explicitly marked bounded continuation.

        Silent: no recognized words in a FULL new audio window, so a brief
        pause may close the previous segment. Long unpunctuated speech is
        displayed after at most max_chunks windows with a visible ellipsis.
        """
        if not isinstance(phrase,str):
            raise TypeError("Expected Unicode transcript")
        text=" ".join(phrase.split())[:2500]
        if text.startswith("[music]"):
            return {"text":text,"complete":True,"pending":False,"chunks":0}
        if language and self.language and language!=self.language and self.pending:
            # Different spoken language cannot safely be glued to the
            # previous source-language sentence.
            previous=self.pending.rstrip()
            self.reset()
            self.language=language
            if text:
                self.pending=text
                self.chunks=1
            return {"text":previous+" …","complete":False,
                    "pending":False,"chunks":1,"language_switched":True}
        if language:
            self.language=language
        if text:
            if self.pending:
                # Even after the prior raw-clip overlap was trimmed, a long
                # ASR hypothesis may repeat words already held by the
                # sentence assembler. Trim a verified 4+ word boundary only.
                # Keep shorter repetitions ("nein nein", "ja ja") intact.
                from kaffeine_next.continuous_captions import remove_repeated_prefix
                text = remove_repeated_prefix(
                    self.pending, text, maximum_words=64, minimum_words=4)
            if text:
                self.pending=(self.pending+" "+text).strip()
                self.chunks+=1
        elif not self.pending:
            return {"text":"","complete":False,"pending":False,"chunks":0}
        boundary=self._cut_at_last_sentence(self.pending)
        if boundary is not None:
            full=self.pending[:boundary].strip()
            self.pending=self.pending[boundary:].strip()
            age=self.chunks
            self.chunks=1 if self.pending else 0
            self.was_split=False
            return {"text":full,"complete":True,"pending":bool(self.pending),
                    "chunks":age}
        if silent:
            result=self.pending
            self.reset()
            return {"text":result,"complete":True,"pending":False,
                    "chunks":1,"closed_by_pause":True}
        if self.chunks>=self.max_chunks or len(self.pending.split())>=self.max_words:
            part=self.pending
            self.pending=""
            self.chunks=0
            self.was_split=True
            return {"text":part+" …","complete":False,"pending":False,
                    "chunks":self.max_chunks,"continued":True}
        return {"text":"","complete":False,"pending":True,
                "chunks":self.chunks}
