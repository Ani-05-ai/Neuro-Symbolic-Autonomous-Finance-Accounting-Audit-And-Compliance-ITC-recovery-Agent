# Low-Level Design (LLD)

## Autonomous ITC Recovery & Vendor Compliance Agent

**Version:** 1.0

---

## 0\. Conventions used here

- Code is illustrative — it shows shapes and contracts, not finished implementations.  
- `# TEST:` markers describe the failing test you write **first** (TDD red step).  
- "Pure" means: no I/O, no network, no clock, no randomness — same input, same output.  
- **Database:** PostgreSQL 15+ with `asyncpg` for async access. **RLS (Row-Level Security) enforces tenant isolation in the database**, not in application code.  
- Every value crossing a layer boundary is a Pydantic v2 model.

---

## 1\. Repository layout

| itc-recovery/├─ backend/│  ├─ itc/│  │  ├─ api/                     \# FastAPI routers, dependencies, auth│  │  │  ├─ deps.py               \# get\_current\_user, set\_tenant\_context│  │  │  ├─ routers/│  │  │  │  ├─ uploads.py│  │  │  │  ├─ cases.py│  │  │  │  ├─ outreach.py│  │  │  │  ├─ reports.py│  │  │  │  └─ audit.py│  │  │  └─ main.py               \# app factory, lifespan, RLS setup│  │  ├─ domain/                  \# Pydantic models (the vocabulary of the system)│  │  │  ├─ facts.py              \# InvoiceFacts, MatchResult│  │  │  ├─ verdict.py            \# Verdict, ReasonStep, VerdictType│  │  │  ├─ case.py               \# Case, CaseStatus│  │  │  ├─ outreach.py           \# OutreachDraft, OutreachRecord│  │  │  ├─ llm.py                \# LLMTask, LLMTrace, extraction/match schemas│  │  │  └─ tenant.py             \# User, Role, TenantSettings│  │  ├─ rules/                   \# LAYER 2 \-- the legal core (pure Python)│  │  │  ├─ engine.py             \# evaluate(facts, catalogue) \-\> Verdict│  │  │  ├─ loader.py             \# load \+ hash YAML catalogue│  │  │  └─ catalogue/│  │  │     ├─ section\_16\_2.yaml│  │  │     ├─ section\_16\_4.yaml│  │  │     ├─ section\_17\_5.yaml│  │  │     └─ rule\_36\_4.yaml│  │  ├─ intelligence/            \# LAYER 1 \-- LLM perception│  │  │  ├─ gateway.py            \# LLMGateway (validate → retry once with error feedback)│  │  │  ├─ extractor.py│  │  │  ├─ resolver.py│  │  │  ├─ matcher.py            \# FAISS retrieve \+ LLM re-rank│  │  │  └─ embeddings.py         \# SentenceTransformer wrapper \+ FAISS index mgmt│  │  ├─ agents/                  \# LAYER 3 \-- Celery tasks│  │  │  ├─ reconciliation.py│  │  │  ├─ prioritisation.py│  │  │  ├─ outreach.py│  │  │  ├─ escalation.py│  │  │  └─ auditor.py│  │  ├─ ingestion/               \# parse \+ validate uploads│  │  │  ├─ gstr2b.py│  │  │  ├─ purchase\_register.py  \# \+ column mapper│  │  │  └─ normalise.py│  │  ├─ db/                      \# Postgres \+ RLS│  │  │  ├─ models.py             \# SQLAlchemy ORM models│  │  │  ├─ schemas.py            \# Pydantic serialization schemas│  │  │  ├─ repositories.py       \# query layer (RLS enforced by Postgres)│  │  │  └─ migrations/           \# Alembic migrations│  │  ├─ outbound/│  │  │  └─ smtp.py               \# SMTP adapter behind an interface│  │  ├─ core/│  │  │  ├─ config.py             \# pydantic-settings; 12-factor env│  │  │  ├─ security.py           \# JWT, RBAC│  │  │  ├─ logging.py            \# structured logs, redaction│  │  │  └─ idempotency.py│  │  └─ celery\_app.py│  ├─ scripts/                    \# synthetic data generators (Sprint 0\)│  │  ├─ generate\_gstr2b.py│  │  ├─ generate\_purchase\_register.py│  │  ├─ generate\_vendor\_master.py│  │  └─ generate\_match\_pairs.py│  ├─ tests/│  │  ├─ unit/│  │  ├─ integration/│  │  └─ fixtures/│  ├─ pyproject.toml│  ├─ alembic.ini│  └─ Dockerfile├─ frontend/│  └─ src/{components,pages,api,store,routes}/├─ docker-compose.yml└─ .github/workflows/ci.yml |
| :---- |

**Dependency rule (one direction only):** `api → agents → {intelligence, rules, ingestion} → db → core`. `rules` depends on nothing but `domain` and `core`. Nothing imports back upward. Interns: if you ever `import` something from a layer above you, stop — that's the bug.

---

## 2\. Domain models (the shared vocabulary)

These are written **first**, before any logic, because every other module speaks in them.

| \# domain/verdict.pyfrom enum import Enumfrom pydantic import BaseModelclass VerdictType(str, Enum):    """    CGST rule evaluation outcomes.    NOTE: PROVISIONAL is retained for historical data only (tax\_period \< 01/2022).    Rule 36(4) provisional ITC was abolished effective 01 January 2022 per     Notification 40/2021-CT. For current-period invoices missing from GSTR-2B     (tax\_period \>= 01/2022), the verdict is INELIGIBLE per Section 16(2)(aa).    The Rule Engine applies a mandatory date-gate override (see Section 4.3.1).    """    ELIGIBLE \= "eligible"    INELIGIBLE \= "ineligible"    BLOCKED \= "blocked"    TIME\_BARRED \= "time\_barred"    PROVISIONAL \= "provisional"  \# Historical only; see date gate belowclass ReasonStep(BaseModel):    rule\_id: str          \# e.g. "section\_16\_2\_c"    section: str          \# human label    passed: bool    message: str          \# rendered, e.g. "Supplier GSTIN ... not in GSTR-1 for 03/2025"class Verdict(BaseModel):    verdict: VerdictType    reason\_chain: list\[ReasonStep\]    catalogue\_version: str   \# git commit hash of the YAML used |
| :---- |

| \# domain/facts.pyfrom datetime import datefrom pydantic import BaseModel, FieldGSTIN\_RE \= r"^\[0-9\]{2}\[A-Z\]{5}\[0-9\]{4}\[A-Z\]\[1-9A-Z\]Z\[0-9A-Z\]$"class InvoiceFacts(BaseModel):    """The validated facts the Rule Engine consumes. Built by Layer 1."""    tenant\_id: str    item\_description\_clean: str    quantity: float | None \= None    unit: str | None \= None    vendor\_gstin: str \= Field(pattern=GSTIN\_RE)    taxable\_amount\_inr: float \= Field(gt=0)    gst\_amount\_inr: float \= Field(ge=0)    tax\_period: str \= Field(pattern=r"^(0\[1-9\]|1\[0-2\])/\[0-9\]{4}$")   \# MM/YYYY    \# match outcome, set by the matcher:    present\_in\_gstr2b: bool    supplier\_filed\_gstr1: bool    buyer\_is\_registered: bool \= True    goods\_received: bool \= True    as\_of\_date: date            \# supplied by the caller, NOT datetime.now() inside the engine |
| :---- |

| \# domain/llm.pyfrom enum import Enumfrom pydantic import BaseModelclass LLMTask(str, Enum):    EXTRACT \= "extract"; RESOLVE \= "resolve"; MATCH \= "match"    DRAFT \= "draft"; BRIEF \= "brief"; SUMMARISE \= "summarise"class ExtractionOut(BaseModel):       \# validated LLM output for EXTRACT    item\_description: str    quantity: float | None    unit: str | None    vendor\_name: str | None    vendor\_gstin: str | None    amount\_inr: float | None    tax\_period: str | Noneclass MatchOut(BaseModel):            \# validated LLM output for MATCH    best\_match\_index: int | None      \# 0..4 or null    confidence: str                   \# high|medium|low|no\_match    reason: str |
| :---- |

`Case`, `Outreach`, `LLMTrace`, `AuditLog` are persisted as ORM models; see the database section (Section 7 below) for their schema.

---

## 3\. Layer 2 — Rule Engine (build this first)

It is a **pure function**. This is also the best place for interns to learn TDD, because there is nothing to mock.

| \# rules/engine.pydef evaluate(facts: InvoiceFacts, catalogue: RuleCatalogue) \-\> Verdict:    """    Pure. No I/O, no clock, no randomness.    Same facts \+ same catalogue.version  \=\>  identical Verdict, always.    Evaluation order (short-circuits on first failure):      1\. Section 17(5) blocked category   \-\> blocked      2\. Section 16(4) time-bar           \-\> time\_barred      3\. Section 16(2)(a) registered      4\. Section 16(2)(b) goods received      5\. Section 16(2)(c) supplier filed  \-\> ineligible if not      6\. Section 16(2)(d) tax paid (via GSTR-2B presence)      7\. Rule 36(4) provisional           \-\> provisional      8\. all pass                         \-\> eligible    """ |
| :---- |

### 3.1 Rule 36(4) Provisional ITC — Mandatory Date-Gate Override

**Effective 01 January 2022**, Rule 36(4) provisional ITC was abolished (Notification 40/2021-CT). The Rule Engine enforces a **mandatory override**:

| def evaluate(facts: InvoiceFacts, catalogue: RuleCatalogue) \-\> Verdict:    """    Apply CGST rules to facts and return a verdict.    CRITICAL: If the result is provisional and facts.tax\_period \>= "01/2022",    override to ineligible (Rule 36(4) abolished post-01.01.2022).    """    base\_verdict \= catalogue.evaluate(facts)  \# Step 1-8 above    \# Legal constraint: provisional ITC abolished 01.01.2022    if (base\_verdict.verdict \== VerdictType.PROVISIONAL and         facts.tax\_period \>= "01/2022"):        return Verdict(            verdict=VerdictType.INELIGIBLE,            reason\_chain=\[                \*base\_verdict.reason\_chain,                ReasonStep(                    rule\_id="rule\_36\_4\_date\_gate",                    section="Notification 40/2021-CT (01.01.2022)",                    passed=False,                    message=f"Rule 36(4) provisional ITC abolished 01.01.2022 (Notif 40/2021-CT). "                           f"Tax period {facts.tax\_period} is post-effective; verdict → ineligible (Sec 16(2)(aa))."                )            \],            catalogue\_version=base\_verdict.catalogue\_version        )    return base\_verdict |
| :---- |

**Test coverage requirement:** Golden corpus must include test cases for:

- tax\_period \< 01/2022: invoice absent from GSTR-2B → `provisional` (allowed)  
- tax\_period \>= 01/2022: invoice absent from GSTR-2B → `ineligible` (override active)

---

YAML rule shape (reviewed line-by-line by the Tax Advisor):

| \# rules/catalogue/section\_16\_2.yamlrule\_id: section\_16\_2\_csection: "Section 16(2)(c) CGST Act 2017"description: "ITC eligible only if supplier filed GSTR-1 with matching details"version: "1.0"last\_reviewed: "2026-05-01"reviewer: "Tax Advisor Name"conditions:  \- field: supplier\_filed\_gstr1    operator: equals    value: true    on\_fail:      verdict: ineligible      reason: "Supplier GSTIN {vendor\_gstin} not found in GSTR-1 for period {tax\_period}. Section 16(2)(c) not satisfied." |
| :---- |

| \# rules/loader.pyclass RuleCatalogue(BaseModel):    version: str               \# git commit hash of the catalogue dir    rules: dict\[str, RuleSpec\]def load\_catalogue(path: str) \-\> RuleCatalogue: ...def catalogue\_version(path: str) \-\> str:        \# \`git rev-parse HEAD\` over the dir    ... |
| :---- |

**TDD contract for the Rule Engine**

| \# TEST: blocked beats everything \-- a 17(5) item that is also time-barred returns \`blocked\`\# TEST: time-bar \-- as\_of\_date after deadline returns \`time\_barred\` with correct reason\# TEST: 16(2)(c) \-- supplier\_filed\_gstr1=False returns \`ineligible\`, reason names GSTIN \+ period\# TEST: provisional (pre\-2022) \-- tax\_period \< 01/2022, not in GSTR\-2B, within Rule 36(4) limit → \`provisional\`\# TEST: ineligible (post\-2022 date gate) \-- tax\_period \>= 01/2022, not in GSTR\-2B → \`ineligible\` (override active, not provisional)\# TEST: date gate override appends "Notif 40/2021-CT" to reason\_chain\# TEST: all conditions met returns \`eligible\`\# TEST: determinism \-- same facts \+ version called 100x returns byte-identical Verdict\# TEST: reason template renders {vendor\_gstin}/{tax\_period} from facts\# COVERAGE GATE: \>=95% branch |
| :---- |

---

## 4\. Layer 1 — LLM Gateway and Intelligence

### 4.1 LLM Gateway — the only place a model is ever called (hand-rolled retry)

| \# intelligence/gateway.pyfrom typing import Typefrom pydantic import BaseModelclass LLMValidationError(Exception):    """Raised when LLM output fails Pydantic validation."""    passclass LLMGateway:    def \_\_init\_\_(self, provider: str, model: str, trace\_repo: "LLMTraceRepository", max\_retries: int \= 1):        self.provider \= provider        self.model \= model        self.trace\_repo \= trace\_repo        self.max\_retries \= max\_retries    async def call(        self,        task: LLMTask,        context: dict,                     \# structured facts only \-- never raw user blobs        tenant\_id: str,        response\_schema: Type\[BaseModel\],    ) \-\> BaseModel:        """        Validate → retry once on failure with error feedback → log trace → return or raise.                1\. build a tenant-scoped prompt for \`task\`        2\. call the model (LiteLLM / Ollama) with format \= response\_schema, temperature=0        3\. validate output against response\_schema via Pydantic        4\. if validation fails AND retries\_left \> 0:           \- retry with amended prompt including validation error message        5\. write an LLMTrace (input context, raw output, validation result, retries) BEFORE returning        6\. return the validated model  (or raise after all retries exhausted)        """        attempt \= 0        last\_error \= None        raw\_output \= None                while attempt \<= self.max\_retries:            \# Step 1: Build prompt            prompt \= self.\_build\_prompt(task, context, tenant\_id, error=last\_error if attempt \> 0 else None)                        try:                \# Step 2: Call model                raw\_output \= await self.\_call\_model(prompt, response\_schema)                                \# Step 3: Validate                validated \= response\_schema.model\_validate\_json(raw\_output)                                \# Step 5: Log trace (success path)                await self.trace\_repo.create(LLMTrace(                    tenant\_id=tenant\_id,                    task=task,                    prompt=prompt,                    raw\_output=raw\_output,                    validation\_passed=True,                    validation\_error=None,                    retries=attempt,                    timestamp=datetime.now(timezone.utc),                ))                                \# Step 6: Return                return validated                            except (ValidationError, JSONDecodeError) as e:                last\_error \= str(e)                attempt \+= 1                                if attempt \> self.max\_retries:                    \# Step 5: Log trace (failure path)                    await self.trace\_repo.create(LLMTrace(                        tenant\_id=tenant\_id,                        task=task,                        prompt=prompt,                        raw\_output=raw\_output,                        validation\_passed=False,                        validation\_error=last\_error,                        retries=attempt \- 1,  \# attempt has already incremented                        timestamp=datetime.now(timezone.utc),                    ))                    raise LLMValidationError(                        f"LLM output failed validation after {self.max\_retries} retries. Last error: {last\_error}"                    )    async def \_call\_model(self, prompt: str, response\_schema: Type\[BaseModel\]) \-\> str:        """Call LiteLLM with temperature=0 and response\_format."""        if self.provider \== "ollama":            return await self.\_call\_ollama(prompt, response\_schema)        else:  \# litellm            return await self.\_call\_litellm(prompt, response\_schema)    async def \_call\_ollama(self, prompt: str, response\_schema: Type\[BaseModel\]) \-\> str:        """Ollama via OpenAI-compatible endpoint."""        from ollama import AsyncClient        client \= AsyncClient()        response \= await client.chat(            model=self.model,            messages=\[{"role": "user", "content": prompt}\],            format=response\_schema.model\_json\_schema(),            options={"temperature": 0},            stream=False,        )        return response.message.content    async def \_call\_litellm(self, prompt: str, response\_schema: Type\[BaseModel\]) \-\> str:        """LiteLLM provider (OpenAI, Anthropic, etc.)."""        import litellm        response \= await litellm.acompletion(            model=self.model,            messages=\[{"role": "user", "content": prompt}\],            response\_format=response\_schema,            temperature=0,            timeout=30,        )        return response.choices\[0\].message.content    def \_build\_prompt(self, task: LLMTask, context: dict, tenant\_id: str, error: str | None \= None) \-\> str:        """Build a structured, tenant-scoped prompt."""        base\_prompt \= PROMPTS\[task\].format(\*\*context)        if error:            base\_prompt \+= f"\\n\\nPrevious attempt failed validation:\\n{error}\\n\\nPlease correct and retry."        return base\_prompt |
| :---- |

**Test coverage requirement:**

| \# TEST: a malformed model output triggers exactly one retry (if max\_retries \>= 1)\# TEST: every call writes one LLMTrace before returning (assert trace repo called)\# TEST: prompt context never contains a key from another tenant (isolation)\# TEST: retry prompt includes the validation error from the first attempt\# TEST: after max\_retries exhausted, raises LLMValidationError with full context\# TEST (contract): each call site uses the correct LLMTask enum \+ response\_schema |
| :---- |

### 4.2 Structured Extractor

| \# intelligence/extractor.pyasync def extract(raw\_row: dict, tenant\_id: str, gw: LLMGateway) \-\> ExtractionOut:    return await gw.call(LLMTask.EXTRACT, {"raw": raw\_row}, tenant\_id, ExtractionOut) |
| :---- |

| \# TEST: 100 synthetic noisy rows \-\> \>=95% correct field parsing (CI gate)\# TEST: GSTIN failing regex is set to null, not guessed\# TEST: amount confirmed positive against raw |
| :---- |

### 4.3 Entity Resolver (bounded — cannot invent GSTINs)

| \# intelligence/resolver.pyasync def resolve(name: str, vendor\_master: dict\[str, str\], tenant\_id, gw) \-\> str | None:    out \= await gw.call(LLMTask.RESOLVE, {"name": name, "known": list(vendor\_master)}, tenant\_id, ResolveOut)    return out.gstin if out.gstin in vendor\_master else None   \# hard guard |
| :---- |

| \# TEST: 50 name variants \-\> \>=90% mapped, ZERO false assignments\# TEST: a GSTIN not in the master is rejected (returns None) even if the model returns it |
| :---- |

### 4.4 Semantic Matcher with LLM Re-Rank (Critical Path)

| \# intelligence/embeddings.pyfrom sentence\_transformers import SentenceTransformerclass Embedder:    def \_\_init\_\_(self):         self.m \= SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")        def encode(self, texts: list\[str\]):         return self.m.encode(texts, normalize\_embeddings=True)\# per-tenant FAISS index file: faiss\_{tenant\_id}.indexdef build\_index(tenant\_id, gstr2b\_texts): ...def topk(tenant\_id, query\_vec, k=5) \-\> list\[Candidate\]: ... |
| :---- |

| \# intelligence/matcher.pyasync def match(row\_facts, tenant\_id, embedder, gw: LLMGateway) \-\> MatchResult:    """    FAISS retrieve top-5, then LLM re-rank to best match.    This is on the CRITICAL PATH for MVP.    """    \# Step 1: FAISS retrieve top-5 candidates    query\_vec \= embedder.encode(\[row\_facts.description\])\[0\]    candidates \= topk(tenant\_id, query\_vec, k=5)        \# Step 2: LLM re-rank (CRITICAL PATH)    \# If LLM accuracy is poor, the entire reconciliation is impacted    out \= await gw.call(        LLMTask.MATCH,         {"row": row\_facts, "candidates": candidates},         tenant\_id,         MatchOut    )        \# Step 3: Return result    if out.best\_match\_index is None:        conf \= "no\_match"        candidate \= None    else:        candidate \= candidates\[out.best\_match\_index\]        conf \= out.confidence        return MatchResult(        candidate=candidate,         confidence=conf,         faiss\_scores=\[c.score for c in candidates\],        llm\_reason=out.reason    ) |
| :---- |

| \# TEST: 1000 labelled pairs \-\> precision \>=90%, recall \>=85% (CI HARD GATE, critical path)\# TEST: FAISS scores AND LLM match result both written to audit log\# TEST: confidence no\_match \-\> open case with null gstr2b pairing\# TEST: LLM reranking improves precision over FAISS-only baseline (measure both)\# TEST: retry on LLM validation failure; if both attempts fail, flag for human review |
| :---- |

---

## 5\. Layer 3 — Agents (Celery tasks)

Each agent is a thin orchestrator. **No agent makes an eligibility decision** — it calls the Rule Engine and acts on the verdict.

### 5.1 Reconciliation Agent

| @app.task(bind=True)def reconcile(self, tenant\_id, gstr2b\_id, register\_id):    for row in load\_register(tenant\_id, register\_id):        facts \= build\_facts(extract(row), resolve(...), match(...))   \# Layer 1        verdict \= evaluate(facts, load\_catalogue())                   \# Layer 2        audit(tenant\_id, extraction, match, verdict)                  \# all three        if verdict.verdict \!= "eligible":            cases\_repo.create(Case.from\_(facts, verdict)) |
| :---- |

| \# TEST (architectural): no path creates a Case without a Verdict object\# TEST: idempotency \-- re-running with the same inputs yields the same cases \+ one audit set |
| :---- |

### 5.2–5.5: Prioritisation, Outreach, Escalation, Auditor

(See HLD Section 6 for orchestration; LLD mirrors the structure of 4.1 with appropriate tests)

---

## 6\. Ingestion

| \# ingestion/gstr2b.pydef parse\_gstr2b(file\_bytes) \-\> list\[Gstr2bEntry\]:    """Validate top-level gstin/fp/data.b2b\[\]. Row-level validation.       Collect ALL errors, then reject the whole file if any (no partial commit).""" |
| :---- |

| \# ingestion/purchase\_register.py class ColumnMapping(BaseModel): ...   \# saved per tenant, reused next timedef parse\_register(file\_bytes, mapping: ColumnMapping) \-\> list\[RawRow\]: ... |
| :---- |

| \# TEST: one bad row rejects the whole file with a full error report\# TEST: saved column mapping is reused on the tenant's next upload\# TEST: duplicate (invoice\_no \+ tax\_period \+ gstin) reported for confirmation |
| :---- |

---

## 7\. Database Layer (PostgreSQL \+ RLS)

### 7.1 ORM Models (SQLAlchemy)

| \# db/models.pyfrom sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey, Textfrom sqlalchemy.ext.declarative import declarative\_baseBase \= declarative\_base()class Case(Base):    \_\_tablename\_\_ \= "cases"        id \= Column(String(36), primary\_key=True)    tenant\_id \= Column(String(255), nullable=False, index=True)  \# RLS filter    vendor\_gstin \= Column(String(15), nullable=False)    tax\_period \= Column(String(7), nullable=False)  \# MM/YYYY    eligible\_amount\_inr \= Column(Integer, nullable=False)    case\_status \= Column(String(50), nullable=False, default="open")  \# open|approved|dispatched|closed    priority\_score \= Column(Float, nullable=False, default=0.0)    \# Foreign key to Verdict    verdict\_id \= Column(String(36), ForeignKey("verdicts.id"), nullable=False)    created\_at \= Column(DateTime, nullable=False)    updated\_at \= Column(DateTime, nullable=False)        \_\_table\_args\_\_ \= (        \# RLS Policy: SELECT/UPDATE/DELETE only where tenant\_id \= current\_setting('app.tenant\_id')        \# Enforced at Postgres layer, not in code    )class Verdict(Base):    \_\_tablename\_\_ \= "verdicts"        id \= Column(String(36), primary\_key=True)    tenant\_id \= Column(String(255), nullable=False, index=True)  \# RLS filter    verdict\_type \= Column(String(50), nullable=False)  \# eligible|ineligible|blocked|time\_barred|provisional    reason\_chain \= Column(JSON, nullable=False)  \# list of ReasonStep objects    catalogue\_version \= Column(String(40), nullable=False)  \# git commit hash    created\_at \= Column(DateTime, nullable=False, index=True)        \# RLS Policy enforced below class LLMTrace(Base):    \_\_tablename\_\_ \= "llm\_trace"        id \= Column(String(36), primary\_key=True)    tenant\_id \= Column(String(255), nullable=False, index=True)  \# RLS filter    task \= Column(String(50), nullable=False)  \# extract|resolve|match|draft|brief|summarise    prompt \= Column(Text, nullable=False)    raw\_output \= Column(Text, nullable=True)    validation\_passed \= Column(Boolean, nullable=False)    validation\_error \= Column(Text, nullable=True)    retries \= Column(Integer, nullable=False, default=0)    created\_at \= Column(DateTime, nullable=False, index=True)        \# RLS Policy enforced below class AuditLog(Base):    \_\_tablename\_\_ \= "audit\_log"        id \= Column(String(36), primary\_key=True)    tenant\_id \= Column(String(255), nullable=False, index=True)  \# RLS filter    case\_id \= Column(String(36), ForeignKey("cases.id"), nullable=True)    action \= Column(String(50), nullable=False)  \# extraction|match|verdict|dispatch|escalate    details \= Column(JSON, nullable=False)  \# structured event data    created\_by \= Column(String(255), nullable=False)  \# user\_id    created\_at \= Column(DateTime, nullable=False, index=True)        \# RLS Policy \+ IMMUTABLE (triggers prevent UPDATE/DELETE) |
| :---- |

### 7.2 RLS Policies (enforced at Postgres, not in code)

| \-- Called at connection start by the app to set the tenant contextSET app.tenant\_id \= %(tenant\_id)s;\-- RLS Policy on cases tableCREATE POLICY tenant\_isolation\_cases ON cases  FOR SELECT USING (tenant\_id \= current\_setting('app.tenant\_id'));CREATE POLICY tenant\_isolation\_cases\_update ON cases  FOR UPDATE USING (tenant\_id \= current\_setting('app.tenant\_id'));CREATE POLICY tenant\_isolation\_cases\_delete ON cases  FOR DELETE USING (tenant\_id \= current\_setting('app.tenant\_id'));\-- Same for verdicts, llm\_trace, audit\_log\-- … \-- IMMUTABLE constraint on audit\_log (triggers prevent updates)CREATE TRIGGER audit\_log\_immutable  BEFORE UPDATE OR DELETE ON audit\_log  FOR EACH ROW  EXECUTE FUNCTION prevent\_modification('Cannot modify audit log'); |
| :---- |

### 7.3 Repository Layer (queries only; RLS enforces filtering)

| \# db/repositories.pyclass CaseRepository:    def \_\_init\_\_(self, db\_session):        self.\_db \= db\_session  \# Session already has app.tenant\_id set via RLS    async def create(self, case: Case) \-\> Case:        """RLS will enforce tenant\_id on INSERT."""        self.\_db.add(case)        await self.\_db.flush()        return case    async def find\_by\_id(self, case\_id: str) \-\> Case | None:        """RLS will filter results by tenant\_id automatically."""        return await self.\_db.execute(            select(Case).where(Case.id \== case\_id)        )    async def find\_all\_open(self, order\_by: str \= "priority\_score desc") \-\> list\[Case\]:        """RLS enforced; no tenant\_id filter needed in code."""        return await self.\_db.execute(            select(Case).where(Case.case\_status \== "open").order\_by(...)        ) |
| :---- |

**TDD contract for database layer:**

| \# TEST (the most important test in the system):\#   Simulate cross-tenant access: set app.tenant\_id=A, query for B docs → RLS returns empty\#   (This is a Postgres constraint, not application logic)\# TEST: AuditLog/LLMTrace reject update and delete operations (IMMUTABLE trigger)\# TEST: ForeignKey constraints prevent orphaned cases/verdicts |
| :---- |

---

## 8\. API layer

| Method | Endpoint | Role | Body / returns |
| :---- | :---- | :---- | :---- |
| POST | `/uploads/gstr2b` | finance\_user | JSON file → triggers reconcile |
| POST | `/uploads/purchase-register` | finance\_user | .xlsx \+ mapping |
| GET | `/cases` | finance\_user, auditor | paginated, filtered, sorted by priority desc |
| GET | `/cases/{id}` | finance\_user, auditor | case \+ full trail (RLS enforced) |
| GET | `/cases/{id}/llm-trace` | auditor | extraction \+ match traces (RLS enforced) |
| POST | `/outreach/{id}/approve` | finance\_user | approval record |
| POST | `/outreach/bulk-approve` | finance\_user | top-N |
| GET | `/reports/monthly` | finance\_user, auditor | PDF/CSV |
| GET | `/audit-log` | auditor | searchable, JSON export (RLS enforced) |

Every request carries a JWT; every response carries a `trace_id` header. RLS is set at the start of each request:

| \# api/deps.py@app.middleware("http")async def set\_tenant\_context(request: Request, call\_next):    user \= get\_current\_user(request)  \# from JWT    \# Set RLS context for this request    await db.execute(f"SET app.tenant\_id \= '{user.tenant\_id}'")    response \= await call\_next(request)    return response |
| :---- |

| \# TEST: request without valid JWT \-\> 401\# TEST: auditor calling an approve endpoint \-\> 403 (RBAC)\# TEST: cross-tenant request (set app.tenant\_id to A, query for B) \-\> 403 (RLS blocks it) |
| :---- |

---

## 9\. Config (12-factor)

| \# core/config.py  (pydantic-settings)class Settings(BaseSettings):    llm\_provider: str \= "ollama"  \# or "litellm"    llm\_model: str \= "mistral:7b-instruct"    database\_url: str  \# postgresql+asyncpg://user:pass@localhost/itc    redis\_url: str    jwt\_public\_key\_path: str    smtp\_host: str; smtp\_port: int |
| :---- |

Provider swap \= one env var. No code change. Secrets via OS secret store, never committed.

---

## 10\. Testing strategy (per the test pyramid)

| Layer | Share | Lives here |
| :---- | :---- | :---- |
| Unit (\~70%) | Rule Engine (golden corpus), LLM Gateway retry logic, validators, ranking math, React components |  |
| Integration (\~20%) | Agent loops with real Postgres \+ Redis test container; FastAPI routes; matcher with mock LLM |  |
| E2E (\~10%) | Playwright: upload → reconcile → approve → dispatch → report |  |

LLM-specific rules:

- **No live LLM calls in CI.** Mock the Gateway; test the retry logic separately.  
- **Matching accuracy suite** (real model vs labelled set) runs **weekly / on model change**, outside the main CI loop. This is critical because matching is on the critical path.  
- Contract tests assert every call site uses the right `LLMTask` \+ `response_schema`.

Coverage gates: Rule Engine ≥95% branch, Gateway+validation ≥90%, repositories/RLS ≥95%, agents/API ≥85%, frontend ≥75%, overall ≥85%.

**Golden corpus requirement (Rule 36(4) date gate):** The Rule Engine golden corpus must include test cases verifying the date-gate override:

| Tax Period | Invoice in GSTR-2B | ITC Amount | Expected Verdict | Reason |
| :---- | :---- | :---- | :---- | :---- |
| 12/2021 | No | ₹500 | PROVISIONAL | Pre-abolition; Rule 36(4) applies |
| 02/2022 | No | ₹500 | INELIGIBLE | Post-abolition; Notif 40/2021-CT override active |
| 2025 | No | ₹500 | INELIGIBLE | Current period; rule\_36\_4 override ensures ineligible |

Any test case where `tax_period >= 01/2022` and the rule catalogue would produce `provisional` **must** verify that `evaluate()` overrides to `ineligible` and includes "Notif 40/2021-CT" in the reason chain.

---

## 11\. Error handling & idempotency (defaults interns should copy)

- LLM validation fails → retry once with error feedback in prompt → if still fails, `extraction_failed` → human-review queue.  
- SMTP fails → 3× exponential backoff → `dispatch_failed` \+ alert.  
- Celery task → deterministic idempotency key (hash of inputs); replay \= same outcome, one audit entry per logical action; \>3 failures → dead-letter queue \+ alert.  
- Upload validation → collect all errors, reject whole file, never partial-commit.

---

## 12\. Frontend (React 19 \+ Tailwind v4, shadcn/ui CLI v4)

Components are built with modern defaults:

- **Init:** `npx shadcn@latest init -s new-york` (default style)  
- **Toast:** Use `sonner` (old shadcn `toast` is deprecated)  
- **CSS:** Tailwind v4 `@theme` directive \+ CSS variables  
- **Compiler:** React 19 Compiler can be enabled (optional, not required)

Frontend-specific tests use Vitest \+ React Testing Library. E2E uses Playwright.

| \# TEST: case list sorts by priority\_score desc by default\# TEST: upload UI shows column mapper on first tenant upload, hidden on repeat\# TEST: auditor cannot reach finance-only routes |
| :---- |

---

