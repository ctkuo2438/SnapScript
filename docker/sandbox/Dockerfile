FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY requirements.txt /tmp/snapscript-sandbox-requirements.txt
RUN pip install --no-cache-dir -r /tmp/snapscript-sandbox-requirements.txt \
    && rm /tmp/snapscript-sandbox-requirements.txt

RUN useradd --create-home --shell /usr/sbin/nologin snapscript
# Use a low-privilege snapscript user inside the container, 
#  and only grant it write access to a temporary workspace on the host for producing the output.
USER snapscript 

CMD ["python", "script.py"]
