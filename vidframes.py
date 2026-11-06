"""Extract evenly-spaced frames from a video so Win can "watch" it.

Usage: python vidframes.py <video_path> [n_frames] [out_dir]
Prints JPG paths (one per line). Then `read` each frame to see it.
Needs: pip install imageio imageio-ffmpeg pillow
"""
import os
import sys
import math


def main():
    if len(sys.argv) < 2:
        print("usage: python vidframes.py <video> [n_frames=8] [out_dir]")
        return 1
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(path)[0] + "_frames"
    os.makedirs(out, exist_ok=True)

    import imageio.v2 as imageio
    r = imageio.get_reader(path)
    meta = r.get_meta_data()
    fps = meta.get("fps") or 25
    dur = meta.get("duration") or 0
    total = int(dur * fps) if dur else 100
    total = max(total, n)
    idxs = [int(i * total / n) for i in range(n)]

    for j, i in enumerate(idxs):
        try:
            frame = r.get_data(i)
        except Exception:
            continue
        p = os.path.join(out, f"frame_{j:02d}_t{i / fps:.1f}s.jpg")
        imageio.imwrite(p, frame, quality=85)
        print(p)
    r.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
