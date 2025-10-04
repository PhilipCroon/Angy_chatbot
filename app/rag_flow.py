"""
Minimal, production-ready-ish RAG pipeline for clinical guidelines (AHA Chest Pain).
- Ingest one or more PDFs
- Clean + chunk (atomic, overlap-aware)
- Embed (sentence-transformers)
- Hybrid retrieval (BM25 + FAISS)
- Compose an answer with a guideline-grounded prompt (OpenAI API optional)

Usage (after installing requirements):
    python aha_chest_pain_rag_minimal.py \
        --pdfs /path/to/aha_slide_set.pdf \
        --persist_dir ./aha_index \
        --build_index

Then query:
    python aha_chest_pain_rag_minimal.py \
        --persist_dir ./aha_index \
        --ask "ED low-risk chest pain next steps?" \
        --patient_json '{"age":45,"sex":"female","setting":"ED","ecg":"normal","hs_ctn_0h":3,"hs_ctn_1h":3,"risk_score":{"HEART":2}}'

Requirements (install):
    pip install pypdf regex rank-bm25 faiss-cpu sentence-transformers openai tiktoken

Note: Internet access is not required. You provide PDFs locally.
"""
from __future__ import annotations
import argparse
import dataclasses
import json
import os
import pickle
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

from pypdf import PdfReader
from rank_bm25 import BM25Okapi
import numpy as np

# FAISS import (faiss-cpu)
try:
    import faiss  # type: ignore
except Exception as e:  # pragma: no cover
    faiss = None

# Sentence-Transformers for embeddings
try:
    from sentence_transformers import SentenceTransformer
except Exception as e:  # pragma: no cover
    SentenceTransformer = None  # type: ignore

# Optional: OpenAI for answer composition
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


# -------------------------------
# Utilities & Data Structures
# -------------------------------

@dataclasses.dataclass
class Chunk:
    id: str
    text: str
    meta: Dict[str, Any]


def read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for i, p in enumerate(reader.pages):
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        # normalize bullets and spacing
        t = t.replace("\u2022", "- ")
        t = re.sub(r"\s+", " ", t)
        pages.append(f"[PAGE {i+1}]\n{t}\n")
    return "\n".join(pages)


def clean_text(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\uf0b7|•", "- ", s)
    s = re.sub(r"\s+", " ", s)
    # keep page anchors like [PAGE N]
    return s


def smart_sentences(s: str) -> List[str]:
    # Split while preserving clinical-ish abbreviations
    # very light heuristic; production: use nltk/spacy
    parts = re.split(r"(?<=[^A-Z].[.?]) +(?=[A-Z(\[])", s)
    # further split on bullets/line breaks
    out: List[str] = []
    for p in parts:
        for q in re.split(r"\n|\r| - ", p):
            q = q.strip()
            if q:
                out.append(q)
    return out


def chunk_text(s: str, max_chars: int = 1000, overlap: int = 150) -> List[str]:
    sentences = smart_sentences(s)
    chunks: List[str] = []
    cur = ""
    for sent in sentences:
        # keep page anchors if present
        if len(cur) + len(sent) + 1 <= max_chars:
            cur = (cur + " " + sent).strip()
        else:
            if cur:
                chunks.append(cur)
            # start next with overlap tail
            tail = cur[-overlap:] if overlap > 0 else ""
            cur = (tail + " " + sent).strip()
    if cur:
        chunks.append(cur)
    return chunks


def tag_metadata(text: str, guideline_id: str) -> Dict[str, Any]:
    # Lightweight heuristics to tag care setting & section
    section = "General"
    if re.search(r"\bED\b|Emergency Department|Acute", text, re.I):
        section = "ED Pathway"
    if re.search(r"Outpatient|Ambulatory|Stable chest pain", text, re.I):
        section = "Outpatient Pathway"
    if re.search(r"Top 10|Take-Home|Key Messages", text, re.I):
        section = "Top10"
    # Optional COR/LOE extraction (naive)
    cor = None
    m = re.search(r"Class of Recommendation:?\s*(I{1,3}|IIa|IIb|III)", text, re.I)
    if m:
        cor = m.group(1).upper()
    loe = None
    m2 = re.search(r"Level of Evidence:?\s*(A|B-?R|B-?NR|C-?LD|C-?EO)", text, re.I)
    if m2:
        loe = m2.group(1).upper()

    meta = {
        "guideline_id": guideline_id,
        "section": section,
        "class_of_recommendation": cor,
        "level_of_evidence": loe,
    }
    return meta


def build_chunks_from_pdfs(pdf_paths: List[Path], guideline_id: str) -> List[Chunk]:
    chunks: List[Chunk] = []
    for path in pdf_paths:
        raw = read_pdf(path)
        raw = clean_text(raw)
        parts = chunk_text(raw)
        for i, c in enumerate(parts):
            meta = tag_metadata(c, guideline_id)
            meta.update({"source_file": str(path.name)})
            chunks.append(Chunk(id=f"{path.stem}-{i}", text=c, meta=meta))
    return chunks


# -------------------------------
# Embedding + Vector Store (FAISS)
# -------------------------------

class Embedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers not installed. pip install sentence-transformers")
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: List[str]) -> np.ndarray:
        return np.array(self.model.encode(texts, show_progress_bar=True, convert_to_numpy=True), dtype="float32")


@dataclasses.dataclass
class HybridIndex:
    faiss_index: Any
    faiss_dim: int
    bm25: BM25Okapi
    corpus: List[str]
    metas: List[Dict[str, Any]]
    ids: List[str]

    def save(self, dirpath: Path):
        dirpath.mkdir(parents=True, exist_ok=True)
        # save FAISS
        faiss_path = dirpath / "faiss.index"
        if faiss is None:
            raise RuntimeError("faiss not available")
        faiss.write_index(self.faiss_index, str(faiss_path))
        # save BM25 + metas
        with open(dirpath / "meta.pkl", "wb") as f:
            pickle.dump({
                "corpus": self.corpus,
                "metas": self.metas,
                "ids": self.ids,
                "faiss_dim": self.faiss_dim,
            }, f)

    @staticmethod
    def load(dirpath: Path) -> "HybridIndex":
        if faiss is None:
            raise RuntimeError("faiss not available")
        with open(dirpath / "meta.pkl", "rb") as f:
            meta = pickle.load(f)
        faiss_index = faiss.read_index(str(dirpath / "faiss.index"))
        tokenized = [doc.split() for doc in meta["corpus"]]
        bm25 = BM25Okapi(tokenized)
        return HybridIndex(
            faiss_index=faiss_index,
            faiss_dim=meta["faiss_dim"],
            bm25=bm25,
            corpus=meta["corpus"],
            metas=meta["metas"],
            ids=meta["ids"],
        )


def build_index(chunks: List[Chunk], embedder: Embedder) -> HybridIndex:
    texts = [c.text for c in chunks]
    metas = [c.meta for c in chunks]
    ids = [c.id for c in chunks]

    # BM25 corpus
    tokenized = [t.split() for t in texts]
    bm25 = BM25Okapi(tokenized)

    # FAISS index
    if faiss is None:
        raise RuntimeError("faiss not available: pip install faiss-cpu")
    vectors = embedder.encode(texts)
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    # normalize for cosine sim
    faiss.normalize_L2(vectors)
    index.add(vectors)

    return HybridIndex(index, dim, bm25, texts, metas, ids)


# -------------------------------
# Retrieval
# -------------------------------

def hybrid_search(index: HybridIndex, embedder: Embedder, query: str, k: int = 8, alpha: float = 0.5,
                  filters: Dict[str, Any] | None = None) -> List[Tuple[float, str, Dict[str, Any]]]:
    """Hybrid = alpha * dense + (1-alpha) * sparse. Returns [(score, text, meta), ...]."""
    # Sparse
    bm25_scores = index.bm25.get_scores(query.split())

    # Dense
    qvec = embedder.encode([query])
    faiss.normalize_L2(qvec)
    dense_scores, dense_ids = index.faiss_index.search(qvec, len(index.corpus))
    dense_scores = dense_scores[0]

    # Combine
    combined = []
    for i, (text, meta, cid) in enumerate(zip(index.corpus, index.metas, index.ids)):
        if filters:
            ok = True
            for kf, vf in filters.items():
                if meta.get(kf) != vf:
                    ok = False
                    break
            if not ok:
                continue
        dscore = dense_scores[i]
        sscore = bm25_scores[i]
        # normalize sparse by max
        sscore_norm = sscore / (np.max(bm25_scores) + 1e-9)
        score = alpha * dscore + (1 - alpha) * sscore_norm
        combined.append((score, text, meta))

    combined.sort(key=lambda x: x[0], reverse=True)
    return combined[:k]


# -------------------------------
# Answer composition (prompt + optional OpenAI call)
# -------------------------------

GUIDELINE_SYSTEM_PROMPT = (
    "You are a clinical copilot. Only use the retrieved AHA/ACC chest pain guideline excerpts. "
    "Cite Class of Recommendation (COR) and Level of Evidence (LOE) if available in the text. "
    "If guidance is unclear or out of scope, say so. Provide next-step actions as bullet verbs."
)


def format_context(hits: List[Tuple[float, str, Dict[str, Any]]]) -> str:
    blocks = []
    for score, text, meta in hits:
        cor = meta.get("class_of_recommendation")
        loe = meta.get("level_of_evidence")
        tag = f"[Section: {meta.get('section','General')}, COR: {cor or '—'}, LOE: {loe or '—'}]"
        blocks.append(tag + "\n" + text)
    return "\n\n".join(blocks)


def compose_answer(query: str, patient_json: Dict[str, Any] | None, context: str, use_openai: bool = False,
                   model: str = "gpt-4o-mini") -> str:
    user_prompt = (
        f"Question: {query}\n"
        f"Patient context (JSON): {json.dumps(patient_json or {}, ensure_ascii=False)}\n\n"
        f"Evidence (do not hallucinate outside this):\n{context}\n\n"
        "Write a concise plan with Assessment, Next steps, and Evidence lines referring to sections above."
    )

    if use_openai:
        if OpenAI is None:
            raise RuntimeError("openai package not installed. pip install openai")
        client = OpenAI()
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": GUIDELINE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return completion.choices[0].message.content
    else:
        # Fallback: Just return the context and a templated plan stub
        return (
            "ASSESSMENT (stub): Based on retrieved AHA/ACC chest pain guidance.\n\n"
            "NEXT STEPS (stub): Use clinical decision pathways; if low risk and serial hs-cTn unchanged with normal ECG, urgent cardiac testing is typically not indicated.\n\n"
            "EVIDENCE (context excerpts):\n" + context
        )


# -------------------------------
# CLI
# -------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", nargs="*", help="Paths to guideline PDFs (e.g., AHA slide set)")
    ap.add_argument("--persist_dir", required=True, help="Directory to save/load the index")
    ap.add_argument("--build_index", action="store_true", help="Build index from PDFs")
    ap.add_argument("--ask", type=str, help="Question to query the guideline")
    ap.add_argument("--patient_json", type=str, default=None, help="Patient context JSON")
    ap.add_argument("--alpha", type=float, default=0.6, help="Hybrid weight: dense share [0..1]")
    ap.add_argument("--k", type=int, default=6, help="Top-k passages")
    ap.add_argument("--use_openai", action="store_true", help="Call OpenAI to compose answer")
    ap.add_argument("--openai_model", type=str, default="gpt-4o-mini")
    ap.add_argument("--embed_model", type=str, default="sentence-transformers/all-MiniLM-L6-v2")
    args = ap.parse_args()

    persist_dir = Path(args.persist_dir)

    embedder = Embedder(model_name=args.embed_model)

    if args.build_index:
        if not args.pdfs:
            print("--build_index requires --pdfs paths", file=sys.stderr)
            sys.exit(2)
        paths = [Path(p) for p in args.pdfs]
        chunks = build_chunks_from_pdfs(paths, guideline_id="AHA_ACC_ChestPain_2021")
        index = build_index(chunks, embedder)
        index.save(persist_dir)
        print(f"Saved index with {len(index.corpus)} chunks to {persist_dir}")
        return

    # load and query
    index = HybridIndex.load(persist_dir)

    if not args.ask:
        print("Provide --ask to query the index.")
        return

    pjson = json.loads(args.patient_json) if args.patient_json else None

    # Simple filter example: route by care setting if present
    filt = None
    if pjson and "setting" in pjson and pjson["setting"]:
        if str(pjson["setting"]).lower().startswith("ed"):
            filt = {"section": "ED Pathway"}
        elif str(pjson["setting"]).lower().startswith("out"):
            filt = {"section": "Outpatient Pathway"}

    hits = hybrid_search(index, embedder, args.ask, k=args.k, alpha=args.alpha, filters=filt)
    context = format_context(hits)
    answer = compose_answer(args.ask, pjson, context, use_openai=args.use_openai, model=args.openai_model)

    print("\n=== ANSWER ===\n")
    print(answer)


if __name__ == "__main__":
    main()
