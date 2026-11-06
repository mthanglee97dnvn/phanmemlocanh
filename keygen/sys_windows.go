//go:build windows

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

func msgBox(title, text string) {
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), 0x10)
}

func browser() string {
	for _, e := range []string{"ProgramFiles(x86)", "ProgramFiles", "LocalAppData"} {
		b := os.Getenv(e)
		if b == "" {
			continue
		}
		for _, p := range []string{filepath.Join(b, "Microsoft", "Edge", "Application", "msedge.exe"), filepath.Join(b, "Google", "Chrome", "Application", "chrome.exe")} {
			if _, err := os.Stat(p); err == nil {
				return p
			}
		}
	}
	return ""
}

// openWindow mở cửa sổ riêng và giữ app chạy tới khi đóng cửa sổ.
func openWindow(url, dir string) {
	b := browser()
	if b == "" {
		msgBox("MThanglee KeyGen", "Cần Microsoft Edge hoặc Google Chrome để mở giao diện.")
		return
	}
	prof := filepath.Join(dir, "window")
	cmd := exec.Command(b, "--app="+url, "--user-data-dir="+prof, "--no-first-run", "--no-default-browser-check", "--window-size=1040,760")
	if err := cmd.Start(); err != nil {
		msgBox("MThanglee KeyGen", "Không mở được cửa sổ: "+err.Error())
		return
	}
	cmd.Wait()
}
