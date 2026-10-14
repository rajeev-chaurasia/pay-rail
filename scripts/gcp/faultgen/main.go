// Seeded observed HTTP fault actions with one compact record per injection.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"os"
	"runtime"
	"strings"
	"sync"
	"time"
)

type fixture struct {
	ID          string `json:"id"`
	CreateKey   string `json:"create_key"`
	CaptureKey  string `json:"capture_key"`
	CaptureHash string `json:"capture_sha256"`
}
type action struct {
	Ordinal            uint64
	Fixture            uint32
	Class              uint8
	Passed             uint8
	Status             uint16
	RetryStatus        uint16
	DurationMicros     uint32
	StartedNanos       uint64
	VerificationStatus uint16
	ResponseHash       [32]byte
	VerificationHash   [32]byte
}

func main() {
	input := flag.String("fixtures", "", "captured synthetic fixture identities and golden hashes")
	keyFile := flag.String("key-file", "", "synthetic credential file")
	output := flag.String("output", "", "compact action output")
	count := flag.Int("faults", 1000000, "counted HTTP fault actions")
	workers := flag.Int("workers", 128, "bounded simultaneous actions")
	seed := flag.Int64("seed", 42, "schedule seed")
	rate := flag.Int("rate", 1000, "bounded fault actions per second")
	flag.Parse()
	if *count < 1 || *count > 1000000 || *workers < 1 || *workers > 512 || *rate < 1 || *rate > 1000 || *output == "" {
		panic("invalid bounded campaign")
	}
	data, err := os.ReadFile(*input)
	if err != nil {
		panic(err)
	}
	var configuration struct {
		Project  string    `json:"project"`
		Fixtures []fixture `json:"fixtures"`
	}
	if err := json.Unmarshal(data, &configuration); err != nil {
		panic(err)
	}
	if !strings.HasPrefix(configuration.Project, "payrail-qual-") || len(configuration.Fixtures) == 0 {
		panic("owned synthetic fixtures required")
	}
	credential, err := os.ReadFile(*keyFile)
	if err != nil {
		panic(err)
	}
	client := &http.Client{Timeout: 15 * time.Second, Transport: &http.Transport{MaxIdleConns: *workers, MaxIdleConnsPerHost: *workers, MaxConnsPerHost: *workers}}
	file, err := os.Create(*output)
	if err != nil {
		panic(err)
	}
	defer file.Close()
	jobs := make(chan action, *workers)
	results := make(chan action, 65536)
	initialJobs := make(chan action)
	var initial sync.WaitGroup
	var group sync.WaitGroup
	var writer sync.WaitGroup
	counts := map[uint8]uint64{}
	var failures uint64
	writer.Add(1)
	go func() {
		defer writer.Done()
		buffer := new(bytes.Buffer)
		for result := range results {
			counts[result.Class]++
			if result.Passed != 1 {
				failures++
			}
			if err := binary.Write(buffer, binary.LittleEndian, result); err != nil {
				panic(err)
			}
			if buffer.Len() >= 1024*1024 {
				if _, err := file.Write(buffer.Bytes()); err != nil {
					panic(err)
				}
				buffer.Reset()
			}
		}
		if _, err := file.Write(buffer.Bytes()); err != nil {
			panic(err)
		}
	}()
	request := func(path, body, key string, discard bool) (uint16, string) {
		req, err := http.NewRequest("POST", "http://10.240.0.10:18080"+path, strings.NewReader(body))
		if err != nil {
			panic(err)
		}
		req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(credential)))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("PayRail-Version", "2026-01-01")
		req.Header.Set("Idempotency-Key", key)
		response, err := client.Do(req)
		if err != nil {
			return 0, ""
		}
		defer response.Body.Close()
		if discard {
			return uint16(response.StatusCode), ""
		}
		bodyBytes, err := io.ReadAll(io.LimitReader(response.Body, 16385))
		if err != nil || len(bodyBytes) > 16384 {
			return uint16(response.StatusCode), ""
		}
		if path != "/v1/payment_intents" && response.StatusCode == 200 {
			var payment struct {
				Status         string `json:"status"`
				AmountReceived int64  `json:"amountReceived"`
			}
			if json.Unmarshal(bodyBytes, &payment) != nil || payment.Status != "succeeded" || payment.AmountReceived != 1000 {
				return uint16(response.StatusCode), ""
			}
		}
		digest := sha256.Sum256(bodyBytes)
		return uint16(response.StatusCode), hex.EncodeToString(digest[:])
	}
	started := time.Now()
	pace := func(ordinal int) {
		if delay := time.Until(started.Add(time.Duration(ordinal) * time.Second / time.Duration(*rate))); delay > 0 {
			time.Sleep(delay)
		}
	}
	// First lose every original capture response after commit, then prove exact retries.
	// Finish this phase before random duplicate actions read the learned golden hashes.
	for worker := 0; worker < *workers; worker++ {
		initial.Add(1)
		go func() {
			defer initial.Done()
			for result := range initialJobs {
				began := time.Now()
				result.StartedNanos = uint64(began.UnixNano())
				f := &configuration.Fixtures[result.Fixture]
				path := "/v1/payment_intents/" + f.ID + "/capture"
				result.Status, _ = request(path, `{"amount":1000}`, f.CaptureKey, true)
				var digest, replay string
				result.RetryStatus, digest = request(path, `{"amount":1000}`, f.CaptureKey, false)
				third, replay := request(path, `{"amount":1000}`, f.CaptureKey, false)
				result.VerificationStatus = third
				if value, err := hex.DecodeString(digest); err == nil {
					copy(result.ResponseHash[:], value)
				}
				if value, err := hex.DecodeString(replay); err == nil {
					copy(result.VerificationHash[:], value)
				}
				if result.Status == 200 && result.RetryStatus == 200 && third == 200 && digest != "" && digest == replay {
					result.Passed = 1
					f.CaptureHash = digest
				}
				result.DurationMicros = uint32(time.Since(began).Microseconds())
				results <- result
			}
		}()
	}
	if *count < len(configuration.Fixtures) {
		panic("campaign must cover every original capture")
	}
	for index := range configuration.Fixtures {
		pace(index)
		if configuration.Fixtures[index].CaptureHash != "" {
			panic("initial fixtures must be authorized with capture deferred")
		}
		initialJobs <- action{Ordinal: uint64(index), Fixture: uint32(index), Class: 3}
	}
	close(initialJobs)
	initial.Wait()
	learned, err := json.MarshalIndent(configuration, "", "  ")
	if err != nil {
		panic(err)
	}
	if err := os.WriteFile(*output+".fixtures.json", append(learned, '\n'), 0644); err != nil {
		panic(err)
	}
	for worker := 0; worker < *workers; worker++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for result := range jobs {
				began := time.Now()
				result.StartedNanos = uint64(began.UnixNano())
				f := configuration.Fixtures[result.Fixture]
				path := "/v1/payment_intents/" + f.ID + "/capture"
				var digest string
				if result.Class == 2 {
					result.Status, _ = request("/v1/payment_intents", `{"amount":1001,"currency":"usd","captureMethod":"manual"}`, f.CreateKey, false)
					if result.Status == 409 {
						result.Passed = 1
					}
				} else if result.Class == 3 {
					// Status headers follow the service commit; deliberately discard the saved body.
					result.Status, _ = request(path, `{"amount":1000}`, f.CaptureKey, true)
					result.RetryStatus, digest = request(path, `{"amount":1000}`, f.CaptureKey, false)
					if result.Status == 200 && result.RetryStatus == 200 && digest == f.CaptureHash {
						result.Passed = 1
					}
				} else {
					result.Status, digest = request(path, `{"amount":1000}`, f.CaptureKey, false)
					if result.Status == 200 && digest == f.CaptureHash {
						result.Passed = 1
					}
				}
				result.DurationMicros = uint32(time.Since(began).Microseconds())
				if value, err := hex.DecodeString(digest); err == nil {
					copy(result.ResponseHash[:], value)
				}
				results <- result
			}
		}()
	}
	random := rand.New(rand.NewSource(*seed))
	for ordinal := len(configuration.Fixtures); ordinal < *count; ordinal++ {
		pace(ordinal)
		value := random.Intn(100)
		class := uint8(1)
		if value >= 90 {
			class = 2
		} else if value >= 70 {
			class = 3
		}
		jobs <- action{Ordinal: uint64(ordinal), Fixture: uint32(random.Intn(len(configuration.Fixtures))), Class: class}
	}
	close(jobs)
	group.Wait()
	close(results)
	writer.Wait()
	if err := file.Sync(); err != nil {
		panic(err)
	}
	summary := map[string]any{"seed": *seed, "attempted_actions": *count, "counted_actions": uint64(*count) - failures, "original_capture_response_losses": len(configuration.Fixtures), "fixture_count": len(configuration.Fixtures), "class_counts": counts, "failures": failures, "elapsed_seconds": time.Since(started).Seconds(), "record_bytes": 96, "go_version": runtime.Version(), "logical_cpus": runtime.NumCPU(), "classes": map[string]string{"1": "duplicate capture replay", "2": "fingerprint conflict", "3": "discard committed response body then exact replay"}}
	summary["offered_fault_rate"] = *rate
	encoded, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		panic(err)
	}
	if err := os.WriteFile(*output+".summary.json", append(encoded, '\n'), 0644); err != nil {
		panic(err)
	}
	fmt.Println(string(encoded))
}
