"""A local, persistent knowledge workflow. All approval rules live here."""
import copy
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def checksum(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class WorkflowError(ValueError):
    pass


class RetrievalError(WorkflowError):
    pass


class ConflictError(WorkflowError):
    pass


TRANSITIONS = {
    "NEW": {"VALIDATING"},
    "VALIDATING": {"PLANNING", "FAILED"},
    "PLANNING": {"HOP1", "FAILED"},
    "HOP1": {"HOP2", "RETRY_RETRIEVAL", "CONFLICT", "FAILED"},
    "HOP2": {"HOP1", "HOP3", "RETRY_RETRIEVAL", "CONFLICT", "FAILED"},
    "HOP3": {"HOP1", "VERIFYING", "RETRY_RETRIEVAL", "CONFLICT", "FAILED"},
    "RETRY_RETRIEVAL": {"HOP1", "HOP2", "HOP3", "FAILED"},
    "CONFLICT": {"HOP1", "REJECTED", "FAILED"},
    "VERIFYING": {"DRAFTING", "HOP1", "FAILED"},
    "DRAFTING": {"HOP1", "WAITING_APPROVAL", "RETRY_DRAFT", "FAILED"},
    "RETRY_DRAFT": {"HOP1", "DRAFTING", "FAILED"},
    "WAITING_APPROVAL": {"APPROVED", "REJECTED", "HOP1"},
    "APPROVED": {"PUBLISHING", "HOP1"},
    "PUBLISHING": {"COMPLETE", "HOP1"},
    "COMPLETE": set(), "FAILED": set(), "REJECTED": set(),
}
REVIEWERS = {"reviewer-1", "reviewer-2"}
TERMINAL = {"COMPLETE", "FAILED", "REJECTED"}


def example_documents():
    return [
        {"id": "employees", "version": 1, "effective_date": "2026-01-01",
         "source": "HR employee directory", "kind": "employees",
         "content": {"Employee A": {"role": "manager", "department": "operations"},
                     "Employee B": {"role": "director", "department": "operations"},
                     "Employee C": {"role": "analyst", "department": "finance"}}},
        {"id": "expenses", "version": 1, "effective_date": "2026-01-01",
         "source": "Finance expense ledger", "kind": "expenses",
         "content": {"Expense X": {"amount": 1500, "currency": "EUR", "category": "travel"},
                     "Expense Y": {"amount": 450, "currency": "EUR", "category": "equipment"},
                     "Expense Z": {"amount": 3500, "currency": "EUR", "category": "travel"}}},
        {"id": "approval-policy", "version": 1, "effective_date": "2026-01-01",
         "source": "Finance approved policy register", "kind": "policy",
         "content": {"currency": "EUR", "limits": {"manager": 2000, "director": 5000, "analyst": 0}}},
        {"id": "approval-policy", "version": 2, "effective_date": "2026-11-01",
         "source": "Finance approved policy register", "kind": "policy",
         "content": {"currency": "EUR", "limits": {"manager": 1000, "director": 5000, "analyst": 0}}},
    ]


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        key = self.path.with_suffix(".key")
        if not key.exists():
            if self.path.exists() and self.path.stat().st_size:
                raise WorkflowError("The integrity key is missing. Restore it with the database.")
            try:
                with key.open("xb") as file:
                    file.write(secrets.token_bytes(32))
            except FileExistsError:
                pass
        self.key = key.read_bytes()
        if len(self.key) != 32:
            raise WorkflowError("Invalid integrity key.")
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS docs
                (id TEXT, version INTEGER, body TEXT, signature TEXT, PRIMARY KEY(id, version));
                CREATE TABLE IF NOT EXISTS flows
                (id TEXT PRIMARY KEY, body TEXT, signature TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def sign(self, value):
        return hmac.new(self.key, encode(value).encode(), hashlib.sha256).hexdigest()

    def unpack(self, row):
        if row is None:
            raise WorkflowError("Record not found.")
        body, signature = row
        value = json.loads(body)
        if not hmac.compare_digest(self.sign(value), signature):
            raise WorkflowError("Saved record integrity check failed.")
        return value

    def documents(self, db):
        return [self.unpack(row) for row in db.execute("SELECT body,signature FROM docs ORDER BY id,version")]

    def save_doc(self, db, document):
        db.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?)",
                   (document["id"], document["version"], encode(document), self.sign(document)))

    def save_flow(self, db, flow):
        flow["revision"] += 1
        db.execute("INSERT OR REPLACE INTO flows VALUES (?,?,?)",
                   (flow["id"], encode(flow), self.sign(flow)))

    def load_flow(self, db, workflow_id):
        flow = self.unpack(db.execute("SELECT body,signature FROM flows WHERE id=?", (workflow_id,)).fetchone())
        if flow["id"] != workflow_id:
            raise WorkflowError("Workflow identity mismatch.")
        return flow

    def audit(self, flow, actor, reason, event="note", **extra):
        flow["audit"].append({"actor": actor, "timestamp": now(), "event": event,
                              "previous_state": flow["state"], "next_state": flow["state"],
                              "reason": reason, **extra})

    def seed(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.documents(db):
                for document in example_documents():
                    self.ingest_in(db, document, "admin")

    def ingest_in(self, db, document, actor):
        if actor != "admin":
            raise WorkflowError("Only admin may update knowledge.")
        required = {"id", "version", "effective_date", "source", "kind", "content"}
        if not isinstance(document, dict) or set(document) != required:
            raise WorkflowError("Supply exactly the document schema fields.")
        document = copy.deepcopy(document)
        if not isinstance(document["id"], str) or not document["id"].strip():
            raise WorkflowError("Document id is required.")
        if type(document["version"]) is not int or document["version"] < 1:
            raise WorkflowError("Version must be a positive integer.")
        date.fromisoformat(document["effective_date"])
        authorities = {"employees": "HR employee directory", "expenses": "Finance expense ledger",
                       "policy": "Finance approved policy register"}
        if document["source"] != authorities.get(document["kind"]):
            raise WorkflowError("Unrecognized source authority.")
        content = document["content"]
        if not isinstance(content, dict) or not content:
            raise WorkflowError("Document content must be a nonempty object.")
        if document["kind"] == "policy":
            limits = content.get("limits")
            if content.get("currency") != "EUR" or not isinstance(limits, dict) or not limits:
                raise WorkflowError("Policy needs EUR currency and role limits.")
            if any(not isinstance(role, str) or type(value) is not int or not 0 <= value <= 1000000
                   for role, value in limits.items()):
                raise WorkflowError("Role limits must be integer EUR amounts from 0 to 1000000.")
        else:
            for entity, record in content.items():
                if not isinstance(entity, str) or not isinstance(record, dict):
                    raise WorkflowError("Invalid entity record.")
                if document["kind"] == "employees":
                    if not all(isinstance(record.get(field), str) and record[field].strip()
                               for field in ("role", "department")):
                        raise WorkflowError("Employee needs role and department.")
                elif (type(record.get("amount")) is not int or not 0 <= record["amount"] <= 1000000
                      or record.get("currency") != "EUR" or not isinstance(record.get("category"), str)):
                    raise WorkflowError("Expense needs integer EUR amount and category.")
        old = self.documents(db)
        same_id = [doc for doc in old if doc["id"] == document["id"]]
        if same_id and any(doc["kind"] != document["kind"] for doc in same_id):
            raise WorkflowError("Document kind cannot change across versions.")
        if same_id and document["version"] <= max(doc["version"] for doc in same_id):
            raise WorkflowError("A new version must increase monotonically.")
        document.update(status="active", checksum=checksum(content), ingested_at=now(), updated_by=actor)
        self.save_doc(db, document)
        return document

    def ingest(self, document, actor):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.ingest_in(db, document, actor)

    def rollback(self, doc_id, version, actor, reason):
        if actor != "admin" or not reason.strip():
            raise WorkflowError("Rollback requires admin and a reason.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            docs = self.documents(db)
            target = next((doc for doc in docs if doc["id"] == doc_id and doc["version"] == version), None)
            if target is None or target["effective_date"] > date.today().isoformat():
                raise WorkflowError("Choose an existing, already effective version.")
            for doc in docs:
                if doc["id"] == doc_id and doc["version"] >= version:
                    doc["status"] = "active" if doc["version"] == version else "withdrawn"
                    doc.update(updated_by=actor, update_reason=reason, updated_at=now())
                    self.save_doc(db, doc)

    def current(self, db, kind, as_of):
        documents = self.documents(db)
        eligible = [doc for doc in documents if doc["kind"] == kind and doc["status"] == "active"
                    and doc["effective_date"] <= as_of]
        current = {}
        for doc in eligible:
            previous = current.get(doc["id"])
            if previous is None or (doc["effective_date"], doc["version"]) > (previous["effective_date"], previous["version"]):
                current[doc["id"]] = doc
        if not current:
            raise RetrievalError(f"No effective {kind} source.")
        return list(current.values())

    def inventory(self):
        with self.connect() as db:
            documents = self.documents(db)
            for doc in documents:
                if doc["status"] == "withdrawn":
                    continue
                if doc["effective_date"] > date.today().isoformat():
                    doc["status"] = "scheduled"
                else:
                    newer = any(other["id"] == doc["id"] and other["status"] == "active"
                                and other["effective_date"] <= date.today().isoformat()
                                and (other["effective_date"], other["version"]) > (doc["effective_date"], doc["version"])
                                for other in documents)
                    doc["status"] = "superseded" if newer else "current"
            return documents

    def snapshot(self, db):
        return checksum(self.documents(db))

    def get(self, workflow_id):
        with self.connect() as db:
            return self.load_flow(db, workflow_id)

    def list_flows(self):
        with self.connect() as db:
            return [self.unpack(row) for row in db.execute("SELECT body,signature FROM flows ORDER BY rowid DESC")]

    def create(self, question, actor="user"):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1000:
            raise WorkflowError("Enter a question of 1 to 1000 characters.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            flow = {"id": uuid.uuid4().hex, "question": question.strip(), "state": "NEW",
                    "created_by": actor, "created_at": now(), "revision": 0, "facts": {},
                    "hops": [], "audit": [], "draft": "", "approval": None, "retries": {},
                    "plan": [], "error": None, "snapshot": None}
            self.audit(flow, actor, "Workflow created.", "create")
            self.save_flow(db, flow)
            return flow

    def move(self, flow, target, reason):
        previous = flow["state"]
        if target not in TRANSITIONS.get(previous, set()):
            raise WorkflowError(f"Illegal transition {previous} -> {target}.")
        if target == "APPROVED" and not flow["approval"]:
            raise WorkflowError("An authenticated review decision is required.")
        if target == "PUBLISHING" and not self.valid_approval(flow):
            raise WorkflowError("Approval is missing or does not match this draft.")
        if target == "COMPLETE" and not flow.get("published"):
            raise WorkflowError("The publish stage has not completed.")
        self.audit(flow, "system", reason, "transition", next_state=target)
        flow["state"] = target

    @staticmethod
    def binding(flow):
        return checksum({"workflow": flow["id"], "question": flow["question"],
                         "draft": flow["draft"], "hops": flow["hops"], "snapshot": flow["snapshot"]})

    def valid_approval(self, flow):
        approval = flow.get("approval")
        return bool(approval and approval["workflow_id"] == flow["id"]
                    and approval["reviewer"] in REVIEWERS and approval["decision"] in {"approve", "edit"}
                    and approval["binding"] == self.binding(flow))

    def retrieve(self, db, flow, kind, entity):
        hits = []
        for doc in self.current(db, kind, flow["as_of"]):
            content = doc["content"]
            value = content if kind == "policy" else next(
                (record for name, record in content.items() if name.casefold() == entity.casefold()), None)
            if value is not None:
                hits.append((doc, value))
        if not hits:
            raise RetrievalError(f"No {kind} evidence for {entity}.")
        if len({encode(value) for _, value in hits}) != 1:
            raise ConflictError(f"Current authoritative {kind} sources disagree for {entity}.")
        doc, value = hits[0]
        evidence = {"document_id": doc["id"], "version": doc["version"], "source": doc["source"],
                    "effective_date": doc["effective_date"], "checksum": doc["checksum"],
                    "retrieved_at": now(), "entity": entity, "excerpt": value}
        return value, evidence

    def reset_evidence(self, flow):
        flow.update(facts={}, hops=[], draft="", approval=None, snapshot=None, error=None)
        flow.pop("published", None)
        flow.pop("review_binding", None)

    def step(self, db, flow):
        state = flow["state"]
        if state == "NEW":
            self.move(flow, "VALIDATING", "Validate supported question.")
        elif state == "VALIDATING":
            match = re.fullmatch(r"Can (Employee [A-Za-z0-9_-]+) approve (Expense [A-Za-z0-9_-]+)(?: under (?:the )?current policy)?\??",
                                 flow["question"], re.I)
            if not match:
                raise WorkflowError("Use 'Can Employee A approve Expense X under the current policy?'")
            flow.update(employee=match[1], expense=match[2])
            self.move(flow, "PLANNING", "Supported employee/expense question.")
        elif state == "PLANNING":
            flow["plan"] = [
                {"hop": 1, "question": f"What is {flow['employee']}'s role?", "depends_on": []},
                {"hop": 2, "question": "Use that role to retrieve its current approval limit.", "depends_on": [1]},
                {"hop": 3, "question": "Retrieve the expense and compare its amount and currency with that limit.", "depends_on": [1, 2]},
            ]
            self.move(flow, "HOP1", "Three dependent evidence steps planned.")
        elif state in {"HOP1", "HOP2", "HOP3"}:
            if state == "HOP1":
                flow["as_of"] = date.today().isoformat()
                flow["snapshot"] = self.snapshot(db)
                value, evidence = self.retrieve(db, flow, "employees", flow["employee"])
                fact = {"role": value["role"], "department": value["department"]}
                flow["facts"].update(fact)
                query = flow["employee"]
                target = "HOP2"
            elif state == "HOP2":
                value, evidence = self.retrieve(db, flow, "policy", flow["facts"]["role"])
                role = flow["facts"]["role"]
                if role not in value["limits"]:
                    raise RetrievalError(f"No policy limit for role {role}.")
                fact = {"limit": value["limits"][role], "currency": value["currency"]}
                flow["facts"].update(fact)
                query = f"Current approval policy for {role}"
                target = "HOP3"
            else:
                value, evidence = self.retrieve(db, flow, "expenses", flow["expense"])
                if value["currency"] != flow["facts"]["currency"]:
                    raise ConflictError("Expense and policy currencies disagree.")
                fact = {**value, "eligible": value["amount"] <= flow["facts"]["limit"]}
                flow["facts"].update(fact)
                query = f"{flow['expense']} compared with {flow['facts']['role']} limit {flow['facts']['limit']}"
                target = "VERIFYING"
            flow["hops"].append({"hop": int(state[-1]), "query": query, "fact": fact,
                                 "depends_on": list(range(1, int(state[-1]))), "evidence": evidence})
            self.audit(flow, "system", f"{state} produced a supported intermediate fact.", "retrieval", hop=flow["hops"][-1])
            self.move(flow, target, "Evidence recorded.")
        elif state == "VERIFYING":
            if len(flow["hops"]) != 3:
                raise WorkflowError("The evidence chain is incomplete.")
            self.move(flow, "DRAFTING", "All three hops have evidence.")
        elif state == "DRAFTING":
            facts = flow["facts"]
            verdict = "can" if facts["eligible"] else "cannot"
            flow["draft"] = (f"{flow['employee']} {verdict} approve {flow['expense']}. "
                             f"The employee's role is {facts['role']} [1]. The current limit is "
                             f"{facts['limit']} {facts['currency']} [2]. The expense is "
                             f"{facts['amount']} {facts['currency']} [3].")
            flow["review_binding"] = self.binding(flow)
            self.move(flow, "WAITING_APPROVAL", "Expense authorization requires human review.")
        elif state == "APPROVED":
            self.move(flow, "PUBLISHING", "Current content-bound approval verified.")
        elif state == "PUBLISHING":
            if not self.valid_approval(flow):
                raise WorkflowError("Content changed after approval.")
            flow["published"] = {"content": flow["draft"], "at": now(),
                                 "approval_id": flow["approval"]["id"], "evidence": flow["hops"]}
            self.move(flow, "COMPLETE", "Publish recorded once in this checkpoint.")

    def resume(self, workflow_id, actor="user", *, one_step=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            flow = self.load_flow(db, workflow_id)
            if flow["state"] in TERMINAL:
                return flow
            if flow["state"] == "CONFLICT":
                if flow["snapshot"] == self.snapshot(db):
                    return flow
                self.reset_evidence(flow)
                self.move(flow, "HOP1", "Knowledge changed after conflict. Retrieve again.")
            if flow["snapshot"] and (flow["snapshot"] != self.snapshot(db)
                                     or flow["as_of"] != date.today().isoformat()):
                self.reset_evidence(flow)
                self.move(flow, "HOP1", "Knowledge changed or approval crossed a date boundary.")
            if flow["state"] == "WAITING_APPROVAL":
                return flow
            for _ in range(20):
                if flow["state"] in TERMINAL | {"WAITING_APPROVAL", "CONFLICT"}:
                    break
                if flow["state"] in {"RETRY_RETRIEVAL", "RETRY_DRAFT"}:
                    self.move(flow, flow["retry_state"], "Resume bounded retry.")
                    flow["error"] = None
                else:
                    previous = flow["state"]
                    started = datetime.now(timezone.utc)
                    try:
                        self.step(db, flow)
                    except ConflictError as error:
                        flow["error"] = str(error)
                        self.move(flow, "CONFLICT", str(error))
                    except (RetrievalError, TimeoutError) as error:
                        flow["error"] = str(error)
                        count = flow["retries"].get(previous, 0) + 1
                        flow["retries"][previous] = count
                        flow["retry_state"] = previous
                        target = "RETRY_DRAFT" if previous == "DRAFTING" else "RETRY_RETRIEVAL"
                        self.move(flow, target if count <= 2 else "FAILED", str(error))
                    except WorkflowError as error:
                        flow["error"] = str(error)
                        self.move(flow, "FAILED", str(error))
                    self.audit(flow, actor, "Step completed.", "duration",
                               duration_ms=(datetime.now(timezone.utc) - started).total_seconds() * 1000)
                if one_step or flow["state"].startswith("RETRY"):
                    break
            self.save_flow(db, flow)
            return flow

    def review(self, workflow_id, actor, decision, reason, expected_revision, binding, edited=None):
        if actor not in REVIEWERS or decision not in {"approve", "edit", "reject"} or not reason.strip():
            raise WorkflowError("Review requires an authorized reviewer, decision and reason.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            flow = self.load_flow(db, workflow_id)
            if (flow["state"] != "WAITING_APPROVAL" or flow["revision"] != expected_revision
                    or binding != flow.get("review_binding") or binding != self.binding(flow)):
                raise WorkflowError("Review is stale, replayed, or for different content.")
            if flow["snapshot"] != self.snapshot(db) or flow["as_of"] != date.today().isoformat():
                raise WorkflowError("Knowledge changed. Resume retrieval before reviewing.")
            if decision == "edit":
                if not isinstance(edited, str) or not 1 <= len(edited.strip()) <= 5000:
                    raise WorkflowError("Provide an edited answer of 1 to 5000 characters.")
                original = flow["draft"]
                flow["draft"] = edited.strip()
                self.audit(flow, actor, reason, "edit", original=original, edited=flow["draft"])
            flow["approval"] = {"id": uuid.uuid4().hex, "workflow_id": flow["id"],
                                "reviewer": actor, "decision": decision, "reason": reason,
                                "timestamp": now(), "binding": self.binding(flow)}
            self.audit(flow, actor, reason, "review", decision=decision)
            self.move(flow, "REJECTED" if decision == "reject" else "APPROVED", reason)
            self.save_flow(db, flow)
            return flow
