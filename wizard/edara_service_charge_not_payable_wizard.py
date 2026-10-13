from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class EdaraServiceChargeNotPayableWizard(models.TransientModel):
    _name = 'edara.service.charge.not.payable.wizard'
    _description = 'Remove Service Charge Line as Not Payable'

    line_id = fields.Many2one('edara.service.charge.line', string='Service Charge Line', required=True, readonly=True)
    tenant_id = fields.Many2one(related='line_id.tenant_id', string='Tenant', readonly=True)
    unit_id = fields.Many2one(related='line_id.unit_id', string='Unit', readonly=True)
    charge_id = fields.Many2one(related='line_id.charge_id', string='Service Charge', readonly=True)
    amount = fields.Monetary(related='line_id.amount', string='Amount', readonly=True)
    currency_id = fields.Many2one(related='line_id.currency_id')
    reason = fields.Text(string='Reason', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'edara.service.charge.line':
            res['line_id'] = active_id
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('property_managment.group_edara_branch_manager'):
            raise AccessError(_("Only branch managers and higher can remove service charge lines as not payable."))
        line = self.line_id
        if not line or not line.exists():
            raise UserError(_("The selected service charge line no longer exists."))
        if line.invoice_id:
            raise UserError(_("An invoiced service charge line cannot be removed as not payable."))
        if not self.reason or not self.reason.strip():
            raise UserError(_("A reason is required to remove this service charge line."))

        tenant = line.tenant_id
        charge_name = line.charge_id.display_name or line.charge_id.name
        unit_name = line.unit_id.display_name or line.unit_id.name
        currency_name = line.currency_id.name or ''
        if tenant:
            tenant.sudo().message_post(
                body=_(
                    "Service charge line for %(charge)s (Unit: %(unit)s, Amount: %(amount)s %(currency)s) "
                    "was removed as not payable.\nReason: %(reason)s",
                    charge=charge_name,
                    unit=unit_name,
                    amount=line.amount,
                    currency=currency_name,
                    reason=self.reason.strip(),
                ),
                author_id=self.env.user.partner_id.id,
            )

        line.with_context(edara_allow_service_charge_line_unlink=True).unlink()
        return {'type': 'ir.actions.act_window_close'}
