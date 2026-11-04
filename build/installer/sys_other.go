//go:build !windows

package main

import "os/exec"

// Bản giả cho Linux/macOS, chỉ để kiểm thử luồng cài đặt.
func setupConsole()                                     {}
func startDetached(exe string)                          {}
func createShortcuts(dir, target, icon string) []string { return []string{"(test) shortcut"} }
func reg(dir, launcher, icon, uninst string)            {}

func pickFolder() string { return "" }

func hideCmd(c *exec.Cmd)              {}
func openAppWindow(u string) *exec.Cmd { println("[gui]", u); return nil }
func killWindow(c *exec.Cmd)           {}

func cleanupProfile() {}

func hasDesktopLink(l []string) bool { return len(l) > 0 }
