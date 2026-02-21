import { useState } from "react";
import type { WorkflowStepConfig, StepState, StepOption } from "../hooks/useWorkflow";
import LogOutput from "./LogOutput";

interface WorkflowStepProps {
  config: WorkflowStepConfig;
  state: StepState;
  options: Record<string, string | number | boolean>;
  onRun: () => void;
  onStop: () => void;
  onSetOption: (flag: string, value: string | number | boolean) => void;
}

const statusConfig: Record<string, { label: string; color: string; dot: string }> = {
  idle: { label: "Idle", color: "bg-surface-overlay text-text-muted", dot: "bg-text-muted" },
  running: { label: "Running", color: "bg-accent/20 text-accent-hover", dot: "bg-accent animate-pulse" },
  success: { label: "Success", color: "bg-success/20 text-success", dot: "bg-success" },
  error: { label: "Error", color: "bg-error/20 text-error", dot: "bg-error" },
};

function OptionInput({
  opt,
  value,
  onChange,
}: {
  opt: StepOption;
  value: string | number | boolean;
  onChange: (v: string | number | boolean) => void;
}) {
  if (opt.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="accent-accent w-4 h-4"
        />
        {opt.label}
      </label>
    );
  }
  return (
    <label className="flex flex-col gap-1 text-sm text-text-secondary">
      <span>{opt.label}</span>
      <input
        type={opt.type === "number" ? "number" : "text"}
        value={String(value)}
        onChange={(e) =>
          onChange(opt.type === "number" ? Number(e.target.value) : e.target.value)
        }
        className="rounded bg-surface border border-border-subtle px-2 py-1 text-text-primary text-sm focus:outline-none focus:border-accent"
      />
    </label>
  );
}

export default function WorkflowStep({ config, state, options, onRun, onStop, onSetOption }: WorkflowStepProps) {
  const [expanded, setExpanded] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const status = statusConfig[state.status];
  const elapsed =
    state.startedAt && state.finishedAt
      ? ((state.finishedAt - state.startedAt) / 1000).toFixed(1) + "s"
      : null;

  return (
    <div className="rounded-xl bg-surface-raised border border-border-subtle p-5 transition-all hover:border-accent/40">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4 min-w-0">
          <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-accent/15 flex items-center justify-center text-accent font-bold text-sm">
            {config.id}
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-text-primary text-lg leading-tight">{config.name}</h3>
            <p className="text-text-secondary text-sm mt-0.5">{config.description}</p>
            <p className="text-text-muted text-xs mt-1 font-mono">{config.script}</p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${status.color}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${status.dot}`} />
            {status.label}
            {elapsed && <span className="ml-1 text-text-muted">({elapsed})</span>}
          </span>
          {state.status === "running" ? (
            <button
              onClick={onStop}
              className="rounded-lg bg-error hover:bg-error/80 px-4 py-2 text-sm font-medium text-white transition-colors"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={onRun}
              className="rounded-lg bg-accent hover:bg-accent-hover px-4 py-2 text-sm font-medium text-white transition-colors"
            >
              Run
            </button>
          )}
        </div>
      </div>

      <div className="flex gap-3 mt-3">
        {config.options.length > 0 && (
          <button
            onClick={() => setShowOptions(!showOptions)}
            className="text-xs text-text-muted hover:text-text-secondary transition-colors"
          >
            {showOptions ? "Hide" : "Show"} Options ({config.options.length})
          </button>
        )}
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-text-muted hover:text-text-secondary transition-colors"
        >
          {expanded ? "Hide" : "Show"} Output{state.output.length > 0 && ` (${state.output.length})`}
        </button>
      </div>

      {showOptions && (
        <div className="mt-3 flex flex-wrap gap-4 p-3 rounded-lg bg-surface border border-border-subtle">
          {config.options.map((opt) => (
            <OptionInput
              key={opt.flag}
              opt={opt}
              value={options[opt.flag]}
              onChange={(v) => onSetOption(opt.flag, v)}
            />
          ))}
        </div>
      )}

      <LogOutput lines={state.output} visible={expanded || state.status === "running"} />
    </div>
  );
}
