"use client";

import { memo } from "react";
import { Handle, Position } from "reactflow";
import type { NodeProps } from "reactflow";
import type { RagNodeData } from "@/lib/ir";

export const CAT_COLORS: Record<string, string> = {
  io: "#5b8cff",
  loader: "#d29922",
  ingest: "#a371f7",
  store: "#2ea043",
  retrieval: "#39c5cf",
  model: "#f778ba",
  query: "#e3b341",
  logic: "#db61a2",
  agent: "#ff7b72",
  tool: "#79c0ff",
  guardrail: "#f85149",
  hitl: "#ffa657",
  observability: "#56d364",
};

function NodeCard({ data, selected }: NodeProps<RagNodeData>) {
  const manifest = data.manifest;
  const inputs = manifest?.ports?.inputs ?? [];
  const outputs = manifest?.ports?.outputs ?? [];
  const category = manifest?.category ?? "";
  const color = CAT_COLORS[category] ?? "#888";

  // Spread handles vertically from the node header area
  const handleOffset = (index: number) => 26 + index * 16;

  return (
    <div className={`rag-node${selected ? " selected" : ""}`}>
      {/* Input handles on the left */}
      {inputs.map((port, i) => (
        <Handle
          key={`in-${port.type}-${i}`}
          id={`in:${port.type}`}
          type="target"
          position={Position.Left}
          style={{
            top: handleOffset(i),
            background: "#888",
            border: "1px solid #444",
          }}
          title={`${port.name} : ${port.type}`}
        />
      ))}

      {/* Node header */}
      <div className="rag-node-hd">
        <span
          className="cat-dot"
          style={{ background: color }}
        />
        {data.label}
      </div>

      {/* Node body — type identifier */}
      <div className="rag-node-bd">{data.type}</div>

      {/* Output handles on the right */}
      {outputs.map((port, i) => (
        <Handle
          key={`out-${port.type}-${i}`}
          id={`out:${port.type}`}
          type="source"
          position={Position.Right}
          style={{
            top: handleOffset(i),
            background: color,
            border: "1px solid #444",
          }}
          title={`${port.name} : ${port.type}`}
        />
      ))}
    </div>
  );
}

export default memo(NodeCard);
