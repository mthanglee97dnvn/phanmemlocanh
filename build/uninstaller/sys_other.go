//go:build !windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

// Bản giả cho Linux/macOS, chỉ để kiểm thử logic.
func setupConsole() {}
func startNewConsole(exe string, args ...string) {
	c := exec.Command(exe, args...)
	c.Stdin, c.Stdout, c.Stderr = os.Stdin, os.Stdout, os.Stderr
	c.Run()
}
func removeReg() {}
func selfDelete() {
	if cleanupDir != "" {
		os.RemoveAll(cleanupDir)
		if cleanupParent {
			os.Remove(filepath.Dir(cleanupDir))
		}
	}
}

func killLeftovers(dir, home string) {}
func removeShortcutsByName()         {}

func msgErr(t string)                  { fmt.Println(t) }
func openAppWindow(u string) *exec.Cmd { println("[gui]", u); return nil }
func killWindow(c *exec.Cmd)           {}
