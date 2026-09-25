from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

STATES = [
    ('submitted', 'Submitted'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]


class EdaraRenewalRequest(models.Model):
    _name = 'edara.renewal.request'
    _description = 'EDARA Lease Renewal Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    contract_id = fields.Many2one('edara.lease.contract', string='Contract', required=True,
                                   index=True, ondelete='restrict')
    tenant_id = fields.Many2one(related='contract_id.tenant_id', store=True, index=True)
    unit_id = fields.Many2one(related='contract_id.unit_id', store=True)
    branch_id = fields.Many2one(related='contract_id.branch_id', store=True, index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)

    requested_start_date = fields.Date(required=True)
    requested_end_date = fields.Date(required=True)
    requested_rent_amount = fields.Monetary(required=True, currency_field='currency_id')
    note = fields.Text(string='Tenant Message')

    state = fields.Selection(STATES, required=True, default='submitted', tracking=True, copy=False)
    decision_note = fields.Text(string='Decision Note', copy=False)
    new_contract_id = fields.Many2one('edara.lease.contract', string='New Contract', readonly=True, copy=False)

    @api.constrains('contract_id', 'state')
    def _check_contract_active_when_submitted(self):
        for request in self:
            if request.state == 'submitted' and request.contract_id.state != 'active':
                raise ValidationError(_("A renewal can only be requested for an active contract."))

    @api.constrains('contract_id', 'state')
    def _check_single_open_request(self):
        for request in self:
            if request.state != 'submitted':
                continue
            other_open = self.search_count([
                ('id', '!=', request.id),
                ('contract_id', '=', request.contract_id.id),
                ('state', '=', 'submitted'),
            ])
            if other_open:
                raise ValidationError(_(
                    "%(contract)s already has an open renewal request.", contract=request.contract_id.display_name))

    @api.constrains('requested_start_date', 'requested_end_date')
    def _check_dates(self):
        for request in self:
            if request.requested_end_date < request.requested_start_date:
                raise ValidationError(_("The requested end date cannot be before the requested start date."))

    def action_approve(self):
        for request in self:
            if request.state != 'submitted':
                raise UserError(_("Only a submitted request can be approved."))
            new_contract = request.contract_id.action_renew(
                request.requested_start_date, request.requested_end_date, request.requested_rent_amount)
            request.write({'state': 'approved', 'new_contract_id': new_contract.id})
            if request.tenant_id:
                # Tenant Portal Expansion (2026-09-22): closes the loop for a
                # tenant-submitted renewal request - same partner_ids
                # tenant-notification pattern already used for maintenance
                # completion/overdue/expiry (Phase 1), surfaced on the
                # portal's Notifications page (spec §14/§18).
                request.message_post(
                    body=_(
                        "Your renewal request for %(contract)s has been approved.",
                        contract=request.contract_id.name,
                    ),
                    partner_ids=request.tenant_id.ids,
                )

    def action_reject(self, reason=None):
        """BD-002 (2026-09-22): a rejection reason is required (Terminate's
        reason stays optional - unchanged, see edara.lease.contract.action_terminate()).
        Reuses the existing decision_note field rather than adding a new
        one - either an explicit reason= argument (programmatic callers) or
        whatever the user has already typed into decision_note on the form
        (see renewal_request_views.xml, now editable while submitted) is
        accepted; empty/whitespace-only is rejected either way."""
        for request in self:
            if request.state != 'submitted':
                raise UserError(_("Only a submitted request can be rejected."))
            decision_note = reason if reason is not None else request.decision_note
            if not (decision_note and decision_note.strip()):
                raise UserError(_("Please provide a reason before rejecting this renewal request."))
            request.write({'state': 'rejected', 'decision_note': decision_note})
            if request.tenant_id:
                request.message_post(
                    body=_(
                        "Your renewal request for %(contract)s was not approved: %(reason)s",
                        contract=request.contract_id.name, reason=decision_note,
                    ),
                    partner_ids=request.tenant_id.ids,
                )

    @api.model
    def _cron_send_renewal_reminders(self):
        """Notifications & Reminders Automation (2026-09-22), resolves
        MAT-FIND-007's "Create Renewal Reminders" cron (spec §60). One
        internal reminder per still-open request, assigned to the Branch
        Manager - idempotent via "does an open activity of this type already
        exist" rather than a date window, since the trigger here is the
        request's own state, not a date. Never touches rent/lease terms -
        purely informational, per the ticket's own constraint."""
        activity_type = self.env.ref('property_managment.mail_activity_type_edara_renewal_pending')
        requests = self.search([('state', '=', 'submitted')])
        sent = 0
        for request in requests:
            if request.activity_ids.filtered(lambda a: a.activity_type_id == activity_type):
                continue
            user = request.branch_id.manager_id or self.env.ref('base.user_admin')
            request.activity_schedule(
                activity_type_id=activity_type.id,
                summary=_("Renewal decision pending"),
                note=_(
                    "%(tenant)s requested to renew %(contract)s. A decision is pending.",
                    tenant=request.tenant_id.display_name, contract=request.contract_id.name,
                ),
                user_id=user.id,
                date_deadline=fields.Date.context_today(self),
            )
            sent += 1
        return sent
