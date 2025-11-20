"use client";

import { useState, useEffect, useRef } from 'react';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Card from "@/components/ui/card";

const LoadingDots = () => (
  <div className="flex space-x-1 items-end h-5">
    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" />
  </div>
);

export default function ChatPage() {
  const { status } = useSession();
  const router = useRouter();
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);

  // Holds the current assistant response while streaming
  const currentAssistantRef = useRef("");
  // Ref to the scrollable container so we can auto-scroll on new messages
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/auth/signin');
    }
  }, [status, router]);

  // Auto-scroll to the bottom whenever messages change
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p>Loading...</p>
      </div>
    );
  }

  if (status === 'unauthenticated') {
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = { role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setLoading(true);
    currentAssistantRef.current = "";

    try {
      const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          input: userMessage.content,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to get chat response");
      }

      if (!response.body) {
        throw new Error("No response body from chat service");
      }

      // Insert a placeholder assistant message that we'll update as chunks arrive
      setMessages(prev => [...prev, { role: 'assistant', content: "" }]);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      let done = false;

      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (!value) continue;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;

          const dataStr = line.replace("data:", "").trim();
          if (!dataStr || dataStr === "[DONE]") continue;

          let data: any;
          try {
            data = JSON.parse(dataStr);
          } catch (err) {
            console.error("Failed to parse SSE chunk", err, dataStr);
            continue;
          }

          if (data.type === "error") {
            throw new Error(
              data.message || "An error occurred while processing your message."
            );
          }

          if (data.type === "completed" && data.conversation_id) {
            setConversationId(data.conversation_id);
            continue;
          }

          if (data.type === "delta" && typeof data.content === "string") {
            currentAssistantRef.current += data.content;

            // Update the last assistant message
            setMessages(prev => {
              const updated = [...prev];
              if (updated.length === 0) return updated;
              const last = updated[updated.length - 1];
              if (last.role === "assistant") {
                last.content = currentAssistantRef.current;
              }
              return updated;
            });
          }
        }
      }
    } catch (error) {
      console.error("Chat failed", error);
      const message =
        error instanceof Error
          ? error.message
          : "Failed to connect to chat service";

      setMessages(prev => [
        ...prev,
        {
          role: "assistant",
          content: `Error: ${message}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="py-6 h-[calc(100vh-64px)] flex flex-col min-h-0">
      <div className="mx-auto w-full max-w-5xl px-4 flex-1 min-h-0 flex flex-col gap-4">
        <Card className="flex-1 min-h-0 flex flex-col p-4 overflow-hidden">
          <div
            ref={scrollContainerRef}
            className="flex-1 min-h-0 overflow-y-auto space-y-4 mb-4"
          >
            {messages.length === 0 ? (
              <div className="h-full flex items-center justify-center text-gray-500">
                Start a new chat...
              </div>
            ) : (
              messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex ${
                    msg.role === "user" ? "justify-end" : "justify-start"
                  }`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg px-4 py-2 prose-sm ${
                      msg.role === "user"
                        ? "bg-blue-600 text-white"
                        : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    {msg.role === "assistant" ? (
                      msg.content ? (
                        <div className="prose prose-sm max-w-none">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        loading && <LoadingDots />
                      )
                    ) : (
                      msg.content
                    )}
                  </div>
                </div>
              ))
            )}
            {/* If last message is user and we're waiting on a reply, show loading bubble */}
            {loading &&
              (messages.length === 0 ||
                messages[messages.length - 1]?.role === "user") && (
                <div className="flex justify-start">
                  <div className="max-w-[80%] rounded-lg px-4 py-2 bg-gray-100 text-gray-800">
                    <LoadingDots />
                  </div>
                </div>
              )}
          </div>

          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type your message..."
              disabled={loading}
            />
            <button
              type="submit"
              className="bg-blue-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              disabled={loading || !input.trim()}
            >
              Send
            </button>
          </form>
        </Card>
      </div>
    </section>
  );
}
