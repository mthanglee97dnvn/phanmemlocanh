//go:build windows

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

var (
	user32      = syscall.NewLazyDLL("user32.dll")
	kernel32    = syscall.NewLazyDLL("kernel32.dll")
	pMessageBox = user32.NewProc("MessageBoxW")
	pMutex      = kernel32.NewProc("CreateMutexW")
	pShellExec  = syscall.NewLazyDLL("shell32.dll").NewProc("ShellExecuteW")
)

func msgBox(title, text string) {
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	pMessageBox.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), 0x10)
}

func hideWindow(c *exec.Cmd) {
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000} // CREATE_NO_WINDOW
}

func openURL(u string) {
	verb, _ := syscall.UTF16PtrFromString("open")
	f, _ := syscall.UTF16PtrFromString(u)
	pShellExec.Call(0, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(f)), 0, 0, 1)
}

var mutexHandle uintptr

// acquireSingleton trả về false nếu một bộ khởi chạy khác đang chạy.
func acquireSingleton() bool {
	name, _ := syscall.UTF16PtrFromString("Local\\MThanglee_CullCollage_Launcher")
	h, _, err := pMutex.Call(0, 0, uintptr(unsafe.Pointer(name)))
	if h == 0 {
		return true
	}
	mutexHandle = h
	if errno, ok := err.(syscall.Errno); ok && errno == 183 { // ERROR_ALREADY_EXISTS
		return false
	}
	return true
}

func browserPath() string {
	var c []string
	for _, e := range []string{"ProgramFiles(x86)", "ProgramFiles", "LocalAppData"} {
		b := os.Getenv(e)
		if b == "" {
			continue
		}
		c = append(c, filepath.Join(b, "Microsoft", "Edge", "Application", "msedge.exe"),
			filepath.Join(b, "Google", "Chrome", "Application", "chrome.exe"))
	}
	for _, p := range c {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return ""
}

// openWindow mở giao diện trong một cửa sổ riêng (chế độ ứng dụng của Edge/Chrome: không thanh địa chỉ, không tab).
func openWindow(u, home string) *exec.Cmd {
	b := browserPath()
	if b == "" {
		openURL(u)
		return nil
	}
	prof := filepath.Join(home, "appwin")
	seedProfile(prof)
	cmd := exec.Command(b, "--app="+u, "--user-data-dir="+prof,
		"--no-first-run", "--no-default-browser-check", "--disable-sync", "--lang=vi",
		"--disable-features=Translate,TranslateUI,msEdgeSync,msImplicitSignin,msEdgeShoppingUI",
		"--window-size=1500,920")
	cmd.Dir = home // tránh để Edge giữ thư mục cài đặt làm thư mục hiện hành (sẽ cản việc gỡ cài đặt)
	if err := cmd.Start(); err != nil {
		openURL(u)
		return nil
	}
	return cmd
}

// seedProfile ghi sẵn cấu hình hồ sơ: tắt dịch trang, tắt đồng bộ/đăng nhập, bỏ trang chào mừng.
func seedProfile(prof string) {
	def := filepath.Join(prof, "Default")
	os.MkdirAll(def, 0o755)
	f := filepath.Join(def, "Preferences")
	mark := filepath.Join(prof, "seeded2")
	if _, err := os.Stat(mark); err == nil {
		return
	}
	os.WriteFile(mark, []byte("1"), 0o644)
	os.WriteFile(f, []byte(`{"translate":{"enabled":false},"translate_blocked_languages":["vi","en"],"browser":{"has_seen_welcome_page":true},"sync":{"requested":false,"suppress_start":true},"signin":{"allowed":false},"profile":{"password_manager_enabled":false}}`), 0o644)
}
