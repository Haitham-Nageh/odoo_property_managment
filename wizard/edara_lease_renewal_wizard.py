from datetime import timedelta

from odoo import api, fields, models


class EdaraLeaseRenewalWizard(models.TransientModel):
    _name = 'edara.lease.renewal.wizard'
    _description = 'Renew Lease Contract'

    contract_id = fields.Many2one('edara.lease.contract', required=True)
    new_start_date = fields.Date(required=True)
    new_end_date = fields.Date(required=True)
    new_rent_amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='contract_id.currency_id')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        contract = self.env['edara.lease.contract'].browse(self.env.context.get('active_id'))
        if contract:
            res.update({
                'contract_id': contract.id,
                'new_start_date': contract.end_date + timedelta(days=1),
                'new_rent_amount': contract.rent_amount,
            })
        return res

    def action_confirm(self):
        self.ensure_one()
        new_contract = self.contract_id.action_renew(
            self.new_start_date, self.new_end_date, self.new_rent_amount)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'edara.lease.contract',
            'view_mode': 'form',
            'res_id': new_contract.id,
        }
