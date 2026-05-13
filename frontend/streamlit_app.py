"""Streamlit frontend for ReportForge."""


def main() -> None:
    """Run the Streamlit app."""
    try:
        import streamlit as st  # type: ignore[import-not-found]
    except ImportError:
        print("Streamlit is not installed. Run with the project extras when available.")
        return

    st.title("ReportForge")
    st.text_input("Research topic")
    st.selectbox("Report type", ["Market Research", "Company Profile", "Technical Report"])
    st.selectbox("Provider", ["gemini", "groq", "ollama"])
    st.file_uploader("Upload documents", accept_multiple_files=True)
    st.button("Generate report")


if __name__ == "__main__":
    main()
