FROM marketplace.gcr.io/google/python:latest
USER root
RUN apt-get update
RUN apt-get install -y wget gconf-service libasound2 libatk1.0-0 libcairo2 libcups2 libfontconfig1 libgdk-pixbuf2.0-0 libgtk-3-0 libnspr4 libpango-1.0-0 libxss1 fonts-liberation libappindicator1 libnss3 lsb-release xdg-utils
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
RUN dpkg -i google-chrome-stable_current_amd64.deb; apt-get -fy install
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY ./src ./src
COPY ./resources ./resources
ENTRYPOINT ["python", "-m", "src/main.py"]
USER cnb