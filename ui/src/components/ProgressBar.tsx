export default function ProgressBar({ n, total, running }: { n: number; total: number; running: boolean }) {
  const pct = total > 0 ? Math.min(100, (n / total) * 100) : 0;
  return (
    <div className={`progress${running && total === 0 ? " indet" : ""}`}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}
