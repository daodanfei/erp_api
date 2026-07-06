from rest_framework import status
from rest_framework.test import APITestCase

from core_apps.authentication.models import User
from core_apps.organization.models import Department


class DepartmentApiTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="org_user", password="testpass")
        self.client.force_authenticate(self.user)

    def test_department_list_returns_tree_from_root_only(self):
        root = Department.objects.create(name="总部")
        child = Department.objects.create(name="财务", parent=root)

        response = self.client.get("/api/org/departments/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], root.id)
        self.assertEqual(len(response.data[0]["children"]), 1)
        self.assertEqual(response.data[0]["children"][0]["id"], child.id)

    def test_department_cannot_set_parent_to_self(self):
        department = Department.objects.create(name="会计")

        response = self.client.patch(
            f"/api/org/departments/{department.id}/",
            {"parent": department.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent", response.data)

    def test_department_cannot_create_cycle(self):
        root = Department.objects.create(name="总部")
        child = Department.objects.create(name="会计", parent=root)

        response = self.client.patch(
            f"/api/org/departments/{root.id}/",
            {"parent": child.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent", response.data)
