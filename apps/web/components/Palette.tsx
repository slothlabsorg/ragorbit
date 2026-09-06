"use client";

import { useStore } from "@/lib/store";
import { CAT_COLORS } from "./NodeCard";

export default function Palette() {
  const registry = useStore((s) => s.registry);

  // Group manifests by category
  const byCat: Record<string, typeof registry> = {};
  for (const m of registry) {
    if (!byCat[m.category]) byCat[m.category] = [];
    byCat[m.category].push(m);
  }

  const categories = Object.keys(byCat).sort();

  function handleDragStart(e: React.DragEvent<HTMLDivElement>, type: string) {
    e.dataTransfer.setData("application/ragnode", type);
    e.dataTransfer.effectAllowed = "copy";
  }

  return (
    <div className="palette">
      {categories.map((cat) => (
        <div key={cat}>
          <div className="cat-label">
            <span
              className="cat-dot"
              style={{ background: CAT_COLORS[cat] ?? "#888" }}
            />
            {cat}
          </div>
          {byCat[cat].map((m) => (
            <div
              key={m.type}
              className="pal-item"
              draggable
              onDragStart={(e) => handleDragStart(e, m.type)}
            >
              {m.title}
              <small>{m.type}</small>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
