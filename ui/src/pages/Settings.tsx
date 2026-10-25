import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";

const PRESETS: { id: string; name: string; desc: string }[] = [
  { id: "auto", name: "Automatic", desc: "Picks by graphics card. On this PC that means High." },
  { id: "high", name: "High", desc: "Most accurate. NVIDIA card with 12 GB+ (this PC's RTX 5070 Ti)." },
  { id: "mid", name: "Mid", desc: "6–8 GB NVIDIA cards. Nearly as accurate, lighter models." },
  { id: "low", name: "Low", desc: "Any laptop, no graphics card. Slower to index and less accurate." },
];

export default function SettingsPage() {
  const { status, toast, refresh } = useApp();
  const [tier, setTier] = useState("auto");
  const [auto, setAuto] = useState("");
  const [keyId, setKeyId] = useState("");
  const [appKey, setAppKey] = useState("");
  const [test, setTest] = useState<string | null>(null);
  const [bucket, setBucket] = useState("");

  useEffect(() => setBucket(status?.b2_bucket ?? ""), [status?.b2_bucket]);

  const saveBucket = async () => {
    await api.setBucket(bucket);
    refresh();
    toast("Bucket saved");
  };

  useEffect(() => {
    api.settings().then((s) => {
      setTier(s.tier);
      setAuto(s.auto_tier);
    });
  }, []);

  const choose = async (t: string) => {
    setTier(t);
    await api.setTier(t);
    toast("Saved. Applies to folders indexed from now on; existing folders keep their preset.");
  };

  const saveKey = async () => {
    try {
      await api.setKey(keyId, appKey);
      setKeyId("");
      setAppKey("");
      refresh();
      toast("Key saved");
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  const testKey = async () => {
    setTest("Connecting…");
    try {
      const r = await api.b2ls(`b2://${status?.b2_bucket}/`);
      setTest(`Connected. ${status?.b2_bucket} has ${r.folders.length} top-level folder(s): ${r.folders.slice(0, 6).join(", ")}`);
    } catch (e) {
      setTest(`Failed: ${(e as Error).message}`);
    }
  };

  return (
    <div className="page">
      <div className="results scroll pad col" style={{ gap: 18 }}>
        <h1>Settings</h1>

        <div className="card-block">
          <h2>This PC</h2>
          <div className="kv">
            <span className="k">GPU</span>
            <span>{status?.gpu ?? "None usable (CPU only)"}</span>
            <span className="k">Data</span>
            <span className="mono">{status?.data_dir}</span>
            <span className="k">Models</span>
            <span>{status?.ready ? "Loaded" : "Loading…"}</span>
          </div>
        </div>

        <div className="card-block">
          <h2>Indexing preset</h2>
          {PRESETS.map((p) => (
            <label key={p.id} className={`radio${tier === p.id ? " on" : ""}`}>
              <input type="radio" name="tier" checked={tier === p.id} onChange={() => choose(p.id)} />
              <span className="col" style={{ gap: 2 }}>
                <span className="strong">
                  {p.name}
                  {p.id === "auto" && auto ? ` (${auto})` : ""}
                </span>
                <span className="hint">{p.desc}</span>
              </span>
            </label>
          ))}
        </div>

        <div className="card-block">
          <h2>Backblaze</h2>
          <div className="row">
            <span className={`dot ${status?.b2_key.set ? "ok" : ""}`} />
            {status?.b2_key.set ? `Key set (…${status.b2_key.key_id_tail})` : "No key yet"}
            {status?.b2_key.set && status.b2_bucket && (
              <button className="btn sm" onClick={testKey}>
                Test connection
              </button>
            )}
          </div>
          {test && <span className={test.startsWith("Failed") ? "error small" : "small"}>{test}</span>}
          <div className="row">
            <span className="muted" style={{ width: 52 }}>Bucket</span>
            <input
              className="input"
              style={{ width: 240 }}
              placeholder="bucket name (as shown in Cyberduck)"
              value={bucket}
              onChange={(e) => setBucket(e.target.value)}
            />
            <button className="btn" disabled={bucket.trim() === (status?.b2_bucket ?? "")} onClick={saveBucket}>
              Save
            </button>
          </div>
          <span className="hint">
            Needs a <b>read-only</b> application key for that bucket: Backblaze website › Application Keys › Add a New
            Application Key › the bucket, Read Only. It's stored in plain text on this PC (
            <span className="mono">backblaze.json</span>), which is why it should be read-only.
          </span>
          <div className="row">
            <input className="input" style={{ width: 240 }} placeholder="keyID" value={keyId} onChange={(e) => setKeyId(e.target.value)} />
            <input
              className="input grow"
              type="password"
              placeholder="applicationKey"
              value={appKey}
              onChange={(e) => setAppKey(e.target.value)}
              autoComplete="off"
            />
            <button className="btn primary" disabled={!keyId.trim() || !appKey.trim()} onClick={saveKey}>
              Save key
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
