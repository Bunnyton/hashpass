from python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY *.py .

CMD ["python3", "server.py"]
