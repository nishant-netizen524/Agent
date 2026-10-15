"""
Children's Storybook Agent
--------------------------
One prompt in -> illustrated 5-page children's story outline (PDF) out.

Pipeline:
  1. Story planner (LLM)   -> JSON: character sheet + 5 pages
  2. Reference image       -> one canonical picture of the main character
  3. Page illustrations    -> each page is generated WITH the reference image attached
                              + the identical character sheet text (consistency)
  4. PDF builder (fpdf2)   -> clean 5-page downloadable PDF

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  python agent.py "your prompt here" -o storybook.pdf
"""
from urllib.parse import quote 
import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from fpdf import FPDF

API_URL = "https://openrouter.ai/api/v1/chat/completions"
# Model slugs are configurable: check openrouter.ai/models if a slug has changed.
TEXT_MODEL = os.getenv("TEXT_MODEL", "google/gemini-2.5-flash")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "google/gemini-2.5-flash-image")

NUM_PAGES = 5

PLANNER_SYSTEM = f"""You are a children's picture-book author and art director.
Given a prompt, return ONLY valid JSON (no markdown fences) with this exact shape:
{{
  "title": "short book title",
  "art_style": "one sentence describing a single consistent illustration style, e.g. soft watercolor, warm colors, rounded shapes",
  "character": {{
    "name": "...",
    "description": "ONE dense paragraph with exact visual details: age, skin tone, hair style and color, eye color, exact clothing items with exact colors, one signature accessory. This text will be pasted into every image prompt, so be specific and concrete."
  }},
  "pages": [
    {{"page": 1, "heading": "short heading", "text": "2-3 simple sentences for children (outline of what happens)", "scene": "what the illustration shows: setting, character's pose and action, mood, key objects"}}
    // exactly {NUM_PAGES} pages, forming a clear beginning, middle and end
  ]
}}
Rules: the main character must appear in every scene; keep the language simple and warm;
the character description must never change between pages."""


def _headers():
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_API_KEY first (export OPENROUTER_API_KEY=...).")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _post(payload, retries=3):
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(API_URL, headers=_headers(), json=payload, timeout=180)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:300]}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"OpenRouter request failed: {last}")


# ---------- 1. Story planner ----------
def plan_story(prompt: str) -> dict:
    data = _post({
        "model": TEXT_MODEL,
        "max_tokens": 3000,
        "messages": [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    })
    raw = data["choices"][0]["message"]["content"]
    raw = re.sub(r"```(?:json)?", "", raw)
    story = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    if len(story.get("pages", [])) != NUM_PAGES:
        raise ValueError(f"Planner returned {len(story.get('pages', []))} pages, expected {NUM_PAGES}")
    return story


# ---------- 2/3. Image generation ----------
def _b64_to_file(data_url: str, path: Path):
    path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))


def _file_to_data_url(path: Path) -> str:
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def generate_image(text_prompt: str, out_path: Path, reference: Path | None = None, retries=3):
    if os.getenv("IMAGE_BACKEND") == "free":
        url = "https://image.pollinations.ai/prompt/" + quote(text_prompt[:1500])
        for attempt in range(retries):
            r = requests.get(url, params={"width": 1024, "height": 1024, "seed": 42, "nologo": "true"}, timeout=180)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                out_path.write_bytes(r.content)
                return out_path
            time.sleep(3)
        raise RuntimeError("Free image backend failed")
    content = [{"type": "text", "text": text_prompt}]
    if reference:
        content.append({"type": "image_url", "image_url": _file_to_data_url(reference)})
    payload = {
        "model": IMAGE_MODEL,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
    }
    for attempt in range(retries):
        data = _post(payload)
        msg = data["choices"][0]["message"]
        images = msg.get("images") or []
        if images:
            _b64_to_file(images[0]["image_url"]["url"], out_path)
            return out_path
        time.sleep(2)
    raise RuntimeError("Image model returned no image: " + str(msg.get("content"))[:200])


def make_illustrations(story: dict, workdir: Path) -> list[Path]:
    style = story["art_style"]
    char = story["character"]
    char_block = f"MAIN CHARACTER ({char['name']}): {char['description']}"

    print("Generating character reference image...")
    ref = workdir / "character_ref.png"
    generate_image(
        f"Children's book character reference. Style: {style}. {char_block} "
        "Show the character full-body, facing the viewer, on a plain light background. "
        "No text, no letters, no watermark.",
        ref,
    )

    paths = []
    for p in story["pages"]:
        print(f"Generating illustration for page {p['page']}...")
        out = workdir / f"page_{p['page']}.png"
        prompt = (
            f"Children's book illustration. Style: {style}. "
            f"{char_block} "
            "The attached image is the character reference: draw EXACTLY the same character "
            "(same face, hair, skin tone, outfit and colors, same proportions and art style). "
            f"Scene: {p['scene']} "
            "Square composition. No text, no letters, no watermark."
        )
        try:
            generate_image(prompt, out, reference=ref)
        except Exception as e:  # fall back to the reference so the PDF still builds
            print(f"  ! page {p['page']} failed ({e}); using reference image instead")
            out = ref
        paths.append(out)
    return paths


# ---------- 4. PDF ----------
def _clean(s: str) -> str:
    """fpdf2 core fonts are latin-1 only; normalise common unicode punctuation."""
    rep = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
           "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " "}
    for k, v in rep.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def build_pdf(story: dict, images: list[Path], out_pdf: Path):
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)
    W = 210
    for i, p in enumerate(story["pages"]):
        pdf.add_page()
        pdf.set_fill_color(255, 249, 235)
        pdf.rect(0, 0, 210, 297, "F")
        y = 14
        if i == 0:
            pdf.set_font("Helvetica", "B", 26)
            pdf.set_text_color(60, 40, 90)
            pdf.set_xy(15, y)
            pdf.multi_cell(W - 30, 12, _clean(story["title"]), align="C")
            y = pdf.get_y() + 2
            pdf.set_font("Helvetica", "I", 11)
            pdf.set_text_color(120, 100, 140)
            pdf.set_xy(15, y)
            pdf.cell(W - 30, 6, _clean(f"Starring {story['character']['name']}"), align="C")
            y += 12
        size = 150 if i == 0 else 165
        pdf.image(str(images[i]), x=(W - size) / 2, y=y, w=size, h=size)
        y += size + 8
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(60, 40, 90)
        pdf.set_xy(20, y)
        pdf.cell(W - 40, 8, _clean(p["heading"]), align="C")
        y += 11
        pdf.set_font("Helvetica", "", 13)
        pdf.set_text_color(50, 50, 50)
        pdf.set_xy(20, y)
        pdf.multi_cell(W - 40, 7, _clean(p["text"]), align="C")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(150, 150, 150)
        pdf.set_xy(0, 285)
        pdf.cell(W, 5, f"- {p['page']} -", align="C")
    pdf.output(str(out_pdf))


def run(prompt: str, out_pdf: str = "storybook.pdf", workdir: str = "output") -> Path:
    wd = Path(workdir)
    wd.mkdir(exist_ok=True)
    print("Planning story...")
    story = plan_story(prompt)
    (wd / "story.json").write_text(json.dumps(story, indent=2))
    images = make_illustrations(story, wd)
    out = Path(out_pdf)
    build_pdf(story, images, out)
    print(f"Done -> {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("-o", "--out", default="storybook.pdf")
    args = ap.parse_args()
    run(args.prompt, args.out)
