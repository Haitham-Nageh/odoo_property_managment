from psycopg2.errors import UniqueViolation

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestEdaraBranch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Phase 6.4: 'RAM' collides with a real, legitimate branch already in
        # this shared dev database (not test data - do not rename/delete it).
        cls.branch_a = cls.env['edara.branch'].create({'name': 'Test Ramallah Branch', 'code': 'TRAM'})
        cls.branch_b = cls.env['edara.branch'].create({'name': 'Nablus Branch', 'code': 'NBL'})

    def test_branch_code_unique_per_company(self):
        # Phase 7: creates its own original instead of assuming a pre-existing 'RAM'
        # branch (which only existed in the old Community dev DB, not a clean DB).
        self.env['edara.branch'].create({'name': 'Original', 'code': 'UNIQ1'})
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation):
            with self.env.cr.savepoint():
                self.env['edara.branch'].create({'name': 'Duplicate', 'code': 'UNIQ1'})

    def test_viewer_sees_only_assigned_branch(self):
        user = new_test_user(self.env, login='edara_viewer_a', groups='property_managment.group_edara_viewer')
        self.branch_a.user_ids = [(4, user.id)]

        branches = self.env['edara.branch'].with_user(user).search([])
        self.assertEqual(branches, self.branch_a)

        with self.assertRaises(AccessError):
            self.branch_b.with_user(user).read(['name'])

    def test_company_manager_sees_all_branches(self):
        # Phase 6.4: assert against "every branch this company manager can
        # see" rather than an exact count, since this shared dev database may
        # already contain other real, legitimate branches beyond the two this
        # test creates - the (1,'=',1) rule's job is to include ALL of them,
        # not just these two.
        pre_existing = self.env['edara.branch'].search([])
        user = new_test_user(self.env, login='edara_cm', groups='property_managment.group_edara_company_manager')

        branches = self.env['edara.branch'].with_user(user).search([])
        self.assertEqual(branches, pre_existing | self.branch_a | self.branch_b)
