FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

ENV MODEL_CACHE_DIR=/app/model_cache/huggingface
ENV HF_HOME=/app/model_cache/huggingface
ENV HUGGINGFACE_HUB_CACHE=/app/model_cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY requirements-torch.txt /app/requirements-torch.txt

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN python -c "import sentencepiece, tiktoken, google.protobuf; print('TOKENIZER DEPS OK')"

RUN pip install --no-cache-dir -r /app/requirements-torch.txt

COPY src /app/src
COPY preload_model.py /app/preload_model.py


EXPOSE 5000
EXPOSE 5001
