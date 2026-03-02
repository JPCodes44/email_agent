import { useState, useCallback, useRef } from "react";

export type StepStatus = "idle" | "running" | "success" | "error";

export interface StepOption {
  flag: string;
  label: string;
  type: "text" | "number" | "boolean" | "textarea";
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
    name: "Person Research",
    description: "Research contacts via email & web",
    script: "02_workflow/research_people.py",
    options: [
      { flag: "--dry-run", label: "Dry Run", type: "boolean", default: false },
      { flag: "--overwrite", label: "Overwrite Existing", type: "boolean", default: false },
      { flag: "-v", label: "Verbose", type: "boolean", default: false },
    ],
  },
  {
    id: 3,
    name: "Template Generation",
    description: "Generate personalized email templates",
    script: "03_workflow/generate_from_csv.py",
    options: [
      { flag: "--dry-run", label: "Dry Run", type: "boolean", default: false },
      { flag: "--overwrite", label: "Overwrite Existing", type: "boolean", default: false },
      { flag: "-v", label: "Verbose", type: "boolean", default: false },
      {
        flag: "--prompt-instructions",
        label: "Email Format",
        type: "textarea",
        default:
          "EMAIL STRUCTURE - follow this template exactly. Fill in the bracketed placeholders with real, " +
          "specific content based on the research and resume provided.\n\n" +
          "Subject Line. Under 60 characters. Specific to the recruiter or company, and relevant to the resume type selected. " +
          "For Automation roles use subject lines that reference efficiency, automation, or saving time. " +
          "For Coding roles reference engineering, shipping software, or a specific tech stack. " +
          "For Data Entry roles reference data quality, reporting, or clean data. " +
          "Never use generic subjects like 'Exciting Opportunity' or 'Quick Question.'\n\n" +
          "BODY TEMPLATE - follow this structure closely, filling in the brackets with specific details:\n\n" +
          "\"I really [word/phrase that represents engagement] your [recent activity] about " +
          "[action that they took]. [How their journey resonates with you personally]\n\n" +
          "I'm a 3rd-year Nanotechnology Engineering student with a minor in Combinatorics and Optimization " +
          "at the University of Waterloo in the [resume subject] niche. " +
          "Having worked in the industry for over 3 years, I figured that companies like yours often face " +
          "[Challenges that the company faces or you can infer from the company research] challenges. " +
          "The reason for this could be [Reason you infer based on the challenges the company faces]. " +
          "Having worked with [technologies/buzzwords with real metrics that would help significantly to the challenges the company is facing] " +
          "in overcoming [What you did to resolve similar challenges to what the company is facing] challenges (get from resume), " +
          "I feel that I could help you do the same\n\n" +
          "Do you think we can set aside 10 mins for a quick feedback session? " +
          "Feel free to say no. I understand people are busy.\n\n" +
          "Thanks,\nJustin Mak\"\n\n" +
          "IMPORTANT RULES:\n" +
          "- Fill every bracket with specific, researched content. Never leave brackets in the output.\n" +
          "- The body should be dense with industry buzzwords that feel natural but signal deep technical fluency.\n" +
          "- Frame everything from the recipient's perspective - they should benefit more than Justin.\n" +
          "- If the context doesn't support strong personalization in the opening, flag it rather than fabricating.\n" +
          "- DO NOT open with 'I hope you are doing well' or any filler pleasantry.\n" +
          "- Use [RECRUITER_FIRST_NAME] as placeholder for the recruiter's first name.\n\n" +
          "HARD RULE: Never use em dashes anywhere in the email. Use commas, periods, or hyphens instead.",
      },
    ],
  },
  {
    id: 4,
    name: "Email Drafter",
    description: "Create Gmail drafts for review",
    script: "04_workflow/draft_emails.py",
    options: [
      { flag: "--dry-run", label: "Dry Run", type: "boolean", default: false },
      { flag: "--company", label: "Single Company", type: "text", default: "" },
      { flag: "-v", label: "Verbose", type: "boolean", default: false },
    ],
  },
  {
    id: 5,
    name: "Email Review",
    description: "QA check emails + resumes",
    script: "05_workflow/review_emails.py",
    options: [
      { flag: "--company", label: "Single Company", type: "text", default: "" },
      { flag: "-v", label: "Verbose", type: "boolean", default: false },
    ],
  },
  {
    id: 6,
    name: "Email Sender",
    description: "Send emails via Gmail SMTP",
    script: "06_workflow/send_emails.py",
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
    "[INFO] Found 15 unique contacts to research",
    "[INFO] Researching: Jane Smith (jane@acme.com) @ Acme Corp",
    "[INFO]     Searching: \"Jane Smith\" \"Acme Corp\"",
    "[INFO]     Scraping: https://linkedin.com/in/janesmith (score=10)",
    "[INFO]   ✓ Saved jane_at_acmecom.json",
    "[INFO] Researching: Bob Jones (bob@globex.com) @ Globex Inc",
    "[OK] Researched 15 contacts → output/person_research/",
  ],
  3: [
    "[INFO] Loading company summaries...",
    "[INFO] Found 12 company profiles",
    "[INFO] Generating email templates...",
    "[INFO] Processing template for Acme Corp...",
    "[INFO] Processing template for Globex Inc...",
    "[OK] Generated 12 personalized templates",
    "[OK] Templates saved to output/emails/",
  ],
  4: [
    "[INFO] Authenticating with Gmail API...",
    "[OK] Authenticated as user@gmail.com",
    "[INFO] Loading email templates...",
    "[INFO] Creating draft for hiring@acme.com...",
    "[INFO] Creating draft for jobs@globex.com...",
    "[OK] Created 12 drafts in Gmail",
  ],
  5: [
    "[INFO] Loading drafts for review...",
    "[INFO] Checking email 1/12: Acme Corp...",
    "[WARN] Email to Globex Inc has no resume attachment",
    "[INFO] Checking email 3/12: Initech...",
    "[OK] 11/12 emails passed QA",
    "[WARN] 1 email flagged for review",
  ],
  6: [
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
  if (stepId === 5 && Math.random() < 0.15) {
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

export type PipelineStatus = "idle" | "running" | "success" | "error";

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

  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus>("idle");
  const [pipelineStepIndex, setPipelineStepIndex] = useState(0);
  const pipelineAborted = useRef(false);

  const updateStepState = useCallback((stepId: number, patch: Partial<StepState>) => {
    setStepStates((prev) => ({
      ...prev,
      [stepId]: { ...prev[stepId], ...patch },
    }));
  }, []);

  const MAX_LOG_LINES = 500;

  const appendOutput = useCallback((stepId: number, line: string) => {
    setStepStates((prev) => {
      const existing = prev[stepId].output;
      const updated = existing.length >= MAX_LOG_LINES
        ? [...existing.slice(-MAX_LOG_LINES + 1), line]
        : [...existing, line];
      return { ...prev, [stepId]: { ...prev[stepId], output: updated } };
    });
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

  const runAll = useCallback(async () => {
    pipelineAborted.current = false;
    setPipelineStatus("running");

    for (let i = 0; i < WORKFLOW_STEPS.length; i++) {
      if (pipelineAborted.current) break;

      const step = WORKFLOW_STEPS[i];
      setPipelineStepIndex(i);

      const controller = new AbortController();
      abortControllers.current[step.id] = controller;

      updateStepState(step.id, {
        status: "running",
        output: [],
        startedAt: Date.now(),
        finishedAt: null,
      });

      const args = stepOptions[step.id] || {};
      let success: boolean;

      try {
        success = await executeStep(step.id, args, (line) => {
          appendOutput(step.id, line);
        }, controller.signal);
      } catch (err) {
        if (controller.signal.aborted) {
          // User stopped the pipeline
          setPipelineStatus("error");
          return;
        }
        appendOutput(step.id, "[WARN] Backend unavailable, using mock output");
        success = await mockExecuteStep(step.id, args, (line) => {
          appendOutput(step.id, line);
        });
      } finally {
        delete abortControllers.current[step.id];
      }

      updateStepState(step.id, {
        status: success ? "success" : "error",
        finishedAt: Date.now(),
      });

      if (!success) {
        setPipelineStatus("error");
        return;
      }
    }

    if (!pipelineAborted.current) {
      setPipelineStatus("success");
    }
  }, [stepOptions, updateStepState, appendOutput]);

  const stopAll = useCallback(async () => {
    pipelineAborted.current = true;

    // Find and abort the currently running step
    const runningStep = WORKFLOW_STEPS.find(
      (s) => abortControllers.current[s.id]
    );

    if (runningStep) {
      await stopStep(runningStep.id);
    }

    setPipelineStatus("error");
  }, [stopStep]);

  return {
    stepStates, stepOptions, setOption, runStep, stopStep,
    pipelineStatus, pipelineStepIndex, runAll, stopAll,
  };
}
