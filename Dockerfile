FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# This default command will runs the full 6-task evaluation suite.
# Please Override with: docker run --env-file .env <image> python main.py "your task" -> if you wanna run only one specific task for testing
ENTRYPOINT ["python", "main.py"]
CMD ["--suite"]
