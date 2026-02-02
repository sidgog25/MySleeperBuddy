FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e .

EXPOSE 8501

# Render sets $PORT; Streamlit must bind 0.0.0.0
CMD streamlit run app.py --server.address=0.0.0.0 --server.port ${PORT} --server.headless true
