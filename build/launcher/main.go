// MThanglee Cull&Collage - bộ khởi chạy không cửa sổ đen.
// Nếu ứng dụng đang chạy thì chỉ mở lại trình duyệt; nếu chưa thì bật máy chủ cục bộ ẩn.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type running struct {
	Pid   int    `json:"pid"`
	Port  int    `json:"port"`
	Token string `json:"token"`
}

func dataHome() string {
	if h := os.Getenv("PHOTOSIFT_HOME"); h != "" {
		return h
	}
	h, _ := os.UserHomeDir()
	return filepath.Join(h, ".photosift")
}

// findRunning trả về địa chỉ nếu một phiên đang chạy và trả lời được.
func findRunning(home string) (string, bool) {
	b, err := os.ReadFile(filepath.Join(home, "running.json"))
	if err != nil {
		return "", false
	}
	var r running
	if json.Unmarshal(b, &r) != nil || r.Port == 0 || r.Token == "" {
		return "", false
	}
	url := fmt.Sprintf("http://127.0.0.1:%d/?t=%s", r.Port, r.Token)
	c := http.Client{Timeout: 2 * time.Second}
	resp, err := c.Get(url)
	if err != nil {
		return "", false
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	return url, resp.StatusCode == 200
}

func waitRunning(home string, d time.Duration) (string, bool) {
	end := time.Now().Add(d)
	for time.Now().Before(end) {
		if u, ok := findRunning(home); ok {
			return u, true
		}
		time.Sleep(500 * time.Millisecond)
	}
	return "", false
}

func main() {
	exe, _ := os.Executable()
	dir := filepath.Dir(exe)
	home := dataHome()

	if u, ok := findRunning(home); ok {
		openWindow(u, home)
		return
	}
	// Tránh mở hai bản cùng lúc khi bấm đúp liên tục
	if !acquireSingleton() {
		if u, ok := waitRunning(home, 90*time.Second); ok {
			openWindow(u, home)
		}
		return
	}

	core := filepath.Join(dir, "core", "CullCollageCore.exe")
	var cmd *exec.Cmd
	if _, err := os.Stat(core); err == nil {
		// Bản đóng gói sẵn: không dùng Python
		cmd = exec.Command(core, append(os.Args[1:], "--no-browser")...)
	} else {
		py := filepath.Join(dir, "python", "python.exe")
		if _, err := os.Stat(filepath.Join(dir, "python", "ready.txt")); err != nil {
			msgBox("MThanglee Cull&Collage", "Bản cài đặt chưa hoàn tất. Hãy chạy lại file cài đặt (MThanglee_CullCollage_Setup.exe).")
			return
		}
		if _, err := os.Stat(py); err != nil {
			msgBox("MThanglee Cull&Collage", "Không tìm thấy Python đi kèm. Hãy chạy lại file cài đặt.")
			return
		}
		cmd = exec.Command(py, append(append([]string{"run.py"}, os.Args[1:]...), "--no-browser")...)
	}
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "PHOTOSIFT_AUTOEXIT=1", "PYTHONUTF8=1", "PHOTOSIFT_APPDIR="+dir)
	if lf, err := os.OpenFile(filepath.Join(dir, "photosift.log"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644); err == nil {
		cmd.Stdout, cmd.Stderr = lf, lf
		defer lf.Close()
	}
	hideWindow(cmd)
	if err := cmd.Start(); err != nil {
		msgBox("MThanglee Cull&Collage", "Không khởi động được: "+err.Error())
		return
	}
	// Máy chủ tự mở trình duyệt; ở đây chờ nó sẵn sàng để giữ khoá, báo lỗi nếu thoát sớm.
	exited := make(chan struct{})
	go func() { cmd.Wait(); close(exited) }()
	end := time.Now().Add(120 * time.Second)
	for time.Now().Before(end) {
		if u, ok := findRunning(home); ok {
			if w := openWindow(u, home); w != nil {
				w.Wait() // chờ người dùng đóng cửa sổ
				time.Sleep(4 * time.Second)
				if idleSeconds(home) > 4 { // không còn giao diện nào đang mở → tắt máy chủ
					quitServer(home)
				}
			}
			return
		}
		select {
		case <-exited:
			msgBox("MThanglee Cull&Collage", "Ứng dụng đã dừng ngay khi khởi động. Xem file photosift.log trong thư mục cài đặt:\n"+dir)
			return
		case <-time.After(500 * time.Millisecond):
		}
	}
}

// idleSeconds: số giây kể từ lần cuối giao diện web hỏi trạng thái (giao diện mở thì ~1 giây).
func idleSeconds(home string) float64 {
	r, ok := readRunning(home)
	if !ok {
		return 999
	}
	var st struct {
		Idle float64 `json:"idle"`
	}
	b, err := apiCall(r, "GET", "/api/status")
	if err != nil || json.Unmarshal(b, &st) != nil {
		return 999
	}
	return st.Idle
}

func quitServer(home string) {
	if r, ok := readRunning(home); ok {
		apiCall(r, "POST", "/api/quit")
	}
}

func readRunning(home string) (running, bool) {
	var r running
	b, err := os.ReadFile(filepath.Join(home, "running.json"))
	if err != nil || json.Unmarshal(b, &r) != nil || r.Port == 0 {
		return r, false
	}
	return r, true
}

func apiCall(r running, method, path string) ([]byte, error) {
	req, _ := http.NewRequest(method, fmt.Sprintf("http://127.0.0.1:%d%s", r.Port, path), strings.NewReader("{}"))
	req.Header.Set("Cookie", "ps="+r.Token)
	req.Header.Set("Content-Type", "application/json")
	c := http.Client{Timeout: 3 * time.Second}
	resp, err := c.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}
