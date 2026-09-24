import logging

from odoo import _, api, fields, models, modules
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

STATES = [
    ('draft', 'Draft'),
    ('invoiced', 'Invoiced'),
    ('partial', 'Partially Paid'),
    ('paid', 'Paid'),
    ('overdue', 'Overdue'),
    ('cancelled', 'Cancelled'),
]

INVOICE_PAYMENT_STATE_TO_LINE_STATE = {
    'not_paid': 'invoiced',
    'in_payment': 'paid',
    'paid': 'paid',
    'partial': 'partial',
    'reversed': 'cancelled',
    'blocked': 'invoiced',
    'invoicing_legacy': 'invoiced',
}


class EdaraPaymentScheduleLine(models.Model):
    _name = 'edara.payment.schedule.line'
    _description = 'EDARA Payment Schedule Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'due_date, id'

    contract_id = fields.Many2one('edara.lease.contract', string='Contract', required=True,
                                   index=True, ondelete='cascade')
    tenant_id = fields.Many2one(related='contract_id.tenant_id', string='Tenant', store=True, index=True)
    unit_id = fields.Many2one(related='contract_id.unit_id', string='Unit', store=True, index=True)
    property_id = fields.Many2one(related='contract_id.property_id', string='Property', store=True, index=True)
    building_id = fields.Many2one(related='contract_id.building_id', string='Building', store=True, index=True)
    branch_id = fields.Many2one(related='contract_id.branch_id', string='Branch', store=True, index=True)
    company_id = fields.Many2one(related='contract_id.company_id', string='Company', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', string='Currency', store=True)

    sequence = fields.Integer(default=10)
    # due_date == period_start: the date the period's rent becomes due and
    # (via _cron_generate_due_invoices()) the date used as the invoice's
    # invoice_date. period_end is the exclusive end of the billing period
    # this line covers (never itself billed - see MAT-FIND-005). Both are
    # set once at generation time in edara.lease.contract._generate_schedule_lines()
    # and are never recomputed afterwards, so an already-invoiced line's
    # period/amount remain the frozen, auditable basis for that invoice
    # even if the contract's rent_amount changes later.
    due_date = fields.Date(required=True, index=True)
    period_start = fields.Date(string='Period Start')
    period_end = fields.Date(string='Period End')
    occupied_days = fields.Integer(string='Occupied Days')
    is_prorated = fields.Boolean(string='Prorated')
    amount = fields.Monetary(required=True, currency_field='currency_id')
    description = fields.Char()

    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False, index=True)
    state = fields.Selection(STATES, compute='_compute_state', store=True)

    _invoice_id_uniq = models.Constraint(
        'unique(invoice_id)',
        'An invoice cannot be linked to more than one payment schedule line.',
    )

    def write(self, vals):
        # Phase 7: once invoiced, the line's amount is the frozen basis of that invoice.
        # (Uninvoiced lines stay editable - the list/form views intentionally allow it.)
        if 'amount' in vals and not self.env.su and any(line.invoice_id for line in self):
            raise AccessError(_("The amount of an invoiced payment schedule line cannot be modified."))
        return super().write(vals)

    def unlink(self):
        """The invoice itself is already protected by native Odoo (a posted
        account.move cannot be unlinked without first resetting to draft, a
        separate accounting permission) - this only stops deleting OUR OWN
        record of which schedule slot produced it, which would silently break
        the audit trail linking a contract's rent periods to their invoices
        even though the invoice/payment history remains untouched. Uninvoiced
        (draft) lines are unaffected - action_terminate() still unlinks them."""
        if any(line.invoice_id for line in self):
            raise UserError(_(
                "An invoiced payment schedule line cannot be deleted, to preserve the "
                "link between the lease contract and its invoice history."))
        return super().unlink()

    @api.depends('invoice_id.payment_state', 'invoice_id.state', 'due_date')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for line in self:
            if not line.invoice_id:
                line.state = 'overdue' if line.due_date < today else 'draft'
            elif line.invoice_id.state == 'cancel':
                line.state = 'cancelled'
            else:
                mapped = INVOICE_PAYMENT_STATE_TO_LINE_STATE.get(line.invoice_id.payment_state, 'invoiced')
                if mapped == 'invoiced' and line.due_date < today:
                    mapped = 'overdue'
                line.state = mapped

    def _create_invoice(self):
        """MAT-FIND-007 (2026-09-22): now reachable from a manual, non-cron
        trigger (action_generate_due_invoices_now()), not just the
        superuser-run daily cron - so, like every other native-accounting-
        creating action in this module (MAT-FIND-015), it needs its own
        explicit authorization check and scoped elevation. Previously relied
        entirely on the cron's own superuser context, which no longer holds
        once a regular EDARA user can reach this path directly."""
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
        self.check_access('write')
        company = self.company_id
        income_account = company.edara_rental_income_account_id
        if not income_account:
            raise UserError(_(
                "Please configure the Rental Income Account for %(company)s "
                "(Settings > EDARA Property Management) before generating invoices.",
                company=company.display_name,
            ))
        analytic_account = self.property_id.get_analytic_account()
        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': self.tenant_id.id,
            'invoice_date': self.due_date,
            'currency_id': self.currency_id.id,
            'company_id': company.id,
            'edara_invoice_type': 'rent',
            'edara_contract_id': self.contract_id.id,
            'edara_unit_id': self.unit_id.id,
            'edara_building_id': self.building_id.id,
            'edara_property_id': self.property_id.id,
            'edara_branch_id': self.branch_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': self.description or self.contract_id.display_name,
                'quantity': 1,
                'price_unit': self.amount,
                'account_id': income_account.id,
                'analytic_distribution': {str(analytic_account.id): 100.0},
            })],
        })
        invoice.action_post()
        # Phase 7: invoice_id is system-managed (edara.system.field.guard); check_access('write') above.
        self.sudo().invoice_id = invoice.id
        return invoice

    def action_charge_late_fee(self):
        """Manual only, per spec §21 "do not automatically charge arbitrary
        late fees without a business rule" - there is no cron and no
        auto-trigger anywhere for this. A Property Manager/Accountant reviews
        an overdue line and deliberately charges the company-configured flat
        amount as a separate invoice, tagged edara_invoice_type='late_fee' so
        it appears distinctly in the Reports and is netted the same way as
        any other posted revenue.

        MAT-FIND-015: no EDARA role implies a native Accounting group (by
        design), so the native invoice create+post is narrowly elevated -
        every value is already resolved server-side above/below.
        Authorization first: explicitly require normal EDARA write access to
        THIS line (ACL + record rules, e.g. branch scoping) before any
        elevation runs - unlike the rent invoice path, this method never
        writes to `self`, so without this explicit check a Viewer's mere
        read access would otherwise be enough to reach the elevated
        create()/action_post() below."""
        self.ensure_one()
        self.check_access('write')
        if self.state != 'overdue':
            raise UserError(_("A late fee can only be charged on an overdue payment schedule line."))
        company = self.company_id
        income_account = company.edara_late_fee_income_account_id
        if not income_account:
            raise UserError(_(
                "Please configure the Late Fee Income Account for %(company)s "
                "(Settings > EDARA Property Management) before charging late fees.",
                company=company.display_name,
            ))
        if not company.edara_late_fee_amount:
            raise UserError(_(
                "Please configure the Late Fee Amount for %(company)s "
                "(Settings > EDARA Property Management) before charging late fees.",
                company=company.display_name,
            ))
        analytic_account = self.property_id.get_analytic_account()
        invoice_date = fields.Date.context_today(self)
        # Phase 8: edara_late_fee_amount is a Monetary in the COMPANY currency, but the
        # invoice is in the contract's currency - convert (native rate at the invoice
        # date) instead of reusing the number as if it were already in that currency.
        late_fee = company.currency_id._convert(
            company.edara_late_fee_amount, self.currency_id, company, invoice_date)
        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': self.tenant_id.id,
            'invoice_date': invoice_date,
            'currency_id': self.currency_id.id,
            'company_id': company.id,
            'edara_invoice_type': 'late_fee',
            'edara_contract_id': self.contract_id.id,
            'edara_unit_id': self.unit_id.id,
            'edara_building_id': self.building_id.id,
            'edara_property_id': self.property_id.id,
            'edara_branch_id': self.branch_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': _("Late fee - %(contract)s due %(due_date)s",
                          contract=self.contract_id.display_name, due_date=self.due_date),
                'quantity': 1,
                'price_unit': late_fee,
                'account_id': income_account.id,
                'analytic_distribution': {str(analytic_account.id): 100.0},
            })],
        })
        invoice.action_post()
        return self.env['account.move'].browse(invoice.id)

    def _process_due_invoices(self, auto_commit=False):
        """MAT-FIND-007 (2026-09-22): the shared business logic behind BOTH
        the daily cron and the manual "Generate Due Invoices Now" trigger
        (action_generate_due_invoices_now()) - self is already the resolved
        candidate set, so the two entry points can only ever differ in HOW
        that set is resolved (see each caller), never in what happens to it.
        Re-checks contract.state == 'active' as a second defense layer against
        a contract terminated after its schedule lines were generated (the
        first layer is action_terminate() unlinking uninvoiced future lines).
        Returns (created, skipped, errors) for user-facing feedback."""
        created = skipped = errors = 0
        for line in self:
            try:
                # 'renewed' stays billable: see edara.lease.contract.action_renew().
                if line.invoice_id or line.contract_id.state not in ('active', 'renewed'):
                    skipped += 1
                    continue
                line._create_invoice()
                created += 1
                if auto_commit:
                    self.env.cr.commit()
            except AccessError:
                # Never silently downgraded to an "error count" - an
                # authorization failure must surface immediately, exactly
                # like every other action in this module (MAT-FIND-015). The
                # daily cron never hits this (it runs unrestricted), so this
                # only ever matters for the manual trigger.
                raise
            except Exception:
                errors += 1
                _logger.exception("EDARA: failed to generate invoice for payment schedule line %s", line.id)
                if auto_commit:
                    self.env.cr.rollback()
        return created, skipped, errors

    @api.model
    def _cron_generate_due_invoices(self):
        """Idempotent, batch-safe: only picks lines with no invoice yet, and
        FOR UPDATE SKIP LOCKED lets concurrent runs (or a slow prior run still
        in flight) partition the work instead of double-invoicing the same line.
        Runs unrestricted (the cron's own superuser context) - see
        action_generate_due_invoices_now() for the record-rule-scoped manual
        equivalent."""
        today = fields.Date.context_today(self)
        self.env.cr.execute("""
            SELECT id FROM edara_payment_schedule_line
            WHERE invoice_id IS NULL AND due_date <= %s
            FOR UPDATE SKIP LOCKED
        """, (today,))
        line_ids = [row[0] for row in self.env.cr.fetchall()]
        auto_commit = not modules.module.current_test
        self.browse(line_ids)._process_due_invoices(auto_commit=auto_commit)

    def action_generate_due_invoices_now(self):
        """MAT-FIND-007 manual trigger (2026-09-22): reuses
        _process_due_invoices() - the exact same business logic the cron
        uses - but resolves candidates through a normal ORM search() instead
        of the cron's unrestricted raw SQL, so record rules (branch/company
        scoping) apply to whichever EDARA user clicks the button. Called on
        an empty recordset (model-level), like _cron_generate_due_invoices()."""
        today = fields.Date.context_today(self)
        lines = self.search([('invoice_id', '=', False), ('due_date', '<=', today)])
        return lines._process_due_invoices()

    @api.model
    def _cron_send_overdue_reminders(self):
        """Notifications & Reminders Automation (2026-09-22). One internal
        reminder per overdue line, assigned to the Branch Manager, plus a
        tenant-facing chatter notification on the parent contract (no new
        payment ledger, no accounting side effect - purely observes the
        already-authoritative computed `state`). Idempotent via "does an open
        activity of this type already exist on this line" - once a Branch
        Manager marks it done, a still-overdue line will be reminded again on
        the next run, which is the correct escalation behaviour."""
        activity_type = self.env.ref('property_managment.mail_activity_type_edara_payment_overdue')
        lines = self.search([('state', '=', 'overdue')])
        sent = 0
        for line in lines:
            if line.activity_ids.filtered(lambda a: a.activity_type_id == activity_type):
                continue
            user = line.branch_id.manager_id or self.env.ref('base.user_admin')
            line.activity_schedule(
                activity_type_id=activity_type.id,
                summary=_("Overdue payment follow-up"),
                note=_(
                    "%(amount)s due on %(date)s for %(contract)s is overdue.",
                    amount=line.amount, date=line.due_date, contract=line.contract_id.name,
                ),
                user_id=user.id,
                date_deadline=fields.Date.context_today(self),
            )
            if line.tenant_id:
                line.contract_id.message_post(
                    body=_(
                        "A payment of %(amount)s due on %(date)s is overdue.",
                        amount=line.amount, date=line.due_date,
                    ),
                    partner_ids=line.tenant_id.ids,
                )
            sent += 1
        return sent
