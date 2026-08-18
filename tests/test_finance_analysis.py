"""
Testes unitários e de integração para o módulo de Análise Financeira (Fatura Nubank).
"""

import os
import sys
import unittest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Adicionar caminho para importar app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "concurso_monitor"))

from app.database import Base, get_db
from app.main import app
from app import models, finance


class TestFinanceAnalysis(unittest.TestCase):

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

    # --- 1. TESTES DO MOTOR DE CATEGORIZAÇÃO ---

    def test_categorize_transaction_defaults(self):
        # Alimentação
        self.assertEqual(finance.categorize_transaction("iFood *Restaurante"), "Alimentação")
        self.assertEqual(finance.categorize_transaction("Supermercado Pao de Acucar"), "Alimentação")
        self.assertEqual(finance.categorize_transaction("McDonalds Shopping"), "Alimentação")

        # Transporte
        self.assertEqual(finance.categorize_transaction("Uber *Trip Sao Paulo"), "Transporte")
        self.assertEqual(finance.categorize_transaction("Posto Shell Campinas"), "Transporte")
        self.assertEqual(finance.categorize_transaction("Sem Parar Pedagios"), "Transporte")

        # Assinaturas & Lazer
        self.assertEqual(finance.categorize_transaction("Netflix.com"), "Assinaturas & Lazer")
        self.assertEqual(finance.categorize_transaction("Spotify Premium"), "Assinaturas & Lazer")
        self.assertEqual(finance.categorize_transaction("Steam Games"), "Assinaturas & Lazer")
        self.assertEqual(finance.categorize_transaction("Smart Fit Academia"), "Assinaturas & Lazer")

        # Moradia
        self.assertEqual(finance.categorize_transaction("CPFL Energia"), "Moradia")
        self.assertEqual(finance.categorize_transaction("Enel Distribuicao"), "Moradia")
        self.assertEqual(finance.categorize_transaction("Sabesp Agua"), "Moradia")

        # Compras
        self.assertEqual(finance.categorize_transaction("Mercado Livre *Compra"), "Compras")
        self.assertEqual(finance.categorize_transaction("Amazon Marketplace"), "Compras")
        self.assertEqual(finance.categorize_transaction("Shopee Brasil"), "Compras")

        # Saúde
        self.assertEqual(finance.categorize_transaction("Droga Raia Farmacia"), "Saúde")
        self.assertEqual(finance.categorize_transaction("Drogasil Sao Paulo"), "Saúde")

        # Educação
        self.assertEqual(finance.categorize_transaction("Udemy Cursos Online"), "Educação")
        self.assertEqual(finance.categorize_transaction("Alura Treinamentos"), "Educação")

    def test_categorize_transaction_custom_rules_override(self):
        custom_rules = [
            {"keyword": "padaria do ze", "category_name": "Alimentação"},
            {"keyword": "clinica vet", "category_name": "Pets / Animais"},
        ]
        # Regra customizada sobrepõe padrão
        cat1 = finance.categorize_transaction("Clinica Vet Amigo Fiel", None, custom_rules)
        self.assertEqual(cat1, "Pets / Animais")

        cat2 = finance.categorize_transaction("Padaria do Ze", None, custom_rules)
        self.assertEqual(cat2, "Alimentação")

    # --- 2. TESTES DE PARSING DE FATURAS NUBANK ---

    def test_parse_nubank_csv_credit_card(self):
        csv_content = """date,category,title,amount
2024-01-15,restaurante,iFood *Ifood,45.90
2024-01-16,transporte,Uber *Uber *Trip,22.50
2024-01-20,supermercado,Carrefour Express,150.00
2024-01-25,outros,Pagamento de fatura,218.40
2024-02-05,lazer,Netflix.com,55.90
"""
        results = finance.parse_nubank_csv(csv_content)
        # Pagamento de fatura deve ser ignorado
        self.assertEqual(len(results), 4)

        self.assertEqual(results[0]["title"], "iFood *Ifood")
        self.assertEqual(results[0]["amount"], 45.90)
        self.assertEqual(results[0]["category"], "Alimentação")
        self.assertEqual(results[0]["month_year"], "2024-01")

        self.assertEqual(results[1]["title"], "Uber *Uber *Trip")
        self.assertEqual(results[1]["amount"], 22.50)
        self.assertEqual(results[1]["category"], "Transporte")

        self.assertEqual(results[3]["title"], "Netflix.com")
        self.assertEqual(results[3]["amount"], 55.90)
        self.assertEqual(results[3]["month_year"], "2024-02")

    def test_parse_nubank_csv_brazilian_format_semicolon(self):
        csv_content = """Data;Categoria;Título;Valor
10/03/2024;serviços;Droga Raia;89,90
12/03/2024;transporte;Auto Posto Ipiranga;150,00
"""
        results = finance.parse_nubank_csv(csv_content)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Droga Raia")
        self.assertEqual(results[0]["amount"], 89.90)
        self.assertEqual(results[0]["category"], "Saúde")
        self.assertEqual(results[0]["month_year"], "2024-03")

        self.assertEqual(results[1]["title"], "Auto Posto Ipiranga")
        self.assertEqual(results[1]["amount"], 150.00)
        self.assertEqual(results[1]["category"], "Transporte")

    def test_parse_ofx_format(self):
        ofx_content = """
<OFX>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20240410120000[-3:BRT]</DTPOSTED>
<TRNAMT>-35.00</TRNAMT>
<MEMO>iFood *Refeicao</MEMO>
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20240412120000[-3:BRT]</DTPOSTED>
<TRNAMT>-19.90</TRNAMT>
<MEMO>Uber Viagem</MEMO>
</STMTTRN>
</BANKTRANLIST>
</OFX>
"""
        results = finance.parse_ofx(ofx_content)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "iFood *Refeicao")
        self.assertEqual(results[0]["amount"], 35.00)
        self.assertEqual(results[0]["category"], "Alimentação")
        self.assertEqual(results[0]["month_year"], "2024-04")

    def test_compute_financial_summary(self):
        mock_transactions = [
            {"month_year": "2024-01", "category": "Alimentação", "amount": 100.0},
            {"month_year": "2024-01", "category": "Transporte", "amount": 50.0},
            {"month_year": "2024-02", "category": "Alimentação", "amount": 150.0},
            {"month_year": "2024-02", "category": "Compras", "amount": 200.0},
        ]
        summary = finance.compute_financial_summary(mock_transactions)
        self.assertEqual(summary["total_spent"], 500.0)
        self.assertEqual(summary["total_transactions"], 4)
        self.assertEqual(summary["months_count"], 2)
        self.assertEqual(summary["avg_monthly"], 250.0)
        self.assertEqual(summary["top_category"], "Alimentação")
        self.assertEqual(summary["top_category_amount"], 250.0)
        self.assertEqual(summary["top_category_percent"], 50.0)
        self.assertEqual(len(summary["monthly_breakdown"]), 2)

    # --- 3. TESTES DE INTEGRAÇÃO DA API ---

    def test_api_create_and_list_transaction(self):
        payload = {
            "date": "2024-05-10",
            "title": "Supermercado Extra",
            "amount": 180.50,
            "category": "Alimentação",
            "payment_method": "Cartão Nubank"
        }
        create_res = self.client.post("/api/finances/transactions", json=payload)
        self.assertEqual(create_res.status_code, 200)
        data = create_res.json()
        self.assertEqual(data["title"], "Supermercado Extra")
        self.assertEqual(data["amount"], 180.50)
        self.assertEqual(data["month_year"], "2024-05")

        list_res = self.client.get("/api/finances/transactions")
        self.assertEqual(list_res.status_code, 200)
        transactions = list_res.json()
        self.assertEqual(len(transactions), 1)

    def test_api_upload_invoice(self):
        csv_file_content = b"date,category,title,amount\n2024-06-01,transporte,Uber 99,25.00\n2024-06-02,restaurante,Habibs,40.00\n"
        files = {"file": ("fatura_nubank_junho.csv", csv_file_content, "text/csv")}
        upload_res = self.client.post("/api/finances/upload", files=files)
        self.assertEqual(upload_res.status_code, 200)
        data = upload_res.json()
        self.assertEqual(data["imported_count"], 2)
        self.assertEqual(data["total_amount"], 65.00)

        summary_res = self.client.get("/api/finances/summary")
        self.assertEqual(summary_res.status_code, 200)
        summary = summary_res.json()
        self.assertEqual(summary["total_spent"], 65.00)
        self.assertEqual(summary["total_transactions"], 2)
        self.assertIn("2024-06", summary["available_months"])

    def test_api_paste_invoice(self):
        paste_content = "2024-07-01,mercado,Carrefour,120.00\n2024-07-05,lazer,Netflix,55.90"
        res = self.client.post("/api/finances/paste", json={"content": paste_content})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["imported_count"], 2)

    def test_api_rules_and_recategorization(self):
        # Criar transação com título específico
        self.client.post("/api/finances/transactions", json={
            "date": "2024-08-01",
            "title": "SmartFit Academia Mensalidade",
            "amount": 129.90,
            "category": "Outros"
        })

        # Adicionar regra customizada para categorizar 'smartfit' como 'Saúde'
        rule_res = self.client.post("/api/finances/rules", json={
            "keyword": "smartfit",
            "category_name": "Saúde"
        })
        self.assertEqual(rule_res.status_code, 200)
        rule_data = rule_res.json()
        self.assertGreaterEqual(rule_data["updated_transactions_count"], 1)

        # Verificar se a transação foi atualizada para Saúde
        txs = self.client.get("/api/finances/transactions").json()
        self.assertTrue(any(t["title"] == "SmartFit Academia Mensalidade" and t["category"] == "Saúde" for t in txs))

    def test_api_clear_finances(self):
        self.client.post("/api/finances/transactions", json={"date": "2024-01-01", "title": "A", "amount": 10.0})
        self.client.post("/api/finances/transactions", json={"date": "2024-02-01", "title": "B", "amount": 20.0})

        # Limpar apenas janeiro
        clear_res = self.client.delete("/api/finances/clear?month=2024-01")
        self.assertEqual(clear_res.status_code, 200)
        txs = self.client.get("/api/finances/transactions").json()
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0]["month_year"], "2024-02")

        # Limpar tudo
        clear_all = self.client.delete("/api/finances/clear")
        self.assertEqual(clear_all.status_code, 200)
        txs_empty = self.client.get("/api/finances/transactions").json()
        self.assertEqual(len(txs_empty), 0)


if __name__ == "__main__":
    unittest.main()
