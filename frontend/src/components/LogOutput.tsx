import { useEffect, useRef } from "react";

interface LogOutputProps {
  lines: string[];
  visible: boolean;
}

function colorize(line: string) {
  if (line.startsWith("[ERROR]")) return "text-error";
  if (line.startsWith("[WARN]")) return "text-warning";
  if (line.startsWith("[OK]")) return "text-success";
  return "text-text-secondary";
}

export default function LogOutput({ lines, visible }: LogOutputProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  if (!visible) return null;

  return (
    <div ref={containerRef} className="mt-3 rounded-lg bg-surface p-3 font-mono text-sm max-h-64 overflow-y-auto border border-border-subtle">
      {lines.length === 0 ? (
        <span className="text-text-muted">No output yet.</span>
      ) : (
        lines.map((line, i) => (
          <div key={i} className={colorize(line)}>
            {line}
          </div>
        ))
      )}
    </div>
  );
}
