FROM python:3.11-slim

# Evitar gravação de arquivos .pyc e buffer de saída do Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependências de sistema mínimas necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivo de dependências
COPY requirements.txt /app/

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o restante da aplicação
COPY . /app/

# Criar diretório para persistência do banco SQLite
RUN mkdir -p /app/data

# Porta onde o FastAPI/Uvicorn vai rodar
EXPOSE 8000

# Healthcheck para monitoramento no Docker/Proxmox
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/cities || exit 1

# Comando para iniciar o servidor
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
