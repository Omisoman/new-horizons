"""Screenshot Streamlit pages through headless Chrome's DevTools protocol.

    uv run python scripts/shots.py                       # every page, :8501
    uv run python scripts/shots.py --port 8502 --out docs/shots/host overview chat
    uv run python scripts/shots.py chat --ask "…"            # chat after an answer
    uv run python scripts/shots.py chat --ask "…" --compare  # -> chat-compare.png

Chrome's own --screenshot flag can't wait for Streamlit (the app renders over
a websocket after `load`, and --virtual-time-budget never settles on an open
socket), so this drives CDP directly: navigate, wait until a page header
(either design system) exists and no spinner is showing, let Plotly settle,
capture the viewport.
Needs only Google Chrome and `websockets` (already a Streamlit dependency).
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PAGES = ["overview", "reconcile", "drift", "patterns", "documents", "chat", "changes", "admin", "settings"]
READY_JS = ("!!document.querySelector('.ac-header') && "
            "!document.querySelector('[data-testid=\"stSpinner\"]')")
ANSWERS_JS = ("[...document.querySelectorAll('[data-testid=\"stCaptionContainer\"]')]"
              ".filter(e => e.innerText.includes('citations:')).length")
TOGGLE_JS = "document.querySelector('[data-testid=\"stSidebar\"] input[type=\"checkbox\"]').click()"
INPUT_JS = "document.querySelector('textarea[data-testid=\"stChatInputTextArea\"]').focus()"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", default=PAGES)
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--out", type=Path, default=Path("docs/shots"))
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--settle", type=float, default=3.0, help="seconds after ready")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--ask", help="chat page: submit this question, wait for the answer")
    ap.add_argument("--compare", action="store_true", help="with --ask: compare mode on")
    a = ap.parse_args()
    width, height = map(int, a.size.split("x"))
    a.out.mkdir(parents=True, exist_ok=True)

    profile = tempfile.mkdtemp(prefix="horizons-shots-")
    dbg = 9333
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={dbg}", f"--user-data-dir={profile}",
         f"--window-size={width},{height}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg}/json/list") as r:
                    targets = json.load(r)
                break
            except OSError:
                time.sleep(0.2)
        page = next(t for t in targets if t["type"] == "page")
        with connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            seq = 0

            def cdp(method: str, **params) -> dict:
                nonlocal seq
                seq += 1
                ws.send(json.dumps({"id": seq, "method": method, "params": params}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == seq:
                        return msg.get("result", {})

            def wait(js: str, until, timeout: float) -> bool:
                deadline = time.time() + timeout
                while time.time() < deadline:
                    time.sleep(0.5)
                    res = cdp("Runtime.evaluate", expression=js, returnByValue=True)
                    if until(res.get("result", {}).get("value")):
                        return True
                return False

            cdp("Emulation.setDeviceMetricsOverride", width=width, height=height,
                deviceScaleFactor=1, mobile=False)
            for name in a.pages:
                url = f"http://localhost:{a.port}/{'' if name == 'overview' else name}"
                cdp("Page.navigate", url=url)
                ready = wait(READY_JS, bool, a.timeout)
                stem = name
                if name == "chat" and a.ask:
                    if a.compare:
                        cdp("Runtime.evaluate", expression=TOGGLE_JS)
                        time.sleep(2)  # rerun renders the "…against" selector
                        stem = "chat-compare"
                    cdp("Runtime.evaluate", expression=INPUT_JS)
                    cdp("Input.insertText", text=a.ask)
                    for kind in ("keyDown", "keyUp"):
                        cdp("Input.dispatchKeyEvent", type=kind, key="Enter", code="Enter",
                            windowsVirtualKeyCode=13)
                    want = 2 if a.compare else 1
                    ready = wait(ANSWERS_JS, lambda n: (n or 0) >= want, 300)
                time.sleep(a.settle)
                png = cdp("Page.captureScreenshot", format="png")["data"]
                (a.out / f"{stem}.png").write_bytes(base64.b64decode(png))
                print(f"{stem:14s} {'ok' if ready else 'TIMEOUT'} -> {a.out / (stem + '.png')}")
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
