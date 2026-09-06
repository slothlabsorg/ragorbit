"use client";

import { useCallback } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  ReactFlowProvider,
  useReactFlow,
} from "reactflow";
import type {
  Connection,
  NodeChange,
  EdgeChange,
} from "reactflow";
import NodeCard from "./NodeCard";
import type { RagNodeData } from "@/lib/ir";
import { useStore } from "@/lib/store";

// Register our custom node type
const nodeTypes = { rag: NodeCard };

interface CanvasInnerProps {
  onConnectionError: (msg: string) => void;
}

/** Port-type compatibility: same type, Any on either side, or Message↔Query */
function portsCompatible(sourceType: string, targetType: string): boolean {
  if (sourceType === targetType) return true;
  if (sourceType === "Any" || targetType === "Any") return true;
  if (
    (sourceType === "Message" && targetType === "Query") ||
    (sourceType === "Query" && targetType === "Message")
  )
    return true;
  return false;
}

function CanvasInner({ onConnectionError }: CanvasInnerProps) {
  const { screenToFlowPosition } = useReactFlow();

  const nodes = useStore((s) => s.nodes);
  const edges = useStore((s) => s.edges);
  const byType = useStore((s) => s.byType);
  const setNodes = useStore((s) => s.setNodes);
  const setEdges = useStore((s) => s.setEdges);
  const setSelectedNodeId = useStore((s) => s.setSelectedNodeId);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) =>
      setNodes(applyNodeChanges(changes, nodes) as typeof nodes),
    [nodes, setNodes]
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges(applyEdgeChanges(changes, edges)),
    [edges, setEdges]
  );

  const onConnect = useCallback(
    (params: Connection) => {
      const sT = (params.sourceHandle ?? "out:Any").split(":")[1];
      const tT = (params.targetHandle ?? "in:Any").split(":")[1];
      if (!portsCompatible(sT, tT)) {
        onConnectionError(
          `No se puede conectar ${sT} → ${tT}: tipos incompatibles.`
        );
        return;
      }
      setEdges(
        addEdge({ ...params, data: { sT, tT } }, edges)
      );
    },
    [edges, setEdges, onConnectionError]
  );

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const type = e.dataTransfer.getData("application/ragnode");
    if (!type) return;
    const manifest = byType.get(type);
    if (!manifest) return;
    const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const id = `${type.replace(/[^a-z0-9]/gi, "_")}_${Math.floor(Math.random() * 9999)}`;
    setNodes([
      ...nodes,
      {
        id,
        type: "rag",
        position: pos,
        data: {
          label: manifest.title,
          type,
          config: { ...(manifest.defaults ?? {}) },
          manifest,
        },
      },
    ]);
  }

  return (
    <div
      className="canvas-wrap"
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_e, n) => setSelectedNodeId(n.id)}
        onPaneClick={() => setSelectedNodeId(null)}
        fitView
        deleteKeyCode="Delete"
      >
        <Background />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  );
}

interface CanvasProps {
  onConnectionError: (msg: string) => void;
}

/** Wrap CanvasInner in ReactFlowProvider so useReactFlow() is available */
export default function Canvas({ onConnectionError }: CanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner onConnectionError={onConnectionError} />
    </ReactFlowProvider>
  );
}
