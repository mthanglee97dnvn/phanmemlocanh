// MTHANGLEE PhotoSift - bộ cài đặt (Windows 10/11 64-bit, cài theo từng người dùng, không cần quyền Admin).
package main

import (
	"archive/zip"
	"bufio"
	"bytes"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

//go:embed payload/app.zip
var appZip []byte

//go:embed payload/launcher.exe
var launcherExe []byte

//go:embed payload/uninstall.exe
var uninstallExe []byte

//go:embed payload/icon.ico
var iconIco []byte

const (
	appName   = "MTHANGLEE PhotoSift"
	version   = "1.0.0"
	regKey    = `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MTHANGLEEPhotoSift`
	pyURL     = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip"
	getPipURL = "https://bootstrap.pypa.io/get-pip.py"
	lbfURL    = "https://raw.githubusercontent.com/kurnianggoro/GSOC2017/master/data/lbfmodel.yaml"
)

var reader = bufio.NewReader(os.Stdin)

var logf = func(s string) { fmt.Println(s) }

func zipHas(data []byte, name string) bool {
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return false
	}
	for _, f := range zr.File {
		if f.Name == name {
			return true
		}
	}
	return false
}

func say(f string, a ...any) { logf(fmt.Sprintf(f, a...)) }

// failHook: ở chế độ đồ hoạ, báo lỗi lên cửa sổ rồi dừng luồng cài đặt.
var failHook func(error)

func fail(err error) {
	if failHook != nil {
		failHook(err)
		runtime.Goexit()
	}
	say("")
	say("*** Cài đặt thất bại: %v", err)
	say("    Kiểm tra kết nối Internet, tạm tắt phần mềm diệt virus rồi chạy lại file cài đặt.")
	say("    Nếu vẫn lỗi, chụp màn hình này gửi cho người hỗ trợ.")
	pause()
	os.Exit(1)
}

func pause() {
	fmt.Print("\nNhấn Enter để đóng…")
	reader.ReadString('\n')
}

func defaultDir() string {
	if d := os.Getenv("LOCALAPPDATA"); d != "" {
		return filepath.Join(d, "MTHANGLEE PhotoSift")
	}
	h, _ := os.UserHomeDir()
	return filepath.Join(h, "MTHANGLEE PhotoSift")
}

func dataHome() string {
	if h := os.Getenv("PHOTOSIFT_HOME"); h != "" {
		return h
	}
	h, _ := os.UserHomeDir()
	return filepath.Join(h, ".photosift")
}

func extractZip(data []byte, dest string) error {
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return err
	}
	base := filepath.Clean(dest) + string(os.PathSeparator)
	for _, f := range zr.File {
		p := filepath.Join(dest, f.Name)
		if !strings.HasPrefix(p, base) { // chặn zip-slip
			return fmt.Errorf("đường dẫn không hợp lệ trong gói: %s", f.Name)
		}
		if f.FileInfo().IsDir() {
			os.MkdirAll(p, 0o755)
			continue
		}
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			return err
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		out, err := os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, f.Mode().Perm()|0o600)
		if err != nil {
			rc.Close()
			return err
		}
		_, err = io.Copy(out, rc)
		rc.Close()
		out.Close()
		if err != nil {
			return err
		}
	}
	return nil
}

var dlDone, dlTotal atomic.Int64 // tổng tiến độ các file tải song song (không tính model tuỳ chọn)

func download(url, dest string, minSize int64, count bool) error {
	var last error
	for try := 1; try <= 3; try++ {
		last = downloadOnce(url, dest, minSize, count)
		if last == nil {
			return nil
		}
		say("    (lần %d lỗi: %v) thử lại…", try, last)
		time.Sleep(2 * time.Second)
	}
	return last
}

func downloadOnce(url, dest string, minSize int64, count bool) error {
	c := http.Client{Timeout: 15 * time.Minute}
	resp, err := c.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("máy chủ trả về %s", resp.Status)
	}
	if count && resp.ContentLength > 0 {
		dlTotal.Add(resp.ContentLength)
	}
	tmp := dest + ".part"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	var done int64
	buf := make([]byte, 128*1024)
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			f.Write(buf[:n])
			done += int64(n)
			if count {
				dlDone.Add(int64(n))
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			f.Close()
			return rerr
		}
	}
	f.Close()
	if done < minSize {
		return fmt.Errorf("file tải về quá nhỏ (%d byte)", done)
	}
	return os.Rename(tmp, dest)
}

// pypiWheel tìm file wheel Windows 64-bit cho Python 3.12 của gói trên PyPI (bản mới nhất).
func pypiWheel(name string) (string, string, error) {
	c := http.Client{Timeout: 30 * time.Second}
	resp, err := c.Get("https://pypi.org/pypi/" + name + "/json")
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", "", fmt.Errorf("PyPI trả về %s cho %s", resp.Status, name)
	}
	var j struct {
		Urls []struct{ Filename, Url string } `json:"urls"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&j); err != nil {
		return "", "", err
	}
	best, bestScore := -1, -1
	for i, u := range j.Urls {
		f := u.Filename
		if !strings.HasSuffix(f, "win_amd64.whl") {
			continue
		}
		score := 0
		switch {
		case strings.Contains(f, "-cp312-cp312-"):
			score = 3
		case strings.Contains(f, "-abi3-"):
			score = 2
		case strings.Contains(f, "-py3-none-"):
			score = 1
		}
		if score > bestScore {
			best, bestScore = i, score
		}
	}
	if best < 0 || bestScore <= 0 {
		return "", "", fmt.Errorf("không có bản wheel phù hợp cho %s", name)
	}
	return j.Urls[best].Filename, j.Urls[best].Url, nil
}

func run(dir string, name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PIP_DISABLE_PIP_VERSION_CHECK=1")
	hideCmd(cmd)
	pr, pw := io.Pipe()
	cmd.Stdout, cmd.Stderr = pw, pw
	done := make(chan struct{})
	go func() {
		defer close(done)
		sc := bufio.NewScanner(pr)
		sc.Buffer(make([]byte, 1<<20), 1<<20)
		sc.Split(func(data []byte, atEOF bool) (int, []byte, error) { // tách dòng theo \n hoặc \r
			for i, b := range data {
				if b == '\n' || b == '\r' {
					return i + 1, data[:i], nil
				}
			}
			if atEOF && len(data) > 0 {
				return len(data), data, nil
			}
			return 0, nil, nil
		})
		for sc.Scan() {
			if t := strings.TrimSpace(sc.Text()); t != "" {
				say("    %s", t)
			}
		}
	}()
	err := cmd.Run()
	pw.Close()
	<-done
	return err
}

// stopRunning yêu cầu phiên PhotoSift đang chạy (nếu có) tự thoát để thay file.
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
		time.Sleep(1500 * time.Millisecond)
	}
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// chooseDir cho người dùng chọn nơi cài. Luôn cài vào một thư mục con riêng «MTHANGLEE PhotoSift»
// để việc gỡ cài đặt chỉ xoá đúng thư mục của phần mềm, không bao giờ đụng tới thư mục khác.
func chooseDir(def string) string {
	for {
		say("Nơi cài đặt mặc định:\n    %s\n", def)
		fmt.Print("  [Enter] Cài vào đây    [C] Chọn thư mục khác (hộp thoại)    hoặc gõ đường dẫn: ")
		ans, _ := reader.ReadString('\n')
		ans = strings.Trim(strings.TrimSpace(ans), `"`)
		var base string
		switch {
		case ans == "":
			return def
		case strings.EqualFold(ans, "c"):
			base = pickFolder()
			if base == "" {
				say("  (chưa chọn thư mục)\n")
				continue
			}
		default:
			base = ans
		}
		if !filepath.IsAbs(base) {
			say("  Đường dẫn không hợp lệ, hãy nhập đường dẫn đầy đủ (vd D:\\Phan mem).\n")
			continue
		}
		d := filepath.Clean(base)
		if !strings.EqualFold(filepath.Base(d), "MTHANGLEE PhotoSift") {
			d = filepath.Join(d, "MTHANGLEE PhotoSift")
		}
		say("\n  Sẽ cài vào: %s", d)
		fmt.Print("  Đồng ý? [Enter = đồng ý, n = chọn lại]: ")
		a, _ := reader.ReadString('\n')
		if strings.HasPrefix(strings.ToLower(strings.TrimSpace(a)), "n") {
			continue
		}
		return d
	}
}

// runInstall chạy toàn bộ các bước cài vào dir, trả về đường dẫn file khởi chạy.
// Các file lớn (Python, thư viện, model) được tải SONG SONG để cài nhanh hơn.
func runInstall(dir string) string {
	parentCreated := false
	if _, err := os.Stat(filepath.Dir(dir)); err != nil {
		parentCreated = true
	}
	stopRunning()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		fail(err)
	}
	pyDir := filepath.Join(dir, "python")
	pyExe := filepath.Join(pyDir, "python.exe")
	ready := filepath.Join(pyDir, "ready.txt")
	whl := filepath.Join(dir, "wheelhouse")
	modelsDir := filepath.Join(dir, "models")
	os.MkdirAll(modelsDir, 0o755)
	os.Remove(filepath.Join(modelsDir, "lbfmodel.yaml.skip"))

	_, haveReady := os.Stat(ready)
	bundled := zipHas(appZip, "core/PhotoSiftCore.exe") // gói đã chứa sẵn mọi thứ: không cần Python
	needPy := haveReady != nil && !bundled

	// ---- Bước 1: chép ứng dụng + tải song song
	stage(1, "Chép ứng dụng và tải thành phần (song song)")
	dlDone.Store(0)
	dlTotal.Store(0)
	var wg sync.WaitGroup
	var errMu sync.Mutex
	var firstErr error
	setErr := func(e error) {
		errMu.Lock()
		if firstErr == nil {
			firstErr = e
		}
		errMu.Unlock()
	}
	var optional sync.WaitGroup
	stopTick := make(chan struct{})
	go func() {
		for {
			select {
			case <-stopTick:
				return
			case <-time.After(300 * time.Millisecond):
				if t := dlTotal.Load(); t > 0 {
					setSub(int(dlDone.Load() * 100 / t))
				}
			}
		}
	}()

	// model nhắm mắt (tuỳ chọn, file lớn): tải nền, không chặn bước khác
	lbf := filepath.Join(modelsDir, "lbfmodel.yaml")
	if st, err := os.Stat(lbf); (err != nil || st.Size() < 10_000) && !bundled {
		optional.Add(1)
		go func() {
			defer optional.Done()
			if err := download(env("PS_LBF_URL", lbfURL), lbf, 10_000, false); err != nil {
				say("    (chưa tải được model nhắm mắt: %v — ứng dụng sẽ tự thử lại khi có mạng)", err)
			}
		}()
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := extractZip(appZip, dir); err != nil {
			setErr(err)
		}
		os.Remove(filepath.Join(modelsDir, "lbfmodel.yaml.skip"))
	}()
	pyZip, getPip := filepath.Join(dir, "py.zip"), filepath.Join(dir, "get-pip.py")
	wheelFiles := []string{}
	var wfMu sync.Mutex
	if needPy {
		os.RemoveAll(pyDir)
		os.MkdirAll(pyDir, 0o755)
		os.MkdirAll(whl, 0o755)
		wg.Add(2)
		go func() {
			defer wg.Done()
			if err := download(env("PS_PYTHON_URL", pyURL), pyZip, 1<<20, true); err != nil {
				setErr(err)
			}
		}()
		go func() {
			defer wg.Done()
			if err := download(env("PS_GETPIP_URL", getPipURL), getPip, 1000, true); err != nil {
				setErr(err)
			}
		}()
		for _, pkg := range []string{"numpy", "pillow", "opencv-contrib-python", "rawpy", "pillow-heif"} {
			pkg := pkg
			wg.Add(1)
			go func() {
				defer wg.Done()
				if os.Getenv("PS_NO_WHEELS") != "" {
					return
				}
				name, url, err := pypiWheel(pkg)
				if err == nil {
					p := filepath.Join(whl, name)
					if err = download(url, p, 1000, true); err == nil {
						wfMu.Lock()
						wheelFiles = append(wheelFiles, p)
						wfMu.Unlock()
					}
				}
				if err != nil {
					say("    (không tải trước được %s: %v — sẽ cài trực tiếp bằng pip)", pkg, err)
				}
			}()
		}
	}
	wg.Wait()
	close(stopTick)
	if firstErr != nil {
		fail(firstErr)
	}

	// ---- Bước 2: Python + thư viện
	if bundled {
		stage(2, "Đã có sẵn mọi thành phần — không cần tải")
		os.RemoveAll(pyDir) // dọn Python của bản cài cũ (nếu có)
	} else if needPy {
		stage(2, "Cài Python và thư viện xử lý ảnh")
		data, err := os.ReadFile(pyZip)
		if err != nil {
			fail(err)
		}
		if err := extractZip(data, pyDir); err != nil {
			fail(err)
		}
		os.Remove(pyZip)
		if _, err := os.Stat(pyExe); err != nil {
			fail(errors.New("không giải nén được Python"))
		}
		pth := "python312.zip\r\n.\r\n..\r\nimport site\r\n"
		if err := os.WriteFile(filepath.Join(pyDir, "python312._pth"), []byte(pth), 0o644); err != nil {
			fail(err)
		}
		// get-pip có sẵn pip bên trong: bỏ setuptools/wheel để khỏi phải tải thêm
		if err := run(dir, pyExe, getPip, "--no-warn-script-location", "--no-setuptools", "--no-wheel"); err != nil {
			fail(fmt.Errorf("cài pip: %w", err))
		}
		os.Remove(getPip)
	} else {
		stage(2, "Python đã có — kiểm tra thư viện")
	}
	libsOK := func() bool {
		return bundled || run(dir, pyExe, "-c", "import cv2, numpy, PIL") == nil
	}
	if !bundled && (needPy || !libsOK()) {
		ok := false
		if len(wheelFiles) >= 3 { // cài từ file đã tải sẵn (không cần tải lại)
			args := []string{"-m", "pip", "install", "--no-warn-script-location", "--no-index", "--find-links", whl, "numpy", "pillow", "opencv-contrib-python"}
			ok = run(dir, pyExe, args...) == nil && libsOK()
		}
		if !ok {
			say("    Cài trực tiếp từ Internet…")
			if err := run(dir, pyExe, "-m", "pip", "install", "--no-warn-script-location", "-r", "requirements.txt"); err != nil {
				fail(fmt.Errorf("cài thư viện: %w", err))
			}
		}
		say("    Cài thêm hỗ trợ ảnh RAW và HEIC (nếu lỗi thì bỏ qua)…")
		extra := []string{"-m", "pip", "install", "--no-warn-script-location", "--find-links", whl, "rawpy", "pillow-heif"}
		if run(dir, pyExe, extra...) != nil {
			say("    (bỏ qua — vẫn đọc được ARW qua ảnh xem trước nhúng)")
		}
	}
	os.RemoveAll(whl)
	if !libsOK() {
		fail(errors.New("thư viện xử lý ảnh chưa dùng được sau khi cài"))
	}

	// ---- Bước 3: model
	stage(3, "Hoàn tất model nhận diện")
	done := make(chan struct{})
	go func() { optional.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(120 * time.Second):
		say("    (model nhắm mắt chưa tải xong — ứng dụng sẽ tự bổ sung khi có mạng)")
	}
	if !bundled {
		if err := os.WriteFile(ready, []byte("ok"), 0o644); err != nil {
			fail(err)
		}
	}

	// ---- Bước 4: lối tắt
	stage(4, "Tạo lối tắt Desktop, Start Menu và đăng ký gỡ cài đặt")
	launcher := filepath.Join(dir, "MTHANGLEE PhotoSift.exe")
	icon := filepath.Join(dir, "photosift.ico")
	uninst := filepath.Join(dir, "Uninstall.exe")
	for p, b := range map[string][]byte{launcher: launcherExe, icon: iconIco, uninst: uninstallExe} {
		if err := os.WriteFile(p, b, 0o755); err != nil {
			fail(err)
		}
	}
	links := createShortcuts(dir, launcher, icon)
	reg(dir, launcher, icon, uninst)
	meta, _ := json.Marshal(map[string]any{"version": version, "links": links, "parent_created": parentCreated})
	os.WriteFile(filepath.Join(dir, "install.json"), meta, 0o644)
	if !hasDesktopLink(links) {
		say("    ! Không tạo được lối tắt ở Desktop. Mở ứng dụng từ: %s", launcher)
		gs.mu.Lock()
		gs.Warn = "Không tạo được lối tắt ở Desktop. Hãy mở ứng dụng từ: " + launcher
		gs.mu.Unlock()
	}
	return launcher
}

func main() {
	setupConsole()
	dir := defaultDir()
	cli := false
	for i, a := range os.Args {
		if a == "--silent" || a == "--console" {
			cli = true
		}
		if a == "--dir" && i+1 < len(os.Args) {
			dir = os.Args[i+1]
			cli = true
		}
	}
	if !cli {
		guiMain()
		return
	}
	unattended := false
	for _, a := range os.Args {
		if a == "--silent" {
			unattended = true
		}
	}
	say("============================================================")
	say("  %s — Bộ cài đặt %s", appName, version)
	say("============================================================")
	say("Thư mục cài đặt: %s\n", dir)
	launcher := runInstall(dir)
	say("\nCài đặt xong!")
	if !unattended {
		fmt.Print("\nMở PhotoSift ngay bây giờ? [Enter = có, n = không]: ")
		ans, _ := reader.ReadString('\n')
		if !strings.HasPrefix(strings.ToLower(strings.TrimSpace(ans)), "n") {
			startDetached(launcher)
		}
	}
}
