// Premiere side of the Scrubless panel (ExtendScript). Returns "ok:..." or "error:..." strings
// (this ExtendScript has no JSON object).

var TICKS = 254016000000;

function _norm(p) {
    return String(p).replace(/\//g, "\\").toLowerCase();
}

function _findByPath(parent, path) {
    for (var i = 0; i < parent.children.numItems; i++) {
        var c = parent.children[i];
        if (c.type === ProjectItemType.BIN) {
            var hit = _findByPath(c, path);
            if (hit) return hit;
        } else if (c.getMediaPath && _norm(c.getMediaPath()) === path) {
            return c;
        }
    }
    return null;
}

function _bin(name) {
    var root = app.project.rootItem;
    for (var i = 0; i < root.children.numItems; i++) {
        if (root.children[i].type === ProjectItemType.BIN && root.children[i].name === name) return root.children[i];
    }
    root.createBin(name);
    for (var k = 0; k < root.children.numItems; k++) {
        if (root.children[k].type === ProjectItemType.BIN && root.children[k].name === name) return root.children[k];
    }
    return root;
}

function _item(path) {
    var key = _norm(path);
    var item = _findByPath(app.project.rootItem, key);
    if (item) return item;
    var bin = _bin("Scrubless");
    app.project.importFiles([path], true, bin, false);
    return _findByPath(bin, key);
}

function _free(track, from, to) {
    if (!track) return true;
    for (var i = 0; i < track.clips.numItems; i++) {
        var c = track.clips[i];
        if (c.start.seconds < to && c.end.seconds > from) return false;
    }
    return true;
}

// mode "source": open the take in the Source Monitor with in/out set.
// mode "place": also drop it at the playhead on the first video track (and matching audio track)
// that is empty for the clip's length, so nothing on the timeline gets overwritten.
function scrublessPlace(path, inSec, outSec, mode, audioOnly) {
    try {
        if (!app.project) return "error:Open a Premiere project first.";
        var item = _item(path);
        if (!item) return "error:Premiere couldn't import " + path;
        item.setInPoint(inSec, 4);
        item.setOutPoint(outSec, 4);
        if (mode === "source") {
            app.sourceMonitor.openProjectItem(item);
            return "ok:Opened in the Source Monitor";
        }
        var seq = app.project.activeSequence;
        if (!seq) return "error:Open a sequence first.";
        var pos = seq.getPlayerPosition().seconds;
        var end = pos + (outSec - inSec);
        var v = seq.videoTracks, a = seq.audioTracks;
        var n = audioOnly ? a.numTracks : v.numTracks;
        for (var i = 0; i < n; i++) {
            var vt = audioOnly ? null : v[i];
            var at = i < a.numTracks ? a[i] : null;
            if (_free(vt, pos, end) && _free(at, pos, end)) {
                (audioOnly ? at : vt).overwriteClip(item, pos);
                seq.setPlayerPosition(String(Math.round(end * TICKS)));
                return "ok:Placed on " + (audioOnly ? "A" : "V") + (i + 1);
            }
        }
        return "error:No empty track at the playhead. Add a track or move the playhead.";
    } catch (e) {
        return "error:" + e.toString();
    }
}
