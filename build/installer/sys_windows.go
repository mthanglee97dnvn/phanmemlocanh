//go:build windows

package main

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

func setupConsole() {
	syscall.NewLazyDLL("kernel32.dll").NewProc("SetConsoleOutputCP").Call(65001)
}

func startDetached(exe string) {
	cmd := exec.Command(exe)
	cmd.Dir = filepath.Dir(exe)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x00000008 | 0x00000200} // DETACHED_PROCESS | NEW_PROCESS_GROUP
	cmd.Start()
}

const lnkScript = `param([string]$Link,[string]$Target,[string]$Dir,[string]$Icon)
$s=(New-Object -ComObject WScript.Shell).CreateShortcut($Link)
$s.TargetPath=$Target; $s.WorkingDirectory=$Dir; $s.IconLocation=$Icon
$s.Description='MThanglee Cull&Collage'; $s.Save()`

func knownFolder(g syscall.GUID) string {
	var out *uint16
	hr, _, _ := syscall.NewLazyDLL("shell32.dll").NewProc("SHGetKnownFolderPath").Call(uintptr(unsafe.Pointer(&g)), 0, 0, uintptr(unsafe.Pointer(&out)))
	if hr != 0 || out == nil {
		return ""
	}
	defer syscall.NewLazyDLL("ole32.dll").NewProc("CoTaskMemFree").Call(uintptr(unsafe.Pointer(out)))
	return syscall.UTF16ToString((*[1 << 15]uint16)(unsafe.Pointer(out))[:])
}

var (
	guidDesktop  = syscall.GUID{Data1: 0xB4BFCC3A, Data2: 0xDB2C, Data3: 0x424C, Data4: [8]byte{0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41}}
	guidPrograms = syscall.GUID{Data1: 0xA77F5D77, Data2: 0x2E2B, Data3: 0x44C3, Data4: [8]byte{0xA6, 0xA2, 0xAB, 0xA6, 0x01, 0x05, 0x4A, 0x51}}
)

func desktopDir() string {
	if d := knownFolder(guidDesktop); d != "" {
		return d
	}
	return filepath.Join(os.Getenv("USERPROFILE"), "Desktop")
}

// makeLink tạo .lnk bằng PowerShell/WScript.Shell; nếu thất bại thì tạo .url (có icon) làm phương án dự phòng.
func makeLink(script, folder, dir, target, icon string) string {
	if folder == "" {
		return ""
	}
	os.MkdirAll(folder, 0o755)
	lnk := filepath.Join(folder, "MThanglee Cull&Collage.lnk")
	cmd := exec.Command("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
		"-Link", lnk, "-Target", target, "-Dir", dir, "-Icon", icon)
	hideCmd(cmd)
	cmd.Run()
	if _, err := os.Stat(lnk); err == nil {
		return lnk
	}
	url := filepath.Join(folder, "MThanglee Cull&Collage.url")
	body := "[InternetShortcut]\r\nURL=file:///" + strings.ReplaceAll(strings.ReplaceAll(target, "\\", "/"), " ", "%20") +
		"\r\nIconFile=" + icon + "\r\nIconIndex=0\r\n"
	if os.WriteFile(url, []byte(body), 0o644) == nil {
		return url
	}
	return ""
}

func createShortcuts(dir, target, icon string) []string {
	script := filepath.Join(dir, "mk_shortcut.ps1")
	os.WriteFile(script, append([]byte{0xEF, 0xBB, 0xBF}, []byte(lnkScript)...), 0o644)
	defer os.Remove(script)
	folders := []string{desktopDir(), knownFolder(guidPrograms)}
	res := make([]string, len(folders))
	var wg sync.WaitGroup
	for i, f := range folders {
		wg.Add(1)
		go func(i int, f string) {
			defer wg.Done()
			res[i] = makeLink(script, f, dir, target, icon)
		}(i, f)
	}
	wg.Wait()
	var links []string
	for _, l := range res {
		if l != "" {
			links = append(links, l)
			say("    lối tắt: %s", l)
		}
	}
	syscall.NewLazyDLL("shell32.dll").NewProc("SHChangeNotify").Call(0x08000000, 0, 0, 0) // làm mới Desktop
	return links
}

func hasDesktopLink(links []string) bool {
	d := strings.ToLower(desktopDir())
	for _, l := range links {
		if strings.HasPrefix(strings.ToLower(l), d) {
			return true
		}
	}
	return false
}

func reg(dir, launcher, icon, uninst string) {
	add := func(name, typ, val string) {
		c := exec.Command("reg", "add", regKey, "/v", name, "/t", typ, "/d", val, "/f")
		c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		c.Run()
	}
	add("DisplayName", "REG_SZ", appName)
	add("DisplayVersion", "REG_SZ", version)
	add("Publisher", "REG_SZ", "MTHANGLEE STUDIO")
	add("InstallLocation", "REG_SZ", dir)
	add("DisplayIcon", "REG_SZ", icon)
	add("UninstallString", "REG_SZ", `"`+uninst+`"`)
	add("QuietUninstallString", "REG_SZ", `"`+uninst+`"`)
	add("NoModify", "REG_DWORD", "1")
	add("NoRepair", "REG_DWORD", "1")
}

// pickFolder mở hộp thoại chọn thư mục của Windows (PowerShell + WinForms).
func pickFolder() string {
	script := `Add-Type -AssemblyName System.Windows.Forms
$f=New-Object System.Windows.Forms.FolderBrowserDialog
$f.Description='Chọn thư mục để cài MThanglee Cull&Collage (sẽ tạo thư mục con riêng)'
$f.ShowNewFolderButton=$true
$top=New-Object System.Windows.Forms.Form; $top.TopMost=$true
if($f.ShowDialog($top) -eq 'OK'){ [Console]::OutputEncoding=[Text.Encoding]::UTF8; Write-Output $f.SelectedPath }`
	cmd := exec.Command("powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script)
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func hideCmd(c *exec.Cmd) {
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
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
		cmd := exec.Command(b, "--app="+u, "--user-data-dir="+filepath.Join(os.TempDir(), "mthanglee_setup_profile"),
			"--no-first-run", "--no-default-browser-check", "--disable-sync", "--lang=vi",
			"--disable-features=Translate,TranslateUI,msEdgeSync,msImplicitSignin", "--window-size=760,640")
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
	// Edge/Chrome có thể giao cửa sổ cho tiến trình khác nên PID trên không còn giữ cửa sổ: tắt theo thư mục hồ sơ riêng.
	ctx, stop := context.WithTimeout(context.Background(), 5*time.Second)
	defer stop()
	p := exec.CommandContext(ctx, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
		`Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe'" | Where-Object { $_.CommandLine -like '*mthanglee_setup_profile*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`)
	hideCmd(p)
	p.Run()
}

func cleanupProfile() {
	c := exec.Command("cmd", "/c", "ping 127.0.0.1 -n 4 >nul & rmdir /s /q \""+filepath.Join(os.TempDir(), "mthanglee_setup_profile")+"\"")
	// Chỉ dùng CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP. Thêm DETACHED_PROCESS thì Windows bỏ qua cờ ẩn,
	// cmd không có console nên ping tự mở một cửa sổ riêng.
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000 | 0x00000200}
	c.Start()
}
