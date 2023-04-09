FROM python:latest
RUN apt-get install libffi-dev libnacl-dev python3-dev
COPY ./app/ /app/
CMD python main.py