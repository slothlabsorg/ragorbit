// ---- Port and Manifest types ----

export interface PortDef {
  name: string;
  type: string;
  required?: boolean;
}

export interface Ports {
  inputs?: PortDef[];
  outputs?: PortDef[];
}

export interface SecretDef {
  name: string;
  required: boolean;
  usedBy: string[];
}

export interface NodeManifest {
  type: string;
  title: string;
  category: string;
  description?: string;
  ports: Ports;
  configSchema?: ConfigSchema;
  defaults?: Record<string, unknown>;
  secrets?: string[];
  mock?: boolean;
}

export interface ConfigSchemaProp {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  items?: ConfigSchemaProp;
  properties?: Record<string, ConfigSchemaProp>;
}

export interface ConfigSchema {
  type: string;
  properties?: Record<string, ConfigSchemaProp>;
  required?: string[];
  title?: string;
}

// ---- Flow IR types ----

export interface FlowMeta {
  id: string;
  name: string;
  deploymentTarget: string;
  description?: string;
  defaults?: {
    llm?: string;
    [key: string]: unknown;
  };
}

export interface IRNode {
  id: string;
  type: string;
  label: string;
  config: Record<string, unknown>;
  position: { x: number; y: number };
}

export interface IREdge {
  source: string;
  sourcePort: string;
  target: string;
  targetPort: string;
  loop?: boolean;
}

export interface FlowIR {
  irVersion: "1.0";
  flow: FlowMeta;
  nodes: IRNode[];
  edges: IREdge[];
  secrets: SecretDef[];
}

// ---- React Flow node data ----

export interface RagNodeData {
  label: string;
  type: string;
  config: Record<string, unknown>;
  manifest: NodeManifest | undefined;
}

// ---- IR conversion helpers ----

import type { Node, Edge } from "reactflow";

/** Convert React Flow nodes/edges + meta to the backend Flow IR */
export function toIR(
  nodes: Node<RagNodeData>[],
  edges: Edge[],
  meta: FlowMeta
): FlowIR {
  return {
    irVersion: "1.0",
    flow: meta,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.type,
      label: n.data.label,
      config: n.data.config ?? {},
      position: n.position,
    })),
    edges: edges.map((e) => ({
      source: e.source,
      sourcePort: (e.sourceHandle ?? "out:Any").split(":")[1],
      target: e.target,
      targetPort: (e.targetHandle ?? "in:Any").split(":")[1],
      loop: !!((e.data as { loop?: boolean } | undefined)?.loop),
    })),
    secrets: collectSecrets(nodes),
  };
}

function collectSecrets(nodes: Node<RagNodeData>[]): SecretDef[] {
  const map = new Map<string, SecretDef>();
  for (const n of nodes) {
    const manifest = n.data.manifest;
    if (!manifest) continue;
    for (const s of manifest.secrets ?? []) {
      if (!map.has(s)) map.set(s, { name: s, required: true, usedBy: [] });
      map.get(s)!.usedBy.push(n.id);
    }
    const ref = (n.data.config as { apiKeyRef?: string }).apiKeyRef;
    if (ref) {
      if (!map.has(ref)) map.set(ref, { name: ref, required: true, usedBy: [] });
      map.get(ref)!.usedBy.push(n.id);
    }
  }
  return Array.from(map.values());
}

/** Convert a template Flow IR back to React Flow nodes/edges */
export function fromIR(
  ir: FlowIR,
  byType: Map<string, NodeManifest>
): { nodes: Node<RagNodeData>[]; edges: Edge[] } {
  const rfNodes: Node<RagNodeData>[] = ir.nodes.map((n) => ({
    id: n.id,
    type: "rag",
    position: n.position ?? { x: 0, y: 0 },
    data: {
      label: n.label ?? n.id,
      type: n.type,
      config: n.config ?? {},
      manifest: byType.get(n.type),
    },
  }));

  const rfEdges: Edge[] = ir.edges.map((e, i) => ({
    id: `e${i}-${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    sourceHandle: `out:${e.sourcePort}`,
    targetHandle: `in:${e.targetPort}`,
    animated: !!e.loop,
    style: e.loop ? { stroke: "#d29922", strokeDasharray: "5 4" } : undefined,
    data: { sT: e.sourcePort, tT: e.targetPort, loop: e.loop ?? false },
  }));

  return { nodes: rfNodes, edges: rfEdges };
}
