"""Assistant service: the conversation-side business logic, engine-adjacent.

This module is the answer to "why does the HTTP layer know how memory
works?" · it shouldn't. Everything here used to live inside the FastAPI
handlers; now the daemon and any future surface (a TUI, a bot) call the same
service functions, and the HTTP layer is what it should be: transport.

Three responsibilities:
  * chat-native intent: "…기억해줘" → a real vault write, no tool-calling
  * follow-up repair: anaphoric turns retrieve on recent context
  * grounded chat turns: retrieval → cited system prompt → session capture
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("lemory.assistant")


def remember_intent(text: str) -> str | None:
    """Chat-native write path: '기억해줘: 환불은 큐로' / '…라고 기억해' →
    the content to save, else None. Rule-based on purpose · works with a
    small on-device brain that can't be trusted with tool-calling."""
    t = text.strip()
    m = re.match(r"^(?:기억해\s*줘?|저장해\s*줘?|메모해\s*줘?|remember)\s*[:,]?\s*(.+)$", t,
                 re.IGNORECASE | re.DOTALL)
    if m and len(m.group(1).strip()) >= 4:
        return m.group(1).strip()
    m = re.match(r"^(.+?)\s*(?:이?라고|고|을|를)?\s*(?:기억해\s*줘?|저장해\s*줘?|메모해\s*줘?)\.?$", t,
                 re.DOTALL)
    if m and len(m.group(1).strip()) >= 8:
        return m.group(1).strip()
    return None


_ANAPHORA = ("그거", "그건", "그때", "그게", "그 ", "이거", "이건", "아까", "방금",
             "걔", "쟤", "거기", "it ", "that ", "this ")


def contextual_query(question: str, msgs: list[dict]) -> str:
    """Follow-up repair: retrieval on '그건 언제였지?' alone finds nothing ·
    when the turn is short or anaphoric, retrieve on the recent conversation
    plus this one. The antecedent of '그 사람/그거' usually lives in the
    ASSISTANT's last answer (e.g. it named '김지수'), not just the user's
    previous question · so fold in both. Generation still sees the raw turn
    (history covers it)."""
    q = question.strip()
    anaphoric = len(q) <= 16 or any(q.startswith(a) or f" {a}" in f" {q}" for a in _ANAPHORA)
    if not anaphoric:
        return question
    prev_user = [m for m in msgs[:-1] if m.get("role") == "user"]
    prev_asst = [m for m in msgs[:-1] if m.get("role") == "assistant"]
    if not prev_user and not prev_asst:
        return question
    parts = []
    if prev_user:
        parts.append(str(prev_user[-1]["content"])[:160])
    if prev_asst:  # the answer that introduced the entity the user now refers to
        parts.append(str(prev_asst[-1]["content"])[:160])
    parts.append(question)
    return " ".join(parts)


def save_from_chat(engine, content: str, client: str = "assistant") -> str:
    """'기억해줘' fulfilment: write the note through the standard pipeline
    (consolidation, approval gate, event log) and return the confirmation
    text a chat surface should show."""
    try:
        path = engine.remember_note(content, client=client)
    except ValueError as e:
        return f"저장 실패: {e}"
    lines = [f"기억했습니다 → `{path}`"]
    if engine.cfg.memory_approval:
        lines.append("(승인 대기 · 건강 탭에서 승인하면 검색에 편입됩니다)")
    for r in getattr(path, "related", []):
        flag = " · 중복일 수 있음" if r.get("near_duplicate") else ""
        lines.append(f"관련 기억: [[{r['title']}]]{flag}")
    return "\n".join(lines)


@dataclass
class ChatTurn:
    """Everything a surface needs to run one grounded assistant turn."""
    system: str
    history: list[dict]
    question: str
    sources: list[dict] = field(default_factory=list)
    hits: list = field(default_factory=list)


def prepare_chat_turn(engine, msgs: list[dict], client: str = "assistant") -> ChatTurn:
    """Retrieval + prompt assembly for a chat turn. The first turn of a
    session additionally folds in the vault boot context (the pyramid's
    always-inject tier), so "요새 나 뭐 하고 있었지?" answers without
    retrieval luck."""
    from .retrieval.answer import SYSTEM, build_context

    cfg = engine.cfg
    question = str(msgs[-1]["content"])
    retrieval_q = contextual_query(question, msgs)
    hits = engine.search(retrieval_q, k=cfg.assistant_k)
    context = build_context(
        hits, store=engine.store, neighbor_chars=cfg.context_neighbor_chars,
    ) if hits else "(관련 노트를 찾지 못했습니다.)"
    system = SYSTEM + "\n\nNOTES (cite as [n]):\n" + context
    if not [m for m in msgs[:-1] if m.get("role") == "assistant"]:
        try:
            system += ("\n\nVAULT CONTEXT (배경 상황, 필요할 때만 활용):\n"
                       + engine.context(max_chars=1600))
        except Exception:
            pass
    if cfg.event_log:
        engine.store.log_event("assistant", client=client, query=question,
                               detail={"top": [h.path for h in hits[:3]]})
    if hits:
        engine.store.record_hits([h.doc_id for h in hits])
    return ChatTurn(
        system=system,
        history=[{"role": m["role"], "content": str(m["content"])} for m in msgs[:-1][-6:]],
        question=question,
        sources=[{"n": i + 1, "title": h.title, "path": h.path,
                  "snippet": h.text[:180]} for i, h in enumerate(hits)],
        hits=hits,
    )


def memory_preamble(engine, messages: list[dict], client: str = "proxy") -> str:
    """The proxy's injection block: pyramid boot + this turn's recall,
    wrapped so the upstream model knows where the memories came from."""
    parts = ["<lemory-memory>", engine.context(max_chars=1800)]
    last_user = next((str(m.get("content", "")) for m in reversed(messages)
                      if m.get("role") == "user"), "").strip()
    if last_user:
        try:
            hits = engine.search(last_user[:300], k=4, record=True, client=client)
        except Exception:
            hits = []
        if hits:
            parts.append("\n## Relevant memories (this turn)")
            parts.extend(f"- [{h.title}] {h.text[:240]}" for h in hits)
    parts.append(
        "</lemory-memory>\n위 기억은 사용자의 개인 볼트에서 왔다. 답변에 자연스럽게 "
        "활용하되, 기억에 없는 사실을 지어내지 마라.")
    return "\n".join(parts)
