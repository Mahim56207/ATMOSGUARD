FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000 8501
# default: the API. docker-compose.yml starts the dashboard from the same image.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
