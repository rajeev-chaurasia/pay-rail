package com.payrail;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@Testcontainers
@AutoConfigureMockMvc
@SpringBootTest(
    properties = {
      "payrail.rate-limit.enabled=true",
      "payrail.rate-limit.requests-per-minute=2",
      "payrail.outbox.enabled=false",
      "spring.kafka.admin.auto-create=false",
      "spring.kafka.listener.auto-startup=false"
    })
class RateLimiterIntegrationTest {
  @Container
  static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16.6-alpine");

  @Container
  static final GenericContainer<?> REDIS =
      new GenericContainer<>("redis:7.4.1-alpine").withExposedPorts(6379);

  @DynamicPropertySource
  static void infrastructure(DynamicPropertyRegistry properties) {
    properties.add("spring.datasource.url", POSTGRES::getJdbcUrl);
    properties.add("spring.datasource.username", POSTGRES::getUsername);
    properties.add("spring.datasource.password", POSTGRES::getPassword);
    properties.add("spring.data.redis.host", REDIS::getHost);
    properties.add("spring.data.redis.port", REDIS::getFirstMappedPort);
  }

  @Autowired MockMvc http;
  @Autowired RedisConnectionFactory redis;
  @Autowired StringRedisTemplate redisStrings;

  @BeforeEach
  void resetQuota() throws InterruptedException {
    // The concurrency assertion describes one quota window, not two adjacent windows.
    long second = java.time.Instant.now().getEpochSecond() % 60;
    if (second >= 57) Thread.sleep((60 - second) * 1000 + 100);
    flushRedis();
  }

  @Test
  void quotaIsAtomicAndExpires() throws Exception {
    var pool = Executors.newFixedThreadPool(8);
    CyclicBarrier start = new CyclicBarrier(8);
    List<Callable<Integer>> calls = new ArrayList<>();
    for (int worker = 0; worker < 8; worker++) {
      calls.add(
          () -> {
            start.await();
            return request().andReturn().getResponse().getStatus();
          });
    }
    var responses = pool.invokeAll(calls);
    pool.shutdown();
    List<Integer> statuses = new ArrayList<>();
    for (var response : responses) statuses.add(response.get());
    assertThat(statuses).containsOnly(404, 429);
    assertThat(statuses).filteredOn(value -> value == 404).hasSize(2);
    assertThat(statuses).filteredOn(value -> value == 429).hasSize(6);
    request()
        .andExpect(status().isTooManyRequests())
        .andExpect(header().string("Retry-After", "60"))
        .andExpect(jsonPath("$.error.code").value("rate_limit_exceeded"));
    String key = redisStrings.keys("rate:tenant_demo:*").stream().findFirst().orElseThrow();
    assertThat(redisStrings.getExpire(key)).isBetween(1L, 65L);
  }

  @Test
  void redisOutageFailsClosedAndRecovers() throws Exception {
    REDIS.getDockerClient().pauseContainerCmd(REDIS.getContainerId()).exec();
    try {
      request()
          .andExpect(status().isServiceUnavailable())
          .andExpect(jsonPath("$.error.code").value("rate_limiter_unavailable"));
    } finally {
      REDIS.getDockerClient().unpauseContainerCmd(REDIS.getContainerId()).exec();
    }
    assertThat(awaitRecoveredStatus()).isEqualTo(404);
  }

  private org.springframework.test.web.servlet.ResultActions request() throws Exception {
    return http.perform(
        get("/v1/payment_intents/missing").header("Authorization", "Bearer pr_test_demo"));
  }

  private void flushRedis() {
    try (var connection = redis.getConnection()) {
      connection.serverCommands().flushAll();
    }
  }

  private int awaitRecoveredStatus() throws Exception {
    int response = 503;
    for (int attempt = 0; attempt < 20 && response == 503; attempt++) {
      Thread.sleep(100);
      response = request().andReturn().getResponse().getStatus();
    }
    return response;
  }
}
