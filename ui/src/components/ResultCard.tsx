import { useState } from "react";
import { Result, tc, thumbUrl } from "../api";
import Icon from "../icons";

type Props = {
  r: Result;
  selected?: boolean;
  picked?: boolean;
  onClick: () => void;
  compact?: boolean;
};

const AUDIO = /\.(wav|mp3|m4a|aac|flac)$/i;

export default function ResultCard({ r, selected, picked, onClick, compact }: Props) {
  const [noPicture, setNoPicture] = useState(AUDIO.test(r.file)); // voiceovers, music: no frame to show
  const cls = `card${selected ? " sel" : ""}${picked ? " picked" : ""}`;
  const at = r.kind === "said" ? r.start : r.peak ?? r.start;
  return (
    <div className={cls} onClick={onClick} title={r.location}>
      <div className={`thumb${noPicture ? " audio" : ""}`}>
        {noPicture ? (
          <Icon name="audio" size={44} />
        ) : (
          <img src={thumbUrl(r, compact ? 240 : 360)} loading="lazy" alt="" onError={() => setNoPicture(true)} />
        )}
        <span className="tc">{tc(at)}</span>
        <span className="corner">
          {r.remote && <span className="badge blue">B2</span>}
          {picked && <span className="badge ok">Picked</span>}
        </span>
      </div>
      <div className="card-body">
        <div className="row">
          <span className="card-file ellipsis grow">{r.file}</span>
          {r.kind === "said" ? (
            <span className="score">{Math.round(r.score * 100)}%</span>
          ) : (
            <span className={`badge ${r.label === "strong" ? "ok" : r.label === "good" ? "blue" : ""}`}>{r.label}</span>
          )}
        </div>
        {r.kind === "said" ? (
          <div className="card-text">“{r.text}”</div>
        ) : (
          !compact && <div className="card-text muted">Shot {tc(r.start)} – {tc(r.end)}</div>
        )}
        {r.takes && r.takes > 1 ? (
          <span className="hint">
            take {r.take} of {r.takes} in this clip
          </span>
        ) : null}
      </div>
    </div>
  );
}
