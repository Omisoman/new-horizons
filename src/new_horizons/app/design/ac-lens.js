/* Nav name tag — over a sidebar nav square, the square's name rises out of the pointer into a
 * glass tag above the square, and glides to the next square instead of blinking at the gaps.
 * design/ac.css owns the look; the pointer itself is the system's own (custom pointers were
 * tried and flickered: an image pointer in Chrome and Safari, a page-drawn one in Chrome).
 * A newer copy of the script replaces an older one; the same copy delivered again by a rerun
 * is ignored. */
(() => {
  const VERSION = 6;
  const installed = window.__acLens;
  if (installed && installed.version === VERSION) return;
  if (installed && installed.stop) installed.stop();
  document.querySelectorAll(".ac-lens, .ac-pointer").forEach((old) => old.remove());
  document.documentElement.classList.remove("ac-lens-ready");   // older copies hid the pointer

  // Built node by node: Streamlit sanitises st.html with DOMPurify, which drops a script
  // whose text holds anything that looks like markup — so no tag strings in this file.
  const tag = document.body.appendChild(document.createElement("div"));
  tag.className = "ac-lens";
  tag.setAttribute("aria-hidden", "true");

  const NAV = '.st-key-app-nav [data-testid="stPageLink-NavLink"]';
  const GAP = 8;        // px between the tag and its square
  const EDGE = 8;       // px the tag keeps from the window's sides
  const GRACE = 160;    // ms the tag waits before leaving: crossing the gap to the next square
  let lastLink = null, current = "", hideTimer = 0;

  const hideTag = () => {
    clearTimeout(hideTimer);
    current = "";
    lastLink = null;
    tag.classList.remove("show", "slide");
  };

  const showTag = (link, px, py) => {
    clearTimeout(hideTimer);
    if (link === lastLink) return;
    lastLink = link;
    const label = link.querySelector('[data-testid="stMarkdownContainer"]');
    const name = label ? label.textContent.trim() : "";
    const key = `${link.getAttribute("href") || ""}|${name}`;
    if (!name || key === current) return;             // a rerun's new node for the same square
    const slide = tag.classList.contains("show");     // already up: glide to the next square
    current = key;
    if (!slide) {
      tag.style.transition = "none";
      tag.classList.remove("show");
    }
    tag.textContent = name;                            // the link's own text: follows the language
    const box = link.getBoundingClientRect();
    const w = tag.offsetWidth;
    const h = tag.offsetHeight;
    const left = Math.min(Math.max(box.left + box.width / 2 - w / 2, EDGE),
                          window.innerWidth - EDGE - w);
    const top = Math.max(box.top - GAP - h, EDGE);
    tag.style.translate = `${Math.round(left)}px ${Math.round(top)}px`;
    if (!slide) {
      tag.style.transformOrigin = `${Math.round(px - left)}px ${Math.round(py - top)}px`;
      void tag.offsetWidth;                            // rise out of the pointer from here
      tag.style.transition = "";
    }
    tag.classList.toggle("slide", slide);
    tag.classList.add("show");
  };

  const ctl = new AbortController();
  const opts = { passive: true, signal: ctl.signal };

  document.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse") return;
    const link = e.target instanceof Element ? e.target.closest(NAV) : null;
    if (link) {
      showTag(link, e.clientX, e.clientY);
    } else if (current) {
      lastLink = null;
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hideTag, GRACE);
    }
  }, opts);
  // Only a real exit hides the tag at once: `mouseout` with no related target also fires
  // while the page updates under a still pointer.
  document.documentElement.addEventListener("mouseleave", hideTag, opts);
  window.addEventListener("blur", hideTag, opts);
  window.addEventListener("scroll", hideTag, { passive: true, capture: true, signal: ctl.signal });

  window.__acLens = {
    version: VERSION,
    stop: () => {
      ctl.abort();
      clearTimeout(hideTimer);
      tag.remove();
    },
  };
})();
