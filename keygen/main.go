// MThanglee KeyGen - app riêng của chủ sở hữu để tạo key cho MThanglee Cull&Collage.
// Khóa bí mật được sinh ngay trên máy này, mã hóa bằng mật khẩu và không bao giờ gửi đi đâu.
package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ed25519"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base32"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const iterations = 600000

var epoch = time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

type vault struct {
	App   string `json:"app"`
	Pub   string `json:"pub"`
	Salt  string `json:"salt"`
	Nonce string `json:"nonce"`
	Data  string `json:"data"`
	Iter  int    `json:"iter"`
}

type issued struct {
	Time    string `json:"time"`
	Name    string `json:"name"`
	Machine string `json:"machine"`
	Expires string `json:"expires"`
	Note    string `json:"note"`
	Key     string `json:"key"`
}

type app struct {
	mu      sync.Mutex
	dir     string
	priv    ed25519.PrivateKey
	token   string
	port    int
	lastTry time.Time
	fails   int
}

func dataDir() string {
	if d := os.Getenv("MTCC_KEYGEN_HOME"); d != "" {
		return d
	}
	d, err := os.UserConfigDir()
	if err != nil {
		d, _ = os.UserHomeDir()
	}
	return filepath.Join(d, "MThanglee KeyGen")
}

func (a *app) vaultPath() string   { return filepath.Join(a.dir, "vault.json") }
func (a *app) historyPath() string { return filepath.Join(a.dir, "history.json") }

func readVault(p string) (*vault, error) {
	b, err := os.ReadFile(p)
	if err != nil {
		return nil, err
	}
	var v vault
	if err := json.Unmarshal(b, &v); err != nil {
		return nil, err
	}
	return &v, nil
}

func writeAtomic(p string, b []byte) error {
	t := p + ".tmp"
	if err := os.WriteFile(t, b, 0o600); err != nil {
		return err
	}
	return os.Rename(t, p)
}

func kdf(pass string, salt []byte, iter int) ([]byte, error) {
	return pbkdf2.Key(sha256.New, pass, salt, iter, 32)
}

func seal(seed []byte, pass string) (*vault, error) {
	salt, nonce := make([]byte, 16), make([]byte, 12)
	rand.Read(salt)
	rand.Read(nonce)
	k, err := kdf(pass, salt, iterations)
	if err != nil {
		return nil, err
	}
	blk, _ := aes.NewCipher(k)
	g, _ := cipher.NewGCM(blk)
	pub := ed25519.NewKeyFromSeed(seed).Public().(ed25519.PublicKey)
	return &vault{App: "MTCC-KeyGen", Pub: hex.EncodeToString(pub), Salt: hex.EncodeToString(salt), Nonce: hex.EncodeToString(nonce),
		Data: hex.EncodeToString(g.Seal(nil, nonce, seed, nil)), Iter: iterations}, nil
}

func open(v *vault, pass string) (ed25519.PrivateKey, error) {
	salt, e1 := hex.DecodeString(v.Salt)
	nonce, e2 := hex.DecodeString(v.Nonce)
	data, e3 := hex.DecodeString(v.Data)
	if e1 != nil || e2 != nil || e3 != nil || len(nonce) != 12 || v.Iter < 1000 {
		return nil, errors.New("File khóa bị hỏng.")
	}
	k, err := kdf(pass, salt, v.Iter)
	if err != nil {
		return nil, err
	}
	blk, _ := aes.NewCipher(k)
	g, _ := cipher.NewGCM(blk)
	seed, err := g.Open(nil, nonce, data, nil)
	if err != nil || len(seed) != ed25519.SeedSize {
		return nil, errors.New("Mật khẩu chưa đúng.")
	}
	return ed25519.NewKeyFromSeed(seed), nil
}

var machRe = regexp.MustCompile(`^[A-Z2-7]{13}$`)

func parseMachine(s string) ([]byte, error) {
	t := strings.ToUpper(strings.NewReplacer("-", "", " ", "").Replace(s))
	if !machRe.MatchString(t) {
		return nil, errors.New("Mã máy chưa đúng. Mã có dạng ABCD-EFGH-IJKLM.")
	}
	b, err := base32.StdEncoding.WithPadding(base32.NoPadding).DecodeString(t)
	if err != nil || len(b) != 8 {
		return nil, errors.New("Mã máy chưa đúng. Mã có dạng ABCD-EFGH-IJKLM.")
	}
	return b, nil
}

func dayNum(t time.Time) int {
	d := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	return int(d.Sub(epoch).Hours() / 24)
}

func makeKey(priv ed25519.PrivateKey, machine []byte, days, serial int) (string, string) {
	body := make([]byte, 14)
	body[0] = 1
	body[1] = byte(serial) // key mọi máy tạo cùng ngày khác nhau nhờ số thứ tự
	now := dayNum(time.Now())
	binary.BigEndian.PutUint16(body[2:], uint16(now))
	exp, label := 0xFFFF, "Vĩnh viễn"
	if days > 0 {
		exp = now + days
		label = epoch.AddDate(0, 0, exp).Format("02/01/2006")
	}
	binary.BigEndian.PutUint16(body[4:], uint16(exp))
	copy(body[6:], machine)
	sig := ed25519.Sign(priv, append([]byte("MTCC1"), body...))
	t := base32.StdEncoding.WithPadding(base32.NoPadding).EncodeToString(append(body, sig...))
	var g []string
	for i := 0; i < len(t); i += 5 {
		e := i + 5
		if e > len(t) {
			e = len(t)
		}
		g = append(g, t[i:e])
	}
	return "MTCC-" + strings.Join(g, "-"), label
}

func (a *app) history() []issued {
	var h []issued
	if b, err := os.ReadFile(a.historyPath()); err == nil {
		json.Unmarshal(b, &h)
	}
	return h
}

func jsonOut(w http.ResponseWriter, code int, v any) {
	b, _ := json.Marshal(v)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(code)
	w.Write(b)
}

func fail(w http.ResponseWriter, msg string) { jsonOut(w, 400, map[string]string{"error": msg}) }

func (a *app) authed(r *http.Request) bool {
	if r.Host != fmt.Sprintf("127.0.0.1:%d", a.port) {
		return false
	}
	c, err := r.Cookie("kg")
	return err == nil && subtle.ConstantTimeCompare([]byte(c.Value), []byte(a.token)) == 1
}

func (a *app) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.Host != fmt.Sprintf("127.0.0.1:%d", a.port) || r.URL.Path != "/" {
			http.Error(w, "forbidden", 403)
			return
		}
		if r.URL.Query().Get("t") == a.token {
			http.SetCookie(w, &http.Cookie{Name: "kg", Value: a.token, HttpOnly: true, SameSite: http.SameSiteStrictMode, Path: "/"})
			http.Redirect(w, r, "/", http.StatusFound)
			return
		}
		if !a.authed(r) {
			http.Error(w, "forbidden", 403)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		w.Write([]byte(page))
	})
	api := func(path string, fn func(http.ResponseWriter, *http.Request)) {
		mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) {
			if !a.authed(r) {
				http.Error(w, "forbidden", 403)
				return
			}
			if r.Method == "POST" && strings.Split(r.Header.Get("Content-Type"), ";")[0] != "application/json" {
				http.Error(w, "forbidden", 403)
				return
			}
			a.mu.Lock()
			defer a.mu.Unlock()
			fn(w, r)
		})
	}
	api("/api/state", func(w http.ResponseWriter, r *http.Request) {
		v, err := readVault(a.vaultPath())
		pub := ""
		if err == nil {
			pub = v.Pub
		}
		jsonOut(w, 200, map[string]any{"setup": err == nil, "unlocked": a.priv != nil, "pub": pub, "count": len(a.history())})
	})
	type passBody struct {
		Password string `json:"password"`
		Backup   string `json:"backup"`
	}
	read := func(r *http.Request, v any) error {
		return json.NewDecoder(http.MaxBytesReader(nil, r.Body, 1<<20)).Decode(v)
	}
	api("/api/setup", func(w http.ResponseWriter, r *http.Request) {
		var b passBody
		if read(r, &b) != nil || len(b.Password) < 8 {
			fail(w, "Mật khẩu cần ít nhất 8 ký tự.")
			return
		}
		if _, err := os.Stat(a.vaultPath()); err == nil {
			fail(w, "Máy này đã có bộ khóa.")
			return
		}
		seed := make([]byte, ed25519.SeedSize)
		rand.Read(seed)
		v, err := seal(seed, b.Password)
		if err != nil {
			fail(w, err.Error())
			return
		}
		j, _ := json.MarshalIndent(v, "", " ")
		os.MkdirAll(a.dir, 0o700)
		if err := writeAtomic(a.vaultPath(), j); err != nil {
			fail(w, "Không ghi được file khóa: "+err.Error())
			return
		}
		a.priv = ed25519.NewKeyFromSeed(seed)
		jsonOut(w, 200, map[string]any{"ok": true, "pub": v.Pub})
	})
	api("/api/unlock", func(w http.ResponseWriter, r *http.Request) {
		var b passBody
		if read(r, &b) != nil {
			fail(w, "Thiếu mật khẩu.")
			return
		}
		if a.fails >= 3 && time.Since(a.lastTry) < time.Duration(a.fails)*2*time.Second {
			fail(w, "Sai nhiều lần. Hãy đợi vài giây rồi thử lại.")
			return
		}
		v, err := readVault(a.vaultPath())
		if err != nil {
			fail(w, "Chưa có bộ khóa trên máy này.")
			return
		}
		p, err := open(v, b.Password)
		a.lastTry = time.Now()
		if err != nil {
			a.fails++
			fail(w, err.Error())
			return
		}
		a.fails, a.priv = 0, p
		jsonOut(w, 200, map[string]any{"ok": true})
	})
	api("/api/lock", func(w http.ResponseWriter, r *http.Request) {
		a.priv = nil
		jsonOut(w, 200, map[string]any{"ok": true})
	})
	api("/api/restore", func(w http.ResponseWriter, r *http.Request) {
		var b passBody
		if read(r, &b) != nil {
			fail(w, "Không đọc được file sao lưu.")
			return
		}
		if _, err := os.Stat(a.vaultPath()); err == nil {
			fail(w, "Máy này đã có bộ khóa, không ghi đè.")
			return
		}
		var v vault
		if json.Unmarshal([]byte(b.Backup), &v) != nil || v.App != "MTCC-KeyGen" {
			fail(w, "File này không phải bản sao lưu khóa.")
			return
		}
		p, err := open(&v, b.Password)
		if err != nil {
			fail(w, err.Error())
			return
		}
		os.MkdirAll(a.dir, 0o700)
		j, _ := json.MarshalIndent(v, "", " ")
		if err := writeAtomic(a.vaultPath(), j); err != nil {
			fail(w, "Không ghi được file khóa: "+err.Error())
			return
		}
		a.priv = p
		jsonOut(w, 200, map[string]any{"ok": true, "pub": v.Pub})
	})
	api("/api/backup", func(w http.ResponseWriter, r *http.Request) {
		b, err := os.ReadFile(a.vaultPath())
		if err != nil {
			http.Error(w, "missing", 404)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Content-Disposition", `attachment; filename="MThanglee_KeyGen_sao_luu_khoa.json"`)
		w.Write(b)
	})
	api("/api/issue", func(w http.ResponseWriter, r *http.Request) {
		var b struct {
			Name    string `json:"name"`
			Machine string `json:"machine"`
			Any     bool   `json:"any"`
			Days    int    `json:"days"`
			Qty     int    `json:"qty"`
			Note    string `json:"note"`
		}
		if a.priv == nil {
			fail(w, "Hãy mở khóa bằng mật khẩu trước.")
			return
		}
		if read(r, &b) != nil {
			fail(w, "Dữ liệu chưa đúng.")
			return
		}
		mach := make([]byte, 8)
		label := "Mọi máy"
		if !b.Any {
			m, err := parseMachine(b.Machine)
			if err != nil {
				fail(w, err.Error())
				return
			}
			mach, label = m, strings.ToUpper(strings.TrimSpace(b.Machine))
			b.Qty = 1
		}
		if b.Days < 0 || b.Days > 18000 {
			fail(w, "Thời hạn chưa đúng.")
			return
		}
		if b.Qty < 1 {
			b.Qty = 1
		}
		if b.Qty > 200 {
			fail(w, "Mỗi lần tạo tối đa 200 key.")
			return
		}
		h := a.history()
		var out []issued
		for i := 0; i < b.Qty; i++ {
			k, exp := makeKey(a.priv, mach, b.Days, i)
			it := issued{Time: time.Now().Format("02/01/2006 15:04"), Name: strings.TrimSpace(b.Name), Machine: label, Expires: exp, Note: strings.TrimSpace(b.Note), Key: k}
			out = append(out, it)
			h = append([]issued{it}, h...)
		}
		j, _ := json.MarshalIndent(h, "", " ")
		if err := writeAtomic(a.historyPath(), j); err != nil {
			fail(w, "Không ghi được lịch sử: "+err.Error())
			return
		}
		jsonOut(w, 200, map[string]any{"keys": out})
	})
	api("/api/history", func(w http.ResponseWriter, r *http.Request) {
		h := a.history()
		if h == nil {
			h = []issued{}
		}
		jsonOut(w, 200, h)
	})
	return mux
}

func main() {
	a := &app{dir: dataDir()}
	tok := make([]byte, 24)
	rand.Read(tok)
	a.token = base64.RawURLEncoding.EncodeToString(tok)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		msgBox("MThanglee KeyGen", "Không mở được cổng cục bộ: "+err.Error())
		return
	}
	a.port = ln.Addr().(*net.TCPAddr).Port
	url := fmt.Sprintf("http://127.0.0.1:%d/?t=%s", a.port, a.token)
	go http.Serve(ln, a.routes())
	if os.Getenv("MTCC_KEYGEN_HEADLESS") == "1" {
		fmt.Println(url)
		select {}
	}
	openWindow(url, a.dir)
}
