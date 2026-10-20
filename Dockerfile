FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY clintr ./clintr
COPY web ./web
RUN pip install --no-cache-dir .
ENV CLINTR_DB=/data/clintr.sqlite3 CLINTR_BLOBS=/data/blobs
EXPOSE 8000
CMD ["uvicorn", "clintr.api:app", "--host", "0.0.0.0", "--port", "8000"]
