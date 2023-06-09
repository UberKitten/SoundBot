FROM python:latest
WORKDIR /app/

RUN apt-get update && apt-get install -y libffi-dev libnacl-dev python3-dev nodejs

COPY ./requirements.txt /app/
RUN pip install -r requirements.txt

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
COPY ./package.json /app/
COPY ./package-lock.json /app/
RUN npm install

COPY ./web.sh /app/
COPY ./app/ /app/app/
RUN npm run build

CMD sh web.sh && python -m app.main
