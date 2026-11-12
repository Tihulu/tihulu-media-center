import tempfile
from pathlib import Path
import unittest

from textcenter.core import (
    Store, clean_text, fetch_feed, parse_feed, safe_https_url,
    text_only, validate_timestamp,
)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Store(Path(self.tmp.name) / "app.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_archive_and_bulletin_persistence(self):
        self.assertEqual(self.db.counts()["articles"], 0)
        self.db.add_bulletin("Offline", "<script>alert(1)</script>", "Owner")
        self.assertEqual(self.db.bulletins()[0]["body"], "<script>alert(1)</script>")
        self.assertEqual(Store(self.db.filename).counts()["bulletins"], 1)

    def test_trusted_feed_registration(self):
        fid = self.db.add_feed("News", "https://example.org/feed.xml")
        self.assertEqual(len(fid), 16)
        self.assertEqual(self.db.feeds()[0]["title"], "News")
        for bad in ("http://example.org/feed", "https://127.0.0.1/rss",
                    "https://example.local/rss", "https://user:pw@example.org/rss",
                    "https://example.org:8080/rss", "javascript:alert(1)",
                    "https://localhost/rss", "https://example.org/rss#fragment"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                safe_https_url(bad)

    def test_rss_parse_and_local_search(self):
        fid = self.db.add_feed("Example", "https://example.org/rss")
        rss = b"""<rss version="2.0"><channel><title>Example</title>
        <item><title>Alpha &amp; beta</title>
        <link>https://example.org/article</link>
        <description><![CDATA[<p>Hello <b>world</b><script>evil()</script></p>]]></description>
        <pubDate>Fri, 06 Nov 2026 10:00:00 +0000</pubDate></item>
        </channel></rss>"""
        parsed = parse_feed(rss,feed_id=fid,feed_title="Example",source_url="https://example.org/rss")
        self.assertEqual(parsed[0]["title"],"Alpha & beta")
        self.assertEqual(parsed[0]["body"],"Hello world")
        self.assertEqual(parsed[0]["medium"],"internet_feed")
        self.assertEqual(self.db.refresh_feed(fid,fetcher=lambda _:rss),1)
        self.assertEqual(self.db.articles("world")[0]["title"],"Alpha & beta")
        self.assertEqual(self.db.articles("%"),[])
        self.assertEqual(self.db.feeds()[0]["last_count"],1)

    def test_json_feed_v11_text_and_html_items(self):
        feed={
            "version":"https://jsonfeed.org/version/1.1",
            "title":"Example",
            "items":[
                {"id":"1","title":"Text item","url":"https://example.org/one",
                 "content_text":"Native JSON Feed body","date_published":"2026-11-06T10:00:00Z"},
                {"id":"2","title":"HTML item","url":"https://example.org/two",
                 "content_html":"<p>Page</p><script>discard()</script><b>safe</b>"},
                {"id":"3","title":"Bad URL","url":"http://127.0.0.1/private",
                 "content_text":"No local link should be exposed"}
            ]
        }
        import json
        fid=self.db.add_feed("JSON", "https://example.org/feed.json")
        rows=parse_feed(json.dumps(feed).encode(),feed_id=fid,feed_title="JSON",
                        source_url="https://example.org/feed.json")
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]["body"],"Native JSON Feed body")
        self.assertIn("Page",rows[1]["body"])
        self.assertNotIn("discard",rows[1]["body"])
        self.assertEqual(rows[2]["url"],"")
        self.assertEqual(self.db.refresh_feed(fid,fetcher=lambda _:json.dumps(feed).encode()),3)
        self.assertEqual(len(self.db.articles()),3)
        for bad in (b'{"version":"not-jsonfeed","items":[]}',
                    b'{"version":"https://jsonfeed.org/version/1.1","items":{}}'):
            with self.assertRaises(ValueError):
                parse_feed(bad,feed_id=fid,feed_title="JSON",source_url="https://example.org/feed.json")

    def test_atom_and_xml_entity_limits(self):
        atom=b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>One</title><link rel="alternate" href="https://example.org/post"/>
        <summary>Read me</summary><updated>2026-11-06T10:00:00Z</updated></entry></feed>"""
        rows=parse_feed(atom,feed_id="f",feed_title="F",source_url="https://example.org/feed")
        self.assertEqual(rows[0]["url"],"https://example.org/post")
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE foo [<!ENTITY x "p">]><rss/>',feed_id="f",feed_title="F",source_url="https://example.org")
        with self.assertRaises(ValueError):
            parse_feed(b"not xml",feed_id="f",feed_title="F",source_url="https://example.org")

    def test_import_provenance_and_missing_pages(self):
        payload={
            "schema_version":1,
            "pages":[{"source_id":"rx1","page":100,"subpage":0,"title":"Real page",
                "body":"Decoded payload","language":"en","received_at":"2026-11-06T12:00:00Z",
                "station":"Example","frequency_hz":514000000,
                "medium":"dvb_teletext","provenance":"Decoder v1 input file"}],
            "events":[{"source_id":"rx2","title":"RDS text","body":"Actual decoded string",
                "language":"de","received_at":"2026-11-06T12:00:00+01:00",
                "station":"FM test","frequency_hz":98600000,"medium":"fm_rds",
                "provenance":"Decoder v1 input file"}]
        }
        self.assertEqual(self.db.import_data(payload),{"pages":1,"events":1})
        self.assertEqual(self.db.page("rx1",100,0)["station"],"Example")
        self.assertEqual(self.db.page("rx1",100,0)["body"],"Decoded payload")
        self.assertIsNone(self.db.page("rx1",101,0))
        self.assertEqual(self.db.events()[0]["medium"],"fm_rds")
        payload["pages"][0]["page"] = 900
        with self.assertRaises(ValueError):
            self.db.import_data(payload)
        self.assertEqual(self.db.counts()["pages"],1)

    def test_reject_fake_decoder_or_missing_timestamp(self):
        obj={"schema_version":1,"pages":[{"source_id":"rx","page":100,"title":"Page",
            "body":"Body","language":"en","station":"X",
            "received_at":"2026-11-06T12:00:00","frequency_hz":514000000,
            "medium":"dvb_teletext","provenance":"file"}]}
        with self.assertRaises(ValueError):
            self.db.import_data(obj)
        obj["pages"][0]["received_at"]="2026-11-06T12:00:00Z"
        obj["pages"][0]["frequency_hz"]=0
        with self.assertRaises(ValueError):
            self.db.import_data(obj)
        obj["pages"][0]["frequency_hz"]=514000000
        obj["pages"][0]["medium"]="rss"
        with self.assertRaises(ValueError):
            self.db.import_data(obj)

    def test_bounded_bookmarks(self):
        self.db.add_bookmark("Index","page","100:0:")
        self.db.add_bookmark("Index updated","page","100:0:")
        self.assertEqual(len(self.db.bookmarks()),1)
        with self.assertRaises(ValueError):
            self.db.add_bookmark("Bad","javascript","alert()")

    def test_html_sanitization_utility(self):
        self.assertEqual(text_only("<p>A<br>B</p><style>secret</style>"),"A B")
        self.assertEqual(clean_text("  a \n b  "),"a b")
        self.assertEqual(validate_timestamp("2026-11-06T10:00:00+01:00"),"2026-11-06T09:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
