from pathlib import Path
p=Path('acceptance_fixes.py');s=p.read_text()
anchor='''            "\\tif(QFileInfo::exists(sidecar))effectiveSubtitle=QUrl::fromLocalFile(sidecar);\\n"
            "\\t}")'''
assert s.count(anchor)==1
add='''
    replace(media, "\\tplay(new MediaSourceUrl(url, subtitleUrl));",
            "\\tplay(new MediaSourceUrl(url, effectiveSubtitle));")'''
s=s.replace(anchor, anchor+add, 1)
p.write_text(s);print('added play line')
