# Deployment handoff — analytics & reconciliation agent

**Deployment:** {{farm}} · aquaponics operations
**Prepared:** {{date}} · **Operator of record:** {{operator}}

This is the document the deployment runs under. It states what the agent may
do, what it may never do, who approves its findings, and how that is proved
after the fact. It is rendered from the running system: the counts and states
on this page are read live, not typed in.

## 1. Scope — what the agent does

- Reads the five farm systems (sensor telemetry, the controller's commands and
  alerts, maintenance work orders, harvests and shipments, supply purchases and
  consumption) through a **read-only** database role.
- Runs the nightly cross-system reconciliation and the drift and pattern scans.
- Reads documents submitted to it — supplier invoices and water-lab reports —
  on this machine (OCR and field extraction) and reconciles them against the
  systems of record.
- Answers questions in English and Arabic, citing either a knowledge-base
  section or the query it ran.

## 2. Boundaries — what the agent never does

- **It never writes to a farm system.** No reading, command, work order,
  harvest, shipment or purchase is created, changed or deleted by the agent.
  Its database role holds `SELECT` only.
- **It never actuates equipment.** It does not switch a pump, dose a tank or
  feed fish. It recommends; a person decides and the controller acts.
- **It never pays or holds a supplier.** A hold is effective when a human
  records it here and in the purchasing system.
- **It never invents a figure or a citation.** Discrepancies are computed by
  fixed rules; the model explains them and proposes action from retrieved
  knowledge-base sections. A proposed action that cannot be traced to a section
  is replaced by that rule's own wording before it is shown.
- **It never sends anything outside the deployment.** No egress beyond the
  configured model endpoint.

## 3. Approval chain

| Finding | Raised by | Decided by | Recorded as |
|---|---|---|---|
| Document discrepancy (quantity, price, supplier) | Agent, on intake | Farm Manager | Approve · Escalate to the owner · Reject |
| Reconciliation exception (commands, harvest, supplies) | Agent, nightly | Farm Manager | Approve · Escalate to the owner · Reject |
| Suspected false records (a harvest with no shipment) | Agent, pattern scan | Owner | Escalate to the owner |
| Drift in water chemistry or equipment duty | Agent, analytics | Farm Manager, with the technician on duty | Approve · Reject |

Every decision is written to the audit chain with the person, the time and the
knowledge-base section it rests on. Nothing in this application moves money or
equipment; the decision recorded here authorises action in the systems that do.

## 4. Escalation

1. A finding not decided within **one working day** is escalated to the owner.
2. An open water-level or dissolved-oxygen alert is a live-stock risk: it is
   escalated after **4 hours**, day or night, and is never closed inside this
   application.
3. Suspected false records go to the owner immediately.
4. Disagreement with a finding is recorded as *Reject* with a reason, which is
   itself auditable — the finding is not deleted.

## 5. Human control

- The **kill switch** in Settings stops every automated action: document
  intake and agent answers. It is one click, it takes effect immediately, and
  the pause is written to the audit chain with who pressed it and when.
- Findings already produced are kept when the agent is paused; nothing is lost.

## 6. Models

- Document reading and field extraction run **on the deployment's own
  hardware**; documents are not sent to a third party.
- The chat model is selected in Settings. Whatever is selected, the same
  agent graph, the same tools and the same citation rules apply, and the model
  in use is recorded on every answer and in the audit chain.
- Changing the model endpoint is a configuration change, not a code change, and
  is subject to the owner's approval.

## 7. Evidence

- Every model call, tool call, retrieval, intake step, decision, pause and
  deploy is appended to a **hash-chained, append-only** log. Each row carries
  the hash of the row before it, so any change to a past row breaks every row
  after it.
- `Verify chain` in the Admin center's audit trail recomputes the whole chain
  on demand.
- The log is the record handed to an auditor; the audit trail filters it by
  unit, work order, shipment, rule or tool.

## 8. Changes to this application

- The application is developed by a sandboxed developer agent and shipped by
  an operator agent (Sojourner). A change reaches this deployment only
  after it has been built, tested and **approved by a person**.
- Every approved deploy is an event in the same audit chain and is listed on
  the Changes page with who approved it and when.

## 9. Data

- The data in this deployment is **synthetic** and is labelled as such on every
  screen. No real farm's records are present.
- When the deployment moves to real data, this section is replaced by the
  farm's own data-handling terms, and retention and access are set with them
  before any real record is loaded.

## 10. Review

- The knowledge base is the source of every recommendation. It is reviewed by
  the Farm Manager on change, and each rule the agent cites carries the
  document and section it came from.
- This document is reviewed whenever the scope, the approval chain or the model
  configuration changes.

---

**Agreed for {{farm}}**

Name: ............................................  Role: ............................................

Signature: ....................................... Date: ..............................

**Agreed for the supplier**

Name: ............................................  Role: ............................................

Signature: ....................................... Date: ..............................
