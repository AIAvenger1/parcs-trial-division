# PARCS-Python node (master or worker).
# The original image was built on debian:stretch with python-pip from apt;
# stretch is EOL and its apt repositories are gone (404), so the original
# Dockerfile no longer builds. The PARCS core is Python-2-only, so we keep
# Python 2.7 but take it from the official python:2.7.18 image and install
# pinned, pure-Python dependencies (no apt, no compiler needed).
FROM python:2.7.18-slim

WORKDIR /parcs
COPY requirements.txt /parcs/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /parcs
RUN chmod +x run.sh generate_config.sh start.py

EXPOSE 8080
# PARCS_ARGS="master"  or  PARCS_ARGS="worker <master-ip>"
CMD ["./run.sh"]
