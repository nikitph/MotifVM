from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motifvm.runtime import run_task  # noqa: E402
from motifvm.reporting import render_report  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent / ".data"
DB_PATH = DATA_DIR / "motifvm_product.sqlite"
PORT = int(os.environ.get("MOTIFVM_PRODUCT_API_PORT", "8787"))

SAMPLE_INPUTS = {
    "dccb_good": {
        "label": "DCCB CRAR success",
        "domain": "dccb_audit",
        "request": "Verify CRAR using examples/crar_good.csv",
        "inputFiles": ["examples/crar_good.csv"],
    },
    "dccb_mismatch": {
        "label": "DCCB reported mismatch",
        "domain": "dccb_audit",
        "request": "Verify CRAR using examples/crar_mismatch.csv",
        "inputFiles": ["examples/crar_mismatch.csv"],
    },
    "code_auth": {
        "label": "Code review auth bypass",
        "domain": "code_review",
        "request": "Review this code diff for security risk",
        "inputFiles": ["examples/code_review/unsafe_auth_bypass/diff.patch"],
    },
    "code_safe": {
        "label": "Code review safe diff",
        "domain": "code_review",
        "request": "Review this code diff for security risk",
        "inputFiles": ["examples/code_review/safe/diff.patch"],
    },
}


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS domains (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              slug TEXT NOT NULL UNIQUE,
              description TEXT NOT NULL,
              authority_material TEXT NOT NULL,
              invariants_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS invariant_proposals (
              id TEXT PRIMARY KEY,
              domain_id TEXT,
              provider TEXT NOT NULL,
              input_json TEXT NOT NULL,
              output_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              request TEXT NOT NULL,
              domain TEXT,
              sample_key TEXT,
              status TEXT NOT NULL,
              failure_class TEXT,
              state_json TEXT NOT NULL,
              report_md TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS graph_layouts (
              run_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              x REAL NOT NULL,
              y REAL NOT NULL,
              PRIMARY KEY (run_id, node_id)
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
              id TEXT PRIMARY KEY,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              run_id TEXT,
              proposal_id TEXT,
              created_at TEXT NOT NULL
            );
            """
        )
        count = conn.execute("SELECT COUNT(*) AS c FROM domains").fetchone()["c"]
        if count == 0:
            now = iso_now()
            conn.execute(
                """
                INSERT INTO domains VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("domain"),
                    "DCCB CRAR Audit",
                    "dccb-audit",
                    "A regulated audit profile where policies define CRAR computation, threshold checks, reported value reconciliation, and evidence lineage.",
                    "CRAR = (Tier I Capital + Tier II Capital) / Risk Weighted Assets * 100. Demo threshold is 9.00 percent. Reported CRAR must match computed CRAR within tolerance.",
                    json.dumps(seed_invariants("dccb_audit")),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO domains VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("domain"),
                    "Code Review Security",
                    "code-review",
                    "A security review profile where diffs become line-level evidence and invariants detect risky code changes.",
                    "Findings must trace to changed lines. Added unconditional auth allow, secret literals, shell execution, eval/exec, disabled TLS, and unsafe deserialization are terminal risks.",
                    json.dumps(seed_invariants("code_review")),
                    now,
                    now,
                ),
            )
        run_count = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
    if run_count == 0:
        create_run({"sampleKey": "dccb_mismatch"})


def seed_invariants(domain: str) -> list[dict[str, str]]:
    if domain == "code_review":
        return [
            {"id": "CODE_003", "name": "No unconditional auth allow", "severity": "error", "authority": "Code review security policy", "check": "Added lines must not bypass authorization."},
            {"id": "CODE_004", "name": "No secret literal", "severity": "error", "authority": "Code review security policy", "check": "Added lines must not introduce obvious API keys or tokens."},
        ]
    return [
        {"id": "DCCB_001", "name": "CRAR formula", "severity": "error", "authority": "DCCB audit profile", "check": "Computed CRAR must equal (Tier I + Tier II) / RWA * 100."},
        {"id": "DCCB_003", "name": "Reported CRAR match", "severity": "error", "authority": "DCCB audit profile", "check": "Reported CRAR must match computed CRAR within tolerance."},
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = "MotifVMProduct/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.json({"ok": True, "db": str(DB_PATH), "root": str(ROOT)})
        if path == "/api/bootstrap":
            return self.json({"domains": list_domains(), "runs": list_runs(), "samples": SAMPLE_INPUTS})
        if path == "/api/runs":
            return self.json({"runs": list_runs()})
        if path.startswith("/api/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            run = get_run(run_id)
            if not run:
                return self.not_found("Run not found")
            return self.json({"run": run, "graph": build_graph(run)})
        if path == "/api/domains":
            return self.json({"domains": list_domains()})
        self.not_found("Unknown endpoint")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = self.read_json()
        if path == "/api/chat":
            return self.json(chat(payload))
        if path == "/api/invariants/propose":
            return self.json(propose_invariants(payload))
        if path == "/api/runs":
            return self.json(create_run(payload))
        if path == "/api/domains":
            return self.json(create_domain(payload), status=201)
        self.not_found("Unknown endpoint")

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        payload = self.read_json()
        if path.startswith("/api/runs/") and path.endswith("/layout"):
            run_id = path.split("/")[-2]
            save_layout(run_id, payload.get("positions", {}))
            return self.json({"ok": True})
        self.not_found("Unknown endpoint")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.cors()
        self.end_headers()

    def read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.cors()
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def not_found(self, message: str) -> None:
        self.json({"error": message}, status=404)

    def cors(self) -> None:
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET,POST,PUT,OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")


def list_domains() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM domains ORDER BY updated_at DESC").fetchall()
    return [domain_row(row) for row in rows]


def domain_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "description": row["description"],
        "authorityMaterial": row["authority_material"],
        "invariants": json.loads(row["invariants_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def list_runs() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, title, request, domain, sample_key, status, failure_class, created_at FROM runs ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
    return [dict(row) for row in rows]


def get_run(run_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "request": row["request"],
        "domain": row["domain"],
        "sampleKey": row["sample_key"],
        "status": row["status"],
        "failureClass": row["failure_class"],
        "state": json.loads(row["state_json"]),
        "report": row["report_md"],
        "createdAt": row["created_at"],
    }


def create_domain(payload: dict) -> dict:
    now = iso_now()
    invariants = payload.get("invariants") or []
    name = payload.get("name") or "Untitled domain"
    slug = slugify(name)
    with db() as conn:
        domain_id = new_id("domain")
        conn.execute(
            "INSERT INTO domains VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                domain_id,
                name,
                slug,
                payload.get("description") or "Domain-parametric MotifVM profile.",
                payload.get("authorityMaterial") or "",
                json.dumps(invariants),
                now,
                now,
            ),
        )
    return {"domain": get_domain(domain_id)}


def get_domain(domain_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM domains WHERE id = ?", (domain_id,)).fetchone()
    return domain_row(row) if row else None


def create_run(payload: dict) -> dict:
    sample_key = payload.get("sampleKey") or "dccb_mismatch"
    sample = SAMPLE_INPUTS.get(sample_key, SAMPLE_INPUTS["dccb_mismatch"])
    request_text = payload.get("request") or sample["request"]
    domain = payload.get("domain") or sample.get("domain")
    input_files = payload.get("inputFiles") or sample.get("inputFiles", [])
    try:
        state = run_task(request_text, root=ROOT, domain=domain, input_files=input_files)
        report = render_report(state)
    except Exception as exc:
        state = {
            "id": new_id("state"),
            "status": "runtime_error",
            "failureClass": "runtime_error",
            "terminalReason": str(exc),
            "taskAst": {"goal": request_text, "meta": {"domain": domain}},
            "motifFrame": {},
            "reasoningPlan": {},
            "patchTimeline": [],
            "graph": {"nodes": {}, "edges": []},
            "artifacts": [],
            "invariants": [],
        }
        report = f"Runtime error\n=============\n\n{exc}"
    run_id = new_id("run")
    now = iso_now()
    title = payload.get("title") or sample["label"]
    with db() as conn:
        conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                title,
                request_text,
                domain,
                sample_key,
                state.get("status", "unknown"),
                state.get("failureClass"),
                json.dumps(state),
                report,
                now,
            ),
        )
    run = get_run(run_id)
    return {"run": run, "graph": build_graph(run)}


def chat(payload: dict) -> dict:
    message = (payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    inferred = infer_task(message)
    proposal = propose_invariants(
        {
            "domainName": inferred["domainName"],
            "authorityMaterial": message,
            "examples": message,
        }
    )
    run_payload = {
        "title": inferred["title"],
        "request": inferred["request"],
        "domain": inferred["domain"],
        "inputFiles": inferred["inputFiles"],
        "sampleKey": inferred["sampleKey"],
    }
    created = create_run(run_payload)
    run = created["run"]
    assistant = normal_assistant_response(run, proposal)
    user_id = new_id("msg")
    assistant_id = new_id("msg")
    with db() as conn:
        conn.execute(
            "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, "user", message, run["id"], proposal.get("proposalId"), iso_now()),
        )
        conn.execute(
            "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?)",
            (assistant_id, "assistant", assistant, run["id"], proposal.get("proposalId"), iso_now()),
        )
    return {
        "message": {"id": assistant_id, "role": "assistant", "content": assistant},
        "proposal": proposal,
        "run": run,
        "graph": created["graph"],
    }


def infer_task(message: str) -> dict:
    lower = message.lower()
    domain = None
    sample_key = None
    input_files: list[str] = []
    request_text = message
    domain_name = "Custom domain"
    title = "MotifVM chat run"
    if any(term in lower for term in ("crar", "tier i", "tier ii", "rwa", "dccb")):
        domain = "dccb_audit"
        domain_name = "DCCB CRAR audit"
        title = "CRAR audit chat"
        if "mismatch" in lower or "reported" in lower:
            sample_key = "dccb_mismatch"
            input_files = SAMPLE_INPUTS[sample_key]["inputFiles"]
            request_text = "Verify CRAR using examples/crar_mismatch.csv"
        elif "below" in lower or "threshold" in lower:
            input_files = ["examples/crar_below_threshold.csv"]
            request_text = "Verify CRAR using examples/crar_below_threshold.csv"
        else:
            sample_key = "dccb_good"
            input_files = SAMPLE_INPUTS[sample_key]["inputFiles"]
            request_text = "Verify CRAR using examples/crar_good.csv"
    elif any(term in lower for term in ("code", "diff", "auth", "security", "secret", "review")):
        domain = "code_review"
        domain_name = "Code review security"
        title = "Code review chat"
        if "safe" in lower:
            sample_key = "code_safe"
        else:
            sample_key = "code_auth"
        input_files = SAMPLE_INPUTS[sample_key]["inputFiles"]
        request_text = SAMPLE_INPUTS[sample_key]["request"]
    return {
        "domain": domain,
        "sampleKey": sample_key,
        "inputFiles": input_files,
        "request": request_text,
        "domainName": domain_name,
        "title": title,
    }


def normal_assistant_response(run: dict, proposal: dict) -> str:
    state = run.get("state", {})
    final = next(
        (
            artifact.get("content", {}).get("text")
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "final_output"
        ),
        None,
    )
    policy = state.get("reasoningPlan", {}).get("verificationPolicy", {}).get("strength", "standard")
    status = run.get("status")
    failure = run.get("failureClass")
    invariant_count = len(proposal.get("invariants", []))
    if final:
        prefix = final
    elif status == "committed_success":
        prefix = "I ran the task and committed a verified success state."
    else:
        prefix = "I ran the task and committed a structured failure state."
    return (
        f"{prefix}\n\n"
        f"Behind the scenes, I bootstrapped {invariant_count} invariant proposal(s), "
        f"compiled a {policy} MotifVM reasoning plan, and committed `{status}`"
        f"{f' with `{failure}`' if failure else ''}. "
        "Open the drill-down graph to inspect the MotifFrame, ReasoningPlan, patches, invariants, and audit artifacts."
    )


def propose_invariants(payload: dict) -> dict:
    provider = "mock"
    started = time.time()
    prompt_payload = {
        "domainName": payload.get("domainName"),
        "authorityMaterial": payload.get("authorityMaterial"),
        "examples": payload.get("examples"),
        "instruction": (
            "Propose MotifVM domain invariants. Return JSON with keys: "
            "summary, invariants, factSchema, fixtureIdeas. Invariants must cite authority material."
        ),
    }
    output = None
    if os.environ.get("DEEPSEEK_API_KEY"):
        try:
            output = call_deepseek(prompt_payload)
            provider = "deepseek"
        except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError, ValueError) as exc:
            output = fallback_invariants(payload, note=f"DeepSeek fallback: {exc.__class__.__name__}")
            provider = "mock_after_deepseek_error"
    else:
        output = fallback_invariants(payload)
    proposal_id = new_id("proposal")
    with db() as conn:
        conn.execute(
            "INSERT INTO invariant_proposals VALUES (?, ?, ?, ?, ?, ?)",
            (
                proposal_id,
                payload.get("domainId"),
                provider,
                json.dumps(prompt_payload),
                json.dumps(output),
                iso_now(),
            ),
        )
    output["proposalId"] = proposal_id
    output["provider"] = provider
    output["durationMs"] = round((time.time() - started) * 1000)
    return output


def call_deepseek(payload: dict) -> dict:
    body = {
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {
                "role": "system",
                "content": "You are MotifVM's invariant authoring assistant. Return only valid JSON.",
            },
            {"role": "user", "content": json.dumps(payload, sort_keys=True)},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    req = urlrequest.Request(
        f"{os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=30) as response:
        raw = json.loads(response.read().decode("utf-8"))
    content = raw["choices"][0]["message"]["content"]
    parsed = json.loads(content) if isinstance(content, str) else content
    if "invariants" not in parsed:
        raise ValueError("missing invariants")
    return parsed


def fallback_invariants(payload: dict, note: str | None = None) -> dict:
    name = payload.get("domainName") or "Custom domain"
    material = (payload.get("authorityMaterial") or "").strip()
    authority = material[:120] + ("..." if len(material) > 120 else "") if material else "Provided domain material"
    invariants = [
        {
            "id": "INV_001",
            "name": "Evidence-backed terminal output",
            "severity": "error",
            "authority": authority,
            "check": "Every terminal output must cite at least one EvidenceRef or authority-backed fact.",
        },
        {
            "id": "INV_002",
            "name": "Authority citation required",
            "severity": "error",
            "authority": authority,
            "check": "Any domain conclusion must cite the policy, regulation, expert note, or example that supplied the rule.",
        },
        {
            "id": "INV_003",
            "name": "Contradiction becomes terminal state",
            "severity": "error",
            "authority": authority,
            "check": "Conflicting evidence must not be hidden in narrative; it must commit as a structured failure or reconciliation request.",
        },
    ]
    return {
        "summary": f"{name} can be onboarded as a domain-parametric MotifVM profile. These bootstrap invariants are proposals, not trusted truth.",
        "invariants": invariants,
        "factSchema": [
            {"kind": "domain_fact", "fields": ["value", "source", "confidence", "evidenceRefId"]},
            {"kind": "authority_rule", "fields": ["rule", "section", "authorityRefId"]},
        ],
        "fixtureIdeas": [
            "A clean success case with complete evidence.",
            "A contradiction case where reported and computed values disagree.",
            "A missing evidence case that should commit as computation_blocked.",
        ],
        "note": note,
    }


def build_graph(run: dict) -> dict:
    state = run.get("state", {})
    layout = load_layout(run["id"])
    nodes = []
    edges = []

    compiler_nodes = [
        ("task", "TaskAST", state.get("taskAst", {}).get("goal", run.get("request", "")), "compiler"),
        ("motif", "MotifFrame", summarize_frame(state.get("motifFrame", {})), "compiler"),
        ("plan", "ReasoningPlan", summarize_plan(state.get("reasoningPlan", {})), "compiler"),
        ("patches", "StatePatches", f"{len(state.get('patchTimeline', []))} patch timeline entries", "runtime"),
        ("invariants", "Invariants", summarize_invariants(state), "runtime"),
        ("terminal", "TerminalState", f"{state.get('status')} / {state.get('failureClass') or 'none'}", "terminal"),
    ]
    x_positions = [0, 270, 540, 810, 1080, 1350]
    for index, (node_id, label, body, kind) in enumerate(compiler_nodes):
        nodes.append(flow_node(node_id, label, body, kind, layout, x_positions[index], 80))
    for source, target, label in [
        ("task", "motif", "diagnose"),
        ("motif", "plan", "compile"),
        ("plan", "patches", "execute"),
        ("patches", "invariants", "verify"),
        ("invariants", "terminal", "commit"),
    ]:
        edges.append({"id": f"{source}-{target}", "source": source, "target": target, "label": label})
    if state.get("replanEvents"):
        edges.append({"id": "invariants-plan-replan", "source": "invariants", "target": "plan", "label": "replan", "animated": True})

    graph_nodes = state.get("graph", {}).get("nodes", {})
    graph_edges = state.get("graph", {}).get("edges", [])
    for index, (node_id, node) in enumerate(list(graph_nodes.items())[:28]):
        row = index // 4
        col = index % 4
        nodes.append(flow_node(node_id, node.get("type", "node"), node.get("content", ""), node.get("type", "state"), layout, 120 + col * 310, 310 + row * 150))
    for index, edge in enumerate(graph_edges[:40]):
        source = edge.get("from")
        target = edge.get("to")
        if source in graph_nodes and target in graph_nodes:
            edges.append({"id": f"state-{index}", "source": source, "target": target, "label": edge.get("relation")})
    return {"nodes": nodes, "edges": edges}


def flow_node(node_id: str, label: str, body: str, kind: str, layout: dict, x: float, y: float) -> dict:
    pos = layout.get(node_id, {"x": x, "y": y})
    return {
        "id": node_id,
        "type": "motif",
        "position": pos,
        "data": {"label": label, "body": str(body or "")[:260], "kind": kind},
    }


def summarize_frame(frame: dict) -> str:
    risk = frame.get("risk", {})
    top = sorted(risk.items(), key=lambda item: item[1], reverse=True)[:3]
    return ", ".join(f"{key} {value:.2f}" for key, value in top) or "No frame"


def summarize_plan(plan: dict) -> str:
    passes = plan.get("selectedPasses", [])
    policy = plan.get("verificationPolicy", {}).get("strength", "unknown")
    return f"{policy} verification, {len(passes)} passes"


def summarize_invariants(state: dict) -> str:
    failed = [item for item in state.get("invariants", []) if not item.get("passed") and item.get("severity") == "error"]
    if failed:
        return f"{len(failed)} terminal failure(s): {failed[0].get('invariantId')}"
    return f"{len(state.get('invariants', []))} checks, no terminal errors"


def load_layout(run_id: str) -> dict:
    with db() as conn:
        rows = conn.execute("SELECT node_id, x, y FROM graph_layouts WHERE run_id = ?", (run_id,)).fetchall()
    return {row["node_id"]: {"x": row["x"], "y": row["y"]} for row in rows}


def save_layout(run_id: str, positions: dict) -> None:
    with db() as conn:
        for node_id, pos in positions.items():
            conn.execute(
                "INSERT OR REPLACE INTO graph_layouts VALUES (?, ?, ?, ?)",
                (run_id, node_id, float(pos.get("x", 0)), float(pos.get("y", 0))),
            )


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "domain"


def main() -> None:
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"MotifVM product API listening on http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
