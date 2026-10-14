FROM eclipse-temurin:17-jre@sha256:cd97df8431db59b12c5ded535294c9b5fb6d9caddb85aeba703c2660ff20d0dc
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade \
    libfreetype6=2.14.2+dfsg-1ubuntu0.2 libpng16-16t64=1.6.57-1ubuntu0.1 \
    && rm -rf /var/lib/apt/lists/* && rm -f /usr/bin/pebble
WORKDIR /app
COPY target/payrail-*.jar app.jar
USER 65532
ENTRYPOINT ["java","-jar","/app/app.jar"]
