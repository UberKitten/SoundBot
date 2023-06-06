FROM python:latest
RUN apt-get update && apt-get install -y libffi-dev libnacl-dev python3-dev

WORKDIR /app/
COPY ./requirements.txt /app/
COPY ./package.json /app/
COPY ./package-lock.json /app/
COPY ./web.sh /app/
COPY ./app/ /app/app/

RUN pip install -r requirements.txt
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
RUN apt-get install -y nodejs
RUN npm install
RUN npm run build

CMD sh web.sh && python -m app.main
