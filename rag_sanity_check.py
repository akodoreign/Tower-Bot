from pathlib import Path
import textwrap

import tower_rag


def main():
    print("=== RAG Sanity Check ===\n")

    # 1) Check DOCS_DIR
    docs_dir = tower_rag.DOCS_DIR
    print(f"DOCS_DIR: {docs_dir}")
    print(f"Exists?  {docs_dir.exists()}")
    if docs_dir.exists():
        txt_files = list(docs_dir.glob("**/*.txt"))
        print(f"\nFound {len(txt_files)} .txt file(s) under campaign_docs:")
        for p in txt_files:
            print(" -", p.relative_to(docs_dir))
    else:
        print("\ncampaign_docs folder NOT found where tower_rag expects it.")
        print("Make sure you have:")
        print("  <project_root>/campaign_docs/*.txt")
        return

    # 2) Try TF-IDF retrieval on a lore keyword
    print("\n=== TF-IDF retrieval test: 'Lotus Guild' ===")
    chunks = tower_rag.get_relevant_chunks("Lotus Guild", top_k=3)
    print("Retrieved chunks:", len(chunks))

    for i, ch in enumerate(chunks, 1):
        preview = textwrap.shorten(ch.replace("\\n", " "), width=300, placeholder=" ...")
        print(f"\n--- Chunk {i} ---")
        print(preview)

    # 3) Build system context like the bot does
    print("\n=== build_context_from_messages() test ===")
    messages = [{"role": "user", "content": "Tell me about the Lotus Guild"}]
    ctx = tower_rag.build_context_from_messages(messages)

    if not ctx:
        print("Context builder returned an EMPTY string.")
    else:
        print("Context length:", len(ctx))
        print("\nContext preview (first 1000 chars):\n")
        print(ctx[:1000])
        print("\n[..truncated..]")


if __name__ == "__main__":
    main()
