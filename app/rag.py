import os
import re
from typing import List
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import settings
from .schemas import RAGChunk

# Light cross-lingual hint map so Hindi/Hinglish/Spanish queries match English KB sections cleanly.
CROSS_LINGUAL_HINTS = {
    "kya": "",
    "kitna": "price cost pricing plan",
    "kharcha": "price cost pricing",
    "paisa": "price cost pricing",
    "daam": "price cost pricing",
    "kimat": "price cost pricing",
    "keemat": "price cost pricing",
    "rupay": "price pricing",
    "sasta": "starter discount pricing",
    "discount": "discount annual volume",
    "chhoot": "discount",
    "suraksha": "security encryption compliance soc2",
    "safe": "security compliance encryption",
    "data": "security privacy residency encryption",
    "jod": "integration sync crm api",
    "crm": "crm hubspot salesforce zoho pipedrive sync",
    "calendar": "calendar appointment booking slot",
    "meeting": "calendar appointment demo booking",
    "demo": "demo trial onboarding case study",
    "fayda": "roi savings case study conversion",
    "precio": "price cost pricing plan",
    "seguridad": "security compliance encryption",
    "integracion": "integration crm api webhook",
    "reunion": "calendar appointment demo",
}


class KnowledgeBaseRAG:
    def __init__(self, kb_dir: str | None = None):
        self.kb_dir = kb_dir or settings.kb_dir
        self.chunks: List[RAGChunk] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None
        self.reload()

    def reload(self) -> int:
        self.chunks = self._load_and_chunk_docs()
        if not self.chunks:
            self.vectorizer = None
            self.matrix = None
            return 0

        corpus = [f"{c.title} {c.section} {c.content}" for c in self.chunks]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
        self.matrix = self.vectorizer.fit_transform(corpus)
        return len(self.chunks)

    def _load_and_chunk_docs(self) -> List[RAGChunk]:
        chunks: List[RAGChunk] = []
        if not os.path.isdir(self.kb_dir):
            return chunks

        for fname in sorted(os.listdir(self.kb_dir)):
            if not fname.endswith((".md", ".txt")):
                continue
            fpath = os.path.join(self.kb_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                continue

            doc_title = fname.replace("_", " ").replace(".md", "").replace(".txt", "").title()
            lines = raw.splitlines()
            if lines and lines[0].startswith("# "):
                doc_title = lines[0][2:].strip()

            sections = re.split(r"(?m)^##\s+", raw)
            for idx, sec in enumerate(sections):
                sec = sec.strip()
                if not sec:
                    continue
                sec_lines = sec.splitlines()
                if idx == 0 and sec_lines[0].startswith("# "):
                    body = "\n".join(sec_lines[1:]).strip()
                    sec_name = "Overview"
                else:
                    sec_name = sec_lines[0].strip()
                    body = "\n".join(sec_lines[1:]).strip()

                if not body:
                    continue

                chunks.append(
                    RAGChunk(
                        doc_id=f"{fname}#{idx}",
                        title=doc_title,
                        section=sec_name,
                        content=body,
                        score=0.0,
                    )
                )
        return chunks

    def _expand_query(self, query: str) -> str:
        tokens = re.findall(r"[a-zA-Z0-9_]+", query.lower())
        extra = [CROSS_LINGUAL_HINTS[t] for t in tokens if t in CROSS_LINGUAL_HINTS]
        if any("\u0900" <= ch <= "\u097f" for ch in query):
            if any(w in query for w in ("दाम", "कीमत", "पैसा", "प्लान", "प्राइस", "खर्च")):
                extra.append("price cost pricing plan discount")
            if any(w in query for w in ("सुरक्षा", "सिक्योरिटी", "डेटा", "प्राइवेसी")):
                extra.append("security compliance encryption privacy")
            if any(w in query for w in ("सीआरएम", "इंटीग्रेशन", "सिंक", "कैलेंडर")):
                extra.append("crm integration sync calendar webhook")
        return f"{query} {' '.join(extra)}".strip()

    def retrieve(self, query: str, top_k: int = 3, min_score: float = 0.05) -> List[RAGChunk]:
        if not self.chunks or self.vectorizer is None or self.matrix is None:
            return []

        expanded = self._expand_query(query)
        q_vec = self.vectorizer.transform([expanded])
        sims = cosine_similarity(q_vec, self.matrix).flatten()

        # Slight keyword overlap boost so exact product terms (e.g., SOC 2, HubSpot, $49) rank cleanly.
        q_words = set(re.findall(r"[a-z0-9]{3,}", expanded.lower()))
        boosted = np.copy(sims)
        for i, chunk in enumerate(self.chunks):
            c_text = f"{chunk.title} {chunk.section} {chunk.content}".lower()
            overlap = sum(1 for w in q_words if w in c_text)
            boosted[i] += min(overlap * 0.03, 0.15)

        ranked_idx = np.argsort(boosted)[::-1][:top_k]
        results: List[RAGChunk] = []
        for idx in ranked_idx:
            score = float(boosted[idx])
            if score < min_score:
                continue
            chunk = self.chunks[idx]
            results.append(
                RAGChunk(
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    section=chunk.section,
                    content=chunk.content,
                    score=round(min(score, 0.99), 3),
                )
            )
        return results

    def add_document(self, filename: str, content: str) -> int:
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        os.makedirs(self.kb_dir, exist_ok=True)
        path = os.path.join(self.kb_dir, safe_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")
        return self.reload()
