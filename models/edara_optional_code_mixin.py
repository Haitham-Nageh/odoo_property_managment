from odoo import api, models


def _blank_code_to_false(vals):
    """A blank code means "no code": store NULL, never '', so the existing
    unique(..., code) constraints (which ignore NULLs) never see two empty strings."""
    code = vals.get('code')
    if isinstance(code, str) and not code.strip():
        vals['code'] = False


class EdaraOptionalCodeMixin(models.AbstractModel):
    """Normalises blank `code` values on create/write for Property, Building and Unit."""
    _name = 'edara.optional.code.mixin'
    _description = 'EDARA Optional Code Normalisation'

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            _blank_code_to_false(vals)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        _blank_code_to_false(vals)
        return super().write(vals)
