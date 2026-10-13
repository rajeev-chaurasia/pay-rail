FROM eclipse-temurin:17-jre
WORKDIR /app
COPY target/payrail-*.jar app.jar
USER 65532
ENTRYPOINT ["java","-jar","/app/app.jar"]
