package com.payrail.auth;

public final class TenantContext {
  private static final ThreadLocal<String> TENANT = new ThreadLocal<>();

  private TenantContext() {}

  public static void set(String tenant) {
    TENANT.set(tenant);
  }

  public static String require() {
    String value = TENANT.get();
    if (value == null) throw new IllegalStateException("tenant context missing");
    return value;
  }

  public static void clear() {
    TENANT.remove();
  }
}
