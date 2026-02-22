FROM python:3.11-slim

# Calisma dizini
WORKDIR /app

# Bagimliliklari kur
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kaynak kodu kopyala
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config.yml.example ./config.yml.example

# Veri ve config dizinleri
RUN mkdir -p /app/data /app/config

# Non-root kullanici
RUN useradd -m -r -u 10001 annem && chown -R annem:annem /app
USER annem

# Calisma portu (HA 8123 ile cakismaz)
EXPOSE 8099

# Saglik kontrolu
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:8099/health', timeout=3.0); exit(0 if r.status_code==200 else 1)"

# Tek proses: uvicorn ile baslat
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8099"]
