# Children's Storybook Agent

Takes a single prompt and produces an illustrated 5-page children's story outline as a downloadable PDF, with the main character kept visually consistent on every page.

## Setup

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-...      # Windows: set OPENROUTER_API_KEY=...
python agent.py "Create a five-page children's book story outline about a young, brave character discovering a hidden, magical garden." -o storybook.pdf
# optional UI may crash on Windows
streamlit run app.py
```

Models are set by env vars `TEXT_MODEL` (default `google/gemini-2.5-flash`) and `IMAGE_MODEL` (default `google/gemini-2.5-flash-image`).

## How it works

1. **Story planner (LLM):** returns JSON with a title, one art style, a detailed character sheet, and 5 pages (heading, text, scene).
2. **Reference image:** one canonical full-body picture of the character is generated first.
3. **Page illustrations:** every page is generated with (a) the same art style string, (b) the character sheet copied word for word, and (c) the reference image attached as input.
4. **PDF builder (fpdf2):** title on page 1, then image + heading + text per page. Exactly 5 pages.

## Consistency approach

Text-only repetition of the character sheet plus an image reference passed to every page call. This is far more stable than prompting alone.

## Limitations

- Consistency is strong but not perfect; small details (e.g., accessories) can drift.
- Image quality and speed depend on the OpenRouter model used.
- If an image call fails after retries, that page falls back to the reference image so the PDF still builds.
