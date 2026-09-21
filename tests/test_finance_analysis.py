"""
Testes unitários e de integração para o módulo de Análise Financeira (Fatura Nubank & Entradas/Saídas).
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

    # --- 1. TESTES DO MOTOR DE CATEGORIZAÇÃO E TIPO ---

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

        # Entradas
        self.assertEqual(finance.categorize_transaction("Transferencia recebida pelo Pix"), "Entradas")
        self.assertEqual(finance.categorize_transaction("Deposito em conta"), "Entradas")
        self.assertEqual(finance.categorize_transaction("Salario Empresa XPTO"), "Entradas")

    def test_detect_transaction_type(self):
        # Entradas
        self.assertEqual(finance.detect_transaction_type("Transferencia recebida", "1500.00"), "income")
        self.assertEqual(finance.detect_transaction_type("Pix recebido de Fulano", "200.00"), "income")
        self.assertEqual(finance.detect_transaction_type("Deposito identificado", "350.00"), "income")
        self.assertEqual(finance.detect_transaction_type("Salario Mensal", "5000.00"), "income")
        self.assertEqual(finance.detect_transaction_type("Reembolso Consulta", "120.00"), "income")
        self.assertEqual(finance.detect_transaction_type("Lançamento", "+500.00"), "income")

        # Saídas
        self.assertEqual(finance.detect_transaction_type("iFood *Restaurante", "45.00"), "expense")
        self.assertEqual(finance.detect_transaction_type("Uber *Trip", "19.90"), "expense")
        self.assertEqual(finance.detect_transaction_type("Pagamento de boleto", "300.00"), "expense")

    def test_categorize_transaction_custom_rules_override(self):
        custom_rules = [
            {"keyword": "padaria do ze", "category_name": "Alimentação"},
            {"keyword": "clinica vet", "category_name": "Pets / Animais"},
        ]
        cat1 = finance.categorize_transaction("Clinica Vet Amigo Fiel", None, custom_rules)
        self.assertEqual(cat1, "Pets / Animais")

        cat2 = finance.categorize_transaction("Padaria do Ze", None, custom_rules)
        self.assertEqual(cat2, "Alimentação")

    # --- 2. TESTES DE PARSING DE FATURAS E EXTRATOS NUBANK ---

    def test_parse_nubank_csv_credit_card(self):
        csv_content = """date,category,title,amount
2024-01-15,restaurante,iFood *Ifood,45.90
2024-01-16,transporte,Uber *Uber *Trip,22.50
2024-01-20,supermercado,Carrefour Express,150.00
2024-01-22,entradas,Pix recebido cliente,500.00
2024-01-25,outros,Pagamento de fatura,218.40
2024-02-05,lazer,Netflix.com,55.90
"""
        results = finance.parse_nubank_csv(csv_content)
        # Pagamento genérico de fatura deve ser ignorado, mas pix recebido deve ser capturado como entrada
        self.assertEqual(len(results), 5)

        # Despesa 1
        self.assertEqual(results[0]["title"], "iFood *Ifood")
        self.assertEqual(results[0]["amount"], 45.90)
        self.assertEqual(results[0]["transaction_type"], "expense")
        self.assertEqual(results[0]["category"], "Alimentação")

        # Entrada
        self.assertEqual(results[3]["title"], "Pix recebido cliente")
        self.assertEqual(results[3]["amount"], 500.00)
        self.assertEqual(results[3]["transaction_type"], "income")
        self.assertEqual(results[3]["category"], "Entradas")

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
<TRNTYPE>CREDIT</TRNTYPE>
<DTPOSTED>20240412120000[-3:BRT]</DTPOSTED>
<TRNAMT>1200.00</TRNAMT>
<MEMO>Transferencia Recebida</MEMO>
</STMTTRN>
</BANKTRANLIST>
</OFX>
"""
        results = finance.parse_ofx(ofx_content)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["transaction_type"], "expense")
        self.assertEqual(results[0]["category"], "Alimentação")

        self.assertEqual(results[1]["transaction_type"], "income")
        self.assertEqual(results[1]["category"], "Entradas")
        self.assertEqual(results[1]["amount"], 1200.00)

    def test_compute_financial_summary_income_and_expenses(self):
        mock_transactions = [
            {"month_year": "2024-01", "category": "Alimentação", "amount": 100.0, "transaction_type": "expense"},
            {"month_year": "2024-01", "category": "Transporte", "amount": 50.0, "transaction_type": "expense"},
            {"month_year": "2024-01", "category": "Entradas", "amount": 1000.0, "transaction_type": "income"},
            {"month_year": "2024-02", "category": "Alimentação", "amount": 150.0, "transaction_type": "expense"},
            {"month_year": "2024-02", "category": "Compras", "amount": 200.0, "transaction_type": "expense"},
            {"month_year": "2024-02", "category": "Entradas", "amount": 1200.0, "transaction_type": "income"},
        ]
        summary = finance.compute_financial_summary(mock_transactions)
        self.assertEqual(summary["total_spent"], 500.0) # Total Saídas
        self.assertEqual(summary["total_income"], 2200.0) # Total Entradas
        self.assertEqual(summary["net_balance"], 1700.0) # Saldo Líquido (2200 - 500)
        self.assertEqual(summary["total_transactions"], 6)
        self.assertEqual(summary["months_count"], 2)
        self.assertEqual(summary["avg_monthly"], 250.0)
        self.assertEqual(summary["top_category"], "Alimentação")
        self.assertEqual(len(summary["monthly_breakdown"]), 2)
        self.assertEqual(summary["monthly_breakdown"][0]["total_income"], 1000.0)
        self.assertEqual(summary["monthly_breakdown"][0]["total_expense"], 150.0)
        self.assertEqual(summary["monthly_breakdown"][0]["net_balance"], 850.0)

    # --- 3. TESTES DE INTEGRAÇÃO DA API ---

    def test_api_create_and_list_transaction(self):
        # Despesa
        p1 = {
            "date": "2024-05-10",
            "title": "Supermercado Extra",
            "amount": 180.50,
            "transaction_type": "expense",
            "category": "Alimentação",
            "payment_method": "Cartão Nubank"
        }
        res1 = self.client.post("/api/finances/transactions", json=p1)
        self.assertEqual(res1.status_code, 200)

        # Entrada
        p2 = {
            "date": "2024-05-15",
            "title": "Pix Cliente Projeto",
            "amount": 2500.00,
            "transaction_type": "income",
            "category": "Entradas",
            "payment_method": "Pix"
        }
        res2 = self.client.post("/api/finances/transactions", json=p2)
        self.assertEqual(res2.status_code, 200)

        # Listar filtrando apenas entradas
        res_income = self.client.get("/api/finances/transactions?tx_type=income")
        self.assertEqual(res_income.status_code, 200)
        self.assertEqual(len(res_income.json()), 1)
        self.assertEqual(res_income.json()[0]["title"], "Pix Cliente Projeto")

        # Listar filtrando apenas saídas
        res_expense = self.client.get("/api/finances/transactions?tx_type=expense")
        self.assertEqual(res_expense.status_code, 200)
        self.assertEqual(len(res_expense.json()), 1)
        self.assertEqual(res_expense.json()[0]["title"], "Supermercado Extra")

        # Summary
        sum_res = self.client.get("/api/finances/summary")
        self.assertEqual(sum_res.status_code, 200)
        sdata = sum_res.json()
        self.assertEqual(sdata["total_spent"], 180.50)
        self.assertEqual(sdata["total_income"], 2500.00)
        self.assertEqual(sdata["net_balance"], 2319.50)
