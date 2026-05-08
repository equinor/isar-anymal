FROM ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive

ARG ANYMAL_RELEASE_VERSION="25.06"
ARG ANYMAL_DOWNLOAD_USER_NAME
ARG APP_HOME=/home/ads-api
ENV APP_HOME=${APP_HOME}

# Install python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ca-certificates \
 && rm -rf /var/lib/apt/lists/*


# Install ADS CLI
WORKDIR /home/
COPY /scripts/install_ads_cli.sh /home/
RUN --mount=type=secret,id=ANYMAL_DOWNLOAD_PASSWORD_SECRET \
    export ANYMAL_DOWNLOAD_PASSWORD=$(cat /run/secrets/ANYMAL_DOWNLOAD_PASSWORD_SECRET) && \
    sh /home/install_ads_cli.sh

ENV VIRTUAL_ENV=/opt/ros/noetic/share/anymal_sdk_python39_environment/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN python3 -m pip install --upgrade pip

COPY requirements.txt ${APP_HOME}/
RUN pip install -r ${APP_HOME}/requirements.txt

WORKDIR ${APP_HOME}
COPY . ${APP_HOME}
RUN chmod +x scripts/entrypoint.sh
#RUN pip install ${APP_HOME}/



# Setup credentials files to be populated at runtime
RUN mkdir -p ${APP_HOME}/credentials/
RUN touch ${APP_HOME}/credentials/ads-cli.pem
RUN chown -R 1001:1001 /${APP_HOME}/credentials/ads-cli.pem
RUN touch ${APP_HOME}/credentials/ads-cli.crt
RUN chown -R 1001:1001 ${APP_HOME}/credentials/ads-cli.crt

# Folder to store the files that are to be sent by the ADS CLI
RUN mkdir -p ${APP_HOME}/data/

# Change to normal user
RUN useradd -ms /bin/bash --uid 1001 ads-cli
RUN chown -R 1001 ${APP_HOME}
RUN chmod 755 ${APP_HOME}
USER 1001

CMD [ "scripts/entrypoint.sh" ]
