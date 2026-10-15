import streamlit as st
from agent import run

st.set_page_config(page_title="Storybook Agent", page_icon="📖")
st.title("📖 Children's Storybook Agent")
st.caption("One prompt → illustrated 5-page story outline as a PDF")

prompt = st.text_area(
    "Story prompt",
    "Create a five-page children's book story outline about a young, brave character "
    "discovering a hidden, magical garden.",
    height=120,
)

if st.button("Generate book", type="primary"):
    with st.spinner("Writing story and drawing pages (1-3 minutes)..."):
        try:
            pdf_path = run(prompt, "storybook.pdf")
            with open(pdf_path, "rb") as f:
                st.success("Done!")
                st.download_button("Download PDF", f, file_name="storybook.pdf", mime="application/pdf")
        except Exception as e:
            st.error(f"Generation failed: {e}")
