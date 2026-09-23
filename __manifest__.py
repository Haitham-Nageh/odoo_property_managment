{
    'name': 'EDARA Property Management',
    'version': '19.0.1.0.0',
    'category': 'Real Estate/Property Management',
    'summary': 'Professional property, lease and tenant management built natively on Odoo Accounting.',
    'description': """
EDARA Property Management
==========================
Manages the complete rental lifecycle - branches, properties, buildings, units,
ownership, tenants, lease contracts, payment schedules, rent invoicing, tenant
payments, security deposits, service charges, maintenance and reporting - on
top of native Odoo Accounting, Portal, Contacts and Security.
""",
    'author': 'EDARA',
    'website': 'https://edara.ps',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'portal',
        'account',
    ],
    'data': [
        'security/edara_security.xml',
        'security/ir.model.access.csv',
        'security/edara_record_rules.xml',
        'data/edara_sequences.xml',
        'data/edara_analytic_plan.xml',
        'data/edara_activity_types.xml',
        'data/edara_cron.xml',
        'views/dashboard_views.xml',
        'views/branch_views.xml',
        'views/property_views.xml',
        'views/building_views.xml',
        'views/unit_views.xml',
        'wizard/edara_lease_renewal_wizard_views.xml',
        'wizard/edara_deposit_transaction_wizard_views.xml',
        'views/payment_schedule_line_views.xml',
        'views/deposit_views.xml',
        'views/service_charge_views.xml',
        'views/maintenance_request_views.xml',
        'views/recurring_maintenance_views.xml',
        'views/renewal_request_views.xml',
        'views/contract_views.xml',
        'views/reports_views.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/portal_templates.xml',
        'views/edara_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'property_managment/static/src/css/edara_dashboard.css',
            'property_managment/static/src/css/payment_schedule_filter_shortcuts.css',
            'property_managment/static/src/js/payment_schedule_filter_shortcuts.js',
            'property_managment/static/src/js/payment_schedule_filter_shortcuts.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
