"""Cửa sổ thật bằng pywebview (WKWebView) như app trên Mac, chụp màn hình bằng screencapture."""
import subprocess, sys, threading, time, webview
port, name = int(sys.argv[1]), sys.argv[2]
w = webview.create_window("test", f"http://127.0.0.1:{port}/", width=1400, height=860, x=0, y=0)
def run():
    time.sleep(7); subprocess.run(["screencapture", "-x", f"shots/native-{name}-1-loc-anh.png"])
    w.evaluate_js("PS.show('layout')"); time.sleep(2); subprocess.run(["screencapture", "-x", f"shots/native-{name}-2-dan-trang.png"])
    w.evaluate_js("PS.show('filter')"); time.sleep(2); subprocess.run(["screencapture", "-x", f"shots/native-{name}-3-ve-loc-anh.png"])
    w.destroy()
threading.Thread(target=run, daemon=True).start()
webview.start()
