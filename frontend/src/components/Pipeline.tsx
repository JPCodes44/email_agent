import { WORKFLOW_STEPS } from "../hooks/useWorkflow";
import type { StepState } from "../hooks/useWorkflow";
import WorkflowStep from "./WorkflowStep";

interface PipelineProps {
  stepStates: Record<number, StepState>;
  stepOptions: Record<number, Record<string, string | number | boolean>>;
  onRun: (stepId: number) => void;
  onStop: (stepId: number) => void;
  onSetOption: (stepId: number, flag: string, value: string | number | boolean) => void;
}

export default function Pipeline({ stepStates, stepOptions, onRun, onStop, onSetOption }: PipelineProps) {
  return (
    <div className="flex flex-col gap-1">
      {WORKFLOW_STEPS.map((step, i) => (
        <div key={step.id}>
          <WorkflowStep
            config={step}
            state={stepStates[step.id]}
            options={stepOptions[step.id]}
            onRun={() => onRun(step.id)}
            onStop={() => onStop(step.id)}
            onSetOption={(flag, value) => onSetOption(step.id, flag, value)}
          />
          {i < WORKFLOW_STEPS.length - 1 && (
            <div className="flex justify-center py-1">
              <div className="w-0.5 h-6 bg-border-subtle rounded-full" />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
