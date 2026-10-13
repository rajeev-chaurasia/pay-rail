package com.payrail;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.payrail.auth.TenantContext;
import com.payrail.service.IdempotencyService;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

final class ConcurrencyEvidenceHarness {
  static final int CONCURRENCY = 8;
  private static final List<Path> SOURCE_PATHS =
      List.of(
          Path.of("pom.xml"), Path.of("src/main/java"), Path.of("src/main/resources/db/migration"));

  record Dependencies(
      JdbcTemplate jdbc,
      TransactionTemplate transactions,
      IdempotencyService idempotency,
      ObjectMapper mapper) {}

  record Sample(
      String phase,
      int worker,
      long startNanos,
      long endNanos,
      String outcome,
      boolean actionExecuted) {}

  record Result(
      List<Sample> samples,
      int guardedActionAttempts,
      long guardedEffects,
      long controlEffects,
      String databaseVersion) {}

  private final Dependencies dependencies;

  ConcurrencyEvidenceHarness(Dependencies dependencies) {
    this.dependencies = dependencies;
  }

  Result run() throws Exception {
    prepareTables();
    AtomicInteger guardedAttempts = new AtomicInteger();
    List<Sample> guarded = runGuarded(guardedAttempts);
    List<Sample> control = runControl();
    List<Sample> samples = new ArrayList<>(guarded);
    samples.addAll(control);
    Result result =
        new Result(
            samples,
            guardedAttempts.get(),
            count("evidence_guarded_effects"),
            count("evidence_unguarded_effects"),
            dependencies.jdbc().queryForObject("select version()", String.class));
    writeEvidenceIfRequested(result);
    return result;
  }

  private List<Sample> runGuarded(AtomicInteger attempts) throws Exception {
    CyclicBarrier start = new CyclicBarrier(CONCURRENCY);
    List<Callable<Sample>> tasks = new ArrayList<>();
    for (int worker = 0; worker < CONCURRENCY; worker++) {
      int workerId = worker;
      tasks.add(() -> guardedRequest(workerId, start, attempts));
    }
    return invoke(tasks);
  }

  private Sample guardedRequest(int worker, CyclicBarrier start, AtomicInteger attempts)
      throws Exception {
    TenantContext.set("tenant_demo");
    start.await();
    long started = System.nanoTime();
    AtomicInteger executed = new AtomicInteger();
    try {
      var response = dependencies.idempotency().executeRaw(guardedCommand(attempts, executed));
      String outcome = dependencies.mapper().readTree(response.body()).path("effect_id").asText();
      return new Sample(
          "guarded", worker, started, System.nanoTime(), outcome, executed.get() == 1);
    } finally {
      TenantContext.clear();
    }
  }

  private IdempotencyService.RawCommand guardedCommand(
      AtomicInteger attempts, AtomicInteger executed) {
    return new IdempotencyService.RawCommand(
        "evidence-shared-key",
        "evidence.create",
        "2026-01-01",
        Map.of("amount", 100),
        201,
        () -> createGuardedEffect(attempts, executed));
  }

  private Map<String, String> createGuardedEffect(AtomicInteger attempts, AtomicInteger executed) {
    attempts.incrementAndGet();
    executed.incrementAndGet();
    String effectId = UUID.randomUUID().toString();
    dependencies.jdbc().update("insert into evidence_guarded_effects values (?)", effectId);
    pauseForOverlap();
    return Map.of("effect_id", effectId);
  }

  private List<Sample> runControl() throws Exception {
    CyclicBarrier start = new CyclicBarrier(CONCURRENCY);
    CyclicBarrier afterRead = new CyclicBarrier(CONCURRENCY);
    List<Callable<Sample>> tasks = new ArrayList<>();
    for (int worker = 0; worker < CONCURRENCY; worker++) {
      int workerId = worker;
      tasks.add(() -> unguardedRequest(workerId, start, afterRead));
    }
    return invoke(tasks);
  }

  private Sample unguardedRequest(int worker, CyclicBarrier start, CyclicBarrier afterRead)
      throws Exception {
    start.await();
    long started = System.nanoTime();
    String effectId =
        dependencies.transactions().execute(ignored -> createUnguardedEffect(afterRead));
    return new Sample("unguarded_control", worker, started, System.nanoTime(), effectId, true);
  }

  private String createUnguardedEffect(CyclicBarrier afterRead) {
    Long existing =
        dependencies
            .jdbc()
            .queryForObject(
                "select count(*) from evidence_unguarded_effects where effect_key='shared'",
                Long.class);
    await(afterRead);
    if (existing != null && existing > 0) return "existing";
    String effectId = UUID.randomUUID().toString();
    dependencies
        .jdbc()
        .update(
            "insert into evidence_unguarded_effects(effect_key,effect_id) values ('shared',?)",
            effectId);
    return effectId;
  }

  private List<Sample> invoke(List<Callable<Sample>> tasks) throws Exception {
    ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
    try {
      List<Sample> samples = new ArrayList<>();
      for (Future<Sample> future : pool.invokeAll(tasks)) samples.add(future.get());
      return samples;
    } finally {
      pool.shutdown();
    }
  }

  private void prepareTables() {
    dependencies.jdbc().execute("drop table if exists evidence_guarded_effects");
    dependencies.jdbc().execute("drop table if exists evidence_unguarded_effects");
    dependencies
        .jdbc()
        .execute("create table evidence_guarded_effects(effect_id text primary key)");
    dependencies
        .jdbc()
        .execute(
            "create table evidence_unguarded_effects(id bigint generated always as identity primary key,effect_key text not null,effect_id text not null)");
  }

  private long count(String table) {
    return dependencies.jdbc().queryForObject("select count(*) from " + table, Long.class);
  }

  private void writeEvidenceIfRequested(Result result) throws IOException {
    String configured = System.getProperty("payrail.evidenceDir");
    if (configured == null || configured.isBlank()) return;
    Path directory = Path.of(configured);
    Files.createDirectories(directory);
    Files.writeString(directory.resolve("raw.csv"), csv(result.samples()), StandardCharsets.UTF_8);
    dependencies
        .mapper()
        .writerWithDefaultPrettyPrinter()
        .writeValue(directory.resolve("manifest.json").toFile(), manifest(result));
  }

  private Map<String, Object> manifest(Result result) {
    Map<String, Object> manifest = new LinkedHashMap<>();
    manifest.put("schema_version", "payrail-concurrency-evidence-v1");
    manifest.put("policy", "postgres-idempotency-row-lock-v1");
    manifest.put("generated_at", Instant.now().toString());
    manifest.put("source_paths", SOURCE_PATHS.stream().map(Path::toString).toList());
    manifest.put("source_tree_sha256", sourceFingerprint());
    manifest.put("database_version", result.databaseVersion());
    manifest.put("concurrency", CONCURRENCY);
    manifest.put("guarded_action_attempts", result.guardedActionAttempts());
    manifest.put("guarded_committed_effects", result.guardedEffects());
    manifest.put("negative_control_committed_effects", result.controlEffects());
    manifest.put("negative_control_detected", result.controlEffects() > 1);
    return manifest;
  }

  private String csv(List<Sample> samples) {
    StringBuilder csv =
        new StringBuilder("phase,worker,start_nanos,end_nanos,outcome,action_executed\n");
    samples.stream()
        .sorted(java.util.Comparator.comparing(Sample::phase).thenComparingInt(Sample::worker))
        .forEach(
            sample ->
                csv.append(sample.phase())
                    .append(',')
                    .append(sample.worker())
                    .append(',')
                    .append(sample.startNanos())
                    .append(',')
                    .append(sample.endNanos())
                    .append(',')
                    .append(sample.outcome())
                    .append(',')
                    .append(sample.actionExecuted())
                    .append('\n'));
    return csv.toString();
  }

  private String sourceFingerprint() {
    try {
      MessageDigest digest = MessageDigest.getInstance("SHA-256");
      for (Path path : sourceFiles()) {
        digest.update(path.toString().getBytes(StandardCharsets.UTF_8));
        digest.update(Files.readAllBytes(path));
      }
      return HexFormat.of().formatHex(digest.digest());
    } catch (IOException | NoSuchAlgorithmException e) {
      throw new IllegalStateException("cannot fingerprint evidence sources", e);
    }
  }

  private List<Path> sourceFiles() throws IOException {
    List<Path> files = new ArrayList<>();
    for (Path source : SOURCE_PATHS) {
      if (Files.isDirectory(source)) {
        try (var paths = Files.walk(source)) {
          paths.filter(Files::isRegularFile).forEach(files::add);
        }
      } else {
        files.add(source);
      }
    }
    return files.stream().sorted().toList();
  }

  private void pauseForOverlap() {
    try {
      Thread.sleep(150);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("evidence worker interrupted", e);
    }
  }

  private void await(CyclicBarrier barrier) {
    try {
      barrier.await();
    } catch (Exception e) {
      throw new IllegalStateException("evidence barrier failed", e);
    }
  }
}
