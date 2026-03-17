# Use Python 3.11 official image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy requirements file first (for caching)
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy all other files
COPY . .

# Expose port (Flask default 5000)
EXPOSE 5000

# Run the app (adjust if your app runs differently)
CMD ["python", "app.py"]