package com.payrail.api;

import jakarta.validation.ConstraintViolationException;
import java.time.Instant;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiErrorHandler {
  @ExceptionHandler(ApiException.class)
  ResponseEntity<?> api(ApiException e) {
    return error(e.status(), e.code(), e.getMessage());
  }

  @ExceptionHandler({
    MethodArgumentNotValidException.class,
    ConstraintViolationException.class,
    MissingRequestHeaderException.class
  })
  ResponseEntity<?> badRequest(Exception e) {
    return error(HttpStatus.BAD_REQUEST, "invalid_request", e.getMessage());
  }

  private ResponseEntity<?> error(HttpStatus status, String code, String message) {
    return ResponseEntity.status(status)
        .body(
            Map.of(
                "error",
                Map.of("code", code, "message", message),
                "timestamp",
                Instant.now().toString()));
  }
}
