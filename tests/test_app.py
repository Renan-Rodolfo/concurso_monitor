"""
Testes unitários e de integração para o sistema Buscando Trabalho (Concursos Públicos, Vagas Privadas e Telegram).
"""

import os
import sys
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Garantir que o diretório raiz da aplicação esteja no sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import Base, get_db
from app.main import app
from app import models


class TestBuscandoTrabalho(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Setup in-memory SQLite com StaticPool para compartilhar conexões
        cls.test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.test_engine)

        def override_get_db():
            db = cls.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    def setUp(self):
        Base.metadata.create_all(bind=self.test_engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.test_engine)

    # --- 1. TESTES DE CONCURSOS & CIDADES ---

    def test_add_and_list_target_cities(self):
        response = self.client.post("/api/cities", json={"name": "Campinas", "uf": "SP"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Campinas")
        self.assertEqual(data["uf"], "SP")

        list_resp = self.client.get("/api/cities")
        self.assertEqual(list_resp.status_code, 200)
        cities = list_resp.json()
        self.assertEqual(len(cities), 1)
        self.assertEqual(cities[0]["name"], "Campinas")

    def test_duplicate_city_rejected(self):
        self.client.post("/api/cities", json={"name": "Sumaré", "uf": "SP"})
        dup_resp = self.client.post("/api/cities", json={"name": "Sumaré", "uf": "SP"})
        self.assertEqual(dup_resp.status_code, 400)

    # --- 2. TESTES DE VAGAS PRIVADAS (JOB SEARCH) ---

    def test_candidate_profile_flow(self):
        profile_data = {
            "full_name": "Candidato Teste",
            "headline": "Desenvolvedor Python & Analista de Suporte",
            "location": "São Paulo, SP",
            "primary_skills": "Python, FastAPI, Docker, SQL",
            "target_roles": "Analista de Suporte, Desenvolvedor Python",
            "dealbreakers": "Apenas Remoto ou Híbrido"
        }
        post_resp = self.client.post("/api/job-search/profile", json=profile_data)
        self.assertEqual(post_resp.status_code, 200)

        get_resp = self.client.get("/api/job-search/profile")
        self.assertEqual(get_resp.status_code, 200)
        saved = get_resp.json()
        self.assertEqual(saved["full_name"], "Candidato Teste")
        self.assertIn("FastAPI", saved["primary_skills"])

    def test_job_opportunity_crud_and_status(self):
        job_data = {
            "title": "Analista de Suporte N2",
            "company": "Empresa XYZ",
            "location": "Remoto",
            "work_model": "Remoto",
            "salary": "R$ 4.500",
            "link": "https://gupy.io/vaga/123",
            "skills_required": "Linux, Redes, Atendimento ao Cliente",
            "pcd_type": "Ampla"
        }
        res = self.client.post("/api/job-search/jobs", json=job_data)
        self.assertEqual(res.status_code, 200)
        created = res.json()
        job_id = created["id"]
        self.assertEqual(created["status"], "Nova")

        # Atualizar status da vaga
        status_resp = self.client.put(f"/api/job-search/jobs/{job_id}/status", json={"status": "Aplicado", "notes": "Candidatura enviada via Gupy"})
        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(status_resp.json()["status"], "Aplicado")

        # Marcar visualizada
        view_resp = self.client.put(f"/api/job-search/jobs/{job_id}/viewed", json={"is_viewed": True})
        self.assertEqual(view_resp.status_code, 200)
        self.assertTrue(view_resp.json()["is_viewed"])

    # --- 3. TESTES DE CONFIGURAÇÃO DO TELEGRAM ---

    def test_telegram_config(self):
        cfg = {"bot_token": "123456789:TEST_TOKEN", "chat_id": "987654321", "enabled": True}
        save_resp = self.client.post("/api/telegram", json=cfg)
        self.assertEqual(save_resp.status_code, 200)

        get_resp = self.client.get("/api/telegram")
        self.assertEqual(get_resp.status_code, 200)
        self.assertTrue(get_resp.json()["is_configured"])
        self.assertEqual(get_resp.json()["chat_id"], "987654321")

    # --- 4. TESTES DE STATS DASHBOARD (SEM FINANÇAS) ---

    def test_stats_dashboard(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("cities_count", data)
        self.assertIn("concursos_count", data)
        self.assertIn("jobs_count", data)
        self.assertIn("jobs_open_count", data)
        # Garantir ausência de campos financeiros
        self.assertNotIn("finances_count", data)
        self.assertNotIn("finances_total_spent", data)

    # --- 5. TESTES DE AUSÊNCIA DE ROTAS FINANCEIRAS ---

    def test_finance_endpoints_are_404(self):
        self.assertEqual(self.client.get("/api/finances/summary").status_code, 404)
        self.assertEqual(self.client.get("/api/finances/transactions").status_code, 404)
        self.assertEqual(self.client.post("/api/finances/transactions", json={}).status_code, 404)
        self.assertEqual(self.client.get("/api/finances/rules").status_code, 404)


if __name__ == "__main__":
    unittest.main()
