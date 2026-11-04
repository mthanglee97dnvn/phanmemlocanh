package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

//go:embed payload/logo.png
var logoPng []byte

//go:embed payload/icon.ico
var iconIco []byte

var (
	mu    sync.Mutex
	phase = "ask" // ask | running | done | error
	errS  string
	logs  []string
	seen  = time.Now()
)

var appWin *exec.Cmd

func guiMain(dir string) {
	if _, err := os.Stat(filepath.Join(dir, "install.json")); err != nil {
		msgErr("Không tìm thấy dữ liệu cài đặt trong " + dir + " — dừng để an toàn, không xoá gì.")
		return
	}
	logf = func(s string) { mu.Lock(); logs = append(logs, s); mu.Unlock() }
	token := fmt.Sprintf("%x", time.Now().UnixNano())
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return
	}
	js := func(w http.ResponseWriter, v any) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(v)
	}
	auth := func(h http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("X-T") != token {
				http.Error(w, "forbidden", 403)
				return
			}
			h(w, r)
		}
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" || r.URL.Query().Get("t") != token {
			http.Error(w, "forbidden", 403)
			return
		}
		h := strings.ReplaceAll(guiHTML, "__TOKEN__", token)
		h = strings.ReplaceAll(h, "__DIR__", dir)
		h = strings.ReplaceAll(h, "__HOME__", dataHome())
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write([]byte(h))
	})
	mux.HandleFunc("/logo.png", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/png")
		w.Write(logoPng)
	})
	mux.HandleFunc("/favicon.ico", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/x-icon")
		w.Write(iconIco)
	})
	mux.HandleFunc("/api/state", auth(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		seen = time.Now()
		v := map[string]any{"phase": phase, "err": errS, "n": delCount.Load(), "log": append([]string(nil), logs...)}
		mu.Unlock()
		js(w, v)
	}))
	mux.HandleFunc("/api/start", auth(func(w http.ResponseWriter, r *http.Request) {
		var b struct{ DelData bool }
		json.NewDecoder(r.Body).Decode(&b)
		mu.Lock()
		if phase != "ask" {
			mu.Unlock()
			js(w, map[string]bool{"ok": false})
			return
		}
		phase = "running"
		mu.Unlock()
		go func() {
			err := uninstallSteps(dir, b.DelData)
			mu.Lock()
			if err != nil {
				phase, errS = "error", err.Error()
			} else {
				phase = "done"
			}
			mu.Unlock()
		}()
		js(w, map[string]bool{"ok": true})
	}))
	mux.HandleFunc("/api/exit", auth(func(w http.ResponseWriter, r *http.Request) {
		js(w, map[string]bool{"ok": true})
		go func() { time.Sleep(300 * time.Millisecond); selfDelete(); killWindow(appWin); os.Exit(0) }()
	}))
	go http.Serve(ln, mux)
	appWin = openAppWindow(fmt.Sprintf("http://%s/?t=%s", ln.Addr().String(), token))
	for {
		time.Sleep(time.Second)
		mu.Lock()
		idle, busy := time.Since(seen), phase == "running"
		mu.Unlock()
		if idle > 20*time.Second && !busy {
			selfDelete()
			killWindow(appWin)
			os.Exit(0)
		}
	}
}
