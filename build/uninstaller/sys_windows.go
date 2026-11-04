//go:build windows

package main

import (
	"encoding/base64"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"unicode/utf16"
	"unsafe"
)

func setupConsole() {
	syscall.NewLazyDLL("kernel32.dll").NewProc("SetConsoleOutputCP").Call(65001)
}

func startNewConsole(exe string, args ...string) {
	cmd := exec.Command(exe, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x00000008} // DETACHED_PROCESS
	cmd.Start()
}

func msgErr(text string) {
	t, _ := syscall.UTF16PtrFromString("MTHANGLEE PhotoSift")
	m, _ := syscall.UTF16PtrFromString(text)
	syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), 0x10)
}

func openAppWindow(u string) *exec.Cmd {
	var b string
	for _, e := range []string{"ProgramFiles(x86)", "ProgramFiles", "LocalAppData"} {
		base := os.Getenv(e)
		if base == "" {
			continue
		}
		for _, p := range []string{
			filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
			filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe")} {
			if _, err := os.Stat(p); err == nil && b == "" {
				b = p
			}
		}
	}
	if b != "" {
		cmd := exec.Command(b, "--app="+u, "--user-data-dir="+filepath.Join(os.TempDir(), "mthanglee_uninst_profile"),
			"--no-first-run", "--no-default-browser-check", "--disable-sync", "--lang=vi",
			"--disable-features=Translate,TranslateUI,msEdgeSync,msImplicitSignin", "--window-size=760,600")
		if cmd.Start() == nil {
			return cmd
		}
	}
	exec.Command("rundll32", "url.dll,FileProtocolHandler", u).Start()
	return nil
}

// killWindow đóng hẳn cửa sổ ứng dụng (cả cây tiến trình Edge/Chrome do mình mở).
func killWindow(c *exec.Cmd) {
	if c == nil || c.Process == nil {
		return
	}
	k := exec.Command("taskkill", "/F", "/T", "/PID", strconv.Itoa(c.Process.Pid))
	k.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	k.Run()
}

func removeReg() {
	c := exec.Command("reg", "delete", regKey, "/f")
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	c.Run()
}

func psQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

// selfDelete chạy một PowerShell ẩn, tách khỏi tiến trình này, để xoá nốt file gỡ cài đặt và thư mục cài đặt
// sau khi thoát (thử lại ~50 giây nếu file còn bị khoá), rồi xoá thư mục cha nếu rỗng.
func selfDelete() {
	exe, _ := os.Executable()
	tmpProf := filepath.Join(os.TempDir(), "mthanglee_uninst_profile")
	var sb strings.Builder
	sb.WriteString("$ErrorActionPreference='SilentlyContinue'\nStart-Sleep -Seconds 2\n")
	if cleanupDir != "" {
		parent := filepath.Dir(cleanupDir)
		sb.WriteString("$exe=" + psQuote(exe) + "; $dir=" + psQuote(cleanupDir) + "; $par=" + psQuote(parent) + "\n")
		sb.WriteString("for($i=0;$i -lt 25;$i++){ Remove-Item -LiteralPath $exe -Force; Remove-Item -LiteralPath $dir -Recurse -Force; if(-not (Test-Path -LiteralPath $dir)){break}; Start-Sleep -Seconds 2 }\n")
		cond := "$false"
		if cleanupParent {
			cond = "$true"
		}
		sb.WriteString("if(((" + cond + ") -or ((Split-Path $par -Leaf) -like 'MTHANGLEE*')) -and (Test-Path -LiteralPath $par) -and (Split-Path $par -Parent) -and -not (Get-ChildItem -LiteralPath $par -Force)){ Remove-Item -LiteralPath $par -Force }\n")
	}
	sb.WriteString("Remove-Item -LiteralPath " + psQuote(tmpProf) + " -Recurse -Force\n")
	u16 := utf16.Encode([]rune(sb.String()))
	raw := make([]byte, 0, len(u16)*2)
	for _, c := range u16 {
		raw = append(raw, byte(c), byte(c>>8))
	}
	enc := base64.StdEncoding.EncodeToString(raw)
	start := func(flags uint32) error {
		c := exec.Command("powershell", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc)
		c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: flags}
		return c.Start()
	}
	// CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB (thoát khỏi job của trình gọi); nếu bị từ chối thì bỏ cờ breakaway
	if start(0x08000000|0x00000200|0x01000000) != nil {
		start(0x08000000 | 0x00000200)
	}
}

// killLeftovers tắt mọi tiến trình còn chạy từ thư mục cài đặt và cửa sổ ứng dụng (Edge hồ sơ PhotoSift).
func killLeftovers(dir, home string) {
	script := `$d=$env:PS_DIR; $h=$env:PS_HOME; $me=[int]$env:PS_SELF
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessId -ne $me -and $_.ProcessId -ne $PID -and (($_.ExecutablePath -and $_.ExecutablePath.StartsWith($d,[StringComparison]::OrdinalIgnoreCase)) -or ($_.CommandLine -and ($_.CommandLine.Contains($h) -or $_.CommandLine.Contains($d)))) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`
	c := exec.Command("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script)
	c.Env = append(os.Environ(), "PS_DIR="+dir, "PS_HOME="+home, "PS_SELF="+strconv.Itoa(os.Getpid()))
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	c.Run()
}

func knownFolder(g syscall.GUID) string {
	var out *uint16
	hr, _, _ := syscall.NewLazyDLL("shell32.dll").NewProc("SHGetKnownFolderPath").Call(uintptr(unsafe.Pointer(&g)), 0, 0, uintptr(unsafe.Pointer(&out)))
	if hr != 0 || out == nil {
		return ""
	}
	defer syscall.NewLazyDLL("ole32.dll").NewProc("CoTaskMemFree").Call(uintptr(unsafe.Pointer(out)))
	return syscall.UTF16ToString((*[1 << 15]uint16)(unsafe.Pointer(out))[:])
}

func removeShortcutsByName() {
	for _, g := range []syscall.GUID{
		{Data1: 0xB4BFCC3A, Data2: 0xDB2C, Data3: 0x424C, Data4: [8]byte{0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41}},
		{Data1: 0xA77F5D77, Data2: 0x2E2B, Data3: 0x44C3, Data4: [8]byte{0xA6, 0xA2, 0xAB, 0xA6, 0x01, 0x05, 0x4A, 0x51}}} {
		if d := knownFolder(g); d != "" {
			os.Remove(filepath.Join(d, "MTHANGLEE PhotoSift.lnk"))
			os.Remove(filepath.Join(d, "MTHANGLEE PhotoSift.url"))
		}
	}
	syscall.NewLazyDLL("shell32.dll").NewProc("SHChangeNotify").Call(0x08000000, 0, 0, 0)
}
