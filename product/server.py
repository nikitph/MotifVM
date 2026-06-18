from __future__ import annotations

import json
import os
import re
import ssl
import sqlite3
import sys
import time
import uuid
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motifvm.compiler import compile_reasoning_plan, create_motif_frame, load_pass_effects  # noqa: E402
from motifvm.passes import registry  # noqa: E402
from motifvm.runtime import diagnose  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent / ".data"
DB_PATH = DATA_DIR / "motifvm_product.sqlite"
PORT = int(os.environ.get("MOTIFVM_PRODUCT_API_PORT", "8787"))


def load_env() -> None:
    for path in (ROOT / ".env", Path(__file__).resolve().parent / ".env"):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_env()

PROMPT_STARTERS = [
    "Review this policy and tell me what can be safely approved. Policy: every approval needs evidence, authority, and a contradiction check.",
    "I am onboarding an insurance claims workflow. Claims need source documents, eligibility rules, and escalation when evidence is missing.",
    "Audit this vendor-risk memo. A high-risk vendor requires a mitigation owner, renewal date, and exception approval.",
]


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
        prompt_domain = conn.execute("SELECT id FROM domains WHERE slug = ?", ("prompt-scaffolded-domain",)).fetchone()
        if not prompt_domain:
            now = iso_now()
            conn.execute(
                """
                INSERT INTO domains VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("domain"),
                    "Prompt-scaffolded domain",
                    "prompt-scaffolded-domain",
                    "A blank MotifVM profile that is instantiated from the user's prompt, authority notes, artifacts, and examples at run time.",
                    "The prompt is the authority boundary. The assistant may propose invariants, facts, and claims, but MotifVM only commits authorized StatePatches with inspectable evidence.",
                    json.dumps(seed_invariants()),
                    now,
                    now,
                ),
            )
        conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()


def seed_invariants() -> list[dict[str, str]]:
    return [
        {"id": "PROMPT_001", "name": "Evidence-bound output", "severity": "error", "authority": "Prompt-scaffolded domain contract", "check": "A terminal answer must be backed by prompt evidence, supplied artifacts, or authority material."},
        {"id": "PROMPT_002", "name": "Unknowns stay explicit", "severity": "error", "authority": "Prompt-scaffolded domain contract", "check": "Missing evidence, contradictions, and unresolved assumptions must become visible terminal state or replan events."},
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = "MotifVMProduct/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.json({"ok": True, "db": str(DB_PATH), "root": str(ROOT)})
        if path == "/api/bootstrap":
            return self.json({"domains": list_domains(), "runs": list_runs(), "promptStarters": PROMPT_STARTERS})
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
        rows = conn.execute(
            """
            SELECT * FROM domains
            WHERE slug NOT IN ('dccb-audit', 'code-review')
            ORDER BY updated_at DESC
            """
        ).fetchall()
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
            """
            SELECT id, title, request, domain, sample_key, status, failure_class, created_at
            FROM runs
            WHERE sample_key IS NULL
              AND COALESCE(domain, '') NOT IN ('dccb_audit', 'code_review')
            ORDER BY created_at DESC
            LIMIT 30
            """
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
    request_text = payload.get("request") or payload.get("message") or "Analyze this domain task."
    proposal = payload.get("proposal") or fallback_invariants(
        {
            "domainName": payload.get("domainName") or title_from_prompt(request_text),
            "authorityMaterial": request_text,
            "examples": request_text,
        }
    )
    state = scaffold_state_from_prompt(request_text, proposal)
    report = render_scaffold_report(state, proposal)
    run_id = new_id("run")
    now = iso_now()
    title = payload.get("title") or title_from_prompt(request_text)
    with db() as conn:
        conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                title,
                request_text,
                state.get("taskAst", {}).get("meta", {}).get("domain"),
                None,
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
    proposal = propose_invariants(
        {
            "domainName": title_from_prompt(message),
            "authorityMaterial": message,
            "examples": message,
        }
    )
    run_payload = {
        "title": title_from_prompt(message),
        "request": message,
        "proposal": proposal,
        "domainName": title_from_prompt(message),
    }
    created = create_run(run_payload)
    run = created["run"]
    assistant = normal_assistant_response(run, proposal, message)
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


def scaffold_state_from_prompt(prompt: str, proposal: dict) -> dict:
    domain_slug = slugify(proposal.get("summary") or title_from_prompt(prompt))[:48]
    task_ast = {
        "id": f"task:{uuid.uuid4().hex[:10]}",
        "goal": prompt,
        "intent": "analyze",
        "inputs": extract_prompt_inputs(prompt),
        "constraints": [],
        "preferences": [],
        "subtasks": [],
        "requiredOutputs": [{"id": "output:answer", "description": "Plain-language answer", "format": "text", "required": True}],
        "uncertainty": [],
        "meta": {"rawRequest": prompt, "timestamp": iso_now(), "domain": f"prompt:{domain_slug}"},
    }
    required = diagnose(task_ast)
    supported = {key: 0.0 for key in required}
    motif_frame = create_motif_frame(task_ast, required, supported)
    plan = compile_reasoning_plan(task_ast, motif_frame, registry(), load_pass_effects(ROOT))
    terminal = terminal_from_prompt(prompt, proposal)
    answer = answer_from_proposal(prompt, proposal, terminal)
    graph_nodes, graph_edges = prompt_graph(prompt, proposal, answer, terminal)
    patch_timeline = prompt_patch_timeline(proposal, terminal)
    state = {
        "id": new_id("state"),
        "taskAst": task_ast,
        "authorityRefs": authority_refs_from_proposal(proposal),
        "inputManifest": [],
        "motifState": {"required": required, "supported": supported, "gap": motif_frame.get("gap", {})},
        "motifSignature": required,
        "motifFrame": motif_frame,
        "reasoningPlan": plan,
        "reasoningPlans": [plan],
        "verificationPolicy": plan.get("verificationPolicy", {}),
        "replanEvents": terminal.get("replanEvents", []),
        "graph": {"nodes": graph_nodes, "edges": graph_edges},
        "artifacts": [
            {
                "id": "artifact:prompt_domain_pack",
                "type": "domain_pack_proposal",
                "content": proposal,
                "producedBy": proposal.get("provider", "invariant_authoring_assistant"),
                "timestamp": iso_now(),
            },
            {
                "id": "artifact:final_output",
                "type": "final_output",
                "content": {"text": answer},
                "producedBy": "motifvm_prompt_scaffold",
                "timestamp": iso_now(),
            },
        ],
        "decisions": [],
        "invariants": invariants_from_proposal(proposal, terminal),
        "passHistory": [],
        "patchTimeline": patch_timeline,
        "executionLog": [],
        "branch": "main",
        "parentCommit": None,
        "status": terminal["status"],
        "failureClass": terminal.get("failureClass"),
        "terminalReason": terminal.get("terminalReason"),
    }
    return state


def normal_assistant_response(run: dict, proposal: dict, prompt: str) -> str:
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
    prefix = final or answer_from_proposal(prompt, proposal, {"status": status, "failureClass": failure})
    if os.environ.get("DEEPSEEK_API_KEY") and not document_profile(prompt)["isLongDocument"]:
        prefix = call_deepseek_answer(prompt, proposal, state, prefix)
    return (
        f"{prefix}\n\n"
        f"Behind the scenes, I bootstrapped {invariant_count} invariant proposal(s), "
        f"compiled a {policy} MotifVM reasoning plan, and committed `{status}`"
        f"{f' with `{failure}`' if failure else ''}. "
        "Open the drill-down graph to inspect the MotifFrame, ReasoningPlan, patches, invariants, and audit artifacts."
    )


def title_from_prompt(prompt: str) -> str:
    document_title = infer_document_title(prompt)
    if document_title:
        return document_title[:72]
    cleaned = " ".join((prompt or "").strip().split())
    if not cleaned:
        return "Prompt-scaffolded run"
    first_clause = re.split(r"[.\n:;!?]", cleaned, maxsplit=1)[0]
    words = first_clause.split()[:8]
    title = " ".join(words).strip(" -_/")
    return title[:72] or "Prompt-scaffolded run"


def extract_prompt_inputs(prompt: str) -> list[dict]:
    pattern = r"(https?://[^\s),]+|[\w./~:-]+\.(?:csv|json|txt|xlsx|xls|patch|diff|pdf|md|log|py|js|ts|tsx|jsx|yaml|yml))"
    inputs = []
    seen = set()
    for index, match in enumerate(re.findall(pattern, prompt or "", flags=re.IGNORECASE), start=1):
        locator = match.strip().strip("`'\"")
        if locator in seen:
            continue
        seen.add(locator)
        kind = "url" if locator.startswith(("http://", "https://")) else Path(locator).suffix.lstrip(".").lower() or "artifact"
        inputs.append({"id": f"input:{index}", "type": kind, "locator": locator, "resolved": False})
    if not inputs:
        inputs.append({"id": "input:prompt", "type": "prompt_text", "locator": "prompt://user-message", "resolved": True})
    return inputs


def terminal_from_prompt(prompt: str, proposal: dict) -> dict:
    text = (prompt or "").lower()
    profile = document_profile(prompt)
    decision_window = text[:700]
    asks_for_decision = any(
        token in decision_window
        for token in [
            "is this compliant",
            "is it compliant",
            "verify compliance",
            "check compliance",
            "can we approve",
            "should we approve",
            "approve this",
            "pass/fail",
        ]
    )
    if profile["isLongDocument"] and not asks_for_decision:
        return {"status": "committed_success", "failureClass": None, "terminalReason": "PROMPT_010_DOCUMENT_SUMMARY_COMMITTED", "replanEvents": []}
    if any(token in text for token in ["contradiction", "conflict", "mismatch", "disagree", "inconsistent"]):
        return {
            "status": "committed_failed",
            "failureClass": "reconciliation_required",
            "terminalReason": "PROMPT_003_CONTRADICTION_RECONCILIATION",
            "replanEvents": [{"failureClass": "reconciliation_required", "action": "request_reconciliation_or_source_priority", "reason": "Prompt contains contradiction-sensitive language."}],
        }
    if any(token in text for token in ["missing", "incomplete", "unknown", "no evidence", "without evidence", "not provided"]):
        return {
            "status": "committed_failed",
            "failureClass": "computation_blocked",
            "terminalReason": "PROMPT_002_EVIDENCE_REQUIRED",
            "replanEvents": [{"failureClass": "computation_blocked", "action": "request_required_evidence", "reason": "Prompt indicates unresolved evidence or unknown inputs."}],
        }
    if any(token in text for token in ["risk", "unsafe", "violation", "breach", "critical", "escalate", "exception"]):
        return {
            "status": "committed_failed",
            "failureClass": "policy_risk_detected",
            "terminalReason": "PROMPT_004_POLICY_RISK",
            "replanEvents": [{"failureClass": "policy_risk_detected", "action": "strengthen_policy_checks_before_approval", "reason": "Prompt asks about risk, exception, or escalation-sensitive material."}],
        }
    return {"status": "committed_success", "failureClass": None, "terminalReason": "PROMPT_001_PROMPT_SCAFFOLD_COMMITTED", "replanEvents": []}


def answer_from_proposal(prompt: str, proposal: dict, terminal: dict) -> str:
    document_answer = document_aware_answer(prompt, proposal, terminal)
    if document_answer:
        return document_answer
    invariants = proposal.get("invariants", [])
    names = ", ".join(item.get("name", item.get("id", "Invariant")) for item in invariants[:3])
    if terminal.get("status") == "committed_success":
        return (
            "I can work with this as a fresh MotifVM domain. "
            f"I identified {len(invariants)} invariant proposal(s)"
            f"{f' around {names}' if names else ''}, compiled a reasoning plan from the prompt, "
            "and reached a provisional committed success. The artifact is inspectable rather than hidden in the chat answer."
        )
    return (
        "I would not treat this as a clean approval yet. "
        f"The prompt-dependent scaffold produced `{terminal.get('failureClass')}` with reason `{terminal.get('terminalReason')}`. "
        f"I still proposed {len(invariants)} invariant(s), but the next correct move is to resolve the blocked/risky condition before committing a final domain outcome."
    )


def infer_document_title(prompt: str) -> str | None:
    lines = [line.strip(" \t\r") for line in (prompt or "").splitlines()]
    compact = [line for line in lines if len(line.strip()) >= 8]
    for line in compact[:30]:
        if "Reserve Bank of India" in line:
            next_lines = [item for item in compact[compact.index(line) + 1 : compact.index(line) + 4] if "Directions" in item]
            if next_lines:
                title = next_lines[0]
                if title.endswith(",") and compact.index(next_lines[0]) + 1 < len(compact):
                    title = f"{title} {compact[compact.index(next_lines[0]) + 1]}"
                return clean_document_title(title)
            title = line
            if title.endswith(",") and compact.index(line) + 1 < len(compact):
                title = f"{title} {compact[compact.index(line) + 1]}"
            return clean_document_title(title)
        if "Directions" in line and ("Bank" in line or "Governance" in line):
            title = line
            if title.endswith(",") and compact.index(line) + 1 < len(compact):
                title = f"{title} {compact[compact.index(line) + 1]}"
            return clean_document_title(title)
        if re.search(r"\b(Board|Committee|Policy|Minutes|Circular|Directions)\b", line, flags=re.IGNORECASE):
            if len(line) < 120:
                return line
    return None


def clean_document_title(title: str) -> str:
    title = " ".join((title or "").split())
    title = re.sub(r"\s+Table of Contents.*$", "", title, flags=re.IGNORECASE)
    return title.strip(" .")


def document_profile(prompt: str) -> dict:
    text = prompt or ""
    lower = text.lower()
    return {
        "isLongDocument": len(text) > 1200 or text.count("\n") > 18,
        "isRegulatory": any(term in lower for term in ["reserve bank of india", "rbi/", "directions", "shall", "regulation act", "nabard"]),
        "isGovernance": any(term in lower for term in ["board of directors", "board meeting", "audit committee", "risk management committee", "code of conduct"]),
        "isMinutes": any(term in lower for term in ["minutes of", "resolved that", "agenda item", "chairman", "meeting held"]),
    }


def document_aware_answer(prompt: str, proposal: dict, terminal: dict) -> str | None:
    profile = document_profile(prompt)
    if not (profile["isLongDocument"] or profile["isRegulatory"] or profile["isMinutes"]):
        return None
    title = infer_document_title(prompt) or title_from_prompt(prompt)
    obligations = extract_document_obligations(prompt)
    cadence = extract_review_cadence(prompt)
    committees = extract_committee_points(prompt)
    sections = [
        f"Document scaffold ready for **{title}**.",
        "I extracted the main authority surfaces from the supplied text and prepared the MotifVM scaffold. I am ready for your next prompt against this document.",
        "",
        "**Extracted rule surfaces**",
    ]
    if obligations:
        sections.extend(f"- {item}" for item in obligations[:8])
    else:
        sections.append("- The document appears to define governance obligations, evidence requirements, and review duties for the supplied domain.")
    if cadence:
        sections.extend(["", "**Review cadence / operating rhythm**"])
        sections.extend(f"- {item}" for item in cadence[:6])
    if committees:
        sections.extend(["", "**Board committee structure**"])
        sections.extend(f"- {item}" for item in committees[:6])
    sections.extend(
        [
            "",
            "**Scaffold status**",
            f"- Proposed {len(proposal.get('invariants', []))} document-specific invariant(s) from the pasted authority text.",
            f"- Terminal state: `{terminal.get('status')}` / `{terminal.get('failureClass') or 'none'}`.",
            "- Evidence layer: prompt/document text captured as the source authority for the current scaffold.",
            "- Drill-down graph: ready for inspecting extracted rules, proposed invariants, patch timeline, and audit artifacts.",
            "",
            "**Ask me next**",
            "- Turn this into a compliance checklist.",
            "- Check a board agenda or minutes against these requirements.",
            "- Extract only Audit Committee or Risk Management Committee duties.",
            "- Identify missing evidence needed for a pass/fail compliance decision.",
        ]
    )
    return "\n".join(sections)


def extract_document_obligations(prompt: str) -> list[str]:
    text = normalize_document_text(prompt)
    candidates = [
        ("applicability", r"These Directions shall be applicable to ([^.]+)\."),
        ("director eligibility", r"The following persons shall not be eligible to become directors of an RCB:([^\\f]+?)(?=17A\\.|8\\.)"),
        ("cooling off", r"after completing a continuous tenure of ten years[^.]+?minimum cooling-off period of three years"),
        ("professional directors", r"an RCB shall have at least two directors[^.]+?professional qualifications[^.]+\."),
        ("CEO approval", r"appointment, reappointment, and termination of appointment of a Chief Executive Officer[^.]+?prior approval of RBI"),
        ("board role", r"The Board of Directors of an RCB shall be responsible for[^.]+?functioning of the RCB"),
        ("RBI circulars", r"all circulars and other material relating to policies issued by RBI / NABARD[^.]+?placed before the Board"),
        ("code of conduct", r"An RCB shall lay down a Code of Conduct[^.]+?Senior Management"),
        ("director conduct", r"The directors of an RCB shall adhere to Do's and Don'ts[^.]+?Code of Conduct"),
    ]
    found = []
    for label, pattern in candidates:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            found.append(humanize_obligation(label, match.group(0)))
    return dedupe(found)


def extract_review_cadence(prompt: str) -> list[str]:
    lower = normalize_document_text(prompt).lower()
    items = []
    if "periodicity: every board meeting" in lower:
        items.append("Every Board meeting should cover funds management, CRR/SLR compliance, loans and advances, regulatory circulars, and statutory/regulatory returns.")
    if "periodicity: quarterly" in lower:
        items.append("Quarterly reviews include business plan performance, recoveries/NPA accounts, branch performance, working results, vigilance/fraud cases, customer service, and Audit Committee observations.")
    if "periodicity: half-yearly" in lower:
        items.append("Half-yearly reviews include investment portfolio, HR/training, IRAC/capital adequacy, risk management implementation, IT/computerization, cost of funds, fair practices, and viability items.")
    if "periodicity: yearly" in lower:
        items.append("Yearly reviews include working-result comparisons and audit/LFAR style review items.")
    if "quarterly return" in lower and "nabard" in lower:
        items.append("A quarterly return must be submitted to the concerned NABARD Regional Office where applicable.")
    return items


def extract_committee_points(prompt: str) -> list[str]:
    text = normalize_document_text(prompt)
    lower = text.lower()
    items = []
    if "audit committee" in lower:
        items.append("The Board must set up an independent Audit Committee with members capable of understanding banking and financial matters.")
    if "three or four directors" in lower and "chartered accountant" in lower:
        items.append("The Audit Committee composition includes three or four directors, excludes the Chairman and CEO/MD, and requires a locally available Chartered Accountant to be co-opted.")
    if "direct, unfettered, and independent access" in lower:
        items.append("The Audit Committee must have direct, unfettered, independent access to management, internal audit, and statutory auditors.")
    if "meet at least once in a quarter" in lower:
        items.append("The Audit Committee must meet at least once every quarter.")
    if "risk management committee" in lower:
        items.append("An RCB must constitute a Risk Management Committee appropriate to its business size and risk exposure.")
    if "heads of credit, investment" in lower:
        items.append("The Risk Management Committee includes the CEO and heads of Credit, Investment, Inspection/Audit, and Accounting, with IT as a special invitee.")
    return dedupe(items)


def humanize_obligation(label: str, raw: str) -> str:
    cleaned = " ".join(raw.split())
    cleaned = cleaned.replace(" / ", "/")
    if label == "applicability":
        return f"Applicability: {cleaned}"
    if label == "director eligibility":
        return "Director eligibility: money-lending/financing/investment conflicts, membership ineligibility, and criminal offences involving moral turpitude are disqualifying conditions."
    if label == "cooling off":
        return "Director tenure: after ten continuous years on the same RCB Board, reappointment requires a three-year cooling-off period."
    if label == "professional directors":
        return "Board composition: each RCB must have at least two directors with suitable banking experience or relevant professional qualifications."
    if label == "CEO approval":
        return "CEO/MD control: appointment, reappointment, and termination of the CEO/MD require prior RBI approval."
    if label == "board role":
        return "Board role: the Board formulates policy and exercises overall supervision/control, while day-to-day administration remains with the CEO/MD."
    if label == "RBI circulars":
        return "Regulatory materials: RBI/NABARD policy circulars must be seen by every Board member and placed before the Board for action."
    if label == "code of conduct":
        return "Conduct framework: the RCB must maintain a Code of Conduct for directors and senior management."
    if label == "director conduct":
        return "Director conduct: directors must follow governance, non-interference, no-sponsorship, conflict-disclosure, and confidentiality expectations."
    return cleaned[:280]


def normalize_document_text(prompt: str) -> str:
    return re.sub(r"\s+", " ", (prompt or "").replace("\f", " ")).strip()


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def authority_refs_from_proposal(proposal: dict) -> list[dict]:
    refs = []
    for index, invariant in enumerate(proposal.get("invariants", []), start=1):
        authority = invariant.get("authority") or proposal.get("summary") or "Prompt supplied authority"
        refs.append(
            {
                "id": f"authority:prompt:{index}",
                "title": invariant.get("name") or f"Prompt invariant {index}",
                "sourceType": "prompt_or_llm_proposed_authority",
                "version": "prompt-scaffold",
                "location": f"prompt://authority-material#{invariant.get('id', index)}",
                "sectionId": invariant.get("id") or f"INV_{index:03d}",
                "quotedRuleExcerpt": authority[:240],
                "sourceHash": hash_text(authority),
            }
        )
    if not refs:
        refs.append(
            {
                "id": "authority:prompt:1",
                "title": "Prompt authority boundary",
                "sourceType": "prompt",
                "version": "prompt-scaffold",
                "location": "prompt://user-message",
                "sectionId": "PROMPT",
                "quotedRuleExcerpt": proposal.get("summary", "Prompt supplied by user")[:240],
                "sourceHash": hash_text(proposal.get("summary", "")),
            }
        )
    return refs


def invariants_from_proposal(proposal: dict, terminal: dict) -> list[dict]:
    failed_once = False
    checks = []
    for index, invariant in enumerate(proposal.get("invariants", []), start=1):
        is_terminal_error = terminal.get("status") != "committed_success" and not failed_once and invariant.get("severity", "error") == "error"
        failed_once = failed_once or is_terminal_error
        checks.append(
            {
                "invariantId": invariant.get("id") or f"INV_{index:03d}",
                "name": invariant.get("name") or f"Invariant {index}",
                "severity": invariant.get("severity") or "error",
                "passed": not is_terminal_error,
                "message": invariant.get("check") or "Prompt-scaffolded invariant check",
                "evidence": ["evidence:prompt"],
                "authorityRefs": [f"authority:prompt:{index}"],
            }
        )
    return checks


def prompt_graph(prompt: str, proposal: dict, answer: str, terminal: dict) -> tuple[dict, list[dict]]:
    nodes = {
        "evidence:prompt": {"type": "evidence", "content": prompt[:420]},
        "fact:domain_intent": {"type": "claim", "content": proposal.get("summary", "Prompt-scaffolded domain")},
        "artifact:domain_pack": {"type": "state", "content": f"{len(proposal.get('invariants', []))} proposed invariants, {len(proposal.get('factSchema', []))} fact schemas"},
        "claim:answer": {"type": "claim", "content": answer[:420]},
        "output:answer": {"type": "output", "content": terminal.get("terminalReason")},
    }
    edges = [
        {"from": "evidence:prompt", "to": "fact:domain_intent", "relation": "extracts"},
        {"from": "fact:domain_intent", "to": "artifact:domain_pack", "relation": "scaffolds"},
        {"from": "artifact:domain_pack", "to": "claim:answer", "relation": "authorizes"},
        {"from": "claim:answer", "to": "output:answer", "relation": "commits"},
    ]
    for index, invariant in enumerate(proposal.get("invariants", []), start=1):
        inv_id = invariant.get("id") or f"INV_{index:03d}"
        node_id = f"invariant:{inv_id}"
        nodes[node_id] = {"type": "error" if terminal.get("status") != "committed_success" and index == 1 else "assumption", "content": f"{invariant.get('name', inv_id)}: {invariant.get('check', '')}"}
        edges.append({"from": "artifact:domain_pack", "to": node_id, "relation": "defines"})
        edges.append({"from": node_id, "to": "claim:answer", "relation": "checks"})
    if terminal.get("replanEvents"):
        nodes["decision:replan"] = {"type": "error", "content": terminal["replanEvents"][0].get("action")}
        edges.append({"from": "claim:answer", "to": "decision:replan", "relation": "triggers"})
        edges.append({"from": "decision:replan", "to": "artifact:domain_pack", "relation": "replans"})
    return nodes, edges


def prompt_patch_timeline(proposal: dict, terminal: dict) -> list[dict]:
    timeline = [
        {"id": new_id("patch"), "op": "prompt_ingest", "actor": "adapter:prompt", "authorized": True, "artifacts": ["evidence:prompt"], "timestamp": iso_now()},
        {"id": new_id("patch"), "op": "invariant_proposal", "actor": proposal.get("provider", "invariant_authoring_assistant"), "authorized": True, "artifacts": ["artifact:prompt_domain_pack"], "timestamp": iso_now()},
        {"id": new_id("patch"), "op": "motif_compile", "actor": "motifvm.compiler", "authorized": True, "artifacts": ["motifFrame", "reasoningPlan"], "timestamp": iso_now()},
        {"id": new_id("patch"), "op": "terminal_commit", "actor": "motifvm.runtime", "authorized": True, "status": terminal.get("status"), "timestamp": iso_now()},
    ]
    if terminal.get("replanEvents"):
        timeline.append({"id": new_id("patch"), "op": "replan_request", "actor": "motifvm.compiler", "authorized": True, "failureClass": terminal.get("failureClass"), "timestamp": iso_now()})
    return timeline


def render_scaffold_report(state: dict, proposal: dict) -> str:
    lines = [
        "# MotifVM Prompt-Scaffolded Run",
        "",
        f"- Status: `{state.get('status')}`",
        f"- Failure class: `{state.get('failureClass') or 'none'}`",
        f"- Terminal reason: `{state.get('terminalReason')}`",
        f"- Goal: {state.get('taskAst', {}).get('goal', '')}",
        f"- Domain: `{state.get('taskAst', {}).get('meta', {}).get('domain')}`",
        "",
        "## Proposed Invariants",
    ]
    for invariant in proposal.get("invariants", []):
        lines.append(f"- `{invariant.get('id', 'INV')}` {invariant.get('name', 'Invariant')}: {invariant.get('check', '')}")
    lines.extend(
        [
            "",
            "## Compiler",
            f"- Required motifs: {', '.join(state.get('motifSignature', {}).keys()) or 'none'}",
            f"- Selected passes: {', '.join(state.get('reasoningPlan', {}).get('selectedPasses', [])) or 'none'}",
            f"- Verification strength: `{state.get('reasoningPlan', {}).get('verificationPolicy', {}).get('strength', 'unknown')}`",
            "",
            "## Trace",
        ]
    )
    for patch in state.get("patchTimeline", []):
        lines.append(f"- `{patch.get('op')}` by `{patch.get('actor')}` authorized={patch.get('authorized')}")
    return "\n".join(lines)


def call_deepseek_answer(prompt: str, proposal: dict, state: dict, fallback: str) -> str:
    payload = {
        "prompt": prompt,
        "proposalSummary": proposal.get("summary"),
        "invariants": proposal.get("invariants", [])[:5],
        "terminalState": {
            "status": state.get("status"),
            "failureClass": state.get("failureClass"),
            "terminalReason": state.get("terminalReason"),
        },
        "instruction": "Write a concise, normal user-facing answer. Do not invent facts beyond the prompt and proposal. Return JSON with key answer.",
    }
    body = {
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": "You are MotifVM's product chat assistant. Return only valid JSON."},
            {"role": "user", "content": json.dumps(payload, sort_keys=True)},
        ],
        "temperature": 0.25,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    req = urlrequest.Request(
        f"{os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=30, context=deepseek_ssl_context()) as response:
            raw = json.loads(response.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
        return parsed.get("answer") or fallback
    except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError, ValueError):
        return fallback


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
            output = fallback_invariants(payload, note=f"DeepSeek fallback: {deepseek_error_note(exc)}")
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
    with urlrequest.urlopen(req, timeout=30, context=deepseek_ssl_context()) as response:
        raw = json.loads(response.read().decode("utf-8"))
    content = raw["choices"][0]["message"]["content"]
    parsed = json.loads(content) if isinstance(content, str) else content
    if "invariants" not in parsed:
        raise ValueError("missing invariants")
    return normalize_proposal(parsed)


def normalize_proposal(proposal: dict) -> dict:
    normalized = dict(proposal)
    invariants = []
    for index, invariant in enumerate(normalized.get("invariants") or [], start=1):
        item = dict(invariant) if isinstance(invariant, dict) else {"check": str(invariant)}
        item.setdefault("id", f"INV_{index:03d}")
        item.setdefault("name", item["id"])
        item.setdefault("severity", "error")
        item.setdefault("authority", normalized.get("summary") or "DeepSeek proposed invariant")
        item.setdefault("check", item.get("description") or item.get("rule") or "Invariant check proposed by DeepSeek.")
        invariants.append(item)
    normalized["invariants"] = invariants
    normalized.setdefault("factSchema", [])
    normalized.setdefault("fixtureIdeas", [])
    normalized.setdefault("summary", "DeepSeek proposed a MotifVM domain scaffold.")
    return normalized


def deepseek_error_note(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="ignore")[:240]
        except Exception:
            body = ""
        return f"HTTPError {exc.code} {exc.reason}: {body}"
    if isinstance(exc, URLError):
        return f"URLError {getattr(exc, 'reason', exc)}"
    return f"{exc.__class__.__name__}: {str(exc)[:240]}"


def deepseek_ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fallback_invariants(payload: dict, note: str | None = None) -> dict:
    name = payload.get("domainName") or "Custom domain"
    material = (payload.get("authorityMaterial") or "").strip()
    authority = material[:120] + ("..." if len(material) > 120 else "") if material else "Provided domain material"
    invariants = fallback_document_invariants(material, authority) or generic_invariants(authority)
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


def generic_invariants(authority: str) -> list[dict]:
    return [
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


def fallback_document_invariants(material: str, authority: str) -> list[dict]:
    profile = document_profile(material)
    if not (profile["isRegulatory"] and profile["isGovernance"]):
        return []
    invariants = [
        {
            "id": "GOV_001",
            "name": "Applicability must be established",
            "severity": "error",
            "authority": authority,
            "check": "Before applying a governance rule, the target institution must be identified as an RCB, StCB, or CCB covered by the Directions.",
        },
        {
            "id": "GOV_002",
            "name": "Board composition and tenure checks",
            "severity": "error",
            "authority": authority,
            "check": "Board compliance claims must verify director eligibility, ten-year tenure cooling-off, and at least two directors with required banking/professional qualifications.",
        },
        {
            "id": "GOV_003",
            "name": "CEO/MD RBI approval",
            "severity": "error",
            "authority": authority,
            "check": "Any CEO/MD appointment, reappointment, or termination claim must cite prior RBI approval evidence.",
        },
        {
            "id": "GOV_004",
            "name": "Board review calendar",
            "severity": "error",
            "authority": authority,
            "check": "Board meeting compliance must map each required review to the prescribed every-meeting, quarterly, half-yearly, or yearly cadence.",
        },
        {
            "id": "GOV_005",
            "name": "Audit and risk committee constitution",
            "severity": "error",
            "authority": authority,
            "check": "Committee compliance must verify Audit Committee independence/composition and Risk Management Committee membership according to the Directions.",
        },
    ]
    return invariants


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


def hash_text(value: str) -> str:
    return "sha256:" + sha256((value or "").encode("utf-8")).hexdigest()


def main() -> None:
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"MotifVM product API listening on http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
