"""One-off probe script: fires the 10 questions from the task brief at the live
/chat endpoint and prints real latency/status/citation-count/trace-length so we can
see actual local-model behavior, not assumptions."""
import json
import time
import urllib.request

QUESTIONS = [
    "Explain the architecture of this repository.",
    "Where is code intelligence implemented?",
    "Where is hybrid retrieval implemented?",
    "How does indexing work?",
    "What is the purpose of the retrieval benchmark?",
    "Which files implement the agent state machine?",
    "What are the main dependencies between the RAG and agent packages?",
    "What happens when an LLM provider is unavailable?",
    "Trace the flow of a /chat request.",
    "What are the current limitations of the application?",
]


def ask(q: str) -> dict:
    body = json.dumps({"repository_id": 1, "message": q}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/api/v1/chat", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    data["_wall_s"] = round(time.monotonic() - t0, 1)
    return data


if __name__ == "__main__":
    for q in QUESTIONS:
        r = ask(q)
        print(f"\nQ: {q}")
        print(f"  status={r['status']} wall={r['_wall_s']}s server_latency_ms={r['latency_ms']} "
              f"tool_calls={len(r['trace'])} citations={len(r['citations'])}")
        print(f"  A: {r['answer'][:220]}")
