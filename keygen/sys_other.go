//go:build !windows

package main

import (
	"fmt"
	"time"
)

func msgBox(title, text string) { fmt.Println(title, text) }
func openWindow(url, dir string) {
	fmt.Println(url)
	time.Sleep(time.Hour)
}
