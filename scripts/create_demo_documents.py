"""Rebuild eight selectable-text, fictional business PDFs with deterministic layout."""

import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "apps/api/app/static/demo/business"


def page(title, summary, sections, table=None, note=None):
    return {"title": title, "summary": summary, "sections": sections, "table": table, "note": note}


DOCS = [
    {
        "file": "employee-handbook-2026.pdf", "title": "Employee handbook", "id": "AV-HR-001",
        "owner": "People Operations", "version": "2.0", "effective": "01 January 2026",
        "pages": [
            page("Employment and leave", "A practical reference for permanent, full-time employees of Aster Vale Technologies. Contractor benefits are governed by the signed engagement, not this handbook.", [
                ("01 / Scope and authority", "People Operations owns this handbook. The People Director approved version 2.0 on 15 December 2025. It replaces version 1.0 for leave beginning on or after 01 January 2026. Local employment obligations and an employee's signed contract take precedence if they provide a different mandatory entitlement. Managers must ask People Operations to resolve exceptions rather than interpret them informally."),
                ("02 / Annual leave", "Annual leave allowance is 24 working days per calendar year. For a mid-year joiner, People Operations calculates a prorated balance using complete months of service. Up to 5 days of unused annual leave may carry into the following year and must be used by 31 March. The carryover balance is not added permanently to the annual entitlement."),
                ("03 / Probation and notice", "New employees complete a 90-day probation period. The manager records a review on day 75 and People Operations confirms the outcome before day 90. The standard employee resignation notice period is 30 calendar days, subject to the signed contract. Unused leave cannot automatically replace the notice period."),
            ], note="Document control: AV-HR-001 / approved / fictional company policy. This document is demonstration content, not legal or employment advice."),
            page("Requesting time away", "Use the People portal as the system of record. Messages in a team chat are a courtesy notification and do not replace a recorded request.", [
                ("04 / Planned leave", "Submit planned annual leave at least 7 calendar days before the first day away. The line manager should approve or request clarification within 2 business days. The employee names a handover owner and links the current task list. A request remains pending until its status is Approved in the portal; a calendar invitation alone is not approval."),
                ("05 / Illness and emergencies", "The separate sick leave allowance is 12 working days per calendar year. Notify the line manager before the normal start time where practical and record the absence within 2 business days of returning. People Operations may request supporting information through a private channel. Do not place medical details in a shared project workspace."),
                ("06 / Working-day convention", "A working day means Monday through Friday excluding holidays in the employee's assigned office calendar. A calendar-day deadline includes weekends. A business-day service target starts on receipt of a complete request. The distinction matters when planning a handover or checking a late submission."),
            ], table=[['Item', 'Rule', 'Record owner'], ['Annual leave', '24 working days / year', 'People Operations'], ['Carryover', 'Up to 5 days; use by 31 March', 'People Operations'], ['Sick leave', '12 working days / year', 'People Operations'], ['Planned request', 'At least 7 calendar days ahead', 'Employee']]),
            page("People policy in practice", "Apply the handbook together with the detailed hybrid work, expenses and information security standards. This page explains how those documents fit together.", [
                ("07 / Hybrid work and equipment", "Eligible employees may work remotely up to 3 days per week with manager approval under AV-HR-002. Tuesday and Thursday are the usual collaboration days in the office. The annual home-office equipment allowance is INR 5000 under AV-FIN-001; it is reimbursement against approved receipts, not an automatic salary payment. Remote work does not change the leave balance."),
                ("08 / Example: joining and taking leave", "A new employee joining on 01 July has 6 complete months remaining in the calendar year. At 24 days per year, the illustrative prorated annual leave balance is 12 days. People Operations confirms the actual balance in the portal. An employee carrying 4 unused days into 2027 must use those carried days by 31 March 2027."),
                ("09 / Questions and policy changes", "Ask People Operations through the People portal for balance corrections or contractual questions. The handbook does not define a parental leave entitlement; People Operations must provide the applicable separate policy. Do not infer an entitlement from this document's silence. Changes require a document revision, effective date and recorded approval."),
            ], table=[['Reference', 'Subject', 'Use it for'], ['AV-HR-002', 'Hybrid work', 'Attendance and exceptions'], ['AV-FIN-001', 'Travel and expenses', 'Receipts and approval limits'], ['AV-SEC-001', 'Information security', 'Access and incident reporting']]),
        ],
    },
    {
        "file": "hybrid-work-2026.pdf", "title": "Hybrid work policy", "id": "AV-HR-002",
        "owner": "People Operations", "version": "2.0", "effective": "01 January 2026",
        "pages": [
            page("Where and when we work", "A predictable hybrid schedule balances focused work with team collaboration. This policy applies to permanent employees whose roles can be performed securely away from the office.", [
                ("01 / Weekly arrangement", "Remote work is allowed up to 3 days per week with line-manager approval. Tuesday and Thursday are the default office collaboration days. Each team publishes its next week's schedule by Friday at 16:00 IST. Client visits and agreed field work count as work duties, not annual leave. This arrangement does not create an entitlement to work from any country."),
                ("02 / Eligibility and core hours", "The manager checks role suitability, service coverage and security training before approving a hybrid arrangement. During working days, employees should be reachable from 11:00 to 16:00 IST, excluding lunch and approved absences. Teams agree their remaining hours. Core availability is not a requirement to work during recorded leave."),
                ("03 / Attendance exceptions", "An exception to a Tuesday or Thursday office day requires manager approval before the day concerned. A recurring exception lasting more than 4 weeks also requires People Operations review. The exception record must state the reason, review date and service-coverage plan. A temporary exception does not change the general policy."),
            ], note="Approved by the People Director on 15 December 2025. Read alongside AV-HR-001 and AV-SEC-001."),
            page("Workspace and reimbursement", "Home-working costs must follow the same approval and receipt controls as other business expenses. An equipment allowance is a cap, not permission to purchase any item.", [
                ("04 / Equipment allowance", "The annual home-office equipment allowance is INR 5000 per employee per calendar year, including tax. Eligible items include an ergonomic keyboard, mouse, headset or monitor accessory. Obtain manager approval before buying and submit the itemized receipt within 15 calendar days of purchase under AV-FIN-001. Unused allowance does not carry into the next year."),
                ("05 / Purchase example", "A headset costing INR 3500 plus INR 630 tax totals INR 4130. If no other equipment reimbursement has been claimed that year, INR 870 of the allowance remains. A personal mobile subscription is not automatically eligible. Finance decides ambiguous categories before purchase; the employee should not assume reimbursement."),
                ("06 / Safe access", "Use a company-managed device, multifactor authentication and the approved VPN when accessing internal systems remotely. Do not use shared family accounts or public computers. Restricted information must not be saved to a personal drive. AV-SEC-001 defines classification and the security incident procedure."),
            ], table=[['Control', 'Requirement', 'Approver'], ['Equipment', 'INR 5000 / calendar year, tax included', 'Line manager'], ['Receipt', 'Submit within 15 calendar days', 'Finance'], ['Restricted data', 'Managed device and approved systems', 'Security team']]),
            page("Continuity and review", "Hybrid arrangements are reviewed against delivery and access needs. Reviews should rely on agreed outcomes and service coverage rather than assumptions about location.", [
                ("07 / Connectivity interruption", "If an outage prevents work, notify the line manager within 30 minutes where communication is available. Agree a safe alternative, such as moving to the office or rescheduling tasks. An outage does not automatically become annual leave. If the outage may involve a compromised device or account, use the security incident procedure instead."),
                ("08 / Temporary location changes", "Working outside the employee's assigned country requires written People Operations and Security review before travel. The review considers contractual, access and client restrictions. This policy does not grant international remote-work approval or specify tax treatment. Employees must wait for the written outcome."),
                ("09 / Review and records", "Managers review a hybrid arrangement every quarter and record any change in the People portal. A temporary withdrawal should include a reason and a review date. People Operations handles disagreements. The approved arrangement remains subject to customer commitments, information security controls and documented role requirements."),
            ], note="For annual leave, see AV-HR-001. For receipts and payment targets, see AV-FIN-001. For suspected compromise, see AV-SEC-001."),
        ],
    },
    {
        "file": "travel-expenses-2026.pdf", "title": "Travel and expenses", "id": "AV-FIN-001",
        "owner": "Finance Operations", "version": "2.0", "effective": "01 January 2026",
        "pages": [
            page("Claim submission and approval", "This standard covers approved business expenses paid personally by employees. It does not authorize travel or spending that has not received the required advance approval.", [
                ("01 / Submission deadline", "Submit expense claims within 15 calendar days of purchase. Count the day after purchase as day 1. Upload an itemized receipt, payment evidence, business purpose, project code and manager's advance approval. For example, a purchase on 10 October must be submitted by 25 October. A card statement alone does not replace an itemized receipt."),
                ("02 / Approval and payment", "The line manager checks the business purpose within 2 business days of a complete submission. Finance aims to pay an approved, complete claim within 5 business days after receiving manager approval. Missing receipts pause that target until the employee supplies the information. The target is not a guaranteed bank settlement time."),
                ("03 / Late claims", "A late claim needs a written explanation and Finance Operations approval before reimbursement. The employee must not alter a purchase date to make a claim appear timely. Claims with missing receipts or disputed categories remain open for review; late submission does not automatically authorize payment."),
            ], note="Approved by the Finance Director on 15 December 2025. Monetary limits below are fictional company controls, not tax guidance."),
            page("Spending limits and evidence", "All limits are in INR and include tax unless an approved trip budget states otherwise. Split receipts from the same purchase must be considered together.", [
                ("04 / Travel authorization", "Obtain manager approval for the trip and its budget before booking. Domestic hotels are capped at INR 4500 per night and meals at INR 900 per travel day. Alcohol, personal entertainment and companion costs are not reimbursable. Any over-limit booking requires written Finance approval before payment; a client meeting alone does not waive the cap."),
                ("05 / Equipment and local transport", "The annual equipment allowance is INR 5000 per employee, including tax, as described in AV-HR-002. Local taxi claims require a receipt and the origin, destination and business purpose. This policy does not set a universal taxi-price cap; the manager checks reasonableness against the approved trip budget."),
                ("06 / Duplicates and refunds", "Do not claim an expense already paid by a company card or reimbursed by a client. Notify Finance within 2 business days of receiving a refund for a reimbursed item. Finance records the adjustment against the original claim reference so the audit trail remains intact."),
            ], table=[['Category', 'Limit', 'Required evidence'], ['Domestic hotel', 'INR 4500 per night', 'Itemized hotel invoice'], ['Travel meals', 'INR 900 per day', 'Itemized receipt'], ['Home-office equipment', 'INR 5000 per year', 'Approval and receipt'], ['Local taxi', 'Approved trip budget', 'Receipt and journey purpose']]),
            page("Worked example and controls", "Use this example to check the difference between a spending allowance, a claim deadline and a payment service target.", [
                ("07 / Example: equipment receipt", "An approved headset costs INR 3500 before tax. Tax is INR 630, giving a total claim of INR 4130. The annual equipment allowance is INR 5000, so the remaining balance is INR 870 if there were no earlier equipment claims. Submit the claim within 15 calendar days; the unused balance is not payable in cash."),
                ("08 / Resolving a returned claim", "Finance returns an incomplete claim with the missing items listed in the expense portal. The employee should reply against the same claim reference rather than submit a duplicate. The 5-business-day processing target begins after the complete claim and manager approval are received. Escalate an unresolved claim to Finance Operations with its reference and submission date."),
                ("09 / Handling sensitive receipts", "Mask unrelated personal payment details before adding a receipt to a project workspace. Preserve the merchant, date, items, tax and total needed for review. Financial records belong in the approved expense system; the information security classification controls in AV-SEC-001 still apply."),
            ], note="Useful cross-check: the fictional demo receipt DEMO-1042 shows the same INR 4130 equipment example. It is not a real transaction."),
        ],
    },
    {
        "file": "information-security-2026.pdf", "title": "Information security standard", "id": "AV-SEC-001",
        "owner": "Security Operations", "version": "1.3", "effective": "01 January 2026",
        "pages": [
            page("Identity and secure access", "This standard applies to employees, approved contractors and service accounts accessing Aster Vale systems. Customer-specific security commitments may impose additional controls.", [
                ("01 / Authentication and accounts", "Multifactor authentication is required for all workforce accounts. Use individual accounts and the approved password manager; never share passwords, recovery codes or API keys in documents or team chat. Service credentials must have an owner, a documented purpose and the minimum permissions needed. A project deadline is not approval to bypass authentication."),
                ("02 / Devices and remote connections", "Access internal systems from managed, encrypted devices. Use the approved VPN for remote access, lock the screen when stepping away and apply managed updates. Do not copy restricted information to personal cloud storage. Report a lost device even if it is encrypted; Security decides the response."),
                ("03 / Access lifecycle", "Managers approve access according to job responsibilities. System owners review access quarterly. People Operations notifies IT of a departure; IT revokes workforce access by the confirmed end of the employee's last working day, or immediately for a security-directed suspension. Return equipment through the recorded offboarding process."),
            ], note="Approved by the Security Lead on 12 December 2025. Related documents: AV-HR-002 and AV-OPS-001."),
            page("Classification and retention", "Classify information before deciding where to store it or who may see it. Classification is about sensitivity; retention is a separate decision about how long a record is needed.", [
                ("04 / Restricted information", "Customer production exports, identity documents and account credentials are Restricted. Store them only in approved systems with named access. Aster Vale's public demo must contain fictional data only. Never upload customer records, real API keys or personal identity information to an unrestricted demonstration workspace."),
                ("05 / Retention scope", "Security audit logs are retained for 180 days unless an approved preservation hold applies. This is a security-log rule; it is not the retention period for every customer project or financial record. The Atlas project requirements define their own operational data retention. Ask the record owner when a category is not covered."),
                ("06 / Deletion requests", "Send a deletion request to the record owner for identity and scope verification. Security supports the review of restricted information. The internal review target is 10 business days after verification; it does not override contractual or mandatory preservation duties. Record the decision and affected systems."),
            ], table=[['Class', 'Example', 'Handling'], ['Public', 'Approved product brochure', 'Approved public channels'], ['Internal', 'Fictional operating guide', 'Workforce access'], ['Restricted', 'Customer export or credential', 'Named access; approved storage']]),
            page("Incident reporting and response", "Early reporting helps contain harm. Report suspected incidents even when you are unsure whether they are confirmed.", [
                ("07 / One-hour reporting rule", "Report suspected security incidents to Security Operations within 1 hour of discovery using the incident portal. Examples include a lost device, phishing interaction, exposed credential or unexpected access. Record when it was noticed, affected systems and observed symptoms. Do not include an exposed password or secret value in the report."),
                ("08 / Immediate actions", "For suspicious email, stop interacting with the message and use the report-phishing control. For a potentially compromised device, follow the incident portal instructions and contact Security before deleting files or wiping it. Preserve relevant evidence. The team, not the reporter, determines severity and customer communication."),
                ("09 / Follow-through", "Security acknowledges the incident, assigns an owner and records containment actions. Recovery requires confirmation that access and affected systems are safe. The owner records a follow-up review with causes, corrective work and due dates. This standard specifies the employee reporting deadline; it does not promise a fixed recovery time for every incident."),
            ], note="If the normal portal is unavailable, use the approved emergency security contact in the internal directory. No real contact details are embedded in this fictional document."),
        ],
    },
    {
        "file": "employee-onboarding-2026.pdf", "title": "Employee onboarding playbook", "id": "AV-OPS-001",
        "owner": "People Operations", "version": "1.2", "effective": "01 January 2026",
        "pages": [
            page("Before the first day", "A named manager and onboarding buddy coordinate each new starter. The checklist records completion evidence; sending a welcome email is not the same as provisioning access.", [
                ("01 / Five business days before start", "People Operations confirms the start date, manager and assigned office calendar. IT prepares a managed laptop and the standard access request. The line manager names a buddy, prepares a first-week plan and identifies any customer-system access that needs separate approval. Do not place personal identity documents in the project knowledge library."),
                ("02 / Access requests", "The manager approves role-based access and the system owner verifies permissions. IT provides account activation through the approved private process. The new starter sets up multifactor authentication before accessing internal systems. Shared starter passwords must not be included in an onboarding document."),
                ("03 / First-day readiness check", "Before the employee starts, People Operations checks that the laptop, activation instructions, buddy and welcome schedule are ready. Missing items are assigned an owner and due date. Access to customer production systems is not part of the default starter package and must wait for explicit authorization."),
            ], note="Approved by the People Operations Manager on 10 December 2025. Security requirements come from AV-SEC-001."),
            page("First-week completion", "The employee and buddy use the checklist together. The manager remains responsible for role clarity and access approval.", [
                ("04 / Day-one orientation", "The buddy introduces the team and explains the support channels. The manager reviews the role objectives and first-month work. The employee confirms device encryption, multifactor authentication and access to the People portal. Read AV-HR-001, AV-HR-002, AV-FIN-001 and AV-SEC-001 before submitting the policy acknowledgement."),
                ("05 / Training and first task", "Complete information security training by the end of working day 5. The manager chooses a small, non-production first task with an acceptance criterion and a reviewer. A task involving restricted customer data requires the relevant access approval first. Record completion and any blocked prerequisites in the onboarding tracker."),
                ("06 / Week-one review", "The manager meets the employee by the end of the first week to check access, workload and support needs. People Operations resolves missing policy acknowledgements. The buddy supports navigation but does not approve financial claims or additional system privileges."),
            ], table=[['When', 'Outcome', 'Accountable role'], ['Day 1', 'MFA, device and role orientation', 'Manager and IT'], ['By working day 5', 'Security training completed', 'New employee'], ['End of week 1', 'Access and support review', 'Line manager']]),
            page("Thirty, sixty and ninety days", "Onboarding continues after the welcome week. Reviews should identify missing support early and give the employee a clear record of agreed expectations.", [
                ("07 / Day-30 checkpoint", "At day 30, the manager reviews the first delivery, role objectives and access suitability. The employee records questions and training needs. Changes to system access follow the normal approval process. Any hybrid schedule is recorded under AV-HR-002 rather than assumed from a team calendar."),
                ("08 / Day-60 checkpoint", "At day 60, review progress against the agreed objectives and update the development plan. The buddy can provide practical feedback but the line manager owns the assessment. People Operations checks that outstanding onboarding tasks have an owner. Do not store sensitive performance notes in a shared customer project space."),
                ("09 / Probation review", "The probation period is 90 days under AV-HR-001. The manager holds the formal review on day 75 and sends the recommendation to People Operations so the outcome can be confirmed before day 90. Completing the onboarding checklist alone does not automatically confirm probation. The signed employment terms remain applicable."),
            ], note="Example distinction: security training is due by working day 5; the formal probation review is on day 75. These are separate milestones."),
        ],
    },
    {
        "file": "customer-onboarding-2026.pdf", "title": "Customer onboarding playbook", "id": "AV-CS-001",
        "owner": "Customer Success", "version": "1.4", "effective": "01 June 2026",
        "pages": [
            page("Discovery to implementation", "This playbook covers a standard customer implementation after a signed order. Project-specific commitments must be recorded in the approved project plan.", [
                ("01 / Discovery and ownership", "Customer onboarding starts with a discovery meeting led by the account manager. Identify the customer sponsor, implementation lead, authorized approver and success measures. The account manager collects requirements within 2 business days after discovery and records assumptions and missing inputs. Sales promises that are absent from the signed scope require clarification before delivery work begins."),
                ("02 / Readiness gate", "The implementation lead checks the requirements baseline, named customer approver, approved access and sample data. Use fictional or anonymized sample data until production access is approved. Aster Vale and the customer must agree acceptance criteria and responsibilities. The implementation clock starts only when the readiness gate is complete."),
                ("03 / Standard implementation target", "The standard implementation target is 10 business days after the readiness gate is complete. Delays caused by missing customer inputs are recorded with an owner and a revised plan. This target is not a promise that every custom project takes 10 days. Approved scope changes may alter the schedule through the change process."),
            ], note="Approved by the Customer Success Director on 20 May 2026. Atlas-specific requirements are controlled by AV-PRD-001."),
            page("Acceptance and launch", "A launch decision needs evidence, a responsible approver and a clear rollback route. A demonstration is not a substitute for customer acceptance.", [
                ("04 / Acceptance evidence", "The implementation lead links each agreed requirement to a test result and records unresolved defects. The customer approver signs acceptance or states the blocking criteria. Restricted exports and account credentials must remain in approved systems rather than the shared launch checklist. Security review is required before production access."),
                ("05 / Training before go-live", "Schedule customer administrator training before launch. Cover account roles, ordinary workflows, support intake and the agreed limitations. Record attendance and provide the approved user guide. Training can be rescheduled, but the launch approver must explicitly accept any remaining training risk before proceeding."),
                ("06 / Launch authorization", "The customer approver, implementation lead and service owner confirm readiness. The launch record lists the release version, configuration owner, open limitations and rollback decision maker. If a blocking acceptance criterion fails, postpone launch or obtain a documented scope decision; do not silently mark the test passed."),
            ], table=[['Gate', 'Evidence', 'Owner'], ['Ready to implement', 'Baseline, access, sample data', 'Implementation lead'], ['Ready to accept', 'Test results and defect list', 'Customer approver'], ['Ready to launch', 'Training and rollback record', 'Service owner']]),
            page("Handover and change control", "Customer success continues after the first launch. Support responsibilities and new requests must be visible to both the service team and the customer.", [
                ("07 / Service handover", "The service owner accepts the operating guide, escalation route and known limitations. The account manager schedules a success review 30 calendar days after launch. Review the agreed success measures and open actions rather than assuming that a successful technical release means the business goal has been met."),
                ("08 / Requirement changes", "A requirement change records the requested behavior, reason, affected requirement IDs, security impact, test changes and schedule impact. The product owner and customer approver must approve a scope change before it enters the committed baseline. An email request is an input to review, not automatic approval. For Atlas, CR-014 demonstrates an approved change in AV-PRD-001 version 2.0."),
                ("09 / Missing commitments", "This playbook does not define subscription pricing, a universal uptime SLA or a guaranteed recovery time. Use the customer's signed agreement for those commitments. If a question cannot be answered from the approved project documents, record the missing information and ask the accountable owner rather than invent a number."),
            ], note="Customer data must follow AV-SEC-001. Standard deadlines are measured from complete inputs, not from an incomplete request."),
        ],
    },
]


def requirements(version):
    updated = version == 2
    return {
        "file": f"atlas-requirements-v{version}.pdf", "title": "Atlas portal requirements",
        "id": "AV-PRD-001", "owner": "Product and Engineering", "version": f"{version}.0",
        "effective": "15 June 2026" if updated else "01 May 2026",
        "pages": [
            page("Baseline and delivery scope", "Atlas is a fictional customer portal for submitting service requests, reviewing status and exporting authorized operational records.", [
                ("01 / Baseline status", ("Version 2.0 is the current approved baseline. It supersedes version 1.0 from 15 June 2026 following change request CR-014, approved on 12 June 2026. The product owner and customer approver accepted the scope and schedule impact. Version 1.0 remains an audit reference and must not be used as the current implementation instruction." if updated else "Version 1.0 is the initial baseline approved on 25 April 2026, effective 01 May 2026. It records the original committed scope. Proposed changes outside this baseline require an impact review and a recorded approval before implementation. Preserve each approved baseline so future decisions can be compared with the original requirements.")),
                ("02 / Users and boundaries", "Requesters submit service requests and see their own records. Customer administrators manage users within their customer organization. Service agents update assigned requests. No user may access another customer's records by changing a URL, export filter or request identifier. Payroll, public signup and payment processing are outside this project scope."),
                ("03 / Delivery responsibilities", "The product owner maintains requirement IDs and acceptance criteria. Engineering implements the approved baseline. Quality Assurance records evidence against each requirement. The customer approver signs acceptance. Customer onboarding follows AV-CS-001; workforce and security controls remain defined by their separate standards."),
            ], table=[['Control', 'Value', 'Decision owner'], ['Document version', f'{version}.0', 'Product owner'], ['Effective date', '15 June 2026' if updated else '01 May 2026', 'Customer approver'], ['Status', 'Current approved baseline' if updated else 'Initial approved baseline', 'Product owner']]),
            page("Requirements and acceptance", "Each numbered requirement has an observable acceptance criterion. Security checks must cover negative cases as well as the intended user journey.", [
                ("REQ-101 / Customer isolation", "All list, detail, export and search routes enforce customer-organization permissions on the server. Acceptance: an authorized user from customer A cannot read or export customer B's records, including by using a valid record ID from B. The test checks both the response and the absence of leaked record content."),
                ("REQ-102 / Export format", ("Customer administrators can export authorized records as CSV and XLSX. Requesters cannot export an organization-wide dataset. Acceptance: both formats contain only the selected customer's permitted records, with a header row and the same documented field names. Formula-like user input is escaped for spreadsheet safety." if updated else "Customer administrators can export authorized records as CSV only. XLSX export is outside this baseline. Acceptance: the CSV includes a header row and only the selected customer's permitted records. Formula-like user input is escaped for spreadsheet safety.")),
                ("REQ-103 / Operational retention", f"Operational request data retention is {180 if updated else 90} days after a request is closed, unless an approved preservation hold applies. Acceptance: the retention job marks eligible closed records and records its decision. Open requests are excluded. This requirement concerns Atlas operational requests, not workforce records or security audit logs."),
                ("REQ-104 / Priority-one support", f"The priority-one support response time is {1 if updated else 4} {'hour' if updated else 'hours'} after a verified priority-one ticket is accepted. This means acknowledgement and ownership, not complete recovery. Acceptance: the service desk records the accepted time and first response time, and flags a breach of the applicable target."),
            ], note="Scope and retention are approved fictional project requirements, not claims about a real deployed service."),
            page("Change record and release gate", "A scope change is complete only when the baseline, implementation plan and acceptance evidence all reflect the same approved decision.", [
                ("04 / CR-014 decision" if updated else "04 / Change approval rule", ("CR-014 adds XLSX export alongside CSV, extends closed-request retention from 90 days to 180 days, and tightens the priority-one response target from 4 hours to 1 hour. Approval was recorded on 12 June 2026; the effective date is 15 June 2026. Customer isolation REQ-101 is unchanged. Security reviewed the longer retention and export controls before approval." if updated else "Requests for additional export formats, longer retention or a tighter support response target require a written impact assessment. The product owner and customer approver must record their decision, affected requirement IDs and effective date. Until an updated baseline is approved, the committed requirements on page 2 remain applicable.")),
                ("05 / Schedule and test impact", ("The planned go-live changes from 30 June 2026 to 07 July 2026 to cover spreadsheet export testing and retention-job verification. Quality Assurance must repeat customer-isolation tests for both export formats. The service owner must confirm priority-one coverage before accepting the new response target. No pricing or uptime commitment is added by this change." if updated else "The planned go-live date in this baseline is 30 June 2026. Test the CSV export, 90-day closed-request retention and 4-hour priority-one response target, alongside customer isolation. If a later approved change affects these criteria, revise the test plan rather than reusing obsolete expected results.")),
                ("06 / Release evidence", "Before launch, link each requirement ID to its latest test result, list unresolved defects and obtain customer acceptance. Record the approved version and effective date in the handover. A passed demonstration with fictional records is useful evidence of a workflow, but does not establish production capacity, uptime or general data-security guarantees."),
            ], table=([['Requirement', 'Version 1.0', 'Version 2.0'], ['REQ-102 export', 'CSV only', 'CSV and XLSX'], ['REQ-103 retention', '90 days after closure', '180 days after closure'], ['REQ-104 response', '4 hours', '1 hour'], ['Planned go-live', '30 June 2026', '07 July 2026']] if updated else [['Requirement', 'Approved baseline', 'Verification owner'], ['REQ-102 export', 'CSV only', 'Quality Assurance'], ['REQ-103 retention', '90 days after closure', 'Engineering'], ['REQ-104 response', '4 hours', 'Service owner'], ['Planned go-live', '30 June 2026', 'Product owner']])),
        ],
    }


DOCS += [requirements(1), requirements(2)]
INK = colors.HexColor("#172C3B")
TEAL = colors.HexColor("#176D70")
PALE = colors.HexColor("#EDF5F4")
MUTED = colors.HexColor("#52616A")
STYLES = {
    "kicker": ParagraphStyle("kicker", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=TEAL, spaceAfter=9),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=INK, spaceAfter=12),
    "summary": ParagraphStyle("summary", fontName="Helvetica", fontSize=10.5, leading=15, textColor=MUTED, spaceAfter=15),
    "heading": ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=11, leading=15, textColor=TEAL, spaceAfter=5),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14.5, textColor=INK, spaceAfter=12),
    "note": ParagraphStyle("note", fontName="Helvetica", fontSize=8.5, leading=12, textColor=MUTED, spaceAfter=8),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=INK, alignment=TA_LEFT),
}


def render(spec, path):
    width, height = 210 * mm, 297 * mm

    def furniture(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(20 * mm, height - 20 * mm, "ASTER VALE")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(width - 20 * mm, height - 20 * mm, f"{spec['id']}  |  v{spec['version']}")
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(1)
        canvas.line(20 * mm, height - 25 * mm, width - 20 * mm, height - 25 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 17 * mm, "FICTIONAL DEMO COMPANY AND CONTENT | No real employee or customer data")
        canvas.drawRightString(width - 20 * mm, 12 * mm, f"Page {doc.page} of 3")
        canvas.drawString(20 * mm, 12 * mm, f"Owner: {spec['owner']} | Effective: {spec['effective']}")
        canvas.restoreState()

    doc = BaseDocTemplate(str(path), pagesize=(width, height), title=f"Aster Vale - {spec['title']} v{spec['version']}", author="Aster Vale Technologies (fictional demo company)", subject="Repository-owned fictional demo content", invariant=1)
    doc.addPageTemplates(PageTemplate(id="business", frames=[Frame(20 * mm, 27 * mm, width - 40 * mm, height - 61 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=furniture))
    story = []
    for number, content in enumerate(spec["pages"], 1):
        if number > 1:
            story.append(PageBreak())
        story.extend([Paragraph(escape(spec["title"].upper()), STYLES["kicker"]), Paragraph(escape(content["title"]), STYLES["title"]), Paragraph(escape(content["summary"]), STYLES["summary"])])
        for title, text in content["sections"]:
            story.append(KeepTogether([Paragraph(escape(title), STYLES["heading"]), Paragraph(escape(text), STYLES["body"])]))
        if content["table"]:
            cells = [[Paragraph(escape(cell), STYLES["cell"]) for cell in row] for row in content["table"]]
            table = Table(cells, colWidths=[46 * mm, 63 * mm, 61 * mm], repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PALE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#D5E2E0"))]))
            story.extend([Spacer(1, 3 * mm), table])
        if content["note"]:
            story.extend([Spacer(1, 3 * mm), Paragraph(escape(content["note"]), STYLES["note"])])
    doc.build(story)


def main():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    for spec in DOCS:
        path = DIRECTORY / spec["file"]
        render(spec, path)
        print(f"Created {path.relative_to(ROOT)}")
    print(json.dumps({"documents": len(DOCS), "company": "Aster Vale Technologies (fictional)", "scope": "Native selectable text; no accuracy guarantee"}))


if __name__ == "__main__":
    main()
