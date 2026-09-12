FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV APP_DB_SERVICE_URL=http://db-service:8081
ENV APP_PREDICTION_ENGINE_URL=http://prediction-engine:8090
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
