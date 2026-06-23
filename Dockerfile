FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command runs the full 5-task evaluation suite.
# Override with: docker run --env-file .env <image> python main.py "your task"
ENTRYPOINT ["python", "main.py"]
CMD ["--suite"]
