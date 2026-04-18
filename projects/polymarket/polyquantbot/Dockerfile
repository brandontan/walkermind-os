FROM python:3.11-slim

WORKDIR /app

# Copy semua file
COPY . .

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt || true

# Run bot
CMD ["python", "main.py"]
