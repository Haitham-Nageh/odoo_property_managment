from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._sync_edara_portal_tenant_group()
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'group_ids' in vals or 'partner_id' in vals or 'active' in vals:
            self._sync_edara_portal_tenant_group()
        return res

    def _sync_edara_portal_tenant_group(self):
        """When a res.users record is created or updated with base.group_portal,
        automatically grant property_managment.group_edara_portal_tenant if the user's
        linked partner has any live EDARA lease contract (scheduled or active).
        Handles Scenario B (user created or granted portal access first).
        """
        portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
        edara_portal_group = self.env.ref('property_managment.group_edara_portal_tenant', raise_if_not_found=False)
        if not portal_group or not edara_portal_group:
            return

        for user in self.sudo():
            if portal_group in user.group_ids and edara_portal_group not in user.group_ids:
                if user.partner_id:
                    has_live_lease = self.env['edara.lease.contract'].sudo().search_count([
                        ('tenant_id', '=', user.partner_id.id),
                        ('state', 'in', ['scheduled', 'active']),
                    ]) > 0
                    if has_live_lease:
                        user.write({'group_ids': [(4, edara_portal_group.id)]})
