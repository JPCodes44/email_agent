import { spawn, $ } from "bun";
import { resolve } from "path";
import { rmSync, readdirSync, statSync, readFileSync, writeFileSync } from "fs";

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
  2: "02_workflow/research_people.py",
  3: "03_workflow/generate_from_csv.py",
  4: "04_workflow/draft_emails.py",
  5: "05_workflow/review_emails.py",
  6: "06_workflow/send_emails.py",
};

// Steps that require csv_path as a positional argument
const CSV_PATH = resolve(WORKFLOWS_DIR, "list.csv");
const STEPS_NEEDING_CSV = new Set([2, 3, 6]);

// Track running processes so we can kill them (store PID to kill entire process tree)
const runningProcs = new Map<number, { pid: number; kill: () => void }>();

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
          cmd: ["setsid", PYTHON, scriptPath, ...cliArgs],
          cwd: WORKFLOWS_DIR,
          stdout: "pipe",
          stderr: "pipe",
        });

        runningProcs.set(stepId, {
          pid: proc.pid,
          kill: () => {
            // Kill the entire process group (setsid makes proc the group leader)
            try { process.kill(-proc.pid, "SIGKILL"); } catch { /* already dead */ }
          },
        });

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
        // Don't remove from runningProcs here — let the stream's finally{} block
        // clean it up once the process is confirmed dead. This way GET /api/workflows
        // still shows it while it's being killed.
      }
      const resp = new Response(JSON.stringify({ killed: !!proc }), {
        headers: { "Content-Type": "application/json" },
      });
      resp.headers.set("Access-Control-Allow-Origin", "*");
      return resp;
    }

    // GET /api/workflows — list all running workflows (verify PIDs are alive)
    if (url.pathname === "/api/workflows" && req.method === "GET") {
      const workflows: { stepId: number; pid: number; script: string }[] = [];
      for (const [stepId, proc] of runningProcs.entries()) {
        try {
          // signal 0 checks if process exists without killing it
          process.kill(proc.pid, 0);
          workflows.push({ stepId, pid: proc.pid, script: STEP_SCRIPTS[stepId] });
        } catch {
          // Process is dead — clean up stale entry
          runningProcs.delete(stepId);
        }
      }
      const resp = new Response(JSON.stringify({ workflows }), {
        headers: { "Content-Type": "application/json" },
      });
      resp.headers.set("Access-Control-Allow-Origin", "*");
      return resp;
    }

    // DELETE /api/output/emails — clear email templates (SSE stream)
    if (url.pathname === "/api/output/emails" && req.method === "DELETE") {
      const dir = resolve(WORKFLOWS_DIR, "output/emails");
      const stream = new ReadableStream({
        async start(controller) {
          const encoder = new TextEncoder();
          const log = (line: string) => controller.enqueue(encoder.encode(sseEvent("output", { line })));

          try {
            log("[INFO] Removing local email templates...");
            rmSync(dir, { recursive: true, force: true });
            log("[OK] Deleted output/emails directory");

            log("[INFO] Deleting Gmail drafts via IMAP...");
            const clearDrafts = spawn({
              cmd: [PYTHON, resolve(WORKFLOWS_DIR, "shared/clear_drafts.py")],
              cwd: WORKFLOWS_DIR,
              stdout: "pipe",
              stderr: "pipe",
            });

            // Stream clear_drafts.py output
            async function streamPipe(pipe: ReadableStream<Uint8Array>) {
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
                  if (line) log(line);
                }
              }
              if (buffer) log(buffer);
            }

            await Promise.all([
              streamPipe(clearDrafts.stdout as ReadableStream<Uint8Array>),
              streamPipe(clearDrafts.stderr as ReadableStream<Uint8Array>),
            ]);
            await clearDrafts.exited;
            log("[OK] Gmail drafts cleared");

            log("[INFO] Clearing EmailLink column in CSV...");
            const csv = readFileSync(CSV_PATH, "utf-8");
            const lines = csv.split("\n");
            const header = lines[0].split(",");
            const linkIdx = header.findIndex((h) => h.trim() === "EmailLink");
            if (linkIdx !== -1) {
              for (let i = 1; i < lines.length; i++) {
                if (!lines[i].trim()) continue;
                const fields: string[] = [];
                let current = "";
                let inQuotes = false;
                for (const ch of lines[i]) {
                  if (ch === '"') { inQuotes = !inQuotes; current += ch; }
                  else if (ch === "," && !inQuotes) { fields.push(current); current = ""; }
                  else { current += ch; }
                }
                fields.push(current);
                if (linkIdx < fields.length) fields[linkIdx] = "";
                lines[i] = fields.join(",");
              }
              writeFileSync(CSV_PATH, lines.join("\n"), "utf-8");
              log("[OK] EmailLink column cleared");
            } else {
              log("[INFO] No EmailLink column found, skipping");
            }

            controller.enqueue(encoder.encode(sseEvent("done", { exitCode: 0 })));
          } catch (err) {
            log(`[ERROR] ${String(err)}`);
            controller.enqueue(encoder.encode(sseEvent("done", { exitCode: 1 })));
          } finally {
            controller.close();
          }
        },
      });

      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    // DELETE /api/output/research/companies — clear company research batches (SSE stream)
    if (url.pathname === "/api/output/research/companies" && req.method === "DELETE") {
      const outputDir = resolve(WORKFLOWS_DIR, "output");
      const stream = new ReadableStream({
        async start(controller) {
          const encoder = new TextEncoder();
          const log = (line: string) => controller.enqueue(encoder.encode(sseEvent("output", { line })));

          try {
            log("[INFO] Scanning output directory...");
            const entries = readdirSync(outputDir);
            const skip = new Set(["emails", "person_research"]);
            const dirs = entries.filter((e) => !skip.has(e) && statSync(resolve(outputDir, e)).isDirectory());

            if (dirs.length === 0) {
              log("[INFO] No company research directories to clear");
            } else {
              log(`[INFO] Found ${dirs.length} director${dirs.length === 1 ? "y" : "ies"} to remove`);
              for (const entry of dirs) {
                const fullPath = resolve(outputDir, entry);
                rmSync(fullPath, { recursive: true, force: true });
                log(`[OK] Removed ${entry}/`);
              }
            }

            log("[OK] Company research cleared");
            controller.enqueue(encoder.encode(sseEvent("done", { exitCode: 0 })));
          } catch (err) {
            log(`[ERROR] ${String(err)}`);
            controller.enqueue(encoder.encode(sseEvent("done", { exitCode: 1 })));
          } finally {
            controller.close();
          }
        },
      });

      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    // DELETE /api/output/research/people — clear person research (SSE stream)
    if (url.pathname === "/api/output/research/people" && req.method === "DELETE") {
      const dir = resolve(WORKFLOWS_DIR, "output/person_research");
      const stream = new ReadableStream({
        async start(controller) {
          const encoder = new TextEncoder();
          const log = (line: string) => controller.enqueue(encoder.encode(sseEvent("output", { line })));

          try {
            log("[INFO] Removing person research...");
            rmSync(dir, { recursive: true, force: true });
            log("[OK] Person research cleared");
            controller.enqueue(encoder.encode(sseEvent("done", { exitCode: 0 })));
          } catch (err) {
            log(`[ERROR] ${String(err)}`);
            controller.enqueue(encoder.encode(sseEvent("done", { exitCode: 1 })));
          } finally {
            controller.close();
          }
        },
      });

      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    return new Response("Not found", { status: 404 });
  },
});

console.log(`Backend API server running on http://localhost:${server.port}`);
