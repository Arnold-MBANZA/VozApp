import os
import tempfile
import time
import unittest

_data_directory = tempfile.TemporaryDirectory()
os.environ["VOZLOCAL_DATA_DIR"] = _data_directory.name
os.environ["TRANSCRIBER_DEMO"] = "1"

from fastapi.testclient import TestClient
from app import app


class ApiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        admin = cls.client.post("/api/auth/register", json={
            "name": "Admin VozLocal", "email": "admin@example.com", "password": "motdepasse-solide"
        })
        assert admin.status_code == 201, admin.text
        cls.admin_headers = {"Authorization": f"Bearer {admin.json()['token']}"}

    def test_complete_user_flow(self) -> None:
        second = self.client.post("/api/auth/register", json={
            "name": "Utilisateur Test", "email": "user@example.com", "password": "autre-motdepasse"
        })
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["user"]["role"], "user")
        headers = {"Authorization": f"Bearer {second.json()['token']}"}
        created = self.client.post(
            "/api/jobs", headers=headers, data={"prompt": "ecclesiologia"},
            files={"audio": ("cours.m4a", b"demo audio", "audio/mp4")},
        )
        self.assertEqual(created.status_code, 202, created.text)
        job_id = created.json()["job_id"]
        job = None
        for _ in range(50):
            detail = self.client.get(f"/api/jobs/{job_id}", headers=headers)
            self.assertEqual(detail.status_code, 200)
            job = detail.json()["job"]
            if job["status"] in {"completed", "failed"}: break
            time.sleep(0.1)
        self.assertEqual(job["status"], "completed", job)
        self.assertTrue(job["has_audio"])
        self.assertTrue(job["has_text"])
        self.assertIn("Igreja", job["transcript"])
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/audio", headers=headers).content, b"demo audio")
        txt = self.client.get(f"/api/jobs/{job_id}/download/txt", headers=headers)
        docx = self.client.get(f"/api/jobs/{job_id}/download/docx", headers=headers)
        self.assertEqual(txt.status_code, 200)
        self.assertTrue(docx.content.startswith(b"PK"))
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}?target=audio", headers=headers).status_code, 200)
        after = self.client.get(f"/api/jobs/{job_id}", headers=headers).json()["job"]
        self.assertFalse(after["has_audio"])
        self.assertTrue(after["has_text"])
        users = self.client.get("/api/admin/users", headers=self.admin_headers)
        self.assertEqual(users.status_code, 200)
        self.assertEqual(len(users.json()["users"]), 2)
        self.assertEqual(self.client.get("/api/admin/users", headers=headers).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}?target=both", headers=headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}", headers=headers).status_code, 404)

    def test_protected_routes_require_authentication(self) -> None:
        self.assertEqual(self.client.get("/api/jobs").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/users").status_code, 401)


if __name__ == "__main__":
    unittest.main()
