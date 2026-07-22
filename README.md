# 🎯 Concurso Monitor & Tracker de Estudos

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)
[![Database](https://img.shields.io/badge/SQLite-3-003B57.svg)](https://www.sqlite.org/)
[![Docker Ready](https://img.shields.io/badge/Docker-Proxmox_LXC-2496ED.svg)](https://www.docker.com/)

Uma aplicação web *self-hosted* leve, moderna e completa em Python (**FastAPI + SQLite + HTML5/TailwindCSS**) projetada para monitorar concursos públicos no Brasil por cidades de interesse, enviar notificações automáticas via **Telegram Bot** e organizar a preparação de estudos com **Edital Verticalizado**.

---

## 🚀 Funcionalidades Principais

- 📍 **Dashboard de Concursos & Cidades de Interesse**:
  - Cadastro dinâmico de cidades/municípios de interesse (ex: *Sumaré*, *Campinas*, *Hortolândia*, *Valinhos*, etc.).
  - Filtro e visualização centralizada de concursos raspados com links diretos para o edital oficial.

- 🤖 **Scraper Automático Diário (APScheduler)**:
  - Varredura agendada (ex: diariamente às 07:00 AM) nos portais **PCI Concursos** e **JC Concursos**.
  - Possibilidade de disparo de varredura manual a qualquer momento via painel web.

- 🔔 **Central de Alertas no Telegram**:
  - Configuração simples de `TELEGRAM_BOT_TOKEN` e `CHAT_ID` via `.env` ou direto pela interface web.
  - Envio automático de mensagens formatadas com detalhes do concurso assim que uma nova oportunidade inédita for detectada.
  - Botão de teste para validação imediata do Bot.

- 📚 **Acompanhamento de Estudos (Edital Verticalizado)**:
  - Cadastro de Cargos/Concursos alvo.
  - Organização por Disciplinas e Tópicos do Edital.
  - Controle percentual de teoria lida, contador de revisões efetuadas e registro de questões (com cálculo automático da taxa de acertos).

- 🐳 **Deploy Otimizado para Proxmox LXC / Docker**:
  - Imagem Docker multi-stage leve baseada em `python:3.11-slim`.
  - Configuração via `docker-compose.yml` com volume persistente para manter os dados no SQLite entre reinícios do container.

---

## 🛠️ Arquitetura do Projeto

```
concurso_monitor/
├── app/
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/app.js
│   ├── templates/
│   │   └── index.html
│   ├── __init__.py
│   ├── database.py       # Conexão e sessão do SQLite (SQLAlchemy)
│   ├── main.py           # API FastAPI & agendador APScheduler
│   ├── models.py         # Modelos ORM (Cidades, Concursos, Alertas, Edital)
│   ├── scraper.py        # Módulo BeautifulSoup4/httpx para PCI e JC Concursos
│   └── telegram.py       # Integração com a Telegram Bot API
├── data/                 # Diretório persistente do banco SQLite (concursos.db)
├── .env.example          # Exemplo de variáveis de ambiente
├── .gitignore
├── Dockerfile            # Configuração de build do container
├── docker-compose.yml    # Orquestração para Docker / Proxmox LXC
├── README.md             # Documentação oficial do projeto
└── requirements.txt      # Dependências Python
```

---

## 💻 Como Rodar Localmente (Ambiente de Desenvolvimento)

### Requisitos
- Python 3.11 ou superior
- Git

### Passo a Passo

1. **Acessar a pasta do projeto**:
   ```bash
   cd concurso_monitor
   ```

2. **Criar e ativar o ambiente virtual (venv)**:
   ```bash
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Instalar as dependências**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar as variáveis de ambiente**:
   Copie o arquivo `.env.example` para `.env`:
   ```bash
   cp .env.example .env
   ```

5. **Iniciar a aplicação**:
   ```bash
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   Acesse a aplicação no navegador em: `http://localhost:8000`

---

## 🐳 Deploy no Proxmox LXC (Docker / Docker Compose)

Esta aplicação foi otimizada para rodar em containers Docker dentro de um LXC no Proxmox VE.

### 1. Preparação no Host / LXC Proxmox

Certifique-se de que o Docker e o Docker Compose estejam instalados na sua instância LXC.

```bash
# Clone ou envie o diretório concurso_monitor para o seu servidor
cd concurso_monitor

# Ajuste as permissões da pasta de dados
mkdir -p data
chmod 777 data

# Crie o arquivo .env com suas configurações
cp .env.example .env
```

### 2. Subindo o Container

```bash
docker compose up -d --build
```

### 3. Verificando o Status e Logs

```bash
# Verificar containers em execução
docker compose ps

# Visualizar logs em tempo real
docker compose logs -f concurso-monitor
```

---

## 🤖 Como Configurar o Bot do Telegram

Para receber as notificações no Telegram:

1. **Criar o Bot**:
   - No Telegram, busque por `@BotFather`.
   - Envie o comando `/newbot` e siga as instruções para definir o nome e username do bot.
   - Guarde o **HTTP API Token** gerado (ex: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).

2. **Obter o seu Chat ID**:
   - Envie qualquer mensagem para o bot `@userinfobot` no Telegram.
   - Ele responderá com o seu **Id** numérico (ex: `987654321`).

3. **Inserir na Aplicação**:
   - Você pode preencher esses valores no arquivo `.env` ou navegar até a aba **Central de Alertas** na interface web da aplicação, colar as credenciais e clicar em **Enviar Mensagem de Teste**.

---


## ⚙️ Variáveis de Ambiente (`.env`)

| Variável | Descrição | Valor Padrão |
| :--- | :--- | :--- |
| `DATABASE_URL` | String de conexão do banco SQLite | `sqlite:///./data/concursos.db` |
| `TELEGRAM_BOT_TOKEN` | Token do bot do Telegram | - |
| `TELEGRAM_CHAT_ID` | ID do chat no Telegram para alertas | - |
| `TELEGRAM_ENABLED` | Ativar/desativar notificações | `true` |
| `SCRAPER_CRON_HOUR` | Hora da execução diária do scraper (0-23) | `7` |
| `SCRAPER_CRON_MINUTE` | Minuto da execução diária do scraper (0-59) | `0` |

---

## 📄 Licença

Este projeto é desenvolvido para uso pessoal e open-source sob a licença MIT.
