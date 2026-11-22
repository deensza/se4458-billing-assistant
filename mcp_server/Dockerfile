FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8001
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY docs_index.py server.py ./
COPY data ./data

RUN useradd --create-home appuser
USER appuser
EXPOSE 8001
CMD ["python", "server.py"]
