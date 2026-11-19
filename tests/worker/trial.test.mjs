// node --test tests/worker/  — Worker bán hàng: POST /trial cấp key dùng thử 3 ngày, mỗi máy một lần
import test from "node:test";
import assert from "node:assert/strict";
import { copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "wk-"));
copyFileSync(join(here, "../../sales-worker/worker.js"), join(dir, "worker.mjs"));
const worker = (await import(join(dir, "worker.mjs"))).default;

const SEED = "11".repeat(32);
const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
function b32dec(s) { s = s.replace(/[^A-Z2-7]/gi, "").toUpperCase(); let bits = 0, val = 0; const o = []; for (const c of s) { val = (val << 5) | B32.indexOf(c); bits += 5; if (bits >= 8) { o.push((val >>> (bits - 8)) & 255); bits -= 8; } } return new Uint8Array(o); }
function b32enc(u) { let bits = 0, val = 0, o = ""; for (const b of u) { val = (val << 8) | b; bits += 8; while (bits >= 5) { o += B32[(val >>> (bits - 5)) & 31]; bits -= 5; } } if (bits > 0) o += B32[(val << (5 - bits)) & 31]; return o; }
const MACH8 = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]);
const t = b32enc(MACH8); const MACHINE = `${t.slice(0, 4)}-${t.slice(4, 8)}-${t.slice(8, 13)}`;
const utcDay = () => { const d = new Date(); return Math.floor((Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) - Date.UTC(2024, 0, 1)) / 86400000); };

function env() { const m = new Map(); return { SALES_SEED_HEX: SEED, SEPAY_APIKEY: "k", TRIALS: { get: async k => m.get(k) ?? null, put: async (k, v) => { m.set(k, v); } } }; }
const post = (e, body, path = "/trial") => worker.fetch(new Request("https://api.cullcollage.com" + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }), e);
function decode(key) { const raw = b32dec(key.replace(/^MTCC-?/, "").replace(/-/g, "")); return { body: raw.slice(0, 14), sig: raw.slice(14) }; }
async function verify(body, sig) {
  const pkcs8 = new Uint8Array(48); pkcs8.set([0x30,0x2e,0x02,0x01,0x00,0x30,0x05,0x06,0x03,0x2b,0x65,0x70,0x04,0x22,0x04,0x20]); pkcs8.set(Uint8Array.from(SEED.match(/../g).map(h => parseInt(h, 16))), 16);
  const priv = await crypto.subtle.importKey("pkcs8", pkcs8, { name: "Ed25519" }, true, ["sign"]);
  const jwk = await crypto.subtle.exportKey("jwk", priv); delete jwk.d; jwk.key_ops = ["verify"];
  const pub = await crypto.subtle.importKey("jwk", jwk, { name: "Ed25519" }, false, ["verify"]);
  const msg = new Uint8Array(19); msg.set([77, 84, 67, 67, 49]); msg.set(body, 5);
  return crypto.subtle.verify("Ed25519", pub, sig, msg);
}

test("cấp key thử mới: serial T, exp = day + 2, đúng máy, chữ ký hợp lệ", async () => {
  const e = env(), day = utcDay();
  const r = await post(e, { machine: MACHINE, day }); assert.equal(r.status, 200);
  const j = await r.json(); assert.equal(j.ok, true); assert.equal(j.again, false);
  const { body, sig } = decode(j.key);
  assert.equal(body[0], 1); assert.equal(body[1], 0x54);
  assert.equal((body[2] << 8) | body[3], day); assert.equal((body[4] << 8) | body[5], day + 2);
  assert.deepEqual([...body.slice(6)], [...MACH8]);
  assert.ok(await verify(body, sig));
});

test("gọi lại cùng máy → đúng key cũ, again=true", async () => {
  const e = env(), day = utcDay();
  const a = await (await post(e, { machine: MACHINE, day })).json();
  const b = await (await post(e, { machine: MACHINE.replace(/-/g, "").toLowerCase(), day: day + 1 })).json();
  assert.equal(b.key, a.key); assert.equal(b.again, true);
});

test("day lệch xa ngày UTC → dùng ngày UTC; lệch 1 ngày → nhận", async () => {
  let j = await (await post(env(), { machine: MACHINE, day: utcDay() + 5 })).json();
  let { body } = decode(j.key); assert.equal((body[2] << 8) | body[3], utcDay());
  j = await (await post(env(), { machine: MACHINE, day: utcDay() + 1 })).json();
  ({ body } = decode(j.key)); assert.equal((body[2] << 8) | body[3], utcDay() + 1);
});

test("mã máy sai → 400", async () => {
  const r = await post(env(), { machine: "ABC", day: utcDay() }); assert.equal(r.status, 400);
});

test("webhook SePay cũ vẫn đòi Authorization", async () => {
  const r = await post(env(), { transferAmount: 500000 }, "/"); assert.equal(r.status, 401);
});

// ---- sửa sau đợt soát cuối
test("đổi bit đệm cuối của mã máy không được thêm lượt thử (I1)", async () => {
  const e = env(), day = utcDay();
  const a = await (await post(e, { machine: MACHINE, day })).json();
  const last = MACHINE.slice(-1), flip = B32[B32.indexOf(last) ^ 1];
  const b = await (await post(e, { machine: MACHINE.slice(0, -1) + flip, day })).json();
  assert.equal(b.again, true); assert.equal(b.key, a.key);
});

test("mã máy toàn số 0 (key dùng mọi máy) bị từ chối ở /trial và webhook (I2)", async () => {
  const r = await post(env(), { machine: "AAAA-AAAA-AAAAA", day: utcDay() }); assert.equal(r.status, 400);
  const w = await worker.fetch(new Request("https://x/", { method: "POST", headers: { "Authorization": "Apikey k", "content-type": "application/json" },
    body: JSON.stringify({ transferType: "in", transferAmount: 500000, content: "MTCCAAAAAAAAAAAAA" }) }), env());
  const j = await w.json(); assert.equal(j.skip, "bad machine");
});

test("trả ngày của máy chủ để app chống vặn lùi đồng hồ (I3)", async () => {
  const j = await (await post(env(), { machine: MACHINE, day: utcDay() })).json();
  assert.equal(j.today, utcDay());
});

test("body null → 400, không CORS (M2, M3)", async () => {
  const r = await worker.fetch(new Request("https://x/trial", { method: "POST", body: "null" }), env());
  assert.equal(r.status, 400); assert.equal(r.headers.get("access-control-allow-origin"), null);
});
