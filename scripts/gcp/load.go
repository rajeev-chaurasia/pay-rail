// Open-loop HTTP generator with compact per-attempt records for scale evidence.
package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"runtime"
	"sync"
	"sync/atomic"
	"time"
)

type record struct {
	Ordinal        uint64
	StartedMicros  uint64
	DurationMicros uint32
	Status         uint16
	Flags          uint16
}

func main() {
	url := flag.String("url", "", "private benchmark URL")
	key := flag.String("key-file", "", "synthetic credential file")
	rate := flag.Int("rate", 100, "offered create arrivals per second")
	seconds := flag.Int("seconds", 60, "measurement duration")
	workers := flag.Int("workers", 2048, "maximum concurrent requests")
	run := flag.String("run", "", "unique run identity")
	output := flag.String("output", "", "binary attempt file")
	flag.Parse()
	if *rate < 1 || *rate > 25000 || *seconds < 1 || *seconds > 1800 || *workers < 1 || *workers > 8192 || *run == "" || *output == "" || *url == "" {
		panic("invalid bounded generator configuration")
	}
	credential, err := os.ReadFile(*key)
	if err != nil {
		panic(err)
	}
	file, err := os.Create(*output)
	if err != nil {
		panic(err)
	}
	defer file.Close()
	transport := &http.Transport{MaxIdleConns: *workers, MaxIdleConnsPerHost: *workers, MaxConnsPerHost: *workers}
	client := &http.Client{Transport: transport, Timeout: 10 * time.Second}
	jobs := make(chan uint64)
	results := make(chan record, 65536)
	var group sync.WaitGroup
	var ready sync.WaitGroup
	var writeGroup sync.WaitGroup
	var dropped, accepted, unexpected atomic.Uint64
	writeGroup.Add(1)
	go func() {
		defer writeGroup.Done()
		buffer := new(bytes.Buffer)
		for sample := range results {
			if err := binary.Write(buffer, binary.LittleEndian, sample); err != nil {
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
	start := time.Now()
	ready.Add(*workers)
	for w := 0; w < *workers; w++ {
		group.Add(1)
		go func() {
			defer group.Done()
			ready.Done()
			for ordinal := range jobs {
				began := time.Now()
				req, err := http.NewRequest("POST", *url+"/v1/payment_intents", bytes.NewBufferString(`{"amount":1000,"currency":"usd","captureMethod":"manual"}`))
				if err != nil {
					panic(err)
				}
				req.Header.Set("Authorization", "Bearer "+string(bytes.TrimSpace(credential)))
				req.Header.Set("Idempotency-Key", fmt.Sprintf("%s-%d", *run, ordinal))
				req.Header.Set("PayRail-Version", "2026-01-01")
				req.Header.Set("Content-Type", "application/json")
				sample := record{Ordinal: ordinal, StartedMicros: uint64(began.Sub(start).Microseconds())}
				response, err := client.Do(req)
				if err == nil {
					sample.Status = uint16(response.StatusCode)
					body, readErr := io.ReadAll(io.LimitReader(response.Body, 16385))
					response.Body.Close()
					var payment struct {
						ID     string `json:"id"`
						Status string `json:"status"`
						Amount int64  `json:"amount"`
					}
					if readErr == nil && len(body) <= 16384 && json.Unmarshal(body, &payment) == nil && response.StatusCode == 201 && payment.ID != "" && payment.Status == "requires_confirmation" && payment.Amount == 1000 {
						sample.Flags = 1
						accepted.Add(1)
					} else {
						unexpected.Add(1)
					}
				} else {
					unexpected.Add(1)
				}
				sample.DurationMicros = uint32(time.Since(began).Microseconds())
				results <- sample
			}
		}()
	}
	// Schedule cumulative arrivals against the original clock, never request completions.
	ready.Wait()
	start = time.Now()
	total := uint64(*rate) * uint64(*seconds)
	for ordinal := uint64(0); ordinal < total; ordinal++ {
		target := start.Add(time.Duration(ordinal) * time.Second / time.Duration(*rate))
		if delay := time.Until(target); delay > 0 {
			time.Sleep(delay)
		}
		if time.Since(target) > 10*time.Millisecond {
			dropped.Add(1)
			results <- record{Ordinal: ordinal, StartedMicros: uint64(time.Since(start).Microseconds()), Flags: 2}
			continue
		}
		select {
		case jobs <- ordinal:
		default:
			dropped.Add(1)
			results <- record{Ordinal: ordinal, StartedMicros: uint64(time.Since(start).Microseconds()), Flags: 2}
		}
	}
	close(jobs)
	if delay := time.Until(start.Add(time.Duration(*seconds) * time.Second)); delay > 0 {
		time.Sleep(delay)
	}
	group.Wait()
	close(results)
	writeGroup.Wait()
	if err := file.Sync(); err != nil {
		panic(err)
	}
	summary := map[string]any{"offered_rate": *rate, "duration_seconds": *seconds, "workers": *workers, "offered": total, "accepted": accepted.Load(), "dropped": dropped.Load(), "unexpected": unexpected.Load(), "elapsed_seconds": time.Since(start).Seconds(), "record_bytes": 24, "go_version": runtime.Version(), "logical_cpus": runtime.NumCPU(), "run_id": *run}
	encoded, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		panic(err)
	}
	if err := os.WriteFile(*output+".summary.json", append(encoded, '\n'), 0644); err != nil {
		panic(err)
	}
	fmt.Println(string(encoded))
}
