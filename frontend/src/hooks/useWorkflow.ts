import { useState, useCallback, useRef } from "react";

export type StepStatus = "idle" | "running" | "success" | "error";

export interface StepOption {
  flag: string;
  label: string;
  type: "text" | "number" | "boolean";
  default?: string | number | boolean;
}

export interface WorkflowStepConfig {
  id: number;
  name: string;
  description: string;
  script: string;
  options: StepOption[];
}

export interface StepState {
  status: StepStatus;
  output: string[];
  startedAt: number | null;
  finishedAt: number | null;
}

export const WORKFLOW_STEPS: WorkflowStepConfig[] = [
  {
    id: 1,
    name: "Company Research",
    description: "Scrape & summarize companies with AI",
    script: "01_workflow/main.py",
    options: [
      { flag: "--batch", label: "Batch Name", type: "text", default: "" },
      { flag: "--verbose", label: "Verbose", type: "boolean", default: false },
    ],
  },
  {
    id: 2,
    name: "Template Generation",
    description: "Generate personalized email templates",
    script: "02_workflow/generate_from_csv.py",
    options: [
      { flag: "--dry-run", label: "Dry Run", type: "boolean", default: false },
      { flag: "--overwrite", label: "Overwrite Existing", type: "boolean", default: false },
      { flag: "-v", label: "Verbose", type: "boolean", default: false },
    ],
  },
  {
    id: 3,
    name: "Email Drafter",
    description: "Create Gmail drafts for review",
    script: "03_workflow/draft_emails.py",
    options: [
      { flag: "--dry-run", label: "Dry Run", type: "boolean", default: false },
      { flag: "--company", label: "Single Company", type: "text", default: "" },
      { flag: "-v", label: "Verbose", type: "boolean", default: false },
    ],
  },
  {
    id: 4,
    name: "Email Review",
    description: "QA check emails + resumes",
    script: "04_workflow/review_emails.py",
    options: [
      { flag: "--company", label: "Single Company", type: "text", default: "" },
      { flag: "-v", label: "Verbose", type: "boolean", default: false },
    ],
  },
  {
    id: 5,
    name: "Email Sender",
    description: "Send emails via Gmail SMTP",
    script: "05_workflow/send_emails.py",
    options: [
      { flag: "--dry-run", label: "Dry Run", type: "boolean", default: true },
      { flag: "--no-dry-run", label: "Actually Send", type: "boolean", default: false },
      { flag: "--preview", label: "Preview Stats", type: "boolean", default: false },
      { flag: "-v", label: "Verbose", type: "boolean", default: false },
    ],
  },
];

const MOCK_OUTPUTS: Record<number, string[]> = {
  1: [
    "[INFO] Starting company research pipeline...",
    "[INFO] Loading target companies from CSV...",
    "[INFO] Found 12 companies to research",
    "[INFO] Scraping company data for Acme Corp...",
    "[INFO] Scraping company data for Globex Inc...",
    "[INFO] Running AI summarization on 12 profiles...",
    "[OK] Generated 12 company summaries",
    "[OK] Results saved to output/companies.json",
  ],
  2: [
    "[INFO] Loading company summaries...",
    "[INFO] Found 12 company profiles",
    "[INFO] Generating email templates with GPT-4...",
    "[INFO] Processing template for Acme Corp...",
    "[INFO] Processing template for Globex Inc...",
    "[OK] Generated 12 personalized templates",
    "[OK] Templates saved to output/templates/",
  ],
  3: [
    "[INFO] Authenticating with Gmail API...",
    "[OK] Authenticated as user@gmail.com",
    "[INFO] Loading email templates...",
    "[INFO] Creating draft for hiring@acme.com...",
    "[INFO] Creating draft for jobs@globex.com...",
    "[OK] Created 12 drafts in Gmail",
  ],
  4: [
    "[INFO] Loading drafts for review...",
    "[INFO] Checking email 1/12: Acme Corp...",
    "[WARN] Email to Globex Inc has no resume attachment",
    "[INFO] Checking email 3/12: Initech...",
    "[OK] 11/12 emails passed QA",
    "[WARN] 1 email flagged for review",
  ],
  5: [
    "[INFO] Connecting to Gmail SMTP...",
    "[OK] SMTP connection established",
    "[INFO] Sending email 1/11: hiring@acme.com...",
    "[INFO] Sending email 2/11: jobs@initech.com...",
    "[INFO] Sending email 3/11: careers@umbrella.com...",
    "[OK] Successfully sent 11/11 emails",
    "[OK] Send log saved to output/send_log.json",
  ],
};

async function mockExecuteStep(
  stepId: number,
  _args: Record<string, string | number | boolean>,
  onOutput: (line: string) => void
): Promise<boolean> {
  const lines = MOCK_OUTPUTS[stepId] || ["[INFO] Running...", "[OK] Done."];
  for (const line of lines) {
    await new Promise((r) => setTimeout(r, 300 + Math.random() * 400));
    onOutput(line);
  }
  if (stepId === 4 && Math.random() < 0.15) {
    onOutput("[ERROR] QA check failed — attachment missing for 3 emails");
    return false;
  }
  return true;
}

async function executeStep(
  stepId: number,
  args: Record<string, string | number | boolean>,
  onOutput: (line: string) => void,
  signal?: AbortSignal
): Promise<boolean> {
  const res = await fetch(`/api/workflow/${stepId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ options: args }),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`Backend returned ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let exitCode = 0;

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
        onOutput(data.line);
      } else if (event === "done") {
        exitCode = data.exitCode;
      } else if (event === "error") {
        onOutput(`[ERROR] ${data.message}`);
        return false;
      }
    }
  }

  return exitCode === 0;
}

export function useWorkflow() {
  const [stepStates, setStepStates] = useState<Record<number, StepState>>(
    Object.fromEntries(
      WORKFLOW_STEPS.map((s) => [
        s.id,
        { status: "idle" as StepStatus, output: [], startedAt: null, finishedAt: null },
      ])
    )
  );

  const [stepOptions, setStepOptions] = useState<Record<number, Record<string, string | number | boolean>>>(
    Object.fromEntries(
      WORKFLOW_STEPS.map((s) => [
        s.id,
        Object.fromEntries(s.options.map((o) => [o.flag, o.default ?? ""])),
      ])
    )
  );

  const updateStepState = useCallback((stepId: number, patch: Partial<StepState>) => {
    setStepStates((prev) => ({
      ...prev,
      [stepId]: { ...prev[stepId], ...patch },
    }));
  }, []);

  const appendOutput = useCallback((stepId: number, line: string) => {
    setStepStates((prev) => ({
      ...prev,
      [stepId]: { ...prev[stepId], output: [...prev[stepId].output, line] },
    }));
  }, []);

  const abortControllers = useRef<Record<number, AbortController>>({});

  const stopStep = useCallback(
    async (stepId: number) => {
      // Abort the SSE fetch
      abortControllers.current[stepId]?.abort();
      delete abortControllers.current[stepId];

      // Tell backend to kill the process
      try {
        await fetch(`/api/workflow/${stepId}`, { method: "DELETE" });
      } catch { /* ignore */ }

      appendOutput(stepId, "[STOPPED] Workflow stopped by user");
      updateStepState(stepId, {
        status: "error",
        finishedAt: Date.now(),
      });
    },
    [appendOutput, updateStepState]
  );

  const setOption = useCallback(
    (stepId: number, flag: string, value: string | number | boolean) => {
      setStepOptions((prev) => ({
        ...prev,
        [stepId]: { ...prev[stepId], [flag]: value },
      }));
    },
    []
  );

  const runStep = useCallback(
    async (stepId: number) => {
      const step = WORKFLOW_STEPS.find((s) => s.id === stepId);
      if (!step) return;

      const controller = new AbortController();
      abortControllers.current[stepId] = controller;

      updateStepState(stepId, {
        status: "running",
        output: [],
        startedAt: Date.now(),
        finishedAt: null,
      });

      const args = stepOptions[stepId] || {};

      let success: boolean;
      try {
        success = await executeStep(stepId, args, (line) => {
          appendOutput(stepId, line);
        }, controller.signal);

      } catch (err) {
        if (controller.signal.aborted) return; // stopped by user, already handled
        // Backend unavailable — fall back to mock
        appendOutput(stepId, "[WARN] Backend unavailable, using mock output");
        success = await mockExecuteStep(stepId, args, (line) => {
          appendOutput(stepId, line);
        });
      } finally {
        delete abortControllers.current[stepId];
      }

      updateStepState(stepId, {
        status: success ? "success" : "error",
        finishedAt: Date.now(),
      });
    },
    [stepOptions, updateStepState, appendOutput]
  );

  return { stepStates, stepOptions, setOption, runStep, stopStep };
}
