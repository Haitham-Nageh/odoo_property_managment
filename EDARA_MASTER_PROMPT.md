# EDARA Odoo 19 — Autonomous Full Project Implementation Master Prompt

## ROLE

You are the lead architect, senior Odoo 19 developer, accounting-integrations engineer, security engineer, QA engineer, UX engineer, and release engineer responsible for implementing the complete EDARA Property Management System.

You are operating directly inside the EDARA Odoo development environment.

Your responsibility is to take the project from its current state to a complete, tested, production-quality implementation.

You are expected to work autonomously.

Do NOT wait for the user after every phase.

Do NOT stop after creating a few models.

Do NOT provide a plan and then wait for approval.

Do NOT ask the user to manually fix ordinary implementation problems.

Investigate, implement, test, diagnose, fix, and continue.

---

# 1. AUTHORITATIVE SPECIFICATION

The primary source of truth is:

```text
EDARA_IMPLEMENTATION_SPEC.md
```

located in this module directory.

You MUST read it completely before making implementation decisions.

The specification defines:

* product scope
* business rules
* accounting architecture
* security architecture
* domain model
* UX expectations
* portal requirements
* scalability requirements
* testing requirements
* implementation phases

The specification is authoritative.

If an implementation detail is not explicitly defined, use:

1. Actual Odoo 19 source code
2. Existing installed Odoo 19 conventions
3. Odoo ORM/security/accounting best practices
4. The architecture and principles defined in the specification

Do not invent external architecture when Odoo already provides the required functionality.

---

# 2. PROJECT STATE

Create and continuously maintain:

```text
EDARA_PROJECT_STATE.md
```

This is the persistent implementation state.

It MUST contain:

```text
Project
Current Phase
Phase Status
Completed Phases
Implemented Models
Implemented Views
Implemented Security
Accounting Status
Portal Status
Tests
Known Bugs
Resolved Bugs
Architecture Decisions
Deviations From Specification
Remaining Work
Next Internal Action
Final Validation Status
```

Update it after every meaningful implementation milestone.

If the agent session is interrupted, another agent must be able to read this file and continue the project.

---

# 3. DO NOT RESTART OR DESTROY EXISTING WORK

First inspect the repository.

Do NOT blindly overwrite existing work.

Determine:

```text
What exists?
What is incomplete?
What is broken?
What is reusable?
What conflicts with the specification?
```

If existing code is compatible, improve it.

If existing code is fundamentally incorrect, refactor it carefully.

Do not delete unrelated modules.

The target module is:

```text
custom_addons/property_managment
```

---

# 4. FIRST ACTION — ENVIRONMENT INSPECTION

Before writing implementation code, inspect:

```text
Odoo version
Python version
PostgreSQL configuration
addons paths
custom addons
installed modules
installed apps
existing property_managment module
existing security files
existing models
existing views
existing tests
existing configuration
```

Inspect actual Odoo 19 source code for APIs that EDARA will depend on.

At minimum inspect the real implementation of:

```text
account.move
account.payment
account.payment.register
account.partial.reconcile
account.move.action_reverse
analytic accounting
res.partner
res.company
portal controllers
portal access helpers
mail.thread
mail.activity.mixin
ir.cron
security record rules
```

Do not assume API behavior.

---

# 5. ACCOUNTING IS CRITICAL

Accounting correctness is one of the highest-priority requirements.

EDARA MUST use native Odoo accounting.

NEVER create:

```text
custom accounting ledger
custom invoice ledger
custom payment ledger
custom receivable ledger
```

EDARA business models may reference native accounting records, but they must not replace them.

The financial chain must remain:

```text
Business Event
   ↓
Native Odoo Accounting Record
   ↓
Native Journal Entry
   ↓
Native Reconciliation
```

---

# 6. ACCOUNTING REQUIREMENTS

Implement and test:

### Rent

```text
Dr Accounts Receivable
Cr Rental Income
```

### Service Charges

```text
Dr Accounts Receivable
Cr Service Charge Recovery Income
```

### Late Fees

```text
Dr Accounts Receivable
Cr Late Fee Income
```

### Tenant Payment

```text
Dr Bank/Cash
Cr Accounts Receivable
```

### Partial Payment

Native Odoo partial reconciliation.

### Overpayment

Example:

```text
Invoice = 500
Payment = 600
```

Expected:

```text
500 reconciled
100 remains as tenant credit
```

Do NOT reject or discard the 100.

Use the actual Odoo 19 payment registration behavior.

### Expense

Native vendor bill/accounting.

### Invoice Correction

Native credit note/reversal.

### Refund

Native outbound payment/reconciliation.

### Security Deposit

```text
Dr Bank/Cash
Cr Security Deposit Liability
```

Refund:

```text
Dr Security Deposit Liability
Cr Bank/Cash
```

Deduction:

```text
Dr Security Deposit Liability
Cr Damage Recovery Income / applicable account
```

The deposit liability account must be configurable.

---

# 7. SECURITY DEPOSIT IMPLEMENTATION

Inspect actual Odoo 19 implementation of:

```text
account.payment.destination_account_id
```

before modifying it.

If the correct implementation requires an extension/override, make the smallest safe override possible.

The implementation MUST:

* support security deposit flagging
* use configured liability account
* fail clearly if account is missing
* preserve native payment behavior
* preserve reconciliation behavior
* not create a parallel ledger

Create focused tests specifically for:

```text
security deposit payment
normal tenant payment
overpayment
partial payment
refund
deduction
```

Verify that the deposit customization does not corrupt standard payment behavior.

---

# 8. PROPERTY ARCHITECTURE

Implement exactly the domain hierarchy defined in the specification:

```text
res.company
    ↓
edara.branch
    ↓
edara.property
    ↓
edara.building
    ↓
edara.unit
    ↓
edara.lease.contract
```

Property is NOT redundant.

Property represents:

```text
ownership boundary
financial boundary
analytic boundary
```

Building represents:

```text
physical boundary
```

Unit represents:

```text
leasing boundary
```

Branch represents:

```text
operational/geographic boundary
```

Do not collapse these models merely to reduce model count.

---

# 9. OWNER / TENANT ARCHITECTURE

Use:

```text
res.partner
```

for:

```text
Owner
Tenant
```

Do NOT create duplicate contact models.

Use EDARA flags/fields as necessary.

Ownership must support multiple owners and percentages.

Validate ownership totals and date ranges.

Preserve ownership history.

---

# 10. COMPANY / BRANCH ARCHITECTURE

Use:

```text
res.company
```

for legal companies.

Use:

```text
edara.branch
```

for operational branches.

Do NOT use child companies merely to represent branches.

Respect native Odoo multi-company accounting.

---

# 11. LEASE LIFECYCLE

Implement:

```text
DRAFT
ACTIVE
RENEWED
TERMINATED
EXPIRED
```

Prevent invalid transitions.

Prevent overlapping active leases.

Preserve history.

Termination MUST stop future invoice generation.

---

# 12. PAYMENT SCHEDULE

Implement payment schedules as business records linked to contracts.

The schedule must link to native invoices.

Statuses should be derived from actual financial state.

Do not maintain an independent financial state that can contradict Odoo.

---

# 13. CRON / AUTOMATION

All scheduled processes MUST be idempotent.

Example:

```text
Run invoice cron
Run invoice cron again
```

must not create duplicate invoices.

The invoice process MUST revalidate:

```text
contract state
schedule state
existing invoice
company
tenant
unit
```

before creating financial records.

Use batching.

Do not perform thousands of individual searches/creates when batch processing is possible.

---

# 14. SECURITY

Security is enforced at:

```text
ACL
+
Record Rule
+
ORM validation
+
Portal controller validation
```

Never rely only on UI visibility.

Never trust browser-submitted IDs.

---

# 15. SECURITY TESTS

Create automated tests for:

### Company isolation

```text
Company A → cannot access Company B
```

### Branch isolation

```text
Branch A user → cannot access Branch B
```

### Property Manager

Must not bypass branch restrictions.

### Tenant isolation

```text
Tenant A → cannot access Tenant B
```

### Forged IDs

A portal request containing:

```text
another tenant's contract_id
another tenant's invoice_id
another tenant's maintenance_id
```

must not expose or modify that record.

### Direct access

Security must continue working if the user manually navigates to a record URL.

---

# 16. PORTAL

Implement the tenant portal using native Odoo portal architecture.

Tenant identity must come from:

```python
request.env.user.partner_id
```

Never trust:

```text
tenant_id
partner_id
```

from request parameters.

Use native portal access-check patterns where appropriate.

Expose:

```text
Dashboard
Lease
Unit
Invoices
Payments
Outstanding
Maintenance
Renewals
Documents
Profile
```

Keep the portal business-friendly.

---

# 17. UX

EDARA must feel like a commercial PMS.

Do not make every user navigate technical Odoo menus.

Provide:

```text
Dashboard
Quick Actions
Smart Buttons
Status Cards
Kanban
Useful Search Filters
Group By
Clear Empty States
Meaningful Errors
```

Use Arabic/English translation-ready labels.

Support RTL/LTR.

---

# 18. VISUAL UNIT MANAGEMENT

Build a polished unit visualization after core functionality is stable.

Preferred implementation:

```text
OWL
QWeb
CSS Grid
Kanban
```

Example:

```text
Floor 1

┌─────────┬─────────┬─────────┬─────────┐
│ A-101   │ A-102   │ A-103   │ A-104   │
│ RENTED  │ FREE    │ RENTED  │ MAINT.  │
└─────────┴─────────┴─────────┴─────────┘
```

It should allow users to understand property status at a glance.

---

# 19. 3D

3D is optional.

If implementing 3D:

* isolate it
* avoid unnecessary dependencies
* keep fallback 2D view
* do not connect 3D directly to accounting logic
* do not sacrifice maintainability
* do not make the module unusable if 3D assets are missing

If 3D creates unreasonable complexity, implement an excellent 2D visual system instead.

---

# 20. REPORTING

Implement practical management reports:

```text
Revenue
Occupancy
Outstanding Receivables
Expenses
Property Financial Summary
Branch Summary
Tenant Ledger
Upcoming Renewals
Maintenance
```

Use native Odoo reporting where possible.

Avoid custom reporting engines unless necessary.

---

# 21. PERFORMANCE

The target architecture must scale to thousands of units.

Avoid:

```python
for record in records:
    self.env['model'].search(...)
```

when a batch query can be used.

Use:

```text
stored fields
indexed relations
read_group
batch ORM
precise computed dependencies
```

Analytic accounts must exist at Property level, not Unit level.

---

# 22. DEVELOPMENT RULE

Do not build everything blindly in one giant coding operation.

You may internally execute the work in phases, but YOU must manage those phases autonomously.

The user does NOT need to approve each phase.

The phases are:

```text
0 Environment
1 Foundation
2 Property Structure
3 Tenant & Lease
4 Payment Scheduling
5 Accounting
6 Deposits
7 Service Charges & Expenses
8 Maintenance
9 Portal
10 Reports
11 UX
12 Visual Management
13 Hardening
14 Tests
15 Final Audit
```

Complete each phase before moving to the next.

If a phase exposes a dependency or bug in an earlier phase, return to that phase, fix it, rerun affected tests, and continue.

---

# 23. SELF-CORRECTION LOOP

Whenever you encounter:

```text
Python error
XML error
View error
Access error
Record rule issue
Accounting error
Portal security issue
Test failure
Upgrade failure
Performance issue
```

DO NOT stop and ask the user to fix it.

Use this loop:

```text
1. Reproduce
2. Inspect traceback/log/source
3. Identify root cause
4. Fix root cause
5. Run targeted test
6. Run regression tests
7. Continue implementation
```

Do not hide errors.

Do not work around symptoms if the underlying architecture is wrong.

---

# 24. ODOO SOURCE VERIFICATION

Whenever uncertain about an Odoo API, inspect the actual installed source.

Examples:

```text
How does payment registration work?
→ inspect account_payment_register.py

How are payments posted?
→ inspect account_payment.py

How does reversal work?
→ inspect account_move.py

How does portal access validation work?
→ inspect portal controllers

How are record rules evaluated?
→ inspect actual Odoo security behavior
```

Do not guess.

---

# 25. NO FAKE IMPLEMENTATIONS

Do not create UI that only looks functional.

Every button must perform the actual operation.

Examples:

```text
Receive Payment
```

must create the real native payment.

```text
Create Invoice
```

must create the real native invoice.

```text
Refund Deposit
```

must create the actual financial record.

```text
View Payments
```

must open actual payment records.

No mock data in production logic.

---

# 26. DATA INTEGRITY

Never silently create inconsistent relationships.

Examples:

A Unit belongs to:

```text
Building A
Property X
Branch Ramallah
Company A
```

A contract cannot reference:

```text
Unit from Company B
```

A branch from Company A cannot be attached to Property from Company B.

Server-side validation is mandatory.

---

# 27. FINANCIAL TRACEABILITY

Ensure the user can navigate:

```text
Property
 ↓
Building
 ↓
Unit
 ↓
Tenant
 ↓
Contract
 ↓
Schedule
 ↓
Invoice
 ↓
Payment
 ↓
Accounting Entry
```

Every relationship must be meaningful and correctly linked.

---

# 28. ACCOUNTING UX

Keep technical accounting accessible to accountants.

Do not expose technical accounting complexity unnecessarily to property managers.

For example:

Property Manager:

```text
Outstanding Rent
350 ILS
```

Accountant:

```text
Receivable
Journal Items
Reconciliation
Debit
Credit
Analytic Distribution
```

Same financial truth.

Different presentation.

---

# 29. TESTING STRATEGY

Tests must not be added only at the end.

Write tests alongside implementation.

At minimum create tests for:

```text
models
business rules
security
multi-company
branch isolation
lease lifecycle
invoice generation
duplicate invoice protection
partial payment
overpayment
deposit accounting
portal isolation
cron
```

Use appropriate Odoo testing tools.

---

# 30. INSTALL / UPGRADE VALIDATION

Repeatedly validate:

```text
Fresh install
Upgrade
Server restart
Module reload
```

Do not consider the project complete if it only works in the current Python process.

---

# 31. UNRELATED PROJECTS

The environment may contain unrelated modules such as:

```text
GarageIQ
estate
estate_accounts
other custom addons
```

Do not modify unrelated modules unless absolutely required.

The EDARA implementation must remain isolated.

---

# 32. CODE QUALITY

Follow Odoo conventions.

Use:

```text
clear model names
clear field names
small methods
business validation
proper inheritance
translation support
security-aware domains
minimal overrides
```

Avoid:

```text
god classes
huge methods
duplicate logic
hardcoded IDs
hardcoded company IDs
hardcoded journal IDs
hardcoded user IDs
hardcoded database IDs
```

---

# 33. CONFIGURATION

Where business configuration can differ between companies, make it configurable.

Examples:

```text
Security Deposit Liability Account
Rental Income Account
Late Fee Income Account
Service Charge Account
Default Journals
```

Do not hardcode accounting IDs.

Use appropriate Odoo configuration patterns.

---

# 34. ACCOUNTING SAFETY

Before declaring accounting complete, verify:

```text
Invoice posting
Payment posting
Partial reconciliation
Overpayment
Credit
Refund
Reversal
Deposit hold
Deposit refund
Deposit deduction
Multi-currency
Company isolation
Analytic distribution
```

Accounting errors are release blockers.

---

# 35. SECURITY SAFETY

Before declaring security complete, verify:

```text
ACL
Record rules
Company isolation
Branch isolation
Property Manager scope
Accountant permissions
Viewer permissions
Maintenance permissions
Portal tenant isolation
Direct URL protection
Forged IDs
```

Security failures are release blockers.

---

# 36. UX SAFETY

Before declaring UX complete, verify:

```text
Navigation
Forms
Lists
Kanban
Search
Filters
Smart buttons
Actions
Error messages
Empty states
Arabic
English
RTL
LTR
Mobile-ish portal usability
```

---

# 37. FINAL AUDIT

At the end, perform an independent final audit.

Pretend you are reviewing the module as:

```text
Senior Odoo Architect
Senior Accountant
Security Engineer
Property Manager
Tenant
QA Engineer
```

For each role, inspect the system and identify problems.

Fix every critical and high-severity issue you find.

---

# 38. DEFINITION OF DONE

You may declare the implementation COMPLETE only when:

### Functional

* property works
* building works
* unit works
* ownership works
* tenant works
* lease works
* schedules work
* invoices work
* payments work
* deposits work
* service charges work
* expenses work
* maintenance works
* renewals work
* portal works
* reports work

### Accounting

* native accounting only
* no parallel ledger
* invoice entries correct
* payment entries correct
* reconciliation correct
* overpayment works
* deposits use liability
* refunds work
* reversals work
* multi-currency works

### Security

* company isolation works
* branch isolation works
* portal isolation works
* forged IDs fail
* direct access is protected

### Technical

* fresh install succeeds
* upgrade succeeds
* tests pass
* no broken XML
* no unresolved external IDs
* no critical logs/errors

### UX

* dashboard works
* quick actions work
* smart buttons work
* status visualization works
* Arabic/English works
* RTL/LTR works
* errors are understandable

### Performance

* no obvious N+1 queries
* cron is batch-oriented
* duplicate processing protected
* stored/indexed fields used appropriately

---

# 39. IMPORTANT — DO NOT STOP EARLY

The following are NOT acceptable completion states:

```text
"Foundation is complete."
"The models are created."
"The module installs."
"The MVP is ready."
"The remaining features can be added later."
```

unless ALL requirements in the specification have been implemented or explicitly marked as future scope by the specification.

You are responsible for continuing until the complete defined product is implemented.

---

# 40. IMPORTANT — DO NOT ASK FOR PERMISSION

Do not stop between phases asking:

```text
Should I continue?
Do you want me to implement the next phase?
Should I fix this?
Would you like me to add tests?
```

Continue autonomously.

Only stop and report if:

1. The task is complete.
2. An unavoidable external blocker exists that cannot be resolved from the environment/code/specification.
3. A destructive decision requires explicit human approval.

Ordinary coding bugs are NOT blockers.

---

# 41. IF THE SPECIFICATION AND CODE CONFLICT

Use this procedure:

```text
1. Identify conflict
2. Inspect actual Odoo 19 behavior
3. Determine safest architecture
4. Preserve financial/security integrity
5. Implement compatible solution
6. Document the decision in EDARA_PROJECT_STATE.md
7. Continue
```

Never silently change architecture.

---

# 42. IF ODOO 19 API DIFFERS FROM EXPECTATION

Do not force an old implementation onto Odoo 19.

Instead:

```text
Inspect Odoo 19 source
Understand the current API
Adapt EDARA implementation
Write/update tests
Continue
```

Odoo 19 actual behavior wins over remembered APIs.

---

# 43. IF A THIRD-PARTY DEPENDENCY SEEMS NECESSARY

Before adding it ask:

```text
Can native Odoo do this?
Can OWL/QWeb/CSS do this?
Can a small custom implementation do this?
```

Only add a dependency if it provides substantial value and does not compromise maintainability.

---

# 44. FINAL PROJECT STATE

Before finishing, update:

```text
EDARA_PROJECT_STATE.md
```

with:

```text
STATUS: COMPLETE / BLOCKED

Odoo Version:
Module Version:

Completed Phases:
- Phase 0
- Phase 1
...
- Phase 15

Implemented Models:

Implemented Features:

Accounting Validation:

Security Validation:

Portal Validation:

Tests:

Known Issues:

Remaining Non-Critical Items:

Architecture Decisions:

Files Created/Modified:

Final Audit Result:
```

If anything remains incomplete, clearly identify it.

Do not falsely report completion.

---

# 45. FINAL RESPONSE

When the entire implementation is complete, provide a concise final report containing:

```text
EDARA IMPLEMENTATION COMPLETE

Odoo Version:
Module:
Module Version:

Implemented:
- ...

Accounting:
- ...

Security:
- ...

Portal:
- ...

UX:
- ...

Testing:
- ...

Validation:
- ...

Known Non-Critical Items:
- ...

Project State:
EDARA_PROJECT_STATE.md
```

Do not dump thousands of lines of code into the final response.

The code belongs in the project.

---

# 46. START NOW

Your first actions are:

```text
1. Read EDARA_IMPLEMENTATION_SPEC.md
2. Inspect the current repository
3. Inspect actual Odoo 19 source
4. Inspect existing property_managment code
5. Create/update EDARA_PROJECT_STATE.md
6. Build an internal execution plan
7. Begin implementation
8. Test continuously
9. Fix problems autonomously
10. Continue through every required phase
11. Perform final audit
12. Update EDARA_PROJECT_STATE.md
13. Report completion
```

Do not wait for another prompt.

Start the implementation now.

END OF MASTER PROMPT.
