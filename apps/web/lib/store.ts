import { create } from "zustand";
import type { Node, Edge } from "reactflow";
import type { NodeManifest, FlowMeta, RagNodeData } from "./ir";
import type { Template } from "./api";

interface RagStore {
  // Registry
  registry: NodeManifest[];
  byType: Map<string, NodeManifest>;
  setRegistry: (items: NodeManifest[]) => void;

  // Templates
  templates: Template[];
  setTemplates: (items: Template[]) => void;

  // Flow metadata
  meta: FlowMeta;
  setMeta: (meta: FlowMeta) => void;

  // Canvas state
  nodes: Node<RagNodeData>[];
  edges: Edge[];
  setNodes: (nodes: Node<RagNodeData>[]) => void;
  setEdges: (edges: Edge[]) => void;

  // Selection
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;

  // Update a single node's config key
  updateNodeConfig: (nodeId: string, key: string, value: unknown) => void;
}

const DEFAULT_META: FlowMeta = {
  id: "nuevo-flujo",
  name: "Nuevo flujo",
  deploymentTarget: "chat-service",
  defaults: { llm: "anthropic:claude-opus-4-8" },
};

export const useStore = create<RagStore>((set) => ({
  registry: [],
  byType: new Map(),
  setRegistry: (items) => {
    const map = new Map<string, NodeManifest>();
    items.forEach((m) => map.set(m.type, m));
    set({ registry: items, byType: map });
  },

  templates: [],
  setTemplates: (items) => set({ templates: items }),

  meta: DEFAULT_META,
  setMeta: (meta) => set({ meta }),

  nodes: [],
  edges: [],
  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  selectedNodeId: null,
  setSelectedNodeId: (id) => set({ selectedNodeId: id }),

  updateNodeConfig: (nodeId, key, value) =>
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              data: {
                ...n.data,
                config: { ...n.data.config, [key]: value },
              },
            }
          : n
      ),
    })),
}));
