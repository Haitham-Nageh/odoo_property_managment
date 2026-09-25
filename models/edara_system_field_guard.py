from odoo import _, api, models
from odoo.exceptions import AccessError


class EdaraSystemFieldGuard(models.AbstractModel):
    """Phase 7 (Enterprise Hardening): UI `readonly` is not a security boundary.

    Two families of fields are system-managed and must never be rewritten by a
    regular user through ORM/RPC (`/web/dataset/call_kw`, custom client code):
      * every stored related field (branch_id/company_id/property_id/... - the
        branch/company boundary the record rules depend on; the ORM lets a
        caller write them directly, leaving them inconsistent with the parent);
      * the explicit `_edara_system_fields` of a model (e.g. contract `state`,
        schedule line `invoice_id`).

    Authorization signal is `env.su`, not a context key: a client controls
    context via RPC, it cannot control `sudo()`. Internal flows that legitimately
    change these fields do `check_access('write')` first and then write through a
    narrowly scoped `.sudo()`. ORM recomputation of related fields never goes
    through write(), so it is unaffected."""
    _name = 'edara.system.field.guard'
    _description = 'EDARA System-Managed Field Guard'

    _edara_system_fields = ()

    def _edara_protected_fields(self):
        derived = {
            name for name, field in self._fields.items()
            if field.related and field.store and field.readonly and not field.inherited
        }
        return derived | set(self._edara_system_fields)

    def write(self, vals):
        if not self.env.su:
            protected = self._edara_protected_fields() & set(vals)
            if protected:
                raise AccessError(_(
                    "The following fields are managed by the system and cannot be modified "
                    "directly: %(fields)s.", fields=', '.join(sorted(protected))))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        # Derived values are always recomputed from the parent record. A client-supplied
        # value could only ever make them inconsistent, so it is discarded (not raised:
        # a legitimate form save may echo them back).
        if not self.env.su:
            protected = self._edara_protected_fields()
            vals_list = [{k: v for k, v in vals.items() if k not in protected} for vals in vals_list]
        return super().create(vals_list)


# One class per guarded model: the mixin is added to the existing model without
# touching its own file. `_edara_system_fields` = non-related system-managed fields.
def _guard(model, system_fields=()):
    class _Guarded(models.Model):
        _name = model
        _inherit = [model, 'edara.system.field.guard']
        _edara_system_fields = system_fields
    _Guarded.__name__ = 'EdaraGuard_' + model.replace('.', '_')
    return _Guarded


for _model, _fields in (
    ('edara.unit', ()),
    ('edara.building', ()),
    ('edara.property', ()),
    ('edara.ownership', ()),
    ('edara.lease.contract', ('state', 'successor_contract_id', 'predecessor_contract_id')),
    ('edara.payment.schedule.line', ('invoice_id',)),
    ('edara.deposit', ()),
    ('edara.deposit.transaction', ()),
    ('edara.service.charge', ()),
    ('edara.service.charge.line', ()),
    ('edara.maintenance.request', ()),
    ('edara.recurring.maintenance', ()),
    ('edara.renewal.request', ()),
):
    _guard(_model, _fields)
