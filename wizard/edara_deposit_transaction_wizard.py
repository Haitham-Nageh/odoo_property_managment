from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EdaraDepositTransactionWizard(models.TransientModel):
    _name = 'edara.deposit.transaction.wizard'
    _description = 'Record Deposit Transaction'

    deposit_id = fields.Many2one('edara.deposit', required=True,
                                  default=lambda self: self.env.context.get('active_id'))
    company_id = fields.Many2one(related='deposit_id.company_id')
    currency_id = fields.Many2one(related='deposit_id.currency_id')
    transaction_type = fields.Selection([
        ('held', 'Collect Deposit'),
        ('refund', 'Refund Deposit'),
        ('deduction', 'Deduct from Deposit'),
    ], required=True, default=lambda self: self.env.context.get('default_transaction_type', 'held'))
    amount = fields.Monetary(required=True, currency_field='currency_id')
    journal_id = fields.Many2one('account.journal', string='Payment Journal',
                                  domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]")
    has_journal_browse_access = fields.Boolean(compute='_compute_has_journal_browse_access', help=(
        "Whether the current user has native Odoo read access to account.journal. "
        "MAT-FIND-015: no EDARA role implies a native Accounting group by design, "
        "so this is normally False for an EDARA-only user - the Payment Journal "
        "field is then locked to the single scoped-resolved journal (see "
        "_resolve_deposit_journal()) instead of being freely browsable, so the "
        "user is never handed a dropdown whose search would fail with an "
        "AccessError."))
    description = fields.Char(string='Reason')

    @api.depends('company_id')
    def _compute_has_journal_browse_access(self):
        has_access = self.env['account.journal'].has_access('read')
        for wizard in self:
            wizard.has_journal_browse_access = has_access

    @api.onchange('deposit_id', 'transaction_type')
    def _onchange_deposit_transaction_type(self):
        """Default Amount to the available amount for the chosen transaction
        type (Collect -> remaining uncollected, Refund/Deduct -> balance), and
        Payment Journal to the company's single matching journal when the
        choice is unambiguous. Both stay freely editable for a user with
        native journal access - this only sets the initial value, it never
        blocks a partial amount or a different journal (see
        EDARA_PROJECT_STATE.md MAT-FIND-001/MAT-FIND-002)."""
        for wizard in self:
            if not wizard.deposit_id:
                continue
            wizard.amount = wizard.deposit_id._default_transaction_amount(wizard.transaction_type)
            if not wizard.journal_id and wizard.transaction_type != 'deduction':
                wizard.journal_id = wizard._resolve_deposit_journal()

    def _resolve_deposit_journal(self):
        """MAT-FIND-015: no EDARA role implies native account.journal read
        access (by design - see EDARA_PROJECT_STATE.md). This lookup is a
        narrow, scoped elevation restricted to exactly the same safe domain
        the field's own widget domain already advertises (Cash/Bank journals
        of this wizard's own company, already resolved server-side from
        deposit_id - never client input) - it is used only to auto-resolve
        this one field, never to hand the calling user a general journal
        search/browse capability. Returns the single matching journal, or an
        empty recordset if the choice is ambiguous (zero or more than one) -
        deliberately never guessed."""
        self.ensure_one()
        journals = self.env['account.journal'].sudo().search([
            ('type', 'in', ('cash', 'bank')),
            ('company_id', '=', self.company_id.id),
        ])
        return journals if len(journals) == 1 else self.env['account.journal']

    def action_confirm(self):
        self.ensure_one()
        if self.transaction_type in ('held', 'refund'):
            if not self.journal_id:
                if not self.has_journal_browse_access:
                    raise UserError(_(
                        "No single Cash/Bank journal could be automatically determined "
                        "for %(company)s, and this user does not have native Odoo "
                        "Accounting access to browse and choose one manually. Please "
                        "ask an administrator to configure exactly one default "
                        "Cash/Bank journal for this company.",
                        company=self.company_id.display_name,
                    ))
                raise UserError(
                    _("Please select the journal receiving this deposit.")
                    if self.transaction_type == 'held' else
                    _("Please select the journal paying out this refund.")
                )
            if self.transaction_type == 'held':
                self.deposit_id.action_collect(self.journal_id.id, self.amount)
            else:
                self.deposit_id.action_refund(self.journal_id.id, self.amount)
        else:
            if not self.description:
                raise UserError(_("Please describe the reason for this deduction."))
            self.deposit_id.action_deduct(self.amount, self.description)
        return {'type': 'ir.actions.act_window_close'}
