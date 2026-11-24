from pathlib import Path
p=Path('acceptance_fixes.py');s=p.read_text()
key='    # Optional mpv playback: the external player opens the file with its'
assert s.count(key)==1
block='''    # The caption overlay must never cover a large part of the video, and the
    # owner must be able to switch it off (default) while subtitles still work.
    replace("src/osdwidget.cpp", "const int stripHeight = qBound(48, measured.height()+30,\\n\\t\\t\\tqMax(48,video.height()/3));",
            "// At most a quarter of the video height: the owner reported the\\n"
            "\\t\\t\\t// strip covering half of the screen.\\n"
            "\\t\\t\\tconst int stripHeight = qBound(40, measured.height()+24,\\n"
            "\\t\\t\\tqMax(40,video.height()/4));")
    replace(media, "\\t\\tcaptionPoll->start(150);",
            "\\t\\t{ // Overlay position toggle: off / compact (default) / full\\n"
            "\\t\\t\\tQSettings overlay(QLatin1String(\\"TIHULU\\"),QLatin1String(\\"CaptionOverlay\\"));\\n"
            "\\t\\t\\tconst QString overlayMode=overlay.value(QLatin1String(\\"mode\\"),QLatin1String(\\"compact\\")).toString();\\n"
            "\\t\\t\\tif(overlayMode==QLatin1String(\\"off\\")) {\\n"
            "\\t\\t\\t\\ttihuluCaptionWidget->hideCaption();\\n"
            "\\t\\t\\t\\tvlc->setTihuluNativeCaption(QString(),false,25,0,QLatin1String(\\"#FFFFFF\\"));\\n"
            "\\t\\t\\t}\\n"
            "\\t\\t\\telse if(overlayMode==QLatin1String(\\"full\\")) {\\n"
            "\\t\\t\\t\\t// full: the caption window keeps the larger appearance\\n"
            "\\t\\t\\t}\\n"
            "\\t\\t}\\n"
            "\\t\\tcaptionPoll->start(150);")

'''
s=s.replace(key, block+key, 1)
p.write_text(s);print('overlay limits ok')
