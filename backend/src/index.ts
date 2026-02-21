import { spawn } from "bun";
import { resolve } from "path";

const PORT = 3001;
const WORKFLOWS_DIR = resolve(import.meta.dir, "../workflows");
function findPython(): string {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;

  // Check common paths explicitly so we don't rely on the shell's PATH
  const candidates = [
    Bun.which("python3"),
    Bun.which("python"),
    "/usr/bin/python3",
    "/usr/local/bin/python3",
  ].filter(Boolean) as string[];

  for (const p of candidates) {
    if (Bun.file(p).size) return p; // verify file actually exists
  }
  return "python3"; // fallback
}

const PYTHON = findPython();
console.log(`Using Python: ${PYTHON}`);

// Map step IDs to script paths (relative to workflows/)
const STEP_SCRIPTS: Record<number, string> = {
  1: "01_workflow/main.py",
  2: "02_workflow/generate_from_csv.py",
  3: "03_workflow/draft_emails.py",
  4: "04_workflow/review_emails.py",
  5: "05_workflow/send_emails.py",
};

// Steps that require csv_path as a positional argument
const CSV_PATH = resolve(WORKFLOWS_DIR, "list.csv");
const STEPS_NEEDING_CSV = new Set([2, 5]);

// Track running processes so we can kill them
const runningProcs = new Map<number, { kill: () => void }>();

function buildArgs(options: Record<string, string | number | boolean>): string[] {
  const args: string[] = [];
  for (const [flag, value] of Object.entries(options)) {
    if (typeof value === "boolean") {
      if (value) args.push(flag);
    } else if (value !== "" && value !== undefined) {
      args.push(flag, String(value));
    }
  }
  return args;
}

function sseEvent(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

async function handleWorkflowRun(stepId: number, body: Record<string, unknown>): Promise<Response> {
  const script = STEP_SCRIPTS[stepId];
  if (!script) {
    return new Response(JSON.stringify({ error: `Unknown step: ${stepId}` }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  const options = (body.options ?? {}) as Record<string, string | number | boolean>;
  const cliArgs = buildArgs(options);
  const scriptPath = resolve(WORKFLOWS_DIR, script);

  // Prepend positional csv_path for steps that require it
  if (STEPS_NEEDING_CSV.has(stepId)) {
    cliArgs.unshift(CSV_PATH);
  }

  const stream = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder();
      const enqueue = (chunk: string) => controller.enqueue(encoder.encode(chunk));

      enqueue(sseEvent("start", { stepId, script }));

      try {
        const proc = spawn({
          cmd: [PYTHON, scriptPath, ...cliArgs],
          cwd: WORKFLOWS_DIR,
          stdout: "pipe",
          stderr: "pipe",
        });

        runningProcs.set(stepId, { kill: () => proc.kill() });

        async function streamPipe(pipe: ReadableStream<Uint8Array>, channel: string) {
          const reader = pipe.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop()!;
            for (const line of lines) {
              if (line) enqueue(sseEvent("output", { channel, line }));
            }
          }
          if (buffer) enqueue(sseEvent("output", { channel, line: buffer }));
        }

        await Promise.all([
          streamPipe(proc.stdout as ReadableStream<Uint8Array>, "stdout"),
          streamPipe(proc.stderr as ReadableStream<Uint8Array>, "stderr"),
        ]);

        const exitCode = await proc.exited;
        enqueue(sseEvent("done", { exitCode }));
      } catch (err) {
        enqueue(sseEvent("error", { message: String(err) }));
      } finally {
        runningProcs.delete(stepId);
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

const server = Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);

    // CORS for dev
    if (req.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, DELETE, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    // POST /api/workflow/:stepId — run a workflow step
    // DELETE /api/workflow/:stepId — stop a running step
    const match = url.pathname.match(/^\/api\/workflow\/(\d+)$/);
    if (match && req.method === "POST") {
      const stepId = parseInt(match[1], 10);
      const body = await req.json().catch(() => ({}));
      const response = await handleWorkflowRun(stepId, body as Record<string, unknown>);
      response.headers.set("Access-Control-Allow-Origin", "*");
      return response;
    }

    if (match && req.method === "DELETE") {
      const stepId = parseInt(match[1], 10);
      const proc = runningProcs.get(stepId);
      if (proc) {
        proc.kill();
        runningProcs.delete(stepId);
      }
      const resp = new Response(JSON.stringify({ killed: !!proc }), {
        headers: { "Content-Type": "application/json" },
      });
      resp.headers.set("Access-Control-Allow-Origin", "*");
      return resp;
    }

    return new Response("Not found", { status: 404 });
  },
});

console.log(`Backend API server running on http://localhost:${server.port}`);
