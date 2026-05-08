#!/bin/bash

apt-get update

apt-get install -y lsb-release gnupg2 ca-certificates curl xvfb

sh -c 'echo "deb [arch=amd64] https://packages-ros.anybotics.com/ros/release-'$ANYMAL_RELEASE_VERSION'/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/any-ros.list'
curl -fsSL https://packages.anybotics.com/gpg | apt-key add -
apt-get update

sh -c 'echo "machine packages.anybotics.com login '$ANYMAL_DOWNLOAD_USER_NAME' password '$ANYMAL_DOWNLOAD_PASSWORD'" > /etc/apt/auth.conf.d/packages.anybotics.com.conf' && chmod 600 /etc/apt/auth.conf.d/packages.anybotics.com.conf

sh -c 'echo "deb [arch=amd64] https://packages.anybotics.com/anymal/release-'$ANYMAL_RELEASE_VERSION'/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/anymal.list'

sh -c 'echo "deb [arch=amd64] https://packages.anybotics.com/robot-configuration/ubuntu/ $(lsb_release -sc) main" > /etc/apt/sources.list.d/anymal-config.list'

curl -fsSL https://packages.anybotics.com/gpg | apt-key add -
sh -c 'echo "Package: *\nPin: origin \"packages.anybotics.com\"\nPin-Priority: 990" > /etc/apt/preferences.d/anybotics-default'

apt-get update

apt-get install -y ros-noetic-anymal-data-sync-cli
