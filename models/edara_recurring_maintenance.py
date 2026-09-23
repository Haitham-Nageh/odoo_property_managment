from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .edara_maintenance_request import MAINTENANCE_CATEGORIES

# Maintenance Phase 2 (2026-09-23), ticket §20: minimum required set,
# followed exactly since the spec defines no recurring-maintenance concept
# at all to override it with.
FREQUENCIES = [
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('semi_annual', 'Semi-Annual'),
    ('yearly', 'Yearly'),
]

FREQUENCY_MONTHS = {'monthly': 1, 'quarterly': 3, 'semi_annual': 6, 'yearly': 12}


class EdaraRecurringMaintenance(models.Model):
    _name = 'edara.recurring.maintenance'
    _description = 'EDARA Recurring Maintenance Definition'
    _inherit = ['mail.thread']
    _order = 'next_date, id'

    # Maintenance Phase 2 (2026-09-23), ticket §18-19: a SCHEDULE/TEMPLATE,
    # never itself a work item - it only ever produces actual
    # edara.maintenance.request records (via the cron below), which then
    # enter the exact same existing lifecycle as any other request. BD-MNT-005:
    # unit_id is required, same as on edara.maintenance.request itself - a
    # generated request needs one anyway (that field's required=True is
    # existing, working, untouched behavior), so this definition requires it
    # up front rather than inventing a "which unit" resolution step for a
    # building/property-level recurrence the current model has no way to
    # represent on the generated request.
    name = fields.Char(required=True, tracking=True)
    unit_id = fields.Many2one('edara.unit', string='Unit', required=True, index=True, tracking=True)
    building_id = fields.Many2one(related='unit_id.building_id', store=True, index=True)
    property_id = fields.Many2one(related='unit_id.property_id', store=True, index=True)
    branch_id = fields.Many2one(related='unit_id.branch_id', store=True, index=True)
    company_id = fields.Many2one(related='unit_id.company_id', store=True, index=True)

    category = fields.Selection(MAINTENANCE_CATEGORIES)
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    description = fields.Text()
    priority = fields.Selection([
        ('low', 'Low'), ('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent'),
    ], required=True, default='normal')

    frequency = fields.Selection(FREQUENCIES, required=True, default='quarterly', tracking=True)
    next_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True, index=True)
    active = fields.Boolean(default=True, tracking=True)

    generated_request_ids = fields.One2many(
        'edara.maintenance.request', 'edara_recurring_id', string='Generated Requests')
    generated_request_count = fields.Integer(compute='_compute_generated_request_count')

    @api.depends('generated_request_ids')
    def _compute_generated_request_count(self):
        data = self.env['edara.maintenance.request']._read_group(
            [('edara_recurring_id', 'in', self.ids)], ['edara_recurring_id'], ['__count'])
        counts = {definition.id: count for definition, count in data}
        for definition in self:
            definition.generated_request_count = counts.get(definition.id, 0)

    def action_view_generated_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_maintenance_request')
        action['domain'] = [('edara_recurring_id', '=', self.id)]
        return action

    @api.model
    def _cron_generate_recurring_maintenance(self):
        """Ticket §21-23: generates one edara.maintenance.request per due,
        active definition, then advances next_date - never mutates a
        historical generated request, never touches an inactive definition.
        Idempotency's real guarantee is the DB-level unique constraint on
        edara.maintenance.request(edara_recurring_id, occurrence_date) (see
        that model) - occurrence_date is set to the definition's next_date
        BEFORE it's advanced, so even if this cron were somehow invoked
        twice for the same definition before next_date changes, the second
        create() would violate that constraint rather than silently
        duplicate the work item. Bounded domain (active, due today) - never
        a full-table scan of definitions or requests."""
        today = fields.Date.context_today(self)
        definitions = self.search([('active', '=', True), ('next_date', '<=', today)])
        Request = self.env['edara.maintenance.request']
        created = 0
        for definition in definitions:
            occurrence_date = definition.next_date
            if Request.search_count([
                ('edara_recurring_id', '=', definition.id), ('occurrence_date', '=', occurrence_date),
            ]):
                # Already generated (e.g. a prior run partially completed) -
                # advance and move on rather than hitting the unique
                # constraint as an error.
                definition.next_date = occurrence_date + relativedelta(months=FREQUENCY_MONTHS[definition.frequency])
                continue
            Request.create({
                'title': _("Recurring: %(name)s", name=definition.name),
                'description': definition.description,
                'unit_id': definition.unit_id.id,
                'category': definition.category,
                'vendor_id': definition.vendor_id.id,
                'priority': definition.priority,
                'edara_recurring_id': definition.id,
                'occurrence_date': occurrence_date,
            })
            definition.next_date = occurrence_date + relativedelta(months=FREQUENCY_MONTHS[definition.frequency])
            created += 1
        return created

    @api.constrains('unit_id', 'company_id')
    def _check_company_consistency(self):
        for definition in self:
            if definition.vendor_id and definition.vendor_id.company_id and (
                    definition.vendor_id.company_id != definition.company_id):
                raise ValidationError(_(
                    "The vendor's company must match the unit's company."))
