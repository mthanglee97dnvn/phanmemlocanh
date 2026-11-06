package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"math"
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

type guiState struct {
	mu       sync.Mutex
	Phase    string   `json:"phase"` // welcome | running | done | error
	Step     int      `json:"step"`
	Text     string   `json:"text"`
	Sub      int      `json:"sub"`
	Err      string   `json:"err"`
	Warn     string   `json:"warn"`
	Dir      string   `json:"dir"`
	Log      []string `json:"log"`
	launcher string
	doneAt   time.Time
	seen     time.Time
}

var gs = &guiState{Phase: "welcome", seen: time.Now()}

func stage(n int, text string) {
	gs.mu.Lock()
	gs.Step, gs.Text, gs.Sub = n, text, 0
	gs.mu.Unlock()
	say("[%d/4] %s…", n, text)
}

func setSub(p int) {
	gs.mu.Lock()
	gs.Sub = p
	gs.mu.Unlock()
}

func normalizeDir(d string) (string, bool) {
	d = strings.Trim(strings.TrimSpace(d), `"`)
	if d == "" || !filepath.IsAbs(d) {
		return "", false
	}
	d = filepath.Clean(d)
	if !strings.EqualFold(filepath.Base(d), "MThanglee CullCollage") {
		d = filepath.Join(d, "MThanglee CullCollage")
	}
	return d, true
}

func guiMain() {
	logf = func(s string) {
		gs.mu.Lock()
		gs.Log = append(gs.Log, s)
		if len(gs.Log) > 300 {
			gs.Log = gs.Log[len(gs.Log)-300:]
		}
		gs.mu.Unlock()
	}
	failHook = func(err error) {
		gs.mu.Lock()
		gs.Phase, gs.Err = "error", err.Error()
		gs.mu.Unlock()
	}
	gs.Dir = defaultDir()
	if updateDir != "" {
		gs.Phase, gs.Dir = "running", updateDir
		go func() {
			closeOldApp()
			l := runInstall(updateDir)
			gs.mu.Lock()
			gs.launcher, gs.Phase = l, "done"
			gs.mu.Unlock()
			startDetached(l)
			time.Sleep(800 * time.Millisecond)
			quit()
		}()
	}
	token := fmt.Sprintf("%x", time.Now().UnixNano())

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		os.Exit(1)
	}
	mux := http.NewServeMux()
	auth := func(h http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("X-T") != token && r.URL.Query().Get("t") != token {
				http.Error(w, "forbidden", 403)
				return
			}
			h(w, r)
		}
	}
	js := func(w http.ResponseWriter, v any) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(v)
	}
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" || r.URL.Query().Get("t") != token {
			http.Error(w, "forbidden", 403)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write([]byte(strings.ReplaceAll(guiHTML, "__TOKEN__", token)))
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
		gs.mu.Lock()
		gs.seen = time.Now()
		left := closeLeft()
		cp := struct {
			Phase, Text, Err, Dir, Warn string
			Step, Sub                   int
			Log                         []string
		}{gs.Phase, gs.Text, gs.Err, gs.Dir, gs.Warn, gs.Step, gs.Sub, append([]string(nil), gs.Log...)}
		gs.mu.Unlock()
		js(w, map[string]any{"phase": cp.Phase, "text": cp.Text, "err": cp.Err, "warn": cp.Warn, "dir": cp.Dir, "step": cp.Step, "sub": cp.Sub, "log": cp.Log, "closeIn": left})
	}))
	mux.HandleFunc("/api/pick", auth(func(w http.ResponseWriter, r *http.Request) {
		js(w, map[string]string{"path": pickFolder()})
	}))
	mux.HandleFunc("/api/start", auth(func(w http.ResponseWriter, r *http.Request) {
		var b struct{ Dir string }
		json.NewDecoder(r.Body).Decode(&b)
		d, ok := normalizeDir(b.Dir)
		gs.mu.Lock()
		if !ok || gs.Phase != "welcome" {
			gs.mu.Unlock()
			w.WriteHeader(400)
			js(w, map[string]string{"error": "Đường dẫn không hợp lệ — hãy nhập đường dẫn đầy đủ, ví dụ D:\\Phan mem"})
			return
		}
		gs.Phase, gs.Dir = "running", d
		gs.mu.Unlock()
		go func() {
			l := runInstall(d)
			gs.mu.Lock()
			gs.launcher, gs.Phase = l, "done"
			gs.mu.Unlock()
		}()
		js(w, map[string]any{"ok": true, "dir": d})
	}))
	mux.HandleFunc("/api/launch", auth(func(w http.ResponseWriter, r *http.Request) {
		gs.mu.Lock()
		l := gs.launcher
		gs.mu.Unlock()
		if l != "" {
			startDetached(l)
		}
		js(w, map[string]bool{"ok": true})
		go func() { time.Sleep(800 * time.Millisecond); quit() }()
	}))
	mux.HandleFunc("/api/exit", auth(func(w http.ResponseWriter, r *http.Request) {
		js(w, map[string]bool{"ok": true})
		go func() { time.Sleep(300 * time.Millisecond); quit() }()
	}))
	go http.Serve(ln, mux)

	url := fmt.Sprintf("http://%s/?t=%s", ln.Addr().String(), token)
	appWin = openAppWindow(url)

	// Thoát khi cửa sổ đã đóng (và không còn đang cài dở)
	for {
		time.Sleep(200 * time.Millisecond)
		gs.mu.Lock()
		idle := time.Since(gs.seen)
		busy := gs.Phase == "running"
		left := closeLeft()
		closing := !gs.doneAt.IsZero()
		gs.mu.Unlock()
		if (idle > 20*time.Second && !busy) || (closing && left <= 0) {
			quit()
		}
	}
}

// closeLeft trả về số giây còn lại trước khi tự đóng sau khi cài xong; đếm ở đây chứ không ở trang web,
// vì trình duyệt có thể giãn nhịp hoặc dừng bộ đếm của cửa sổ nằm dưới cửa sổ khác. Cần giữ gs.mu.
func closeLeft() int {
	if gs.Phase != "done" || gs.Warn != "" {
		return -1
	}
	if gs.doneAt.IsZero() {
		gs.doneAt = time.Now()
	}
	return int(math.Ceil((autoCloseAfter - time.Since(gs.doneAt)).Seconds()))
}

var appWin *exec.Cmd

const autoCloseAfter = 5 * time.Second

func quit() {
	killWindow(appWin)
	cleanupProfile()
	os.Exit(0)
}
