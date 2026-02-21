import Pipeline from "./components/Pipeline";
import { useWorkflow } from "./hooks/useWorkflow";

function App() {
  const { stepStates, stepOptions, setOption, runStep, stopStep } = useWorkflow();

  return (
    <div className="min-h-screen bg-surface">
      <div className="max-w-3xl mx-auto px-6 py-10">
        <header className="mb-8">
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">
            Email Agent
          </h1>
          <p className="text-text-secondary mt-1">
            Automated outreach pipeline — research, draft, review, and send.
          </p>
        </header>

        <Pipeline
          stepStates={stepStates}
          stepOptions={stepOptions}
          onRun={runStep}
          onStop={stopStep}
          onSetOption={setOption}
        />
      </div>
    </div>
  );
}

export default App;
