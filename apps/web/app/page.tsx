"use client";

import { useEffect, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import Palette from "@/components/Palette";
import Inspector from "@/components/Inspector";
import { useStore } from "@/lib/store";
import { fetchRegistry, fetchTemplates, validateFlow, runMock, generateAndDownload } from "@/lib/api";
import { fromIR, toIR } from "@/lib/ir";
import type { MockResult } from "@/lib/api";
import type { Template } from "@/lib/api";

// Canvas uses ReactFlow which can't SSR
const Canvas = dynamic(() => import("@/components/Canvas"), { ssr: false });

type FeedbackState = { type: "ok" | "err" | "warn"; text: string } | null;
type ChatState = ({ loading: true } | MockResult) | null;

export default function HomePage() {
  const setRegistry = useStore((s) => s.setRegistry);
  const setTemplates = useStore((s) => s.setTemplates);
  const byType = useStore((s) => s.byType);
  const templates = useStore((s) => s.templates);
  const meta = useStore((s) => s.meta);
  const setMeta = useStore((s) => s.setMeta);
  const nodes = useStore((s) => s.nodes);
  const edges = useStore((s) => s.edges);
  const setNodes = useStore((s) => s.setNodes);
  const setEdges = useStore((s) => s.setEdges);
  const setSelectedNodeId = useStore((s) => s.setSelectedNodeId);

  const [feedback, setFeedback] = useState<FeedbackState>(null);
  const [chat, setChat] = useState<ChatState>(null);
  const [busy, setBusy] = useState(false);

  // Load registry + templates on mount
  useEffect(() => {
    fetchRegistry()
      .then(setRegistry)
      .catch((e: unknown) =>
        setFeedback({ type: "err", text: `Error cargando registro: ${String(e)}` })
      );
    fetchTemplates()
      .then(setTemplates)
      .catch((e: unknown) =>
        setFeedback({ type: "err", text: `Error cargando templates: ${String(e)}` })
      );
  }, [setRegistry, setTemplates]);

  function loadTemplate(tpl: Template | undefined) {
    if (!tpl) return;
    const ir = tpl.flow;
    setMeta(ir.flow);
    const { nodes: rfNodes, edges: rfEdges } = fromIR(ir, byType);
    setNodes(rfNodes);
    setEdges(rfEdges);
    setFeedback({
      type: "ok",
      text: `Template cargado: ${ir.flow.name} (${rfNodes.length} nodos).`,
    });
    setChat(null);
    setSelectedNodeId(null);
  }

  const handleConnectionError = useCallback((msg: string) => {
    setFeedback({ type: "err", text: msg });
  }, []);

  async function doValidate() {
    setBusy(true);
    try {
      const ir = toIR(nodes, edges, meta);
      const result = await validateFlow(ir);
      if (result.ok) {
        setFeedback({
          type: result.warnings.length > 0 ? "warn" : "ok",
          text:
            `✅ Válido. ${result.warnings.length} warnings.` +
            (result.warnings.length
              ? "\n• " + result.warnings.slice(0, 4).join("\n• ")
              : ""),
        });
      } else {
        setFeedback({
          type: "err",
          text: "❌ " + result.errors.length + " errores:\n• " + result.errors.join("\n• "),
        });
      }
    } catch (e: unknown) {
      setFeedback({ type: "err", text: `Error: ${String(e)}` });
    } finally {
      setBusy(false);
    }
  }

  async function doRunMock() {
    setBusy(true);
    setChat({ loading: true });
    try {
      const ir = toIR(nodes, edges, meta);
      const res = await runMock(ir);
      if (!res.ok) {
        setChat(null);
        setFeedback({
          type: "err",
          text: "❌ " + (res.errors ?? ["error"]).join("\n"),
        });
      } else {
        setChat(res.result ?? null);
      }
    } catch (e: unknown) {
      setChat(null);
      setFeedback({ type: "err", text: `Error: ${String(e)}` });
    } finally {
      setBusy(false);
    }
  }

  async function doExport() {
    setBusy(true);
    try {
      const ir = toIR(nodes, edges, meta);
      const res = await generateAndDownload(ir);
      if (res.ok) {
        setFeedback({
          type: "ok",
          text: `⬇️ Proyecto exportado: ${meta.id}.zip (incluye app/, mocks/, tests/).`,
        });
      } else {
        setFeedback({
          type: "err",
          text: "❌ " + res.errors.join("\n"),
        });
      }
    } catch (e: unknown) {
      setFeedback({ type: "err", text: `Error: ${String(e)}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      {/* Top bar */}
      <div className="topbar">
        <div className="brand">
          🛰️ RAG<span>orbit</span>
        </div>
        <div className="topbar-actions">
          <select
            onChange={(e) => {
              const tpl = templates.find((t) => t.id === e.target.value);
              loadTemplate(tpl);
              // Reset select to placeholder
              e.target.value = "";
            }}
            defaultValue=""
          >
            <option value="" disabled>
              — Galería de templates (10 casos) —
            </option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <span style={{ fontSize: 11, color: "var(--muted)" }}>
            {meta.deploymentTarget}
          </span>
          <button onClick={doValidate} disabled={busy}>
            Validar
          </button>
          <button onClick={doRunMock} disabled={busy}>
            Probar con mocks
          </button>
          <button className="primary" onClick={doExport} disabled={busy}>
            Exportar
          </button>
        </div>
      </div>

      {/* Left: palette */}
      <Palette />

      {/* Center: canvas */}
      <Canvas onConnectionError={handleConnectionError} />

      {/* Right: inspector */}
      <Inspector feedback={feedback} chat={chat} />
    </div>
  );
}
