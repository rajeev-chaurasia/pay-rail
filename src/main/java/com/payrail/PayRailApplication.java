package com.payrail;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@EnableScheduling
@SpringBootApplication
public class PayRailApplication {
  public static void main(String[] args) {
    SpringApplication.run(PayRailApplication.class, args);
  }
}
