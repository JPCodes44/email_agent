import { useState, useCallback, useEffect } from "react";
import Pipeline from "./components/Pipeline";
import LogOutput from "./components/LogOutput";
import { useWorkflow, WORKFLOW_STEPS } from "./hooks/useWorkflow";
import type { PipelineStatus, StepState } from "./hooks/useWorkflow";

type ClearStatus = "idle" | "running" | "success" | "error";

interface BackgroundWorkflow {
  stepId: number;
  pid: number;
  script: string;
}

function useClearOperation(endpoint: string) {
  const [status, setStatus] = useState<ClearStatus>("idle");
  const [logs, setLogs] = useState<string[]>([]);

  const run = useCallback(async () => {
    if (!confirm("This cannot be undone. Continue?")) return;
    setStatus("running");
    setLogs([]);

    try {
      const res = await fetch(endpoint, { method: "DELETE" });
      if (!res.ok || !res.body) {
        setLogs((prev) => [...prev, `[ERROR] Server returned ${res.status}`]);
        setStatus("error");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const events = buffer.split("\n\n");
        buffer = events.pop()!;

        for (const raw of events) {
          const eventMatch = raw.match(/^event:\s*(.+)$/m);
          const dataMatch = raw.match(/^data:\s*(.+)$/m);
          if (!eventMatch || !dataMatch) continue;

          const event = eventMatch[1];
          const data = JSON.parse(dataMatch[1]);

          if (event === "output") {
            setLogs((prev) => [...prev, data.line]);
          } else if (event === "done") {
            setStatus(data.exitCode === 0 ? "success" : "error");
          }
        }
      }
    } catch {
      setLogs((prev) => [...prev, "[ERROR] Failed to connect to backend"]);
      setStatus("error");
    }
  }, [endpoint]);

  return { status, logs, run };
}

function useBackgroundWorkflows() {
  const [workflows, setWorkflows] = useState<BackgroundWorkflow[]>([]);

  useEffect(() => {
    const fetchWorkflows = async () => {
      try {
        const res = await fetch("/api/workflows");
        if (res.ok) {
          const data = await res.json();
          setWorkflows(data.workflows || []);
        }
      } catch {
        // Ignore errors - workflows might not be available
      }
    };

    fetchWorkflows();
    const interval = setInterval(fetchWorkflows, 2000); // Poll every 2 seconds
    return () => clearInterval(interval);
  }, []);

  const killWorkflow = useCallback(async (stepId: number, pid: number) => {
    try {
      await fetch(`/api/workflow/${stepId}`, { method: "DELETE" });
      setWorkflows((prev) => prev.filter((w) => w.stepId !== stepId));
    } catch {
      // Ignore errors
    }
  }, []);

  return { workflows, killWorkflow };
}

const statusStyles: Record<ClearStatus, { label: string; color: string; dot: string }> = {
  idle: { label: "Idle", color: "bg-surface-overlay text-text-muted", dot: "bg-text-muted" },
  running: { label: "Running", color: "bg-accent/20 text-accent-hover", dot: "bg-accent animate-pulse" },
  success: { label: "Done", color: "bg-success/20 text-success", dot: "bg-success" },
  error: { label: "Error", color: "bg-error/20 text-error", dot: "bg-error" },
};

function ClearCard({ title, description, endpoint }: { title: string; description: string; endpoint: string }) {
  const { status, logs, run } = useClearOperation(endpoint);
  const style = statusStyles[status];

  return (
    <div className="rounded-xl bg-surface-raised border border-border-subtle p-4 flex flex-col h-full">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-text-primary text-sm leading-tight">{title}</h3>
          <p className="text-text-secondary text-xs mt-0.5">{description}</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium flex-shrink-0 ${style.color}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
          {style.label}
        </span>
      </div>

      <button
        onClick={run}
        disabled={status === "running"}
        className="rounded-lg border border-border-subtle bg-surface hover:border-error/50 hover:text-error disabled:opacity-40 px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors w-full mb-3"
      >
        {status === "running" ? "Clearing..." : `Clear ${title}`}
      </button>

      <div className="flex-1 min-h-0">
        <LogOutput lines={logs} visible={true} />
      </div>
    </div>
  );
}

const pipelineStyles: Record<PipelineStatus, { label: string; color: string; dot: string }> = {
  idle: { label: "Ready", color: "bg-surface-overlay text-text-muted", dot: "bg-text-muted" },
  running: { label: "Running", color: "bg-accent/20 text-accent-hover", dot: "bg-accent animate-pulse" },
  success: { label: "Complete", color: "bg-success/20 text-success", dot: "bg-success" },
  error: { label: "Stopped", color: "bg-error/20 text-error", dot: "bg-error" },
};

function RunAllCard({
  pipelineStatus,
  pipelineStepIndex,
  onRunAll,
  onStopAll,
}: {
  pipelineStatus: PipelineStatus;
  pipelineStepIndex: number;
  onRunAll: () => void;
  onStopAll: () => void;
}) {
  const style = pipelineStyles[pipelineStatus];
  const totalSteps = WORKFLOW_STEPS.length;
  const currentStepName = WORKFLOW_STEPS[pipelineStepIndex]?.name ?? "";
  const isRunning = pipelineStatus === "running";

  let statusText = "Click Run All to execute the full pipeline";
  if (pipelineStatus === "running") {
    statusText = `Step ${pipelineStepIndex + 1}/${totalSteps}: ${currentStepName}`;
  } else if (pipelineStatus === "success") {
    statusText = `All ${totalSteps} steps completed successfully`;
  } else if (pipelineStatus === "error") {
    statusText = `Pipeline stopped at step ${pipelineStepIndex + 1}: ${currentStepName}`;
  }

  return (
    <div className="rounded-xl bg-surface-raised border border-border-subtle p-4 mb-5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-text-primary text-sm">Run All</h3>
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${style.color}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                {style.label}
              </span>
            </div>
            <p className="text-text-secondary text-xs mt-0.5">{statusText}</p>
          </div>
        </div>

        <div className="flex gap-2 flex-shrink-0">
          {isRunning ? (
            <button
              onClick={onStopAll}
              className="rounded-lg border border-error/50 bg-surface hover:bg-error/10 text-error px-4 py-1.5 text-xs font-medium transition-colors"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={onRunAll}
              className="rounded-lg border border-accent/50 bg-accent/10 hover:bg-accent/20 text-accent-hover px-4 py-1.5 text-xs font-medium transition-colors"
            >
              Run All
            </button>
          )}
        </div>
      </div>

      {isRunning && (
        <div className="mt-3 flex gap-1">
          {WORKFLOW_STEPS.map((step, i) => (
            <div
              key={step.id}
              className={`h-1.5 flex-1 rounded-full transition-colors ${
                i < pipelineStepIndex
                  ? "bg-success"
                  : i === pipelineStepIndex
                  ? "bg-accent animate-pulse"
                  : "bg-surface-overlay"
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ElapsedTime({ startedAt }: { startedAt: number }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [startedAt]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return <span className="tabular-nums">{mins}:{secs.toString().padStart(2, "0")}</span>;
}

function RunningWorkflowsCard({
  stepStates,
  onStopAll,
}: {
  stepStates: Record<number, StepState>;
  onStopAll: () => void;
}) {
  const runningSteps = WORKFLOW_STEPS.filter((s) => stepStates[s.id]?.status === "running");

  if (runningSteps.length === 0) return null;

  return (
    <div className="rounded-xl bg-surface-raised border border-accent/30 p-4 flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
          <h3 className="font-semibold text-text-primary text-sm">Running</h3>
          <span className="text-text-muted text-xs">({runningSteps.length})</span>
        </div>
        <button
          onClick={onStopAll}
          className="rounded-lg border border-error/50 bg-surface hover:bg-error/10 text-error px-3 py-1 text-xs font-medium transition-colors"
        >
          Stop All
        </button>
      </div>

      <div className="flex flex-col gap-2">
        {runningSteps.map((step) => (
          <div
            key={step.id}
            className="flex items-center justify-between rounded-lg bg-surface-overlay px-3 py-2"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse flex-shrink-0" />
              <span className="text-text-primary text-xs font-medium truncate">{step.name}</span>
            </div>
            {stepStates[step.id]?.startedAt && (
              <span className="text-text-muted text-xs flex-shrink-0 ml-2">
                <ElapsedTime startedAt={stepStates[step.id].startedAt!} />
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function BackgroundWorkflowsCard({
  workflows,
  onKill,
}: {
  workflows: BackgroundWorkflow[];
  onKill: (stepId: number, pid: number) => void;
}) {
  if (workflows.length === 0) return null;

  return (
    <div className="rounded-xl bg-surface-raised border border-accent/30 p-4 flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
          <h3 className="font-semibold text-text-primary text-sm">Background Processes</h3>
          <span className="text-text-muted text-xs">({workflows.length})</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {workflows.map((wf) => (
          <div
            key={wf.stepId}
            className="flex items-center justify-between rounded-lg bg-surface-overlay px-3 py-2"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="w-1.5 h-1.5 rounded-full bg-accent flex-shrink-0" />
              <div className="flex flex-col min-w-0">
                <span className="text-text-primary text-xs font-medium truncate">
                  {WORKFLOW_STEPS.find((s) => s.id === wf.stepId)?.name || `Step ${wf.stepId}`}
                </span>
                <span className="text-text-muted text-[10px] font-mono">PID: {wf.pid}</span>
              </div>
            </div>
            <button
              onClick={() => onKill(wf.stepId, wf.pid)}
              className="rounded border border-error/30 bg-surface hover:bg-error/10 hover:text-error text-text-muted text-[10px] px-2 py-0.5 transition-colors flex-shrink-0"
            >
              Kill
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function App() {
  const {
    stepStates, stepOptions, setOption, runStep, stopStep,
    pipelineStatus, pipelineStepIndex, runAll, stopAll,
  } = useWorkflow();
  const { workflows, killWorkflow } = useBackgroundWorkflows();

  return (
    <div className="min-h-screen bg-surface">
      <div className="max-w-7xl mx-auto px-6 py-10">
        <header className="mb-8">
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">
            Email Agent
          </h1>
          <p className="text-text-secondary mt-1">
            Automated outreach pipeline — research, draft, review, and send.
          </p>
        </header>

        <RunAllCard
          pipelineStatus={pipelineStatus}
          pipelineStepIndex={pipelineStepIndex}
          onRunAll={runAll}
          onStopAll={stopAll}
        />

        <div className="grid grid-cols-[1fr_280px] gap-5 items-start">
          <Pipeline
            stepStates={stepStates}
            stepOptions={stepOptions}
            onRun={runStep}
            onStop={stopStep}
            onSetOption={setOption}
          />

          <div className="flex flex-col gap-5">
            <RunningWorkflowsCard
              stepStates={stepStates}
              onStopAll={stopAll}
            />

            <BackgroundWorkflowsCard
              workflows={workflows}
              onKill={killWorkflow}
            />

            <ClearCard
              title="Templates"
              description="Delete local email templates, Gmail drafts, and CSV links"
              endpoint="/api/output/emails"
            />

            <ClearCard
              title="Company Research"
              description="Remove company research batches"
              endpoint="/api/output/research/companies"
            />

            <ClearCard
              title="Person Research"
              description="Remove person research data"
              endpoint="/api/output/research/people"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
