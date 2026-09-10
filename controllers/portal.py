from odoo import _
from odoo.exceptions import AccessError, UserError
from odoo.http import request, route

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class EdaraPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id
        if 'lease_count' in counters:
            values['lease_count'] = request.env['edara.lease.contract'].search_count(
                [('tenant_id', '=', partner.id)])
        if 'maintenance_count' in counters:
            values['maintenance_count'] = request.env['edara.maintenance.request'].search_count(
                [('tenant_id', '=', partner.id)])
        return values

    def _edara_tenant_active_units(self):
        partner = request.env.user.partner_id
        contracts = request.env['edara.lease.contract'].search([
            ('tenant_id', '=', partner.id), ('state', '=', 'active'),
        ])
        return contracts.mapped('unit_id')

    # ------------------------------------------------------------
    # My Lease
    # ------------------------------------------------------------

    @route(['/my/leases', '/my/leases/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_leases(self, page=1, **kw):
        Contract = request.env['edara.lease.contract']
        domain = [('tenant_id', '=', request.env.user.partner_id.id)]
        pager = portal_pager(
            url='/my/leases', total=Contract.search_count(domain), page=page, step=self._items_per_page)
        contracts = Contract.search(
            domain, order='start_date desc', limit=self._items_per_page, offset=pager['offset'])
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'lease', 'contracts': contracts, 'pager': pager})
        return request.render('property_managment.portal_my_leases', values)

    @route(['/my/leases/<int:contract_id>'], type='http', auth='user', website=True)
    def portal_lease_detail(self, contract_id, **kw):
        contract_sudo = self._document_check_access('edara.lease.contract', contract_id)
        open_renewal = contract_sudo.renewal_request_ids.filtered(lambda r: r.state == 'submitted')
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'lease',
            'contract': contract_sudo,
            'open_renewal': open_renewal[:1],
        })
        return request.render('property_managment.portal_lease_detail', values)

    @route(['/my/leases/<int:contract_id>/renew'], type='http', auth='user', website=True, methods=['POST'])
    def portal_lease_request_renewal(self, contract_id, **post):
        contract_sudo = self._document_check_access('edara.lease.contract', contract_id)
        if contract_sudo.tenant_id.id != request.env.user.partner_id.id:
            raise AccessError(_("You are not allowed to request a renewal for this lease."))
        try:
            rent_amount = float(post.get('requested_rent_amount') or contract_sudo.rent_amount)
        except ValueError:
            rent_amount = contract_sudo.rent_amount
        request.env['edara.renewal.request'].create({
            'contract_id': contract_sudo.id,
            'requested_start_date': post.get('requested_start_date') or contract_sudo.end_date,
            'requested_end_date': post.get('requested_end_date'),
            'requested_rent_amount': rent_amount,
            'note': post.get('note'),
        })
        return request.redirect('/my/leases/%d' % contract_id)

    # ------------------------------------------------------------
    # My Maintenance Requests
    # ------------------------------------------------------------

    @route(['/my/maintenance', '/my/maintenance/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_maintenance(self, page=1, **kw):
        MaintenanceRequest = request.env['edara.maintenance.request']
        domain = [('tenant_id', '=', request.env.user.partner_id.id)]
        pager = portal_pager(
            url='/my/maintenance', total=MaintenanceRequest.search_count(domain),
            page=page, step=self._items_per_page)
        maintenance_requests = MaintenanceRequest.search(
            domain, order='requested_date desc', limit=self._items_per_page, offset=pager['offset'])
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'maintenance', 'maintenance_requests': maintenance_requests, 'pager': pager,
        })
        return request.render('property_managment.portal_my_maintenance', values)

    @route(['/my/maintenance/new'], type='http', auth='user', website=True, methods=['GET'])
    def portal_maintenance_new_form(self, **kw):
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'maintenance', 'units': self._edara_tenant_active_units()})
        return request.render('property_managment.portal_maintenance_new', values)

    @route(['/my/maintenance/new'], type='http', auth='user', website=True, methods=['POST'])
    def portal_maintenance_new_submit(self, **post):
        units = self._edara_tenant_active_units()
        try:
            unit_id = int(post.get('unit_id') or 0)
        except ValueError:
            unit_id = 0
        if unit_id not in units.ids:
            raise UserError(_("You can only file a maintenance request for a unit you currently lease."))
        # sudo: ownership already verified above (unit_id restricted to the tenant's own
        # active leases); a portal user has no ir.sequence read access, needed for the
        # request's naming sequence, so the actual create must run with elevated rights.
        maintenance_request = request.env['edara.maintenance.request'].sudo().create({
            'title': post.get('title'),
            'description': post.get('description'),
            'unit_id': unit_id,
            'tenant_id': request.env.user.partner_id.id,
            'priority': post.get('priority') or 'normal',
        })
        return request.redirect('/my/maintenance/%d' % maintenance_request.id)

    @route(['/my/maintenance/<int:request_id>'], type='http', auth='user', website=True)
    def portal_maintenance_detail(self, request_id, **kw):
        maintenance_request_sudo = self._document_check_access('edara.maintenance.request', request_id)
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'maintenance', 'maintenance_request': maintenance_request_sudo})
        return request.render('property_managment.portal_maintenance_detail', values)
