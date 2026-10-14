"""The README's lead GIF: the Reconcile page, then the chat answering the
verification question — ~20 s, driven through headless Chrome like shots.py.

    make demo1            # in another terminal (needs db-up mock kb)
    uv run python scripts/readme-gif.py [--port 8501] [--out docs/shots/readme.gif]

Frames are real captures of the running app (nothing is drawn), scaled to
960 px and quantised to one palette so the file stays small.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from websockets.sync.client import connect

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
QUESTION = ("How many kilograms did AQ-03 lose in the week after the pump failure, and what "
            "does the maintenance SOP say the response time should have been?")
READY_JS = ("!!document.querySelector('.ac-header') && "
            "!document.querySelector('[data-testid=\"stSpinner\"]')")
ANSWERS_JS = ("[...document.querySelectorAll('[data-testid=\"stExpander\"] summary')]"
              ".filter(e => /trace ·|التتبع ·/i.test(e.innerText)).length")
OPEN_TRACE_JS = ("[...document.querySelectorAll('[data-testid=\"stExpander\"] summary')]"
                 ".filter(e => /trace ·/i.test(e.innerText)).pop().click()")
INPUT_JS = "document.querySelector('textarea[data-testid=\"stChatInputTextArea\"]').focus()"
SCROLL_JS = ("(document.querySelector('[data-testid=\"stMain\"]') || document.scrollingElement)"
             ".scrollBy({top: %d, behavior: 'instant'})")
BOTTOM_JS = ("(() => {const m = document.querySelector('[data-testid=\"stMain\"]') || "
             "document.scrollingElement; m.scrollTop = m.scrollHeight;})()")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--out", type=Path, default=Path("docs/shots/readme.gif"))
    ap.add_argument("--width", type=int, default=960)
    a = ap.parse_args()
    W, H = 1440, 900
    profile = tempfile.mkdtemp(prefix="horizons-gif-")
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--remote-debugging-port=9334", f"--user-data-dir={profile}",
         f"--window-size={W},{H}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frames: list[tuple[Image.Image, int]] = []       # (frame, milliseconds)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen("http://127.0.0.1:9334/json/list") as r:
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

            def js(expr: str):
                return cdp("Runtime.evaluate", expression=expr, returnByValue=True) \
                    .get("result", {}).get("value")

            def wait(expr: str, until, timeout: float = 120) -> None:
                deadline = time.time() + timeout
                while time.time() < deadline and not until(js(expr)):
                    time.sleep(0.4)

            def snap(ms: int, settle: float = 1.2) -> None:
                time.sleep(settle)
                png = base64.b64decode(cdp("Page.captureScreenshot", format="png")["data"])
                img = Image.open(io.BytesIO(png)).convert("RGB")
                img = img.resize((a.width, round(a.width * H / W)), Image.LANCZOS)
                frames.append((img, ms))

            cdp("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1,
                mobile=False)
            cdp("Page.navigate", url=f"http://localhost:{a.port}/reconcile")
            wait(READY_JS, bool)
            snap(3200, settle=3.0)
            js(SCROLL_JS % 640)
            snap(3000)
            js(BOTTOM_JS)
            snap(2600)

            cdp("Page.navigate", url=f"http://localhost:{a.port}/chat")
            wait(READY_JS, bool)
            time.sleep(2.0)
            js(INPUT_JS)
            cdp("Input.insertText", text=QUESTION)
            snap(2200, settle=0.6)
            for kind in ("keyDown", "keyUp"):
                cdp("Input.dispatchKeyEvent", type=kind, key="Enter", code="Enter",
                    windowsVirtualKeyCode=13)
            wait(ANSWERS_JS, lambda n: (n or 0) >= 1, 300)
            js(BOTTOM_JS)
            snap(3600, settle=1.5)
            js(OPEN_TRACE_JS)
            js(BOTTOM_JS)
            snap(4200, settle=1.5)
    finally:
        chrome.terminate()

    # one shared palette across frames: no shimmer between them
    sheet = Image.new("RGB", (frames[0][0].width, frames[0][0].height * len(frames)))
    for i, (img, _) in enumerate(frames):
        sheet.paste(img, (0, i * img.height))
    palette = sheet.quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    quantised = [img.quantize(palette=palette, dither=Image.Dither.NONE) for img, _ in frames]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    quantised[0].save(a.out, save_all=True, append_images=quantised[1:], loop=0,
                      duration=[ms for _, ms in frames], optimize=True, disposal=1)
    total = sum(ms for _, ms in frames) / 1000
    print(f"{len(frames)} frames, {total:.1f} s, {a.out.stat().st_size / 1e6:.2f} MB -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
