import type { NodeManifest, FlowIR } from "./ir";

// All API calls go through Next.js rewrites → http://127.0.0.1:8000

export interface Template {
  id: string;
  name: string;
  description: string;
  deploymentTarget: string;
  flow: FlowIR;
}

export interface ValidateResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

export interface MockTraceAgent {
  tool_calls?: unknown[];
}

export interface MockTraceFanout {
  processed: number;
}

export interface MockTrace {
  agent?: MockTraceAgent;
  fanout?: MockTraceFanout;
}

export interface MockResult {
  response: string | unknown;
  escalations?: unknown[];
  notifications?: unknown[];
  citations?: unknown[];
  audit?: number;
  metrics?: number;
  trace?: MockTrace;
}

export interface RunMockResponse {
  ok: boolean;
  errors?: string[];
  result?: MockResult;
}

/** Fetch all node manifests from the registry */
export async function fetchRegistry(): Promise<NodeManifest[]> {
  const res = await fetch("/api/registry/nodes");
  if (!res.ok) throw new Error(`Registry fetch failed: ${res.status}`);
  return res.json() as Promise<NodeManifest[]>;
}

/** Fetch the list of example templates */
export async function fetchTemplates(): Promise<Template[]> {
  const res = await fetch("/api/templates");
  if (!res.ok) throw new Error(`Templates fetch failed: ${res.status}`);
  return res.json() as Promise<Template[]>;
}

/** Validate a flow against the backend */
export async function validateFlow(flow: FlowIR): Promise<ValidateResult> {
  const res = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flow }),
  });
  if (!res.ok) throw new Error(`Validate failed: ${res.status}`);
  return res.json() as Promise<ValidateResult>;
}

/** Run the flow in mock mode */
export async function runMock(
  flow: FlowIR,
  seedMessage = "Hola, ¿me ayudas con mi caso?"
): Promise<RunMockResponse> {
  const res = await fetch("/api/run-mock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flow, seedMessage }),
  });
  if (!res.ok) throw new Error(`Run-mock failed: ${res.status}`);
  return res.json() as Promise<RunMockResponse>;
}

/** Generate project ZIP and trigger download */
export async function generateAndDownload(
  flow: FlowIR
): Promise<{ ok: true } | { ok: false; errors: string[] }> {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flow }),
  });
  if (!res.ok) {
    try {
      const d = (await res.json()) as { errors?: string[] };
      return { ok: false, errors: d.errors ?? ["Error desconocido"] };
    } catch {
      return { ok: false, errors: [`HTTP ${res.status}`] };
    }
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${flow.flow.id}.zip`;
  a.click();
  URL.revokeObjectURL(url);
  return { ok: true };
}
