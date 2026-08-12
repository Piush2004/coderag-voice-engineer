"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

type Repo = { id: number; name: string; root_path: string };
type ChatTurn = {
  role: "user" | "assistant";
  content: string;
  citations?: { file: string; lines?: string; symbol?: string | null }[];
  trace?: string[];
  status?: string;
};

export default function VoiceConsole() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState<number | null>(null);
  const [newRepoPath, setNewRepoPath] = useState("");
  const [newRepoName, setNewRepoName] = useState("");
  const [indexing, setIndexing] = useState(false);
  const [indexResult, setIndexResult] = useState<string | null>(null);

  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<any>(null);
  const conversationIdRef = useRef<number | null>(null);

  useEffect(() => {
    fetchRepos();
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    setVoiceSupported(!!SpeechRecognition);
  }, []);

  async function fetchRepos() {
    try {
      const res = await fetch(`${API_BASE}/api/v1/repositories`);
      setRepos(await res.json());
    } catch {
      // backend not reachable yet; user sees the empty state
    }
  }

  async function indexRepo() {
    if (!newRepoPath.trim()) return;
    setIndexing(true);
    setIndexResult(null);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/repositories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newRepoName || newRepoPath, root_path: newRepoPath }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Indexing failed");
      setIndexResult(
        `Indexed ${data.files_indexed} files (${data.files_parsed} parsed), ${data.chunks_indexed} chunks, ${data.commits_indexed} commits.`
      );
      await fetchRepos();
      setRepoId(data.repository_id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setIndexing(false);
    }
  }

  async function sendMessage(text: string) {
    if (!text.trim() || !repoId || busy) return;
    setTurns((t) => [...t, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repository_id: repoId,
          message: text,
          conversation_id: conversationIdRef.current,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      conversationIdRef.current = data.conversation_id;
      const turn: ChatTurn = {
        role: "assistant",
        content: data.answer,
        citations: data.citations,
        trace: data.trace,
        status: data.status,
      };
      setTurns((t) => [...t, turn]);
      speak(data.answer);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function speak(text: string) {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text.replace(/CONFIRMED:|INFERRED:|UNKNOWN:/g, ""));
    window.speechSynthesis.speak(utter);
  }

  function stopSpeaking() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  function toggleListening() {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    stopSpeaking();
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onresult = (event: any) => {
      const transcript = Array.from(event.results)
        .map((r: any) => r[0].transcript)
        .join("");
      setInput(transcript);
      if (event.results[event.results.length - 1].isFinal) {
        sendMessage(transcript);
      }
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <header className="border-b border-zinc-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">CodeRAG Voice Engineer</h1>
          <p className="text-xs text-zinc-500">Voice-first repository intelligence</p>
        </div>
        <select
          className="bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-sm"
          value={repoId ?? ""}
          onChange={(e) => {
            setRepoId(Number(e.target.value) || null);
            conversationIdRef.current = null;
            setTurns([]);
          }}
        >
          <option value="">Select repository...</option>
          {repos.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
      </header>

      <div className="max-w-4xl mx-auto p-6 grid gap-6">
        <section className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <h2 className="text-sm font-medium text-zinc-300 mb-2">Index a repository</h2>
          <div className="flex gap-2 flex-wrap">
            <input
              className="flex-1 min-w-[200px] bg-zinc-950 border border-zinc-700 rounded px-3 py-2 text-sm"
              placeholder="Local path, e.g. D:\path\to\repo"
              value={newRepoPath}
              onChange={(e) => setNewRepoPath(e.target.value)}
            />
            <input
              className="w-40 bg-zinc-950 border border-zinc-700 rounded px-3 py-2 text-sm"
              placeholder="Name (optional)"
              value={newRepoName}
              onChange={(e) => setNewRepoName(e.target.value)}
            />
            <button
              onClick={indexRepo}
              disabled={indexing}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded px-4 py-2 text-sm font-medium"
            >
              {indexing ? "Indexing..." : "Index"}
            </button>
          </div>
          {indexResult && <p className="text-xs text-emerald-400 mt-2">{indexResult}</p>}
        </section>

        <section className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 min-h-[400px] flex flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto max-h-[50vh]">
            {turns.length === 0 && (
              <p className="text-zinc-500 text-sm">
                {repoId
                  ? 'Try: "Explain the architecture" or "Where is retrieval implemented?"'
                  : "Index or select a repository to begin."}
              </p>
            )}
            {turns.map((t, i) => (
              <div key={i} className={t.role === "user" ? "text-right" : ""}>
                <div
                  className={
                    "inline-block max-w-[85%] rounded-lg px-3 py-2 text-sm text-left whitespace-pre-wrap " +
                    (t.role === "user" ? "bg-indigo-600" : "bg-zinc-800")
                  }
                >
                  {t.content}
                </div>
                {t.trace && t.trace.length > 0 && (
                  <div className="text-xs text-zinc-500 mt-1 text-left">
                    {t.trace.map((line, j) => (
                      <div key={j}>· {line}</div>
                    ))}
                  </div>
                )}
                {t.citations && t.citations.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1 text-left">
                    {t.citations.slice(0, 6).map((c, j) => (
                      <span
                        key={j}
                        className="text-[10px] font-mono bg-zinc-800 border border-zinc-700 rounded px-1.5 py-0.5 text-zinc-400"
                      >
                        {c.file}
                        {c.lines ? `:${c.lines}` : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {busy && <p className="text-xs text-zinc-500">Agent is investigating...</p>}
          </div>

          {error && <p className="text-xs text-red-400 mt-2">{error}</p>}

          <div className="flex items-center gap-2 mt-4 pt-4 border-t border-zinc-800">
            <button
              onClick={toggleListening}
              disabled={!voiceSupported || !repoId}
              title={voiceSupported ? "Push to talk" : "Voice not supported in this browser"}
              className={
                "w-10 h-10 rounded-full flex items-center justify-center disabled:opacity-30 " +
                (listening ? "bg-red-600 animate-pulse" : "bg-zinc-800 hover:bg-zinc-700")
              }
            >
              🎙
            </button>
            <input
              className="flex-1 bg-zinc-950 border border-zinc-700 rounded px-3 py-2 text-sm"
              placeholder="Ask about this repository..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendMessage(input)}
              disabled={!repoId}
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!repoId || busy}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded px-4 py-2 text-sm font-medium"
            >
              Send
            </button>
            <button
              onClick={stopSpeaking}
              className="text-xs text-zinc-500 hover:text-zinc-300 px-2"
            >
              Stop
            </button>
          </div>
          {!voiceSupported && (
            <p className="text-[11px] text-zinc-600 mt-1">
              Voice input needs a browser with SpeechRecognition (Chrome/Edge). Text still
              works everywhere.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
