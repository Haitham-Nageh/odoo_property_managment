# EDARA — Odoo 19 Property Management System

## Complete Product & Technical Implementation Specification

### Source of Truth

**Document:** EDARA_IMPLEMENTATION_SPEC.md
**Product:** EDARA Property Management
**Platform:** Odoo 19.0
**Implementation:** Native Odoo Custom Module
**Primary Addon:** `property_managment`
**Status:** Authoritative Implementation Specification

---

# 1. PURPOSE

EDARA is a professional property-management system implemented natively inside Odoo 19.

The system manages the complete rental lifecycle:

```text
Company
  ↓
Branch
  ↓
Property
  ↓
Building
  ↓
Unit
  ↓
Owner
  ↓
Tenant
  ↓
Lease Contract
  ↓
Payment Schedule
  ↓
Invoice
  ↓
Payment
  ↓
Reconciliation
```

Additional operational flows:

```text
Property
 ├── Ownership
 ├── Buildings
 ├── Units
 ├── Contracts
 ├── Financials
 ├── Expenses
 ├── Service Charges
 ├── Maintenance
 ├── Documents
 └── Reporting
```

EDARA MUST feel like a serious commercial Property Management System rather than a technical Odoo customization.

The system must be usable by:

- Property owners
- Property management companies
- Property managers
- Branch managers
- Accountants
- Front-desk / administrative staff
- Maintenance staff
- Read-only users
- Tenants through the Odoo portal

---

# 2. ABSOLUTE PLATFORM RULE

EDARA MUST be implemented for:

**Odoo 19.0**

Before implementing anything, the developer/agent MUST inspect the actual installed Odoo 19 source code and installed addons.

Do NOT assume APIs from:

- Odoo 16
- Odoo 17
- Odoo 18
- Odoo 20
- Internet tutorials
- outdated StackOverflow examples

Actual installed Odoo 19 behavior is authoritative for framework/API behavior.

---

# 3. NATIVE ODOO FIRST

EDARA MUST reuse Odoo functionality whenever practical.

Do NOT create custom replacements for functionality that Odoo already provides.

Prefer:

- `res.company`
- `res.partner`
- `res.users`
- `account.move`
- `account.payment`
- payment registration wizard
- `account.partial.reconcile`
- `res.currency`
- `ir.attachment`
- `mail.thread`
- `mail.activity.mixin`
- `mail.message`
- `ir.cron`
- native access control
- native record rules
- native portal
- native accounting
- native analytic accounting
- native reporting mechanisms
- native chatter
- native activities
- native sequences
- native translations

EDARA MUST NOT create a second accounting ledger.

---

# 4. BUSINESS MODEL

EDARA supports two conceptual operating models.

## 4.1 MVP — Principal Model

The company manages properties it owns or treats as its own rental portfolio.

Rent collected is company income.

```text
Tenant
   ↓
Rent Invoice
   ↓
Accounts Receivable
   ↓
Rental Income
```

This is the MVP accounting model.

---

## 4.2 Future — Agency / Property Management Model

A future customer may manage properties owned by third-party owners.

In that case:

```text
Tenant Rent
    ↓
Owner Payable / Liability
    ↓
Management Fee
    ↓
Expenses
    ↓
Owner Settlement
```

The architecture MUST NOT prevent this future model.

Do not build the complete agency settlement system unless explicitly included in the current implementation scope, but ensure today's architecture does not make it impossible.

---

# 5. DOMAIN HIERARCHY

The canonical hierarchy is:

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

---

# 6. COMPANY

Use:

```text
res.company
```

for the legal/accounting company.

Do NOT create `edara.company` unless absolutely required by an actual Odoo limitation.

Odoo multi-company behavior must be respected.

Each relevant EDARA record must have a company relationship, directly or through its parent where appropriate.

---

# 7. BRANCH

Model:

```text
edara.branch
```

Purpose:

- geographic branch
- operational region
- staff assignment
- reporting
- management scope

Examples:

```text
Ramallah Branch
Nablus Branch
Jenin Branch
```

A branch:

- belongs to one `res.company`
- does not represent a separate legal company
- does not create a separate chart of accounts
- does not create separate journals
- does not imply intercompany accounting

Suggested core fields:

```text
name
code
company_id
manager_id
user_ids
active
address/contact fields where useful
```

Branch code must be unique within the company.

---

# 8. PROPERTY

Model:

```text
edara.property
```

A Property is the ownership and financial boundary.

Examples:

```text
Al-Irsal Complex
Al-Masyoun Residence
Rafidia Complex
```

A Property:

- belongs to one branch
- belongs to one company
- has ownership information
- owns/builds the financial identity of the property
- has one Property-level analytic account
- contains one or more buildings
- rolls up buildings and units
- is the primary financial reporting granularity

A Property is NOT merely a UI grouping.

---

# 9. BUILDING

Model:

```text
edara.building
```

Building is the physical boundary.

Every property MUST contain at least one Building when units are created.

Even a single-building property uses:

```text
Property
  └── Building
       └── Units
```

Do not introduce optional "unit without building" logic.

Suggested fields:

```text
name
code
property_id
address
floor_count
unit_count
active
```

Building numbering must support:

- floor
- unit number
- labels/codes
- future floor-plan visualization

---

# 10. UNIT

Model:

```text
edara.unit
```

Unit is the leasing boundary.

Examples:

```text
A-101
A-102
Shop-01
Office-304
Villa-02
```

Suggested fields:

```text
name
code
building_id
property_id
branch_id
company_id
floor
unit_number
unit_type
area
bedrooms
bathrooms
rent_amount_default
currency_id
occupancy_status
operational_status
active
```

Where practical, parent fields may be related/stored for fast reporting.

Important:

For large portfolios, fields used frequently for filtering/reporting should be stored and indexed where justified.

---

# 11. UNIT STATUS

EDARA distinguishes business occupancy from operational availability where useful.

Canonical occupancy statuses:

```text
AVAILABLE
RESERVED
RENTED
SOLD
OWNER_OCCUPIED
UNDER_MAINTENANCE
```

The implementation MUST avoid contradictory states.

Examples:

- A rented unit cannot simultaneously be available.
- A unit under maintenance cannot be offered as available unless business rules explicitly permit scheduling after maintenance.
- A sold unit cannot receive a new rental contract.

Status should be derived/computed wherever practical rather than allowing arbitrary manual manipulation.

---

# 12. OWNERSHIP

Model:

```text
edara.ownership
```

Ownership is attached to the Property level.

A Property can have multiple owners.

Example:

```text
Property: Al-Irsal Complex

Owner A = 60%
Owner B = 40%
```

Ownership records should support:

```text
property_id
owner_id
ownership_percentage
date_from
date_to
active
company_id
```

Business rules:

- ownership percentages must not exceed 100%
- active ownership should normally total 100%
- ownership history must be preserved
- never overwrite historical ownership records when changing ownership
- close the old ownership period and create a new record
- validate overlapping periods

Owners use `res.partner`.

No separate duplicate owner contact model.

Owner flagging may use fields such as:

```text
is_edara_owner
```

---

# 13. TENANTS

Tenants use:

```text
res.partner
```

Do NOT create a duplicate `edara.tenant` contact model.

Useful EDARA fields:

```text
is_edara_tenant
```

Tenant information may include:

- name
- phone
- mobile
- email
- address
- identification information where legally appropriate
- emergency/contact information where needed
- portal access

Tenant identity MUST always resolve to the actual `res.partner` associated with the authenticated user.

---

# 14. LEASE CONTRACT

Model:

```text
edara.lease.contract
```

The contract is the core rental business object.

Suggested fields:

```text
name
reference
company_id
branch_id
property_id
building_id
unit_id
tenant_id
start_date
end_date
currency_id
rent_amount
billing_frequency
payment_day
deposit_amount
deposit_required
state
renewal fields
termination fields
notes
```

Contract states:

```text
DRAFT
ACTIVE
RENEWED
TERMINATED
EXPIRED
```

A renewed contract must retain historical traceability.

Do not destroy or overwrite previous contract history.

---

# 15. CONTRACT VALIDATION

Before activation:

- tenant must exist
- unit must exist
- dates must be valid
- end date must be after start date
- rent must be valid
- currency must be valid
- company must be consistent
- branch/property/building/unit hierarchy must be consistent
- unit must be eligible for rental
- overlapping active contracts must be prevented

The system must prevent two active overlapping leases on the same unit unless an explicit business rule allows it.

---

# 16. PAYMENT SCHEDULE

Model:

```text
edara.payment.schedule.line
```

A contract generates payment schedule lines.

Suggested fields:

```text
contract_id
tenant_id
unit_id
property_id
building_id
branch_id
company_id
due_date
amount
currency_id
invoice_id
state
description
sequence
```

Payment schedule status MUST be derived from the linked invoice/payment state.

Do not make financial status freely manually editable.

Possible derived statuses:

```text
DRAFT
DUE
PARTIAL
PAID
OVERDUE
CANCELLED
```

---

# 17. RENT INVOICING

Rent invoices MUST use:

```text
account.move
move_type = out_invoice
```

Accounting:

```text
Dr Accounts Receivable
Cr Rental Income
```

The invoice must contain sufficient EDARA context:

```text
contract
tenant
unit
building
property
branch
company
```

Use native Odoo invoice behavior.

Do not create an `edara.invoice` accounting replacement.

---

# 18. AUTOMATIC INVOICE GENERATION

Use an Odoo scheduled action / cron.

The cron must:

1. find eligible payment schedule lines
2. verify contract is still active
3. verify line has no existing invoice
4. verify unit/tenant/company consistency
5. create invoice using native Odoo accounting
6. link the invoice to the schedule line
7. preserve EDARA context
8. prevent duplicate invoices
9. work in batches
10. be safe if executed more than once

Critical rule:

Contract termination MUST prevent future uninvoiced schedule lines from becoming invoices.

The invoice cron MUST re-check this even if schedule lines were created earlier.

Do not rely only on a UI button or state change.

---

# 19. DUPLICATE INVOICE PROTECTION

The system must be idempotent.

If the cron executes twice:

```text
Schedule line → exactly one intended invoice
```

Use appropriate:

- ORM checks
- database constraints where appropriate
- transactional logic
- unique constraints where appropriate

Do not depend solely on:

```python
if not invoice_id:
```

if race conditions could still produce duplicates.

---

# 20. SERVICE CHARGES

Service charges must support allocation.

Model(s) may include:

```text
edara.service.charge
edara.service.charge.line
```

Allocation methods:

```text
EQUAL
PROPORTIONAL
PER_SQM
FIXED_PER_UNIT
```

Example:

Building service charge:

```text
Total = 10,000 ILS
```

Possible allocation:

```text
Equal
Proportional by ownership/area
Per square meter
Fixed amount per unit
```

Generated tenant charges must become native Odoo invoices.

---

# 21. LATE FEES

Late fees use native invoices.

Accounting:

```text
Dr Accounts Receivable
Cr Late Fee Income
```

Late fee rules must be configurable.

Do not automatically charge arbitrary late fees without a business rule.

---

# 22. TENANT PAYMENTS

Tenant payments must use native Odoo payment mechanisms.

Primary mechanism:

```text
account.payment.register
```

or the actual Odoo 19 equivalent verified from source.

Payment methods may include:

- cash
- bank transfer
- cheque
- other configured methods

The business UI should be simple.

Preferred UX:

```text
Receive Payment

Tenant:      Ahmed
Invoice:     INV/2026/001
Outstanding: 500 ILS

Amount:      500 ILS
Method:      Bank
Reference:   TRANS-123

[Confirm Payment]
```

The underlying accounting must remain native.

---

# 23. PARTIAL PAYMENTS

If invoice:

```text
500 ILS
```

and payment:

```text
200 ILS
```

then:

```text
Invoice residual = 300 ILS
Payment = 200 ILS
Invoice state = PARTIAL
```

Do not create a separate EDARA partial-payment ledger.

Use native reconciliation.

---

# 24. OVERPAYMENTS

Overpayment MUST NOT be rejected.

Example:

```text
Invoice = 500 ILS
Payment = 600 ILS
```

Expected:

```text
500 → reconciled against invoice
100 → tenant credit / unreconciled receivable
```

Use the actual Odoo 19 payment registration behavior.

Do not create a custom "credit balance" ledger.

The system should expose the credit in a user-friendly manner.

---

# 25. FINANCIAL CORRECTIONS

Never delete posted financial records.

Use native Odoo mechanisms:

```text
Credit Notes
Reversals
Refunds
Payment cancellation/reversal
Reconciliation
```

Invoice correction:

```text
Original invoice
      ↓
Credit note / reversal
      ↓
Corrected invoice
```

Preserve links and audit trail.

---

# 26. SECURITY DEPOSIT

Model:

```text
edara.deposit
edara.deposit.transaction
```

A deposit is NOT rental revenue by default.

Default accounting:

### Deposit Held

```text
Dr Bank/Cash
Cr Security Deposit Liability
```

### Deposit Refund

```text
Dr Security Deposit Liability
Cr Bank/Cash
```

### Deposit Deduction

```text
Dr Security Deposit Liability
Cr Damage Recovery Income / applicable account
```

Exact account configuration MUST be company-configurable.

Do not hardcode the liability account.

If required configuration is missing, show a clear blocking error:

```text
Configure a Security Deposit account before recording deposits.
```

Never silently post deposits to Accounts Receivable.

---

# 27. DEPOSIT ACCOUNTING IMPLEMENTATION

If overriding or extending:

```text
account.payment.destination_account_id
```

or equivalent Odoo 19 mechanism, inspect actual Odoo 19 implementation first.

The extension must be minimal and safe.

A security-deposit payment should redirect its destination account to the configured liability account.

The business model:

```text
edara.deposit.transaction
```

is only an index/audit layer.

It is NOT a parallel financial ledger.

Each transaction must point to the actual:

```text
account.payment
```

or:

```text
account.move
```

record.

---

# 28. DEPOSIT TRANSACTION TYPES

Support:

```text
HELD
REFUND
DEDUCTION
```

Preserve transaction history.

Do not delete financial history.

---

# 29. EXPENSES

Property expenses must use native Odoo accounting.

Typical flow:

```text
Vendor Bill
Dr Expense
Cr Accounts Payable
```

or applicable native accounting mechanism.

Expense records should be associated with:

```text
branch
property
building
unit where applicable
```

Analytic distribution should identify the Property.

---

# 30. ANALYTIC ACCOUNTING

Use native Odoo analytic accounting.

Primary design:

```text
One analytic account per Property
```

Not:

```text
One analytic account per unit
```

Not:

```text
One analytic account per building
```

A large property portfolio could have:

```text
5,000 units
```

but only perhaps:

```text
300 properties
```

Analytic accounting should therefore scale with Property count.

Recommended plan:

```text
EDARA Property Analytics
```

Each Property has one analytic account.

---

# 31. BRANCH / BUILDING / UNIT FINANCIAL CONTEXT

Branch/building/unit do not need separate analytic accounts.

Use stored indexed business fields where appropriate:

```text
branch_id
property_id
building_id
unit_id
```

on EDARA-related accounting records / invoice lines as required by implementation.

Reports can use:

```text
read_group
domains
stored relations
```

rather than creating thousands of analytic accounts.

---

# 32. FUTURE OWNER SETTLEMENT

Architecture must remain compatible with:

```text
Property Management Company
        ↓
Third-party Property Owner
        ↓
Tenant
```

Future accounting:

```text
Tenant Rent
    ↓
Owner Payable Liability

Management Fee
    ↓
Management Fee Income

Property Expense
    ↓
Reduces Owner Payable

Owner Settlement
    ↓
Bank
```

Future feature may include:

```text
edara.owner.settlement
```

with:

- owner statement
- management fee
- expenses
- net payable
- settlement payment
- reconciliation

Do not implement the full feature unless included in the active scope.

---

# 33. MULTI-CURRENCY

Use:

```text
res.currency
```

Contracts must support currencies independent of company default where appropriate.

Example:

```text
Company currency = ILS
Lease currency = USD
```

or:

```text
Lease currency = JOD
```

Historical posted accounting must remain immutable.

Do not manually rewrite historical exchange rates.

Use native Odoo currency conversion.

---

# 34. MULTI-COMPANY

EDARA MUST support Odoo multi-company correctly.

Every record must respect company isolation.

A user belonging to Company A must not see Company B records unless explicitly permitted by legitimate Odoo configuration.

Do not bypass standard Odoo multi-company security.

---

# 35. SECURITY GROUPS

Create appropriate EDARA groups.

At minimum:

```text
EDARA Administrator
EDARA Company Manager
EDARA Branch Manager
EDARA Property Manager
EDARA Accountant
EDARA Maintenance Staff
EDARA Viewer
EDARA Portal Tenant
```

Where useful, distinguish:

```text
internal users
portal users
```

Do not give all EDARA users unrestricted access.

---

# 36. SECURITY MODEL

Security MUST be enforced at the ORM/security layer.

Not only through menus.

Not only through hidden buttons.

Not only through JavaScript.

Not only through controllers.

Record rules and ACLs are mandatory.

Direct record access must also be protected.

---

# 37. BRANCH ISOLATION

Example:

```text
Company A
 ├── Ramallah Branch
 └── Nablus Branch
```

A user assigned to Ramallah must not see Nablus records if their role is branch-scoped.

Record rules should derive access from:

```text
branch.user_ids
```

or equivalent assignment.

Administrator/company manager bypass must be deliberate and controlled.

---

# 38. PROPERTY MANAGER

A Property Manager must only see records they are authorized to manage.

Do not accidentally give Property Manager an unrestricted bypass simply because they belong to an EDARA group.

---

# 39. PORTAL SECURITY

Tenant portal identity MUST be derived from:

```python
env.user.partner_id
```

Never trust:

```text
tenant_id
partner_id
contract_id
invoice_id
```

posted by the browser.

Controllers must verify that the requested document belongs to the authenticated tenant.

Use Odoo's native portal access patterns such as `_document_check_access` where appropriate.

Unauthorized records should not leak their existence.

Prefer:

```text
404 / inaccessible
```

rather than exposing whether another tenant's record exists.

---

# 40. TENANT PORTAL

Tenant portal should eventually provide:

```text
Dashboard
My Lease
My Unit
Invoices
Payments
Outstanding Balance
Payment History
Renewal Requests
Maintenance Requests
Documents
Notifications
Profile
```

Business language should be used.

Example:

```text
Outstanding
350 ILS
```

instead of exposing technical accounting concepts by default.

Accountants still retain access to full accounting details.

---

# 41. MAINTENANCE

Do NOT force EDARA maintenance into native `maintenance.request` if the actual Odoo 19 implementation is equipment-centric and unsuitable.

Use:

```text
edara.maintenance.request
```

for property/unit maintenance.

Suggested fields:

```text
reference
title
description
tenant_id
property_id
building_id
unit_id
branch_id
company_id
assigned_user_id
priority
state
requested_date
completed_date
cost
vendor
attachments
```

Initial lifecycle:

```text
NEW
ASSIGNED
IN_PROGRESS
DONE
CANCELLED
```

Use:

```text
mail.thread
mail.activity.mixin
```

where appropriate.

---

# 42. DOCUMENTS

Community Odoo may not have Enterprise Documents.

Use:

```text
ir.attachment
```

and native attachment functionality.

Documents may be associated with:

- property
- building
- unit
- contract
- tenant
- maintenance request
- invoice

Do not create a redundant file-storage system.

---

# 43. CHATTER

Important business records should use:

```text
mail.thread
```

Examples:

- Property
- Unit
- Lease Contract
- Maintenance Request
- Deposit

Use chatter for:

- history
- notes
- communication
- audit context
- attachments

---

# 44. ACTIVITIES

Use:

```text
mail.activity.mixin
```

where useful.

Examples:

```text
Lease renewal due
Outstanding rent follow-up
Maintenance follow-up
Document expiration
```

---

# 45. RENEWALS

Model:

```text
edara.renewal.request
```

or an equivalent native-friendly implementation.

Renewal workflow:

```text
Active Contract
      ↓
Renewal Due
      ↓
Renewal Request
      ↓
Approved
      ↓
New / Extended Contract
```

Do not destroy previous contract history.

---

# 46. TERMINATION

When a contract is terminated:

- state becomes TERMINATED
- termination date recorded
- future uninvoiced schedule lines become cancelled/ineligible
- future invoice generation must stop
- already posted invoices remain intact
- already posted payments remain intact
- accounting history remains intact

Never delete historical financial records.

---

# 47. DASHBOARD

EDARA needs a professional management dashboard.

At minimum, design for:

```text
Total Properties
Total Buildings
Total Units
Occupied Units
Available Units
Under Maintenance
Monthly Revenue
Outstanding Receivables
Upcoming Renewals
Open Maintenance
Recent Payments
```

Use Odoo-native dashboard/action/view architecture where practical.

Avoid unnecessary external frontend frameworks.

---

# 48. VISUAL PROPERTY MANAGEMENT

The UI should provide a visual overview.

A unit grid/floor visualization should be possible.

Example:

```text
Floor 1

┌────────┬────────┬────────┬────────┐
│ A-101  │ A-102  │ A-103  │ A-104  │
│ RENTED │ FREE   │ RENTED │ MAINT. │
└────────┴────────┴────────┴────────┘
```

Status should be visually obvious.

Preferred implementation:

- OWL component
- QWeb/kanban
- CSS grid
- native Odoo frontend architecture

Avoid unnecessary third-party dependencies.

---

# 49. 3D VISUALIZATION

3D visualization is desirable only if it improves usability and remains maintainable.

It is NOT a mandatory dependency for the core system.

Priority:

```text
1. Excellent 2D visualization
2. Optional 3D enhancement
```

Do not compromise system stability for 3D.

If 3D is implemented, isolate it from the accounting/domain layer.

---

# 50. UX PRINCIPLES

EDARA must be understandable to nontechnical users.

Avoid exposing technical terms unnecessarily.

Prefer:

```text
Receive Payment
```

instead of:

```text
Register Account Payment
```

Prefer:

```text
Outstanding Rent
```

instead of:

```text
Receivable Residual
```

Prefer:

```text
Property
Building
Unit
Tenant
Contract
```

rather than internal technical names.

---

# 51. QUICK ACTIONS

Useful quick actions should exist:

```text
New Property
New Building
New Unit
New Tenant
New Contract
Receive Payment
Create Maintenance Request
Record Deposit
Renew Contract
```

---

# 52. SMART BUTTONS

Useful smart buttons:

### Property

```text
Buildings
Units
Contracts
Invoices
Expenses
Maintenance
Documents
```

### Building

```text
Units
Contracts
Maintenance
Invoices
```

### Unit

```text
Contracts
Invoices
Payments
Maintenance
Documents
```

### Contract

```text
Payment Schedule
Invoices
Payments
Deposit
Renewals
Documents
```

---

# 53. ACCOUNTING TRACEABILITY

The business user should be able to navigate:

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
Invoice
 ↓
Payment
 ↓
Accounting Entry
```

The chain must remain intact.

---

# 54. ACCOUNTING UI

Accountants must still have access to native:

```text
Journal Items
Accounting Entries
Reconciliation
Payment
Invoice
Credit Note
```

Property Managers should not be overwhelmed by technical accounting information.

Hide/de-emphasize technical accounting navigation in their views where appropriate, without weakening actual permissions.

---

# 55. REPORTS

Provide useful reports.

At minimum:

### Revenue

```text
Revenue by Property
Revenue by Branch
Revenue by Building
Revenue by Period
```

### Occupancy

```text
Occupied
Available
Reserved
Maintenance
Sold
Owner Occupied
```

### Receivables

```text
Outstanding
Overdue
Partial
Paid
Tenant balance
```

### Expenses

```text
Expenses by Property
Expenses by Building
Expenses by Period
```

### Property Financial Summary

```text
Revenue
Expenses
Net Operating Result
Outstanding
```

Use native Odoo accounting/reporting capabilities wherever possible.

---

# 56. DATA VALIDATION

Validation must exist both:

- in UI
- server-side

Never rely only on XML/UI restrictions.

Examples:

- negative rent
- invalid dates
- overlapping contracts
- ownership > 100%
- mismatched company
- mismatched branch/property/building/unit
- invalid deposit account
- invalid currency
- cross-company references

must be rejected appropriately.

---

# 57. DATABASE CONSTRAINTS

Use SQL constraints where appropriate.

Examples:

- unique branch code per company
- unique property code where required
- unique building code within property
- unique unit code within building/property
- unique invoice link per payment schedule line
- valid ownership percentages
- appropriate non-null relationships

Do not overuse database constraints where business rules require date-aware ORM logic.

---

# 58. PERFORMANCE

The system must be designed for thousands of units.

Avoid:

```python
for every record:
    search()
    create()
```

when a batch operation is possible.

Prefer:

- batched ORM operations
- `read_group`
- stored fields where appropriate
- indexed foreign keys
- selective prefetching
- efficient domains
- minimal computed-field dependencies

---

# 59. COMPUTED FIELDS

Computed fields must have narrow dependencies.

Do not make:

```text
unit occupancy status
```

recompute because an unrelated invoice somewhere in the database changed.

Use precise `@api.depends`.

Store values when beneficial for frequent filtering/reporting.

---

# 60. CRON DESIGN

Scheduled actions must be:

- idempotent
- batch-oriented
- safe to rerun
- logged appropriately
- company-aware
- resistant to duplicate processing

Potential jobs:

```text
Generate Due Rent Invoices
Update Contract Expiration
Create Renewal Reminders
Update Overdue State
Maintenance reminders
```

---

# 61. AUDITABILITY

Important actions must remain traceable.

Never silently:

- delete posted invoices
- delete payments
- overwrite ownership history
- overwrite terminated contracts
- rewrite financial history

Use Odoo chatter/history/accounting reversal mechanisms.

---

# 62. IMPORT / EXPORT

The system should be designed to support importing:

```text
Properties
Buildings
Units
Owners
Tenants
Contracts
```

Use Odoo native import compatibility where possible.

Do not build a complicated custom import engine unless required.

---

# 63. INTERNATIONALIZATION

EDARA must support:

```text
Arabic
English
```

The UI must work with:

```text
LTR
RTL
```

All user-facing strings must be translatable.

Avoid hardcoded UI text in Python/JavaScript where translation is required.

Arabic labels should be professionally written.

---

# 64. CURRENCIES

Primary expected currencies:

```text
ILS
JOD
USD
```

Do not hardcode these as the only currencies.

Use Odoo currency records.

---

# 65. PAYMENT METHODS

Support the configured Odoo payment methods/journals relevant to the company.

Common business methods:

```text
Cash
Bank Transfer
Cheque
```

Do not hardcode journal IDs.

---

# 66. ACCESSIBILITY

UI should provide:

- readable labels
- logical hierarchy
- clear status indicators
- keyboard-friendly controls where practical
- meaningful empty states
- useful error messages

Do not rely solely on color to communicate status.

---

# 67. ERROR HANDLING

Errors must be understandable.

Bad:

```text
ValidationError: False
```

Better:

```text
Cannot activate this contract because the selected unit already has an active lease during this period.
```

For configuration errors:

```text
A Security Deposit Liability account is not configured for this company.
Please configure it before recording a deposit.
```

---

# 68. NO SILENT FALLBACKS

Do not silently:

- use wrong company
- use wrong branch
- post deposits to receivable
- create invoices without a contract
- create cross-company records
- use a default account when required configuration is missing

Fail safely and explain why.

---

# 69. MODULE DEPENDENCIES

The implementation must inspect the actual installed environment and select dependencies based on real functionality.

Likely dependencies include:

```text
base
web
mail
contacts
account
portal
```

Add others only where required.

Do not add unnecessary dependencies.

If HR, maintenance, website, or other modules are not actually required for the implementation, do not make them mandatory dependencies simply because they exist.

---

# 70. PROJECT STRUCTURE

A maintainable structure should be used, for example:

```text
property_managment/
├── __init__.py
├── __manifest__.py
│
├── models/
│   ├── __init__.py
│   ├── branch.py
│   ├── property.py
│   ├── building.py
│   ├── unit.py
│   ├── ownership.py
│   ├── lease_contract.py
│   ├── payment_schedule.py
│   ├── deposit.py
│   ├── maintenance.py
│   ├── service_charge.py
│   └── account_move.py
│
├── security/
│   ├── security.xml
│   ├── ir.model.access.csv
│   └── record_rules.xml
│
├── views/
│   ├── branch_views.xml
│   ├── property_views.xml
│   ├── building_views.xml
│   ├── unit_views.xml
│   ├── ownership_views.xml
│   ├── contract_views.xml
│   ├── payment_schedule_views.xml
│   ├── deposit_views.xml
│   ├── maintenance_views.xml
│   ├── service_charge_views.xml
│   ├── dashboard_views.xml
│   ├── menus.xml
│   └── account_move_views.xml
│
├── wizard/
├── controllers/
├── data/
│   ├── sequences.xml
│   ├── cron.xml
│   └── configuration.xml
│
├── reports/
├── static/
│   └── src/
│
└── tests/
```

This is a guideline, not an excuse to create unnecessary files.

---

# 71. PROJECT STATE

Claude MUST maintain:

```text
EDARA_PROJECT_STATE.md
```

This file records:

```text
Current Phase
Completed Phases
Implemented Models
Implemented Views
Security Status
Accounting Status
Portal Status
Tests
Known Issues
Architecture Decisions
Pending Issues
Next Internal Phase
Final Validation Status
```

The state file is a progress record.

This specification remains the source of truth.

---

# 72. IMPLEMENTATION PHASES

Claude should execute these phases autonomously.

## Phase 0 — Environment & Architecture Verification

Inspect:

- Odoo version
- addons
- PostgreSQL
- existing modules
- existing `property_managment`
- actual Odoo accounting APIs
- portal APIs
- security APIs

Do not modify unrelated modules.

---

## Phase 1 — Foundation

Implement:

- manifest
- module structure
- company integration
- branch
- security foundation
- ACLs
- record rules
- sequences
- menus
- base views

---

## Phase 2 — Property Structure

Implement:

- property
- building
- unit
- ownership
- validations
- hierarchy
- statuses
- smart buttons

---

## Phase 3 — Tenant & Lease

Implement:

- tenant partner extensions
- lease contract
- contract lifecycle
- validation
- overlap protection
- renewals foundation
- chatter

---

## Phase 4 — Payment Scheduling

Implement:

- payment schedule
- recurring rent logic
- due states
- schedule/invoice links
- cron foundation
- duplicate protection

---

## Phase 5 — Accounting Integration

Implement:

- rent invoices
- analytic context
- invoice extensions
- native payment workflow
- partial payments
- overpayments
- reconciliation
- corrections
- currency support

---

## Phase 6 — Deposits

Implement:

- deposit
- deposit transaction
- liability configuration
- deposit payment
- refund
- deduction
- accounting tests

---

## Phase 7 — Service Charges & Expenses

Implement:

- service charges
- allocation engine
- service charge invoicing
- expense integration
- analytics

---

## Phase 8 — Maintenance

Implement:

- maintenance requests
- assignment
- status lifecycle
- chatter
- activities
- costs
- attachments

---

## Phase 9 — Portal

Implement:

- tenant portal dashboard
- lease
- unit
- invoices
- payments
- outstanding
- maintenance
- documents
- renewals
- security isolation

---

## Phase 10 — Reporting

Implement:

- revenue
- occupancy
- receivables
- expenses
- property summary
- branch summary
- tenant ledger
- useful filters/grouping

---

## Phase 11 — UX

Implement:

- dashboard
- smart buttons
- quick actions
- polished forms
- kanban views
- status visualization
- empty states
- professional navigation

---

## Phase 12 — Visual Property Management

Implement a maintainable visual unit/floor representation.

Preferred:

```text
OWL / QWeb / CSS grid
```

Optional:

```text
3D enhancement
```

3D MUST NOT become a core dependency for accounting/domain functionality.

---

## Phase 13 — Hardening

Audit:

- security
- record rules
- multi-company
- portal isolation
- direct URLs
- forged IDs
- company mismatches
- branch mismatches
- financial integrity
- duplicate cron execution
- performance

---

## Phase 14 — Full Test & Regression

Run:

- module install
- module upgrade
- Python tests
- ORM tests
- security tests
- accounting tests
- portal tests
- cron tests
- multi-company tests
- validation tests

Fix all discovered issues.

---

## Phase 15 — Final Product Audit

Verify:

```text
Functional completeness
Accounting correctness
Security correctness
Performance
UX
RTL/LTR
Arabic/English
Maintainability
Upgrade safety
```

Only then declare completion.

---

# 73. REQUIRED TEST SCENARIOS

At minimum:

### Security

```text
Company A cannot access Company B
Branch A cannot access Branch B
Property Manager cannot bypass branch rules
Tenant A cannot access Tenant B
Forged contract ID fails
Forged invoice ID fails
Direct URL access fails
```

### Contracts

```text
Create
Activate
Renew
Terminate
Expire
Overlap prevention
```

### Accounting

```text
Invoice
Full payment
Partial payment
Overpayment
Credit
Refund
Reversal
```

### Deposits

```text
Hold
Partial refund
Full refund
Deduction
Missing liability account
```

### Cron

```text
Run once
Run twice
Run concurrently where practical
Terminated contract
Already invoiced schedule
```

---

# 74. FINANCIAL INVARIANTS

The implementation must preserve:

```text
No duplicate invoice for same schedule line
No posted financial record deletion
No deposit silently posted to receivable
No payment silently lost
No overpayment discarded
No cross-company accounting
No unauthorized reconciliation
No financial record without correct company
```

---

# 75. UX DEFINITION OF DONE

A nontechnical property manager should be able to:

```text
Create Property
→ Create Building
→ Create Unit
→ Add Tenant
→ Create Lease
→ Generate Rent Schedule
→ Generate Invoice
→ Receive Payment
→ See Outstanding Balance
```

without needing to understand accounting journal mechanics.

An accountant must still be able to inspect the full native accounting chain.

---

# 76. TECHNICAL DEFINITION OF DONE

The implementation is complete only if:

- module installs
- module upgrades
- all XML loads
- all Python imports
- no unresolved external IDs
- no broken actions
- no broken menus
- no broken views
- ACLs work
- record rules work
- portal rules work
- accounting works
- cron works
- tests pass
- no critical TODOs remain
- no known critical security issue remains
- no known critical accounting issue remains

---

# 77. OUT OF SCOPE UNLESS REQUIRED

Do not introduce unnecessary complexity such as:

- external Node backend
- React application
- separate PostgreSQL application database
- custom authentication system
- custom accounting ledger
- custom payment ledger
- external file-storage platform
- unnecessary microservices
- unnecessary third-party UI frameworks

EDARA is an Odoo-native system.

---

# 78. FINAL PRODUCT PRINCIPLE

EDARA should combine:

```text
Odoo's Accounting
+
Odoo's Security
+
Odoo's ORM
+
Odoo's Portal
+
Odoo's Chatter
+
Odoo's Activities
+
EDARA's Property Domain
+
EDARA's UX
```

The result must feel like:

**A professional Property Management System built natively on Odoo 19.**

Not:

**an Odoo database with a few custom forms.**

---

# 79. ARCHITECTURE PRIORITY ORDER

When two requirements conflict, use this priority:

```text
1. Financial correctness
2. Security
3. Data integrity
4. Odoo 19 compatibility
5. Business correctness
6. Scalability
7. Maintainability
8. UX
9. Visual enhancement
```

Never sacrifice:

```text
Accounting
Security
Data integrity
```

for visual features.

---

# 80. SOURCE OF TRUTH RULE

This file is the authoritative product specification.

Claude MUST:

1. Read this file before implementation.
2. Follow it throughout implementation.
3. Update `EDARA_PROJECT_STATE.md`.
4. Resolve implementation details using actual Odoo 19 source.
5. Never silently contradict this specification.
6. If a technical conflict is discovered, document it in the project state and choose the safest compatible implementation.
7. Continue implementation autonomously.

END OF SPECIFICATION.
