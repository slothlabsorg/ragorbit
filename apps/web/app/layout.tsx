import type { Metadata } from "next";
import "./globals.css";
import "reactflow/dist/style.css";

export const metadata: Metadata = {
  title: "RAGorbit · Constructor visual de estrategias RAG/agénticas",
  description: "Visual builder for RAG/agentic pipelines",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
