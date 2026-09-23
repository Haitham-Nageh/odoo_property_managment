from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestEdaraMultiCompany(TransactionCase):
    """Phase 14: the branch-manager/company-manager 'sees all branches' rule
    is a plain (1,'=',1) domain - it only stays company-scoped because it gets
    ANDed with the separate global multi-company rule (company_id in
    company_ids). That assumption was never directly exercised by a test with
    a second real res.company - this closes that gap."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Phase 6.4: company_a used to be cls.env.company (the real default
        # company), which already holds real, legitimate branch/property/unit
        # data in this shared dev database - "sees exactly branch_a" then
        # silently also matched that real data. Use a second isolated company
        # here too, matching company_b's own pattern, so both sides of this
        # test are genuinely clean.
        cls.company_a = cls.env['res.company'].create({'name': 'EDARA Test Company A'})
        cls.company_b = cls.env['res.company'].create({'name': 'EDARA Test Company B'})
        cls.branch_a = cls.env['edara.branch'].create(
            {'name': 'Branch A', 'code': 'MCA', 'company_id': cls.company_a.id})
        cls.branch_b = cls.env['edara.branch'].create(
            {'name': 'Branch B', 'code': 'MCB', 'company_id': cls.company_b.id})

    def test_company_manager_restricted_to_one_company_cannot_see_other_companys_branch(self):
        user = new_test_user(
            self.env, login='edara_cm_company_a', groups='property_managment.group_edara_company_manager',
            company_id=self.company_a.id, company_ids=[(6, 0, [self.company_a.id])])

        branches = self.env['edara.branch'].with_user(user).search([])
        self.assertEqual(branches, self.branch_a)
        with self.assertRaises(AccessError):
            self.branch_b.with_user(user).read(['name'])

    def test_company_manager_with_both_companies_sees_both_branches(self):
        user = new_test_user(
            self.env, login='edara_cm_both', groups='property_managment.group_edara_company_manager',
            company_id=self.company_a.id,
            company_ids=[(6, 0, [self.company_a.id, self.company_b.id])])

        branches = self.env['edara.branch'].with_user(user).search([])
        self.assertEqual(branches, self.branch_a | self.branch_b)
