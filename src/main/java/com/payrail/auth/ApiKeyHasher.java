package com.payrail.auth;

import com.payrail.config.PayRailProperties;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import org.springframework.stereotype.Component;

@Component
public class ApiKeyHasher {
  private final String pepper;

  public ApiKeyHasher(PayRailProperties properties) {
    this.pepper = properties.auth().pepper();
  }

  public String hash(String key) {
    try {
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256")
                  .digest((pepper + ":" + key).getBytes(StandardCharsets.UTF_8)));
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }
}
