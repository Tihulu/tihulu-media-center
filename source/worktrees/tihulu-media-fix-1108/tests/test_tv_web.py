"""No-hardware tests for authorized remote TV commands and web bundles."""
from pathlib import Path
import threading
import unittest
from tv_center.web_control import WebCommandQueue
from tv_center.lan import MobileLAN
from tv_center.bridge import TVBridge

class BrowserTVTests(unittest.TestCase):
    def test_web_command_queued_for_gui_thread(self):
        bridge=WebCommandQueue()
        result=[]
        def client():
            result.append(bridge.submit("channels",{}))
        worker=threading.Thread(target=client)
        worker.start()
        self.assertTrue(bridge.queue.not_empty or worker.is_alive())
        bridge.drain(lambda action,params: {"action":action,"params":params})
        worker.join(timeout=2)
        self.assertEqual(result,[{"action":"channels","params":{}}])
        bridge.close()
        with self.assertRaises(RuntimeError):
            bridge.submit("channels",{})

    def test_reject_unlisted_web_action(self):
        controller=WebCommandQueue()
        with self.assertRaises(ValueError):
            controller.submit("arbitrary_shell",{"cmd":"rm"})
        controller.close()

    def test_lan_pairing_uses_cookie_and_commands_opt_in(self):
        controller=MobileLAN(lambda:{},lambda p:None,lambda:None,
                             commands=lambda name,args:{"requested":name})
        self.assertIsNotNone(controller.commands)
        ticket,err=controller.accept_pin("192.168.1.50",controller.pin)
        self.assertIsNone(err)
        self.assertTrue(controller.authorized("tihulu_tv="+ticket))
        self.assertFalse(controller.authorized(""))

    def test_pages_token_remains_opt_in_and_localhost_only(self):
        bridge=TVBridge(lambda:{},lambda p:None,commands=lambda name,args:{})
        self.assertIsNotNone(bridge.commands)
        with self.assertRaises(ValueError):
            TVBridge(lambda:{},lambda p:None,host="0.0.0.0")

    def test_browser_assets_link_to_real_controls(self):
        root=Path(__file__).parents[1]/"tv_center/web"
        pages=(root/"index.html").read_text()
        mobile=(root/"mobile.html").read_text()
        for page in (pages,mobile):
            self.assertIn('id="web-control-root"',page)
            self.assertIn("web-controls.js",page)
        self.assertIn("browser-ai-ui.js",pages)
        for name in ("browser-ai-ui.js","browser-ai-worker.js","web-controls.js"):
            self.assertTrue((root/name).is_file())

if __name__=="__main__":
    unittest.main()
