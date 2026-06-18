import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { motion } from "framer-motion";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  MarkerType
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Activity,
  Archive,
  BookOpen,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  Database,
  FileText,
  GitBranch,
  LayoutDashboard,
  Loader2,
  Play,
  Save,
  ShieldCheck,
  Sparkles,
  Terminal,
  Workflow,
  XCircle
} from "lucide-react";
import "./styles.css";

const API = "";

function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

const nodeTypes = { motif: MotifNode };

function Button({ children, variant = "default", size = "md", className, disabled, ...props }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 border font-semibold transition focus:outline-none focus:ring-2 focus:ring-brand/25 disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-10 px-4 text-sm",
        variant === "primary" && "border-brand bg-brand text-white shadow-sm hover:bg-brand/90",
        variant === "ghost" && "border-transparent bg-transparent text-quiet hover:bg-slate-100 hover:text-ink",
        variant === "outline" && "border-line bg-white text-ink hover:bg-slate-50",
        variant === "default" && "border-line bg-white text-ink shadow-sm hover:bg-slate-50",
        className
      )}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}

function Field({ label, children }) {
  return (
    <label className="grid gap-2 text-xs font-bold uppercase tracking-[0.12em] text-quiet">
      {label}
      {children}
    </label>
  );
}

function Textarea(props) {
  return (
    <textarea
      className="min-h-28 w-full resize-none border border-line bg-white px-3 py-3 text-sm text-ink shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-brand/10"
      {...props}
    />
  );
}

function Input(props) {
  return (
    <input
      className="h-10 w-full border border-line bg-white px-3 text-sm text-ink shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-brand/10"
      {...props}
    />
  );
}

function Select(props) {
  return (
    <select
      className="h-10 w-full border border-line bg-white px-3 text-sm font-medium text-ink shadow-sm outline-none transition focus:border-brand focus:ring-4 focus:ring-brand/10"
      {...props}
    />
  );
}

function MotifNode({ data }) {
  const palette = {
    compiler: "border-blue/25 bg-blue/5 text-blue",
    runtime: "border-amber/25 bg-amber/5 text-amber",
    terminal: "border-brand/25 bg-brand/5 text-brand",
    evidence: "border-brand/25 bg-brand/5 text-brand",
    claim: "border-blue/25 bg-blue/5 text-blue",
    output: "border-brand/25 bg-brand/5 text-brand",
    error: "border-rose/25 bg-rose/5 text-rose",
    assumption: "border-amber/25 bg-amber/5 text-amber",
    state: "border-slate-300 bg-slate-50 text-slate-600"
  };
  return (
    <div className="w-[230px] border border-line bg-white p-3 shadow-soft">
      <div className="flex items-start gap-2">
        <span className={cx("mt-0.5 h-2.5 w-2.5 shrink-0 border", palette[data.kind] || palette.state)} />
        <div className="min-w-0">
          <div className="truncate text-sm font800 text-ink">{data.label}</div>
          <div className="mt-1 line-clamp-4 text-xs leading-5 text-quiet">{data.body}</div>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [boot, setBoot] = useState({ domains: [], runs: [], samples: {} });
  const [activeRun, setActiveRun] = useState(null);
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [request, setRequest] = useState("Verify CRAR using examples/crar_mismatch.csv");
  const [sampleKey, setSampleKey] = useState("dccb_mismatch");
  const [domain, setDomain] = useState("dccb_audit");
  const [domainName, setDomainName] = useState("Healthcare claims policy");
  const [authorityMaterial, setAuthorityMaterial] = useState("Claims must cite source documents. Contradictory evidence should be escalated. Missing required evidence should block final approval.");
  const [proposal, setProposal] = useState(null);
  const [loading, setLoading] = useState("");
  const [tab, setTab] = useState("graph");
  const [error, setError] = useState("");

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    const sample = boot.samples?.[sampleKey];
    if (sample) {
      setRequest(sample.request);
      setDomain(sample.domain);
    }
  }, [sampleKey, boot.samples]);

  useEffect(() => {
    setNodes(graph.nodes || []);
    setEdges(formatEdges(graph.edges || []));
  }, [graph]);

  async function refresh() {
    try {
      const data = await api("/api/bootstrap");
      setBoot(data);
      if (data.runs?.[0] && !activeRun) {
        const detail = await api(`/api/runs/${data.runs[0].id}`);
        setActiveRun(detail.run);
        setGraph(detail.graph);
      }
    } catch (exc) {
      setError(exc.message);
    }
  }

  async function runMotifVM() {
    setLoading("run");
    setError("");
    try {
      const data = await api("/api/runs", {
        method: "POST",
        body: { request, domain, sampleKey }
      });
      setActiveRun(data.run);
      setGraph(data.graph);
      const fresh = await api("/api/runs");
      setBoot((previous) => ({ ...previous, runs: fresh.runs }));
      setTab("graph");
    } catch (exc) {
      setError(exc.message);
    } finally {
      setLoading("");
    }
  }

  async function propose() {
    setLoading("proposal");
    setError("");
    try {
      const data = await api("/api/invariants/propose", {
        method: "POST",
        body: { domainName, authorityMaterial, examples: request }
      });
      setProposal(data);
      setTab("domain");
    } catch (exc) {
      setError(exc.message);
    } finally {
      setLoading("");
    }
  }

  async function saveLayout() {
    if (!activeRun) return;
    await api(`/api/runs/${activeRun.id}/layout`, {
      method: "PUT",
      body: { positions: Object.fromEntries(nodes.map((node) => [node.id, node.position])) }
    });
  }

  const onNodesChange = useCallback((changes) => setNodes((items) => applyNodeChanges(changes, items)), []);
  const onEdgesChange = useCallback((changes) => setEdges((items) => applyEdgeChanges(changes, items)), []);
  const onConnect = useCallback((connection) => setEdges((items) => addEdge(connection, items)), []);

  const state = activeRun?.state || {};
  const frame = state.motifFrame || {};
  const plan = state.reasoningPlan || {};
  const failed = (state.invariants || []).filter((item) => !item.passed && item.severity === "error");
  const samples = Object.entries(boot.samples || {});

  return (
    <ReactFlowProvider>
      <div className="min-h-screen bg-paper text-ink">
        <Header />
        <main className="grid min-h-[calc(100vh-64px)] grid-cols-1 pt-16 xl:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="border-b border-line bg-white/82 p-4 xl:border-b-0 xl:border-r">
            <div className="mb-4 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-quiet">
              <Database className="h-4 w-4" />
              Local SQLite workspace
            </div>
            <div className="grid gap-3">
              <Field label="Sample artifact">
                <Select value={sampleKey} onChange={(event) => setSampleKey(event.target.value)}>
                  {samples.map(([key, sample]) => (
                    <option value={key} key={key}>
                      {sample.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Domain profile">
                <Select value={domain} onChange={(event) => setDomain(event.target.value)}>
                  <option value="dccb_audit">DCCB CRAR Audit</option>
                  <option value="code_review">Code Review Security</option>
                  <option value="">Custom / generic</option>
                </Select>
              </Field>
              <Field label="Task">
                <Textarea value={request} onChange={(event) => setRequest(event.target.value)} />
              </Field>
              <Button variant="primary" onClick={runMotifVM} disabled={loading === "run"}>
                {loading === "run" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Run MotifVM
              </Button>
            </div>

            <div className="mt-8">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-xs font-bold uppercase tracking-[0.12em] text-quiet">Run history</div>
                <Activity className="h-4 w-4 text-quiet" />
              </div>
              <div className="grid gap-2">
                {(boot.runs || []).map((run) => (
                  <button
                    key={run.id}
                    onClick={async () => {
                      const data = await api(`/api/runs/${run.id}`);
                      setActiveRun(data.run);
                      setGraph(data.graph);
                    }}
                    className={cx(
                      "border border-line bg-white p-3 text-left transition hover:border-brand/30 hover:bg-slate-50",
                      activeRun?.id === run.id && "border-brand/40 bg-brand/5"
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font800">{run.title}</span>
                      <StatusPill status={run.status} />
                    </div>
                    <div className="mt-1 truncate text-xs text-quiet">{run.failure_class || run.domain || "generic"}</div>
                  </button>
                ))}
              </div>
            </div>
          </aside>

          <section className="min-w-0">
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="border-b border-line bg-white/76 px-6 py-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="text-xs font-bold uppercase tracking-[0.12em] text-brand">Domain-parametric reasoning workbench</div>
                  <h1 className="mt-1 font-display text-3xl font850 leading-tight text-ink">
                    LLM proposes invariants. MotifVM verifies state.
                  </h1>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={() => setTab("domain")}>
                    <Sparkles className="h-4 w-4" />
                    Bootstrap invariants
                  </Button>
                  <Button variant="outline" onClick={saveLayout} disabled={!activeRun}>
                    <Save className="h-4 w-4" />
                    Save layout
                  </Button>
                </div>
              </div>
              {error && <div className="mt-3 border border-rose/20 bg-rose/5 px-3 py-2 text-sm text-rose">{error}</div>}
            </motion.div>

            <div className="grid grid-cols-1 gap-0 2xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="min-w-0">
                <Tabs tab={tab} setTab={setTab} />
                {tab === "graph" && (
                  <div className="h-[680px] min-h-[560px] bg-[#f8fafc] 2xl:h-[calc(100vh-200px)]">
                    <ReactFlow
                      nodes={nodes}
                      edges={edges}
                      onNodesChange={onNodesChange}
                      onEdgesChange={onEdgesChange}
                      onConnect={onConnect}
                      nodeTypes={nodeTypes}
                      fitView
                      minZoom={0.25}
                    >
                      <Background color="#d9e2ea" gap={24} />
                      <MiniMap pannable zoomable nodeStrokeWidth={3} />
                      <Controls />
                    </ReactFlow>
                  </div>
                )}
                {tab === "trace" && <TracePanel state={state} />}
                {tab === "audit" && <AuditPanel run={activeRun} />}
                {tab === "domain" && (
                  <DomainPanel
                    domainName={domainName}
                    setDomainName={setDomainName}
                    authorityMaterial={authorityMaterial}
                    setAuthorityMaterial={setAuthorityMaterial}
                    proposal={proposal}
                    propose={propose}
                    loading={loading}
                  />
                )}
              </div>

              <aside className="border-t border-line bg-white p-4 2xl:border-l 2xl:border-t-0">
                <Inspector run={activeRun} frame={frame} plan={plan} failed={failed} />
              </aside>
            </div>
          </section>
        </main>
      </div>
    </ReactFlowProvider>
  );
}

function Header() {
  return (
    <header className="fixed inset-x-0 top-0 z-20 flex h-16 items-center justify-between border-b border-line bg-white/86 px-5 backdrop-blur-xl">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center border border-brand/25 bg-brand/10 text-sm font900 text-brand">M</div>
        <div>
        <div className="text-sm font900 leading-none">MotifVM Workbench</div>
          <div className="mt-1 text-xs text-quiet">Domain-parametric reasoning CI</div>
        </div>
      </div>
      <div className="hidden items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-quiet lg:flex">
        <ShieldCheck className="h-4 w-4 text-brand" />
        Runtime guarantees, not domain omniscience
      </div>
    </header>
  );
}

function Tabs({ tab, setTab }) {
  const tabs = [
    ["graph", Workflow, "Graph"],
    ["trace", GitBranch, "Trace"],
    ["audit", Archive, "Audit"],
    ["domain", Sparkles, "Domain"]
  ];
  return (
    <div className="flex border-b border-line bg-white px-4">
      {tabs.map(([id, Icon, label]) => (
        <button
          key={id}
          onClick={() => setTab(id)}
          className={cx(
            "flex h-12 items-center gap-2 border-b-2 px-3 text-sm font-semibold transition",
            tab === id ? "border-brand text-ink" : "border-transparent text-quiet hover:text-ink"
          )}
        >
          <Icon className="h-4 w-4" />
          {label}
        </button>
      ))}
    </div>
  );
}

function Inspector({ run, frame, plan, failed }) {
  const risk = Object.entries(frame.risk || {}).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const policy = plan.verificationPolicy || {};
  return (
    <div className="grid gap-4">
      <section>
        <div className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-quiet">Terminal state</div>
        <div className="border border-line bg-slate-50 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="font800">{run?.status || "No run yet"}</span>
            {run?.status === "committed_success" ? <CheckCircle2 className="h-5 w-5 text-brand" /> : <XCircle className="h-5 w-5 text-rose" />}
          </div>
          <p className="mt-1 text-sm text-quiet">{run?.failureClass || "No terminal failure class."}</p>
        </div>
      </section>

      <section>
        <div className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-quiet">Motif risk</div>
        <div className="grid gap-2">
          {risk.map(([key, value]) => (
            <div key={key}>
              <div className="mb-1 flex justify-between text-xs">
                <span className="font-semibold text-ink">{key}</span>
                <span className="text-quiet">{Number(value).toFixed(2)}</span>
              </div>
              <div className="h-2 bg-slate-100">
                <div className="h-2 bg-brand" style={{ width: `${Math.min(100, value * 100)}%` }} />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-quiet">Reasoning plan</div>
        <div className="border border-line bg-white p-3">
          <div className="text-sm font800">{policy.strength || "unknown"} verification</div>
          <p className="mt-1 text-xs leading-5 text-quiet">{plan.rationale || "Run a task to compile a plan."}</p>
          <div className="mt-3 flex flex-wrap gap-1">
            {(plan.selectedPasses || []).map((pass) => (
              <span key={pass} className="border border-line bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-600">
                {pass}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-quiet">Invariant failures</div>
        <div className="grid gap-2">
          {failed.length === 0 ? (
            <div className="border border-line bg-brand/5 p-3 text-sm text-brand">No terminal invariant failures.</div>
          ) : (
            failed.map((item) => (
              <div key={item.invariantId} className="border border-rose/20 bg-rose/5 p-3">
                <div className="text-sm font800 text-rose">{item.invariantId}</div>
                <p className="mt-1 text-xs leading-5 text-quiet">{item.message}</p>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function TracePanel({ state }) {
  const events = [
    ["Task", state.taskAst?.goal || "No task loaded"],
    ["MotifFrame", summarizeRisk(state.motifFrame)],
    ["ReasoningPlan", `${state.reasoningPlan?.selectedPasses?.length || 0} passes selected`],
    ["StatePatches", `${state.patchTimeline?.length || 0} patch timeline records`],
    ["Invariants", `${state.invariants?.length || 0} invariant checks`],
    ["Replan", state.replanEvents?.[0] ? `${state.replanEvents[0].failureClass} -> ${state.replanEvents[0].action}` : "No replan event"],
    ["TerminalState", `${state.status || "none"} / ${state.failureClass || "none"}`]
  ];
  return (
    <div className="p-6">
      <div className="max-w-4xl border border-line bg-white p-4 shadow-soft">
        <div className="mb-4 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-brand">
          <GitBranch className="h-4 w-4" />
          Compiler trace
        </div>
        <ol className="grid gap-3">
          {events.map(([label, body], index) => (
            <li key={label} className="grid grid-cols-[44px_180px_minmax(0,1fr)] items-start gap-4 border-b border-line pb-3 last:border-0">
              <span className="font-mono text-sm font800 text-amber">{String(index + 1).padStart(2, "0")}</span>
              <span className="font800 text-ink">{label}</span>
              <span className="text-sm text-quiet">{body}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function AuditPanel({ run }) {
  const state = run?.state || {};
  const files = ["state.json", "motif_frame.json", "reasoning_plan.json", "graph.json", "lineage.json", "extracted_facts.json", "patch_timeline.json", "report.md"];
  return (
    <div className="grid gap-4 p-6 lg:grid-cols-[320px_minmax(0,1fr)]">
      <div className="border border-line bg-white p-4 shadow-soft">
        <div className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-brand">
          <FileText className="h-4 w-4" />
          Audit pack surface
        </div>
        <div className="grid gap-2">
          {files.map((file) => (
            <div key={file} className="border border-line bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-600">
              {file}
            </div>
          ))}
        </div>
      </div>
      <pre className="max-h-[620px] overflow-auto border border-line bg-white p-4 text-xs leading-5 text-slate-700 shadow-soft">
        {run?.report || JSON.stringify(state, null, 2)}
      </pre>
    </div>
  );
}

function DomainPanel({ domainName, setDomainName, authorityMaterial, setAuthorityMaterial, proposal, propose, loading }) {
  return (
    <div className="grid gap-4 p-6 lg:grid-cols-[420px_minmax(0,1fr)]">
      <div className="border border-line bg-white p-4 shadow-soft">
        <div className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-brand">
          <BrainCircuit className="h-4 w-4" />
          LLM invariant authoring assistant
        </div>
        <p className="mb-4 text-sm leading-6 text-quiet">
          The LLM proposes. MotifVM stores, versions, tests, and enforces. Invariants are to MotifVM what tests are to CI.
        </p>
        <div className="grid gap-3">
          <Field label="Domain name">
            <Input value={domainName} onChange={(event) => setDomainName(event.target.value)} />
          </Field>
          <Field label="Authority material / expert notes">
            <Textarea value={authorityMaterial} onChange={(event) => setAuthorityMaterial(event.target.value)} />
          </Field>
          <Button variant="primary" onClick={propose} disabled={loading === "proposal"}>
            {loading === "proposal" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            Propose invariants
          </Button>
        </div>
      </div>

      <div className="border border-line bg-white p-4 shadow-soft">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="text-xs font-bold uppercase tracking-[0.12em] text-brand">Proposed domain pack</div>
          {proposal?.provider && <span className="border border-line bg-slate-50 px-2 py-1 text-xs font-semibold text-quiet">{proposal.provider}</span>}
        </div>
        {!proposal ? (
          <div className="grid min-h-[320px] place-items-center border border-dashed border-line bg-slate-50 text-center">
            <div>
              <Boxes className="mx-auto mb-3 h-8 w-8 text-quiet" />
              <p className="max-w-sm text-sm text-quiet">Add policy text or examples, then ask the assistant to propose inspectable invariants.</p>
            </div>
          </div>
        ) : (
          <div className="grid gap-4">
            <p className="text-sm leading-6 text-quiet">{proposal.summary}</p>
            <div className="grid gap-2">
              {(proposal.invariants || []).map((item) => (
                <div key={item.id || item.name} className="border border-line bg-slate-50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font800 text-ink">{item.name}</span>
                    <span className="text-xs font-bold uppercase tracking-wide text-rose">{item.severity}</span>
                  </div>
                  <p className="mt-1 text-sm text-quiet">{item.check}</p>
                  <p className="mt-2 text-xs text-slate-500">Authority: {item.authority}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const ok = status === "committed_success";
  return (
    <span className={cx("shrink-0 border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide", ok ? "border-brand/20 bg-brand/10 text-brand" : "border-rose/20 bg-rose/10 text-rose")}>
      {ok ? "pass" : "fail"}
    </span>
  );
}

function summarizeRisk(frame = {}) {
  const top = Object.entries(frame.risk || {}).sort((a, b) => b[1] - a[1]).slice(0, 3);
  return top.map(([key, value]) => `${key} ${Number(value).toFixed(2)}`).join(", ") || "No motif frame";
}

function formatEdges(rawEdges) {
  return rawEdges.map((edge) => ({
    ...edge,
    markerEnd: { type: MarkerType.ArrowClosed, color: "#8aa0b4" },
    style: { stroke: edge.animated ? "#0f766e" : "#8aa0b4", strokeWidth: edge.animated ? 2 : 1.4 },
    labelStyle: { fill: "#526272", fontWeight: 700, fontSize: 11 }
  }));
}

createRoot(document.getElementById("root")).render(<App />);
