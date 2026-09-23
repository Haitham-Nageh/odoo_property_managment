from odoo import _, fields, models
from odoo.exceptions import UserError


class EdaraServiceChargeLine(models.Model):
    _name = 'edara.service.charge.line'
    _description = 'EDARA Service Charge Line'
    _order = 'id'

    charge_id = fields.Many2one('edara.service.charge', string='Service Charge', required=True,
                                 index=True, ondelete='cascade')
    unit_id = fields.Many2one('edara.unit', string='Unit', required=True, index=True)
    tenant_id = fields.Many2one('res.partner', string='Tenant', required=True, index=True)
    property_id = fields.Many2one(related='charge_id.property_id', store=True, index=True)
    building_id = fields.Many2one(related='charge_id.building_id', store=True, index=True)
    branch_id = fields.Many2one(related='charge_id.branch_id', store=True, index=True)
    company_id = fields.Many2one(related='charge_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='charge_id.currency_id', store=True)

    amount = fields.Monetary(required=True, currency_field='currency_id')
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False, index=True)

    _invoice_id_uniq = models.Constraint(
        'unique(invoice_id)',
        'An invoice cannot be linked to more than one service charge line.',
    )

    def unlink(self):
        """See edara.payment.schedule.line.unlink - same audit-trail rationale."""
        if any(line.invoice_id for line in self):
            raise UserError(_(
                "An invoiced service charge line cannot be deleted, to preserve the "
                "link between the allocation and its invoice history."))
        return super().unlink()

    def _create_invoice(self):
        """MAT-FIND-015: no EDARA role implies a native Accounting group (by
        design - see EDARA_PROJECT_STATE.md), so creating/posting the native
        invoice needs a narrow, scoped elevation. Every value below is
        already resolved server-side from `self` and its related records,
        never from client input. Authorization first: explicitly require
        normal EDARA write access to THIS line (ACL + record rules, e.g.
        branch scoping) before any elevation runs - read-only access (a
        Viewer has that) must never be enough to reach the elevated
        create()/action_post() below."""
        self.ensure_one()
        self.check_access('write')
        if self.invoice_id:
            return self.invoice_id
        company = self.company_id
        income_account = company.edara_service_charge_income_account_id
        if not income_account:
            raise UserError(_(
                "Please configure the Service Charge Income Account for %(company)s "
                "(Settings > EDARA Property Management) before generating invoices.",
                company=company.display_name,
            ))
        analytic_account = self.property_id.get_analytic_account()
        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': self.tenant_id.id,
            'invoice_date': fields.Date.context_today(self),
            'currency_id': self.currency_id.id,
            'company_id': company.id,
            'edara_invoice_type': 'service_charge',
            'edara_unit_id': self.unit_id.id,
            'edara_building_id': self.building_id.id,
            'edara_property_id': self.property_id.id,
            'edara_branch_id': self.branch_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': self.charge_id.display_name,
                'quantity': 1,
                'price_unit': self.amount,
                'account_id': income_account.id,
                'analytic_distribution': {str(analytic_account.id): 100.0},
            })],
        })
        invoice.action_post()
        self.invoice_id = invoice.id
        return self.invoice_id
