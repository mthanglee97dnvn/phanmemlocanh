//go:build !windows

package main

import (
	"fmt"
	"os/exec"
)

// Bản giả cho Linux/macOS, chỉ để kiểm thử logic.
func msgBox(title, text string)           { fmt.Println("[msgbox]", title, "-", text) }
func hideWindow(c *exec.Cmd)              {}
func openURL(u string)                    { fmt.Println("[open]", u) }
func openWindow(u, home string) *exec.Cmd { fmt.Println("[window]", u); return nil }
func acquireSingleton() bool              { return true }
