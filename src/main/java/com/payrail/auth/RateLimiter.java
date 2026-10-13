package com.payrail.auth;

import com.payrail.api.ApiException;
import com.payrail.config.PayRailProperties;
import java.time.Instant;
import java.util.List;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

@Component
public class RateLimiter {
  private static final DefaultRedisScript<Long> SCRIPT =
      new DefaultRedisScript<>(
          "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('PEXPIRE',KEYS[1],ARGV[1]) end; return n",
          Long.class);
  private final StringRedisTemplate redis;
  private final PayRailProperties.RateLimit config;

  public RateLimiter(StringRedisTemplate redis, PayRailProperties properties) {
    this.redis = redis;
    this.config = properties.rateLimit();
  }

  public void check(String tenant) {
    if (!config.enabled()) return;
    long minute = Instant.now().getEpochSecond() / 60;
    try {
      Long count = redis.execute(SCRIPT, List.of("rate:" + tenant + ":" + minute), "65000");
      if (count != null && count > config.requestsPerMinute())
        throw new ApiException(
            HttpStatus.TOO_MANY_REQUESTS, "rate_limit_exceeded", "Tenant request limit exceeded");
    } catch (ApiException e) {
      throw e;
    } catch (RuntimeException e) {
      throw new ApiException(
          HttpStatus.SERVICE_UNAVAILABLE, "rate_limiter_unavailable", "Rate limiter unavailable");
    }
  }
}
