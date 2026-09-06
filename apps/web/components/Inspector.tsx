"use client";

import { useStore } from "@/lib/store";
import type { MockResult } from "@/lib/api";
import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import type { IChangeEvent } from "@rjsf/core";
import type { RJSFSchema } from "@rjsf/utils";

interface InspectorProps {
  feedback: { type: "ok" | "err" | "warn"; text: string } | null;
  chat: ({ loading: true } | MockResult) | null;
}

export default function Inspector({ feedback, chat }: InspectorProps) {
  const nodes = useStore((s) => s.nodes);
  const selectedId = useStore((s) => s.selectedNodeId);
  const updateNodeConfig = useStore((s) => s.updateNodeConfig);

  const selNode = nodes.find((n) => n.id === selectedId);
  const manifest = selNode?.data?.manifest;

  function handleFormChange(data: IChangeEvent, id?: string) {
    if (!selectedId) return;
    const formData = data.formData as Record<string, unknown>;
    // Apply each changed key individually so the store stays in sync
    for (const [key, value] of Object.entries(formData ?? {})) {
      updateNodeConfig(selectedId, key, value);
    }
    void id; // suppress unused warning
  }

  // Build a valid JSON Schema for RJSF from the manifest's configSchema
  const schema: RJSFSchema | null =
    manifest?.configSchema
      ? (manifest.configSchema as unknown as RJSFSchema)
      : null;

  const formData = selNode?.data?.config ?? {};

  const isMockLoading = chat && "loading" in chat && chat.loading;
  const mockResult = chat && !("loading" in chat) ? (chat as MockResult) : null;

  return (
    <div className="inspector">
      {selNode ? (
        <div>
          <h3>{selNode.data.label}</h3>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>
            {selNode.data.type}
          </div>

          {schema && Object.keys(schema.properties ?? {}).length > 0 ? (
            <div className="rjsf">
              <Form
                schema={schema}
                validator={validator}
                formData={formData}
                onChange={handleFormChange}
                uiSchema={{
                  "ui:submitButtonOptions": { norender: true },
                }}
                liveValidate={false}
              />
            </div>
          ) : (
            <p style={{ color: "var(--muted)", fontSize: 12 }}>
              Este nodo no requiere configuración.
            </p>
          )}
        </div>
      ) : (
        <div>
          <h3>Inspector</h3>
          <p style={{ color: "var(--muted)", fontSize: 12 }}>
            Carga un template o arrastra nodos desde la paleta. Haz clic en un
            nodo para configurarlo. Conecta puertos del mismo tipo.
          </p>
        </div>
      )}

      {/* Feedback message */}
      {feedback && (
        <div className={`msg ${feedback.type}`}>{feedback.text}</div>
      )}

      {/* Mock run result panel */}
      {chat && (
        <div className="chat-result">
          {isMockLoading ? (
            <span style={{ color: "var(--muted)" }}>
              Ejecutando en modo mock…
            </span>
          ) : mockResult ? (
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                🤖 Respuesta (mock)
              </div>
              <div style={{ fontSize: 12, marginBottom: 6 }}>
                {typeof mockResult.response === "string" ? (
                  mockResult.response
                ) : (
                  <pre style={{ margin: 0, fontSize: 11 }}>
                    {JSON.stringify(mockResult.response, null, 2)}
                  </pre>
                )}
              </div>
              <div>
                {mockResult.citations && mockResult.citations.length > 0 && (
                  <span className="chip">
                    📚 {mockResult.citations.length} citas
                  </span>
                )}
                {mockResult.escalations && mockResult.escalations.length > 0 && (
                  <span className="chip">
                    🙋 {mockResult.escalations.length} escalación
                  </span>
                )}
                {mockResult.notifications &&
                  mockResult.notifications.length > 0 && (
                    <span className="chip">
                      📨 {mockResult.notifications.length} notif
                    </span>
                  )}
                {mockResult.audit !== undefined && mockResult.audit > 0 && (
                  <span className="chip">📝 audit {mockResult.audit}</span>
                )}
                {mockResult.trace?.agent && (
                  <span className="chip">
                    🛠️{" "}
                    {(mockResult.trace.agent.tool_calls ?? []).length} tool
                    calls
                  </span>
                )}
                {mockResult.trace?.fanout && (
                  <span className="chip">
                    ⚡ fanout {mockResult.trace.fanout.processed}
                  </span>
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
