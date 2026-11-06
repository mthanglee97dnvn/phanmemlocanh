// MThanglee Cull&Collage - bộ gỡ cài đặt.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const regKey = `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MThangleeCullCollage`

var logf = func(s string) {}

func say(f string, a ...any) { logf(fmt.Sprintf(f, a...)) }

func dataHome() string {
	if h := os.Getenv("PHOTOSIFT_HOME"); h != "" {
		return h
	}
	h, _ := os.UserHomeDir()
	return filepath.Join(h, ".photosift")
}

func stopRunning() {
	b, err := os.ReadFile(filepath.Join(dataHome(), "running.json"))
	if err != nil {
		return
	}
	var r struct {
		Port  int    `json:"port"`
		Token string `json:"token"`
	}
	if json.Unmarshal(b, &r) != nil || r.Port == 0 {
		return
	}
	req, _ := http.NewRequest("POST", fmt.Sprintf("http://127.0.0.1:%d/api/quit", r.Port), strings.NewReader("{}"))
	req.Header.Set("Cookie", "ps="+r.Token)
	req.Header.Set("Content-Type", "application/json")
	c := http.Client{Timeout: 3 * time.Second}
	if resp, err := c.Do(req); err == nil {
		resp.Body.Close()
		time.Sleep(300 * time.Millisecond)
	}
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}

func main() {
	setupConsole()
	// Chạy tại chỗ (không chép ra thư mục Temp để tránh bị phần mềm diệt virus chặn).
	exe, _ := os.Executable()
	os.Chdir(os.TempDir()) // không giữ thư mục cài đặt làm thư mục hiện hành (sẽ khoá việc xoá)
	guiMain(filepath.Dir(exe))
}

var (
	cleanupDir    string // thư mục cài đặt: xoá nốt sau khi tiến trình này thoát
	cleanupParent bool
)

// uninstallSteps gỡ sạch: tiến trình, lối tắt, mục đăng ký, thư mục cài đặt, và (tuỳ chọn) dữ liệu người dùng.
func uninstallSteps(dir string, delData bool) error {
	var meta struct {
		Links         []string `json:"links"`
		ParentCreated bool     `json:"parent_created"`
	}
	if b, err := os.ReadFile(filepath.Join(dir, "install.json")); err == nil {
		json.Unmarshal(b, &meta)
	}
	// Lối tắt + mục gỡ cài đặt xoá song song với việc tắt tiến trình
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		say("Xoá lối tắt và mục gỡ cài đặt…")
		for _, l := range meta.Links {
			os.Remove(l)
		}
		removeShortcutsByName()
		removeReg()
	}()
	say("Tắt ứng dụng nếu đang chạy…")
	stopRunning()
	killLeftovers(dir, dataHome())
	wg.Wait()

	say("Xoá thư mục cài đặt…")
	self, _ := os.Executable()
	if err := removeTree(dir, self, 0); err != nil {
		// File đang bị khoá: không báo lỗi, hẹn xoá nốt (thử lại nhiều lần) ngay sau khi đóng cửa sổ này.
		say("Một số file đang bị Windows giữ (%v) — sẽ tự xoá nốt sau khi bạn đóng cửa sổ này.", err)
	}
	cleanupDir, cleanupParent = dir, meta.ParentCreated
	if delData {
		home := dataHome()
		say("Xoá dữ liệu người dùng…")
		if e2 := removeTree(home, "", 0); e2 != nil {
			return fmt.Errorf("chưa xoá hết dữ liệu tại %s (%v)", home, e2)
		}
	}
	return nil
}

var (
	delSem   = make(chan struct{}, 24)
	delCount atomic.Int64 // số mục đã xoá (hiển thị tiến độ)
)

// removeTree xoá song song cây thư mục (bỏ qua file `keep`). Semaphore chỉ giữ khi xoá thật,
// không giữ trong lúc chờ thư mục con (tránh nghẽn vòng).
func removeTree(p, keep string, depth int) error {
	st, err := os.Lstat(p)
	if err != nil {
		return nil
	}
	if !st.IsDir() || depth >= 3 {
		if strings.EqualFold(p, keep) {
			return nil
		}
		delSem <- struct{}{}
		err := retryRemoveAll(p)
		<-delSem
		delCount.Add(1)
		return err
	}
	ents, _ := os.ReadDir(p)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var first error
	for _, e := range ents {
		c := filepath.Join(p, e.Name())
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := removeTree(c, keep, depth+1); err != nil {
				mu.Lock()
				if first == nil {
					first = err
				}
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if first != nil {
		return first
	}
	if keep != "" && strings.HasPrefix(strings.ToLower(keep), strings.ToLower(p)+string(os.PathSeparator)) {
		return nil // thư mục chứa file đang chạy: xoá sau khi thoát
	}
	delCount.Add(1)
	return retryRemoveAll(p)
}

func retryRemoveAll(p string) error {
	var err error
	for i := 0; i < 3; i++ { // file bị khoá: thử lại ít lần, phần còn lại sẽ xoá nốt sau khi thoát
		if err = os.RemoveAll(p); err == nil {
			return nil
		}
		time.Sleep(300 * time.Millisecond)
	}
	return err
}
