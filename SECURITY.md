# Security — the analytics agent

Scope: the Streamlit app, its agent and its data on one machine. The two-tier
developer sandbox that changes this app is sojourner; its threat model
is in that repository's SECURITY.md.

## Threat model

Adversary: the chat model itself (prompt injection through a question, a
document or a retrieved passage; plain model error). Goals it must NOT achieve:
change a farm record, reach the network, present an invented figure or citation
as fact, or alter the record of what it did.

## Enforced (by the database, the process and the code — not by prompts)

| Control | Mechanism |
|---|---|
| Read-only data access | `sql_query` connects as `farm_ro` (SELECT only, one statement, `statement_timeout` 10 s); the app's own writes go to the audit chain and the checkpointer only |
| No egress | every model call goes to the configured OpenAI-compatible endpoint (`LLM_BASE_URL`); embeddings and the vision model always resolve to the local Ollama host (`shared/llm/provider.py`). On a remote lane say "one controlled egress point to our inference endpoint", never "nothing leaves the machine" |
| Figures need evidence | the figure gate and figure verification (`shared/harness/graph.py`, docs/brief-agent-hardening.md): a number no tool result or retrieved passage supports is sent back, then stripped and audited |
| Citations need an index entry | `U.check_citations`: a source that is not an indexed (file, section) is never rendered |
| Detection is code | reconciliation, drift and pattern findings are deterministic (`app/analytics/`); the model explains and recommends from retrieved KB sections |
| Kill switch | Settings → Pause agent writes an `agent_state` event; document intake and chat answers stop until resumed |
| Audit integrity | hash-chained `audit_log` (UPDATE/DELETE revoked; each row hashes its predecessor) + a JSONL mirror; `make test` and Admin center → Verify chain recompute it. Rotation archives a table intact, never truncates |
| Documents stay local | OCR (Tesseract / Surya) and field extraction (qwen3-vl) run on this machine; uploads are written under `data/uploads/` only |

## Known trade-offs (deliberate, demo-scoped)

- No sign-in: the operator recorded on a decision is `HORIZONS_OPERATOR` or the
  OS user. A deployment authenticates people through its own IdP.
- Postgres credentials are demo defaults in `.env.example`; change them, and the
  `farm_ro` password in `shared/db/schema.sql`, before any shared deployment.
- The app runs on one machine for one operator; Streamlit's server is not
  hardened for exposure beyond localhost.

## Reporting

Open a private security advisory on the repository, or write to the author.
Please do not file public issues for vulnerabilities.
